import fcntl
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
HELPER = HERE.parent / 'scripts' / 'feedback.py'
FAKE = HERE / 'fake_gh.py'
USER = {'login': 'synthetic-user', 'id': 9001}
OTHER = {'login': 'synthetic-other', 'id': 9002}
REPO = {'full_name': 'openwizdev/OpenWiz', 'private': False, 'visibility': 'public',
        'archived': False, 'has_issues': True}
TOKEN = 'synthetic-token-000000'
SECRET_PATH = '/home/synthetic-user/secret-project'
TITLE = 'Plan page hides the approve button on a narrow phone'
BODY = 'On a 360-pixel screen the approve button sits under the footer.'
SHORT_WRITE = '''
import errno, os, runpy, stat, sys
real, calls = os.write, []
def write(fd, data):
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        return real(fd, data)  # pipes (the create request's stdin) are untouched
    calls.append(len(data))
    if len(calls) == 1:
        return real(fd, bytes(data)[:len(data) // 2])
    raise OSError(errno.ENOSPC, 'No space left on device')
os.write = write
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
'''
DIR_SYNC_FAILS_AFTER_FIRST = '''
import errno, os, runpy, stat, sys
real, syncs = os.fsync, []
def fsync(fd):
    if stat.S_ISDIR(os.fstat(fd).st_mode):
        syncs.append(fd)
        if len(syncs) > 1:
            raise OSError(errno.EIO, 'Input/output error')
    return real(fd)
os.fsync = fsync
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
'''
FULL_DISK_AFTER_FIRST = '''
import errno, os, runpy, stat, sys
real, saves = os.write, []
def write(fd, data):
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        return real(fd, data)
    if saves and saves[-1] != fd:
        raise OSError(errno.ENOSPC, 'No space left on device')
    saves.append(fd)
    return real(fd, data)
os.write = write
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
'''


class Helper(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='feedback-proof-'))
        self.addCleanup(shutil.rmtree, self.tmp)
        self.bin = self.tmp / 'bin'
        self.bin.mkdir()
        gh = self.bin / 'gh'
        gh.write_text(f'#!/bin/sh\nexec {sys.executable} -I {FAKE} "$@"\n')
        gh.chmod(0o755)
        self.state = self.tmp / 'state'
        self.log = self.tmp / 'gh.log'
        self.log.write_text('')
        self.work = self.tmp / SECRET_PATH.lstrip('/')
        self.work.mkdir(parents=True)
        (self.work / 'notes.txt').write_text(f'private notes {TOKEN}\n')
        self.scenario = self.tmp / 'world.json'
        self.world(user=USER, repo=dict(REPO), create={'status': 201}, readback='ok', list='ok',
                   issues=[], next_number=41)

    def world(self, **change):
        world = json.loads(self.scenario.read_text()) if self.scenario.exists() else {}
        world.update(change)
        self.scenario.write_text(json.dumps(world))

    def run_helper(self, *args, expect=None, env_change=None, short_write=False, full_disk_after_first=False,
                   dir_sync_fails_after_first=False):
        env = {'PATH': str(self.bin), 'OPENWIZ_STATE_DIR': str(self.state), 'HOME': str(self.work),
               'FAKE_GH_SCENARIO': str(self.scenario), 'FAKE_GH_LOG': str(self.log), 'LC_ALL': 'C',
               'SYNTHETIC_PRIVATE_TOKEN': TOKEN, 'SYNTHETIC_PRIVATE_PATH': SECRET_PATH}
        for k, v in (env_change or {}).items():
            if v is None:
                env.pop(k, None)
            else:
                env[k] = v
        program = (['-c', SHORT_WRITE, str(HELPER)] if short_write
                   else ['-c', FULL_DISK_AFTER_FIRST, str(HELPER)] if full_disk_after_first
                   else ['-c', DIR_SYNC_FAILS_AFTER_FIRST, str(HELPER)] if dir_sync_fails_after_first else [str(HELPER)])
        run = subprocess.run([sys.executable, '-I', *program, *args], capture_output=True,
                             text=True, env=env, cwd=self.work, timeout=60)
        try:
            answer = json.loads(run.stdout) if run.stdout else {}
        except ValueError:
            self.fail(f'not one JSON answer: {run.stdout!r} {run.stderr!r}')
        if expect is not None:
            self.assertEqual(run.returncode, expect, (run.stdout, run.stderr))
        return run.returncode, answer

    def files(self, title=TITLE, body=BODY):
        t, b = self.tmp / 'title.txt', self.tmp / 'body.txt'
        t.write_text(title)
        b.write_text(body)
        return ['--title-file', str(t), '--body-file', str(b)]

    def draft(self, **kw):
        _, a = self.run_helper('draft', *self.files(**kw), expect=0)
        self.assertEqual(a['phase'], 'draft')
        return a['operation_id']

    def preview(self, op):
        _, a = self.run_helper('preview', op, expect=0)
        self.assertEqual(a['phase'], 'previewed')
        a['preview_id'] = a['preview'].rsplit('\n', 1)[1].removeprefix('To create it, reply: yes ')
        return a

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def creates(self):
        return [c for c in self.calls() if '--method' in c['argv'] and c['argv'][c['argv'].index('--method') + 1] != 'GET']

    def record(self, op):
        return json.loads((self.state / 'feedback' / f'{op}.json').read_text())

    def body_of(self, op, body=BODY):
        return f'{body}\n\nOpenWiz feedback operation {op}'

    def sent_issue(self, op, number=7, login='synthetic-user', uid=9001, body=None, title=TITLE, **extra):
        issue = {'number': number, 'title': title, 'body': self.body_of(op) if body is None else body,
                 'user': {'login': login, 'id': uid}}
        issue.update(extra)
        return issue


class Consent(Helper):
    def test_skill_invoked_with_no_yes_creates_nothing(self):
        op = self.draft()
        a = self.preview(op)
        self.assertEqual(a['preview'], '\n'.join([
            'Destination: openwizdev/OpenWiz (public: anyone can read it)',
            'Account: synthetic-user',
            'A yes creates one public issue on openwizdev/OpenWiz, once.',
            '', 'Title:', TITLE, '', 'Body:', self.body_of(op),
            '', f"To create it, reply: yes {a['preview_id']}"]))
        self.assertRegex(a['preview_id'], r'^[0-9]{6}$')
        self.run_helper('status', op, expect=0)
        self.assertEqual(self.creates(), [])
        self.assertEqual(len(op), 32)
        self.assertTrue(all(ch in '0123456789abcdef' for ch in op))

    def test_preview_and_status_hand_the_agent_no_send_key(self):
        op = self.draft()
        _, a = self.run_helper('preview', op, expect=0)
        _, status = self.run_helper('status', op, expect=0)
        for answer in (a, status):
            self.assertEqual(sorted(answer), ['operation_id', 'phase', 'preview', 'say'])
        self.assertEqual(status['preview'], a['preview'])

    def test_planted_private_context_reaches_no_request(self):
        op = self.draft()
        a = self.preview(op)
        self.run_helper('send', op, '--preview-id', a['preview_id'], expect=0)
        creates = self.creates()
        self.assertEqual(len(creates), 1)
        self.assertEqual(creates[0]['argv'], ['api', '--include', '--method', 'POST',
                                              'repos/openwizdev/OpenWiz/issues', '--input', '-'])
        self.assertEqual(json.loads(creates[0]['stdin']), {'title': TITLE, 'body': self.body_of(op)})
        for call in self.calls():
            text = json.dumps(call)
            self.assertNotIn(TOKEN, text)
            self.assertNotIn(SECRET_PATH, text)
            self.assertNotIn('private notes', text)

    def test_change_before_yes_refuses_and_needs_a_new_preview(self):
        changes = {
            'edit': lambda op: self.run_helper('edit', op, *self.files(body=BODY + ' Also on tablets.'), expect=0),
            'account': lambda op: self.world(user=OTHER),
            'same login, other id': lambda op: self.world(user={'login': 'synthetic-user', 'id': 9003}),
            'archived': lambda op: self.world(repo=dict(REPO, archived=True)),
            'private': lambda op: self.world(repo=dict(REPO, private=True, visibility='private')),
            'unreadable destination': lambda op: self.world(repo='fail'),
            'no login': lambda op: self.world(user=None),
        }
        for name, change in changes.items():
            with self.subTest(name):
                self.world(user=USER, repo=dict(REPO))
                op = self.draft(title=f'{TITLE} ({name})')
                a = self.preview(op)
                change(op)
                _, sent = self.run_helper('send', op, '--preview-id', a['preview_id'], expect=1)
                self.assertEqual(sent['phase'], 'refused')
                self.assertEqual(self.creates(), [])
                rec = self.record(op)
                self.assertEqual((rec['phase'], rec['preview'], rec['attempts']), ('refused', None, 0))
        self.world(user=USER, repo=dict(REPO))
        a = self.preview(op)
        self.run_helper('send', op, '--preview-id', a['preview_id'], expect=0)
        self.assertEqual(len(self.creates()), 1)

    def test_no_ambiguous_or_stale_answer_creates_nothing(self):
        op = self.draft()
        self.preview(op)
        _, a = self.run_helper('refuse', op, '--reason', 'the user said no', expect=0)
        self.assertEqual((a['phase'], a['reason']), ('refused', 'the user said no'))
        first = self.preview(op)['preview_id']
        self.preview(op)
        _, a = self.run_helper('send', op, '--preview-id', first, expect=1)
        self.assertEqual(a['phase'], 'refused')
        _, a = self.run_helper('send', op, '--preview-id', 'not-a-preview', expect=1)
        self.assertEqual(a['phase'], 'refused')
        self.assertEqual(self.creates(), [])
        self.assertEqual(self.record(op)['operation_id'], op)

    def test_repeated_yes_and_restart_in_sent_make_one_create(self):
        op = self.draft()
        a = self.preview(op)
        self.run_helper('send', op, '--preview-id', a['preview_id'], expect=0)
        _, again = self.run_helper('send', op, '--preview-id', a['preview_id'], expect=1)
        self.assertEqual(again['phase'], 'sent')
        _, status = self.run_helper('status', op, expect=0)
        self.assertEqual(status['phase'], 'sent')
        _, re_preview = self.run_helper('preview', op, expect=1)
        self.assertEqual(re_preview['phase'], 'sent')
        self.assertEqual(len(self.creates()), 1)


CONTRACT = HERE.parents[2] / 'contracts' / 'feedback-loop.v1.md'


def loop_contract():
    text = CONTRACT.read_text()
    start = text.index('```feedback-loop-v1\n') + len('```feedback-loop-v1\n')
    return json.loads(text[start:text.index('```', start)])


class Report(Helper):
    def test_filed_issue_is_a_report_by_marker_and_names_the_triage_label(self):
        loop = loop_contract()
        op = self.draft()
        a = self.preview(op)
        _, sent = self.run_helper('send', op, '--preview-id', a['preview_id'], expect=0)
        [create] = self.creates()
        self.assertIn(loop['destination'], create['argv'][4])
        filed = json.loads(create['stdin'])
        self.assertEqual(sorted(filed), ['body', 'title'])
        before, blank, marker = filed['body'].rsplit('\n', 2)
        self.assertEqual((before, blank), (BODY, ''))
        self.assertRegex(marker, loop['marker'])
        self.assertIn(f"`{loop['label']}` label", sent['say'])
        self.assertIn('only if triage sends it to a fleet and that fix merges', sent['say'])
        self.assertIn('pull request and the release', sent['say'])
        self.assertIn('a report held for the OpenWiz maintainers can close without that comment', sent['say'])
        self.assertNotIn('if a fix for it merges', sent['say'])


class Outcomes(Helper):
    def send(self, expect):
        op = self.draft()
        a = self.preview(op)
        _, sent = self.run_helper('send', op, '--preview-id', a['preview_id'], expect=expect)
        return op, sent

    def test_201_with_matching_read_back_is_sent(self):
        op, a = self.send(0)
        self.assertEqual(a['phase'], 'sent')
        self.assertEqual(a['issue'], {'number': 41, 'url': 'https://github.com/openwizdev/OpenWiz/issues/41'})
        self.assertIn('not yet read by the OpenWiz maintainers', a['say'])
        reads = [c['argv'] for c in self.calls()]
        self.assertEqual(reads[-1], ['api', '--include', '--method', 'GET', 'repos/openwizdev/OpenWiz/issues/41'])

    def test_422_is_failed_and_can_be_previewed_again(self):
        self.world(create={'status': 422})
        op, a = self.send(1)
        self.assertEqual((a['phase'], a['reason']), ('failed', 'GitHub answered HTTP 422'))
        _, again = self.run_helper('send', op, '--preview-id', 'ffffffffffffffff', expect=1)
        self.assertEqual(again['phase'], 'failed')
        self.assertEqual(len(self.creates()), 1)
        self.world(create={'status': 201})
        b = self.preview(op)
        _, sent = self.run_helper('send', op, '--preview-id', b['preview_id'], expect=0)
        self.assertEqual(sent['phase'], 'sent')
        self.assertEqual(len(self.creates()), 2)
        self.assertEqual(self.record(op)['attempts'], 2)

    def test_every_failed_status_needs_a_complete_response(self):
        for status in (401, 403, 404, 410, 429):
            with self.subTest(status):
                self.world(create={'status': status})
                _, a = self.send(1)
                self.assertEqual(a['phase'], 'failed')

    def test_lost_or_unconfirmed_results_are_uncertain_and_never_resent(self):
        cases = {
            'dropped connection': {'create': {'drop': True}},
            '502': {'create': {'status': 502}},
            '500': {'create': {'status': 500}},
            'read-back fails': {'readback': 'fail'},
            'read-back differs': {'readback': 'differs'},
        }
        for name, change in cases.items():
            with self.subTest(name):
                self.world(**{'create': {'status': 201}, 'readback': 'ok', **change})
                before = len(self.creates())
                op = self.draft(title=f'{TITLE} ({name})')
                a = self.preview(op)
                _, sent = self.run_helper('send', op, '--preview-id', a['preview_id'], expect=1)
                self.assertEqual(sent['phase'], 'uncertain')
                self.assertEqual(len(self.creates()), before + 1)
                self.world(create={'status': 201}, readback='ok')
                _, again = self.run_helper('send', op, '--preview-id', a['preview_id'], expect=1)
                self.assertEqual(again['phase'], 'uncertain')
                _, re_preview = self.run_helper('preview', op, expect=1)
                self.assertEqual(re_preview['phase'], 'uncertain')
                _, same = self.run_helper('draft', *self.files(title=f'{TITLE} ({name})'), expect=1)
                self.assertIn('Reconcile it first', same['refused'])
                self.assertEqual(len(self.creates()), before + 1)

    def test_restart_in_sending_is_uncertain(self):
        self.world(create={'kill_parent': True})
        op = self.draft()
        a = self.preview(op)
        code, _ = self.run_helper('send', op, '--preview-id', a['preview_id'])
        self.assertEqual(code, -9)
        self.assertEqual(self.record(op)['phase'], 'sending')
        _, status = self.run_helper('status', op, expect=0)
        self.assertEqual(status['phase'], 'uncertain')
        self.assertEqual(self.record(op)['phase'], 'sending', 'status only reads')
        self.world(create={'status': 201})
        _, again = self.run_helper('send', op, '--preview-id', a['preview_id'], expect=1)
        self.assertEqual(again['phase'], 'uncertain')
        self.assertEqual(self.record(op)['phase'], 'uncertain')
        self.assertEqual(len(self.creates()), 1)


class Accounts(Helper):

    def test_an_environment_token_is_refused_before_any_call(self):
        for name in ('GH_TOKEN', 'GITHUB_TOKEN'):
            with self.subTest(name):
                self.world(accounts=[], token_user=OTHER)
                op = self.draft(title=f'{TITLE} ({name})')
                before = len(self.calls())
                _, a = self.run_helper('preview', op, expect=1, env_change={name: TOKEN})
                self.assertIn(name, a['refused'])
                self.assertEqual(self.record(op)['phase'], 'draft')
                self.assertEqual(len(self.calls()), before, 'gh is never run with the token')
                self.world(accounts=['synthetic-user'])
                b = self.preview(op)
                before = len(self.calls())
                _, sent = self.run_helper('send', op, '--preview-id', b['preview_id'], expect=1,
                                          env_change={name: TOKEN})
                self.assertEqual(sent['phase'], 'refused')
                self.assertIn(name, sent['reason'])
                self.assertEqual(len(self.calls()), before, 'gh is never run with the token')
        self.assertEqual(self.creates(), [])

    def test_more_than_one_candidate_account_is_refused(self):
        self.world(accounts=['synthetic-user', 'synthetic-other'])
        op = self.draft()
        _, a = self.run_helper('preview', op, expect=1)
        self.assertIn('more than one GitHub account', a['refused'])
        self.assertEqual(self.record(op)['phase'], 'draft')
        self.world(accounts=['synthetic-user'])
        b = self.preview(op)
        self.world(accounts=['synthetic-user', 'synthetic-other'])
        _, sent = self.run_helper('send', op, '--preview-id', b['preview_id'], expect=1)
        self.assertEqual(sent['phase'], 'refused')
        self.assertIn('more than one GitHub account', sent['reason'])
        self.assertEqual(self.creates(), [])

    def test_a_login_other_than_the_one_stored_account_is_refused(self):
        self.world(accounts=['synthetic-other'])
        op = self.draft()
        _, a = self.run_helper('preview', op, expect=1)
        self.assertIn('could not be read', a['refused'])
        self.assertEqual(self.creates(), [])


class Reconcile(Helper):
    def uncertain(self, title=TITLE):
        self.world(create={'status': 502})
        op = self.draft(title=title)
        a = self.preview(op)
        self.run_helper('send', op, '--preview-id', a['preview_id'], expect=1)
        self.world(create={'status': 201})
        return op

    def test_one_matching_issue_is_sent_with_no_create(self):
        op = self.uncertain()
        self.world(issues=[self.sent_issue(op, 7), self.sent_issue(op, 8, body='Unrelated feedback.')])
        _, a = self.run_helper('reconcile', op, expect=0)
        self.assertEqual((a['phase'], a['issue']['number']), ('sent', 7))
        self.assertEqual(len(self.creates()), 1)
        lists = [c['argv'] for c in self.calls() if '--paginate' in c['argv']]
        self.assertEqual(len(lists), 1)
        self.assertTrue(lists[0][-1].startswith('repos/openwizdev/OpenWiz/issues?creator=synthetic-user&state=all&since='))

    def test_none_two_differing_or_unreadable_stay_uncertain(self):
        cases = {
            'none': lambda op, t: [],
            'two': lambda op, t: [self.sent_issue(op, 7, title=t), self.sent_issue(op, 8, title=t)],
            'content differs': lambda op, t: [self.sent_issue(op, 7, title=t, body=f'Changed.\n\nOpenWiz feedback operation {op}')],
            'another author': lambda op, t: [self.sent_issue(op, 7, title=t, uid=9004)],
            'a pull request': lambda op, t: [self.sent_issue(op, 7, title=t, pull_request={})],
            'list fails': lambda op, t: [self.sent_issue(op, 7, title=t)],
            'account changed': lambda op, t: [self.sent_issue(op, 7, title=t)],
            'no login': lambda op, t: [self.sent_issue(op, 7, title=t)],
        }
        worlds = {'list fails': {'list': 'fail'}, 'account changed': {'user': OTHER}, 'no login': {'user': None}}
        for name, issues in cases.items():
            with self.subTest(name):
                self.world(user=USER, list='ok', issues=[])
                title = f'{TITLE} ({name})'
                op = self.uncertain(title)
                before = len(self.creates())
                self.world(issues=issues(op, title), **worlds.get(name, {}))
                _, a = self.run_helper('reconcile', op, expect=1)
                self.assertEqual(a['phase'], 'uncertain')
                self.assertIn('check', a)
                self.assertEqual(len(self.creates()), before)
                self.assertEqual(self.record(op)['phase'], 'uncertain')

    def test_an_issue_number_from_the_user_follows_the_same_rules(self):
        op = self.uncertain()
        self.world(issues=[self.sent_issue(op, 7, login='synthetic-user')])
        _, a = self.run_helper('reconcile', op, '--issue', '7', expect=0)
        self.assertEqual(a['phase'], 'sent')
        op = self.uncertain()
        self.world(issues=[self.sent_issue(op, 9), self.sent_issue(op, 10, login='renamed')])
        _, a = self.run_helper('reconcile', op, '--issue', '10', expect=1)
        self.assertEqual(a['phase'], 'uncertain')

    def test_only_an_uncertain_operation_is_reconciled(self):
        op = self.draft()
        _, a = self.run_helper('reconcile', op, expect=1)
        self.assertEqual(a['phase'], 'draft')
        self.assertEqual([c for c in self.calls()], [])


class Record(Helper):
    def test_record_is_owner_only_and_keeps_the_binding(self):
        op = self.draft()
        self.preview(op)
        place = self.state / 'feedback'
        self.assertEqual(stat.S_IMODE(os.stat(place).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(place / f'{op}.json').st_mode), 0o600)
        rec = self.record(op)
        self.assertEqual((rec['destination'], rec['account'], rec['title'], rec['body']),
                         ('openwizdev/OpenWiz', USER, TITLE, self.body_of(op)))
        self.assertRegex(rec['preview']['at'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$')

    def test_missing_or_unreadable_record_never_makes_an_attempt_safe(self):
        op = self.draft()
        a = self.preview(op)
        path = self.state / 'feedback' / f'{op}.json'
        good = path.read_text()
        for name, text in {'truncated': good[:40], 'extra key': good.replace('"schema"', '"extra": 1, "schema"'),
                           'unknown phase': good.replace('"previewed"', '"queued"')}.items():
            with self.subTest(name):
                path.write_text(text)
                _, b = self.run_helper('send', op, '--preview-id', a['preview_id'], expect=1)
                self.assertIn('cannot tell whether earlier feedback was created', b['refused'])
                _, c = self.run_helper('draft', *self.files(title='Something else'), expect=1)
                self.assertIn('cannot tell', c['refused'])
        path.unlink()
        _, b = self.run_helper('send', op, '--preview-id', a['preview_id'], expect=1)
        self.assertIn('cannot tell whether earlier feedback was created', b['refused'])
        self.assertEqual(self.creates(), [])

    def test_state_inside_a_repository_or_open_to_others_is_refused(self):
        (self.state / '.git').mkdir(parents=True)
        _, a = self.run_helper('draft', *self.files(), expect=1)
        self.assertIn('outside every repository', a['refused'])
        shutil.rmtree(self.state / '.git')
        self.state.chmod(0o755)
        _, a = self.run_helper('draft', *self.files(), expect=1)
        self.assertIn('mode 700', a['refused'])

    def test_content_outside_the_contract_is_refused_before_preview(self):
        cases = {'empty title': (' ', BODY), 'two-line title': ('a\nb', BODY), 'long title': ('t' * 257, BODY),
                 'empty body': (TITLE, '\n'), 'own marker': (TITLE, 'x\nOpenWiz feedback operation ' + 'a' * 32),
                 'long body': (TITLE, 'b' * 65536),
                 'bidi override in title': ('fix \u202edrawkcab', BODY), 'bidi isolate in body': (TITLE, 'a \u2067b\u2069'),
                 'zero-width space in title': ('ap\u200bprove', BODY), 'zero-width joiner in body': (TITLE, 'x\u200dy'),
                 'byte order mark in body': (TITLE, '\ufeffbody'), 'tag character in body': (TITLE, 'x\U000e0041')}
        for name, (title, body) in cases.items():
            with self.subTest(name):
                self.run_helper('draft', *self.files(title=title, body=body), expect=1)
        op = self.draft()
        _, edited = self.run_helper('edit', op, *self.files(title=TITLE, body='a\u202eb'), expect=1)
        self.assertIn('U+202E', edited['refused'])
        self.assertEqual(self.record(op)['chosen_body'], BODY)
        self.assertEqual(self.calls(), [])
        self.run_helper('draft', *self.files(title='t' * 256, body='b' * (65536 - 2 - 59)), expect=0)


    def test_a_saved_draft_from_before_the_format_check_is_refused_at_preview(self):
        for field in ('title', 'body'):
            with self.subTest(field):
                op = self.draft(title=f'{TITLE} {field}')
                path = self.state / 'feedback' / f'{op}.json'
                rec = self.record(op)
                if field == 'title':
                    rec['title'] = 'fix \u202edrawkcab'
                else:
                    rec['chosen_body'] = 'a \u202eb'
                    rec['body'] = self.body_of(op, rec['chosen_body'])
                path.write_text(json.dumps(rec, ensure_ascii=False))
                _, a = self.run_helper('preview', op, expect=1)
                self.assertIn(f'The {field} holds an invisible character, U+202E', a['refused'])
                self.assertNotIn('preview', a)
                self.assertEqual((self.record(op)['phase'], self.record(op)['preview']), ('draft', None))
                self.run_helper('edit', op, *self.files(title=f'{TITLE} {field}'), expect=0)
        self.assertEqual(self.calls(), [])


    def test_a_saved_preview_from_before_the_format_check_is_refused_at_send(self):
        for field in ('title', 'body'):
            with self.subTest(field):
                op = self.draft(title=f'{TITLE} {field}')
                code = self.preview(op)['preview_id']
                path = self.state / 'feedback' / f'{op}.json'
                rec = self.record(op)
                if field == 'title':
                    rec['title'] = 'fix \u202edrawkcab'
                else:
                    rec['chosen_body'] = 'a \u202eb'
                    rec['body'] = self.body_of(op, rec['chosen_body'])
                path.write_text(json.dumps(rec, ensure_ascii=False))
                before = len(self.calls())
                _, a = self.run_helper('send', op, '--preview-id', code, expect=1)
                self.assertEqual(a['phase'], 'refused')
                self.assertIn(f'The {field} holds an invisible character, U+202E', a['reason'])
                self.assertEqual(len(self.calls()), before)
                self.assertEqual((self.record(op)['phase'], self.record(op)['preview']), ('refused', None))
                self.run_helper('edit', op, *self.files(title=f'{TITLE} {field}'), expect=0)
        self.assertEqual(self.creates(), [])


class Duplicates(Helper):

    def make_uncertain(self, title=TITLE):
        op = self.draft(title=title)
        a = self.preview(op)
        self.world(readback='fail')
        self.run_helper('send', op, '--preview-id', a['preview_id'], expect=1)
        self.world(readback='ok')
        self.assertEqual(self.record(op)['phase'], 'uncertain')
        return op

    def test_a_matching_draft_made_earlier_is_not_sent(self):
        twin = self.draft()
        self.make_uncertain()
        b = self.preview(twin)
        _, sent = self.run_helper('send', twin, '--preview-id', b['preview_id'], expect=1)
        self.assertEqual(sent['phase'], 'refused')
        self.assertIn('Reconcile it first', sent['reason'])
        self.assertEqual(len(self.creates()), 1)

    def test_an_edit_to_the_uncertain_text_is_refused(self):
        other = self.draft(title='Something unrelated')
        self.make_uncertain()
        _, edited = self.run_helper('edit', other, *self.files(), expect=1)
        self.assertIn('Reconcile it first', edited['refused'])
        self.assertEqual(self.record(other)['title'], 'Something unrelated')
        self.assertEqual(len(self.creates()), 1)

    def test_a_failed_operation_is_not_retried_while_a_twin_is_uncertain(self):
        twin = self.draft()
        b = self.preview(twin)
        self.world(create={'status': 422})
        self.run_helper('send', twin, '--preview-id', b['preview_id'], expect=1)
        self.world(create={'status': 201})
        self.make_uncertain()
        b = self.preview(twin)
        _, sent = self.run_helper('send', twin, '--preview-id', b['preview_id'], expect=1)
        self.assertEqual(sent['phase'], 'refused')
        self.assertEqual(len(self.creates()), 2, 'the 422 and the uncertain one; no third')

    def test_sends_of_twins_are_serialized_by_the_store_lock(self):
        twin = self.draft()
        op = self.draft()
        a, b = self.preview(op), self.preview(twin)
        self.world(create={'kill_parent': True})
        self.run_helper('send', op, '--preview-id', a['preview_id'])
        self.assertEqual(self.record(op)['phase'], 'sending')
        fd = os.open(self.state / 'feedback' / f'{op}.lock', os.O_RDWR)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        self.world(create={'status': 201})
        _, sent = self.run_helper('send', twin, '--preview-id', b['preview_id'], expect=1)
        self.assertEqual(sent['phase'], 'refused')
        self.assertEqual(len(self.creates()), 1)


class Placement(Helper):

    def test_a_symlinked_ancestor_into_a_repository_is_refused(self):
        repo = self.tmp / 'synthetic-repo'
        (repo / '.git').mkdir(parents=True)
        (repo / 'subdir').mkdir()
        alias = self.tmp / 'alias'
        alias.symlink_to(repo / 'subdir')
        for name, change in {'OPENWIZ_STATE_DIR': {'OPENWIZ_STATE_DIR': str(alias / 'state')},
                             'XDG_STATE_HOME': {'OPENWIZ_STATE_DIR': None, 'XDG_STATE_HOME': str(alias)}}.items():
            with self.subTest(name):
                _, a = self.run_helper('draft', *self.files(), expect=1, env_change=change)
                self.assertIn('outside every repository', a['refused'])
                self.assertEqual(sorted(p.name for p in (repo / 'subdir').iterdir()), [], 'nothing created inside the repository')
        self.assertEqual(self.calls(), [])


class Durability(Helper):

    def test_a_short_write_then_a_full_disk_sends_nothing_and_keeps_the_record(self):
        op = self.draft()
        a = self.preview(op)
        place = self.state / 'feedback'
        before = (place / f'{op}.json').read_bytes()
        _, sent = self.run_helper('send', op, '--preview-id', a['preview_id'], expect=1, short_write=True)
        self.assertEqual(self.creates(), [], 'no create after a failed save')
        self.assertIn('nothing was sent', sent.get('refused', ''))
        self.assertEqual((place / f'{op}.json').read_bytes(), before, 'the previewed record is unchanged')
        self.assertEqual([p.name for p in place.iterdir() if p.name.endswith('.tmp')], [])
        _, again = self.run_helper('send', op, '--preview-id', a['preview_id'], expect=0)
        self.assertEqual(again['phase'], 'sent')
        self.assertEqual(len(self.creates()), 1)

    def test_an_outcome_that_cannot_be_saved_is_still_told_and_never_resent(self):
        op = self.draft()
        a = self.preview(op)
        code, sent = self.run_helper('send', op, '--preview-id', a['preview_id'], full_disk_after_first=True)
        self.assertEqual(len(self.creates()), 1)
        self.assertEqual(code, 1, 'not a clean success: the outcome is not durable')
        self.assertEqual((sent['phase'], sent['issue']['number']), ('sent', 41), 'the known outcome is reported')
        self.assertNotIn('nothing was sent', json.dumps(sent).lower())
        self.assertIn('Do not send again', sent['record_not_saved'])
        self.assertEqual(self.record(op)['phase'], 'sending', 'the durable record from before the request is kept')
        _, status = self.run_helper('status', op, expect=0)
        self.assertEqual(status['phase'], 'uncertain')
        self.run_helper('send', op, '--preview-id', a['preview_id'], expect=1)
        self.assertEqual(len(self.creates()), 1, 'never sent again')
        _, rec = self.run_helper('reconcile', op, expect=0)
        self.assertEqual((rec['phase'], rec['issue']['number']), ('sent', 41))
        self.assertEqual(len(self.creates()), 1)

    def test_an_outcome_whose_folder_sync_fails_is_still_told_and_never_resent(self):
        op = self.draft()
        a = self.preview(op)
        code, sent = self.run_helper('send', op, '--preview-id', a['preview_id'], dir_sync_fails_after_first=True)
        self.assertEqual(len(self.creates()), 1)
        self.assertEqual(code, 1, 'not a clean success: durability is unconfirmed')
        self.assertEqual((sent.get('operation_id'), sent.get('phase')), (op, 'sent'), 'the known outcome is reported')
        self.assertEqual(sent['issue']['number'], 41)
        warning = sent['record_not_saved']
        self.assertIn('Do not send again', warning)
        self.assertIn('run status', warning)
        self.assertNotIn('still says sending', warning, 'the record was replaced: no claim it still says sending')
        self.assertNotIn('nothing was sent', json.dumps(sent).lower())
        self.assertEqual(self.record(op)['phase'], 'sent', 'the outcome was renamed into place')
        _, status = self.run_helper('status', op, expect=0)
        self.assertEqual((status['phase'], status['issue']['number']), ('sent', 41))
        self.run_helper('send', op, '--preview-id', a['preview_id'], expect=1)
        self.assertEqual(len(self.creates()), 1, 'never sent again')


class Share(Helper):
    def share(self, text, url, expect):
        f = self.tmp / 'share.txt'
        f.write_text(text)
        return self.run_helper('share', '--text-file', str(f), '--url', url, expect=expect)[1]

    def test_share_shows_exactly_the_text_and_the_repository_url(self):
        a = self.share('Try OpenWiz with me.\n', 'https://github.com/openwizdev/OpenWiz', 0)
        self.assertEqual(a['share'], 'Try OpenWiz with me.\n\nhttps://github.com/openwizdev/OpenWiz')
        self.assertEqual(self.calls(), [])

    def test_share_of_a_destination_issue_reads_it_back(self):
        self.world(issues=[{'number': 5, 'title': 't', 'body': 'b', 'user': USER},
                           {'number': 6, 'title': 't', 'body': 'b', 'user': USER, 'pull_request': {}}])
        a = self.share('See this.', 'https://github.com/openwizdev/OpenWiz/issues/5', 0)
        self.assertEqual(a['share'], 'See this.\n\nhttps://github.com/openwizdev/OpenWiz/issues/5')
        for url in ('https://github.com/openwizdev/OpenWiz/issues/6', 'https://github.com/openwizdev/OpenWiz/issues/99'):
            self.share('See this.', url, 1)
        self.world(repo=dict(REPO, private=True, visibility='private'))
        self.share('See this.', 'https://github.com/openwizdev/OpenWiz/issues/5', 1)
        self.assertEqual(self.creates(), [])

    def test_share_refuses_private_looking_or_unlisted_targets(self):
        for url in ('https://github.com/openwizdev/OpenWiz?ref=x', 'https://github.com/openwizdev/OpenWiz#top',
                    'https://github.com/openwizdev/OpenWiz/', 'http://github.com/openwizdev/OpenWiz',
                    'https://github.com/jparker2006/ClosedWiz', 'http://127.0.0.1:7370/',
                    'https://github.com/openwizdev/OpenWiz/issues/05', 'https://github.com/openwizdev/OpenWiz/pull/5'):
            with self.subTest(url):
                self.share('Try it.', url, 1)
        for text in (f'my token {TOKEN} https://example.com', 'open http://localhost:7370', 'see www.example.com',
                     'at 192.168.1.10', '', 'see github.com/synthetic-owner/synthetic-repo',
                     'at Code.Example.ORG:8443/team/project', 'clone git@github.com:synthetic-owner/synthetic-repo',
                     'at synthetic-git:8443/owner/repo', 'clone git@synthetic-git:owner/repo',
                     'see code.example.org./team/project', 'clone git@code.example:~synthetic-owner/repo'):
            with self.subTest(text):
                self.share(text, 'https://github.com/openwizdev/OpenWiz', 1)
        self.assertEqual(self.share('Try OpenWiz 0.0.5/today, e.g. at work/home.', 'https://github.com/openwizdev/OpenWiz', 0)['share'],
                         'Try OpenWiz 0.0.5/today, e.g. at work/home.\n\nhttps://github.com/openwizdev/OpenWiz')
        self.assertEqual(self.calls(), [])



class Capitals(Helper):
    SAME = ('openwizdev/openwiz', 'openwizdev/OpenWiz', 'OpenWizDev/OPENWIZ')
    FOREIGN = ('openwizdev/openwiz2', 'someone/openwiz', 'openwizdev/WizPlugins')

    def test_send_accepts_either_capitals_in_github_replies(self):
        for name in self.SAME:
            with self.subTest(name):
                self.world(name=name, repo=dict(REPO, full_name=name))
                op = self.draft(title=f'{TITLE} ({name})')
                a = self.preview(op)
                _, sent = self.run_helper('send', op, '--preview-id', a['preview_id'], expect=0)
                self.assertEqual(sent['phase'], 'sent')
        self.assertEqual(len(self.creates()), len(self.SAME))

    def test_send_refuses_another_repository_in_github_replies(self):
        for name in self.FOREIGN:
            with self.subTest(name):
                self.world(name=REPO['full_name'], repo=dict(REPO))
                op = self.draft(title=f'{TITLE} ({name})')
                a = self.preview(op)
                self.world(name=name, repo=dict(REPO, full_name=name))
                _, sent = self.run_helper('send', op, '--preview-id', a['preview_id'], expect=1)
                self.assertEqual(sent['phase'], 'refused')
        self.assertEqual(self.creates(), [])

    def test_created_issue_in_another_repository_is_not_sent(self):
        self.world(name='openwizdev/openwiz2')
        op = self.draft()
        a = self.preview(op)
        _, sent = self.run_helper('send', op, '--preview-id', a['preview_id'], expect=1)
        self.assertNotEqual(sent['phase'], 'sent')
        self.assertEqual(len(self.creates()), 1)

    def test_share_of_an_issue_accepts_either_capitals_only(self):
        self.world(issues=[{'number': 5, 'title': 't', 'body': 'b', 'user': USER}])
        url = 'https://github.com/' + REPO['full_name'] + '/issues/5'
        for name in self.SAME:
            with self.subTest(name):
                self.world(name=name, repo=dict(REPO, full_name=name))
                self.assertEqual(self.share('See this.', url, 0)['share'], 'See this.\n\n' + url)
        for name in self.FOREIGN:
            with self.subTest(name):
                self.world(name=name, repo=dict(REPO))
                self.share('See this.', url, 1)
        self.assertEqual(self.creates(), [])

    def test_a_record_with_either_capitals_still_reads(self):
        op = self.draft()
        path = self.state / 'feedback' / f'{op}.json'
        for name, expect in (('OpenWizDev/OpenWiz', 0), ('openwizdev/openwiz2', 1)):
            with self.subTest(name):
                rec = json.loads(path.read_text())
                rec['destination'] = name
                path.write_text(json.dumps(rec))
                self.run_helper('status', op, expect=expect)

    def share(self, text, url, expect):
        f = self.tmp / 'share.txt'
        f.write_text(text)
        return self.run_helper('share', '--text-file', str(f), '--url', url, expect=expect)[1]


FACTS_PREFIX = 'OpenWiz feedback facts '
FACTS_ORDER = [
    'v', 'kind', 'area', 'openwiz', 'wizskills', 'skill', 'os', 'arch',
    'host', 'driver', 'harness', 'model', 'log_lines', 'redactions',
]
SLUG_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,31}$')
VER_RE = re.compile(r'^[0-9]+\.[0-9]+\.[0-9]+$')
SKILL_VER_RE = re.compile(r'^feedback@[0-9]+\.[0-9]+\.[0-9]+$')
MODEL_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{0,63}$')
MARKER_RE = re.compile(r'^OpenWiz feedback operation [0-9a-f]{32}$')


def parse_contract_facts(body):
    lines = body.split('\n')
    if len(lines) < 5:
        return None
    if not MARKER_RE.fullmatch(lines[-1]) or lines[-2] != '' or lines[-4] != '':
        return None
    facts_line = lines[-3]
    if not facts_line.startswith(FACTS_PREFIX) or len(facts_line) > 1024 or not facts_line.isascii():
        return None
    raw = facts_line[len(FACTS_PREFIX):]
    seen = []

    def pairs(items):
        keys = [k for k, _ in items]
        if len(keys) != len(set(keys)):
            raise ValueError('repeated key')
        seen.extend(keys)
        return dict(items)

    try:
        obj = json.loads(raw, object_pairs_hook=pairs)
    except ValueError:
        return None
    if not isinstance(obj, dict) or json.dumps(obj, separators=(',', ':'), ensure_ascii=True) != raw:
        return None
    if 'v' not in obj or obj['v'] != 1 or type(obj['v']) is not int:
        return None
    if any(k not in FACTS_ORDER for k in seen):
        return None
    if seen != [k for k in FACTS_ORDER if k in obj]:
        return None
    checks = {
        'v': lambda v: type(v) is int and v == 1,
        'kind': lambda v: v in ('bug', 'idea', 'question'),
        'area': lambda v: isinstance(v, str) and bool(SLUG_RE.fullmatch(v)),
        'openwiz': lambda v: isinstance(v, str) and bool(VER_RE.fullmatch(v)),
        'wizskills': lambda v: isinstance(v, str) and bool(VER_RE.fullmatch(v)),
        'skill': lambda v: isinstance(v, str) and bool(SKILL_VER_RE.fullmatch(v)),
        'os': lambda v: v in ('linux', 'macos', 'windows', 'other'),
        'arch': lambda v: v in ('x86_64', 'arm64', 'other'),
        'host': lambda v: isinstance(v, str) and bool(SLUG_RE.fullmatch(v)),
        'driver': lambda v: isinstance(v, str) and bool(SLUG_RE.fullmatch(v)),
        'harness': lambda v: isinstance(v, str) and bool(SLUG_RE.fullmatch(v)),
        'model': lambda v: isinstance(v, str) and bool(MODEL_RE.fullmatch(v)),
        'log_lines': lambda v: type(v) is int and 0 <= v <= 40,
        'redactions': lambda v: type(v) is int and 0 <= v <= 9999,
    }
    if not all(checks[k](v) for k, v in obj.items()):
        return None
    if sum(1 for line in lines if line.startswith(FACTS_PREFIX)) != 1:
        return None
    return obj


class ReportInputAndFacts(Helper):
    def write_openwiz_stub(self, script):
        ow = self.bin / 'openwiz'
        ow.write_text('#!/bin/sh\n' + script + '\n')
        ow.chmod(0o755)

    def report_file(self, data, name='report.json'):
        p = self.tmp / name
        p.write_text(json.dumps(data))
        return str(p)

    def full_report(self, **overrides):
        data = {
            'title': 'launch-fleet stops before starting a builder',
            'kind': 'bug',
            'area': 'launch-fleet',
            'ran': 'openwiz launch-fleet',
            'happened': 'It exited without starting a builder.',
            'expected': 'It starts a builder for the ready ticket.',
            'host': 'cloudroom',
            'driver': 'cloudroom',
            'harness': 'claude-code',
            'model': 'claude-opus-5-5',
        }
        data.update(overrides)
        return data

    def test_report_with_all_fields_previews_and_sends_exact_body(self):
        self.write_openwiz_stub('echo "openwiz 0.1.1"')
        log_path = self.tmp / 'run.log'
        log_path.write_text('user@box:~/work$ openwiz launch-fleet\nerror: failed with synthetic-token-000000\n')
        _, d = self.run_helper('draft', '--report-file', self.report_file(self.full_report()),
                               '--log-file', str(log_path), expect=0)
        op = d['operation_id']
        a = self.preview(op)
        _, sent = self.run_helper('send', op, '--preview-id', a['preview_id'], expect=0)
        self.assertEqual(sent['phase'], 'sent')
        [create] = self.creates()
        filed = json.loads(create['stdin'])
        self.assertEqual(sorted(filed), ['body', 'title'])
        body = filed['body']
        self.assertIn(f'Body:\n{body}\n', a['preview'])
        for label in ('What I ran:', 'What happened:', 'What I expected:', 'Log (secrets removed):'):
            self.assertIn(label + '\n', body)
        self.assertLess(body.index('What I ran:'), body.index('What happened:'))
        self.assertLess(body.index('What happened:'), body.index('What I expected:'))
        self.assertLess(body.index('What I expected:'), body.index('Log (secrets removed):'))
        facts = parse_contract_facts(body)
        self.assertIsNotNone(facts, body)
        self.assertEqual(facts['kind'], 'bug')
        self.assertEqual(facts['area'], 'launch-fleet')
        self.assertEqual(facts['openwiz'], '0.1.1')
        self.assertEqual(facts['host'], 'cloudroom')
        self.assertEqual(facts['driver'], 'cloudroom')
        self.assertEqual(facts['harness'], 'claude-code')
        self.assertEqual(facts['model'], 'claude-opus-5-5')
        self.assertEqual(facts['log_lines'], 2)
        self.assertEqual(facts['redactions'], 1)
        self.assertIn('OpenWiz 0.1.1', a['preview'])
        self.assertIn('Agent: claude-code, model claude-opus-5-5', a['preview'])
        self.assertIn("for OpenWiz's agents", a['preview'])
        self.assertIn('--drop', a['preview'])
        self.assertNotIn('synthetic-token-000000', body)

    def test_dropping_every_fact_leaves_no_facts_line(self):
        self.write_openwiz_stub('echo "openwiz 0.1.1"')
        rf = self.report_file(self.full_report())
        _, d = self.run_helper('draft', '--report-file', rf, '--no-facts', expect=0)
        op = d['operation_id']
        a = self.preview(op)
        _, sent = self.run_helper('send', op, '--preview-id', a['preview_id'], expect=0)
        self.assertEqual(sent['phase'], 'sent')
        filed = json.loads(self.creates()[0]['stdin'])
        self.assertNotIn(FACTS_PREFIX, filed['body'])
        self.assertTrue(filed['body'].endswith(f'\n\nOpenWiz feedback operation {op}'))
        drop_args = []
        for k in ('kind', 'area', 'openwiz', 'wizskills', 'skill', 'os', 'arch',
                  'host', 'driver', 'harness', 'model'):
            drop_args.extend(['--drop', k])
        _, d2 = self.run_helper('draft', '--report-file', self.report_file(self.full_report(title='Drop all individually')),
                                *drop_args, expect=0)
        op2 = d2['operation_id']
        a2 = self.preview(op2)
        self.assertNotIn(FACTS_PREFIX, a2['preview'])

    def test_invalid_fact_values_are_refused_naming_the_key(self):
        bad_cases = [
            ('kind', 'feature'),
            ('area', 'Not_A_Slug'),
            ('host', 'my host'),
            ('driver', 'UPPER'),
            ('harness', 'bad/harness'),
            ('model', 'model with spaces'),
        ]
        for key, bad_val in bad_cases:
            with self.subTest(key=key):
                rf = self.report_file(self.full_report(**{key: bad_val}), name=f'bad-{key}.json')
                _, a = self.run_helper('draft', '--report-file', rf, expect=1)
                self.assertIn(key, a['refused'])

    def test_changed_fact_voids_preview(self):
        rf = self.report_file(self.full_report())
        _, d = self.run_helper('draft', '--report-file', rf, expect=0)
        op = d['operation_id']
        a = self.preview(op)
        self.run_helper('edit', op, '--report-file', rf, '--drop', 'model', expect=0)
        _, sent = self.run_helper('send', op, '--preview-id', a['preview_id'], expect=1)
        self.assertEqual(sent['phase'], 'refused')
        self.assertEqual(self.creates(), [])

    def test_no_private_env_or_hostname_reaches_preview_or_request(self):
        self.write_openwiz_stub('exit 1')
        planted_env = {
            'HOSTNAME': 'secret-laptop-999.internal',
            'HOST': 'secret-host-999',
            'USER': 'secret-person-999',
            'USERNAME': 'secret-person-999',
            'OPENWIZ_HOST': 'secret-openwiz-host',
            'OPENWIZ_DRIVER': 'secret-driver',
            'OPENWIZ_MODEL': 'secret-model',
            'ANTHROPIC_API_KEY': 'sk-ant-synthetic000000000000000000',
        }
        rf = self.report_file({'title': 'Minimal report', 'happened': 'Something broke.'})
        _, d = self.run_helper('draft', '--report-file', rf, expect=0, env_change=planted_env)
        op = d['operation_id']
        _, p = self.run_helper('preview', op, expect=0, env_change=planted_env)
        code = p['preview'].rsplit('\n', 1)[1].removeprefix('To create it, reply: yes ')
        self.run_helper('send', op, '--preview-id', code, expect=0, env_change=planted_env)
        combined = p['preview'] + json.dumps(self.calls())
        for needle in ('secret-laptop-999', 'secret-host-999', 'secret-person-999',
                       'secret-openwiz-host', 'secret-driver', 'secret-model',
                       'sk-ant-synthetic', TOKEN, SECRET_PATH):
            self.assertNotIn(needle, combined)
        facts = parse_contract_facts(json.loads(self.creates()[0]['stdin'])['body'])
        self.assertIsNotNone(facts)
        self.assertNotIn('openwiz', facts)


class SecretsAndWarnings(Helper):
    def report_file(self, data, name='report.json'):
        p = self.tmp / name
        p.write_text(json.dumps(data))
        return str(p)

    def test_token_in_happened_refused_and_in_log_scrubbed_and_counted(self):
        bad = {'title': 'Bug title', 'happened': 'line one\nleaked synthetic-token-000000 here'}
        _, a = self.run_helper('draft', '--report-file', self.report_file(bad, 'bad.json'), expect=1)
        self.assertIn('happened', a['refused'])
        self.assertIn('2', a['refused'])
        good = {'title': 'Bug title', 'happened': 'It crashed on startup.'}
        log_path = self.tmp / 'crash.log'
        log_path.write_text('token=synthetic-token-000000\n')
        _, d = self.run_helper('draft', '--report-file', self.report_file(good, 'good.json'),
                               '--log-file', str(log_path), expect=0)
        op = d['operation_id']
        p = self.preview(op)
        self.assertNotIn('synthetic-token-000000', p['preview'])
        self.assertIn('[secret removed]', p['preview'])
        _, sent = self.run_helper('send', op, '--preview-id', p['preview_id'], expect=0)
        self.assertEqual(sent['phase'], 'sent')
        facts = parse_contract_facts(json.loads(self.creates()[0]['stdin'])['body'])
        self.assertEqual(facts['redactions'], 1)
        self.assertEqual(facts['log_lines'], 1)

    def test_private_key_block_in_title_or_section_refused(self):
        key_text = '-----BEGIN OPENSSH PRIVATE KEY-----\nabcdef\n-----END OPENSSH PRIVATE KEY-----'
        bad = {'title': 'Key leak', 'happened': 'oops\n' + key_text}
        _, a = self.run_helper('draft', '--report-file', self.report_file(bad, 'key.json'), expect=1)
        self.assertIn('happened', a['refused'])
        self.assertIn('2', a['refused'])

    def test_home_path_and_email_in_happened_warn_without_altering_body(self):
        happened = f'Opened {SECRET_PATH}/app.py and mailed synthetic@example.com.'
        rf = self.report_file({'title': 'Path and email report', 'happened': happened})
        _, d = self.run_helper('draft', '--report-file', rf, expect=0)
        self.assertTrue(d.get('warnings'))
        joined = '\n'.join(d['warnings']).lower()
        self.assertIn('path', joined)
        self.assertIn('e-mail', joined)
        p = self.preview(d['operation_id'])
        self.assertTrue(p.get('warnings'))
        self.assertIn(happened, p['preview'])
        self.run_helper('send', d['operation_id'], '--preview-id', p['preview_id'], expect=0)
        filed = json.loads(self.creates()[0]['stdin'])
        self.assertIn(happened, filed['body'])

    def test_log_scrub_limits_40_lines_200_chars_indent_and_replacements(self):
        lines = [f'$ line {i} ' + ('x' * 220) for i in range(50)]
        lines[-1] = (
            'user@host:~/proj$ curl https://alice:pass@private.example.com/a '
            'https://example.org/doc synthetic@example.com 192.168.1.42 '
            '/home/synthetic-user/secret-project thr_abc12345'
        )
        log_path = self.tmp / 'big.log'
        log_path.write_text('\n'.join(lines) + '\n')
        rf = self.report_file({'title': 'Long log report', 'happened': 'See log.'})
        _, d = self.run_helper('draft', '--report-file', rf, '--log-file', str(log_path), expect=0)
        p = self.preview(d['operation_id'])
        self.run_helper('send', d['operation_id'], '--preview-id', p['preview_id'], expect=0)
        body = json.loads(self.creates()[0]['stdin'])['body']
        facts = parse_contract_facts(body)
        self.assertEqual(facts['log_lines'], 40)
        self.assertGreaterEqual(facts['redactions'], 6)
        log_section = body.split('Log (secrets removed):\n', 1)[1].split('\n\nOpenWiz feedback facts ', 1)[0]
        log_lines = log_section.split('\n')
        self.assertEqual(len(log_lines), 40)
        for line in log_lines:
            self.assertTrue(line.startswith('    '), repr(line))
            self.assertLessEqual(len(line) - 4, 200)
        for forbidden in ('alice:pass', 'private.example.com', 'example.org', 'synthetic@example.com',
                          '192.168.1.42', '/home/synthetic-user/secret-project', 'thr_abc12345', 'user@host:'):
            self.assertNotIn(forbidden, log_section)


class NoPersonName(Helper):
    def test_no_person_name_in_helper_say_refusals_or_skill_md(self):
        skill_text = (HERE.parent / 'SKILL.md').read_text()
        self.assertNotIn('Jake', skill_text)
        _, empty = self.run_helper('draft', *self.files(body='   '), expect=1)
        self.assertNotIn('Jake', empty['refused'])
        self.assertIn('the OpenWiz maintainers', empty['refused'])
        op = self.draft()
        a = self.preview(op)
        _, sent = self.run_helper('send', op, '--preview-id', a['preview_id'], expect=0)
        self.assertNotIn('Jake', sent['say'])
        self.assertIn('the OpenWiz maintainers', sent['say'])
        self.assertIn(sent['issue']['url'], sent['say'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
