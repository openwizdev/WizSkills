#!/usr/bin/env python3
"""Merge one approved pull request at its exact head, then post the ticket's cost and the landed comment
(WS8, #1181; WS26, #1670; FL4, #1848).

  merge.py read   OWNER/NAME PR HEAD
  merge.py admit  OWNER/NAME PR HEAD CHECKS
  merge.py merge  OWNER/NAME PR HEAD CHECKS BODY --ticket TICKET [--base-rule-checked] [-- COST ARGS]
  merge.py cost   OWNER/NAME PR HEAD TICKET [-- COST ARGS]
  merge.py settle OWNER/NAME PR TICKET [-- COST ARGS]

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

After a verified merge `cost` also tells a feedback report it landed (FL4, #1848; the feedback-loop
contract v1 in OpenWiz): for a pull request in any openwizdev repository, each openwizdev/OpenWiz issue
it closes that carries a report link (a record author's issue whose body ends with a blank line and
`Report: #<report>`) leads to its report, which gets `Landed: the fix for this report merged in
<owner>/<repo>#<PR> and will ship in OpenWiz <milestone>.` once, ever, read back on the report. It adds
`; landed posted <id> on openwizdev/OpenWiz#<report>`,
`; landed already posted <id>` (a record author's landed comment is there), `; landed none: <why>` (no
report, or no `X.Y.Z` milestone) or `; landed unknown: <why>` (reconcile on the next run, never retried
blind); a merge that closes no linked issue adds nothing.

`settle` is the cost a queued merge still owes: it reads the newest record
author's queue receipt on the pull request and runs `cost` at that commit
(`refused: ...` while it isn't merged there), or prints `no queued merge`.
"""
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('launch_fleet_post', HERE / 'post.py')
post = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(post)
Stop = post.Stop

QUERY = '''query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) { defaultBranchRef { name } pullRequest(number: $number) {
    state baseRefName headRefOid isMergeQueueEnabled isInMergeQueue mergeable mergeCommit { oid }
    mergeQueueEntry { headCommit { oid } } repository { nameWithOwner }
    closingIssuesReferences(first: 50) { pageInfo { hasNextPage } nodes { number body repository { nameWithOwner } } }
    timelineItems(itemTypes: [REMOVED_FROM_MERGE_QUEUE_EVENT], last: 1) {
      nodes { ... on RemovedFromMergeQueueEvent { createdAt reason } } }
    commits(last: 1) { nodes { commit { oid statusCheckRollup { contexts(first: 50) { pageInfo { hasNextPage }
      nodes { __typename ... on CheckRun { name conclusion } ... on StatusContext { context state } } } } } } } } } }'''
COST = 'tools/collector/cost_line.py'
SHA = re.compile(r'[0-9a-f]{40}')
TICKET = re.compile(r'(?:([A-Za-z0-9-]+/[A-Za-z0-9_.-]+)#)?([1-9][0-9]{0,11})')
QUEUED = re.compile(r'launch-fleet: merge queued ([0-9a-f]{40})\b')
# The feedback-loop contract v1 (#1840): its destination, marker, report link, version and landed comment,
# for a fix in any repository of the destination's owner, named in full (planner ruling 7040055832 on #1848).
DESTINATION = 'openwizdev/OpenWiz'
OWNER = DESTINATION.split('/')[0]
MARKER = re.compile(r'OpenWiz feedback operation [0-9a-f]{32}')
LINK = re.compile(r'Report: #([1-9][0-9]*)')
VERSION = re.compile(r'[0-9]+\.[0-9]+\.[0-9]+')
LANDED = 'Landed: the fix for this report merged in {pr} and will ship in OpenWiz {version}.'
LANDED_ANY = re.compile(r'Landed: the fix for this report merged in [A-Za-z0-9-]+/[A-Za-z0-9_.-]+#[1-9][0-9]* '
                        r'and will ship in OpenWiz [0-9]+\.[0-9]+\.[0-9]+\.')


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


def lines(body):
    return (body or '').replace('\r\n', '\n').split('\n') if isinstance(body, str) else []


def report_link(body):
    """The report number a body's last line links, after a blank line, as its only link line; else None."""
    found = lines(body)
    links = [x for x in found if LINK.fullmatch(x)]
    return int(LINK.fullmatch(found[-1]).group(1)) if len(found) > 2 and found[-2] == '' and links == found[-1:] \
        else None


def issue(repo, number):
    value = post.read_json('api', f'repos/{repo}/issues/{number}')
    return value if isinstance(value, dict) and value.get('number') == number else None


def is_report(value):
    """An issue (never a pull request) labelled `feedback`, or whose body ends with the marker after a blank line."""
    labels = {x.get('name') for x in value.get('labels') or [] if isinstance(x, dict)}
    found = lines(value.get('body'))
    return 'pull_request' not in value and ('feedback' in labels or (
        len(found) > 1 and found[-2] == '' and MARKER.fullmatch(found[-1]) is not None))


def land(fix, report, auth):
    """Post the landed comment naming FIX (`owner/repo#n`) on one report once, read back; one outcome."""
    repo, at = DESTINATION, f'{DESTINATION}#{report}'
    value = issue(repo, report)
    if value is None:
        return f'landed unknown: {at} could not be read'
    if not is_report(value):
        return f'landed none: {at} is not a report'
    milestone = value.get('milestone')
    version = milestone.get('title') if isinstance(milestone, dict) else None
    if not (isinstance(version, str) and VERSION.fullmatch(version)):
        return f'landed none: {at} has no version milestone'
    before = post.thread(repo, report)
    if before is None:
        return f'landed unknown: {at} could not be read, so nothing was posted'
    for c in before:
        if post.ours(c, auth) and LANDED_ANY.fullmatch(c.get('body') or ''):
            return f"landed already posted {c.get('id')}"
    body = LANDED.format(pr=fix, version=version)
    made = post.read_json('api', '--method', 'POST', f'repos/{repo}/issues/{report}/comments', '-f', f'body={body}')
    if not isinstance(made, dict) or type(made.get('id')) is not int:
        return f'landed unknown: the write on {at} returned no receipt, so reconcile {at} and never retry blind'
    after = post.thread(repo, report) or []
    if not any(c.get('id') == made['id'] and c.get('body') == body and post.ours(c, auth) for c in after):
        return f'landed unknown: the comment on {at} could not be read back, so reconcile {at}'
    return f"landed posted {made['id']} on {at}"


def landed(repo, number, p):
    """`; landed ...` per report the merged pull request's closed issues link to, or '' (FL4, #1848)."""
    if repo.split('/')[0].casefold() != OWNER.casefold():
        return ''
    name = ((p or {}).get('repository') or {}).get('nameWithOwner')
    if not (isinstance(name, str) and post.REPO.fullmatch(name) and name.casefold() == repo.casefold()):
        return f'; landed unknown: the repository of PR #{number} could not be read'
    refs = (p or {}).get('closingIssuesReferences') or {}
    if (refs.get('pageInfo') or {}).get('hasNextPage') is not False:
        return f'; landed unknown: the issues PR #{number} closes could not be read whole'
    linked = sorted({i['number'] for i in refs.get('nodes') or [] if isinstance(i, dict)
                     and type(i.get('number')) is int and report_link(i.get('body'))
                     and str((i.get('repository') or {}).get('nameWithOwner')).casefold() == DESTINATION.casefold()})
    if not linked:
        return ''
    try:
        auth = post.authors(DESTINATION)
    except Stop as outcome:
        return f'; landed unknown: {outcome}'
    reports, told = set(), []
    for n in linked:  # the link counts only as read whole, on a record author's issue
        value = issue(DESTINATION, n)
        if value is None:
            told.append(f'landed unknown: {DESTINATION}#{n} could not be read')
        elif post.ours(value, auth) and report_link(value.get('body')):
            reports.add(report_link(value.get('body')))
    told += [land(f'{name}#{number}', r, auth) for r in sorted(reports)]
    return ''.join('; ' + x for x in told)


def cost(repo, number, head, ticket, extra=()):
    main, p = snapshot(repo, number)
    state = where(main, p, head)
    if not state.startswith('merged '):
        raise Stop(f'refused: no verified merge at {head} ({state})')
    home, ticket = ticket_of(repo, number, p, ticket)
    told = landed(repo, number, p)
    try:
        return _cost(repo, number, home, ticket, extra) + told
    except Stop as outcome:
        raise Stop(f'{outcome}{told}')


def _cost(repo, number, home, ticket, extra):
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
