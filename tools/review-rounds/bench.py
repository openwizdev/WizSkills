#!/usr/bin/env python3
import argparse
import json
import math
import re
import statistics
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

RECORD_AUTHORS = frozenset({'openwiz[bot]', 'jparker2006'})
CHECKS = ('Spec', 'Sweep', 'Standards')
FINDING = re.compile(r'^\s*[-*]\s+\*\*R[0-9]+ \[blocking\]\*\* `[^`\n]+`[^\n]*?\((Spec|Sweep|Standards)\)', re.M)
WORD = re.compile(r'VERDICT:\s*([A-Z]+)')
LATE = re.compile(r'^\s*[-*]\s+\*\*R[0-9]+ \[blocking\]\*\* `([^`\n]+)`[^\n]*?\((?:Spec|Sweep|Standards)\)', re.M)
HEAD = re.compile(r'VERDICT:\s*[A-Z]+ at ([0-9a-f]{7,40})\b')
PLACE = re.compile(r'(.+):([0-9]+)(?:-([0-9]+))?')
HUNK = re.compile(r'^@@ -[0-9]+(?:,[0-9]+)? \+([0-9]+)(?:,([0-9]+))? @@', re.M)
GIT_READS = ('diff', 'cat-file')
WITHDRAWN = re.compile(r'^\s*[-*]\s+\*\*(R[0-9]+) \[blocking\]\*\* withdrawn:', re.M)
POLISH_ISSUE = re.compile(r'^\s*[-*]\s+\*\*R[0-9]+ \[polish\]\*\*[^\n]*?\bPolish issue: #([0-9]+)\b', re.M)
POLISH_TITLE = '(polish for #'
TEST_PATH = re.compile(r'(?:^|/)(?:tests?|__tests__|testdata|fixtures)/|(?:^|/)test_[^/]*$|[_.](?:test|spec)\.[^/]+$')
DUE = timedelta(days=7)
SIZE = re.compile(r'Size: ([SML])\.')
BANDS = (('under 300', 0, 300), ('300-599', 300, 600), ('600+', 600, None),
         ('600-999', 600, 1000), ('1000+', 1000, None))
SEARCH_CAP = 1000
PAGE = 100
SEARCH_PAGE = 40

COMMENT_NODE = 'author { login __typename } createdAt body'
ISSUE_NODE = 'body repository { nameWithOwner }'
CONNECTIONS = {'comments': COMMENT_NODE, 'closingIssuesReferences': ISSUE_NODE}
PR_FIELDS = ('number title createdAt mergedAt additions deletions changedFiles baseRefOid headRefOid '
             + ' '.join('%s(first: %d) { pageInfo { hasNextPage endCursor } nodes { %s } }' % (k, PAGE, v)
                        for k, v in CONNECTIONS.items()))
SEARCH = ('query($q: String!, $after: String) { search(type: ISSUE, query: $q, first: %d, after: $after) '
          '{ issueCount pageInfo { hasNextPage endCursor } nodes { ... on PullRequest { %s } } } }'
          % (SEARCH_PAGE, PR_FIELDS))
MORE = ('query($owner: String!, $name: String!, $number: Int!, $after: String) { repository(owner: $owner, name: $name) '
        '{ pullRequest(number: $number) { %s(first: %d, after: $after) { pageInfo { hasNextPage endCursor } nodes { %s } } } } }')


class BenchError(Exception):
    pass


ISSUE = ('query($owner: String!, $name: String!, $number: Int!) { repository(owner: $owner, name: $name) '
         '{ issue(number: $number) { number title state stateReason closedAt } } }')
DOCUMENTS = frozenset([SEARCH, ISSUE] + [MORE % (field, PAGE, shape) for field, shape in CONNECTIONS.items()])


def read_only(document):
    if document not in DOCUMENTS:
        raise BenchError('refused: only the bench\'s own GraphQL query documents are sent')
    return document


def gh_graphql(document, variables, runner=subprocess.run):
    args = ['gh', 'api', 'graphql', '-f', 'query=' + read_only(document)]
    for key, value in variables.items():
        if value is None:
            continue
        args += ['-F' if isinstance(value, int) else '-f', '%s=%s' % (key, value)]
    done = runner(args, capture_output=True, text=True)
    if done.returncode != 0:
        raise BenchError('gh api graphql failed: ' + (done.stderr.strip() or 'exit %d' % done.returncode))
    try:
        reply = json.loads(done.stdout)
    except ValueError:
        raise BenchError('gh api graphql printed no JSON') from None
    if not isinstance(reply, dict) or reply.get('errors') or not isinstance(reply.get('data'), dict):
        raise BenchError('GraphQL errors: ' + json.dumps(reply.get('errors') if isinstance(reply, dict) else reply))
    return reply['data']


def gh_issue(repo, number, runner=subprocess.run):
    owner, name = repo.split('/')
    done = runner(['gh', 'api', 'graphql', '-f', 'query=' + read_only(ISSUE), '-f', 'owner=' + owner,
                   '-f', 'name=' + name, '-F', 'number=%d' % number], capture_output=True, text=True)
    try:
        reply = json.loads(done.stdout)
    except ValueError:
        raise BenchError('gh api graphql failed: ' + (done.stderr.strip() or 'exit %d' % done.returncode)) from None
    errors = reply.get('errors') if isinstance(reply, dict) else None
    if errors and all(isinstance(e, dict) and e.get('type') == 'NOT_FOUND' for e in errors):
        return None
    if done.returncode != 0 or errors or not isinstance(reply.get('data'), dict):
        raise BenchError('GraphQL errors: ' + json.dumps(errors if errors else reply))
    return (reply['data'].get('repository') or {}).get('issue')


def is_test(path):
    return bool(TEST_PATH.search(path))


def ignored_when_due(issue, due):
    closed = issue.get('state') == 'CLOSED' and issue.get('closedAt') and parse_time(issue['closedAt']) <= due
    return not closed or issue.get('stateReason') == 'NOT_PLANNED'


def polish_status(records, issue, now):
    cache = {}
    for r in records:
        split = Counter(not_due=0, unknown=0, ignored=0, handled=0)
        due = parse_time(r['merged_at']) + DUE
        for number in r['polish_issues']:
            if due > now:
                split['not_due'] += 1
                continue
            key = (r['issue_repo'], number)
            if key not in cache:
                cache[key] = issue(*key)
            found = cache[key]
            if not found or POLISH_TITLE not in (found.get('title') or ''):
                split['unknown'] += 1
            else:
                split['ignored' if ignored_when_due(found, due) else 'handled'] += 1
        r['polish_split'] = split
    return records


def diff_size(records, clones, git):
    for r in records:
        r['diff_size'] = None
        clone = clones.get(r['repo'].lower())
        base, head = r['base'], r['head']
        if not (clone and all(re.fullmatch(r'[0-9a-f]{7,40}', oid or '') for oid in (base, head))):
            continue
        if any(local_git(clone, ['cat-file', '-e', oid + '^{commit}'], git).returncode for oid in (base, head)):
            continue
        done = local_git(clone, ['diff', '--numstat', '--no-renames', '--no-ext-diff', '--no-textconv',
                                 base + '...' + head], git)
        if done.returncode != 0:
            continue
        size = Counter(code_lines=0, test_lines=0, code_files=0, test_files=0)
        for line in done.stdout.splitlines():
            added, deleted, path = line.split('\t', 2)
            kind = 'test' if is_test(path) else 'code'
            size[kind + '_files'] += 1
            size[kind + '_lines'] += sum(int(x) for x in (added, deleted) if x != '-')
        r['diff_size'] = size
    return records


def local_git(clone, args, runner=subprocess.run):
    if not args or args[0] not in GIT_READS:
        raise BenchError('refused: only local git diff and cat-file run')
    return runner(['git', '-C', clone, '--no-pager'] + list(args), capture_output=True, text=True)


def added_lines(clone, first, head, path, git):
    for obj in (first + '^{commit}', head + '^{commit}', head + ':' + path):
        if local_git(clone, ['cat-file', '-e', obj], git).returncode != 0:
            return None
    done = local_git(clone, ['diff', '--no-ext-diff', '--no-textconv', '--no-color', '--no-renames', '--text', '-U0',
                             first, head, '--', path], git)
    if done.returncode != 0:
        return None
    lines = set()
    for start, count in HUNK.findall(done.stdout):
        lines.update(range(int(start), int(start) + (int(count) if count else 1)))
    return lines


def classify(records, clones, git):
    cache = {}
    for r in records:
        split = Counter(changed=0, unchanged=0, unknown=0)
        clone = clones.get(r['repo'].lower())
        for head, place in r['late']:
            found = PLACE.fullmatch(place)
            if not (clone and r['first_head'] and head and found):
                split['unknown'] += 1
                continue
            path, low = found.group(1), int(found.group(2))
            key = (clone, r['first_head'], head, path)
            if key not in cache:
                cache[key] = added_lines(clone, r['first_head'], head, path, git)
            touched = cache[key]
            if touched is None:
                split['unknown'] += 1
            elif touched & set(range(low, int(found.group(3) or low) + 1)):
                split['changed'] += 1
            else:
                split['unchanged'] += 1
        r['late_split'] = split
    return records


def parse_time(text):
    value = text.strip()
    if value.endswith('Z'):
        value = value[:-1] + '+00:00'
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        raise ValueError('time needs a zone: ' + text)
    return moment.astimezone(timezone.utc)


def stamp(moment):
    return moment.strftime('%Y-%m-%dT%H:%M:%SZ')


def complete(owner, name, node, graphql):
    for field, shape in CONNECTIONS.items():
        connection = node[field]
        nodes = list(connection['nodes'])
        info = connection['pageInfo']
        while info['hasNextPage']:
            data = graphql(MORE % (field, PAGE, shape),
                           {'owner': owner, 'name': name, 'number': node['number'], 'after': info['endCursor']})
            page = data['repository']['pullRequest'][field]
            nodes += page['nodes']
            info = page['pageInfo']
        node[field] = nodes
    return node


def fetch(repo, start, end, graphql):
    owner, name = repo.split('/')
    query = 'repo:%s is:pr is:merged merged:%s..%s sort:created-asc' % (repo, stamp(start), stamp(end))
    found, after, count = {}, None, None
    while True:
        search = graphql(SEARCH, {'q': query, 'after': after})['search']
        count = search['issueCount']
        if count > SEARCH_CAP:
            raise BenchError('%s: %d PRs match, over the search cap of %d; use a shorter window' % (repo, count, SEARCH_CAP))
        for node in search['nodes']:
            if node['number'] in found:
                raise BenchError('%s: search returned PR %d twice' % (repo, node['number']))
            found[node['number']] = complete(owner, name, node, graphql)
        if not search['pageInfo']['hasNextPage']:
            break
        after = search['pageInfo']['endCursor']
    if len(found) != count:
        raise BenchError('%s: search reported %d PRs but returned %d' % (repo, count, len(found)))
    return [n for n in found.values() if start <= parse_time(n['mergedAt']) <= end]


def author_of(comment):
    author = comment.get('author')
    if not author:
        return None
    return author['login'] + ('[bot]' if author.get('__typename') == 'Bot' else '')


def record(repo, node):
    verdicts = sorted((c for c in node['comments']
                       if author_of(c) in RECORD_AUTHORS and c['body'].startswith('VERDICT:')),
                      key=lambda c: parse_time(c['createdAt']))
    words = [(WORD.match(c['body']) or [None, None])[1] for c in verdicts]
    findings = [Counter(FINDING.findall(c['body'])) for c in verdicts]
    heads = [(HEAD.match(c['body']) or [None, None])[1] for c in verdicts]
    issues = [i['body'] or '' for i in node['closingIssuesReferences']]
    sizes = sorted({m for b in issues for m in SIZE.findall(b)})
    approved = [i for i, w in enumerate(words) if w == 'APPROVE']
    return {
        'repo': repo, 'number': node['number'], 'title': node['title'], 'created_at': node['createdAt'],
        'diff': node['additions'] + node['deletions'], 'files': node['changedFiles'],
        'ticket': bool(sizes), 'size': ''.join(sizes) or None,
        'rounds': len(verdicts), 'changes': words.count('CHANGES'), 'first': words[0] if words else None,
        'reapprovals': len(approved) - 1 if approved else 0,
        'first_findings': findings[0] if findings else Counter(),
        'recheck_findings': findings[1:],
        'first_head': heads[0] if heads else None,
        'late': [(heads[i], place) for i in range(1, len(verdicts)) for place in LATE.findall(verdicts[i]['body'])],
        'withdrawn': len({label for c in verdicts for label in WITHDRAWN.findall(c['body'])}),
        'polish_issues': sorted({int(n) for c in verdicts for n in POLISH_ISSUE.findall(c['body'])}),
        'issue_repo': (lambda repos: repos.pop() if len(repos) == 1 else repo)(
            {(i.get('repository') or {}).get('nameWithOwner') or repo for i in node['closingIssuesReferences']}),
        'merged_at': node['mergedAt'], 'base': node.get('baseRefOid'), 'head': node.get('headRefOid'),
    }


def pct(part, whole):
    return math.floor(100 * part / whole + 0.5) if whole else None


def nearest_rank(values, share):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)] if ordered else None


def summarize(records):
    reviewed = [r for r in records if r['rounds']]
    rounds = [r['rounds'] for r in reviewed]
    first = Counter()
    recheck = Counter()
    for r in reviewed:
        first.update(r['first_findings'])
        for found in r['recheck_findings']:
            recheck.update(found)
    rechecks = [f for r in reviewed for f in r['recheck_findings']]
    n = len(reviewed)
    late = Counter()
    for r in reviewed:
        late.update(r.get('late_split', {}))
    blocking = sum(first.values()) + sum(recheck.values())
    polish = Counter()
    for r in reviewed:
        polish.update(r.get('polish_split', {}))
    withdrawn = sum(r.get('withdrawn', 0) for r in reviewed)
    due = polish['ignored'] + polish['handled']
    sized = [r['diff_size'] for r in reviewed if r.get('diff_size') is not None]

    def median(key):
        return statistics.median(s[key] for s in sized) if sized else None
    return {
        'merged': len(records), 'reviewed': n, 'verdicts': sum(rounds),
        'rounds': {'mean': round(sum(rounds) / n, 2) if n else None,
                   'median': statistics.median(rounds) if n else None,
                   'p90': nearest_rank(rounds, 0.9), 'max': max(rounds) if n else None},
        'changes': {'total': sum(r['changes'] for r in reviewed),
                    'mean': round(sum(r['changes'] for r in reviewed) / n, 2) if n else None},
        'approve_first': {'count': sum(r['first'] == 'APPROVE' for r in reviewed),
                          'pct': pct(sum(r['first'] == 'APPROVE' for r in reviewed), n)},
        'three_plus': {'count': sum(x >= 3 for x in rounds), 'pct': pct(sum(x >= 3 for x in rounds), n)},
        'distribution': {k: sum(1 for x in rounds if (x == int(k) if k != '5+' else x >= 5))
                         for k in ('1', '2', '3', '4', '5+')},
        'reapprovals': sum(r['reapprovals'] for r in reviewed),
        'findings': {
            'first': dict({c: first[c] for c in CHECKS}, total=sum(first.values())),
            'rechecks': dict({c: recheck[c] for c in CHECKS}, total=sum(recheck.values()), count=len(rechecks),
                             with_new_blocker=sum(1 for f in rechecks if f)),
        },
        'late': {'blocking': blocking, 'late': sum(recheck.values()), 'pct': pct(sum(recheck.values()), blocking),
                 'changed': late['changed'], 'unchanged': late['unchanged'], 'unknown': late['unknown']},
        'withdrawn_ignored': {'blocking': blocking, 'withdrawn': withdrawn, 'withdrawn_pct': pct(withdrawn, blocking),
                              'polish': sum(polish.values()), 'not_due': polish['not_due'],
                              'unknown': polish['unknown'], 'due': due, 'ignored': polish['ignored'],
                              'ignored_pct': pct(polish['ignored'], due),
                              'either_pct': pct(withdrawn + polish['ignored'], blocking + due)},
        'size': dict({k: median(k) for k in ('code_lines', 'test_lines', 'code_files', 'test_files')},
                     sized=len(sized), unknown=len(reviewed) - len(sized)),
    }


def in_band(r, low, high):
    return r['diff'] >= low and (high is None or r['diff'] < high)


def worst(records, limit=10):
    ranked = sorted((r for r in records if r['rounds']),
                    key=lambda r: (-r['changes'], -r['rounds'], r['repo'], r['number']))
    return [{k: r[k] for k in ('repo', 'number', 'title', 'rounds', 'changes', 'size', 'diff', 'files')}
            for r in ranked[:limit]]


def bench(repos, start, end, opened_after, graphql, clones=None, git=subprocess.run, issue=gh_issue, now=None):
    now = now or datetime.now(timezone.utc)
    by_repo = {}
    for repo in repos:
        nodes = fetch(repo, start, end, graphql)
        if opened_after is not None:
            nodes = [n for n in nodes if parse_time(n['createdAt']) > opened_after]
        records = classify([record(repo, n) for n in nodes], clones or {}, git)
        by_repo[repo] = diff_size(polish_status(records, issue, now), clones or {}, git)
    everything = [r for repo in repos for r in by_repo[repo]]
    tickets = [r for r in everything if r['ticket']]
    sizes = {}
    for size in 'SML':
        diffs = [r['diff'] for r in tickets if r['size'] == size]
        sizes[size] = {'count': len(diffs), 'median_diff': statistics.median(diffs) if diffs else None}
    return {
        'window': {'merged_from': stamp(start), 'merged_to': stamp(end),
                   'opened_after': stamp(opened_after) if opened_after else None},
        'all': dict({repo: summarize(by_repo[repo]) for repo in repos}, All=summarize(everything)),
        'tickets': dict({repo: summarize([r for r in by_repo[repo] if r['ticket']]) for repo in repos},
                        All=summarize(tickets)),
        'ticket_bands': {label: summarize([r for r in tickets if in_band(r, low, high)])
                         for label, low, high in BANDS},
        'ticket_sizes': sizes,
        'worst': worst(everything),
    }


def cell(value, share=None):
    if value is None:
        return '-'
    if share is not None:
        return '%d (%d%%)' % (value, share)
    return '%.2f' % value if isinstance(value, float) and not value.is_integer() else '%d' % value


def table(rows):
    head = ('| Cohort | Merged | Reviewed | Rounds mean | Median | p90 | Max | CHANGES mean | APPROVE at first | 3+ rounds '
            '| First-review blockers (Spec/Sweep/Standards) | Re-checks with a new blocker | Re-check blockers (Spec/Sweep/Standards) |')
    lines = [head, '|' + ' --- |' * head.count(' | ') + ' --- |']
    for label, s in rows.items():
        f, rc = s['findings']['first'], s['findings']['rechecks']
        lines.append('| %s |' % label + ''.join(' %s |' % c for c in (
            s['merged'], s['reviewed'], cell(s['rounds']['mean']), cell(s['rounds']['median']), cell(s['rounds']['p90']),
            cell(s['rounds']['max']), cell(s['changes']['mean']),
            cell(s['approve_first']['count'], s['approve_first']['pct']) if s['reviewed'] else '-',
            cell(s['three_plus']['count'], s['three_plus']['pct']) if s['reviewed'] else '-',
            '%d (%d/%d/%d)' % (f['total'], f['Spec'], f['Sweep'], f['Standards']),
            '%d of %d' % (rc['with_new_blocker'], rc['count']),
            '%d (%d/%d/%d)' % (rc['total'], rc['Spec'], rc['Sweep'], rc['Standards']))))
    return '\n'.join(lines)


def late_table(rows):
    lines = ['| Cohort | Merged | Reviewed | Rounds mean | Blocking findings | First seen at round 2+ '
             '| Changed by the fix | Unchanged since the first review | Unknown |',
             '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for label, s in rows.items():
        late = s['late']
        lines.append('| %s |' % label + ''.join(' %s |' % c for c in (
            s['merged'], s['reviewed'], cell(s['rounds']['mean']), late['blocking'],
            cell(late['late'], late['pct']) if late['blocking'] else '-',
            *(cell(late[k], pct(late[k], late['late'])) if late['late'] else '-'
              for k in ('changed', 'unchanged', 'unknown')))))
    return '\n'.join(lines)


def withdrawn_table(rows):
    lines = ['| Cohort | Merged | Reviewed | Rounds mean | Blocking findings | Withdrawn | Polish issues '
             '| Not yet due | Unknown | Ignored when due | Withdrawn or ignored |',
             '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for label, s in rows.items():
        w = s['withdrawn_ignored']
        lines.append('| %s |' % label + ''.join(' %s |' % c for c in (
            s['merged'], s['reviewed'], cell(s['rounds']['mean']), w['blocking'],
            cell(w['withdrawn'], w['withdrawn_pct']) if w['blocking'] else '-', w['polish'], w['not_due'],
            w['unknown'], '%d of %d (%d%%)' % (w['ignored'], w['due'], w['ignored_pct']) if w['due'] else '-',
            '%d%%' % w['either_pct'] if w['either_pct'] is not None else '-')))
    return '\n'.join(lines)


def size_table(rows):
    lines = ['| Cohort | Merged | Reviewed | Rounds mean | Sized | Median code lines | Median test lines '
             '| Median code files | Median test files | Unknown |',
             '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for label, s in rows.items():
        z = s['size']
        lines.append('| %s |' % label + ''.join(' %s |' % c for c in (
            s['merged'], s['reviewed'], cell(s['rounds']['mean']), z['sized'], cell(z['code_lines']),
            cell(z['test_lines']), cell(z['code_files']), cell(z['test_files']), z['unknown'])))
    return '\n'.join(lines)


def markdown(result):
    w = result['window']
    out = ['Window: merged %s to %s%s.' % (w['merged_from'], w['merged_to'],
                                           ', opened after %s' % w['opened_after'] if w['opened_after'] else ''),
           '', '**All PRs**', '', table(result['all']),
           '', '**Ticket PRs** (a closing issue has `Size: S.`, `M.` or `L.`)', '', table(result['tickets']),
           '', '**Ticket PRs by diff lines**', '', table(result['ticket_bands']), '']
    sizes = result['ticket_sizes']
    out.append('Median ticket diff by size: ' + ', '.join(
        '%s %s (n %d)' % (k, cell(v['median_diff']), v['count']) for k, v in sizes.items()) + '.')
    a = result['all']['All']
    out += ['', 'Distribution (all reviewed PRs): ' + ', '.join(
        '%s %d' % ({'1': '1 round', '5+': '5 or more'}.get(k, k + ' rounds'), v) for k, v in a['distribution'].items()) + '. Verdicts %d, `CHANGES` %d, re-approvals %d.'
        % (a['verdicts'], a['changes']['total'], a['reapprovals']), '', '**Worst PRs**', '',
        '| PR | Rounds (`CHANGES`) | Size | Diff lines | Files |', '| --- | --- | --- | --- | --- |']
    for r in result['worst']:
        out.append('| %s#%d | %d (%d) | %s | %d | %d |' % (r['repo'].split('/')[1], r['number'], r['rounds'],
                                                        r['changes'], r['size'] or 'none', r['diff'], r['files']))
    out += ['', '**Late blocking findings** (new blocking findings first seen at round 2 or later, by whether '
            'the fix changed their line since the first review)', '',
            late_table(dict(result['all'], **{'Ticket PRs': result['tickets']['All']})),
            '', '**Withdrawn or ignored** (blockers withdrawn, and polish issues still open or closed as not planned '
            '7 days after their PR merged)', '',
            withdrawn_table(dict(result['all'], **{'Ticket PRs': result['tickets']['All']})),
            '', '**Diff size against rounds** (reviewed PRs, from local git; tests counted apart; '
            'ticket PRs in the diff-line bands)', '',
            size_table(dict(result['all'], **result['ticket_bands']))]
    return '\n'.join(out)


def main(argv=None, graphql=gh_graphql, out=sys.stdout, git=subprocess.run, issue=gh_issue, now=None):
    parser = argparse.ArgumentParser(description='Read-only review-rounds bench over merged PRs.')
    parser.add_argument('--repo', action='append', required=True, help='owner/name; repeat for each repository')
    parser.add_argument('--merged-from', required=True, type=parse_time)
    parser.add_argument('--merged-to', required=True, type=parse_time)
    parser.add_argument('--opened-after', type=parse_time)
    parser.add_argument('--clone', action='append', default=[],
                        help='owner/name=path of a local git clone holding the verdict heads; repeat per repository')
    args = parser.parse_args(argv)
    seen = {}
    for repo in args.repo:
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
            parser.error('--repo must be owner/name: ' + repo)
        if repo.lower() in seen:
            parser.error('--repo repeated: %s and %s name one repository' % (seen[repo.lower()], repo))
        seen[repo.lower()] = repo
    clones = {}
    for pair in args.clone:
        repo, _, path = pair.partition('=')
        if repo.lower() not in seen or not path:
            parser.error('--clone must be owner/name=path for a --repo: ' + pair)
        if repo.lower() in clones:
            parser.error('--clone repeated: ' + repo)
        clones[repo.lower()] = path
    if args.merged_from > args.merged_to:
        parser.error('--merged-from is after --merged-to')
    try:
        result = bench(args.repo, args.merged_from, args.merged_to, args.opened_after, graphql, clones, git, issue, now)
    except BenchError as error:
        print('bench: ' + str(error), file=sys.stderr)
        return 1
    out.write(markdown(result) + '\n\n```json\n' + json.dumps(result, indent=2, sort_keys=True) + '\n```\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
