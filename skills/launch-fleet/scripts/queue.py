#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


post = _load('launch_fleet_post', 'post.py')
records = _load('launch_fleet_records', 'records.py')

QUERY = '''query($owner: String!, $name: String!, $number: Int!, $removed: String, $checks: String) {
  repository(owner: $owner, name: $name) { pullRequest(number: $number) {
    state headRefOid isInMergeQueue mergeCommit { oid } mergeQueueEntry { headCommit { oid } }
    added: timelineItems(itemTypes: [ADDED_TO_MERGE_QUEUE_EVENT], last: 1) {
      nodes { ... on AddedToMergeQueueEvent { createdAt } } }
    removed: timelineItems(itemTypes: [REMOVED_FROM_MERGE_QUEUE_EVENT], first: 100, after: $removed) {
      pageInfo { hasNextPage endCursor } nodes { ... on RemovedFromMergeQueueEvent { createdAt reason actor { login } } } }
    commits(last: 1) { nodes { commit { oid statusCheckRollup { contexts(first: 100, after: $checks) {
      pageInfo { hasNextPage endCursor }
      nodes { __typename ... on CheckRun { name status conclusion startedAt } ... on StatusContext { context state createdAt } } } } } } } } }'''
PAGES = 50
SHA = re.compile(r'[0-9a-f]{40}')
TIME = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z')
REASON = re.compile(r'[a-z][a-z0-9_]{0,63}')
QUEUED = re.compile(r'launch-fleet: merge queued ([0-9a-f]{40})\b')
DROPPED = re.compile(rf'launch-fleet: merge dropped ([0-9a-f]{{40}}): ({REASON.pattern}) at ({TIME.pattern})')
QUEUE_BOT = 'github-merge-queue'
CHECK_CAUSES = ('branch_protection_failure', 'failed_checks')
STATES = ('OPEN', 'CLOSED', 'MERGED')
RUN_STATUS = ('COMPLETED', 'IN_PROGRESS', 'QUEUED', 'WAITING', 'PENDING', 'REQUESTED')
CONCLUSIONS = ('SUCCESS', 'FAILURE', 'CANCELLED', 'SKIPPED', 'NEUTRAL', 'TIMED_OUT', 'ACTION_REQUIRED',
               'STALE', 'STARTUP_FAILURE')
NOT_FAILED = ('SUCCESS', 'SKIPPED', 'NEUTRAL')
CONTEXT_STATES = ('SUCCESS', 'FAILURE', 'ERROR', 'PENDING', 'EXPECTED')
USAGE = '''  queue.py read OWNER/NAME PR HEAD CHECKS

CHECKS are fleet.md's required checks, comma-separated, as for merge.py. It only
reads: one GraphQL query (paged to the end) for the pull request's state, head,
queue entry, latest enqueue, every removal from the queue and every check run on
its head, and the record authors' comments on it, read as merge.py reads them:
the queue receipt `launch-fleet: merge queued <commit>` and the drop record
`launch-fleet: merge dropped <commit>: <reason> at <time>`. It prints one line:

  merged <commit>                      merged (exit 0)
  queued                               in the queue at HEAD (exit 0)
  not queued                           no receipt at HEAD: nothing to judge (exit 0)
  dropped HEAD: <reason> at <time>     a removal after the receipt that no record names yet:
                                       record it (exit 0)
  wait HEAD: <cause>                   a recorded drop whose cause still stands (exit 0)
  requeue HEAD: <why>                  the first recorded drop at HEAD, its cause gone (exit 0)
  blocked HEAD: <why>                  dropped twice at HEAD, or a reason never re-queued
                                       automatically (exit 1)
  unknown: <why>                       a fact unreadable, incomplete or inconsistent (exit 2)

A drop's cause is gone only for GitHub's reasons `branch_protection_failure` and
`failed_checks`, removed by `github-merge-queue`, when nothing on HEAD is running,
every required check's latest run on HEAD is green, and either each of those runs
started after the removal or every failed run on HEAD was a cancelled duplicate (a
CANCELLED run followed by a green run of the same check, as on #2253). A merge
conflict, a person's removal and any other reason are blocked. Bad arguments
print this usage on stderr and exit 2, reading nothing.
'''


class Unknown(Exception):
    pass


def need(ok, why):
    if not ok:
        raise Unknown(why)


def exact(value, keys, why):
    need(isinstance(value, dict) and set(value) == set(keys), why)
    return value


def time_of(value, why):
    need(isinstance(value, str) and TIME.fullmatch(value), why)
    return value


def page(owner, name, number, removed, checks):
    args = ['api', 'graphql', '-f', f'owner={owner}', '-f', f'name={name}', '-F', f'number={number}',
            *(['-f', f'removed={removed}'] if removed else ['-F', 'removed=null']),
            *(['-f', f'checks={checks}'] if checks else ['-F', 'checks=null']), '-f', f'query={QUERY}']
    text = post.gh(*args)
    try:
        value = json.loads(text, object_pairs_hook=records.unique) if text is not None else None
    except ValueError:
        value = None
    need(isinstance(value, dict) and set(value) == {'data'} and isinstance(value['data'], dict),
         'the queue facts could not be read')
    repo = exact(value['data'], ['repository'], 'the queue facts could not be read')['repository']
    p = exact(repo, ['pullRequest'], 'the repository could not be read')['pullRequest']
    p = exact(p, ['state', 'headRefOid', 'isInMergeQueue', 'mergeCommit', 'mergeQueueEntry', 'added', 'removed',
                  'commits'], 'the pull request could not be read whole')
    need(p['state'] in STATES and isinstance(p['headRefOid'], str) and SHA.fullmatch(p['headRefOid'])
         and type(p['isInMergeQueue']) is bool, 'the pull request could not be read whole')
    merge = p['mergeCommit']
    need(merge is None or (isinstance(exact(merge, ['oid'], 'its merge commit could not be read')['oid'], str)
                           and SHA.fullmatch(merge['oid'])), 'its merge commit could not be read')
    entry = p['mergeQueueEntry']
    if entry is not None:
        oid = exact(exact(entry, ['headCommit'], 'its queue entry could not be read')['headCommit'], ['oid'],
                    'its queue entry could not be read')['oid']
        need(isinstance(oid, str) and SHA.fullmatch(oid), 'its queue entry could not be read')
    added = exact(p['added'], ['nodes'], 'its latest enqueue could not be read')['nodes']
    need(isinstance(added, list) and len(added) <= 1, 'its latest enqueue could not be read')
    for n in added:
        time_of(exact(n, ['createdAt'], 'its latest enqueue could not be read')['createdAt'],
                'its latest enqueue could not be read')
    removed = exact(p['removed'], ['pageInfo', 'nodes'], 'its removals could not be read')
    for n in removed['nodes'] if isinstance(removed['nodes'], list) else [None]:
        exact(n, ['createdAt', 'reason', 'actor'], 'a removal could not be read')
        time_of(n['createdAt'], 'a removal time could not be read')
        need(isinstance(n['reason'], str) and REASON.fullmatch(n['reason']), 'a removal reason could not be read')
        need(n['actor'] is None or (isinstance(exact(n['actor'], ['login'], 'a removal actor could not be read')
                                               ['login'], str)), 'a removal actor could not be read')
    commits = exact(p['commits'], ['nodes'], 'its head commit could not be read')['nodes']
    need(isinstance(commits, list) and len(commits) == 1, 'its head commit could not be read')
    commit = exact(commits[0], ['commit'], 'its head commit could not be read')['commit']
    commit = exact(commit, ['oid', 'statusCheckRollup'], 'its head commit could not be read')
    need(commit['oid'] == p['headRefOid'], 'its head commit could not be read')
    rollup = commit['statusCheckRollup']
    if rollup is None:
        contexts = {'pageInfo': {'hasNextPage': False, 'endCursor': None}, 'nodes': []}
    else:
        contexts = exact(exact(rollup, ['contexts'], 'its checks could not be read')['contexts'],
                         ['pageInfo', 'nodes'], 'its checks could not be read')
    for n in contexts['nodes'] if isinstance(contexts['nodes'], list) else [None]:
        run(n)
    for info, why in ((removed['pageInfo'], 'its removals could not be paged'),
                      (contexts['pageInfo'], 'its checks could not be paged')):
        exact(info, ['hasNextPage', 'endCursor'], why)
        need(type(info['hasNextPage']) is bool and (info['endCursor'] is None or isinstance(info['endCursor'], str))
             and (not info['hasNextPage'] or info['endCursor']), why)
    return p, removed, contexts


def run(n):
    why = 'a check on its head could not be read'
    need(isinstance(n, dict), why)
    if n.get('__typename') == 'CheckRun':
        exact(n, ['__typename', 'name', 'status', 'conclusion', 'startedAt'], why)
        need(isinstance(n['name'], str) and n['name'] and n['status'] in RUN_STATUS, why)
        done = n['status'] == 'COMPLETED'
        need((n['conclusion'] in CONCLUSIONS) if done else n['conclusion'] is None, why)
        need(n['startedAt'] is None and not done or isinstance(n['startedAt'], str) and TIME.fullmatch(n['startedAt']),
             why)
        return n['name'], ('done' if done else 'running'), n['conclusion'], n['startedAt']
    exact(n, ['__typename', 'context', 'state', 'createdAt'], why)
    need(n['__typename'] == 'StatusContext' and isinstance(n['context'], str) and n['context']
         and n['state'] in CONTEXT_STATES, why)
    time_of(n['createdAt'], why)
    busy = n['state'] in ('PENDING', 'EXPECTED')
    return n['context'], ('running' if busy else 'done'), (None if busy else n['state']), n['createdAt']


def facts(repo, number):
    owner, name = repo.split('/')
    removed_at = checks_at = None
    removals, runs, first = [], [], None
    removals_done = checks_done = False
    for _ in range(PAGES):
        p, removed, contexts = page(owner, name, number, removed_at, checks_at)
        fixed = {k: p[k] for k in ('state', 'headRefOid', 'isInMergeQueue', 'mergeCommit', 'mergeQueueEntry', 'added')}
        if first is None:
            first = fixed
        need(fixed == first, 'the pull request changed while its pages were read; read it again')
        if not removals_done:
            removals += removed['nodes']
            removals_done, removed_at = not removed['pageInfo']['hasNextPage'], removed['pageInfo']['endCursor']
        if not checks_done:
            runs += [run(n) for n in contexts['nodes']]
            checks_done, checks_at = not contexts['pageInfo']['hasNextPage'], contexts['pageInfo']['endCursor']
        if removals_done and checks_done:
            return first, removals, runs
    raise Unknown(f'its facts take more than {PAGES} pages')


def fleet_records(repo, number, head):
    try:
        auth = post.authors(repo)
    except post.Stop:
        raise Unknown('docs/agents/fleet.md names no record authors, so no record can be read')
    items = post.thread(repo, number)
    need(isinstance(items, list), f'the comments on #{number} could not be read')
    receipts, drops = [], set()
    for c in items:
        if not post.ours(c, auth):
            continue
        body = c.get('body')
        need(isinstance(body, str), f'a record on #{number} could not be read')
        line = body.replace('\r\n', '\n').split('\n', 1)[0]
        queued = QUEUED.match(line)
        if line.startswith('launch-fleet: merge dropped'):
            dropped = DROPPED.fullmatch(line)
            need(dropped, f'a merge dropped record on #{number} could not be read')
            if dropped.group(1) == head:
                drops.add((dropped.group(3), dropped.group(2)))
        elif queued and queued.group(1) == head:
            receipts.append(time_of(c.get('created_at'), f'a queue receipt record on #{number} could not be read'))
    return receipts, drops


def cause(head, removal, runs, checks):
    at, reason = removal['createdAt'], removal['reason']
    busy = sorted({name for name, state, _, _ in runs if state == 'running'})
    if busy:
        return f"wait {head}: still running: {', '.join(busy)}"
    latest, red = {}, []
    for check in checks:
        mine = sorted((r for r in runs if r[0] == check), key=lambda r: r[3])
        if not mine:
            red.append(f'{check} (no run)')
            continue
        last = [r for r in mine if r[3] == mine[-1][3]]
        need(len({r[2] for r in last}) == 1, f'{check} has two runs started at {mine[-1][3]} that disagree')
        latest[check] = mine[-1]
        if mine[-1][2] != 'SUCCESS':
            red.append(f'{check} ({mine[-1][2]})')
    if red:
        return f"wait {head}: not green on it: {', '.join(red)}"
    if all(latest[c][3] > at for c in checks):
        return f'requeue {head}: every required check ran again after the removal and is green'
    failed = [r for r in runs if r[2] not in NOT_FAILED]
    duplicates = failed and all(r[2] == 'CANCELLED' and any(o[0] == r[0] and o[3] > r[3] and o[2] == 'SUCCESS'
                                                            for o in runs) for r in failed)
    if duplicates:
        return f'requeue {head}: every required check is green on it, and its failed runs were cancelled duplicates'
    stale = [c for c in checks if latest[c][3] <= at]
    return f"wait {head}: {reason} at {at} may still stand: {', '.join(stale)} last ran before it"


def read(repo, number, head, checks):
    p, removals, runs = facts(repo, number)
    need(p['headRefOid'] == head, f"its head is {p['headRefOid']}, not {head}")
    if p['state'] == 'MERGED':
        need(p['mergeCommit'] is not None, 'it reads merged with no merge commit')
        return f"merged {p['mergeCommit']['oid']}", 0
    need(p['state'] == 'OPEN', f"it is {p['state']}")
    entry = (p['mergeQueueEntry'] or {}).get('headCommit', {}).get('oid')
    if p['isInMergeQueue']:
        need(entry == head, f'it is in the queue at {entry}, not {head}')
        return 'queued', 0
    need(entry is None, 'it reads out of the queue with a queue entry')
    receipts, drops = fleet_records(repo, number, head)
    if not receipts:
        return 'not queued', 0
    since = min(receipts)
    after = sorted((r for r in removals if r['createdAt'] >= since), key=lambda r: r['createdAt'])
    named = {(r['createdAt'], r['reason']) for r in after}
    for at, reason in sorted(drops):
        need((at, reason) in named, f'a merge dropped record at {head} names no removal after its receipt ({at})')
    fresh = [r for r in after if (r['createdAt'], r['reason']) not in drops]
    if fresh:
        return f"dropped {head}: {fresh[0]['reason']} at {fresh[0]['createdAt']}", 0
    need(after, f'it reads out of the queue at {head}, but no removal after its receipt reads yet')
    if len(after) >= 2:
        return f'blocked {head}: dropped twice at this head', 1
    removal = after[0]
    added = [n['createdAt'] for n in p['added']['nodes']]
    need(not added or added[0] <= removal['createdAt'],
         f"it was re-queued at {added[0] if added else ''} and reads out of the queue with no removal after")
    reason, actor = removal['reason'], (removal['actor'] or {}).get('login')
    if reason == 'dequeued' or actor != QUEUE_BOT:
        return f'blocked {head}: a person took it out of the queue ({reason})', 1
    if reason == 'merge_conflict':
        return f'blocked {head}: merge_conflict needs its builder to merge main in', 1
    if reason not in CHECK_CAUSES:
        return f'blocked {head}: {reason} is never re-queued automatically', 1
    return cause(head, removal, runs, checks), 0


def main(argv):
    checks = argv[4].split(',') if len(argv) == 5 else []
    if len(argv) != 5 or argv[0] != 'read' or not post.REPO.fullmatch(argv[1]) \
            or not re.fullmatch(r'[1-9][0-9]{0,11}', argv[2]) or not SHA.fullmatch(argv[3]) \
            or not all(checks) or len(set(checks)) != len(checks):
        print(USAGE, end='', file=sys.stderr)
        return 2
    try:
        line, code = read(argv[1], int(argv[2]), argv[3], checks)
    except Unknown as why:
        print(f'unknown: {why}')
        return 2
    print(line)
    return code


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
