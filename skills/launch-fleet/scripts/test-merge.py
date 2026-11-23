#!/usr/bin/env python3
"""merge.py on a synthetic GitHub (WS8, #1181; WS26, #1670): exact-head merges and FM4's cost line.

python3 -I skills/launch-fleet/scripts/test-merge.py
"""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('test_post', HERE / 'test-post.py')
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)
REPO, comment = T.REPO, T.comment
TICKETS = 'synthetic-owner/synthetic-tickets'

# The shared fake serves one repository. This router gives each repository its
# own world (FAKE_WORLDS) and answers the pull request's closing issues from
# its world's `closes`, so a write to the wrong repository lands where a test sees it.
# A world's `faults: {"read": "fail"}` fails its next comment-list read, `{"read_of": "N"}`
# its next read of issue N's comments; its `issues` answers one issue's read (the landed
# comment's brief and report), and a DELETE removes one comment. Calls take a lock on the
# world, so runs side by side never lose a write; FAKE_RACE=N holds each run's first read of
# issue N's comments until two runs have made it (#1848 R2). A ticket's spec query
# (RC3, #1831) is answered from the world's `tickets`, by number; a world without them has no spec.
ROUTER = r'''import fcntl, json, os, subprocess, sys, time
args = sys.argv[1:]
named = dict(a.split('=', 1) for a in args if a.split('=', 1)[0] in ('owner', 'name'))
repo = named['owner'] + '/' + named['name'] if len(named) == 2 else None
for i, a in enumerate(args):
    if a == '--repo':
        repo = args[i + 1]
    elif a.startswith('repos/'):
        repo = '/'.join(a.split('/')[1:3])
path = json.loads(os.environ.get('FAKE_WORLDS') or '{}').get(repo, os.environ['FAKE_WORLD'])
issue = [a.split('?')[0].split('/') for a in args if a.startswith('repos/')]
race = os.environ.get('FAKE_RACE')
if race and '--method' not in args and issue and issue[0][3:] == ['issues', race, 'comments']:
    mine = path + '.raced-' + str(os.getppid())
    if not os.path.exists(mine):
        open(mine, 'w').close()
        with open(path + '.arrived', 'a') as f:
            f.write('x')
        stop = time.time() + 20
        while open(path + '.arrived').read().count('x') < 2 and time.time() < stop:
            time.sleep(0.02)
lock = open(path + '.lock', 'a')
fcntl.flock(lock, fcntl.LOCK_EX)
if '--method' in args and args[args.index('--method') + 1] == 'DELETE':
    with open(path) as f:
        world = json.load(f)
    if world.get('faults', {}).pop('delete', None) == 'fail':
        with open(path, 'w') as f:
            json.dump(world, f)
        sys.exit('HTTP 502')
    gone = int(issue[0][-1])
    for items in world.get('comments', {}).values():
        if any(c['id'] == gone for c in items):
            items[:] = [c for c in items if c['id'] != gone]
            world['writes'].append({'delete': gone})
            with open(path, 'w') as f:
                json.dump(world, f)
            sys.exit(0)
    sys.exit('HTTP 404')
if '--method' not in args and issue and issue[0][3] == 'issues' and issue[0][5:] == ['comments']:
    with open(path) as f:
        world = json.load(f)
    if world.get('faults', {}).get('read_of') == issue[0][4]:
        del world['faults']['read_of']
        with open(path, 'w') as f:
            json.dump(world, f)
        sys.exit('HTTP 502')
if args[0] == 'api' and '--method' not in args and issue and len(issue[0]) == 5 and issue[0][3] == 'issues':
    with open(path) as f:
        found = json.load(f).get('issues', {}).get(issue[0][4])  # one issue, read whole (#1848)
    sys.stdout.write(json.dumps(found)) if found else sys.exit('HTTP 404')
    sys.exit(0)
if args[0] == 'api' and '--method' not in args and any(a.split('?')[0].endswith('/comments') for a in args):
    with open(path) as f:
        world = json.load(f)
    if world.get('faults', {}).pop('read', None) == 'fail':
        with open(path, 'w') as f:
            json.dump(world, f)
        sys.exit('HTTP 502')
if args[:2] == ['api', 'graphql'] and any(a.startswith('query=') and 'parent {' in a for a in args):
    with open(path) as f:
        world = json.load(f)
    number = next(a.split('=', 1)[1] for a in args if a.startswith('number='))
    tickets = world.get('tickets')
    issue = {'number': int(number), 'parent': None} if tickets is None else tickets.get(number)
    print(json.dumps({'data': {'repository': {'issue': issue}}}))
    sys.exit(0)
if args[:2] == ['api', 'graphql'] and any(a.startswith('query=') and 'enqueuePullRequest' in a for a in args):
    with open(path) as f:
        world = json.load(f)
    pr, got = world['pr'], dict(a.split('=', 1) for a in args if '=' in a and not a.startswith('query='))
    kind = world.get('faults', {}).pop('enqueue', None)
    if kind == 'moved':
        pr['headRefOid'] = 'b' * 40
    world['writes'].append({'enqueue': got.get('id'), 'head': got.get('head')})
    running = [c for c in pr['checks'] if (c.get('name') or c.get('context')) == 'check'
               and (c.get('status', 'COMPLETED') != 'COMPLETED' or c.get('state') in ('PENDING', 'EXPECTED'))]
    refused = (kind == 'fail' or got.get('id') != 'PR_synthetic' + str(pr['number'])
               or got.get('head') != pr['headRefOid'] or running or not pr['isMergeQueueEnabled'])
    if not refused and kind != 'pending':
        pr.update(isInMergeQueue=True, mergeQueueEntry={'headCommit': {'oid': pr['headRefOid']}},
                  enqueued={'enqueuer': {'login': world['me']}})
    with open(path, 'w') as f:
        json.dump(world, f)
    if refused:
        sys.exit('GraphQL: Pull request is not ready to be enqueued')
    if kind == 'lost':
        sys.exit('connection reset')
    print(json.dumps({'data': {'enqueuePullRequest': {'mergeQueueEntry': {'headCommit': {'oid': got['head']}}}}}))
    sys.exit(0)
r = subprocess.run([sys.executable, '-I', %r, *args], env=dict(os.environ, FAKE_WORLD=path),
                   capture_output=True, text=True)
out = r.stdout
if args[:2] == ['pr', 'merge'] and r.returncode == 0:
    with open(path) as f:
        world = json.load(f)
    if world['pr']['state'] == 'MERGED':
        world['pr']['mergedBy'] = {'login': world['me']}
        with open(path, 'w') as f:
            json.dump(world, f)
if args[:2] == ['api', 'graphql'] and r.returncode == 0:
    value = json.loads(out)
    node = value['data']['repository']['pullRequest']
    if node is not None:
        with open(path) as f:
            world = json.load(f)
        node['closingIssuesReferences'] = {'pageInfo': {'hasNextPage': False}, 'nodes': world['pr'].get('closes', [])}
        node['repository'] = {'nameWithOwner': world['repo']}
        node['id'] = 'PR_synthetic' + str(world['pr']['number'])
        node['enqueued'] = {'nodes': [world['pr']['enqueued']] if world['pr'].get('enqueued') else []}
        node['mergedBy'] = world['pr'].get('mergedBy')
    out = json.dumps(value)
sys.stdout.write(out)
sys.stderr.write(r.stderr)
sys.exit(r.returncode)
''' % str(HERE / 'fixtures/fake_github.py')


class World(T.World):
    """T.World with the router as `gh`; `others` maps another repository to its own world."""

    def __init__(self, test, others=None, **extra):
        super().__init__(test, **extra)
        (self.dir / 'router.py').write_text(ROUTER)
        gh = '#!/bin/sh\nexec "%s" -I "%s" "$@"\n' % (sys.executable, self.dir / 'router.py')
        (self.dir / 'bin/gh').write_text(gh)
        self.others = {repo: T.World(test, repo=repo, **value) for repo, value in (others or {}).items()}
        self.env['FAKE_WORLDS'] = json.dumps({r: str(o.path) for r, o in self.others.items()})


def closes(*refs):
    return [{'number': n, 'repository': {'nameWithOwner': r}} for r, n in refs]


HEAD = 'a' * 40
OTHER = 'b' * 40
LINE = ('Ticket #12 cost (PR #7): builder 3.5 credits, 120,000 tokens; reviewer unknown; '
        'CI 4.2 runner minutes; total 3.5 credits, 120,000 tokens, 4.2 runner minutes')


def pr(**changes):
    value = {'number': 7, 'state': 'OPEN', 'baseRefName': 'main', 'headRefOid': HEAD,
             'isMergeQueueEnabled': False, 'isInMergeQueue': False, 'mergeCommit': None,
             'mergeQueueEntry': None, 'mergeable': 'MERGEABLE', 'left': None, 'more_checks': False,
             'closes': closes((REPO, 12)),
             'checks': [{'__typename': 'CheckRun', 'name': 'check', 'status': 'COMPLETED', 'conclusion': 'SUCCESS'},
                        {'__typename': 'StatusContext', 'context': 'privacy', 'state': 'SUCCESS'}]}
    value.update(changes)
    return value


def project(world, script):
    """A consuming project whose FM4 command is `script` (Python source), or none."""
    root = world.dir / 'project'
    (root / 'tools/collector').mkdir(parents=True)
    if script is not None:
        (root / 'tools/collector/cost_line.py').write_text(script)
    return root


PRINTS = 'import sys\nassert sys.argv[1:5] == ["--repo", %r, "--pr", "7"], sys.argv\nprint(%r)\n' % (REPO, LINE)
REFUSES = ('import sys\nprint("cost: PR #7 closes more than one ticket; nothing printed", file=sys.stderr)\n'
           'sys.exit(1)\n')


class Read(unittest.TestCase):
    def test_where_it_stands(self):
        cases = [
            (pr(), 'open, the merge queue is off'),
            (pr(isMergeQueueEnabled=True), 'open, the merge queue is on'),
            (pr(isMergeQueueEnabled=True, left={'createdAt': '2026-01-01T00:00:00Z', 'reason': 'failed checks'}),
             'open, the merge queue is on; it left the queue at 2026-01-01T00:00:00Z: failed checks'),
            (pr(isMergeQueueEnabled=True, isInMergeQueue=True, mergeQueueEntry={'headCommit': {'oid': HEAD}}),
             'queued'),
            (pr(state='MERGED', mergeCommit={'oid': 'c' * 40}), 'merged ' + 'c' * 40),
            (pr(headRefOid=OTHER), 'stop: its head is %s, not %s' % (OTHER, HEAD)),
            (pr(state='MERGED', mergeCommit={'oid': 'c' * 40}, headRefOid=OTHER),
             'stop: its head is %s, not %s' % (OTHER, HEAD)),
            (pr(baseRefName='release'), 'stop: its base is release, not the default branch main'),
            (pr(state='CLOSED'), 'stop: CLOSED, in the merge queue: False'),
        ]
        for value, want in cases:
            with self.subTest(want=want):
                self.assertEqual(World(self, pr=value).run('merge.py', 'read', REPO, 7, HEAD), (0, want))
        self.assertEqual(World(self, pr=pr(number=8)).run('merge.py', 'read', REPO, 7, HEAD),
                         (0, 'stop: no such pull request'))

    def test_an_unreadable_state_is_a_stop(self):
        w = World(self, pr=pr(), faults={'graphql': 'fail'})
        code, out = w.run('merge.py', 'read', REPO, 7, HEAD)
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('stop: '), out)


class Admit(unittest.TestCase):
    def test_admission(self):
        failing = pr(checks=[{'__typename': 'CheckRun', 'name': 'check', 'conclusion': 'FAILURE'}])
        cases = [
            (pr(), 'check,privacy', 'base rule: no merge queue; mergeable: MERGEABLE'),
            (pr(mergeable='CONFLICTING'), 'check', 'base rule: no merge queue; mergeable: CONFLICTING'),
            (pr(isMergeQueueEnabled=True), 'check', 'admit: the merge queue re-tests it on the latest main'),
            (failing, 'check', 'wait: not every required check is green on it: check'),
            (pr(), 'check,privacy,nightly', 'wait: not every required check is green on it: nightly'),
            (pr(more_checks=True), 'check', 'wait: its head has more checks than one read shows'),
            (pr(headRefOid=OTHER), 'check', 'wait: its head is %s, not %s' % (OTHER, HEAD)),
            (pr(state='MERGED'), 'check', 'wait: it is MERGED, not open'),
            (pr(baseRefName='release'), 'check', 'wait: its base is release, not the default branch main'),
        ]
        for value, checks, want in cases:
            with self.subTest(want=want):
                self.assertEqual(World(self, pr=value).run('merge.py', 'admit', REPO, 7, HEAD, checks), (0, want))


class Merge(unittest.TestCase):
    def merge(self, w, *extra):
        return w.run('merge.py', 'merge', REPO, 7, HEAD, 'check', 'APPROVE 1 and plan approval 2', *extra,
                     cwd=w.dir / 'project')

    def test_a_merge_waits_for_its_admission_with_zero_writes(self):
        w = World(self, pr=pr(checks=[]))
        project(w, PRINTS)
        code, out = self.merge(w, '--ticket', 12)
        self.assertEqual(code, 1)
        self.assertEqual(out, 'blocked: not every required check is green on it: check; recorded 5001')
        self.assertEqual(w.bodies(7), ['launch-fleet: merge blocked %s: not every required check is green on it: '
                                       'check' % HEAD])
        self.assertFalse(any('merge' in x for x in w.writes()))

    def test_a_direct_merge_needs_the_base_rule_checked(self):
        w = World(self, pr=pr())
        project(w, PRINTS)
        code, out = self.merge(w, '--ticket', 12)
        self.assertEqual((code, out), (1, 'base rule: no merge queue; mergeable: MERGEABLE; '
                                          'check the base rule and fleet.sh every, then pass --base-rule-checked'))
        self.assertEqual(w.writes(), [])

    def test_a_verified_merge_posts_the_tickets_cost_line_once(self):
        w = World(self, pr=pr())
        project(w, PRINTS)
        code, out = self.merge(w, '--ticket', 12, '--base-rule-checked')
        self.assertEqual((code, out), (0, 'merged %s; cost posted 5001' % ('f' * 40)))
        self.assertEqual(w.bodies(12), ['launch-fleet: cost: ' + LINE])
        # A later wake that reads it merged posts nothing again.
        code, out = self.merge(w, '--ticket', 12, '--base-rule-checked')
        self.assertEqual((code, out), (0, 'merged %s; cost already posted 5001' % ('f' * 40)))
        self.assertEqual(w.bodies(12), ['launch-fleet: cost: ' + LINE])

    def test_the_head_moving_after_admission_never_merges_another_commit(self):
        w = World(self, pr=pr(isMergeQueueEnabled=True), faults={'enqueue': 'moved'})
        project(w, PRINTS)
        code, out = self.merge(w, '--ticket', 12)
        self.assertEqual((code, out), (1, 'not queued: GraphQL: Pull request is not ready to be enqueued; it reads '
                                          'back as: its head is %s, not %s; nothing was recorded, so run it again '
                                          'next wake' % (OTHER, HEAD)))
        self.assertEqual(w.load()['pr']['state'], 'OPEN')
        self.assertEqual((w.bodies(7), w.bodies(12)), ([], []))

    def test_the_queue_takes_it_and_its_record_says_what_allowed_it(self):
        w = World(self, pr=pr(isMergeQueueEnabled=True))
        project(w, PRINTS)
        code, out = self.merge(w, '--ticket', 12)
        self.assertEqual((code, out), (0, 'queued; recorded 5001'))
        self.assertEqual(w.bodies(7), ['launch-fleet: merge queued %s: APPROVE 1 and plan approval 2' % HEAD])
        self.assertEqual(w.bodies(12), [])

    def test_a_queue_that_let_it_go_blocks_it(self):
        left = {'createdAt': '2026-01-01T00:00:00Z', 'reason': 'failed checks', 'beforeCommit': {'oid': HEAD}}
        w = World(self, pr=pr(isMergeQueueEnabled=True, left=left),
                  comments={'7': [comment(4000, 'launch-fleet: merge queued %s: APPROVE 1' % HEAD)]})
        project(w, PRINTS)
        code, out = self.merge(w, '--ticket', 12)
        self.assertEqual((code, out), (1, 'blocked: left the merge queue: failed checks; recorded 5001'))
        self.assertFalse(any('merge' in x for x in w.writes()))

    def test_a_lost_merge_response_is_read_back(self):
        w = World(self, pr=pr(), faults={'merge': 'lost'})
        project(w, PRINTS)
        code, out = self.merge(w, '--ticket', 12, '--base-rule-checked')
        self.assertEqual((code, out), (0, 'merged %s; cost posted 5001' % ('f' * 40)))

    def test_a_refused_merge_is_blocked_and_recorded(self):
        w = World(self, pr=pr(), faults={'merge': 'fail'})
        project(w, PRINTS)
        code, out = self.merge(w, '--ticket', 12, '--base-rule-checked')
        self.assertEqual((code, out), (1, 'blocked: open, the merge queue is off; recorded 5001'))
        self.assertEqual(w.bodies(7), ['launch-fleet: merge blocked %s: open, the merge queue is off' % HEAD])
        self.assertEqual(w.bodies(12), [])

    def test_merged_but_not_yet_read_back_waits_for_the_next_wake(self):
        w = World(self, pr=pr(), faults={'merge': 'pending'})
        project(w, PRINTS)
        code, out = self.merge(w, '--ticket', 12, '--base-rule-checked')
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith('pending: '), out)
        self.assertEqual(w.bodies(7), [])


class Cost(unittest.TestCase):
    def cost(self, w):
        return w.run('merge.py', 'cost', REPO, 7, HEAD, 12, cwd=w.dir / 'project')

    def merged(self, **extra):
        return World(self, pr=pr(state='MERGED', mergeCommit={'oid': 'c' * 40}), **extra)

    def test_no_cost_line_before_a_verified_merge(self):
        for value in (pr(), pr(state='MERGED', mergeCommit={'oid': 'c' * 40}, headRefOid=OTHER), pr(state='CLOSED')):
            with self.subTest(state=value['state']):
                w = World(self, pr=value)
                project(w, PRINTS)
                code, out = self.cost(w)
                self.assertEqual(code, 1)
                self.assertTrue(out.startswith('refused: '), out)
                self.assertEqual(w.writes(), [])

    def test_an_unavailable_cost_is_posted_unknown_never_zero(self):
        for script, reason in ((REFUSES, 'PR #7 closes more than one ticket'),
                               ('print("Ticket #13 cost (PR #7): builder 0 credits")\n', 'unexpected cost output'),
                               ('import sys\nprint("oops thr' + '_synx", file=sys.stderr)\nsys.exit(1)\n',
                                'the cost command failed')):
            with self.subTest(reason=reason):
                w = self.merged()
                project(w, script)
                self.assertEqual(self.cost(w), (0, 'cost posted 5001'))
                self.assertEqual(w.bodies(12), ['launch-fleet: cost unknown (PR #7): ' + reason])

    def test_only_a_record_authors_cost_record_counts_as_posted(self):
        w = self.merged(comments={'12': [comment(4000, 'launch-fleet: cost: ' + LINE, login='someone-else'),
                                         comment(4001, 'launch-fleet: cost: Ticket #12 cost (PR #9): total unknown')]})
        project(w, PRINTS)
        self.assertEqual(self.cost(w), (0, 'cost posted 5001'))
        self.assertEqual(w.bodies(12)[-1], 'launch-fleet: cost: ' + LINE)



ROOM_CLI = r"""import datetime, json, os, sys
args = sys.argv[1:]
with open(os.environ['FAKE_USAGE_LOG'], 'a') as f:
    f.write(json.dumps(args) + '\n')
usage = json.loads(os.environ['FAKE_USAGE'])
if len(args) != 3 or args[0] != 'usage' or args[2] != '--json' or args[1] not in usage:
    sys.exit(2)
got = usage[args[1]]
if 'fail' in got:
    sys.exit(1)
if 'raw' in got:
    print(got['raw'])
    sys.exit(0)
if 'json' in got:
    print(json.dumps(got['json']))
    sys.exit(0)
now = datetime.datetime.now(datetime.timezone.utc).replace(minute=0, second=0, microsecond=0)
day = now.replace(hour=0) - datetime.timedelta(days=6)
first = got.get('first', 2)
stamp = lambda t: t.strftime('%Y-%m-%dT%H:00:00.000Z')
if first == 'none':
    hours = []
else:
    start = day if first == 'window' else now - datetime.timedelta(hours=first)
    hours = [{'credits': 0, 'hour': stamp(start), 'threads': 1}, {'credits': got['credits'], 'hour': stamp(now), 'threads': 1}]
print(json.dumps({'credits': 50000, 'history': {'credits': got['credits'], 'hours': hours, 'id': args[1],
                  'own': got['credits'], 'subagents': [], 'title': '#12: synthetic ' + args[1]}, 'plan': 'pro',
                  'text': 'synthetic ' + args[1]}))
"""
TH = 'thr' + '_'
BUILDER, REVIEWER, SECOND, ELSEWHERE = TH + 'synbuild', TH + 'synreview1', TH + 'synreview2', TH + 'synother'
THREADS = {'builder:12': BUILDER, 'review:7:' + HEAD: REVIEWER, 'review:7:claim:9001': REVIEWER,
           'review:7:' + OTHER: SECOND, 'review:7:claim:9002': SECOND, 'builder:13': ELSEWHERE, 'review:8:' + HEAD: ELSEWHERE,
           'comment:9001': TH + 'synsender', 'fleet:3': TH + 'synfleet'}
THIRD = 'd' * 40
RECORDS = [comment(9001, 'launch-fleet: review started ' + HEAD), comment(9002, 'launch-fleet: review started ' + OTHER)]


def on(repo, number, c):
    return dict(c, issue_url='https://api.github.com/repos/%s/issues/%s' % (repo, number))
USAGE = {BUILDER: {'credits': 3.5}, REVIEWER: {'credits': 2}, SECOND: {'credits': 1.25}, ELSEWHERE: {'credits': 99}}
KNOWN = 'Ticket #12 cost (PR %s): builder %s; reviewer %s; CI unknown; total %s'


def known(builder, reviewer, total, ref='#7'):
    return 'launch-fleet: cost: ' + KNOWN % (ref,
        builder if builder == 'unknown' else builder + ' credits, unknown tokens',
        reviewer if reviewer == 'unknown' else reviewer + ' credits, unknown tokens',
        total if total == 'unknown' else total + ' credits, unknown tokens, unknown runner minutes')


class CostFromAgents(unittest.TestCase):
    def world(self, threads=THREADS, usage=USAGE, runs=None, state='file', home=REPO, owner=None, records=RECORDS,
              home_7=()):
        merged = dict(state='MERGED', mergeCommit={'oid': 'c' * 40})
        on_pr = {'7': records} if records is not None else {}
        if home == REPO:
            w = World(self, pr=pr(**merged), comments=on_pr)
        else:
            w = World(self, pr=pr(closes=closes((home, 12)), **merged), comments={'12': [], **on_pr},
                      others={home: {'comments': {'12': [], '7': list(home_7)}}})
        project(w, None)
        (w.dir / 'room-cli.py').write_text(ROOM_CLI)
        cli = w.dir / 'bin/room-cli'
        cli.write_text('#!/bin/sh\nexec "%s" -I "%s" "$@"\n' % (sys.executable, w.dir / 'room-cli.py'))
        cli.chmod(0o755)
        w.env.pop('LAUNCH_FLEET_STATE', None)
        w.env.pop('LAUNCH_FLEET_RUNS', None)
        w.env.update(FAKE_USAGE=json.dumps(usage), FAKE_USAGE_LOG=str(w.dir / 'usage.log'))
        if state == 'file':
            (w.dir / 'state.json').write_text(json.dumps({'repo': owner or home, 'threads': threads}))
            w.env['LAUNCH_FLEET_STATE'] = str(w.dir / 'state.json')
        elif state is not None:
            w.env['LAUNCH_FLEET_STATE'] = state
        if runs is not None:
            (w.dir / 'runs.json').write_text(json.dumps(runs) if isinstance(runs, dict) else runs)
            w.env['LAUNCH_FLEET_RUNS'] = str(w.dir / 'runs.json')
        return w

    def cost(self, w):
        return w.run('merge.py', 'cost', REPO, 7, HEAD, 12, cwd=w.dir / 'project')

    def reads(self, w):
        log = w.dir / 'usage.log'
        return sorted(json.loads(x)[1] for x in log.read_text().splitlines()) if log.exists() else []

    def no_id(self, w, out):
        self.assertNotIn(TH, out)
        for body in w.bodies(12) + [json.dumps(x) for x in w.writes()]:
            self.assertNotIn(TH, body)

    def test_the_line_carries_the_builders_credits_and_the_reviewers_summed(self):
        w = self.world()
        self.assertEqual(self.cost(w), (0, 'cost posted 5001'))
        self.assertEqual(w.bodies(12), [known('3.5', '3.25', '6.75')])
        self.assertEqual(self.reads(w), sorted([BUILDER, REVIEWER, SECOND]))
        self.no_id(w, '')
        self.assertEqual(self.cost(w), (0, 'cost already posted 5001'))
        self.assertEqual(len(w.bodies(12)), 1)

    def test_no_command_and_no_state_posts_the_all_unknown_line(self):
        w = self.world(state=None)
        self.assertEqual(self.cost(w), (0, 'cost posted 5001'))
        self.assertEqual(w.bodies(12), [known('unknown', 'unknown', 'unknown')])
        self.assertEqual(self.reads(w), [])

    def test_each_unknown_role_makes_the_total_unknown_never_zero(self):
        no_builder = {k: v for k, v in THREADS.items() if k != 'builder:12'}
        no_reviewer = {k: v for k, v in THREADS.items() if not k.startswith('review:7:')}
        bad = lambda answer: dict(USAGE, **{BUILDER: answer})
        bad_reviewer = lambda answer: dict(USAGE, **{SECOND: answer})
        driver = {'repo': REPO, 'runs': {'12': {'host': 'synthetic', 'run': 'run-1'}}}
        driver_review = {'repo': REPO, 'runs': {'7': {'host': 'synthetic', 'run': 'run-2'}}}
        cases = {
            'state file missing': (dict(state=str(Path('/nonexistent-synthetic/state.json'))), 'unknown', 'unknown'),
            'state path relative': (dict(state='state.json'), 'unknown', 'unknown'),
            'missing builder': (dict(threads=no_builder), 'unknown', '3.25'),
            'no reviewer': (dict(threads=no_reviewer), '3.5', 'unknown'),
            'driver run in state': (dict(threads=dict(THREADS, **{'run:12': TH + 'synrun'})), 'unknown', '3.25'),
            'driver run in the run map': (dict(runs=driver), 'unknown', '3.25'),
            'driver reviewer in the run map': (dict(runs=driver_review), '3.5', 'unknown'),
            'driver reviewer in state': (dict(threads=dict(THREADS, **{'run:7': TH + 'synrun'})), '3.5', 'unknown'),
            'driver reviewer and no CloudRoom reviewer': (dict(threads=no_reviewer, runs=driver_review),
                                                          '3.5', 'unknown'),
            'run map unreadable': (dict(runs='{"repo": "x"'), 'unknown', 'unknown'),
            'failed read': (dict(usage=bad({'fail': 1})), 'unknown', '3.25'),
            'not JSON': (dict(usage=bad({'raw': 'credits: 4'})), 'unknown', '3.25'),
            'credits missing': (dict(usage=bad({'json': {'history': {'hours': []}}})), 'unknown', '3.25'),
            'credits not a number': (dict(usage=bad({'credits': '4'})), 'unknown', '3.25'),
            'credits negative': (dict(usage=bad({'credits': -1})), 'unknown', '3.25'),
            'credits a boolean': (dict(usage=bad({'credits': True})), 'unknown', '3.25'),
            'another thread answered': (dict(usage=bad({'json': {'history': {
                'credits': 4, 'id': TH + 'synelse', 'hours': [{'credits': 4, 'hour': '2099-01-01T00:00:00.000Z'}]}}})),
                'unknown', '3.25'),
            'an hour without a zone': (dict(usage=bad({'json': {'history': {
                'credits': 4, 'id': BUILDER, 'hours': [{'credits': 4, 'hour': '2099-01-01T00:00:00'}]}}})),
                'unknown', '3.25'),
            'no hours in the window': (dict(usage=bad({'credits': 0, 'first': 'none'})), 'unknown', '3.25'),
            'short window': (dict(usage=bad({'credits': 3.5, 'first': 'window'})), 'unknown', '3.25'),
            'one reviewer unread': (dict(usage=bad_reviewer({'fail': 1})), '3.5', 'unknown'),
            'one reviewer in a short window': (dict(usage=bad_reviewer({'credits': 1, 'first': 'window'})),
                                               '3.5', 'unknown'),
        }
        for name, (setup, builder, reviewer) in cases.items():
            with self.subTest(case=name):
                w = self.world(**setup)
                self.assertEqual(self.cost(w), (0, 'cost posted 5001'))
                self.assertEqual(w.bodies(12), [known(builder, reviewer, 'unknown')])
                self.no_id(w, '')

    def test_a_cross_repository_ticket_gets_its_agents_line_once(self):
        w = self.world(home=TICKETS)
        self.assertEqual(self.cost(w), (0, 'cost posted 5001'))
        line = known('3.5', '3.25', '6.75', ref='%s#7' % REPO)
        self.assertEqual(w.others[TICKETS].bodies(12), [line])
        self.assertEqual(w.bodies(12), [])
        self.assertEqual(self.reads(w), sorted([BUILDER, REVIEWER, SECOND]))
        self.no_id(w, '')
        self.assertEqual(self.cost(w), (0, 'cost already posted 5001'))
        self.assertEqual(w.others[TICKETS].bodies(12), [line])
        self.assertEqual(len(self.reads(w)), 3)

    def test_a_same_numbered_pull_request_elsewhere_adds_no_reviewer(self):
        theirs = [on(TICKETS, 7, comment(8001, 'launch-fleet: review started ' + THIRD))]
        mine = {'builder:12': BUILDER, 'review:7:' + HEAD: REVIEWER, 'review:7:claim:9001': REVIEWER}
        for name, commit in (('another head', THIRD), ('the same head', HEAD)):
            with self.subTest(case=name):
                same = dict(mine, **{'review:7:claim:8001': ELSEWHERE, 'review:7:' + commit: ELSEWHERE})
                w = self.world(home=TICKETS, threads=same, records=RECORDS[:1], home_7=theirs)
                self.assertEqual(self.cost(w), (0, 'cost posted 5001'))
                self.assertEqual(w.others[TICKETS].bodies(12), [known('3.5', '2', '5.5', ref='%s#7' % REPO)])
                self.assertEqual(self.reads(w), sorted([BUILDER, REVIEWER]))

    def test_a_reviewer_bound_to_no_claim_on_either_pull_request_is_unknown(self):
        mine = {'builder:12': BUILDER, 'review:7:claim:9001': REVIEWER}
        cases = {
            'a shared head with no claim': (TICKETS, dict(mine, **{'review:7:' + HEAD: ELSEWHERE}), RECORDS[:1]),
            'a claim whose record is gone': (REPO, THREADS, RECORDS[:1]),
            'a claim whose record is gone, elsewhere': (TICKETS, THREADS, RECORDS[:1]),
        }
        for name, (home, threads, records) in cases.items():
            with self.subTest(case=name):
                w = self.world(home=home, threads=threads, records=records)
                self.assertEqual(self.cost(w), (0, 'cost posted 5001'))
                ref = '#7' if home == REPO else '%s#7' % REPO
                target = w if home == REPO else w.others[TICKETS]
                self.assertEqual(target.bodies(12), [known('3.5', 'unknown', 'unknown', ref=ref)])

    def test_a_reviewer_the_pull_requests_records_cannot_vouch_for_is_unknown(self):
        driver = comment(9001, 'launch-fleet: review started %s\nDriver review: other-family' % HEAD)
        recheck = comment(9002, 'launch-fleet: re-check sent %s\nDriver re-check: other-family' % OTHER)
        cases = {
            'a short legacy commit key': dict(threads=dict(THREADS, **{'review:7:aaaaaaa': REVIEWER})),
            'a key of no known form': dict(threads=dict(THREADS, **{'review:7:synthetic': REVIEWER})),
            'no records on the pull request': dict(records=[]),
            "the pull request's records unreadable": dict(faults={'read_of': '7'}),
            "only another author's records": dict(records=[dict(c, user={'login': 'someone-else'}) for c in RECORDS]),
            'a driver review on the pull request': dict(records=[driver, RECORDS[1]]),
            'a driver re-check on the pull request': dict(records=[RECORDS[0], recheck]),
            'a pending driver start after a given-up reviewer': dict(records=[
                comment(9001, 'launch-fleet: review given up %s: synthetic quiet reviewer' % HEAD),
                RECORDS[1], comment(9003, 'launch-fleet: review starting %s\nDriver review: other-family' % HEAD),
                comment(9004, 'VERDICT: APPROVE at ' + HEAD)]),
        }
        for name, setup in cases.items():
            for home in (REPO, TICKETS):
                with self.subTest(case=name, home=home):
                    w = self.world(home=home, **{k: v for k, v in setup.items() if k != 'faults'})
                    if 'faults' in setup:
                        w.update(faults=setup['faults'])
                    self.assertEqual(self.cost(w), (0, 'cost posted 5001'))
                    ref = '#7' if home == REPO else '%s#7' % REPO
                    target = w if home == REPO else w.others[TICKETS]
                    self.assertEqual(target.bodies(12), [known('3.5', 'unknown', 'unknown', ref=ref)])
                    self.no_id(w, '')

    def test_the_tickets_run_map_names_no_driver_for_a_pull_request_elsewhere(self):
        runs = {'repo': TICKETS, 'runs': {'7': {'host': 'synthetic', 'run': 'run-2'}}}
        w = self.world(home=TICKETS, runs=runs)
        self.assertEqual(self.cost(w), (0, 'cost posted 5001'))
        self.assertEqual(w.others[TICKETS].bodies(12), [known('3.5', '3.25', '6.75', ref='%s#7' % REPO)])

    def test_a_cross_repository_state_must_be_the_tickets_fleet(self):
        w = self.world(home=TICKETS, owner=REPO)
        self.assertEqual(self.cost(w), (0, 'cost posted 5001'))
        self.assertEqual(w.others[TICKETS].bodies(12), [known('unknown', 'unknown', 'unknown', ref='%s#7' % REPO)])
        self.assertEqual(self.reads(w), [])

    def test_a_cross_repository_project_command_is_still_refused(self):
        w = self.world(home=TICKETS)
        (w.dir / 'project/tools/collector/cost_line.py').write_text(PRINTS)
        self.assertEqual(self.cost(w), (0, 'cost posted 5001'))
        self.assertEqual(w.others[TICKETS].bodies(12), [
            'launch-fleet: cost unknown (PR %s#7): the cost command costs only tickets in the pull '
            "request's repository" % REPO])
        self.assertEqual(self.reads(w), [])

    def test_the_projects_own_command_still_wins(self):
        w = self.world()
        (w.dir / 'project/tools/collector/cost_line.py').write_text(PRINTS)
        self.assertEqual(self.cost(w), (0, 'cost posted 5001'))
        self.assertEqual(w.bodies(12), ['launch-fleet: cost: ' + LINE])
        self.assertEqual(self.reads(w), [])

class Documented(unittest.TestCase):
    """#1622: SKILL.md's two merge commands, run as written from a consuming project's checkout
    (the installed skill lives outside it), so the project's FM4 command resolves there."""

    def commands(self):
        text = (HERE.parent / 'SKILL.md').read_text()
        found = re.findall(r'`(python3 -I [^`]*merge\.py"? (?:admit|merge) [^`]*)`', text)
        self.assertEqual(len(found), 2, found)
        values = {"<this skill's folder>": str(HERE.parent), '<owner>/<repo>': REPO, '<P>': '7',
                  '<commit>': HEAD, '<checks>': 'check',
                  '<the APPROVE and the plan approval it relies on>': 'APPROVE 1 and plan approval 2', '<N>': '12'}
        argvs = []
        for command in found:
            for name, value in values.items():
                command = command.replace(name, value)
            argv = shlex.split(command)
            self.assertNotRegex(' '.join(argv), r'<[^>]+>', 'a placeholder left unfilled')
            argvs.append([sys.executable] + argv[1:])
        return argvs

    def test_the_documented_commands_run_from_the_project_checkout(self):
        # catches: the merge commands naming scripts/merge.py relative to the consuming project,
        # which has no such file, so an approved green PR is never admitted or merged (#1622).
        w = World(self, pr=pr())
        root = project(w, PRINTS)
        admit, merge = self.commands()
        for argv, want in [(admit, 'base rule: no merge queue; mergeable: MERGEABLE'),
                           (merge + ['--base-rule-checked'], 'merged %s; cost posted 5001' % ('f' * 40))]:
            r = subprocess.run(argv, capture_output=True, text=True, env=w.env, cwd=root, timeout=60)
            self.assertEqual((r.returncode, r.stdout.strip()), (0, want), r.stderr)
        self.assertEqual(w.bodies(12), ['launch-fleet: cost: ' + LINE])


    def archive_rule(self):
        """The archive row's settle command, filled, and the results it may archive after."""
        row = next(x for x in (HERE.parent / 'SKILL.md').read_text().splitlines() if x.startswith('| `archive #N` |'))
        found = re.findall(r'`(python3 -I [^`]*merge\.py"? settle [^`]*)`', row)
        self.assertEqual(len(found), 1, row)
        command = found[0]
        for name, value in {"<this skill's folder>": str(HERE.parent), '<owner>/<repo>': REPO, '<P>': '7', '<N>': '12'}.items():
            command = command.replace(name, value)
        argv = shlex.split(command)
        self.assertNotRegex(' '.join(argv), r'<[^>]+>', 'a placeholder left unfilled')
        after = re.search(r'archives? only after ([^;.]*)', row)
        self.assertIsNotNone(after, 'the archive row names no settled results that let it archive')
        settled = [x.split(' <')[0] for x in re.findall(r'`([^`]+)`', after.group(1))]
        return [sys.executable] + argv[1:], settled

    def test_the_archive_row_archives_only_after_a_settled_cost(self):
        # catches: the archive row archiving on a settle result that confirms no cost record (an
        # `unknown:` read or write, a `refused:`), after which fleet.sh prints no archive line and
        # the queued merge's cost is never posted (#115 R2).
        argv, settled = self.archive_rule()
        receipt = comment(4000, 'launch-fleet: merge queued %s: APPROVE 1 and plan approval 2' % HEAD)
        merged = dict(state='MERGED', mergeCommit={'oid': 'c' * 40})
        # name: (pull request, its comments, the fault, archives now, archives on the next wake)
        cases = {
            'settled': (pr(**merged), [receipt], {}, True, True),
            'never queued': (pr(**merged), [], {}, True, True),
            'receipt read fails': (pr(**merged), [receipt], {'read': 'fail'}, False, True),
            'cost write fails': (pr(**merged), [receipt], {'post': 'fail'}, False, True),
            'cost write lost': (pr(**merged), [receipt], {'post': 'lost'}, False, True),
            'still queued': (pr(isMergeQueueEnabled=True, isInMergeQueue=True,
                                mergeQueueEntry={'headCommit': {'oid': HEAD}}), [receipt], {}, False, False),
        }
        for name, (value, comments, faults, now, later) in cases.items():
            with self.subTest(name):
                w = World(self, pr=value, comments={'7': comments}, faults=faults)
                root = project(w, PRINTS)
                for want in (now, later):  # this wake, then the next one, the fault gone
                    r = subprocess.run(argv, capture_output=True, text=True, env=w.env, cwd=root, timeout=60)
                    out = r.stdout.strip()
                    archives = any(out.startswith(x) for x in settled)
                    self.assertEqual(archives, want, (out, r.stderr))
                    # Never archived while a queued merge's cost is missing from the ticket.
                    costs = [b for b in w.bodies(12) if b.startswith('launch-fleet: cost')]
                    self.assertTrue(not archives or costs or not comments, (out, costs))


class CrossRepository(unittest.TestCase):
    """#1502: the pull request lives in one repository and closes a ticket in another."""

    def world(self, refs, **pr_changes):
        # The pull request's repository has its own issue #12 too.
        return World(self, pr=pr(closes=closes(*refs), **pr_changes), comments={'12': []},
                     others={TICKETS: {'comments': {'12': []}}})

    def test_the_cost_is_posted_on_the_tickets_own_repository_once(self):
        # catches: the cost looked up and posted on the PR repository's same-number issue (#1502).
        w = self.world([(TICKETS, 12)])
        project(w, PRINTS)
        merged = 'merged %s; ' % ('f' * 40)
        want = ('launch-fleet: cost unknown (PR %s#7): the cost command costs only tickets in the pull '
                "request's repository" % REPO)
        code, out = Merge.merge(self, w, '--ticket', 12, '--base-rule-checked')
        self.assertEqual((code, out), (0, merged + 'cost posted 5001'))
        self.assertEqual(w.others[TICKETS].bodies(12), [want])
        self.assertEqual(w.bodies(12), [])
        # The next wake finds that record on the ticket's repository and posts nothing again.
        code, out = Merge.merge(self, w, '--ticket', '%s#12' % TICKETS, '--base-rule-checked')
        self.assertEqual((code, out), (0, merged + 'cost already posted 5001'))
        self.assertEqual(w.others[TICKETS].bodies(12), [want])
        self.assertEqual(w.bodies(12), [])

    def test_a_ticket_the_pull_request_does_not_close_is_refused_before_any_write(self):
        # catches: a merge whose cost would land on an issue the PR doesn't close, or on the wrong
        # one of two same-number closing issues.
        for refs, ticket in (([(TICKETS, 13)], '12'), ([(TICKETS, 12)], '%s#12' % REPO),
                             ([(TICKETS, 12), (REPO, 12)], '12')):
            with self.subTest(refs=refs, ticket=ticket):
                w = self.world(refs)
                project(w, PRINTS)
                code, out = Merge.merge(self, w, '--ticket', ticket, '--base-rule-checked')
                self.assertEqual(code, 1)
                self.assertTrue(out.startswith('refused: '), out)
                self.assertEqual((w.writes(), w.others[TICKETS].writes()), ([], []))

    def test_a_wrong_ticket_on_a_queued_or_stopped_pull_request_writes_nothing(self):
        queued = dict(isMergeQueueEnabled=True, isInMergeQueue=True, mergeQueueEntry={'headCommit': {'oid': HEAD}})
        for name, changes in {'queued without its receipt': queued, 'stopped': dict(headRefOid=OTHER),
                              'closed': dict(state='CLOSED')}.items():
            with self.subTest(name):
                w = self.world([(TICKETS, 12)], **changes)
                project(w, PRINTS)
                code, out = Merge.merge(self, w, '--ticket', 13)
                self.assertEqual((code, out), (1, 'refused: PR #7 does not close 13'))
                self.assertEqual((w.writes(), w.others[TICKETS].writes()), ([], []))

    def test_the_named_one_of_two_same_number_tickets_gets_it(self):
        # catches: a qualified ticket ignored in favour of the PR repository's same number.
        w = self.world([(TICKETS, 12), (REPO, 12)], state='MERGED', mergeCommit={'oid': 'c' * 40})
        project(w, PRINTS)
        self.assertEqual(w.run('merge.py', 'cost', REPO, 7, HEAD, '%s#12' % TICKETS, cwd=w.dir / 'project'),
                         (0, 'cost posted 5001'))
        self.assertEqual(len(w.others[TICKETS].bodies(12)), 1)
        self.assertEqual(w.bodies(12), [])


    def merged_once(self):
        w = self.world([(TICKETS, 12)], state='MERGED', mergeCommit={'oid': 'c' * 40})
        project(w, PRINTS)
        self.assertEqual(w.run('merge.py', 'cost', REPO, 7, HEAD, 12, cwd=w.dir / 'project'), (0, 'cost posted 5001'))
        return w

    def test_a_case_variant_of_the_pull_requests_repository_finds_the_same_record(self):
        # catches: a retry with another letter case of the same PR repository posting a second
        # cost record on the ticket (R2).
        w = self.merged_once()
        self.assertEqual(w.run('merge.py', 'cost', REPO.upper(), 7, HEAD, 12, cwd=w.dir / 'project'),
                         (0, 'cost already posted 5001'))
        self.assertEqual(len(w.others[TICKETS].bodies(12)), 1)

    def test_an_unreadable_duplicate_lookup_posts_nothing(self):
        # catches: a failed read of the ticket's records taken as "none yet", so a retry posts a
        # second cost record (R2).
        w = self.merged_once()
        w.others[TICKETS].update(faults={'read': 'fail'})
        code, out = w.run('merge.py', 'cost', REPO, 7, HEAD, 12, cwd=w.dir / 'project')
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('unknown: '), out)
        self.assertEqual(len(w.others[TICKETS].bodies(12)), 1)


class Enqueue(unittest.TestCase):
    def merge(self, w):
        return Merge.merge(self, w, '--ticket', 12)

    def running(self):
        return [{'__typename': 'CheckRun', 'name': 'check', 'status': 'COMPLETED', 'conclusion': 'SUCCESS'},
                {'__typename': 'CheckRun', 'name': 'check', 'status': 'IN_PROGRESS', 'conclusion': None}]

    def test_running_required_checks_are_refused_with_no_record(self):
        w = World(self, pr=pr(isMergeQueueEnabled=True, checks=self.running()))
        project(w, PRINTS)
        self.assertEqual(self.merge(w), (1, 'refused: its required checks are running: check; nothing was enqueued '
                                            'or recorded, so run it again once they finish'))
        self.assertEqual((w.bodies(7), w.writes()), ([], []))

    def test_a_pending_status_context_is_running_too(self):
        checks = pr()['checks'] + [{'__typename': 'StatusContext', 'context': 'check', 'state': 'PENDING'}]
        w = World(self, pr=pr(isMergeQueueEnabled=True, checks=checks))
        project(w, PRINTS)
        code, out = self.merge(w)
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('refused: its required checks are running: check;'), out)
        self.assertEqual((w.bodies(7), w.writes()), ([], []))

    def test_a_check_run_with_no_status_reads_as_running(self):
        checks = [{'__typename': 'CheckRun', 'name': 'check', 'conclusion': 'SUCCESS'}]
        w = World(self, pr=pr(isMergeQueueEnabled=True, checks=checks))
        project(w, PRINTS)
        code, out = self.merge(w)
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('refused: its required checks are running: check;'), out)
        self.assertEqual((w.bodies(7), w.writes()), ([], []))

    def test_an_optional_running_check_does_not_hold_it(self):
        checks = pr()['checks'] + [{'__typename': 'CheckRun', 'name': 'extra', 'status': 'QUEUED', 'conclusion': None}]
        w = World(self, pr=pr(isMergeQueueEnabled=True, checks=checks))
        project(w, PRINTS)
        self.assertEqual(self.merge(w), (0, 'queued; recorded 5001'))
        self.assertEqual(w.writes()[0], {'enqueue': 'PR_synthetic7', 'head': HEAD})

    def test_green_checks_enqueue_pinned_and_the_receipt_follows_the_read_back(self):
        w = World(self, pr=pr(isMergeQueueEnabled=True))
        project(w, PRINTS)
        self.assertEqual(self.merge(w), (0, 'queued; recorded 5001'))
        receipt = 'launch-fleet: merge queued %s: APPROVE 1 and plan approval 2' % HEAD
        self.assertEqual(w.writes(), [{'enqueue': 'PR_synthetic7', 'head': HEAD}, {'post': 7, 'body': receipt}])
        self.assertEqual(w.bodies(7), [receipt])

    def test_a_refused_enqueue_writes_no_receipt(self):
        w = World(self, pr=pr(isMergeQueueEnabled=True), faults={'enqueue': 'fail'})
        project(w, PRINTS)
        self.assertEqual(self.merge(w), (1, 'not queued: GraphQL: Pull request is not ready to be enqueued; '
                                            'nothing was recorded, so run it again next wake'))
        self.assertEqual(w.bodies(7), [])
        self.assertEqual(self.merge(w), (0, 'queued; recorded 5001'))

    def test_an_enqueue_that_reads_back_unqueued_writes_no_receipt(self):
        w = World(self, pr=pr(isMergeQueueEnabled=True), faults={'enqueue': 'pending'})
        project(w, PRINTS)
        code, out = self.merge(w)
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith('pending: '), out)
        self.assertEqual(w.bodies(7), [])

    def test_a_lost_enqueue_response_is_read_back_before_the_receipt(self):
        w = World(self, pr=pr(isMergeQueueEnabled=True), faults={'enqueue': 'lost'})
        project(w, PRINTS)
        self.assertEqual(self.merge(w), (0, 'queued; recorded 5001'))
        self.assertEqual(w.bodies(7), ['launch-fleet: merge queued %s: APPROVE 1 and plan approval 2' % HEAD])


class Queue(unittest.TestCase):
    """#1616 and #1631: what the merge queue owes across wakes."""

    def merge(self, w):
        return Merge.merge(self, w, '--ticket', 12)

    def receipt(self):
        return 'launch-fleet: merge queued %s: APPROVE 1 and plan approval 2' % HEAD

    def test_a_queued_merge_gets_its_cost_before_the_archive(self):
        # catches: the queue merging between wakes, and the closed-ticket wake archiving with no
        # cost record (#1616).
        w = World(self, pr=pr(isMergeQueueEnabled=True))
        project(w, PRINTS)
        settle = lambda: w.run('merge.py', 'settle', REPO, 7, 12, cwd=w.dir / 'project')
        self.assertEqual(self.merge(w), (0, 'queued; recorded 5001'))
        # Still queued: nothing to cost yet, and nothing written.
        code, out = settle()
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('refused: '), out)
        self.assertEqual(len(w.writes()), 2)
        value = w.load()
        value['pr'].update(state='MERGED', mergeCommit={'oid': 'c' * 40}, isInMergeQueue=False, mergeQueueEntry=None)
        w.save(value)
        self.assertEqual(settle(), (0, 'cost posted 5002'))
        self.assertEqual(w.bodies(12), ['launch-fleet: cost: ' + LINE])
        self.assertEqual(settle(), (0, 'cost already posted 5002'))
        self.assertEqual(w.bodies(12), ['launch-fleet: cost: ' + LINE])

    def test_without_a_queue_receipt_there_is_nothing_to_settle(self):
        # catches: a settle that costs a pull request the fleet never queued, or one another
        # author claims to have queued.
        w = World(self, pr=pr(state='MERGED', mergeCommit={'oid': 'c' * 40}),
                  comments={'7': [comment(4000, self.receipt(), login='someone-else')]})
        project(w, PRINTS)
        self.assertEqual(w.run('merge.py', 'settle', REPO, 7, 12, cwd=w.dir / 'project'), (0, 'no queued merge'))
        self.assertEqual(w.writes(), [])

    def test_an_unconfirmed_queue_receipt_is_repaired_on_the_next_wake(self):
        w = World(self, pr=pr(isMergeQueueEnabled=True), faults={'post': 'fail'})
        project(w, PRINTS)
        code, out = self.merge(w)
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('queued; receipt unconfirmed '), out)
        self.assertEqual((w.bodies(7), w.load()['pr']['isInMergeQueue']), ([], True))
        self.assertEqual(self.merge(w), (0, 'queued; recorded 5001'))
        self.assertEqual(w.bodies(7), [self.receipt()])
        self.assertEqual(self.merge(w), (0, 'queued; the queue merges it or lets it go'))
        self.assertEqual(w.bodies(7), [self.receipt()])
        # The queue lets it go: the receipt blocks a second enqueue at that head.
        value = w.load()
        value['pr'].update(isInMergeQueue=False, mergeQueueEntry=None,
                           left={'createdAt': '2026-01-01T00:00:00Z', 'reason': 'failed checks',
                                 'beforeCommit': {'oid': HEAD}})
        w.save(value)
        self.assertEqual(self.merge(w), (1, 'blocked: left the merge queue: failed checks; recorded 5002'))
        self.assertEqual(sum('enqueue' in x for x in w.writes()), 1)

    def test_a_queue_merge_whose_receipt_failed_still_settles_its_cost(self):
        w = World(self, pr=pr(isMergeQueueEnabled=True), faults={'post': 'fail'})
        project(w, PRINTS)
        code, out = self.merge(w)
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('queued; receipt unconfirmed '), out)
        value = w.load()
        value['pr'].update(state='MERGED', mergeCommit={'oid': 'c' * 40}, isInMergeQueue=False, mergeQueueEntry=None)
        w.save(value)
        settle = lambda: w.run('merge.py', 'settle', REPO, 7, 12, cwd=w.dir / 'project')
        self.assertEqual(settle(), (0, 'cost posted 5001'))
        self.assertEqual(w.bodies(12), ['launch-fleet: cost: ' + LINE])
        self.assertEqual(settle(), (0, 'cost already posted 5001'))
        self.assertEqual(w.bodies(7), [])

    def test_a_merge_someone_else_enqueued_without_a_receipt_has_nothing_to_settle(self):
        w = World(self, pr=pr(state='MERGED', mergeCommit={'oid': 'c' * 40},
                              enqueued={'enqueuer': {'login': 'someone-else'}}))
        project(w, PRINTS)
        self.assertEqual(w.run('merge.py', 'settle', REPO, 7, 12, cwd=w.dir / 'project'), (0, 'no queued merge'))
        self.assertEqual(w.writes(), [])

    def test_an_earlier_heads_removal_never_blocks_the_replacement_head(self):
        left = {'createdAt': '2026-01-01T00:00:00Z', 'reason': 'failed checks', 'beforeCommit': {'oid': OTHER}}
        w = World(self, pr=pr(isMergeQueueEnabled=True, left=left), comments={'7': [comment(4000, self.receipt())]})
        project(w, PRINTS)
        self.assertEqual(self.merge(w), (0, 'queued; recorded 4000'))
        self.assertEqual(w.writes(), [{'enqueue': 'PR_synthetic7', 'head': HEAD}])
        self.assertEqual(w.bodies(7), [self.receipt()])

    def test_the_replacement_heads_unconfirmed_receipt_is_retried_after_an_earlier_removal(self):
        left = {'createdAt': '2026-01-01T00:00:00Z', 'reason': 'failed checks', 'beforeCommit': {'oid': OTHER}}
        w = World(self, pr=pr(isMergeQueueEnabled=True, left=left), faults={'post': 'lost'}, me='someone-else')
        project(w, PRINTS)
        code, out = self.merge(w)
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('queued; receipt unconfirmed '), out)
        value = w.load()
        value['me'] = value['comments']['7'][0]['user']['login'] = 'openwiz[bot]'
        value['pr'].update(isInMergeQueue=False, mergeQueueEntry=None)
        w.save(value)
        self.assertEqual(self.merge(w), (0, 'queued; recorded 5001'))
        self.assertEqual(sum('enqueue' in x for x in w.writes()), 2)
        self.assertFalse(any(b.startswith('launch-fleet: merge blocked') for b in w.bodies(7)))

    def test_a_removal_whose_commit_cannot_be_read_writes_nothing(self):
        left = {'createdAt': '2026-01-01T00:00:00Z', 'reason': 'failed checks'}
        w = World(self, pr=pr(isMergeQueueEnabled=True, left=left), comments={'7': [comment(4000, self.receipt())]})
        project(w, PRINTS)
        code, out = self.merge(w)
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('unknown: '), out)
        self.assertEqual(w.writes(), [])

    def test_settling_after_the_fleets_direct_merge_posts_the_cost_it_still_owes(self):
        w = World(self, pr=pr())
        project(w, PRINTS)
        w.update(faults={'post': 'fail'})
        code, out = Merge.merge(self, w, '--ticket', 12, '--base-rule-checked')
        self.assertEqual(code, 1, out)
        self.assertEqual((w.load()['pr']['state'], w.bodies(12)), ('MERGED', []))
        settle = lambda: w.run('merge.py', 'settle', REPO, 7, 12, cwd=w.dir / 'project')
        self.assertEqual(settle(), (0, 'cost posted 5001'))
        self.assertEqual(w.bodies(12), ['launch-fleet: cost: ' + LINE])
        self.assertEqual(settle(), (0, 'cost already posted 5001'))
        self.assertEqual(w.bodies(12), ['launch-fleet: cost: ' + LINE])

    def test_a_direct_merge_after_an_earlier_heads_receipt_still_settles_its_cost(self):
        old = 'launch-fleet: merge queued %s: APPROVE 1 and plan approval 2' % OTHER
        w = World(self, pr=pr(), comments={'7': [comment(4000, old)]})
        project(w, PRINTS)
        w.update(faults={'post': 'fail'})
        code, out = Merge.merge(self, w, '--ticket', 12, '--base-rule-checked')
        self.assertEqual(code, 1, out)
        self.assertEqual((w.load()['pr']['state'], w.bodies(12)), ('MERGED', []))
        settle = lambda: w.run('merge.py', 'settle', REPO, 7, 12, cwd=w.dir / 'project')
        self.assertEqual(settle(), (0, 'cost posted 5001'))
        self.assertEqual(w.bodies(12), ['launch-fleet: cost: ' + LINE])
        self.assertEqual(settle(), (0, 'cost already posted 5001'))

    def test_a_queued_pull_request_without_its_receipt_gets_one(self):
        # catches: a pull request someone else queued staying without the receipt the removal guard
        # and settle read (#1631).
        queued = {'headCommit': {'oid': HEAD}}
        w = World(self, pr=pr(isMergeQueueEnabled=True, isInMergeQueue=True, mergeQueueEntry=queued))
        project(w, PRINTS)
        self.assertEqual(self.merge(w), (0, 'queued; recorded 5001'))
        self.assertEqual(self.merge(w), (0, 'queued; the queue merges it or lets it go'))
        self.assertEqual(w.bodies(7), [self.receipt()])

    def test_a_receipt_written_but_not_read_back_is_not_posted_twice(self):
        w = World(self, pr=pr(isMergeQueueEnabled=True), faults={'post': 'lost'}, me='someone-else')
        project(w, PRINTS)
        code, out = self.merge(w)
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('queued; receipt unconfirmed '), out)
        # The read-back missed it; the next wake reads it as the record author's.
        value = w.load()
        value['me'] = value['comments']['7'][0]['user']['login'] = 'openwiz[bot]'
        w.save(value)
        self.assertEqual(self.merge(w), (0, 'queued; the queue merges it or lets it go'))
        self.assertEqual(w.bodies(7), [self.receipt()])
        self.assertEqual(sum('enqueue' in x for x in w.writes()), 1)


# RC3 (#1831): the late look, read with the checkpoints contract's own forms
# (contracts/checkpoints.v1.md); the contract's synthetic decider `Robin` joins the decider list.
_merge = importlib.util.spec_from_file_location('launch_fleet_merge', HERE / 'merge.py')
M = importlib.util.module_from_spec(_merge)
_merge.loader.exec_module(M)
CONTRACT = M.CONTRACT
SPEC = '## Problem Statement\n\nA synthetic settings page.\n\n## Checkpoints\n\n- One-way door: %s\n- User-visible: %s\n'
VISIBLE, RELEASE, NEITHER = SPEC % ('no', 'yes'), SPEC % ('no', 'yes, a release'), SPEC % ('no', 'no')
ASKED = ('launch-fleet: late look asked #7 at %s\n\nEvidence: preview https://preview.example.test/settings\n'
         'Look for: the settings page saves a synthetic name.')
EVIDENCE = ('Evidence: preview https://preview.example.test/settings\n'
            'Look for: the settings page saves a synthetic name.\n')
LOOKED = ('**Late look by %s, 2030-01-05, #7 at %s:** %s: the settings page works as the evidence shows.\n'
          'Private record: https://github.com/jparker2006/ClosedWiz/issues/9001#issuecomment-9000000011')
MERGED = 'merged %s; cost posted ' % ('f' * 40)


def ticket(spec, siblings=(('CLOSED', 11),), repo=REPO, more=False):
    """Ticket #12 of spec #40: `spec` is the spec's body, `siblings` its other planned tickets, each
    (state, number) or (state, number, its closing pull requests as (number, state, in the merge queue))."""
    def node(state, n, prs=()):
        refs = [{'number': p, 'state': st, 'isInMergeQueue': q, 'repository': {'nameWithOwner': repo}}
                for p, st, q in prs]
        return {'number': n, 'state': state, 'repository': {'nameWithOwner': repo},
                'closedByPullRequestsReferences': {'pageInfo': {'hasNextPage': False}, 'nodes': refs}}
    nodes = [node(*x) for x in siblings]
    nodes.append(node('OPEN', 12, [(7, 'OPEN', False)]))
    return {'12': {'number': 12, 'parent': {'number': 40, 'body': spec, 'repository': {'nameWithOwner': repo},
                                            'subIssues': {'pageInfo': {'hasNextPage': more}, 'nodes': nodes}}}}


def said(login, body):
    return {'id': 0, 'body': body, 'user': {'login': login}, 'created_at': '2026-01-01T00:00:00Z'}


class LateLook(unittest.TestCase):
    """merge.py run in process, so the contract's path and its test decider can be set."""

    def run_merge(self, w, *argv):
        out = io.StringIO()
        cwd = os.getcwd()
        os.chdir(w.dir / 'project')
        try:
            with mock.patch.dict(os.environ, w.env), mock.patch.object(M, 'DECIDERS', M.DECIDERS + ('Robin',)), \
                    contextlib.redirect_stdout(out):
                code = M.main([str(a) for a in argv])
        finally:
            os.chdir(cwd)
        return code, out.getvalue().strip()

    def world(self, spec, comments=(), **extra):
        w = World(self, pr=pr(), tickets=ticket(spec, **extra))
        project(w, PRINTS)
        w.update(comments={'40': [dict(c, id=4000 + i) for i, c in enumerate(comments)]})
        return w

    def merge(self, w):
        return self.run_merge(w, 'merge', REPO, 7, HEAD, 'check', 'APPROVE 1 and plan approval 2', '--ticket', 12,
                              '--base-rule-checked')

    def ask(self, w, text=EVIDENCE):
        (w.dir / 'evidence.txt').write_text(text)
        return self.run_merge(w, 'ask', REPO, 7, HEAD, 'check', '--ticket', 12, w.dir / 'evidence.txt')

    def add(self, w, *comments):
        value = w.load()
        items = value['comments'].setdefault('40', [])
        for c in comments:
            value['next_id'] += 1
            items.append(dict(c, id=value['next_id']))
        w.save(value)

    def merges(self, w):
        return [x for x in w.writes() if 'merge' in x]

    def test_a_user_visible_specs_final_merge_waits_for_one_ask_and_the_late_look(self):
        # catches: the final merge of a user-visible spec landing before the owner looked at its
        # evidence, the ask posted twice for one head, or a "changes asked" look releasing it (P3).
        w = self.world(VISIBLE)
        self.assertEqual(self.merge(w), (1, 'held: ask-due: post the evidence ask on %s#40 with merge.py ask' % REPO))
        self.assertEqual(w.writes(), [])
        code, out = self.ask(w)
        self.assertEqual((code, out), (0, 'ask posted 5001'))
        self.assertEqual(w.bodies(40), [ASKED % HEAD])
        self.assertEqual(self.ask(w), (0, 'ask already posted 5001'))
        self.assertEqual(self.merge(w), (1, 'held: look-due: the late look asked on %s#40 is not recorded' % REPO))
        self.add(w, said('synthetic-owner', LOOKED % ('Robin', HEAD, 'changes asked')))
        self.assertEqual(self.merge(w), (1, 'held: changes-asked: the late look on %s#40 asked for changes' % REPO))
        self.assertEqual(self.merges(w), [])
        self.add(w, said('openwiz[bot]', LOOKED % ('Robin', HEAD, 'approved')))
        code, out = self.merge(w)
        self.assertEqual(code, 0, out)
        self.assertTrue(out.startswith(MERGED), out)
        self.assertEqual(len(self.merges(w)), 1)
        self.assertEqual(len([b for b in w.bodies(40) if b.startswith('launch-fleet: late look asked')]), 1)

    def test_a_release_spec_is_held_the_same_way(self):
        # catches: `User-visible: yes, a release` read as anything but user-visible, so a release
        # merges without the owner's late look.
        w = self.world(RELEASE)
        self.assertEqual(self.merge(w)[0], 1)
        self.assertEqual(self.ask(w), (0, 'ask posted 5001'))
        self.assertEqual(self.merge(w)[1], 'held: look-due: the late look asked on %s#40 is not recorded' % REPO)
        self.add(w, said('openwiz[bot]', LOOKED % ('Robin', HEAD, 'approved')))
        self.assertTrue(self.merge(w)[1].startswith(MERGED))

    def test_every_other_merge_flows_as_today(self):
        # catches: the hold reaching a merge the contract lets flow: a ticket that is not its spec's
        # last open one, a spec answered no, one-way door only, a spec planned before the contract (P4),
        # a template quoted in a fenced block, or a ticket with no spec.
        fenced = '## Problem\n\nThe template:\n\n```text\n## Checkpoints\n\n- One-way door: no\n- User-visible: yes\n```\n'
        cases = [('not final', dict(spec=VISIBLE, siblings=[('OPEN', 11)])),
                 ('both no', dict(spec=NEITHER)),
                 ('one-way door only', dict(spec=SPEC % ('yes', 'no'))),
                 ('absent', dict(spec='## Problem Statement\n\nPlanned before the contract.\n')),
                 ('fenced example', dict(spec=fenced))]
        for name, case in cases:
            with self.subTest(name):
                w = self.world(case.pop('spec'), **case)
                code, out = self.merge(w)
                self.assertEqual(code, 0, out)
                self.assertTrue(out.startswith(MERGED), out)
                self.assertEqual(w.bodies(40), [])
        with self.subTest('no spec'):
            w = self.world(VISIBLE)
            w.update(tickets={'12': {'number': 12, 'parent': None}})
            self.assertTrue(self.merge(w)[1].startswith(MERGED))

    def test_an_unreadable_answer_holds_like_a_yes(self):
        # catches: a near-miss heading, a bad answer line or a Checkpoints section behind an inline
        # code span (#1922) read as absent, so the final merge skips the late look.
        span = 'Status: ```synthetic status```\n\n' + VISIBLE
        for name, spec in [('near-miss heading', VISIBLE.replace('## Checkpoints', '## Checkpoint answers')),
                           ('bad answer', SPEC % ('no', 'maybe')), ('inline code span', span)]:
            with self.subTest(name):
                w = self.world(spec)
                self.assertEqual(self.merge(w)[1],
                                 'held: ask-due: post the evidence ask on %s#40 with merge.py ask' % REPO)
                self.assertEqual(self.merges(w), [])

    def test_only_the_owners_recorded_look_at_this_head_after_its_ask_releases_it(self):
        # catches: a merge released by a look at another head, a look before the ask, a look or ask
        # by someone who is not a record author, another decider's look, or an invalid record.
        ask = said('openwiz[bot]', ASKED % HEAD)
        good = LOOKED % ('Robin', HEAD, 'approved')
        quoted = good.replace('the settings page works', '"it works"')
        cases = [('another head', [said('openwiz[bot]', ASKED % OTHER), said('openwiz[bot]', LOOKED % ('Robin', OTHER, 'approved'))], 'ask-due'),
                 ('ask by a stranger', [said('synthetic-stranger', ASKED % HEAD)], 'ask-due'),
                 ('record before the ask', [said('openwiz[bot]', good), ask], 'look-due'),
                 ('record by a stranger', [ask, said('synthetic-stranger', good)], 'look-due'),
                 ('another decider', [ask, said('openwiz[bot]', LOOKED % ('Casey', HEAD, 'approved'))], 'look-due'),
                 ('quoted words', [ask, said('openwiz[bot]', quoted)], 'look-due'),
                 ('changes after approved', [ask, said('openwiz[bot]', good),
                                             said('openwiz[bot]', LOOKED % ('Robin', HEAD, 'changes asked'))],
                  'changes-asked')]
        for name, comments, why in cases:
            with self.subTest(name):
                w = self.world(VISIBLE, comments)
                code, out = self.merge(w)
                self.assertEqual((code, out.split(':')[:2]), (1, ['held', ' ' + why]), out)
                self.assertEqual(self.merges(w), [])

    def test_an_ask_that_shows_code_or_breaks_the_form_is_refused_before_any_write(self):
        # catches: an evidence ask that points the owner at code (a pull request, a file) or carries
        # extra lines, against the contract's "never code".
        w = self.world(VISIBLE)
        for text, code in [('Evidence: preview https://github.com/synthetic-owner/synthetic-repo/pull/7\n'
                            'Look for: the page.\n', 'evidence-code'),
                           ('Look for: the page.\n', 'evidence-missing'),
                           (EVIDENCE + '```diff\n```\n', 'ask-line')]:
            with self.subTest(code):
                self.assertEqual(self.ask(w, text), (1, 'refused: the evidence ask is invalid: ' + code))
        self.assertEqual(w.writes(), [])

    def test_no_ask_while_nothing_is_held(self):
        # catches: an ask posted for a merge that flows, which would ask the owner about a refactor.
        w = self.world(NEITHER)
        self.assertEqual(self.ask(w), (1, 'refused: no late look is due: the merge flows'))
        self.assertEqual(w.writes(), [])

    def test_the_ask_goes_to_the_specs_own_repository(self):
        # catches: the ask and the records read on the pull request's repository when the ticket and
        # its spec live in another, so the hold could never be released (or the ask lands nowhere).
        w = World(self, pr=pr(closes=closes((TICKETS, 12))), others={TICKETS: {'tickets': ticket(VISIBLE, repo=TICKETS)}})
        project(w, PRINTS)
        (w.dir / 'evidence.txt').write_text(EVIDENCE)
        self.assertEqual(self.run_merge(w, 'ask', REPO, 7, HEAD, 'check', '--ticket', '%s#12' % TICKETS, w.dir / 'evidence.txt'),
                         (0, 'ask posted 5001'))
        self.assertEqual(w.others[TICKETS].bodies(40), [ASKED % HEAD])
        self.assertEqual(w.bodies(40), [])

    def test_an_unreadable_spec_or_contract_merges_nothing(self):
        # catches: a spec whose planned tickets or comments can't be read whole, or a missing
        # contract, treated as "no late look", so a held merge slips through.
        w = self.world(VISIBLE, more=True)
        self.assertEqual(self.merge(w), (1, "unknown: spec %s#40's planned tickets could not be read whole; "
                                            'nothing was merged' % REPO))
        for name, change in [('a state it does not know', lambda t: t['parent']['subIssues']['nodes'][0].update(state='MERGED')),
                             ('no page info', lambda t: t['parent']['subIssues'].update(pageInfo=None)),
                             ('a body that is not text', lambda t: t['parent'].update(body=None)),
                             ('no such ticket', lambda t: t.clear())]:
            with self.subTest(name):
                w = self.world(VISIBLE)
                value = w.load()
                change(value['tickets']['12'])
                value['tickets'] = {k: v for k, v in value['tickets'].items() if v} or {'12': None}
                w.save(value)
                self.assertEqual(self.merge(w), (1, 'unknown: the spec of %s#12 could not be read; nothing was merged'
                                                 % REPO))
                self.assertEqual(self.merges(w), [])
        w = self.world(VISIBLE)
        w.update(faults={'read': 'fail'})
        self.assertEqual(self.merge(w), (1, 'unknown: the comments on %s#40 could not be read; nothing was merged'
                                         % REPO))
        partial = w.dir / 'partial.md'
        partial.write_text(CONTRACT.read_text().replace('  "record_pointer"', '  "record_pointer_gone"'))
        for contract in (w.dir / 'missing.md', partial):
            with self.subTest(contract.name):
                w = self.world(VISIBLE)
                with mock.patch.object(M, 'CONTRACT', contract):
                    out = io.StringIO()
                    with mock.patch.dict(os.environ, w.env), contextlib.redirect_stdout(out):
                        code = M.main(['merge', REPO, '7', HEAD, 'check', 'APPROVE 1', '--ticket', '12',
                                       '--base-rule-checked'])
                self.assertEqual((code, out.getvalue().strip()),
                                 (1, 'unknown: the checkpoints contract could not be read; nothing was merged'))
                self.assertEqual(self.merges(w), [])

    def test_a_sibling_already_queued_or_merged_makes_this_the_final_merge(self):
        # catches (review R1): two tickets of a user-visible spec both entering the merge queue while
        # each still sees the other open, so the final merge lands without the owner's late look.
        queued = [('OPEN', 11, [(6, 'OPEN', True)])]
        for name, siblings in [('queued', queued), ('merged, not yet closed', [('OPEN', 11, [(6, 'MERGED', False)])]),
                               ('queued, beside a closed one', [('CLOSED', 10)] + queued)]:
            with self.subTest(name):
                w = World(self, pr=pr(isMergeQueueEnabled=True), tickets=ticket(VISIBLE, siblings=siblings))
                project(w, PRINTS)
                code, out = self.run_merge(w, 'merge', REPO, 7, HEAD, 'check', 'APPROVE 1', '--ticket', 12)
                self.assertEqual((code, out), (1, 'held: ask-due: post the evidence ask on %s#40 with merge.py ask'
                                               % REPO))
                self.assertEqual(w.writes(), [])
        with self.subTest('a sibling still in review'):
            w = World(self, pr=pr(isMergeQueueEnabled=True),
                      tickets=ticket(VISIBLE, siblings=[('OPEN', 11, [(6, 'OPEN', False)])]))
            project(w, PRINTS)
            self.assertEqual(self.run_merge(w, 'merge', REPO, 7, HEAD, 'check', 'APPROVE 1', '--ticket', 12),
                             (0, 'queued; recorded 5001'))

    def test_an_ask_waits_for_a_green_mergeable_head(self):
        # catches (review R2): the owner asked to look at evidence for a head the fleet can't merge,
        # because a required check turned red or the head conflicts after the hold was read.
        w = self.world(VISIBLE)
        self.assertEqual(self.merge(w)[1], 'held: ask-due: post the evidence ask on %s#40 with merge.py ask' % REPO)
        value = w.load()
        value['pr']['checks'] = [{'__typename': 'CheckRun', 'name': 'check', 'conclusion': 'FAILURE'}]
        w.save(value)
        self.assertEqual(self.ask(w), (1, 'refused: no ask for a head that cannot merge: not every required check '
                                          'is green on it: check'))
        for state in ('CONFLICTING', 'UNKNOWN'):
            with self.subTest(state):
                w = self.world(VISIBLE)
                w.update(pr=pr(mergeable=state))
                self.assertEqual(self.ask(w), (1, 'refused: no ask for a head that cannot merge: mergeable: ' + state))
                self.assertEqual(w.writes(), [])
        with self.subTest('merge offers no ask for a conflicting head'):
            w = self.world(VISIBLE)
            w.update(pr=pr(mergeable='CONFLICTING'))
            self.assertEqual(self.merge(w), (1, 'blocked: not mergeable: CONFLICTING; recorded 5001'))
            self.assertEqual(w.bodies(40), [])
            self.assertEqual(self.merges(w), [])

    def test_the_documented_late_look_commands_run_as_written(self):
        # catches: reviews.md's `look` or `ask` command naming a verb, argument order or path
        # merge.py doesn't take, so a held merge's ask is never posted and it waits forever.
        text = (HERE.parent / 'references/reviews.md').read_text()
        found = dict((m.group(2), m.group(1)) for m in
                     re.finditer(r'`(python3 -I [^`]*merge\.py"? (look|ask) [^`]*)`', text))
        self.assertEqual(sorted(found), ['ask', 'look'])
        w = self.world(VISIBLE)
        (w.dir / 'evidence.txt').write_text(EVIDENCE)
        values = {"<this skill's folder>": str(HERE.parent), '<owner>/<repo>': REPO, '<P>': '7', '<commit>': HEAD,
                  '<checks>': 'check', '<N>': '12', '<file>': str(w.dir / 'evidence.txt')}
        for verb, want in [('look', 'held: ask-due: post the evidence ask on %s#40 with merge.py ask' % REPO),
                           ('ask', 'ask posted 5001'),
                           ('look', 'held: look-due: the late look asked on %s#40 is not recorded' % REPO)]:
            command = found[verb]
            for name, value in values.items():
                command = command.replace(name, value)
            argv = shlex.split(command)
            self.assertEqual(argv[:2], ['python3', '-I'])
            self.assertNotRegex(' '.join(argv), r'<[^>]+>', 'a placeholder left unfilled')
            self.assertEqual(self.run_merge(w, *argv[3:]), (0, want))


# The feedback-loop contract (v1, contracts/feedback-loop.v1.md in OpenWiz, FL1 #1840): its
# landed fixtures, as GitHub answers them. Every account, number and text is synthetic.
DEST = 'openwizdev/OpenWiz'
MARK = 'OpenWiz feedback operation 3f2a9c4e1b7d40a6958e0c2d7b1a4f63'
LANDED = 'Landed: the fix for this report merged in openwizdev/OpenWiz#9201 and will ship in OpenWiz 9.4.2.'
SKILLS = 'openwizdev/WizSkills'


def issue(number, body, login='openwiz[bot]', labels=(), milestone='9.4.2', **extra):
    value = {'number': number, 'user': {'login': login}, 'body': body, 'labels': [{'name': x} for x in labels],
             'milestone': milestone and {'title': milestone}}
    value.update(extra)
    return value


def brief(number, report=9101, **extra):
    return issue(number, 'Keep the approve button above the footer.\n\nReport: #%d' % report,
                 labels=['ready-for-agent'], **extra)


REPORT = issue(9101, 'On a 360-pixel screen the approve button sits under the footer.\n\n' + MARK,
               login='synthetic-user', labels=['feedback'])


class Landed(unittest.TestCase):
    """P4 (#1848): a merged fix posts the contract's landed comment on its report, once."""

    def world(self, issues, close=(9106, 9101), comments=None, repo=DEST, **extra):
        refs = [{'number': n, 'repository': {'nameWithOwner': repo},
                 'body': issues[str(n)]['body'] if str(n) in issues else ''} for n in close]
        value = pr(number=9201, closes=refs, state='MERGED', mergeCommit={'oid': 'c' * 40})
        return World(self, repo=repo, pr=value, issues=issues, comments=comments or {}, **extra)

    def merge(self, w, ticket=9106, repo=DEST):
        return w.run('merge.py', 'merge', repo, 9201, HEAD, 'check', 'APPROVE 1 and plan approval 2',
                     '--ticket', ticket, cwd=w.dir / 'project')

    def posts(self, w):
        return [(x['post'], x['body']) for x in w.writes() if 'post' in x and not x['body'].startswith('launch-fleet:')]

    def setUp(self):
        self.issues = {'9106': brief(9106), '9101': REPORT}

    def test_a_merged_fix_posts_one_landed_comment_and_a_second_run_posts_nothing(self):
        # catches: a merge that never tells the reporter, or tells them again on every later run
        # (a re-run after an unknown cost, or settle after the queue merged it).
        w = self.world(self.issues)
        project(w, None)
        code, out = self.merge(w)
        self.assertEqual((code, out.split('; ')[0]), (0, 'merged ' + 'c' * 40), out)
        self.assertEqual(self.posts(w), [(9101, LANDED)])
        self.assertTrue(out.endswith('; cost posted 5002; landed posted 5001 on openwizdev/OpenWiz#9101'), out)
        self.assertEqual(self.merge(w), (0, 'merged %s; cost already posted 5002; landed already posted 5001'
                                         % ('c' * 40)))
        self.assertEqual(w.run('merge.py', 'settle', DEST, 9201, 9106, cwd=w.dir / 'project'),
                         (0, 'no queued merge; landed already posted 5001'))
        self.assertEqual(self.posts(w), [(9101, LANDED)])
        self.assertEqual(w.bodies(9106), ['launch-fleet: cost: Ticket #9106 cost (PR #9201): builder unknown; reviewer unknown; CI unknown; total unknown'])

    def test_a_held_final_merge_tells_no_report_it_landed(self):
        # catches (RC3 #1831 with FL4 #1848): a user-visible spec's final merge posting its landed
        # comment, or merging, before the owner's late look releases it.
        w = self.world(self.issues)
        value = w.load()
        value['pr'].update(state='OPEN', mergeCommit=None)
        spec = ticket(VISIBLE, repo=DEST)['12']
        spec['parent']['subIssues']['nodes'][-1]['number'] = 9106
        value['tickets'] = {'9106': dict(spec, number=9106)}
        w.save(value)
        project(w, None)
        code, out = w.run('merge.py', 'merge', DEST, 9201, HEAD, 'check', 'APPROVE 1 and plan approval 2',
                          '--ticket', 9106, '--base-rule-checked', cwd=w.dir / 'project')
        self.assertEqual((code, out), (1, 'held: ask-due: post the evidence ask on %s#40 with merge.py ask' % DEST))
        self.assertEqual(w.writes(), [])

    def test_a_report_landed_by_an_earlier_fix_gets_nothing(self):
        # catches: the once-per-report rule read per pull request, so a second fix posts again.
        earlier = comment(4000, 'Landed: the fix for this report merged in openwizdev/WizSite#9200 '
                                'and will ship in OpenWiz 9.4.1.')
        w = self.world({'9108': brief(9108), '9101': REPORT}, close=(9108,), comments={'9101': [earlier]})
        project(w, None)
        self.assertEqual(self.merge(w, 9108)[1].split('; ')[-1], 'landed already posted 4000')
        self.assertEqual(self.posts(w), [])

    def test_only_a_record_authors_landed_comment_counts(self):
        # catches: anyone pasting the landed line on a report silencing the real one.
        forged = comment(4000, LANDED, login='synthetic-user')
        # Not the contract's form: the fix it names is outside openwizdev (amended FL1 2f54a80).
        elsewhere = comment(4001, LANDED.replace(DEST, 'synthetic-owner/OpenWiz'))
        w = self.world(self.issues, comments={'9101': [forged, elsewhere]})
        project(w, None)
        self.assertEqual(self.merge(w)[0], 0)
        self.assertEqual(self.posts(w), [(9101, LANDED)])

    def test_a_merge_that_closes_no_report_posts_nothing(self):
        # catches: a landed comment on an ordinary ticket, a forged or misplaced link, a link to
        # an issue that is no report, a pull request or a report with no version milestone.
        plain = issue(9107, 'An ordinary ticket.', labels=['ready-for-agent'])
        cases = {
            'ordinary ticket': ({'9107': plain}, (9107,), 9107),
            'report closed directly': ({'9101': REPORT}, (9101,), 9101),
            'forged link': ({'9109': brief(9109, login='synthetic-user'), '9101': REPORT}, (9109,), 9109),
            'link not last': ({'9109': issue(9109, 'Report: #9101\n\nMore words.'), '9101': REPORT}, (9109,), 9109),
            'two links': ({'9109': issue(9109, 'Report: #9100\n\nReport: #9101'), '9101': REPORT}, (9109,), 9109),
            'not a report': ({'9106': brief(9106), '9101': issue(9101, 'I saw this line:\n\n%s\n\nIs it a bug?' % MARK,
                                                                  login='synthetic-user')}, (9106,), 9106),
            'a pull request': ({'9106': brief(9106), '9101': dict(REPORT, pull_request={'url': 'x'})}, (9106,), 9106),
            'no milestone': ({'9106': brief(9106), '9101': dict(REPORT, milestone=None)}, (9106,), 9106),
            'not a version': ({'9106': brief(9106), '9101': dict(REPORT, milestone={'title': 'Later'})}, (9106,), 9106),
            'a bare milestone': ({'9106': brief(9106), '9101': dict(REPORT, milestone='9.4.2')}, (9106,), 9106),
        }
        for name, (issues, close, ticket) in cases.items():
            with self.subTest(name):
                w = self.world(issues, close=close)
                project(w, None)
                code, out = self.merge(w, ticket)
                self.assertEqual(code, 0, out)
                self.assertEqual(self.posts(w), [])

    def test_a_report_found_by_its_marker_alone_gets_it(self):
        # catches: an agent-route report, which carries the marker before triage labels it, missed.
        w = self.world({'9106': brief(9106), '9101': dict(REPORT, labels=[])})
        project(w, None)
        self.assertEqual(self.merge(w)[0], 0)
        self.assertEqual(self.posts(w), [(9101, LANDED)])

    def test_two_briefs_linking_one_report_lead_to_one_comment(self):
        # catches: one comment per brief instead of per report.
        w = self.world({'9106': brief(9106), '9108': brief(9108), '9101': REPORT}, close=(9106, 9108))
        project(w, None)
        self.assertEqual(self.merge(w)[0], 0)
        self.assertEqual(self.posts(w), [(9101, LANDED)])

    def cross(self, repo=SKILLS, issues=None, brief_repo=DEST, comments=None):
        """A fix merged in REPO that closes OpenWiz's brief and report (planner ruling 7040055832 on #1848)."""
        issues = issues or self.issues
        refs = [{'number': n, 'repository': {'nameWithOwner': brief_repo if n == 9106 else DEST},
                 'body': issues[str(n)]['body']} for n in (9106, 9101)]
        value = pr(number=9201, closes=refs, state='MERGED', mergeCommit={'oid': 'c' * 40})
        dest = {'issues': {} if brief_repo != DEST else issues, 'comments': comments or {}}
        others = {DEST: dest} if repo != DEST else {}
        w = World(self, repo=repo, pr=value, issues=issues if brief_repo != DEST else {}, others=others)
        project(w, None)
        code, out = self.merge(w, '%s#9106' % brief_repo, repo=repo)
        return code, out, w.others[DEST] if DEST in w.others else w

    def test_a_fix_merged_in_another_openwizdev_repository_names_it_in_full(self):
        # catches: a fix that lands in WizSkills or WizSite never telling the reporter, or the
        # comment's bare `#9201` naming OpenWiz's pull request 9201 instead of the fix.
        code, out, dest = self.cross()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.posts(dest), [(9101, LANDED.replace(DEST, SKILLS))])
        self.assertTrue(out.endswith('; landed posted 5001 on openwizdev/OpenWiz#9101'), out)

    def test_a_fix_outside_openwizdev_posts_nothing(self):
        # catches: another owner's merge (a fork, a lookalike repository) speaking on a report.
        code, out, dest = self.cross(repo='synthetic-owner/WizSkills')
        self.assertEqual(code, 0, out)
        self.assertEqual(self.posts(dest), [])

    def test_a_brief_outside_openwiz_posts_nothing(self):
        # catches: a report link on another repository's issue followed to an OpenWiz issue.
        code, out, dest = self.cross(brief_repo=SKILLS)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.posts(dest), [])

    def test_a_lost_landed_response_is_reconciled_never_posted_twice(self):
        # catches: a blind retry after the response was lost, so the reporter is told twice.
        w = self.world(self.issues)
        project(w, None)
        # The cost record posts first; lose the landed comment's response only.
        gh = w.dir / 'bin' / 'gh'
        head, rest = gh.read_text().split('\n', 1)
        lose = w.dir / 'lose.py'
        lose.write_text('import json, os\nw = json.load(open(os.environ["FAKE_WORLD"]))\n'
                        'w["faults"]["post"] = "lost"\njson.dump(w, open(os.environ["FAKE_WORLD"], "w"))\n')
        gh.write_text('%s\ncase " $* " in *" POST "*"issues/9101/comments"*) "%s" -I "%s";; esac\n%s'
                      % (head, sys.executable, lose, rest))
        code, out = self.merge(w)
        self.assertEqual(code, 0, out)
        self.assertTrue(out.split('; ')[-1].startswith('landed unknown: '), out)
        gh.write_text('%s\n%s' % (head, rest))
        self.assertEqual(self.merge(w)[1].split('; ')[-1], 'landed already posted 5001')
        self.assertEqual(self.posts(w), [(9101, LANDED)])

    def test_an_unreadable_report_posts_nothing_and_says_unknown(self):
        # catches: a failed read of the report's comments treated as none, then posting again.
        earlier = comment(4000, LANDED)
        w = self.world(self.issues, comments={'9101': [earlier]})
        project(w, None)
        value = w.load()
        value['comments']['9106'] = [comment(3999, 'launch-fleet: cost unknown (PR #9201): no cost command')]
        value['faults'] = {'read': 'fail'}
        w.save(value)
        code, out = self.merge(w)
        self.assertEqual(code, 0, out)
        self.assertTrue(out.split('; ')[-1].startswith('landed unknown: '), out)
        self.assertEqual(self.posts(w), [])

    def archive(self, w):
        """One wake's archive row, filled for this fix: (archives, its output) (#1848 R1)."""
        row = next(x for x in (HERE.parent / 'SKILL.md').read_text().splitlines() if x.startswith('| `archive #N` |'))
        command = re.findall(r'`(python3 -I [^`]*merge\.py"? settle [^`]*)`', row)[0]
        for name, value in {"<this skill's folder>": str(HERE.parent), '<owner>/<repo>': DEST, '<P>': '9201',
                            '<N>': '9106'}.items():
            command = command.replace(name, value)
        settled = [x.split(' <')[0] for x in re.findall(r'`([^`]+)`', re.search(r'archives? only after ([^;.]*)',
                                                                               row).group(1))]
        r = subprocess.run([sys.executable] + shlex.split(command)[1:], capture_output=True, text=True, env=w.env,
                           cwd=w.dir / 'project', timeout=60)
        out = r.stdout.strip()
        return any(out.startswith(x) for x in settled), out

    def test_a_transient_report_read_keeps_the_work_open_until_a_later_wake_lands_it(self):
        # catches: (#127 R1) a `landed unknown:` after a direct or a queued merge archived as
        # settled, so the reporter is never told; the archive row ran settle only after the queue.
        receipt = comment(4000, 'launch-fleet: merge queued %s: APPROVE 1 and plan approval 2' % HEAD)
        for name, comments in {'direct': {}, 'queued': {'9201': [receipt]}}.items():
            with self.subTest(name):
                w = self.world(self.issues, comments=comments, faults={'read_of': '9101'})
                project(w, None)
                if name == 'direct':
                    code, out = self.merge(w)
                    self.assertEqual(code, 0, out)
                    self.assertIn('; landed unknown: ', out)
                    w.update(faults={'read_of': '9101'})
                archives, out = self.archive(w)  # this wake: the report's comments can't be read
                self.assertFalse(archives, out)
                self.assertEqual(w.bodies(9101), [])
                archives, out = self.archive(w)  # the next wake re-checks the report and posts
                self.assertTrue(archives, out)
                self.assertEqual(w.bodies(9101), [LANDED])
                self.assertEqual(self.archive(w)[0], True)
                self.assertEqual(w.bodies(9101), [LANDED])
        # The row settles every merged pull request, so a direct merge's landed comment is retried too.
        row = next(x for x in (HERE.parent / 'SKILL.md').read_text().splitlines() if x.startswith('| `archive #N` |'))
        self.assertNotIn('through the merge queue', row)

    def test_two_runs_racing_on_one_report_leave_the_earliest_comment_only(self):
        # catches: (#127 R2) two runs both reading no landed comment, then both posting and each
        # reading back its own, so the reporter is told twice.
        w = self.world(self.issues)
        project(w, None)
        w.env['FAKE_RACE'] = '9101'
        runs = [subprocess.Popen([sys.executable, '-I', str(HERE / 'merge.py'), 'cost', DEST, '9201', HEAD, '9106'],
                                 stdout=subprocess.PIPE, text=True, env=w.env, cwd=w.dir / 'project')
                for _ in range(2)]
        outs = sorted(r.communicate(timeout=60)[0].strip().split('; ')[-1] for r in runs)
        kept = [c for c in w.load()['comments']['9101']]
        self.assertEqual([c['body'] for c in kept], [LANDED], outs)
        self.assertEqual(outs, ['landed already posted %d' % kept[0]['id'],
                                'landed posted %d on openwizdev/OpenWiz#9101' % kept[0]['id']])
        posted = [x['body'] for x in w.writes() if x.get('post') == 9101]
        deleted = [x['delete'] for x in w.writes() if 'delete' in x]
        self.assertEqual((len(posted), len(deleted)), (2, 1))
        self.assertGreater(deleted[0], kept[0]['id'])

    def test_a_refused_duplicate_delete_is_retried_and_keeps_the_settle_open(self):
        receipt = comment(4000, 'launch-fleet: merge queued %s: APPROVE 1 and plan approval 2' % HEAD)
        w = self.world(self.issues, comments={'9201': [receipt]}, faults={'delete': 'fail'})
        project(w, None)
        w.env['FAKE_RACE'] = '9101'
        runs = [subprocess.Popen([sys.executable, '-I', str(HERE / 'merge.py'), 'cost', DEST, '9201', HEAD, '9106'],
                                 stdout=subprocess.PIPE, text=True, env=w.env, cwd=w.dir / 'project')
                for _ in range(2)]
        outs = sorted(r.communicate(timeout=60)[0].strip().split('; ')[-1] for r in runs)
        del w.env['FAKE_RACE']
        first, later = [c['id'] for c in w.load()['comments']['9101']]
        self.assertTrue(outs[1].startswith('landed unknown: our duplicate %d ' % later), outs)
        self.assertEqual(w.bodies(9101), [LANDED, LANDED])
        settle = lambda: w.run('merge.py', 'settle', DEST, 9201, 9106, cwd=w.dir / 'project')
        w.update(faults={'delete': 'fail'})
        code, out = settle()
        self.assertEqual(code, 1, out)
        self.assertTrue(out.startswith('unknown: ') and '; landed unknown: ' in out, out)
        self.assertEqual(w.bodies(9101), [LANDED, LANDED])
        code, out = settle()
        self.assertEqual((code, out.split('; ')[-1]), (0, 'landed already posted %d' % first), out)
        self.assertEqual([c['id'] for c in w.load()['comments']['9101']], [first])
        self.assertEqual(settle()[1].split('; ')[-1], 'landed already posted %d' % first)
        self.assertEqual([x['delete'] for x in w.writes() if 'delete' in x], [later])
        self.assertEqual(len([x for x in w.writes() if x.get('post') == 9101]), 2)

    def test_a_duplicate_left_by_a_refused_delete_is_deleted_after_the_milestone_moves(self):
        receipt = comment(4000, 'launch-fleet: merge queued %s: APPROVE 1 and plan approval 2' % HEAD)
        w = self.world(self.issues, comments={'9201': [receipt]}, faults={'delete': 'fail'})
        project(w, None)
        w.env['FAKE_RACE'] = '9101'
        runs = [subprocess.Popen([sys.executable, '-I', str(HERE / 'merge.py'), 'cost', DEST, '9201', HEAD, '9106'],
                                 stdout=subprocess.PIPE, text=True, env=w.env, cwd=w.dir / 'project')
                for _ in range(2)]
        outs = sorted(r.communicate(timeout=60)[0].strip().split('; ')[-1] for r in runs)
        del w.env['FAKE_RACE']
        first, later = [c['id'] for c in w.load()['comments']['9101']]
        self.assertTrue(outs[1].startswith('landed unknown: our duplicate %d ' % later), outs)
        value = w.load()
        value['issues']['9101']['milestone'] = {'title': '9.5.0'}
        w.save(value)
        code, out = w.run('merge.py', 'settle', DEST, 9201, 9106, cwd=w.dir / 'project')
        self.assertEqual((code, out.split('; ')[-1]), (0, 'landed already posted %d' % first), out)
        self.assertEqual([c['id'] for c in w.load()['comments']['9101']], [first])
        self.assertEqual([x['delete'] for x in w.writes() if 'delete' in x], [later])

    def test_a_later_landed_comment_for_another_fix_is_left_alone(self):
        other = LANDED.replace('OpenWiz#9201', 'WizSite#9200')
        w = self.world(self.issues, comments={'9101': [comment(4000, LANDED), comment(4001, other)]})
        project(w, None)
        code, out = self.merge(w)
        self.assertEqual((code, out.split('; ')[-1]), (0, 'landed already posted 4000'), out)
        self.assertEqual(w.bodies(9101), [LANDED, other])
        self.assertFalse(any('delete' in x for x in w.writes()))


class Help(unittest.TestCase):
    def test_the_merge_help_describes_the_current_merge_order(self):
        r = subprocess.run([sys.executable, '-I', str(HERE / 'merge.py'), '--help'], capture_output=True, text=True,
                           timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        text = ' '.join(r.stdout.split())
        self.assertIn('merge.py merge OWNER/NAME PR HEAD CHECKS BODY --ticket TICKET', text)
        order = [text.find(x) for x in ('refused: its required checks are running', 'expectedHeadOid',
                                        'queued; recorded <id>')]
        self.assertTrue(-1 not in order and order == sorted(order), order)
        self.assertIn('only after it reads the queue entry back', text)
        self.assertNotIn('recorded before the enqueue', text)
        self.assertNotIn('recorded before the enqueue', M.__doc__)


class WizSkillsRoute(unittest.TestCase):
    def route(self):
        text = (HERE.parents[2] / 'docs/agents/fleet.md').read_text()
        section = lambda name: text.split('\n## %s\n' % name, 1)[1].split('\n## ', 1)[0]
        checks = re.findall(r'^\| `([^`]+)` \|', section('CI checks'), re.M)
        found = re.findall(r'`(python3 -I [^`]*merge\.py"? merge [^`]*)`', section('Standing merge rules'))
        self.assertEqual(len(found), 1, "WizSkills' merge rule names no merge.py merge command: %r" % found)
        values = {"<launch-fleet's folder>": str(HERE.parent), '<P>': '7', '<commit>': HEAD,
                  '<checks>': ','.join(checks), '<the APPROVE and the plan approval it relies on>':
                  'APPROVE 1 and plan approval 2', '<N>': '12'}
        command = found[0]
        for name, value in values.items():
            command = command.replace(name, value)
        argv = shlex.split(command)
        self.assertNotRegex(' '.join(argv), r'<[^>]+>', 'a placeholder left unfilled')
        self.assertEqual(argv[3:6], ['merge', SKILLS, '7'])
        return [sys.executable] + argv[1:], text

    def test_an_approved_head_is_enqueued_pinned_and_recorded_only_after_the_read_back(self):
        argv, text = self.route()
        w = World(self, repo=SKILLS, fleet_md=text, comments={'7': []},
                  pr=pr(isMergeQueueEnabled=True, closes=closes((DEST, 12))), others={DEST: {'comments': {'12': []}}})
        root = project(w, PRINTS)
        r = subprocess.run(argv, capture_output=True, text=True, env=w.env, cwd=root, timeout=60)
        receipt = 'launch-fleet: merge queued %s: APPROVE 1 and plan approval 2' % HEAD
        self.assertEqual((r.returncode, r.stdout.strip()), (0, 'queued; recorded 5001'), r.stderr)
        self.assertEqual(w.writes(), [{'enqueue': 'PR_synthetic7', 'head': HEAD}, {'post': 7, 'body': receipt}])
        self.assertEqual((w.bodies(7), w.others[DEST].writes()), ([receipt], []))

    def test_before_the_queue_is_on_it_prints_the_fallback_line_and_writes_nothing(self):
        argv, text = self.route()
        fallback = re.search(r'While `merge\.py` prints `([^`]+)`', text)
        self.assertIsNotNone(fallback, "WizSkills' merge rule names no fallback for a repository without the queue")
        w = World(self, repo=SKILLS, fleet_md=text, comments={'7': []},
                  pr=pr(closes=closes((DEST, 12))), others={DEST: {'comments': {'12': []}}})
        root = project(w, PRINTS)
        r = subprocess.run(argv, capture_output=True, text=True, env=w.env, cwd=root, timeout=60)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertTrue(r.stdout.startswith(fallback.group(1) + ';'), r.stdout)
        self.assertEqual((w.writes(), w.others[DEST].writes()), ([], []))


if __name__ == '__main__':
    unittest.main()
