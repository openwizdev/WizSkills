#!/usr/bin/env python3
"""Merge one approved pull request at its exact head, then post the ticket's cost (WS8, #1181; WS26, #1670).

  merge.py read   OWNER/NAME PR HEAD
  merge.py admit  OWNER/NAME PR HEAD CHECKS
  merge.py merge  OWNER/NAME PR HEAD CHECKS BODY --ticket TICKET [--base-rule-checked] [-- COST ARGS]
  merge.py cost   OWNER/NAME PR HEAD TICKET [-- COST ARGS]
  merge.py settle OWNER/NAME PR TICKET [-- COST ARGS]
  merge.py look   OWNER/NAME PR HEAD --ticket TICKET
  merge.py ask    OWNER/NAME PR HEAD --ticket TICKET EVIDENCE-FILE

`read` prints where the pull request stands: `merged <commit>`, `queued`,
`open, the merge queue is on|off[; it left the queue at <time>: <reason>]` or
`stop: <why>`. `admit` prints `admit: ...`, `base rule: no merge queue;
mergeable: <state>` or `wait: <why>`; CHECKS are fleet.md's required checks,
comma-separated. Both only read.

`merge` reads, admits and merges HEAD with `gh pr merge --merge
--match-head-commit` (never `--admin`), reads it back and records the outcome:
`merged <commit>; cost ...` (exit 0), `queued; recorded <id>` (exit 0),
`pending: ...` (exit 0, nothing recorded: read again next wake),
`blocked: <why>; recorded <id>` (exit 1). The queue receipt (`launch-fleet:
merge queued <commit>`) is what tells a later removal from a fresh enqueue and
what `settle` reads, so it is recorded before the enqueue: a receipt it can't
confirm prints `not queued: ...` (exit 1) and nothing is enqueued; the next run
reuses a receipt that did land. A pull request read as queued without its
receipt gets one then (`queued; recorded <id>`, or `queued; receipt
unconfirmed ...`, exit 1). Without a merge queue it merges only
with `--base-rule-checked`, after you applied fleet.md's base rule and
`fleet.sh every` still prints this merge line. BODY names the APPROVE and the
plan approval that allowed it.

TICKET is `N` or `OWNER/NAME#N`, and must be one of the issues the pull
request closes: a bare `N` names its one closing issue numbered N, in whatever
repository; anything else is `refused: ...` before any write.

`cost`, also run by `merge` after a verified merge, runs the project's FM4
command `tools/collector/cost_line.py --repo OWNER/NAME --pr PR [COST ARGS]`
from the current directory and posts `launch-fleet: cost: <its line>` on the
ticket, in the ticket's own repository, or `launch-fleet: cost unknown (PR
<ref>): <why>`; never a zero for an unknown part. <ref> is `#PR`, or
`OWNER/NAME#PR` when the ticket lives in another repository; FM4's command
costs only tickets in the pull request's repository, so such a ticket's cost
is unknown. It posts once: `cost already posted <id>` names an earlier record
author's record, matching the pull request's repository in any letter case;
when the ticket's records can't be read it prints `unknown: ...` and posts
nothing. It refuses before a verified merge at HEAD.

The late look (RC3, #1831; contracts/checkpoints.v1.md): `merge` holds the
final merge of a user-visible spec (the merge of its last open planned ticket,
where the spec answers `User-visible: yes` or `yes, a release`, or its answers
are invalid) until a record author's late-look record by the owner approves
this head after its evidence ask: `held: ask-due|look-due|changes-asked: ...`
(exit 1, nothing written). Every other merge, and a spec answered `no` or
planned before the contract, flows as today. A spec, its planned tickets, its
comments or the contract it can't read is `unknown: ...` and merges nothing.
`look` prints the same reading (`flows: ...`, `released: ...` or `held: ...`)
and only reads. `ask` posts the contract's evidence ask on the spec: its
opening line for PR and HEAD, then EVIDENCE-FILE's `Evidence:` and `Look
for:` lines; it refuses an ask the contract refuses (code links included) and
posts one ask per head (`ask posted <id>`, `ask already posted <id>`).

`settle` is the cost a queued merge still owes: it reads the newest record
author's queue receipt on the pull request and runs `cost` at that commit
(`refused: ...` while it isn't merged there), or prints `no queued merge`.
"""
import datetime
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('launch_fleet_post', HERE / 'post.py')
post = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(post)
Stop = post.Stop

QUERY = '''query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) { defaultBranchRef { name } pullRequest(number: $number) {
    state baseRefName headRefOid isMergeQueueEnabled isInMergeQueue mergeable mergeCommit { oid }
    mergeQueueEntry { headCommit { oid } }
    closingIssuesReferences(first: 50) { pageInfo { hasNextPage } nodes { number repository { nameWithOwner } } }
    timelineItems(itemTypes: [REMOVED_FROM_MERGE_QUEUE_EVENT], last: 1) {
      nodes { ... on RemovedFromMergeQueueEvent { createdAt reason } } }
    commits(last: 1) { nodes { commit { oid statusCheckRollup { contexts(first: 50) { pageInfo { hasNextPage }
      nodes { __typename ... on CheckRun { name conclusion } ... on StatusContext { context state } } } } } } } } } }'''
COST = 'tools/collector/cost_line.py'
SHA = re.compile(r'[0-9a-f]{40}')
TICKET = re.compile(r'(?:([A-Za-z0-9-]+/[A-Za-z0-9_.-]+)#)?([1-9][0-9]{0,11})')
QUEUED = re.compile(r'launch-fleet: merge queued ([0-9a-f]{40})\b')
# The late look (RC3): the checkpoints contract's forms and the open-development contract's deciders.
CONTRACT = HERE.parents[2] / 'contracts/checkpoints.v1.md'
DECIDERS = ('Jake',)
QUOTES = '"\u201c\u201d'
FORMS = {'section', 'section_like', 'setext_text', 'setext_underline', 'section_end', 'fence', 'one_way_door',
         'user_visible', 'ask_opening', 'ask_evidence', 'ask_look_for', 'link_host', 'code_hosts', 'uploaded_hosts',
         'uploaded_path', 'record_opening', 'record_pointer'}
SPEC_QUERY = '''query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) { issue(number: $number) { number parent { number body
    repository { nameWithOwner }
    subIssues(first: 100) { pageInfo { hasNextPage } nodes { number state repository { nameWithOwner } } } } } } }'''


def snapshot(repo, number):
    owner, name = repo.split('/')
    value = post.read_json('api', 'graphql', '-f', f'owner={owner}', '-f', f'name={name}', '-F', f'number={number}',
                           '-f', f'query={QUERY}')
    try:
        r = value['data']['repository']
        return r['defaultBranchRef']['name'], r['pullRequest']
    except (TypeError, KeyError):
        raise Stop('stop: the pull request could not be read')


def where(main, p, head):
    if not isinstance(p, dict):
        return 'stop: no such pull request'
    if p['headRefOid'] != head:
        return f"stop: its head is {p['headRefOid']}, not {head}"
    if p['baseRefName'] != main:
        return f"stop: its base is {p['baseRefName']}, not the default branch {main}"
    if p['state'] == 'MERGED' and isinstance((p.get('mergeCommit') or {}).get('oid'), str):
        return 'merged ' + p['mergeCommit']['oid']
    entry = ((p.get('mergeQueueEntry') or {}).get('headCommit') or {}).get('oid')
    if p['state'] == 'OPEN' and p['isInMergeQueue'] is True and entry == head:
        return 'queued'
    if p['state'] == 'OPEN' and p['isInMergeQueue'] is False and type(p['isMergeQueueEnabled']) is bool:
        nodes = (p.get('timelineItems') or {}).get('nodes') or []
        left = nodes[-1] if nodes else None
        return ('open, the merge queue is ' + ('on' if p['isMergeQueueEnabled'] else 'off')
                + (f"; it left the queue at {left['createdAt']}: {left['reason']}" if left else ''))
    return f"stop: {p['state']}, in the merge queue: {p['isInMergeQueue']}"


def admission(main, p, head, checks):
    if not isinstance(p, dict):
        return 'wait: no such pull request'
    if p['state'] != 'OPEN':
        return f"wait: it is {p['state']}, not open"
    commit = ((p.get('commits') or {}).get('nodes') or [{}])[0].get('commit') or {}
    if p['headRefOid'] != head or commit.get('oid') != head:
        return f"wait: its head is {p['headRefOid']}, not {head}"
    if p['baseRefName'] != main:
        return f"wait: its base is {p['baseRefName']}, not the default branch {main}"
    contexts = (commit.get('statusCheckRollup') or {}).get('contexts') or {}
    if (contexts.get('pageInfo') or {}).get('hasNextPage') is not False:
        return 'wait: its head has more checks than one read shows'
    green = {n.get('name') or n.get('context') for n in contexts.get('nodes') or []
             if (n.get('conclusion') or n.get('state')) == 'SUCCESS'}
    missing = [c for c in checks if c not in green]
    if missing:
        return 'wait: not every required check is green on it: ' + ', '.join(missing)
    if p['isMergeQueueEnabled'] is True:
        return f'admit: the merge queue re-tests it on the latest {main}'
    if p['isMergeQueueEnabled'] is False:
        return f"base rule: no merge queue; mergeable: {p['mergeable']}"
    return 'wait: whether the merge queue is on is unknown'


def ticket_of(repo, number, p, ticket):
    """The (repository, number) of the closing issue TICKET names, or a refusal."""
    named, n = TICKET.fullmatch(ticket).groups()
    refs = (p or {}).get('closingIssuesReferences') or {}
    if (refs.get('pageInfo') or {}).get('hasNextPage') is not False:
        raise Stop(f'refused: the issues PR #{number} closes could not be read whole')
    found = {(r, i['number']) for i in refs.get('nodes') or []
             if isinstance(i, dict) and type(i.get('number')) is int
             and isinstance(r := (i.get('repository') or {}).get('nameWithOwner'), str)}
    match = [(r, i) for r, i in found if i == int(n) and (named is None or r.casefold() == named.casefold())]
    if not match:
        raise Stop(f'refused: PR #{number} does not close {ticket}')
    if len(match) > 1:
        raise Stop(f'refused: PR #{number} closes two issues numbered {n}; name it as OWNER/NAME#{n}')
    return match[0]


def receipts(repo, number):
    """The record authors' queue receipts on the pull request as (commit, comment id), oldest first."""
    auth = post.authors(repo)
    items = post.thread(repo, number)
    if items is None:
        raise Stop(f'unknown: #{number} could not be read; run it again next wake')
    return [(m.group(1), c.get('id')) for c in items if post.ours(c, auth)
            for m in [QUEUED.match((c.get('body') or '').split('\n', 1)[0])] if m]


def record(repo, number, body):
    try:
        return post.comment(repo, number, body).split()[-1]
    except Stop as outcome:
        return f'not recorded ({outcome})'


def cost(repo, number, head, ticket, extra=()):
    main, p = snapshot(repo, number)
    state = where(main, p, head)
    if not state.startswith('merged '):
        raise Stop(f'refused: no verified merge at {head} ({state})')
    home, ticket = ticket_of(repo, number, p, ticket)
    same = home.casefold() == repo.casefold()
    ref = f'(PR #{number})' if same else f'(PR {repo}#{number})'
    auth = post.authors(home)
    items = post.thread(home, ticket)
    if items is None:
        raise Stop(f'unknown: the cost records on {home}#{ticket} could not be read; nothing was posted')
    for c in items:
        first = (c.get('body') or '').split('\n', 1)[0]
        if post.ours(c, auth) and first.startswith('launch-fleet: cost') and ref.casefold() in first.casefold():
            return f"cost already posted {c['id']}"
    body = f'launch-fleet: cost unknown {ref}: '
    if not same:
        body += "the cost command costs only tickets in the pull request's repository"
    elif not Path(COST).is_file():
        body += 'no cost command'
    else:
        try:
            r = subprocess.run([sys.executable, '-I', COST, '--repo', repo, '--pr', str(number), *extra],
                               capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
            out, err, code = r.stdout.splitlines(), r.stderr.strip(), r.returncode
        except (OSError, subprocess.TimeoutExpired):
            out, err, code = [], '', None
        reason = re.fullmatch(r'cost: ([A-Za-z0-9 #,.()-]+); nothing printed', err)
        if code == 0 and len(out) == 1 and out[0].startswith(f'Ticket #{ticket} cost (PR #{number}): '):
            body = 'launch-fleet: cost: ' + out[0]
        elif code == 0:
            body += 'unexpected cost output'
        else:
            body += reason.group(1) if reason else 'the cost command failed'
    return 'cost posted ' + post.comment(home, ticket, body).split()[-1]


def settle(repo, number, ticket, extra=()):
    found = receipts(repo, number)
    return cost(repo, number, found[-1][0], ticket, extra) if found else 'no queued merge'


def forms():
    """The checkpoints contract's one `checkpoints-v1` block, compiled; refused when unreadable."""
    try:
        blocks = re.findall(r'^```checkpoints-v1\n(.*?)^```$', CONTRACT.read_text(encoding='utf-8'), re.M | re.S)
        if len(blocks) != 1:
            raise ValueError(blocks)
        f = {k: re.compile(v) if isinstance(v, str) else set(v) for k, v in json.loads(blocks[0]).items()}
        if not FORMS <= f.keys():
            raise ValueError(FORMS - f.keys())
        return f
    except (OSError, ValueError, AttributeError, TypeError, re.error):
        raise Stop('unknown: the checkpoints contract could not be read; nothing was merged')


def lines_of(text):
    return (text or '').replace('\r\n', '\n').replace('\r', '\n').split('\n')


def late(body, f):
    """Whether the spec body gives the owner a late look: answered user-visible, or invalid."""
    lines = lines_of(body)
    inside, opening = set(), None
    for i, line in enumerate(lines):
        if opening is None:
            m = f['fence'].fullmatch(line)
            if m:
                opening = m.group(1)
                inside.add(i)
            continue
        inside.add(i)
        close = re.fullmatch(r' {0,3}(`+|~+)[ \t]*', line)
        if close and close.group(1)[0] == opening[0] and len(close.group(1)) >= len(opening):
            opening = None
    outside = [i for i in range(len(lines)) if i not in inside]
    for i in outside:
        if (f['section_like'].fullmatch(lines[i]) and not f['section'].fullmatch(lines[i])) or (
                f['setext_text'].fullmatch(lines[i]) and i + 1 in outside
                and f['setext_underline'].fullmatch(lines[i + 1])):
            return True  # section-heading: invalid reads as both yes
    starts = [i for i in outside if f['section'].fullmatch(lines[i])]
    if len(starts) != 1:
        return bool(starts)  # absent is early only; section-repeated is invalid
    answers = []
    for i in range(starts[0] + 1, len(lines)):
        if i not in inside and f['section_end'].fullmatch(lines[i]):
            break
        if lines[i].strip():
            answers.append(lines[i])
    user = f['user_visible'].fullmatch(answers[1]) if len(answers) == 2 else None
    if not (user and f['one_way_door'].fullmatch(answers[0])):
        return True
    return user.group(1) != 'no'


def link_code(url, f):
    """None for an evidence link, else the contract's refusal code."""
    try:
        parts = urlsplit(url)
        parts.port
    except ValueError:
        return 'evidence-link'
    host = (parts.hostname or '').rstrip('.')
    if ('\\' in url or parts.scheme.lower() != 'https' or not url[len(parts.scheme):].startswith('://')
            or '@' in parts.netloc or not f['link_host'].fullmatch(host)):
        return 'evidence-link'
    if host in f['uploaded_hosts'] and f['uploaded_path'].fullmatch(parts.path):
        return None
    return 'evidence-code' if host in f['code_hosts'] else None


def read_ask(text, f):
    """(PR, commit) of a valid evidence ask, or its refusal code."""
    lines = [x for x in lines_of(text) if x.strip()]
    first = f['ask_opening'].fullmatch(lines[0]) if lines else None
    if not first:
        return 'ask-opening'
    rest = lines[1:]
    if not (rest and f['ask_evidence'].fullmatch(rest[0])):
        return 'evidence-missing'
    while rest and (m := f['ask_evidence'].fullmatch(rest[0])):
        code = link_code(m.group(2), f)
        if code:
            return code
        rest = rest[1:]
    if len(rest) != 1 or not f['ask_look_for'].fullmatch(rest[0]):
        return 'ask-line'
    return int(first.group(1)), first.group(2)


def read_record(text, f):
    """(decider, PR, commit, outcome) of a valid late-look record, else None."""
    lines = [x for x in lines_of(text) if x.strip()]
    first = f['record_opening'].fullmatch(lines[0]) if lines else None
    try:
        datetime.date.fromisoformat(first.group(2))
    except (AttributeError, ValueError):
        return None
    if any(q in first.group(6) for q in QUOTES) or len(lines) != 2 or not f['record_pointer'].fullmatch(lines[1]):
        return None
    return first.group(1), int(first.group(3)), first.group(4), first.group(5)


def spec_of(home, ticket):
    """(spec repository, number, body, final) for the ticket's spec, or None for a ticket with none."""
    owner, name = home.split('/')
    value = post.read_json('api', 'graphql', '-f', f'owner={owner}', '-f', f'name={name}', '-F', f'number={ticket}',
                           '-f', f'query={SPEC_QUERY}')
    try:
        spec = value['data']['repository']['issue']['parent']
        if spec is None:
            return None
        where_, number, body = spec['repository']['nameWithOwner'], spec['number'], spec['body']
        page, nodes = spec['subIssues']['pageInfo']['hasNextPage'], spec['subIssues']['nodes']
        states = {(n['repository']['nameWithOwner'].casefold(), n['number']): n['state'] for n in nodes}
        if not (isinstance(where_, str) and post.REPO.fullmatch(where_) and type(number) is int
                and isinstance(body, str) and type(page) is bool and set(states.values()) <= {'OPEN', 'CLOSED'}):
            raise TypeError(spec)
    except (TypeError, KeyError, AttributeError):
        raise Stop(f'unknown: the spec of {home}#{ticket} could not be read; nothing was merged')
    if page:
        raise Stop(f"unknown: spec {where_}#{number}'s planned tickets could not be read whole; nothing was merged")
    states.pop((home.casefold(), ticket), None)
    return where_, number, body, all(state == 'CLOSED' for state in states.values())


def look(repo, number, head, ticket, p):
    """The late look's reading for HEAD: ('flows'|'released'|<held why>, spec ref, the valid ask's id)."""
    home, n = ticket_of(repo, number, p, ticket)
    spec = spec_of(home, n)
    if spec is None:
        return 'flows', f'{home}#{n} has no spec', None
    where_, s, body, final = spec
    ref = f'{where_}#{s}'
    if not final:
        return 'flows', f'{home}#{n} is not the last open ticket of {ref}', None
    f = forms()
    if not late(body, f):
        return 'flows', f'{ref} asks no late look', None
    auth = post.authors(where_)
    items = post.thread(where_, s)
    if items is None:
        raise Stop(f'unknown: the comments on {ref} could not be read; nothing was merged')
    asked, newest = [], None
    for c in items:
        if not post.ours(c, auth):
            continue
        text = c.get('body') or ''
        ask, rec = read_ask(text, f), read_record(text, f)
        if ask == (number, head):
            asked.append(c.get('id'))
        elif rec and asked and rec[1:3] == (number, head) and rec[0] in DECIDERS:
            newest = rec[3]
    if not asked:
        return 'ask-due', ref, None
    return {None: 'look-due', 'approved': 'released'}.get(newest, 'changes-asked'), ref, asked[0]


def held(why, ref):
    return 'held: ' + why + ': ' + {'ask-due': f'post the evidence ask on {ref} with merge.py ask',
                                    'look-due': f'the late look asked on {ref} is not recorded',
                                    'changes-asked': f'the late look on {ref} asked for changes'}[why]


def look_line(repo, number, head, ticket):
    main, p = snapshot(repo, number)
    state = where(main, p, head)
    if state.startswith('stop: '):
        raise Stop(state)
    why, ref, _ = look(repo, number, head, ticket, p)
    if why == 'flows':
        return 'flows: ' + ref
    return f'released: the late look on {ref} approved {head}' if why == 'released' else held(why, ref)


def ask(repo, number, head, ticket, path):
    try:
        text = Path(path).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        raise Stop(f'refused: {path} could not be read')
    body = f'launch-fleet: late look asked #{number} at {head}\n\n' + text.strip()
    main, p = snapshot(repo, number)
    state = where(main, p, head)
    if not state.startswith('open'):
        raise Stop(f'refused: no ask for a pull request that is not open at {head} ({state})')
    f = forms()
    code = read_ask(body, f)
    if code != (number, head):
        raise Stop(f'refused: the evidence ask is invalid: {code}')
    why, ref, asked = look(repo, number, head, ticket, p)
    if why == 'flows':
        raise Stop('refused: no late look is due: the merge flows')
    if asked is not None:
        return f'ask already posted {asked}'
    where_, s = ref.rsplit('#', 1)
    return 'ask ' + post.comment(where_, int(s), body)



def merge(repo, number, head, checks, body, ticket, checked, extra):
    def blocked(why):
        raise Stop(f'blocked: {why}; recorded ' + record(repo, number, f'launch-fleet: merge blocked {head}: {why}'))

    def receipt(fail):
        """The queue receipt for HEAD, the newest one or a new one; `fail` prefixes an unconfirmed write."""
        mine = [i for h, i in receipts(repo, number) if h == head]
        if mine:
            return mine[-1]
        try:
            return post.comment(repo, number, f'launch-fleet: merge queued {head}: {body}').split()[-1]
        except Stop as outcome:
            raise Stop(f'{fail} ({outcome}); run it again next wake')

    main, p = snapshot(repo, number)
    state = where(main, p, head)
    if state.startswith('merged '):
        return state + '; ' + cost(repo, number, head, ticket, extra)
    if state == 'queued':
        if any(h == head for h, _ in receipts(repo, number)):
            return 'queued; the queue merges it or lets it go'
        return 'queued; recorded ' + str(receipt('queued; receipt unconfirmed'))
    if state.startswith('stop: '):
        blocked(state[6:])
    ticket_of(repo, number, p, ticket)
    if '; it left the queue at ' in state and any(h == head for h, _ in receipts(repo, number)):
        blocked('left the merge queue: ' + state.split(': ', 1)[1])
    admit = admission(main, p, head, checks)
    if admit.startswith('wait: '):
        blocked(admit[6:])
    why, ref, _ = look(repo, number, head, ticket, p)
    if why not in ('flows', 'released'):
        raise Stop(held(why, ref))
    if admit.startswith('base rule: ') and not checked:
        raise Stop(admit + '; check the base rule and fleet.sh every, then pass --base-rule-checked')
    # Save before you send: the queue may merge it or let it go before any later wake, and the
    # receipt is what settle and the removal guard read then.
    kept = receipt('not queued: the queue receipt is unconfirmed, so nothing was enqueued') \
        if admit.startswith('admit: ') else None
    done = post.gh('pr', 'merge', str(number), '--repo', repo, '--merge', '--match-head-commit', head,
                   '--body', body) is not None
    state = where(*snapshot(repo, number), head)
    if state.startswith('merged '):
        return state + '; ' + cost(repo, number, head, ticket, extra)
    if state == 'queued':
        return 'queued; recorded ' + str(kept or receipt('queued; receipt unconfirmed'))
    if state.startswith('open') and done:
        return 'pending: the merge command succeeded but it still reads open; read it again next wake'
    blocked(state[6:] if state.startswith('stop: ') else state)


def main(argv):
    extra = []
    if '--' in argv:
        at = argv.index('--')
        argv, extra = argv[:at], argv[at + 1:]
    usage = __doc__.split('\n\n')[1]
    try:
        verb, repo, number, *rest = argv
        head = None if verb == 'settle' else rest.pop(0)  # settle reads its commit from the queue receipt
        number = int(number) if re.fullmatch(r'[1-9][0-9]{0,11}', number) else None
        ok = post.REPO.fullmatch(repo) and number and (head is None or SHA.fullmatch(head))
    except (ValueError, IndexError):
        ok = False
    if not ok:
        print(usage, file=sys.stderr)
        return 2
    try:
        if verb == 'read' and not rest:
            print(where(*snapshot(repo, number), head))
        elif verb == 'admit' and len(rest) == 1:
            print(admission(*snapshot(repo, number), head, rest[0].split(',')))
        elif verb == 'cost' and len(rest) == 1 and TICKET.fullmatch(rest[0]):
            print(cost(repo, number, head, rest[0], extra))
        elif verb == 'settle' and len(rest) == 1 and TICKET.fullmatch(rest[0]):
            print(settle(repo, number, rest[0], extra))
        elif verb == 'look' and len(rest) == 2 and rest[0] == '--ticket' and TICKET.fullmatch(rest[1]):
            print(look_line(repo, number, head, rest[1]))
        elif verb == 'ask' and len(rest) == 3 and rest[0] == '--ticket' and TICKET.fullmatch(rest[1]):
            print(ask(repo, number, head, rest[1], rest[2]))
        elif verb == 'merge' and len(rest) >= 4 and rest[2] == '--ticket' and TICKET.fullmatch(rest[3]) \
                and set(rest[4:]) <= {'--base-rule-checked'}:
            print(merge(repo, number, head, rest[0].split(','), rest[1], rest[3],
                        '--base-rule-checked' in rest[4:], extra))
        else:
            print(usage, file=sys.stderr)
            return 2
    except Stop as outcome:
        print(outcome)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
