#!/usr/bin/env python3
"""Merge one approved pull request at its exact head, then post the ticket's cost and the landed comment
(WS8, #1181; WS26, #1670; FL4, #1848).

  merge.py read   OWNER/NAME PR HEAD
  merge.py admit  OWNER/NAME PR HEAD CHECKS
  merge.py merge  OWNER/NAME PR HEAD CHECKS BODY --ticket TICKET [--base-rule-checked] [-- COST ARGS]
  merge.py cost   OWNER/NAME PR HEAD TICKET [-- COST ARGS]
  merge.py settle OWNER/NAME PR TICKET [-- COST ARGS]
  merge.py look   OWNER/NAME PR HEAD --ticket TICKET
  merge.py ask    OWNER/NAME PR HEAD CHECKS --ticket TICKET EVIDENCE-FILE

`read` prints where the pull request stands: `merged <commit>`, `queued`,
`open, the merge queue is on|off[; it left the queue at <time>: <reason>]` or
`stop: <why>`. `admit` prints `admit: ...`, `base rule: no merge queue;
mergeable: <state>` or `wait: <why>`; CHECKS are fleet.md's required checks,
comma-separated. Both only read.

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

The late look (RC3, #1831; contracts/checkpoints.v1.md): `merge` holds the
final merge of a user-visible spec (the merge of its last open planned ticket,
where the spec answers `User-visible: yes` or `yes, a release`, or its answers
are invalid) until a record author's late-look record by the owner approves
this head after its evidence ask: `held: ask-due|look-due|changes-asked: ...`
(exit 1, nothing written). Every other merge, and a spec answered `no` or
planned before the contract, flows as today. A spec, its planned tickets, its
comments or the contract it can't read is `unknown: ...` and merges nothing.
A sibling ticket whose closing pull request is in the merge queue or merged
counts as closed, so two tickets queued one after the other leave the later
one held. A held head that conflicts is `blocked: not mergeable: ...`, never
offered an ask. `look` prints the same reading (`flows: ...`, `released: ...`
or `held: ...`) and only reads. `ask` posts the contract's evidence ask on the
spec: its opening line for PR and HEAD, then EVIDENCE-FILE's `Evidence:` and
`Look for:` lines. It posts only for a head whose CHECKS are green and that is
mergeable, refuses an ask the contract refuses (code links included) and posts
one ask per head (`ask posted <id>`, `ask already posted <id>`).
"""
import datetime
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('launch_fleet_post', HERE / 'post.py')
post = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(post)
Stop = post.Stop
_spec = importlib.util.spec_from_file_location('launch_fleet_records', HERE / 'records.py')
records = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(records)
_spec = importlib.util.spec_from_file_location('launch_fleet_queue', HERE / 'queue.py')
decider = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(decider)

QUERY = '''query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) { defaultBranchRef { name } pullRequest(number: $number) {
    id state baseRefName headRefOid isMergeQueueEnabled isInMergeQueue mergeable mergeCommit { oid }
    mergedBy { login } mergeQueueEntry { headCommit { oid } } repository { nameWithOwner }
    closingIssuesReferences(first: 50) { pageInfo { hasNextPage } nodes { number body repository { nameWithOwner } } }
    timelineItems(itemTypes: [REMOVED_FROM_MERGE_QUEUE_EVENT], last: 100) {
      nodes { ... on RemovedFromMergeQueueEvent { createdAt reason beforeCommit { oid } } } }
    enqueued: timelineItems(itemTypes: [ADDED_TO_MERGE_QUEUE_EVENT], last: 1) {
      nodes { ... on AddedToMergeQueueEvent { id createdAt enqueuer { login } } } }
    commits(last: 1) { nodes { commit { oid statusCheckRollup { contexts(first: 50) { pageInfo { hasNextPage }
      nodes { __typename ... on CheckRun { name status conclusion } ... on StatusContext { context state } } } } } } } } } }'''
ENQUEUE = '''mutation($id: ID!, $head: GitObjectID!) {
  enqueuePullRequest(input: {pullRequestId: $id, expectedHeadOid: $head}) { mergeQueueEntry { headCommit { oid } } } }'''
COST = 'tools/collector/cost_line.py'
SHA = re.compile(r'[0-9a-f]{40}')
TICKET = re.compile(r'(?:([A-Za-z0-9-]+/[A-Za-z0-9_.-]+)#)?([1-9][0-9]{0,11})')
QUEUED = re.compile(r'launch-fleet: merge queued ([0-9a-f]{40})\b')
RERAN = 'every required check ran again after the removal and is green'
CLAIM = re.compile(r'\n\nRe-queue claimed at ([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z)\.$')
CLAIM_HOLDS = datetime.timedelta(minutes=15)
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
    subIssues(first: 100) { pageInfo { hasNextPage } nodes { number state repository { nameWithOwner }
      closedByPullRequestsReferences(first: 20, includeClosedPrs: true) { pageInfo { hasNextPage }
        nodes { state isInMergeQueue } } } } } } } }'''
# The feedback-loop contract v1 (#1840): its destination, marker, report link, version and landed comment,
# for a fix in any repository of the destination's owner, named in full (planner ruling 7040055832 on #1848).
DESTINATION = 'openwizdev/OpenWiz'
OWNER = DESTINATION.split('/')[0]
MARKER = re.compile(r'OpenWiz feedback operation [0-9a-f]{32}')
LINK = re.compile(r'Report: #([1-9][0-9]*)')
VERSION = re.compile(r'[0-9]+\.[0-9]+\.[0-9]+')
PULL_REQUEST = re.compile(r'openwizdev/[A-Za-z0-9._-]+#[1-9][0-9]*')
LANDED = 'Landed: the fix for this report merged in {pr} and will ship in OpenWiz {version}.'
LANDED_ANY = re.compile(r'Landed: the fix for this report merged in openwizdev/[A-Za-z0-9._-]+#[1-9][0-9]* '
                        r'and will ship in OpenWiz [0-9]+\.[0-9]+\.[0-9]+\.')
MERGE_HELP = (
    '`merge` reads, admits and merges HEAD, never with `--admin`, and records the outcome. With the merge queue '
    'on, it first refuses while a required check on HEAD is still running (`refused: its required checks are '
    'running: ...`, exit 1, nothing enqueued or recorded), then enqueues HEAD pinned (`enqueuePullRequest` with '
    '`expectedHeadOid`) and records the queue receipt (`launch-fleet: merge queued <commit>`) only after it reads '
    'the queue entry back: `queued; recorded <id>` (exit 0). An enqueue that does not read back as queued prints '
    "`not queued: <GitHub's reason>; nothing was recorded ...` (exit 1), or `pending: ...` (exit 0, read again next "
    'wake) when the call succeeded but it still reads open. A pull request read as queued without its receipt gets '
    'one then (`queued; recorded <id>`, or `queued; receipt unconfirmed ...`, exit 1). The receipt is what `settle` '
    'reads. Out of the queue, a head with its receipt or a `launch-fleet: merge dropped` record, or whose removal of '
    "HEAD came after the fleet's own latest enqueue, acts on `queue.py read` (also on any enqueue's read-back): "
    '`dropped; recorded <id>` posts the drop record once, `waiting: <cause>` and `pending: ...` write nothing, a '
    'second drop, a merge conflict or a person\'s removal is `blocked: ...`, and once every required check ran '
    'green after the removal it passes the late look again, claims its one retry on the drop record (`Re-queue '
    'claimed at <time>.`, held 15 minutes while it does not read back) and prints `re-queued; ...`. Queue facts it '
    'cannot read or that disagree are `pending: ...`. Two runs on one machine take turns, and a drop record or receipt '
    'two runs posted at once is kept once. Without a merge queue it merges with `gh pr merge --merge --match-head-commit` only with '
    "`--base-rule-checked`, after you applied fleet.md's base rule and `fleet.sh every` still prints this merge line, "
    'and reads it back: `merged <commit>; cost ...` (exit 0). Anything else is `blocked: <why>; recorded <id>` '
    '(exit 1). TICKET is checked before any write. BODY names the APPROVE and the plan approval that allowed it.')
SETTLE_HELP = (
    '`settle` is the cost a merge still owes: it runs `cost` at the merged head when a record author\'s queue '
    'receipt names that head, or a record author enqueued or merged it, so a merge whose cost write failed still gets '
    'its line once, even after an earlier head\'s receipt. Before a merge it runs `cost` at the newest receipt\'s '
    'commit (`refused: ...` while it isn\'t merged there); otherwise it prints `no queued merge` (with the landed '
    'outcome when the pull request merged). Any '
    '`landed unknown:` makes it `unknown: ...` (exit 1), so the work stays open for a later wake, which reads the '
    'report again. A landed comment is read back after posting; when an earlier one is there too, the earliest '
    'stands and ours is deleted, and a later duplicate naming this fix, at any milestone, that a refused delete left '
    'behind is deleted on the next run, read back, before it counts as posted.')


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


def running(p, checks):
    commit = ((p.get('commits') or {}).get('nodes') or [{}])[0].get('commit') or {}
    nodes = ((commit.get('statusCheckRollup') or {}).get('contexts') or {}).get('nodes') or []
    busy = {n.get('name') or n.get('context') for n in nodes
            if (n.get('__typename') == 'CheckRun' and n.get('status') != 'COMPLETED')
            or (n.get('__typename') == 'StatusContext' and n.get('state') in ('PENDING', 'EXPECTED'))}
    return [c for c in checks if c in busy]


def enqueue(p, head):
    if not isinstance(p.get('id'), str):
        return "the pull request's id could not be read"
    try:
        r = subprocess.run(['gh', 'api', 'graphql', '-f', f"id={p['id']}", '-f', f'head={head}',
                            '-f', f'query={ENQUEUE}'], capture_output=True, text=True, timeout=60,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return 'the enqueue call did not finish'
    why = ' '.join(r.stderr.split())[:200] or 'the enqueue call failed'
    return None if r.returncode == 0 else why


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
    body = LANDED.format(pr=fix, version=version)
    found = [c['id'] for c in before if post.ours(c, auth) and type(c.get('id')) is int
             and LANDED_ANY.fullmatch(c.get('body') or '')]
    if found:
        mine = LANDED.split('{version}')[0].format(pr=fix)
        return drop(repo, report, min(found), [c['id'] for c in before if c.get('id') in found
                                               and c['id'] != min(found) and c['body'].startswith(mine)])
    made = post.read_json('api', '--method', 'POST', f'repos/{repo}/issues/{report}/comments', '-f', f'body={body}')
    if not isinstance(made, dict) or type(made.get('id')) is not int:
        return f'landed unknown: the write on {at} returned no receipt, so reconcile {at} and never retry blind'
    after = post.thread(repo, report) or []
    if not any(c.get('id') == made['id'] and c.get('body') == body and post.ours(c, auth) for c in after):
        return f'landed unknown: the comment on {at} could not be read back, so reconcile {at}'
    # Another run may have read before either wrote (#127 R2, ruling 7044043399 on #1848): the
    # earliest landed comment stands, and a later one of ours is deleted.
    earliest = min(c['id'] for c in after if post.ours(c, auth) and type(c.get('id')) is int
                   and LANDED_ANY.fullmatch(c.get('body') or ''))
    if earliest == made['id']:
        return f"landed posted {made['id']} on {at}"
    return drop(repo, report, earliest, [made['id']])


def drop(repo, report, earliest, duplicates):
    at = f'{repo}#{report}'
    for d in duplicates:
        post.gh('api', '--method', 'DELETE', f'repos/{repo}/issues/comments/{d}')
    back = post.thread(repo, report) if duplicates else []
    kept = [d for d in duplicates if back is None or any(c.get('id') == d for c in back)]
    if kept:
        return f'landed unknown: our duplicate {kept[0]} on {at} could not be deleted, so reconcile {at}'
    return f'landed already posted {earliest}'


def landed(repo, number, p):
    """`; landed ...` per report the merged pull request's closed issues link to, or '' (FL4, #1848)."""
    if repo.split('/')[0].casefold() != OWNER.casefold():
        return ''
    name = ((p or {}).get('repository') or {}).get('nameWithOwner')
    if not (isinstance(name, str) and post.REPO.fullmatch(name) and name.casefold() == repo.casefold()):
        return f'; landed unknown: the repository of PR #{number} could not be read'
    if not PULL_REQUEST.fullmatch(f'{name}#{number}'):
        return ''
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
    if not Path(COST).is_file():
        body = 'launch-fleet: cost: ' + _agents_line(repo, home, ref, number, ticket)
    elif not same:
        body += "the cost command costs only tickets in the pull request's repository"
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



USAGE_WINDOW_DAYS = 7


def _amount(value, unit, places):
    if value is None:
        return 'unknown ' + unit
    text = f'{round(value, places):,.{places}f}'
    return (text.rstrip('0').rstrip('.') if places else text) + ' ' + unit


def _role(credits):
    return 'unknown' if credits is None else _amount(credits, 'credits', 2) + ', ' + _amount(None, 'tokens', 0)


def _cost_line(ref, ticket, builder, reviewer):
    total = None if builder is None or reviewer is None else builder + reviewer
    return (f'Ticket #{ticket} cost {ref}: builder {_role(builder)}; reviewer {_role(reviewer)}; '
            'CI unknown; total ' + ('unknown' if total is None else
                                    ', '.join((_amount(total, 'credits', 2), _amount(None, 'tokens', 0),
                                               _amount(None, 'runner minutes', 1)))))


def _usage(thread):
    try:
        r = subprocess.run(['room-cli', 'usage', thread, '--json'], capture_output=True, text=True, timeout=60,
                           stdin=subprocess.DEVNULL)
        if r.returncode:
            return None
        history = json.loads(r.stdout, object_pairs_hook=records.unique).get('history')
        credits, hours = history.get('credits'), history.get('hours')
        if (history.get('id') != thread or type(credits) not in (int, float) or not 0 <= credits < float('inf')
                or not isinstance(hours, list) or not hours):
            return None
        first = min(datetime.datetime.fromisoformat(h['hour'].replace('Z', '+00:00')) for h in hours)
        today = datetime.datetime.now(datetime.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        return None if first <= today - datetime.timedelta(days=USAGE_WINDOW_DAYS - 1) else credits
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError, TypeError, KeyError):
        return None


def _driven(number, threads, runs, here=True):
    return (f'run:{number}' in threads or runs in (records.UNREADABLE, records.MISSING, None)
            or (here and isinstance(runs, dict) and str(number) in runs))


REVIEW_RECORD = re.compile(rf'launch-fleet: (?:review [a-z]+(?: [a-z]+)?|re-check sent) ({records.SHA})\b')
DRIVER_LINE = ('Driver review:', 'Driver re-check:')


def _elsewhere(claim, places, repo, number):
    for place in places:
        found = post.read_json('api', f'repos/{place}/issues/comments/{claim}')
        url = found.get('issue_url') if isinstance(found, dict) else None
        if isinstance(url, str) and not url.casefold().endswith(f'/repos/{repo}/issues/{number}'.casefold()):
            return True
    return False


def _reviewers(repo, home, number, threads):
    try:
        auth, items = post.authors(repo), post.thread(repo, number)
    except Stop:
        return None
    if items is None:
        return None
    claims = set()
    for c in items:
        lines = (c.get('body') or '').splitlines() if post.ours(c, auth) else []
        if not lines or not REVIEW_RECORD.match(lines[0]):
            continue
        if lines[1:2] and lines[1].startswith(DRIVER_LINE):
            return None
        claims.add(str(c.get('id')))
    prefix, held = f'review:{number}:', {}
    for key, thread in threads.items():
        if not key.startswith(prefix):
            continue
        rest = key[len(prefix):]
        claim = re.fullmatch(r'claim:([0-9]+)', rest)
        if not (claim or re.fullmatch(records.SHA, rest)):
            return None
        held.setdefault(thread, set()).update([claim[1]] if claim else [])
    places = list(dict.fromkeys([repo, home]))
    mine = set()
    for thread, ids in held.items():
        if ids and ids <= claims:
            mine.add(thread)
        elif not ids or ids & claims or not all(_elsewhere(i, places, repo, number) for i in ids):
            return None
    return mine


def _agents_line(repo, home, ref, number, ticket):
    try:
        threads = records.private_state(home) if os.environ.get('LAUNCH_FLEET_STATE') else None
        runs = records.driver_runs(home)
    except (OSError, ValueError):
        threads = runs = None
    if not threads:
        return _cost_line(ref, ticket, None, None)
    builder = None if _driven(ticket, threads, runs) else threads.get(f'builder:{ticket}')
    here = home.casefold() == repo.casefold()
    reviewers = None if _driven(number, threads, runs, here) else _reviewers(repo, home, number, threads)
    read = {t: _usage(t) for t in sorted((reviewers or set()) | ({builder} if builder else set()))}
    builder_credits = read[builder] if builder else None
    reviewer_credits = (None if not reviewers or threads.get(f'builder:{ticket}') in reviewers
                        or None in (read[t] for t in reviewers) else sum(read[t] for t in sorted(reviewers)))
    return _cost_line(ref, ticket, builder_credits, reviewer_credits)


def enqueued_by_us(repo, p):
    nodes = ((p or {}).get('enqueued') or {}).get('nodes') or []
    login = ((nodes[-1] if isinstance(nodes[-1], dict) else {}).get('enqueuer') or {}).get('login') if nodes else None
    return login is not None and post.ours({'user': {'login': login}}, post.authors(repo))


def merged_by_us(repo, p):
    login = ((p or {}).get('mergedBy') or {}).get('login')
    return isinstance(login, str) and post.ours({'user': {'login': login}}, post.authors(repo))


def settle(repo, number, ticket, extra=()):
    found = receipts(repo, number)
    main, p = snapshot(repo, number)
    head = (p or {}).get('headRefOid')
    merged = where(main, p, head).startswith('merged ')
    if merged and (any(h == head for h, _ in found) or enqueued_by_us(repo, p) or merged_by_us(repo, p)):
        told = cost(repo, number, head, ticket, extra)
    elif found and not merged:
        told = cost(repo, number, found[-1][0], ticket, extra)
    else:  # a direct merge still owes its landed comment (#127 R1)
        told = 'no queued merge' + (landed(repo, number, p) if merged else '')
    if '; landed unknown: ' in told:
        raise Stop('unknown: ' + told)
    return told


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


def closing(n):
    """Whether a planned ticket is closed or on its way: a closing pull request merged or in the merge queue."""
    refs = n['closedByPullRequestsReferences']
    prs = [(r['state'], r['isInMergeQueue']) for r in refs['nodes']]
    if (n['state'] not in ('OPEN', 'CLOSED') or refs['pageInfo']['hasNextPage'] is not False
            or not all(st in ('OPEN', 'CLOSED', 'MERGED') and type(q) is bool for st, q in prs)):
        raise TypeError(n)
    return n['state'] == 'CLOSED' or any(st == 'MERGED' or q for st, q in prs)


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
        states = {(n['repository']['nameWithOwner'].casefold(), n['number']): closing(n) for n in nodes}
        if not (isinstance(where_, str) and post.REPO.fullmatch(where_) and type(number) is int
                and isinstance(body, str) and type(page) is bool):
            raise TypeError(spec)
    except (TypeError, KeyError, AttributeError):
        raise Stop(f'unknown: the spec of {home}#{ticket} could not be read; nothing was merged')
    if page:
        raise Stop(f"unknown: spec {where_}#{number}'s planned tickets could not be read whole; nothing was merged")
    states.pop((home.casefold(), ticket), None)
    return where_, number, body, all(states.values())


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


def ask(repo, number, head, checks, ticket, path):
    try:
        text = Path(path).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        raise Stop(f'refused: {path} could not be read')
    body = f'launch-fleet: late look asked #{number} at {head}\n\n' + text.strip()
    main, p = snapshot(repo, number)
    state = where(main, p, head)
    if not state.startswith('open'):
        raise Stop(f'refused: no ask for a pull request that is not open at {head} ({state})')
    admit = admission(main, p, head, checks)
    if admit.startswith('wait: ') or p['mergeable'] != 'MERGEABLE':
        why = admit[6:] if admit.startswith('wait: ') else f"mergeable: {p['mergeable']}"
        raise Stop('refused: no ask for a head that cannot merge: ' + why)
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



def serial(repo, number):
    handle = open(Path(tempfile.gettempdir()) / f"openwiz-merge-{repo.replace('/', '-')}-{number}.lock", 'a')
    fcntl.flock(handle, fcntl.LOCK_EX)
    return handle


def first_line(c):
    return (c.get('body') or '').replace('\r\n', '\n').split('\n', 1)[0]


def records_at(repo, number, head):
    auth = post.authors(repo)
    items = post.thread(repo, number)
    if items is None:
        raise Stop(f'unknown: #{number} could not be read; run it again next wake')
    mine = sorted((c for c in items if post.ours(c, auth) and type(c.get('id')) is int), key=lambda c: c['id'])
    return ([c['id'] for c in mine if (m := QUEUED.match(first_line(c))) and m.group(1) == head],
            [c for c in mine if first_line(c).startswith(f'launch-fleet: merge dropped {head}: ')])


def once(repo, number, made, same):
    auth = post.authors(repo)
    items = post.thread(repo, number)
    twins = sorted(c['id'] for c in items or [] if post.ours(c, auth) and type(c.get('id')) is int
                   and same(first_line(c)))
    if not twins:
        raise Stop(f'unknown: #{number} could not be read back after {made} was posted; read #{number} before any retry')
    if twins[0] == made:
        return made
    post.gh('api', '--method', 'DELETE', f'repos/{repo}/issues/comments/{made}')
    back = post.thread(repo, number)
    if back is None or any(c.get('id') == made for c in back):
        raise Stop(f'unknown: our duplicate {made} on #{number} could not be deleted; reconcile #{number}')
    return twins[0]


def tied(repo, p, head):
    added = ((p.get('enqueued') or {}).get('nodes') or [None])[-1] or {}
    left = ((p.get('timelineItems') or {}).get('nodes') or [None])[-1] or {}
    at = added.get('createdAt')
    if isinstance(at, str) and isinstance(left.get('createdAt'), str) and left['createdAt'] >= at \
            and (left.get('beforeCommit') or {}).get('oid') == head and enqueued_by_us(repo, p):
        return at
    return None


def verdict(repo, number, head, checks, since=None):
    real = decider.fleet_records

    def counted(*args):
        found, drops = real(*args)
        return found + [at for at, _ in drops] + ([since] if since else []), drops

    decider.fleet_records = counted
    try:
        return decider.read(repo, number, head, checks)[0]
    except decider.Unknown as why:
        return f'unknown: {why}'
    finally:
        decider.fleet_records = real


def dropped(repo, number, head, line, p):
    if not line.startswith(f'dropped {head}: '):
        return None
    reason, at = line.split(': ', 1)[1].rsplit(' at ', 1)
    left = [n for n in (p.get('timelineItems') or {}).get('nodes') or []
            if isinstance(n, dict) and n.get('createdAt') == at and n.get('reason') == reason]
    if not left:
        return f'pending: its removal at {at} does not read on the pull request yet; read it again next wake'
    oid = (left[-1].get('beforeCommit') or {}).get('oid')
    if not (isinstance(oid, str) and SHA.fullmatch(oid)):
        raise Stop('unknown: the commit that left the merge queue could not be read; nothing was enqueued or '
                   'recorded, so run it again next wake')
    if oid != head:
        return f'pending: its removal at {at} took {oid} out of the queue, not {head}; read it again next wake'
    body = 'launch-fleet: merge ' + line
    try:
        made = int(post.comment(repo, number, body).split()[-1])
        return f'dropped; recorded {once(repo, number, made, lambda first: first == body)}'
    except Stop as outcome:
        raise Stop(f'dropped; not recorded ({outcome}); run it again next wake')


def gate(repo, number, head, ticket, p, blocked):
    why, ref, _ = look(repo, number, head, ticket, p)
    if why == 'ask-due' and p['mergeable'] == 'CONFLICTING':
        blocked('not mergeable: CONFLICTING')
    if why not in ('flows', 'released'):
        raise Stop(held(why, ref))


def claim(repo, number, head):
    _, drops = records_at(repo, number, head)
    if not drops:
        return 'pending: its drop record does not read yet; read it again next wake'
    now = datetime.datetime.now(datetime.timezone.utc)
    for c in drops:
        m = CLAIM.search((c.get('body') or '').replace('\r\n', '\n'))
        at = m and datetime.datetime.strptime(m.group(1), '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
        if at and now - at < CLAIM_HOLDS:
            return (f'pending: its one re-queue was claimed at {m.group(1)} and does not read back yet; '
                    'read it again next wake')
    body = first_line(drops[0]) + f"\n\nRe-queue claimed at {now.strftime('%Y-%m-%dT%H:%M:%SZ')}."
    try:
        post.edit(repo, drops[0]['id'], body)
    except Stop as outcome:
        raise Stop(f'not re-queued: its re-queue claim was not recorded ({outcome}); nothing was enqueued, '
                   'so run it again next wake')
    return None


def requeue(repo, number, head, checks, ticket, p, kept, since, blocked, receipt):
    line = verdict(repo, number, head, checks, since)
    told = dropped(repo, number, head, line, p)
    if told:
        return told
    if line.startswith(f'wait {head}: '):
        return 'waiting: ' + line.split(': ', 1)[1]
    if line.startswith(f'blocked {head}: '):
        blocked(line.split(': ', 1)[1])
    if line.startswith('unknown: '):
        return f"pending: {line.split(': ', 1)[1]}; read it again next wake"
    if not line.startswith(f'requeue {head}: '):
        return f'pending: the queue reads {line}; read it again next wake'
    if line != f'requeue {head}: {RERAN}':
        return ('waiting: ' + line.split(': ', 1)[1] + ', but nothing ties those runs to the failed merge group, '
                'so it goes back in only once every required check ran again after the removal and is green')
    gate(repo, number, head, ticket, p, blocked)
    told = claim(repo, number, head)
    if told:
        return told
    refused = enqueue(p, head)
    main, back = snapshot(repo, number)
    state = where(main, back, head)
    if state == 'queued':
        if kept is not None:
            return f're-queued; its receipt {kept} still names {head}'
        return f"re-queued; recorded {receipt('re-queued; receipt unconfirmed')}"
    if state.startswith('open'):
        told = dropped(repo, number, head, verdict(repo, number, head, checks, since), back)
        if told:
            return told
    if refused is None:
        return 'pending: the enqueue call succeeded but it still reads open; its claim holds, so read it again next wake'
    raise Stop(f'not re-queued: {refused}; its claim holds 15 minutes, so run it again next wake')


def merge(repo, number, head, checks, body, ticket, checked, extra):
    def blocked(why):
        raise Stop(f'blocked: {why}; recorded ' + record(repo, number, f'launch-fleet: merge blocked {head}: {why}'))

    def receipt(fail):
        mine = [i for h, i in receipts(repo, number) if h == head]
        if mine:
            return mine[-1]
        text = f'launch-fleet: merge queued {head}: {body}'
        try:
            made = int(post.comment(repo, number, text).split()[-1])
            return once(repo, number, made, lambda first: bool(m := QUEUED.match(first)) and m.group(1) == head)
        except Stop as outcome:
            raise Stop(f'{fail} ({outcome}); run it again next wake')

    main, p = snapshot(repo, number)
    state = where(main, p, head)
    ticket_of(repo, number, p, ticket)
    if state.startswith('merged '):
        return state + '; ' + cost(repo, number, head, ticket, extra)
    if state == 'queued':
        if any(h == head for h, _ in receipts(repo, number)):
            return 'queued; the queue merges it or lets it go'
        return 'queued; recorded ' + str(receipt('queued; receipt unconfirmed'))
    if state.startswith('stop: OPEN, in the merge queue: '):
        return (f"pending: its queue facts read {state[6:]}, with merge queue {p.get('isMergeQueueEnabled')} and "
                f'entry {p.get("mergeQueueEntry")}; nothing was written, so read it again next wake')
    if state.startswith('stop: '):
        blocked(state[6:])
    since = tied(repo, p, head)
    kept, drops = records_at(repo, number, head) if p['isMergeQueueEnabled'] is True or since else ([], [])
    if kept or drops or since:
        if '; it left the queue at ' in state:
            left = (((p.get('timelineItems') or {}).get('nodes') or [{}])[-1].get('beforeCommit') or {}).get('oid')
            if not (isinstance(left, str) and SHA.fullmatch(left)):
                raise Stop('unknown: the commit that left the merge queue could not be read; nothing was enqueued or '
                           'recorded, so run it again next wake')
        return requeue(repo, number, head, checks, ticket, p, kept[-1] if kept else None, since, blocked, receipt)
    busy = running(p, checks) if p['isMergeQueueEnabled'] is True else []
    if busy:
        raise Stop('refused: its required checks are running: ' + ', '.join(busy)
                   + '; nothing was enqueued or recorded, so run it again once they finish')
    admit = admission(main, p, head, checks)
    if admit.startswith('wait: '):
        blocked(admit[6:])
    gate(repo, number, head, ticket, p, blocked)
    if admit.startswith('base rule: ') and not checked:
        raise Stop(admit + '; check the base rule and fleet.sh every, then pass --base-rule-checked')
    if admit.startswith('admit: '):
        refused = enqueue(p, head)
        done = refused is None
    else:
        refused, done = None, post.gh('pr', 'merge', str(number), '--repo', repo, '--merge',
                                      '--match-head-commit', head, '--body', body) is not None
    main, back = snapshot(repo, number)
    state = where(main, back, head)
    if state.startswith('merged '):
        return state + '; ' + cost(repo, number, head, ticket, extra)
    if state == 'queued':
        return 'queued; recorded ' + str(receipt('queued; receipt unconfirmed'))
    if admit.startswith('admit: ') and state.startswith('open'):
        line = verdict(repo, number, head, checks, tied(repo, back, head))
        told = dropped(repo, number, head, line, back)
        if told:
            return told
        if line.startswith('unknown: ') and refused is None:
            return f"pending: {line.split(': ', 1)[1]}; nothing was recorded, so read it again next wake"
    if state.startswith('open') and done:
        return 'pending: the merge command succeeded but it still reads open; read it again next wake'
    if admit.startswith('admit: '):
        tail = f'; it reads back as: {state[6:]}' if state.startswith('stop: ') else ''
        raise Stop(f"not queued: {refused or 'the enqueue call succeeded'}{tail}; "
                   'nothing was recorded, so run it again next wake')
    blocked(state[6:] if state.startswith('stop: ') else state)


def main(argv):
    extra = []
    if '--' in argv:
        at = argv.index('--')
        argv, extra = argv[:at], argv[at + 1:]
    usage = __doc__.split('\n\n')[1]
    if argv in (['--help'], ['-h']):
        parts = __doc__.split('\n\n')
        print('\n\n'.join(parts[:3] + [MERGE_HELP] + parts[3:] + [SETTLE_HELP]))
        return 0
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
        elif verb == 'ask' and len(rest) == 4 and rest[1] == '--ticket' and TICKET.fullmatch(rest[2]):
            print(ask(repo, number, head, rest[0].split(','), rest[2], rest[3]))
        elif verb == 'merge' and len(rest) >= 4 and rest[2] == '--ticket' and TICKET.fullmatch(rest[3]) \
                and set(rest[4:]) <= {'--base-rule-checked'}:
            with serial(repo, number):
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
