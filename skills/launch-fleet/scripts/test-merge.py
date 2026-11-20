#!/usr/bin/env python3
"""merge.py on a synthetic GitHub (WS8, #1181; WS26, #1670): exact-head merges and FM4's cost line.

python3 -I skills/launch-fleet/scripts/test-merge.py
"""
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
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
# A world's `faults: {"read": "fail"}` fails its next comment-list read, and its
# `issues` answers one issue's read (the landed comment's brief and report).
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
issue = [a.split('/') for a in args if a.startswith('repos/')]
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

    def test_an_unconfirmed_queue_receipt_enqueues_nothing(self):
        # catches: an enqueue whose receipt failed, so the queue can merge it (no cost to settle) or
        # let it go (re-enqueued at the same head) before any later wake repairs it (#1631, R1).
        w = World(self, pr=pr(isMergeQueueEnabled=True), faults={'post': 'fail'})
        project(w, PRINTS)
        code, out = self.merge(w)
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('not queued: '), out)
        self.assertEqual((w.bodies(7), w.writes(), w.load()['pr']['isInMergeQueue']), ([], [], False))
        self.assertEqual(self.merge(w), (0, 'queued; recorded 5001'))
        self.assertEqual(w.bodies(7), [self.receipt()])
        self.assertEqual(self.merge(w), (0, 'queued; the queue merges it or lets it go'))
        self.assertEqual(w.bodies(7), [self.receipt()])
        # The queue lets it go: the receipt blocks a second enqueue at that head.
        value = w.load()
        value['pr'].update(isInMergeQueue=False, mergeQueueEntry=None,
                           left={'createdAt': '2026-01-01T00:00:00Z', 'reason': 'failed checks'})
        w.save(value)
        self.assertEqual(self.merge(w), (1, 'blocked: left the merge queue: failed checks; recorded 5002'))
        self.assertEqual(sum('merge' in x for x in w.writes()), 1)

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
        # catches: a retry duplicating a receipt whose write happened but could not be confirmed,
        # or enqueueing before it is confirmed.
        w = World(self, pr=pr(isMergeQueueEnabled=True), faults={'post': 'lost'}, me='someone-else')
        project(w, PRINTS)
        code, out = self.merge(w)
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('not queued: '), out)
        self.assertFalse(any('merge' in x for x in w.writes()))
        # The read-back missed it; the next wake reads it as the record author's.
        value = w.load()
        value['me'] = value['comments']['7'][0]['user']['login'] = 'openwiz[bot]'
        w.save(value)
        self.assertEqual(self.merge(w), (0, 'queued; recorded 5001'))
        self.assertEqual(w.bodies(7), [self.receipt()])
        self.assertEqual(sum('merge' in x for x in w.writes()), 1)


# The feedback-loop contract (v1, contracts/feedback-loop.v1.md in OpenWiz, FL1 #1840): its
# landed fixtures, as GitHub answers them. Every account, number and text is synthetic.
DEST = 'openwizdev/OpenWiz'
MARK = 'OpenWiz feedback operation 3f2a9c4e1b7d40a6958e0c2d7b1a4f63'
LANDED = 'Landed: the fix for this report merged in #9201 and will ship in OpenWiz 9.4.2.'


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
        self.assertTrue(out.endswith('; landed posted 5002 on #9101'), out)
        self.assertEqual(self.merge(w), (0, 'merged %s; cost already posted 5001; landed already posted 5002'
                                         % ('c' * 40)))
        self.assertEqual(w.run('merge.py', 'settle', DEST, 9201, 9106, cwd=w.dir / 'project'), (0, 'no queued merge'))
        self.assertEqual(self.posts(w), [(9101, LANDED)])
        self.assertEqual(w.bodies(9106), ['launch-fleet: cost unknown (PR #9201): no cost command'])

    def test_a_report_landed_by_an_earlier_fix_gets_nothing(self):
        # catches: the once-per-report rule read per pull request, so a second fix posts again.
        earlier = comment(4000, 'Landed: the fix for this report merged in #9200 and will ship in OpenWiz 9.4.1.')
        w = self.world({'9108': brief(9108), '9101': REPORT}, close=(9108,), comments={'9101': [earlier]})
        project(w, None)
        self.assertEqual(self.merge(w, 9108)[1].split('; ')[-1], 'landed already posted 4000')
        self.assertEqual(self.posts(w), [])

    def test_only_a_record_authors_landed_comment_counts(self):
        # catches: anyone pasting the landed line on a report silencing the real one.
        forged = comment(4000, LANDED, login='synthetic-user')
        w = self.world(self.issues, comments={'9101': [forged]})
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

    def test_another_repositorys_merge_posts_nothing(self):
        # catches: `#<pull request>` naming another repository's number on the report.
        w = self.world(self.issues, repo=REPO)
        project(w, None)
        self.assertEqual(self.merge(w, repo=REPO)[0], 0)
        self.assertEqual(self.posts(w), [])

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
        self.assertEqual(self.merge(w)[1].split('; ')[-1], 'landed already posted 5002')
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


if __name__ == '__main__':
    unittest.main()
