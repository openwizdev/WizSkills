import argparse
import datetime
import fnmatch
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
LINKS = HERE.parent / 'check-links.sh'
RELIES = HERE.parent / 'check-relies.sh'
CHECK_APPROVAL = HERE / 'check-approval.sh'
GRILL = re.compile(r'https://github\.com/[A-Za-z0-9-]+/[A-Za-z0-9_.-]+/(issues|pull)/[1-9][0-9]*'
                   r'#issuecomment-[1-9][0-9]*')
REPO = re.compile(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+')
TICKET_LINE = re.compile(r'ticket #([1-9][0-9]*) blocked-by (none|#[1-9][0-9]*(?: #[1-9][0-9]*)*) '
                         r'body sha256 ([0-9a-f]{64}) title (.+)')
TICKED = (re.compile(rb'^([ \t]*[-*+][ \t]+)\[[xX]\]$'), re.compile(rb'^([ \t]*[-*+][ \t]+)\[[xX]\]([ \t\r])'))


class Unreadable(Exception):
    pass


def unticked_sha256(text):
    lines = (text + '\n').encode().split(b'\n')
    out = []
    for line in lines:
        line = TICKED[0].sub(rb'\1[ ]', line)
        line = TICKED[1].sub(rb'\1[ ]\2', line)
        out.append(line)
    return hashlib.sha256(b'\n'.join(out)).hexdigest()


def visible_lines(body):
    out = []
    fence = None
    in_comment = False
    for line in body.replace('\r\n', '\n').split('\n'):
        if fence is not None:
            if re.fullmatch(rf' {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}[ \t]*', line):
                fence = None
            continue
        if not in_comment:
            m = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
            if m and (m.group(1)[0] == '~' or '`' not in m.group(2)):
                fence = m.group(1)
                continue
        pos = 0
        parts = []
        while pos < len(line):
            if in_comment:
                end = line.find('-->', pos)
                if end == -1:
                    pos = len(line)
                else:
                    in_comment = False
                    pos = end + 3
            else:
                start = line.find('<!--', pos)
                if start == -1:
                    parts.append(line[pos:])
                    pos = len(line)
                else:
                    parts.append(line[pos:start])
                    in_comment = True
                    pos = start + 4
        if parts:
            out.append(''.join(parts))
    return out


def section(body, heading):
    lines = visible_lines(body)
    for i, line in enumerate(lines):
        if line.rstrip() == '## ' + heading:
            rest = []
            for after in lines[i + 1:]:
                if after.startswith('## '):
                    break
                rest.append(after)
            return rest
    return None


def human(ticket):
    return section(ticket['body'], 'Done by') is not None


def owned(ticket, default_repo):
    lines = section(ticket['body'], 'Owned paths')
    if lines is None:
        raise ValueError('no `## Owned paths` section')
    bullets = [line[2:] for line in lines if line.startswith('- ')]
    if not bullets:
        raise ValueError('no owned path bullet')
    out = []
    for bullet in bullets:
        repos = re.findall(r'\bin `([^`]+)`', bullet)
        repo = default_repo
        if repos:
            if len(repos) != 1 or not REPO.fullmatch(repos[0]):
                raise ValueError(f'unclear repository in "{bullet}"')
            repo = repos[0]
        paths = [p for p in re.findall(r'`([^`]+)`', bullet) if p not in repos]
        if not paths:
            raise ValueError(f'a bullet names no exact path: "{bullet}"')
        for path in paths:
            parts = path.rstrip('/').split('/')
            if path.startswith('/') or any(part in ('', '.', '..') for part in parts) or ' ' in path:
                raise ValueError(f'`{path}` is not a repository-relative path')
            out.append((repo.lower(), path, '(shared' in bullet))
    return out


def segments_overlap(p, q):
    if '[' in p or '[' in q:
        return True
    m, n = len(p), len(q)
    stack, seen = [(0, 0)], {(0, 0)}
    while stack:
        i, j = stack.pop()
        if i == m and j == n:
            return True
        next_states = []
        if i < m and p[i] == '*':
            next_states.append((i + 1, j))
            if j < n and q[j] != '*':
                next_states.append((i, j + 1))
        if j < n and q[j] == '*':
            next_states.append((i, j + 1))
            if i < m and p[i] != '*':
                next_states.append((i + 1, j))
        if i < m and j < n and p[i] != '*' and q[j] != '*':
            if p[i] == '?' or q[j] == '?' or p[i] == q[j]:
                next_states.append((i + 1, j + 1))
        for state in next_states:
            if state not in seen:
                seen.add(state)
                stack.append(state)
    return False


def overlap(a, b):
    x, y = a.rstrip('/').split('/'), b.rstrip('/').split('/')
    for p, q in zip(x, y):
        if p == '**' or q == '**':
            return True
        if not segments_overlap(p, q):
            return False
    return True


def contains(own, path):
    x, y = own.rstrip('/').split('/'), path.split('/')
    longest = len(y) - 1 if own.endswith('/') else len(y)
    return len(x) <= longest and all(fnmatch.fnmatchcase(q, p) for p, q in zip(x, y))


def relies_items(body):
    lines = [line for line in visible_lines(body) if line.startswith('**Relies on:**')]
    found = re.findall(r'`([^`]+)`(?: in `([^`]+)`)?', lines[0]) if len(lines) == 1 else []
    return [(repo.lower() or None, path) for path, repo in found]


def relies_paths(body):
    return [path for _, path in relies_items(body)]


REMOTE_PATH = re.compile(r'[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*')
FILE_QUERY = ('query($owner: String!, $name: String!, $path: String!) { repository(owner: $owner, name: $name) '
              '{ nameWithOwner defaultBranchRef { target { ... on Commit { file(path: $path) { mode } } } } } }')
MODES = {0o100644: True, 0o100755: True, 0o040000: False, 0o120000: False, 0o160000: False}
NOT_FOUND = {'type': 'NOT_FOUND', 'path': ['repository', 'defaultBranchRef', 'target', 'file']}


def on_default_branch(repo, path):
    if not REPO.fullmatch(repo) or not REMOTE_PATH.fullmatch(path) or {'.', '..'} & set(path.split('/')):
        return False
    owner, name = repo.split('/')
    out = subprocess.run(['gh', 'api', 'graphql', '-f', f'owner={owner}', '-f', f'name={name}', '-f', f'path={path}',
                          '-f', f'query={FILE_QUERY}'], capture_output=True, text=True)
    try:
        answer = json.loads(out.stdout)
        found = answer['data']['repository']
        entry, errors = found['defaultBranchRef']['target']['file'], answer.get('errors', [])
        same = found['nameWithOwner'].lower() == repo.lower()
    except (ValueError, TypeError, KeyError, AttributeError):
        same = False
    if same and entry is None and out.returncode != 0 and isinstance(errors, list) and errors and all(
            isinstance(e, dict) and {k: e.get(k) for k in NOT_FOUND} == NOT_FOUND for e in errors):
        return False
    if (same and out.returncode == 0 and 'errors' not in answer and isinstance(entry, dict)
            and type(entry.get('mode')) is int and entry['mode'] in MODES):
        return MODES[entry['mode']]
    raise Unreadable(f'cannot read `{path}` in `{repo}` from its default branch')


def read_revision(text, graph):
    lines = text.split('\n')
    if lines[-1:] != [''] or len(lines) < 3 or lines[0] != 'plan-graph revision v2':
        return ['not revision.sh version 2 text']
    spec = graph['source'].get('spec')
    if not re.fullmatch(rf'spec #{spec} body sha256 [0-9a-f]{{64}}', lines[1]):
        return [f'its spec line is not spec #{spec}\'s']
    named = {}
    for line in lines[2:-1]:
        m = TICKET_LINE.fullmatch(line)
        if not m or int(m[1]) in named:
            return [f'unreadable or repeated line: "{line[:60]}"']
        named[int(m[1])] = m
    tickets = {t['number']: t for t in graph['tickets']}
    why = []
    if sorted(named) != sorted(tickets):
        why.append('its tickets are not the graph\'s tickets')
    for n in sorted(set(named) & set(tickets)):
        m, t = named[n], tickets[n]
        blockers = ' '.join(f'#{b}' for b in sorted(b['number'] for b in t['blocked_by'])) or 'none'
        if m[2] != blockers:
            why.append(f'#{n}\'s blockers differ')
        if m[4] != t['title']:
            why.append(f'#{n}\'s title differs')
        if m[3] != unticked_sha256(t['body']):
            why.append(f'#{n}\'s body differs')
    return why


def check_links(graph_text):
    out = subprocess.run(['sh', str(LINKS), '--graph', '-'], input=graph_text,
                         capture_output=True, text=True)
    if out.returncode == 2:
        raise Unreadable('check-links.sh could not read the graph: ' + out.stderr.strip()[:200])
    if out.returncode != 0:
        return [line.strip() for line in out.stderr.splitlines() if line.strip()] or ['check-links.sh refused']
    return []


def check_checkpoints(spec_text, graph, revision):
    spec = graph['source']['spec']
    body = json.loads(spec_text)
    if not isinstance(body, dict) or not isinstance(body.get('body'), str):
        raise Unreadable(f'spec #{spec} has no body')
    if revision.split('\n')[1] != f'spec #{spec} body sha256 {unticked_sha256(body["body"])}':
        return [f"spec #{spec}'s body differs from the revision's"]
    out = subprocess.run(['sh', str(CHECK_APPROVAL), '--checkpoints', str(spec)], input=json.dumps(body),
                         capture_output=True, text=True)
    why = [line.strip().removeprefix('check-approval.sh: ') for line in out.stderr.splitlines() if line.strip()]
    if out.returncode == 2:
        raise Unreadable('; '.join(why)[:200] or 'check-approval.sh could not read the spec')
    return (why or ['check-approval.sh refused']) if out.returncode != 0 else []


def run_relies(root, body, args):
    return subprocess.run(['sh', str(RELIES), '--root', str(root), *args], input=body, capture_output=True, text=True)


def check_relies(tickets, owners, checkouts):
    why = []
    with tempfile.TemporaryDirectory() as empty_root:
        for t in tickets:
            blockers = [b['number'] for b in t['blocked_by']]
            repos = {repo for repo, _, _ in owners.get(t['number'], [])}
            planned, unplanned, vouched, remote = [], [], [], []
            for elsewhere, path in relies_items(t['body']):
                if elsewhere is not None:
                    vouched.append((elsewhere, path))
                    if not any(repo == elsewhere and contains(own, path)
                               for b in blockers for repo, own, _ in owners.get(b, [])):
                        remote.append((elsewhere, path))
                    continue
                if len(repos) == 1 and any(repo in repos and contains(own, path)
                                           for b in blockers for repo, own, _ in owners.get(b, [])):
                    planned += ['--planned', path]
                else:
                    unplanned.append(path)
            checkout = checkouts.get(next(iter(repos))) if len(repos) == 1 else None
            relies_root = checkout if checkout is not None else empty_root
            checked = planned if checkout is not None else planned + [a for p in unplanned for a in ('--planned', p)]
            out = run_relies(relies_root, t['body'], checked + [a for item in vouched for a in ('--elsewhere', *item)])
            if out.returncode == 0 and remote:
                missing = {item for item in remote if not on_default_branch(*item)}
                if missing:
                    out = run_relies(relies_root, t['body'],
                                     checked + [a for item in vouched if item not in missing
                                                for a in ('--elsewhere', *item)])
            if out.returncode != 0:
                why.append(f'#{t["number"]}: ' + (out.stderr.strip().splitlines() or ['refused'])[-1])
            elif unplanned and checkout is None:
                where = f'`{next(iter(repos))}`' if len(repos) == 1 else 'more than one repository'
                why.append(f'#{t["number"]}: Relies on: `{unplanned[0]}` is in {where}, which has no supplied checkout; '
                           'a direct blocker there must own it')
    return why


SIZES_SINCE = '2026-11-23T00:00:00Z'


def check_sizes(tickets, spec_text):
    spec = json.loads(spec_text)
    created = spec.get('createdAt') if isinstance(spec, dict) else None
    if not isinstance(created, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', created):
        raise Unreadable('the spec has no createdAt')
    why, counts = [], {'S': 0, 'M': 0, 'L': 0}
    for t in tickets:
        parent = section(t['body'], 'Parent') or []
        sizes = re.findall(r'\bSize: ([A-Za-z]+)\b', '\n'.join(parent))
        if len(sizes) != 1 or sizes[0] not in counts:
            why.append(f'#{t["number"]} needs exactly one `Size: S`, `M` or `L` in Parent')
            continue
        counts[sizes[0]] += 1
        if created < SIZES_SINCE:
            continue
        if sizes[0] == 'L':
            why.append(f'#{t["number"]} is `Size: L`; split it into tickets of S or M')
        elif sizes[0] == 'M' and not any(re.fullmatch(r'Why M: *\S.*', line.rstrip()) for line in parent):
            why.append(f'#{t["number"]} is `Size: M` without a `Why M: <reason it can\'t split>` line in Parent')
    return why, counts


def chain_width(after, planned, done):
    level, indegree = {}, {n: 0 for n in after}
    for n in after:
        for m in after[n]:
            indegree[m] += 1
    ready = sorted(n for n in after if indegree[n] == 0)
    for n in ready:
        level[n] = 0 if n in done else 1
    while ready:
        n = ready.pop(0)
        for m in sorted(after[n]):
            level[m] = max(level.get(m, 0), level[n] + (0 if m in done else 1))
            indegree[m] -= 1
            if indegree[m] == 0:
                ready.append(m)
    unreached = sorted(n for n in after if indegree[n] > 0)
    waves = {}
    for n in planned:
        if n not in done and n in level:
            waves[level[n]] = waves.get(level[n], 0) + 1
    return max(level.values(), default=0), max(waves.values(), default=0), unreached


FILE_PATH = re.compile(r'(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+/?')


def file_link_files(body, blocker):
    lines = [line.rstrip(' \t') for line in section(body, 'Links') or []]
    found = [line for line in lines if re.match(rf'- #{blocker} (real|file):', line)]
    if len(found) != 1 or not found[0].startswith(f'- #{blocker} file:'):
        return None
    files = [p for p in re.findall(r'`([^`]*)`', found[0])
             if FILE_PATH.fullmatch(p) and not any(part in ('.', '..') for part in p.rstrip('/').split('/'))]
    return files or None


def soft_link(ticket, blocker, default_repo):
    if ticket['state'] != 'OPEN' or human(ticket) or blocker is None or human(blocker):
        return False
    files = file_link_files(ticket['body'], blocker['number'])
    try:
        mine, theirs = owned(ticket, default_repo), owned(blocker, default_repo)
    except ValueError:
        return False
    if files is None:
        return False
    inputs = relies_paths(ticket['body'])
    if any(overlap(i, p) for i in inputs for p in files + [path for _, path, _ in theirs]):
        return False
    return not any(ra == rb and overlap(pa, pb) and not (sa and sb)
                   for ra, pa, sa in mine for rb, pb, sb in theirs)


def check_width(graph):
    numbers = {t['number'] for t in graph['tickets']}
    tickets = {t['number']: t for t in graph['tickets']}
    after = {n: set() for n in numbers}
    hard = {n: set() for n in numbers}
    done = {t['number'] for t in graph['tickets'] if t['state'] != 'OPEN'}
    for t in graph['tickets']:
        for b in t['blocked_by']:
            after.setdefault(b['number'], set()).add(t['number'])
            hard.setdefault(b['number'], set())
            if not soft_link(t, tickets.get(b['number']), graph['repo']):
                hard[b['number']].add(t['number'])
            if b['number'] not in numbers and b['state'] != 'OPEN':
                done.add(b['number'])
    _, _, unreached = chain_width(after, numbers, done)
    chain, widest, _ = chain_width(hard, numbers, done)
    if unreached:
        return [f'a cycle: {" ".join(f"#{n}" for n in unreached)} can never start'], 0, 0
    why = []

    def reaches(start, goal, skip):
        stack, seen = [m for m in after[start] if m != skip], set()
        while stack:
            n = stack.pop()
            if n == goal:
                return True
            if n not in seen:
                seen.add(n)
                stack.extend(after[n])
        return False

    for b in sorted(numbers):
        for t in sorted(after[b]):
            if reaches(b, t, skip=t):
                why.append(f'the arrow #{b} -> #{t} is implied by another chain; drop it')
    return why, chain, widest


FLAT_SINCE = '2026-11-28T00:00:00Z'
MAX_CHAIN = 5
MAX_RATIO = (2, 3)
RATIO_FLOOR = 3
WHY_DEEP = re.compile(r'Why deep: *(\S.*)')


def flat_spec(spec_text):
    spec = json.loads(spec_text)
    created = spec.get('createdAt') if isinstance(spec, dict) else None
    if not isinstance(created, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', created):
        raise Unreadable('the spec has no createdAt')
    return created >= FLAT_SINCE, spec.get('body') if isinstance(spec.get('body'), str) else ''


def check_depth(graph, spec_text, chain):
    flat, spec_body = flat_spec(spec_text)
    count = sum(1 for t in graph['tickets'] if t['state'] == 'OPEN')
    deep = chain > MAX_CHAIN or (chain > RATIO_FLOOR and chain * MAX_RATIO[1] > count * MAX_RATIO[0])
    if not flat or not deep:
        return []
    named = {t['number'] for t in graph['tickets']} | {b['number'] for t in graph['tickets'] for b in t['blocked_by']}
    for line in visible_lines(spec_body):
        m = WHY_DEEP.fullmatch(line.rstrip())
        if m and {int(n) for n in re.findall(r'#([1-9][0-9]*)\b', m[1])} & named:
            return []
    return [f'the critical chain is {chain} for {count} open tickets, over the limit of {MAX_CHAIN} or of '
            f'{MAX_RATIO[0]}/{MAX_RATIO[1]} of the open tickets once over {RATIO_FLOOR}; cut a contract-first '
            'ticket that both sides wait on, or add a `Why deep: <the real needs, naming their tickets>` line '
            'to the spec']


REASON_WORD = re.compile(r"[A-Za-z]+(?:['-][A-Za-z]+)*'?")
FILLER = set('a an the and or nor its their this these those of to for from with in on at by as per plus both each every '
             'all any it'.split())
INTERFACE = set('command subcommand flag option argument form format type schema file stub interface signature field '
                'path name header shape exit code answer output input json'.split())
CLAUSE = re.compile(r',?\s+(?:which|that|whose|who)\b(.*)$')
EXTENDS = re.compile(r'\b(?:extends?|extending|modifies|changes|builds on)\b')


def behaviour_words(reason):
    text = re.sub(r'`[^`]*`', ' ', reason.strip())
    m = CLAUSE.search(text)
    head, rest = (text[:m.start()], m[1]) if m else (text, '')
    words = []
    for piece in head.split():
        word = piece.strip('()[]{}"\',.;:!?').lower()
        base = word.removesuffix("'s").rstrip("'")
        if not REASON_WORD.fullmatch(word) or base in FILLER:
            continue
        if base in INTERFACE or (base.endswith('s') and base[:-1] in INTERFACE):
            continue
        words.append(base)
    return words, bool(EXTENDS.search(rest))


def contract_first(ticket):
    return ticket is not None and ticket['title'].rstrip().lower().endswith(', first')


def check_reasons(graph, agents, spec_text):
    if not flat_spec(spec_text)[0]:
        return []
    tickets = {t['number']: t for t in graph['tickets']}
    repo = re.escape(graph['repo'])
    why = []
    for t in agents:
        if 'live check' in t['title'].lower():
            continue
        open_blockers = {b['number'] for b in t['blocked_by'] if b['state'] == 'OPEN'}
        for line in section(t['body'], 'Links') or []:
            m = re.fullmatch(rf'- (?:(?i:{repo}))?#([1-9][0-9]*) real:(.*)', line.rstrip(' \t'))
            if not m or int(m[1]) not in open_blockers or contract_first(tickets.get(int(m[1]))):
                continue
            words, extends = behaviour_words(m[2])
            if not words and not extends:
                why.append(f'#{t["number"]}: the real line for #{m[1]} names only an interface, not the behaviour '
                           f'#{t["number"]} needs; name that behaviour, or say the ticket extends #{m[1]}\'s code, '
                           'or block on a contract-first ticket instead')
    return why


def check_owned(graph, agents):
    why, owners = [], {}
    for t in agents:
        try:
            owners[t['number']] = owned(t, graph['repo'])
        except ValueError as e:
            why.append(f'#{t["number"]}: {e}')
    before = {t['number']: {b['number'] for b in t['blocked_by']} for t in graph['tickets']}

    def ordered(a, b):
        stack, seen = list(before.get(b, ())), set()
        while stack:
            n = stack.pop()
            if n == a:
                return True
            if n not in seen:
                seen.add(n)
                stack.extend(before.get(n, ()))
        return False

    numbers = sorted(owners)
    for i, a in enumerate(numbers):
        for b in numbers[i + 1:]:
            if ordered(a, b) or ordered(b, a):
                continue
            for repo_a, path_a, shared_a in owners[a]:
                for repo_b, path_b, shared_b in owners[b]:
                    if repo_a == repo_b and overlap(path_a, path_b) and not (shared_a and shared_b):
                        why.append(f'#{a} and #{b} can run at once and both own `{path_a}` / `{path_b}`')
    return why, owners


def record(args, graph, revision, counts):
    links, relies, sizes, chain, widest, owned_count = counts
    rows = []
    for t in sorted(graph['tickets'], key=lambda t: t['number']):
        blockers = ' '.join(f'#{b}' for b in sorted(b['number'] for b in t['blocked_by'])) or 'none'
        label = 'none' if t['state'] != 'OPEN' else 'ready-for-human' if human(t) else 'ready-for-agent'
        title = t['title'].replace('|', '\\|')
        rows.append(f'| #{t["number"]} | {title} | {blockers} | {label} |')
    fingerprint = hashlib.sha256(revision.encode()).hexdigest()
    parts = [
        f'**Machine plan approval, {args.date}, revision {args.number}:** '
        'links, relies, sizes, width and owned paths passed.',
        f'Grill confirmed: {args.grill}',
        '',
        f'Checks: {len(graph["tickets"])} tickets; links {links}; relies {relies}; '
        f'sizes S {sizes["S"]}, M {sizes["M"]}, L {sizes["L"]}; width: chain {chain}, widest {widest}; '
        f'owned paths {owned_count}.',
        '',
    ]
    if args.number > 1:
        parts += [f'Changed since revision {args.number - 1}: {args.changed.rstrip(".")}.', '']
    parts += ['| Ticket | Title | Blocked by | Label |', '| --- | --- | --- | --- |', *rows, '',
              f'Fingerprint: `{fingerprint}`', '',
              '<details><summary>Revision text</summary>', '', '```text']
    return '\n'.join(parts) + '\n' + revision + '```\n\n</details>\n'


DESCRIPTION = 'The machine plan approval (#1339, J202): check a plan graph and print its record.'


def parse_checkouts(items):
    out = {}
    for item in items:
        repo, sep, path = item.partition('=')
        if not sep or not REPO.fullmatch(repo) or not path:
            return None
        folder = Path(path)
        if not folder.is_dir():
            return None
        key = repo.lower()
        if key in out:
            return None
        out[key] = folder.resolve()
    return out


def main():
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument('--graph', type=Path, required=True)
    parser.add_argument('--revision', type=Path, required=True)
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--grill', required=True)
    parser.add_argument('--number', type=int, required=True)
    parser.add_argument('--changed')
    parser.add_argument('--date', default=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d'))
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--checkout', action='append', default=[])
    args = parser.parse_args()
    extra_checkouts = parse_checkouts(args.checkout)
    if (not GRILL.fullmatch(args.grill) or args.number < 1 or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', args.date)
            or (args.number > 1) != bool(args.changed and args.changed.strip())
            or (args.changed and '\n' in args.changed) or not args.root.is_dir() or extra_checkouts is None):
        print('approve: usage: a grill confirmation comment URL, revision number >= 1, a YYYY-MM-DD date, '
              'a root folder, optional --checkout OWNER/REPO=DIR folders (one per repo), '
              'and --changed exactly when the number is above 1', file=sys.stderr)
        return 2
    try:
        graph_text = args.graph.read_text(encoding='utf-8')
        revision = args.revision.read_text(encoding='utf-8')
        spec_text = args.spec.read_text(encoding='utf-8')
        graph = json.loads(graph_text)
        if (not isinstance(graph, dict) or graph.get('kind') != 'graph' or not isinstance(graph.get('tickets'), list)
                or not graph['tickets'] or not isinstance(graph.get('source'), dict)):
            raise Unreadable('not a graph read')
        stale = read_revision(revision, graph)
        if stale:
            for why in stale:
                print(f'approve: revision: {why}', file=sys.stderr)
            return 1
        failures = [('links', why) for why in check_links(graph_text)]
        open_tickets = [t for t in graph['tickets'] if t['state'] == 'OPEN']
        agents = [t for t in open_tickets if not human(t)]
        failures += [('links', why) for why in check_reasons(graph, agents, spec_text)]
        owned_why, owners = check_owned(graph, agents)
        checkouts = {graph['repo'].lower(): args.root.resolve(), **extra_checkouts}
        failures += [('relies', why) for why in check_relies(agents, owners, checkouts)]
        size_why, sizes = check_sizes(open_tickets, spec_text)
        failures += [('sizes', why) for why in size_why]
        width_why, chain, widest = check_width(graph)
        failures += [('width', why) for why in width_why]
        failures += [('width', why) for why in check_depth(graph, spec_text, chain)]
        failures += [('owned paths', why) for why in owned_why]
        failures += [('checkpoints', why) for why in check_checkpoints(spec_text, graph, revision)]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, Unreadable) as e:
        print(f'approve: unreadable input: {e}', file=sys.stderr)
        return 2
    if failures:
        for check, why in failures:
            print(f'approve: {check}: {why}', file=sys.stderr)
        return 1
    links = sum(len(t['blocked_by']) for t in open_tickets)
    sys.stdout.write(record(args, graph, revision, (links, len(agents), sizes, chain, widest, len(owners))))
    return 0


if __name__ == '__main__':
    sys.exit(main())
