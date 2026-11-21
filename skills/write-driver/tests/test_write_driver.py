"""write-driver's script tests: the contract's forms, the template copy, kit runs, the safety asks, the timer,
stop-everything and the share. Every value is synthetic; nothing reaches a real host or GitHub.

    python3 -I skills/write-driver/tests/test_write_driver.py

Linux: the stop and expired-login tests read /proc. The kit here is a synthetic stand-in
(fixtures/openwiz/kernel/driver-kit/kit.py); the real kit runs in write-driver's eval (WD3).
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / 'scripts' / 'write_driver.py'
FIXTURES = HERE / 'fixtures'
OPENWIZ = FIXTURES / 'openwiz'
CONTRACT = FIXTURES / 'contract'
sys.dont_write_bytecode = True
sys.path.insert(0, str(SCRIPT.parent))
import write_driver as wd  # noqa: E402

PASS5 = ''.join('pass %s: synthetic\n' % c for c in ('version', 'start', 'wake', 'stop', 'token'))
SECRET = 'synthetic-secret-value-0123456789'


def alive(pid):
    try:
        with open('/proc/%d/stat' % pid) as f:
            return f.read().rpartition(')')[2].split()[0] != 'Z'
    except OSError:
        return False


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='write-driver-test-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state = self.tmp / 'state'
        self.bin = self.tmp / 'bin'
        self.bin.mkdir()
        shutil.copy(FIXTURES / 'gh', self.bin / 'gh')
        self.gh_log = self.tmp / 'gh.log'
        self.world = self.tmp / 'world.json'
        self.set_world()
        self.env = {'PATH': '%s:%s' % (self.bin, os.environ.get('PATH', '/usr/bin:/bin')),
                    'HOME': str(self.tmp / 'home'), 'FAKE_GH_LOG': str(self.gh_log),
                    'FAKE_GH_WORLD': str(self.world), 'EXAMPLEHOST_API_TOKEN': SECRET,
                    'OPENWIZ_EXAMPLEHOST_STATE': str(self.tmp / 'driver-state')}

    def set_world(self, issues=None, comment_exit=0):
        if issues is None:
            issues = [{'number': 1966, 'title': 'Driver times', 'state': 'OPEN', 'pinned': True}]
        self.world.write_text(json.dumps({'login': 'example-user', 'issues': issues, 'comment_exit': comment_exit}))

    def wd(self, *args, stdin='', check=None):
        p = subprocess.run([sys.executable, '-I', str(SCRIPT), *map(str, args)], input=stdin, env=self.env,
                           capture_output=True, text=True, timeout=60, cwd=self.tmp)
        for text in (p.stdout, p.stderr):
            self.assertNotIn(SECRET, text)
        if check is not None:
            self.assertEqual(p.returncode, check, p.stdout + p.stderr)
        return p

    def gh_calls(self):
        if not self.gh_log.exists():
            return []
        return [json.loads(line) for line in self.gh_log.read_text().splitlines()]

    def saved(self):
        return json.loads((self.state / 'run.json').read_text())

    def shift_paste(self, seconds, passed_too=False):
        s = self.saved()
        s['paste'] -= seconds
        if passed_too and s.get('passed_at'):  # as if time went on after the driver passed
            s['passed_at'] -= seconds
        (self.state / 'run.json').write_text(json.dumps(s))

    def begin(self, costly=False):
        self.wd('begin', '--state', self.state, check=0)
        self.wd('host', '--state', self.state, '--host', 'examplehost', '--costly', 'yes' if costly else 'no',
                check=0)

    def reply(self, text, *extra, check=None):
        f = self.tmp / 'reply.txt'
        f.write_text(text)
        return self.wd(*extra, '--file', f, check=check)

    def kit(self, out=PASS5, code=0, *extra):
        (self.tmp / 'kit.out').write_text(out)
        self.env.update(FAKE_KIT_OUT=str(self.tmp / 'kit.out'), FAKE_KIT_ARGV=str(self.tmp / 'kit.argv'),
                        FAKE_KIT_EXIT=str(code))
        return self.wd('kit', '--state', self.state, '--openwiz', OPENWIZ, '--driver', self.tmp / 'driver',
                       '--repo', 'example-user/examplehost-driver-kit', '--ticket', 7, '--harness', 'exampleagent',
                       '--model', 'example-model', *extra)

    def lessons_pass(self):
        live = self.tmp / 'live.json'
        live.write_text('{"state": "running", "id": "synthetic-1"}')
        self.wd('lesson', 'live-shape', '--state', self.state, '--live', live, '--fixture', live, check=0)
        self.wd('lesson', 'wake-after-turn', '--state', self.state, '--turn-ended', 'yes', '--wake', 'answered',
                '--note-edited', 'yes', '--second-note', 'no', check=0)
        self.wd('lesson', 'expired-login', '--state', self.state, '--driver', self.fixed_driver(), '--harness',
                'exampleagent', check=0)

    def fixed_driver(self, name='fixed', host='examplehost', change=None):
        """A copy of the synthetic template that fails `start` on an expired sign-in, with its own fixtures."""
        folder = self.tmp / name
        if not folder.exists():
            shutil.copytree(OPENWIZ / 'adapters' / 'template', folder)
            text = (folder / 'driver').read_text()
            text = text.replace("HOST = 'template'", "HOST = %r" % host)
            text = text.replace('OPENWIZ_TEMPLATE_STATE', 'OPENWIZ_EXAMPLEHOST_STATE')
            text = text.replace('FIRST_TURN_CHECK = False', 'FIRST_TURN_CHECK = True')
            (folder / 'driver').write_text(change(text) if change else text)
        return folder / 'driver'

    def passing_report(self, minutes=23):
        self.begin()
        self.kit()
        self.lessons_pass()
        self.shift_paste(minutes * 60 - 30)
        self.wd('stop-all', '--state', self.state, check=0)
        return self.wd('report', '--state', self.state, '--pr', 'https://github.com/example-user/examplehost-driver/pull/1',
                       check=0)


class Forms(unittest.TestCase):
    """The skill reads and writes every form exactly as contracts/write-driver.v1.md says."""

    def test_contract_fixtures_read_as_expected(self):
        # catches: the skill's reader drifting from the contract's own fixtures (a report, ask, lesson or share
        # line the contract refuses read as valid, or the reverse)
        expected = json.loads((CONTRACT / 'expected.json').read_text())['fixtures']
        readers = {'copy-line': wd.read_copy, 'fleet': wd.read_fleet, 'ticket': wd.read_ticket,
                   'start': wd.read_start, 'lesson': wd.read_lesson, 'ask': wd.read_ask,
                   'report': wd.read_report, 'share': wd.read_share, 'preview': wd.read_preview}
        seen = 0
        for group, cases in expected.items():
            if group == 'admission':  # build-ticket's own admission: the contract's check runs it, not the skill
                continue
            for rel, want in cases.items():
                text = (CONTRACT / rel).read_text(encoding='utf-8')
                text = text[:-1] if text.endswith('\n') else text
                with self.subTest(rel):
                    self.assertEqual(readers[group](text), want)
                seen += 1
        self.assertEqual(seen, 68)

    def test_ticket_writes_the_exact_forms(self):
        # catches: a throwaway repository whose fleet.md, ticket or start record a builder or the kit can't read
        out = Path(tempfile.mkdtemp(prefix='write-driver-ticket-'))
        self.addCleanup(shutil.rmtree, out, True)
        p = subprocess.run([sys.executable, '-I', str(SCRIPT), 'ticket', '--host', 'key-host', '--account',
                            'example-user', '--out', str(out)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(wd.read_fleet((out / 'docs/agents/fleet.md').read_text()),
                         {'result': 'valid', 'account': 'example-user'})
        self.assertEqual(wd.read_ticket((out / 'ticket.json').read_text()), {'result': 'valid', 'host': 'key-host'})
        self.assertEqual(wd.read_start((out / 'start-record.md').read_text()), {'result': 'valid', 'host': 'key-host'})

    def test_copy_line_is_the_contracts(self):
        # catches: SKILL.md quoting a copy line that differs from the one the Drivers page copies
        skill = (SCRIPT.parents[1] / 'SKILL.md').read_text()
        self.assertIn('> ' + wd.forms()['copy_line'] + '\n', skill)


class Copy(Base):
    def test_copy_renames_the_template_for_the_host(self):
        # catches: a copied driver still calling itself `template` or sharing the template's state folder, so two
        # drivers' runs collide; a changed schema.json the kit then fails; the template's evidence shipped as the host's
        self.begin()
        repo = self.tmp / 'repo'
        self.wd('copy', '--state', self.state, '--openwiz', OPENWIZ, '--into', repo, '--login', 'machine', check=0)
        dest = repo / 'adapters' / 'examplehost'
        driver = (dest / 'driver').read_text()
        self.assertIn("'driver': 'examplehost'", driver)
        self.assertIn("'OPENWIZ_EXAMPLEHOST_STATE'", driver)
        self.assertIn("openwiz-examplehost'", driver)
        self.assertNotIn('TEMPLATE', driver)
        self.assertNotIn('openwiz-template', driver)
        self.assertIn('adapters/examplehost/test_driver.py', (dest / 'test_driver.py').read_text())
        self.assertEqual((dest / 'schema.json').read_bytes(),
                         (OPENWIZ / 'adapters/template/schema.json').read_bytes())
        self.assertFalse((dest / 'evidence').exists())
        self.assertTrue(os.access(dest / 'driver', os.X_OK))
        self.assertTrue(os.access(dest / 'fixtures' / 'fake-harness', os.X_OK))
        version = subprocess.run([str(dest / 'driver'), 'version'], capture_output=True, text=True)
        self.assertEqual(json.loads(version.stdout)['driver'], 'examplehost')

    def test_copy_opens_its_readme_with_the_login_line_for_the_host(self):
        # catches: a copied driver whose README keeps the template's login line, so a cloud driver says its login
        # stays on the user's machine (driver v1, "The login line")
        for login, line in (('machine', 'Login: stays on your machine'), ('host', 'Login: held by examplehost')):
            with self.subTest(login):
                self.begin()
                repo = self.tmp / ('repo-' + login)
                self.wd('copy', '--state', self.state, '--openwiz', OPENWIZ, '--into', repo, '--login', login,
                        check=0)
                lines = (repo / 'adapters' / 'examplehost' / 'README.md').read_text().split('\n')
                self.assertTrue(lines[0].startswith('# '), lines[0])
                self.assertEqual(lines[1:3], ['', line])
                self.assertEqual([x for x in lines if x.startswith('Login:')], [line])

    def test_a_cloud_copy_names_its_api_key_variable_never_a_value(self):
        # catches: a cloud driver's README that never names the variable its API key goes in (driver v1, "The login
        # line"), or a copy that writes a value, or names a variable for a login that stays on the machine
        self.begin()
        repo = self.tmp / 'repo'
        self.wd('copy', '--state', self.state, '--openwiz', OPENWIZ, '--into', repo, '--login', 'host',
                '--key-variable', 'EXAMPLEHOST_API_KEY', check=0)
        lines = (repo / 'adapters' / 'examplehost' / 'README.md').read_text().split('\n')
        self.assertEqual(lines[1:5], ['', 'Login: held by examplehost', '',
                                      'API key: set `EXAMPLEHOST_API_KEY` yourself; the driver never asks for it.'])
        for name, args in (('a value', ['--login', 'host', '--key-variable', 'EXAMPLEHOST_API_KEY=%s' % SECRET]),
                           ('a lower-case name', ['--login', 'host', '--key-variable', 'examplehost_key']),
                           ('a machine login', ['--login', 'machine', '--key-variable', 'EXAMPLEHOST_API_KEY'])):
            with self.subTest(name):
                p = self.wd('copy', '--state', self.state, '--openwiz', OPENWIZ, '--into', self.tmp / name, *args,
                            check=1)
                self.assertIn('key variable', p.stdout)
                self.assertFalse((self.tmp / name).exists())

    def test_a_key_variable_shaped_like_a_credential_is_refused_and_never_echoed(self):
        # catches (R10): a credential-shaped value the kit flags, accepted as a variable name and written verbatim
        # into a README meant for a pull request, or echoed back when refused
        self.begin()
        for name in ('AKIA' + 'SYNTHETIC0000000', 'GHP_' + 'SYNTHETIC0123456789', 'SYNTHETICVALUE0123456789ABCDEF'):
            with self.subTest(name[:4]):
                repo = self.tmp / ('repo-' + name[:4])
                p = self.wd('copy', '--state', self.state, '--openwiz', OPENWIZ, '--into', repo, '--login', 'host',
                            '--key-variable', name, check=1)
                self.assertIn('key variable', p.stdout)
                self.assertNotIn(name, p.stdout + p.stderr)
                self.assertFalse(repo.exists())

    def test_copy_never_overwrites(self):
        # catches: a rerun replacing the user's fixed driver with the template again
        self.begin()
        repo = self.tmp / 'repo'
        (repo / 'adapters' / 'examplehost').mkdir(parents=True)
        (repo / 'adapters' / 'examplehost' / 'driver').write_text('# the user\'s own fix\n')
        p = self.wd('copy', '--state', self.state, '--openwiz', OPENWIZ, '--into', repo, '--login', 'machine', check=1)
        self.assertIn('already exists', p.stdout)
        self.assertEqual((repo / 'adapters/examplehost/driver').read_text(), '# the user\'s own fix\n')

    def test_copy_refuses_a_template_it_no_longer_recognises(self):
        # catches: a template change silently leaving `template` names in the copy
        self.begin()
        changed = self.tmp / 'openwiz'
        shutil.copytree(OPENWIZ, changed)
        d = changed / 'adapters/template/driver'
        d.write_text(d.read_text().replace("'driver': 'template'", "'driver': 'base'"))
        p = self.wd('copy', '--state', self.state, '--openwiz', changed, '--into', self.tmp / 'repo', '--login',
                    'machine', check=1)
        self.assertIn("'driver': 'template'", p.stdout)
        self.assertFalse((self.tmp / 'repo' / 'adapters' / 'examplehost').exists())

    def test_begin_refuses_a_host_name_the_contract_refuses(self):
        # catches: a host folder name that breaks the report and share forms later in the run
        for host in ('Example', 'example-', '9host', 'a' * 41):
            with self.subTest(host):
                self.wd('begin', '--state', self.state, check=0)
                self.wd('host', '--state', self.state, '--host', host, '--costly', 'no', check=1)


class Kit(Base):
    def test_kit_runs_with_the_run_arguments_and_records_each_check(self):
        # catches: the kit run with another ticket, repository or harness than the throwaway one, or a result
        # recorded against the wrong check
        self.begin()
        out = PASS5.replace('pass wake', 'fail wake')
        p = self.kit(out, 1)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        argv = (self.tmp / 'kit.argv').read_text().split('\n')
        proxy = argv[argv.index('--driver') + 1]
        self.assertTrue(proxy.startswith(str(self.state) + '/'), proxy)
        self.assertIn(str(self.tmp / 'driver'), Path(proxy).read_text())
        for pair in (['--repo', 'example-user/examplehost-driver-kit'],
                     ['--ticket', '7'], ['--harness', 'exampleagent'], ['--model', 'example-model']):
            i = argv.index(pair[0])
            self.assertEqual(argv[i:i + 2], pair)
        self.assertEqual(self.saved()['kit'], {'version': 'pass', 'start': 'pass', 'wake': 'fail', 'stop': 'pass',
                                              'token': 'pass'})
        self.assertIn('Kit: version pass, start pass, wake fail, stop pass, token pass', p.stdout)

    def test_a_kit_that_could_not_run_records_nothing(self):
        # catches: a kit crash or a garbled kit line read as passing or as a result, or an earlier pass kept
        # after a rerun that proved nothing (R7)
        self.begin()
        self.kit(PASS5, 0)
        for out, code in (('', 2), (PASS5.replace('pass token', 'pass extra'), 0), (PASS5 * 2, 0),
                          (PASS5.replace('pass stop: synthetic\n', ''), 0), (PASS5, 1)):
            with self.subTest(out=out, code=code):
                p = self.kit(out, code)
                self.assertEqual(p.returncode, 2, p.stdout)
                self.assertIn('could not run', p.stdout)
                self.assertEqual(self.saved()['kit'], {}, 'a rerun without usable results keeps no old pass')

    def test_a_costly_kit_run_needs_a_yes_first(self):
        # catches: a kit run against a host that costs money or starts a machine without the user's yes
        self.begin(costly=True)
        p = self.kit()
        self.assertEqual(p.returncode, 1)
        self.assertIn('ask first', p.stdout)
        self.assertFalse((self.tmp / 'kit.argv').exists())
        ask = self.wd('ask', '--state', self.state, '--operation', 'kit', '--effect', 'start a machine', check=0)
        self.assertEqual(ask.stdout.strip(), 'Before I run the driver kit on examplehost: this may start a machine. '
                                             'Say yes to go ahead, or no to skip it.')
        ask_id = self.saved()['asks'][-1]['id']
        p = self.kit(PASS5, 0, '--asked', ask_id)
        self.assertEqual(p.returncode, 1)
        self.assertIn('no answer yet', p.stdout)
        self.reply('yes', 'reply', '--state', self.state)
        self.kit(PASS5, 0, '--asked', ask_id)
        self.assertEqual(self.kit(PASS5, 0, '--asked', ask_id).returncode, 1, 'one ask covers one step')

    def test_a_no_skips_the_kit_and_its_checks_read_not_run(self):
        # catches: a declined step run anyway, or its checks left at an earlier pass
        self.begin(costly=True)
        self.wd('ask', '--state', self.state, '--operation', 'kit', '--effect', 'cost money', check=0)
        ask_id = self.saved()['asks'][-1]['id']
        self.reply('yes, but use the small machine', 'reply', '--state', self.state)
        p = self.kit(PASS5, 0, '--asked', ask_id)
        self.assertEqual(p.returncode, 3, p.stdout)
        self.assertFalse((self.tmp / 'kit.argv').exists())
        self.assertEqual(set(self.saved()['kit'].values()), {'not run'})


    def test_a_yes_to_another_step_never_runs_the_kit(self):
        # catches (R3): a yes to one host step passed as the consent for a costly kit run the user was never asked
        self.begin(costly=True)
        self.wd('ask', '--state', self.state, '--operation', 'host', '--step', 'read the host help', '--effect',
                'cost money', check=0)
        ask_id = self.saved()['asks'][-1]['id']
        self.reply('yes', 'reply', '--state', self.state, check=0)
        p = self.kit(PASS5, 0, '--asked', ask_id)
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn('not an ask for this step', p.stdout)
        self.assertFalse((self.tmp / 'kit.argv').exists())
        self.wd('ask', '--state', self.state, '--operation', 'kit', '--effect', 'cost money', check=0)
        kit_ask = self.saved()['asks'][-1]['id']
        self.reply('yes', 'reply', '--state', self.state, check=0)
        p = self.wd('lesson', 'expired-login', '--state', self.state, '--driver', self.fixed_driver(), '--harness',
                    'exampleagent', '--asked', kit_ask)
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn('not an ask for this step', p.stdout)
        self.assertNotIn('expired-login', self.saved()['lessons'])

    def test_runs_the_kit_started_are_stopped_even_when_its_start_check_fails(self):
        # catches (R4): a run the kit started, whose start check then failed, left running while stop-all says
        # everything stopped
        self.begin()
        driver = self.fixed_driver('plain')
        self.env['PATH'] = '%s:%s' % (driver.parent / 'fixtures', self.env['PATH'])
        self.env['FAKE_KIT_STARTS'] = '1'
        out = ('pass version: synthetic\nfail start: no builder status note appeared\nfail wake: not run: start '
               'failed\nfail stop: not run: start failed\npass token: synthetic\n')
        (self.tmp / 'kit.out').write_text(out)
        self.env.update(FAKE_KIT_OUT=str(self.tmp / 'kit.out'), FAKE_KIT_ARGV=str(self.tmp / 'kit.argv'),
                        FAKE_KIT_EXIT='1')
        self.wd('kit', '--state', self.state, '--openwiz', OPENWIZ, '--driver', driver, '--repo',
                'example-user/examplehost-driver-kit', '--ticket', 7, '--harness', 'fake-harness', '--model',
                'example-model', check=1)
        runs = list((self.tmp / 'driver-state').iterdir())
        self.assertEqual(len(runs), 1)
        pid = int(runs[0].read_text())
        self.addCleanup(lambda: alive(pid) and os.killpg(pid, signal.SIGKILL))
        self.assertTrue(alive(pid))
        p = self.wd('stop-all', '--state', self.state, check=0)
        self.assertEqual(p.stdout.strip().split('\n')[-1], 'Stopped: everything it started (1)')
        for _ in range(50):
            if not alive(pid):
                break
            time.sleep(0.05)
        self.assertFalse(alive(pid))


    def answering_driver(self, answer):
        """A synthetic driver whose `start` prints answer (a Python expression) and whose `stop` leaves a marker."""
        driver = self.tmp / 'answering-driver'
        driver.write_text('#!%s\nimport json, os, sys\nif sys.argv[1] == "start":\n    print(json.dumps(%s))\n'
                          'else:\n    open(%r, "a").write(sys.stdin.read() + "\\n")\n'
                          % (sys.executable, answer, str(self.tmp / 'stopped')))
        driver.chmod(0o700)
        return driver

    def kit_starts_once(self, driver):
        self.env['FAKE_KIT_STARTS'] = '1'
        out = ('pass version: synthetic\nfail start: its start answer held a credential, which the kit does not '
               'show\nfail wake: not run: start failed\nfail stop: not run: start failed\npass token: synthetic\n')
        (self.tmp / 'kit.out').write_text(out)
        self.env.update(FAKE_KIT_OUT=str(self.tmp / 'kit.out'), FAKE_KIT_ARGV=str(self.tmp / 'kit.argv'),
                        FAKE_KIT_EXIT='1')
        self.wd('kit', '--state', self.state, '--openwiz', OPENWIZ, '--driver', driver, '--repo',
                'example-user/examplehost-driver-kit', '--ticket', 7, '--harness', 'fake-harness', '--model',
                'example-model', check=1)

    def test_a_start_answer_the_kit_refuses_never_enters_state_or_cleanup_output(self):
        # catches (R8): the proxy storing a credential-shaped or off-schema run id in run.json, and stop-all
        # printing it, before the kit has screened the answer
        for name, answer, value in (
                ('a secret of the environment', '{"run": os.environ["EXAMPLEHOST_API_TOKEN"]}', SECRET),
                ('a key shape', '{"run": "AKIA" + "SYNTHETIC0000000"}', 'AKIASYNTHETIC0000000'),
                ('a key shape in a field the schema refuses', '{"run": "run-1", "note": "sk-" + "s" * 24}', 'sk-sss'),
                ('a run id the schema refuses', '{"run": "-synthetic-run"}', '-synthetic-run')):
            with self.subTest(name):
                self.tearDown_state()
                self.begin()
                self.kit_starts_once(self.answering_driver(answer))
                self.assertNotIn(value, (self.state / 'run.json').read_text())
                p = self.wd('stop-all', '--state', self.state, check=1)
                self.assertNotIn(value, p.stdout)
                last = p.stdout.strip().split('\n')[-1]
                self.assertTrue(last.startswith('Not stopped: a driver run the kit started'), last)
                self.assertFalse((self.tmp / 'stopped').exists())

    def test_a_start_answer_the_kit_accepts_is_recorded_and_stopped(self):
        # catches (R8): the kit's checks refusing a good answer, so a run it started is never stopped
        self.begin()
        self.kit_starts_once(self.answering_driver('{"run": "run-synthetic-1"}'))
        p = self.wd('stop-all', '--state', self.state, check=0)
        self.assertEqual(p.stdout.strip().split('\n')[-1], 'Stopped: everything it started (1)')
        self.assertEqual((self.tmp / 'stopped').read_text(), '{"run": "run-synthetic-1"}\n')

    def tearDown_state(self):
        shutil.rmtree(self.state, True)
        (self.tmp / 'stopped').unlink(missing_ok=True)

class Asks(Base):
    def test_an_ask_naming_a_credential_is_refused_before_it_is_shown(self):
        # catches: the skill asking the user to hand over or set a login or key
        self.begin()
        for step in ('set EXAMPLEHOST_API_TOKEN for the driver', 'paste your PAT', 'read your login',
                     'copy the apikey', 'use the oauth app'):
            with self.subTest(step):
                p = self.wd('ask', '--state', self.state, '--operation', 'host', '--step', step, '--effect',
                            'cost money', check=1)
                self.assertNotIn('Before I', p.stdout)
                self.assertIn('credential', p.stdout)
        self.wd('begin', '--state', self.tmp / 'other', check=0)
        self.wd('host', '--state', self.tmp / 'other', '--host', 'key-host', '--costly', 'no', check=0)
        self.wd('ask', '--state', self.tmp / 'other', '--operation', 'host', '--step', 'start a sandbox', '--effect',
                'start a machine', check=0)

    def test_only_an_explicit_yes_goes_ahead(self):
        # catches: "maybe", "looks good, but change X" or an empty reply read as consent
        for text, want in (('yes', 'yes'), ('Yes.', 'yes'), ('  YES!\n', 'yes'), ('y', 'yes'), ('no', 'no'),
                           ('', 'no'), ('maybe', 'no'), ('yes, but change the step', 'no'), ('not yes', 'no'),
                           ('yes\nand also do X', 'no')):
            with self.subTest(text=text):
                self.assertEqual(wd.explicit_yes(text), want == 'yes')

    def test_sign_in_says_the_users_own_sign_in(self):
        # catches: the sign-in message offering to handle the user's sign-in
        self.begin()
        p = self.wd('sign-in', '--state', self.state, '--harness', 'exampleagent', check=0)
        self.assertEqual(p.stdout.strip(), 'Your exampleagent sign-in on examplehost has ended. Sign in there '
                                           'yourself, then say done; I never see or handle it.')


class Clock(Base):
    def test_the_time_runs_from_paste_to_passing_rounded_up(self):
        # catches: a time measured from another moment than paste, rounded down, or kept running after 5 of 5
        p = self.passing_report(23)
        self.assertEqual(p.stdout.split('\n')[0], 'Your examplehost driver passed 5 of 5 in 23 minutes.')
        self.shift_paste(600, passed_too=True)  # later reruns of the report keep the time it passed at
        p = self.wd('report', '--state', self.state, '--pr',
                    'https://github.com/example-user/examplehost-driver/pull/1', check=0)
        self.assertTrue(p.stdout.startswith('Your examplehost driver passed 5 of 5 in 23 minutes.\n'), p.stdout)

    def test_the_clock_starts_at_paste_not_when_the_host_is_named(self):
        # catches: the grill's minutes left out of the time because the clock restarts when the host is named
        self.wd('begin', '--state', self.state, check=0)
        self.shift_paste(10 * 60)
        paste = self.saved()['paste']
        self.wd('begin', '--state', self.state, check=0)  # a resumed session keeps it
        self.wd('host', '--state', self.state, '--host', 'examplehost', '--costly', 'no', check=0)
        self.assertEqual(self.saved()['paste'], paste)

    def test_a_fast_run_says_one_minute(self):
        # catches: `0 minutes` or `1 minutes`, both refused by the share line
        self.begin()
        self.kit()
        self.lessons_pass()
        self.wd('stop-all', '--state', self.state, check=0)
        p = self.wd('report', '--state', self.state, '--pr', 'https://github.com/example-user/x/pull/2', check=0)
        self.assertEqual(p.stdout.split('\n')[0], 'Your examplehost driver passed 5 of 5 in 1 minute.')

    def test_a_run_that_never_passes_still_says_its_time(self):
        # catches: a not-passing run ending without its time, or claiming passing with a failed lesson
        self.begin()
        self.kit()
        live = self.tmp / 'live.json'
        fixture = self.tmp / 'fixture.json'
        live.write_text('{"sandbox": {"state": "running"}}')
        fixture.write_text('{"state": "running"}')
        p = self.wd('lesson', 'live-shape', '--state', self.state, '--live', live, '--fixture', fixture)
        self.assertIn('live-shape fail: shape-differs', p.stdout)
        self.shift_paste(58 * 60 - 30)
        self.wd('stop-all', '--state', self.state, check=0)
        p = self.wd('report', '--state', self.state, check=0)
        lines = p.stdout.rstrip('\n').split('\n')
        self.assertEqual(lines[0], 'Your examplehost driver reached 5 of 5 after 58 minutes; not passing yet.')
        self.assertEqual(lines[2], 'Live lessons: live-shape fail, wake-after-turn not run, expired-login not run')
        self.assertEqual(wd.read_report('\n'.join(lines))['result'], 'not-passing')

    def test_a_passing_report_needs_its_pull_request(self):
        # catches: a passing report without the pull request line the contract requires
        self.begin()
        self.kit()
        self.lessons_pass()
        self.wd('stop-all', '--state', self.state, check=0)
        p = self.wd('report', '--state', self.state, check=1)
        self.assertIn('--pr', p.stdout)


class Stop(Base):
    def start_run(self, driver):
        p = subprocess.run([str(driver), 'start'], input=json.dumps(
            {'repository': 'example-user/examplehost-driver-kit', 'ticket': 7, 'skill': 'build-ticket',
             'harness': 'fake-harness', 'model': 'example-model'}), capture_output=True, text=True,
            env=dict(self.env, PATH='%s:%s' % (driver.parent / 'fixtures', self.env['PATH'])))
        self.assertEqual(p.returncode, 0, p.stdout)
        run = json.loads(p.stdout)['run']
        pid = int((self.tmp / 'driver-state' / run).read_text())
        self.addCleanup(lambda: alive(pid) and os.killpg(pid, signal.SIGKILL))
        return run, pid

    def test_stop_all_stops_each_thing_it_started_and_the_report_counts_them(self):
        # catches: a driver run or host machine left running after the skill ends
        self.begin()
        repo = self.tmp / 'repo'
        self.wd('copy', '--state', self.state, '--openwiz', OPENWIZ, '--into', repo, '--login', 'machine', check=0)
        driver = repo / 'adapters/examplehost/driver'
        run, pid = self.start_run(driver)
        self.assertTrue(alive(pid))
        self.wd('started', 'run', '--state', self.state, '--driver', driver, '--run', run, check=0)
        marker = self.tmp / 'sandbox-stopped'
        self.wd('started', 'add', '--state', self.state, '--what', 'sandbox example-1', '--', 'touch', marker,
                check=0)
        p = self.wd('stop-all', '--state', self.state, check=0)
        self.assertEqual(p.stdout.strip().split('\n')[-1], 'Stopped: everything it started (2)')
        for _ in range(50):
            if not alive(pid):
                break
            time.sleep(0.05)
        self.assertFalse(alive(pid))
        self.assertTrue(marker.exists())
        p = self.wd('stop-all', '--state', self.state, check=0)  # a rerun stops nothing twice
        self.assertEqual(p.stdout.strip().split('\n')[-1], 'Stopped: everything it started (2)')

    def test_what_could_not_stop_is_named_with_how_to_stop_it(self):
        # catches: a report saying everything stopped while a machine still runs
        self.begin()
        self.wd('started', 'add', '--state', self.state, '--what', 'sandbox example-2', '--', 'false', check=0)
        p = self.wd('stop-all', '--state', self.state, check=1)
        last = p.stdout.strip().split('\n')[-1]
        self.assertTrue(last.startswith('Not stopped: sandbox example-2'), last)
        self.assertIn('false', last)
        self.kit()
        self.lessons_pass()
        p = self.wd('report', '--state', self.state, '--pr', 'https://github.com/example-user/x/pull/3', check=0)
        self.assertEqual(wd.read_report(p.stdout.rstrip('\n'))['stopped'], False)

    def test_the_report_waits_for_stop_all(self):
        # catches: a final report sent before everything it started was stopped
        self.begin()
        self.wd('started', 'add', '--state', self.state, '--what', 'sandbox example-3', '--', 'true', check=0)
        p = self.wd('report', '--state', self.state, check=1)
        self.assertIn('stop-all', p.stdout)


class ExpiredLogin(Base):
    def test_the_templates_silent_start_fails_the_lesson(self):
        # catches: a driver that answers a run whose first turn ended on an expired sign-in passing the lesson
        self.begin()
        driver = self.fixed_driver('silent', change=lambda t: t.replace('FIRST_TURN_CHECK = True',
                                                                        'FIRST_TURN_CHECK = False'))
        p = self.wd('lesson', 'expired-login', '--state', self.state, '--driver', driver, '--harness',
                    'exampleagent', check=0)
        self.assertIn('expired-login fail: silent-start', p.stdout)
        self.assertEqual(self.saved()['lessons']['expired-login'], 'fail')

    def test_a_driver_that_fails_start_with_the_sign_in_next_passes(self):
        # catches: the lesson never reaching pass for a driver that does it right
        self.begin()
        p = self.wd('lesson', 'expired-login', '--state', self.state, '--driver', self.fixed_driver(), '--harness',
                    'exampleagent', check=0)
        self.assertIn('expired-login pass', p.stdout)

    def test_a_sign_in_next_for_another_harness_or_host_fails(self):
        # catches (R5): a driver whose expired-login error sends the user to the wrong harness or host passing
        self.begin()
        for name, change in (('other-host', lambda t: t.replace("HOST = 'examplehost'", "HOST = 'otherhost'")),
                             ('other-harness', lambda t: t.replace("(req['harness'], HOST)", "('otheragent', HOST)"))):
            with self.subTest(name):
                driver = self.fixed_driver(name, change=change)
                p = self.wd('lesson', 'expired-login', '--state', self.state, '--driver', driver, '--harness',
                            'exampleagent', check=0)
                self.assertIn('expired-login fail: no-sign-in-next', p.stdout)

    def probing_driver(self, name, probe):
        """The fixed driver, refusing with a wrong next step when probe (Python, at its start) succeeds."""
        return self.fixed_driver(name, change=lambda t: t.replace(
            "    if cmd == 'start':\n", "    if cmd == 'start':\n        try:\n            %s\n        except Exception:\n"
            "            pass\n        else:\n            refuse('the probe reached the host', 'nothing')\n" % probe))

    def test_the_probe_runs_only_the_stand_in_in_a_credential_free_environment(self):
        # catches (R2, R5): the probe handing the caller's environment (and any credential in it) to the driver,
        # or falling through to the user's real harness
        self.begin()
        real = self.bin / 'exampleagent'
        real.write_text('#!/bin/sh\ntouch "%s"\n' % (self.tmp / 'real-harness-ran'))
        real.chmod(0o755)
        leaked = ('assert %r not in json.dumps(dict(os.environ)) and %r not in os.environ["PATH"] '
                  'and os.environ["HOME"] != %r and sorted(k for k in os.environ if k not in '
                  '("PWD", "SHLVL", "_", "LC_CTYPE")) == ["HOME", "LANG", "OPENWIZ_EXAMPLEHOST_STATE", "PATH"]; '
                  'raise RuntimeError' % (SECRET, str(self.bin), self.env['HOME']))
        p = self.wd('lesson', 'expired-login', '--state', self.state, '--driver', self.probing_driver('env', leaked),
                    '--harness', 'exampleagent', check=0)
        self.assertIn('expired-login pass', p.stdout)
        self.assertFalse((self.tmp / 'real-harness-ran').exists())
        self.assertEqual(self.gh_calls(), [])

    def test_the_probe_reaches_no_network_host_socket_or_host_file(self):
        # catches (R9): a driver under test reading the user's files or another process's environment, writing
        # outside its box, or reaching the network, a host socket or a real client outside its fixtures
        import socket
        self.begin()
        host_file = self.tmp / 'host-file'
        host_file.write_text('synthetic host file\n')
        tcp = socket.socket()
        tcp.bind(('127.0.0.1', 0))
        tcp.listen(5)
        tcp.setblocking(False)
        self.addCleanup(tcp.close)
        unix = socket.socket(socket.AF_UNIX)
        unix.bind(str(self.tmp / 'host.sock'))
        unix.listen(5)
        unix.setblocking(False)
        self.addCleanup(unix.close)
        client = self.tmp / 'real-client'
        client.write_text('#!/bin/sh\necho reached > "%s"\n' % (self.tmp / 'client-ran'))
        client.chmod(0o755)
        probes = {
            'a host file': 'open(%r).read()' % str(host_file),
            'a write outside its box': 'open(%r, "w").write("x")' % str(self.tmp / 'written'),
            'the parent process environment': 'open("/proc/%d/environ" % os.getppid(), "rb").read()',
            'the network': '__import__("socket").create_connection(("127.0.0.1", %d), 2)' % tcp.getsockname()[1],
            'a host socket': 's = __import__("socket").socket(1); s.connect(%r)' % str(self.tmp / 'host.sock'),
            'a client outside its fixtures': 'subprocess.run([%r], check=True)' % str(client),
            'a file beside the driver': 'open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '
                                        '"host-login.json")).read()',
            'system configuration': 'open("/etc/passwd").read()'}
        for n, (name, probe) in enumerate(probes.items()):
            with self.subTest(name):
                driver = self.probing_driver('probe-%d' % n, probe)
                (driver.parent / 'host-login.json').write_text('{"synthetic": "beside the driver"}')
                p = self.wd('lesson', 'expired-login', '--state', self.state, '--driver', driver, '--harness',
                            'exampleagent', check=0)
                self.assertIn('expired-login pass', p.stdout)
        for sock in (tcp, unix):
            with self.assertRaises(BlockingIOError):
                sock.accept()
        self.assertFalse((self.tmp / 'written').exists())
        self.assertFalse((self.tmp / 'client-ran').exists())

    def test_without_isolation_the_probe_never_runs_the_driver(self):
        # catches (R9): a system that can't isolate the probe running the driver unisolated anyway
        import contextlib
        import io
        from unittest import mock
        self.begin()
        driver = self.probing_driver('unisolated', 'open(%r, "w").write("x")' % str(self.tmp / 'driver-ran'))
        out = io.StringIO()
        with mock.patch.object(wd, 'landlock_abi', return_value=0, create=True), contextlib.redirect_stdout(out):
            code = wd.main(['lesson', 'expired-login', '--state', str(self.state), '--driver', str(driver),
                            '--harness', 'exampleagent'])
        self.assertEqual(code, 1, out.getvalue())
        self.assertIn('cannot isolate', out.getvalue())
        self.assertFalse((self.tmp / 'driver-ran').exists())
        self.assertNotIn('expired-login', self.saved()['lessons'])

    def test_on_macos_only_the_expired_login_probe_is_skipped_with_a_plain_line(self):
        # catches (J289): a Mac, where Landlock, seccomp and /proc don't exist, refusing the lesson (so the skill
        # can never finish there) or running the driver unisolated
        import contextlib
        import io
        from unittest import mock
        self.begin()
        driver = self.probing_driver('mac', 'open(%r, "w").write("x")' % str(self.tmp / 'driver-ran'))
        out = io.StringIO()
        with mock.patch.object(wd.sys, 'platform', 'darwin'), contextlib.redirect_stdout(out):
            code = wd.main(['lesson', 'expired-login', '--state', str(self.state), '--driver', str(driver),
                            '--harness', 'exampleagent'])
        self.assertEqual(code, 3, out.getvalue())
        self.assertEqual(out.getvalue(), 'expired-login not run: this Mac cannot isolate the probe (it needs '
                                         'Linux), so it is skipped; check that lesson on Linux\n')
        self.assertFalse((self.tmp / 'driver-ran').exists())
        self.assertEqual(self.saved()['lessons']['expired-login'], 'not run')
        live = self.tmp / 'live.json'
        live.write_text('{"state": "running"}')
        self.wd('lesson', 'live-shape', '--state', self.state, '--live', live, '--fixture', live, check=0)
        self.kit()
        self.wd('stop-all', '--state', self.state, check=0)
        p = self.wd('report', '--state', self.state, check=0)
        self.assertIn('expired-login not run', p.stdout)

    def test_a_driver_that_never_runs_the_stand_in_proves_nothing(self):
        # catches (R5): a lesson read as passing although the driver never ran the stand-in harness
        self.begin()
        driver = self.fixed_driver('no-harness', change=lambda t: t.replace(
            "    if cmd == 'start':\n", "    if cmd == 'start':\n        refuse('run run-x: the first turn ended at "
            "once: the harness is not signed in (exit 1)', 'sign in to exampleagent on examplehost yourself, then "
            "start again')\n"))
        p = self.wd('lesson', 'expired-login', '--state', self.state, '--driver', driver, '--harness', 'exampleagent',
                    check=1)
        self.assertIn('never ran the stand-in', p.stdout)
        self.assertNotIn('expired-login', self.saved()['lessons'])

    def test_a_harness_that_is_not_a_harness_name_is_refused_before_any_file_is_written(self):
        # catches (R6): a harness given as a path overwriting that file with the stand-in
        self.begin()
        victim = self.tmp / 'victim'
        victim.write_text('keep me\n')
        for harness in (str(victim), '../victim', 'Example', 'a/b'):
            with self.subTest(harness):
                p = self.wd('lesson', 'expired-login', '--state', self.state, '--driver', self.fixed_driver(),
                            '--harness', harness, check=1)
                self.assertIn('not a harness name', p.stdout)
        self.assertEqual(victim.read_text(), 'keep me\n')

    def test_a_costly_lesson_needs_a_yes_and_a_no_reads_not_run(self):
        # catches: a lesson that starts a machine on a costly host run without asking
        self.begin(costly=True)
        driver = self.fixed_driver()
        p = self.wd('lesson', 'expired-login', '--state', self.state, '--driver', driver, '--harness',
                    'exampleagent', check=1)
        self.assertIn('ask first', p.stdout)
        self.wd('ask', '--state', self.state, '--operation', 'expired-login', '--effect', 'start a machine',
                check=0)
        ask_id = self.saved()['asks'][-1]['id']
        self.reply('no', 'reply', '--state', self.state)
        self.wd('lesson', 'expired-login', '--state', self.state, '--driver', driver, '--harness', 'exampleagent',
                '--asked', ask_id, check=3)
        self.assertEqual(self.saved()['lessons']['expired-login'], 'not run')


class Share(Base):
    def offer(self):
        self.passing_report(23)
        return self.wd('share', 'offer', '--state', self.state)

    def test_yes_posts_exactly_the_previewed_line_once(self):
        # catches: a posted comment that differs from the preview, goes elsewhere, or is posted twice
        p = self.offer()
        self.assertEqual(p.returncode, 0, p.stdout)
        preview = p.stdout.rstrip('\n')
        self.assertEqual(wd.read_preview(preview), {'result': 'valid', 'issue': 1966, 'account': 'example-user',
                                                    'host': 'examplehost', 'minutes': 23})
        self.assertFalse([c for c in self.gh_calls() if c['argv'][:2] == ['issue', 'comment']])
        self.reply('yes', 'share', 'reply', '--state', self.state, check=0)
        posts = [c for c in self.gh_calls() if c['argv'][:2] == ['issue', 'comment']]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]['argv'], ['issue', 'comment', '1966', '--repo', 'openwizdev/OpenWiz',
                                            '--body-file', '-'])
        self.assertEqual(posts[0]['stdin'], preview.split('\n')[2])
        self.assertEqual(posts[0]['stdin'], 'examplehost: 5 of 5 in 23 minutes')
        self.reply('yes', 'share', 'reply', '--state', self.state, check=1)
        self.assertEqual(self.wd('share', 'offer', '--state', self.state).returncode, 1)
        self.assertEqual(len([c for c in self.gh_calls() if c['argv'][:2] == ['issue', 'comment']]), 1)

    def test_anything_but_yes_posts_nothing_and_says_nothing_more(self):
        # catches: a share posted without the user's explicit yes
        for text in ('no', '', 'sure, but add my harness', 'maybe later'):
            with self.subTest(text=text):
                self.setUp()
                self.offer()
                p = self.reply(text, 'share', 'reply', '--state', self.state, check=0)
                self.assertEqual(p.stdout, '')
                self.assertFalse([c for c in self.gh_calls() if c['argv'][:2] == ['issue', 'comment']])
                self.reply('yes', 'share', 'reply', '--state', self.state, check=1)
                self.assertFalse([c for c in self.gh_calls() if c['argv'][:2] == ['issue', 'comment']])

    def test_a_failed_post_is_said_and_never_retried(self):
        # catches: a retry posting the line twice after a failure that may have posted it
        self.set_world(comment_exit=1)
        self.offer()
        p = self.reply('yes', 'share', 'reply', '--state', self.state, check=1)
        self.assertIn('did not post', p.stdout)
        self.reply('yes', 'share', 'reply', '--state', self.state, check=1)
        self.assertEqual(len([c for c in self.gh_calls() if c['argv'][:2] == ['issue', 'comment']]), 1)

    def test_no_offer_without_the_one_pinned_driver_times_issue(self):
        # catches: a share posted to a guessed issue, an unpinned or closed one, or one of two
        for issues in ([], [{'number': 1966, 'title': 'Driver times', 'state': 'OPEN', 'pinned': False}],
                       [{'number': 1966, 'title': 'Driver times', 'state': 'CLOSED', 'pinned': True}],
                       [{'number': 1966, 'title': 'Driver time', 'state': 'OPEN', 'pinned': True}],
                       [{'number': 1966, 'title': 'Driver times', 'state': 'OPEN', 'pinned': True},
                        {'number': 2001, 'title': 'Driver times', 'state': 'OPEN', 'pinned': True}],
                       [{'number': 2001, 'title': 'Driver times', 'state': 'OPEN', 'pinned': True}]):
            with self.subTest(issues=issues):
                self.setUp()
                self.set_world(issues)
                p = self.offer()
                self.assertEqual(p.returncode, 1)
                self.assertIn("can't find where driver times go", p.stdout)
                self.assertNotIn('Share your time?', p.stdout)

    def test_a_changed_account_or_issue_needs_a_fresh_preview(self):
        # catches (R1): a yes to one account's preview posting as another account, or to an issue no longer the
        # pinned Driver times issue
        for change in ('account', 'issue'):
            with self.subTest(change):
                self.setUp()
                self.offer()
                world = json.loads(self.world.read_text())
                if change == 'account':
                    world['login'] = 'other-user'
                else:
                    world['issues'][0]['pinned'] = False
                self.world.write_text(json.dumps(world))
                p = self.reply('yes', 'share', 'reply', '--state', self.state, check=1)
                self.assertIn('fresh preview', p.stdout)
                self.assertFalse([c for c in self.gh_calls() if c['argv'][:2] == ['issue', 'comment']])
        p = self.wd('share', 'offer', '--state', self.state, check=1)  # the issue is still unpinned: no offer
        self.assertIn("can't find where driver times go", p.stdout)

    def test_a_fresh_preview_after_an_account_change_names_the_new_account(self):
        # catches (R1): the stale preview's account reused after the binding changed
        self.offer()
        world = json.loads(self.world.read_text())
        world['login'] = 'other-user'
        self.world.write_text(json.dumps(world))
        self.reply('yes', 'share', 'reply', '--state', self.state, check=1)
        p = self.wd('share', 'offer', '--state', self.state, check=0)
        self.assertEqual(wd.read_preview(p.stdout.rstrip('\n'))['account'], 'other-user')
        self.reply('yes', 'share', 'reply', '--state', self.state, check=0)
        self.assertEqual(len([c for c in self.gh_calls() if c['argv'][:2] == ['issue', 'comment']]), 1)

    def test_changed_evidence_or_resources_void_the_report_and_the_pending_share(self):
        # catches (R7): a share offered or posted from a report that no longer holds: a new thing started, or a
        # kit rerun that proved nothing
        self.passing_report(23)
        self.wd('started', 'add', '--state', self.state, '--what', 'sandbox example-4', '--', 'true', check=0)
        p = self.wd('share', 'offer', '--state', self.state, check=1)
        self.assertNotIn('Share your time?', p.stdout)
        self.setUp()
        self.offer()
        self.kit('', 2)
        p = self.reply('yes', 'share', 'reply', '--state', self.state, check=1)
        self.assertFalse([c for c in self.gh_calls() if c['argv'][:2] == ['issue', 'comment']])
        self.wd('stop-all', '--state', self.state, check=0)
        p = self.wd('report', '--state', self.state, check=0)
        self.assertTrue(p.stdout.startswith('Your examplehost driver reached 0 of 5 after'), p.stdout)
        self.wd('share', 'offer', '--state', self.state, check=1)

    def test_no_offer_unless_passing_and_stopped(self):
        # catches: a share offered for a run that did not pass, or that left something running
        self.begin()
        self.kit(PASS5.replace('pass token', 'fail token'), 1)
        self.lessons_pass()
        self.wd('stop-all', '--state', self.state, check=0)
        self.wd('report', '--state', self.state, check=0)
        p = self.wd('share', 'offer', '--state', self.state, check=1)
        self.assertNotIn('Share your time?', p.stdout)
        self.assertEqual(self.gh_calls(), [])


class NoCredential(Base):
    def test_no_step_reads_or_writes_a_login_or_key(self):
        # catches: a step copying a secret from the environment into its state, output or a command it runs
        self.passing_report(23)
        self.wd('share', 'offer', '--state', self.state, check=0)
        self.reply('yes', 'share', 'reply', '--state', self.state, check=0)
        for path in self.state.rglob('*'):
            if path.is_file():
                self.assertNotIn(SECRET, path.read_text())
        self.assertNotIn(SECRET, self.gh_log.read_text())
        self.assertEqual(oct(self.state.stat().st_mode & 0o777), '0o700')
        self.assertEqual(oct((self.state / 'run.json').stat().st_mode & 0o777), '0o600')


if __name__ == '__main__':
    unittest.main()
