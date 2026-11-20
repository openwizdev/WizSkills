#!/usr/bin/env python3
"""merge.py on a synthetic GitHub (WS8, #1181; WS26, #1670): exact-head merges and FM4's cost line.

python3 -I skills/launch-fleet/scripts/test-merge.py
"""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

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
ROUTER = r'''import json, os, subprocess, sys
args = sys.argv[1:]
named = dict(a.split('=', 1) for a in args if a.split('=', 1)[0] in ('owner', 'name'))
repo = named['owner'] + '/' + named['name'] if len(named) == 2 else None
for i, a in enumerate(args):
    if a == '--repo':
        repo = args[i + 1]
    elif a.startswith('repos/'):
        repo = '/'.join(a.split('/')[1:3])
path = json.loads(os.environ.get('FAKE_WORLDS') or '{}').get(repo, os.environ['FAKE_WORLD'])
r = subprocess.run([sys.executable, '-I', %r, *args], env=dict(os.environ, FAKE_WORLD=path),
                   capture_output=True, text=True)
out = r.stdout
if args[:2] == ['api', 'graphql'] and r.returncode == 0:
    value = json.loads(out)
    node = value['data']['repository']['pullRequest']
    if node is not None:
        with open(path) as f:
            closes = json.load(f)['pr'].get('closes', [])
        node['closingIssuesReferences'] = {'pageInfo': {'hasNextPage': False}, 'nodes': closes}
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
             'checks': [{'__typename': 'CheckRun', 'name': 'check', 'conclusion': 'SUCCESS'},
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
        w = World(self, pr=pr(isMergeQueueEnabled=True))
        project(w, PRINTS)
        # Admission reads HEAD; GitHub then sees another head at merge time.
        script = w.dir / 'bin/gh'
        script.write_text(script.read_text().replace(
            'exec ', 'case "$1 $2" in "pr merge") "%s" -I -c "import json,os;p=os.environ[\'FAKE_WORLD\'];'
            'w=json.load(open(p));w[\'pr\'][\'headRefOid\']=\'%s\';json.dump(w,open(p,\'w\'))";; esac\nexec '
            % (sys.executable, OTHER), 1))
        code, out = self.merge(w, '--ticket', 12)
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('blocked: '), out)
        self.assertEqual(w.load()['pr']['state'], 'OPEN')
        self.assertEqual(w.bodies(12), [])

    def test_the_queue_takes_it_and_its_record_says_what_allowed_it(self):
        w = World(self, pr=pr(isMergeQueueEnabled=True))
        project(w, PRINTS)
        code, out = self.merge(w, '--ticket', 12)
        self.assertEqual((code, out), (0, 'queued; recorded 5001'))
        self.assertEqual(w.bodies(7), ['launch-fleet: merge queued %s: APPROVE 1 and plan approval 2' % HEAD])
        self.assertEqual(w.bodies(12), [])

    def test_a_queue_that_let_it_go_blocks_it(self):
        left = {'createdAt': '2026-01-01T00:00:00Z', 'reason': 'failed checks'}
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
        for script, reason in ((REFUSES, 'PR #7 closes more than one ticket'), (None, 'no cost command'),
                               ('print("Ticket #13 cost (PR #7): builder 0 credits")\n', 'unexpected cost output'),
                               ('import sys\nprint("oops thr_x", file=sys.stderr)\nsys.exit(1)\n',
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

    def test_the_named_one_of_two_same_number_tickets_gets_it(self):
        # catches: a qualified ticket ignored in favour of the PR repository's same number.
        w = self.world([(TICKETS, 12), (REPO, 12)], state='MERGED', mergeCommit={'oid': 'c' * 40})
        project(w, PRINTS)
        self.assertEqual(w.run('merge.py', 'cost', REPO, 7, HEAD, '%s#12' % TICKETS, cwd=w.dir / 'project'),
                         (0, 'cost posted 5001'))
        self.assertEqual(len(w.others[TICKETS].bodies(12)), 1)
        self.assertEqual(w.bodies(12), [])


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

    def test_a_failed_queue_receipt_fails_and_a_later_read_repairs_it(self):
        # catches: a lost queue receipt reported as success and never restored, so a later removal
        # re-enqueues the same head (#1631).
        w = World(self, pr=pr(isMergeQueueEnabled=True), faults={'post': 'fail'})
        project(w, PRINTS)
        code, out = self.merge(w)
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('queued; receipt unconfirmed ('), out)
        self.assertEqual(w.bodies(7), [])
        self.assertEqual(self.merge(w), (0, 'queued; recorded 5001'))
        self.assertEqual(w.bodies(7), [self.receipt()])
        self.assertEqual(self.merge(w), (0, 'queued; the queue merges it or lets it go'))
        self.assertEqual(w.bodies(7), [self.receipt()])
        # The queue lets it go: the repaired receipt blocks a second enqueue at that head.
        value = w.load()
        value['pr'].update(isInMergeQueue=False, mergeQueueEntry=None,
                           left={'createdAt': '2026-01-01T00:00:00Z', 'reason': 'failed checks'})
        w.save(value)
        self.assertEqual(self.merge(w), (1, 'blocked: left the merge queue: failed checks; recorded 5002'))
        self.assertEqual(sum('merge' in x for x in w.writes()), 1)

    def test_a_lost_queue_receipt_response_is_not_posted_twice(self):
        # catches: the repair duplicating a receipt whose write happened but could not be read back.
        w = World(self, pr=pr(isMergeQueueEnabled=True), faults={'post': 'lost'}, me='someone-else')
        project(w, PRINTS)
        self.assertEqual(self.merge(w)[0], 1)
        w.update(me='openwiz[bot]')
        value = w.load()
        value['comments']['7'][0]['user']['login'] = 'openwiz[bot]'
        w.save(value)
        self.assertEqual(self.merge(w), (0, 'queued; the queue merges it or lets it go'))
        self.assertEqual(w.bodies(7), [self.receipt()])


if __name__ == '__main__':
    unittest.main()
