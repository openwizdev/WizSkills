#!/usr/bin/env python3
import copy
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
QUEUE = HERE / 'queue.py'
git_origin = runpy.run_path(str(HERE / 'fixtures/git_origin.py'))['env']
FIXTURES = HERE / 'fixtures/queue'
REPO, NUMBER, CHECKS = 'openwizdev/OpenWiz', '2253', 'ci,privacy,web-test'
HEAD = '0c54d3bb82cb197314d6d028ae78c4fdb5ad66c4'
MERGE = '7892eaf91f54b1cac9278ee794a21cbba0b5bc60'
FLEET = ('# Fleet settings\n\n## GitHub identity\n\n| Setting | Value |\n| --- | --- |\n'
         '| Record authors | `openwiz[bot]`, `jparker2006` |\n')

FAKE = r'''import json, os, re, sys
args = sys.argv[1:]
fixture = json.load(open(os.environ['FAKE_QUEUE']))
def note(kind):
    with open(os.environ['FAKE_LOG'], 'a') as f:
        f.write(json.dumps([kind, args]) + '\n')
def write():
    note('write')
    sys.exit('fake gh: refused a write')
if not args or args[0] != 'api' or any(a in ('--input', '--raw-field') or a.startswith('--input=') for a in args):
    write()
rest, method = args[1:], None
for i, a in enumerate(rest):
    if a in ('--method', '-X') and i + 1 < len(rest):
        method = rest[i + 1].upper()
    elif a.startswith(('--method=', '-X')) and a not in ('-X',):
        method = a.split('=', 1)[-1].removeprefix('-X').upper()
if rest[:1] == ['graphql']:
    query = [a.split('=', 1)[1] for a in rest if a.startswith('query=')]
    if method not in (None, 'POST') or len(query) != 1 or re.search(r'\bmutation\b', query[0]) \
            or not query[0].lstrip().startswith('query'):
        write()
    note('read')
    if query[0].count('{') != query[0].count('}'):
        sys.exit('GraphQL: Expected NAME, actual: (none)')
    with open(os.environ['FAKE_LOG']) as f:
        served = sum(1 for line in f if json.loads(line)[1][:2] == ['api', 'graphql']) - 1
    pages = fixture['graphql']
    if served >= len(pages):
        sys.exit('HTTP 502: no such page')
    page = pages[served]
    sys.stdout.write(page if isinstance(page, str) else json.dumps(page))
    sys.exit(0)
if method not in (None, 'GET') or any(a in ('-f', '-F', '--field') for a in rest):
    write()
paths = [a for a in rest if a.startswith('repos/')]
if len(paths) == 1 and paths[0] == 'repos/openwizdev/OpenWiz/contents/docs/agents/fleet.md':
    note('read')
    if fixture.get('fleet', 'default') is None:
        sys.exit('HTTP 404')
    sys.stdout.write(fixture.get('fleet') if fixture.get('fleet', 'default') != 'default' else os.environ['FAKE_FLEET'])
    sys.exit(0)
if len(paths) == 1 and paths[0].split('?')[0] == 'repos/openwizdev/OpenWiz/issues/2253/comments':
    note('read')
    if fixture['comments'] == 'fail':
        sys.exit('HTTP 502')
    sys.stdout.write(json.dumps([fixture['comments']] if '--slurp' in rest else fixture['comments']))
    sys.exit(0)
note('unexpected')
sys.exit('fake gh: no such fixture read')
'''


def fixture(name):
    return json.loads((FIXTURES / f'{name}.json').read_text())


def node(value, page=0):
    return value['graphql'][page]['data']['repository']['pullRequest']


def contexts(value, page=0):
    return node(value, page)['commits']['nodes'][0]['commit']['statusCheckRollup']['contexts']


class Queue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / 'bin').mkdir()
        gh = root / 'bin/gh'
        gh.write_text(f'#!{sys.executable} -I\n' + FAKE)
        gh.chmod(0o755)
        self.log = root / 'gh.log'
        self.log.write_text('')
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ('OPENWIZ_GITHUB_APP_KEY', 'GH_TOKEN', 'GITHUB_TOKEN')}
        self.env.update(PATH=f"{root / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
                        FAKE_LOG=str(self.log), FAKE_FLEET=FLEET)
        self.root = root

    def calls(self, kind=None):
        found = [json.loads(line) for line in self.log.read_text().splitlines()]
        return [args for k, args in found if kind is None or k == kind]

    def run_queue(self, value, *argv):
        path = self.root / 'fixture.json'
        path.write_text(json.dumps(value) if not isinstance(value, str) else (FIXTURES / f'{value}.json').read_text())
        fleet = json.loads(path.read_text()).get('fleet', 'default')
        origin = git_origin(self.root, {REPO: FLEET if fleet == 'default' else fleet})
        r = subprocess.run([sys.executable, '-I', str(QUEUE), *(argv or ('read', REPO, NUMBER, HEAD, CHECKS))],
                           capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
                           env=dict(self.env, FAKE_QUEUE=str(path), **origin))
        self.assertEqual(self.calls('write'), [], 'queue.py tried to write')
        self.assertEqual(self.calls('unexpected'), [], 'queue.py made a read no fixture serves')
        return r.returncode, r.stdout, r.stderr

    def verdict(self, value, line, code):
        got = self.run_queue(value)
        self.assertEqual(got[:2], (code, line + '\n'), got)

    def unknown(self, value, why):
        code, out, err = self.run_queue(value)
        self.assertEqual((code, out.count('\n')), (2, 1), (out, err))
        self.assertTrue(out.startswith('unknown: ') and why in out, (out, why))

    def test_2253_drop_is_told_with_githubs_reason_and_time(self):
        self.verdict('2253-dropped', f'dropped {HEAD}: branch_protection_failure at 2026-11-22T10:00:03Z', 0)

    def test_2253_recorded_drop_waits_while_its_cancelled_runs_predate_the_enqueue(self):
        self.verdict('2253-recorded', f'wait {HEAD}: branch_protection_failure at 2026-11-22T10:00:03Z may still stand: '
                     'ci, privacy, web-test last ran before it', 0)

    def test_2253_goes_back_in_once_its_checks_are_green_again(self):
        self.verdict('2253-green-again', f'requeue {HEAD}: every required check ran again after the removal '
                     'and is green', 0)

    def test_old_cancelled_duplicates_never_excuse_a_new_failure(self):
        self.verdict('old-duplicates', f'wait {HEAD}: failed_checks at 2026-11-22T10:00:03Z may still stand: '
                     'ci, privacy, web-test last ran before it', 0)

    def test_duplicates_cancelled_in_the_merge_group_go_back_in(self):
        self.verdict('group-duplicates', f'requeue {HEAD}: every required check is green on it, '
                     'and its failed runs in the merge group were cancelled duplicates', 0)

    def test_a_real_failure_in_the_merge_group_beside_a_duplicate_waits(self):
        value = fixture('group-duplicates')
        contexts(value)['nodes'] += [
            {'__typename': 'CheckRun', 'name': 'lint', 'status': 'COMPLETED', 'conclusion': 'FAILURE',
             'startedAt': '2026-11-22T09:55:00Z'},
            {'__typename': 'CheckRun', 'name': 'lint', 'status': 'COMPLETED', 'conclusion': 'SUCCESS',
             'startedAt': '2026-11-22T09:56:00Z'}]
        self.verdict(value, f'wait {HEAD}: branch_protection_failure at 2026-11-22T10:00:03Z may still stand: '
                     'ci, privacy, web-test last ran before it', 0)

    def test_a_failure_after_the_removal_is_not_the_merge_groups(self):
        value = fixture('group-duplicates')
        contexts(value)['nodes'] += [
            {'__typename': 'CheckRun', 'name': 'lint', 'status': 'COMPLETED', 'conclusion': 'FAILURE',
             'startedAt': '2026-11-22T10:30:00Z'},
            {'__typename': 'CheckRun', 'name': 'lint', 'status': 'COMPLETED', 'conclusion': 'SUCCESS',
             'startedAt': '2026-11-22T10:31:00Z'}]
        self.verdict(value, f'requeue {HEAD}: every required check is green on it, '
                     'and its failed runs in the merge group were cancelled duplicates', 0)

    def test_duplicates_with_no_enqueue_read_never_go_back_in(self):
        value = fixture('group-duplicates')
        node(value)['added']['nodes'] = []
        self.verdict(value, f'wait {HEAD}: branch_protection_failure at 2026-11-22T10:00:03Z may still stand: '
                     'ci, privacy, web-test last ran before it', 0)

    def test_2253_re_queued_reads_queued(self):
        self.verdict('2253-requeued', 'queued', 0)

    def test_2253_merged_reads_its_merge_commit(self):
        self.verdict('2253-merged', f'merged {MERGE}', 0)

    def test_2253_second_removal_is_told_as_a_new_drop(self):
        self.verdict('2253-second-drop', f'dropped {HEAD}: branch_protection_failure at 2026-11-22T12:02:25Z', 0)

    def test_2253_dropped_twice_at_one_head_is_blocked(self):
        self.verdict('2253-dropped-twice', f'blocked {HEAD}: dropped twice at this head', 1)

    def test_checks_still_red_wait(self):
        self.verdict('checks-red', f'wait {HEAD}: not green on it: ci (FAILURE)', 0)

    def test_checks_running_wait(self):
        self.verdict('checks-running', f'wait {HEAD}: still running: ci', 0)

    def test_checks_green_again_after_the_removal_go_back_in(self):
        self.verdict('checks-green-again', f'requeue {HEAD}: every required check ran again after the removal '
                     'and is green', 0)

    def test_checks_green_only_before_the_removal_wait(self):
        self.verdict('checks-stale', f'wait {HEAD}: failed_checks at 2026-11-22T10:00:03Z may still stand: '
                     'ci, privacy, web-test last ran before it', 0)

    def test_a_cancelled_run_with_no_green_run_after_it_is_no_duplicate(self):
        value = fixture('group-duplicates')
        runs = contexts(value)['nodes']
        runs[:] = [r for r in runs if not (r['name'] == 'changelog' and r['conclusion'] == 'SUCCESS')]
        self.verdict(value, f'wait {HEAD}: branch_protection_failure at 2026-11-22T10:00:03Z may still stand: '
                     'ci, privacy, web-test last ran before it', 0)

    def test_a_cancelled_run_after_the_last_green_one_is_no_duplicate(self):
        value = fixture('group-duplicates')
        contexts(value)['nodes'].append({'__typename': 'CheckRun', 'name': 'changelog', 'status': 'COMPLETED',
                                         'conclusion': 'CANCELLED', 'startedAt': '2026-11-22T09:58:00Z'})
        self.verdict(value, f'wait {HEAD}: branch_protection_failure at 2026-11-22T10:00:03Z may still stand: '
                     'ci, privacy, web-test last ran before it', 0)

    def test_a_missing_required_check_waits(self):
        value = fixture('group-duplicates')
        contexts(value)['nodes'][:] = [r for r in contexts(value)['nodes'] if r['name'] != 'web-test']
        self.verdict(value, f'wait {HEAD}: not green on it: web-test (no run)', 0)

    def test_a_merge_conflict_is_blocked(self):
        self.verdict('conflict', f'blocked {HEAD}: merge_conflict needs its builder to merge main in', 1)

    def test_a_persons_removal_is_blocked(self):
        self.verdict('person', f'blocked {HEAD}: a person took it out of the queue (dequeued)', 1)

    def test_a_person_removing_it_for_any_reason_is_blocked(self):
        self.verdict('person-actor', f'blocked {HEAD}: a person took it out of the queue (branch_protection_failure)', 1)

    def test_any_other_reason_is_blocked(self):
        self.verdict('other-reason', f'blocked {HEAD}: invalid_merge_commit is never re-queued automatically', 1)

    def test_no_receipt_at_head_is_not_queued(self):
        self.verdict('not-queued', 'not queued', 0)

    def test_every_page_of_checks_is_read(self):
        self.verdict('paged', f'wait {HEAD}: not green on it: ci (FAILURE)', 0)
        reads = [a for a in self.calls('read') if a[:2] == ['api', 'graphql']]
        self.assertEqual(len(reads), 2)
        self.assertIn('checks=c3ludGhldGljLXBhZ2UtMQ', reads[1])

    def test_an_outsiders_drop_record_counts_for_nothing(self):
        value = fixture('2253-recorded')
        value['comments'][-1]['user']['login'] = 'synthetic-outsider'
        self.verdict(value, f'dropped {HEAD}: branch_protection_failure at 2026-11-22T10:00:03Z', 0)

    def test_two_records_of_one_removal_are_one_drop(self):
        value = fixture('2253-green-again')
        value['comments'].append(dict(value['comments'][-1], id=7000000009, created_at='2026-11-22T10:06:00Z'))
        self.verdict(value, f'requeue {HEAD}: every required check ran again after the removal and is green', 0)

    def test_a_record_at_another_head_counts_for_nothing(self):
        value = fixture('2253-recorded')
        value['comments'][-1]['body'] = value['comments'][-1]['body'].replace(HEAD, 'a' * 40)
        self.verdict(value, f'dropped {HEAD}: branch_protection_failure at 2026-11-22T10:00:03Z', 0)

    def broken(self, change, why):
        value = fixture('2253-green-again')
        change(value)
        self.unknown(value, why)

    def test_unreadable_answers_are_unknown(self):
        cases = {
            'not json': (lambda v: v.update(graphql=['{"data": ']), 'could not be read'),
            'errors': (lambda v: v.update(graphql=[{'errors': [{'message': 'synthetic'}], 'data': None}]),
                       'could not be read'),
            'gh fails': (lambda v: v.update(graphql=[]), 'could not be read'),
            'repeated key': (lambda v: v.update(graphql=[json.dumps(v['graphql'][0]).replace(
                '"state": "OPEN"', '"state": "OPEN", "state": "OPEN"')]), 'could not be read'),
            'extra key': (lambda v: node(v).update(isDraft=False), 'pull request'),
            'missing key': (lambda v: node(v).pop('isInMergeQueue'), 'pull request'),
            'string bool': (lambda v: node(v).update(isInMergeQueue='false'), 'pull request'),
            'no such pull request': (lambda v: v['graphql'][0]['data']['repository'].update(pullRequest=None),
                                     'pull request'),
            'run lacks a start': (lambda v: contexts(v)['nodes'][0].pop('startedAt'), 'check'),
            'completed run never started': (lambda v: contexts(v)['nodes'][0].update(startedAt=None), 'check'),
            'odd conclusion': (lambda v: contexts(v)['nodes'][0].update(conclusion='WEIRD'), 'check'),
            'odd context': (lambda v: contexts(v)['nodes'].append({'__typename': 'Other'}), 'check'),
            'checks pages run out': (lambda v: contexts(v)['pageInfo'].update(hasNextPage=True, endCursor='MTY'),
                                     'could not be read'),
            'cursor missing': (lambda v: node(v)['removed']['pageInfo'].update(hasNextPage=True, endCursor=None),
                               'removal'),
            'odd removal time': (lambda v: node(v)['removed']['nodes'][0].update(createdAt='2026-11-22 10:00:03'),
                                 'removal'),
            'odd reason': (lambda v: node(v)['removed']['nodes'][0].update(reason='Branch protection'), 'removal'),
            'tied runs': (lambda v: contexts(v)['nodes'].append({'__typename': 'CheckRun', 'name': 'ci',
                          'status': 'COMPLETED', 'conclusion': 'FAILURE', 'startedAt': '2026-11-22T11:40:00Z'}),
                          'ci'),
            'comments unread': (lambda v: v.update(comments='fail'), 'comments'),
            'no record authors': (lambda v: v.update(fleet=None), 'record authors'),
            'author not an object': (lambda v: v['comments'][0].update(user='synthetic-person'), 'comment'),
            'comment not an object': (lambda v: v['comments'].append('synthetic'), 'comment'),
            'record names no removal': (lambda v: v['comments'][-1].update(
                body=v['comments'][-1]['body'].replace('10:00:03Z', '10:00:04Z')), 'names no removal'),
            'malformed record': (lambda v: v['comments'][-1].update(
                body=f'launch-fleet: merge dropped {HEAD}: soon'), 'record'),
            'odd record time': (lambda v: v['comments'][1].update(created_at='yesterday'), 'record'),
            'queued at another head': (lambda v: node(v).update(
                isInMergeQueue=True, mergeQueueEntry={'headCommit': {'oid': 'b' * 40}}), 'queue'),
            'out of the queue with an entry': (lambda v: node(v).update(
                mergeQueueEntry={'headCommit': {'oid': HEAD}}), 'queue'),
            'head moved': (lambda v: node(v).update(headRefOid='b' * 40), 'head'),
            'closed': (lambda v: node(v).update(state='CLOSED'), 'CLOSED'),
            'merged without a commit': (lambda v: node(v).update(state='MERGED'), 'merge commit'),
            'requeued but out with no removal after': (lambda v: node(v)['added']['nodes'][0].update(
                createdAt='2026-11-22T11:52:39Z'), 're-queued'),
            'receipt but no removal': (lambda v: node(v)['removed'].update(
                nodes=[], pageInfo={'hasNextPage': False, 'endCursor': None}), 'no removal'),
        }
        for name, (change, why) in cases.items():
            with self.subTest(name):
                self.log.write_text('')
                self.broken(change, why)

    def test_a_later_page_may_not_change_the_pull_request(self):
        value = fixture('paged')
        node(value, 1)['headRefOid'] = 'b' * 40
        node(value, 1)['commits']['nodes'][0]['commit']['oid'] = 'b' * 40
        self.unknown(value, 'changed')

    def test_bad_arguments_exit_2_and_read_nothing(self):
        for argv in (('read', 'openwizdev', NUMBER, HEAD, CHECKS), ('read', REPO, '0', HEAD, CHECKS),
                     ('read', REPO, NUMBER, HEAD[:12], CHECKS), ('read', REPO, NUMBER, HEAD, 'ci,,privacy'),
                     ('read', REPO, NUMBER, HEAD, 'ci,ci'), ('merge', REPO, NUMBER, HEAD, CHECKS),
                     ('read', REPO, NUMBER, HEAD)):
            with self.subTest(argv):
                code, out, err = self.run_queue('2253-recorded', *argv)
                self.assertEqual((code, out), (2, ''))
                self.assertIn('queue.py read', err)
        self.assertEqual(self.calls(), [])

    def test_the_fake_gh_refuses_every_write(self):
        (self.root / 'fixture.json').write_text((FIXTURES / '2253-recorded.json').read_text())
        env = dict(self.env, FAKE_QUEUE=str(self.root / 'fixture.json'))
        writes = [
            ['api', '--method', 'POST', 'repos/openwizdev/OpenWiz/issues/2253/comments', '-f', 'body=x'],
            ['api', 'repos/openwizdev/OpenWiz/issues/2253/comments', '-f', 'body=x'],
            ['api', '-X', 'PATCH', 'repos/openwizdev/OpenWiz/issues/comments/1', '-f', 'body=x'],
            ['api', '--method=DELETE', 'repos/openwizdev/OpenWiz/issues/comments/1'],
            ['api', 'graphql', '-f', 'id=PR_x', '-f', 'query=mutation($id: ID!) { enqueuePullRequest('
             'input: {pullRequestId: $id}) { clientMutationId } }'],
            ['api', 'graphql', '-f', 'query=  mutation { x }'],
            ['api', '--input', 'body.json', 'repos/openwizdev/OpenWiz/issues/2253/comments'],
            ['pr', 'merge', '2253', '--repo', REPO, '--merge'],
            ['issue', 'comment', '2253', '--repo', REPO, '--body', 'x'],
        ]
        for argv in writes:
            with self.subTest(argv):
                r = subprocess.run([str(self.root / 'bin/gh'), *argv], capture_output=True, text=True, env=env)
                self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.calls('write'), writes)


if __name__ == '__main__':
    unittest.main()
