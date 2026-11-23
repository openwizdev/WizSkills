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
        for n, name in enumerate(('AKIA' + 'SYNTHETIC0000000', 'GHP_' + 'SYNTHETIC0123456789',
                                  'SYNTHETICVALUE0123456789ABCDEF', 'GHP_' + 'SYNTH0123456')):
            with self.subTest(n):
                repo = self.tmp / ('repo-%d' % n)
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
        self.assertFalse(Path(proxy).exists(), 'the proxy outlived the kit run')
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

    def test_a_link_in_the_drivers_fixtures_is_refused_never_followed(self):
        # catches (R9): staging following a link in fixtures/ and copying a host file into the probe's reach
        self.begin()
        host_file = self.tmp / 'host-login.json'
        host_file.write_text('{"synthetic": "host file"}')
        driver = self.fixed_driver('linked')
        (driver.parent / 'fixtures' / 'login.json').symlink_to(host_file)
        p = self.wd('lesson', 'expired-login', '--state', self.state, '--driver', driver, '--harness', 'exampleagent',
                    check=1)
        self.assertIn('copies only plain files', p.stdout)
        self.assertNotIn('expired-login', self.saved()['lessons'])

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


KEY_OPENWIZ = FIXTURES / 'key-openwiz'
KEY_DRIVER = r'''#!/usr/bin/env python3
"""A synthetic key-host driver: start sends one POST through the key helper beside it, as driver v1 N4 says."""
import json, os, subprocess, sys
HELPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'kernel', 'driver-kit', 'hostkey.py')
HOST = 'examplehost'


def refuse(error, next_):
    print(json.dumps({'error': error, 'next': next_}))
    sys.exit(1)


def ask(method, path, body=None):
    request = {'host': HOST, 'method': method, 'path': path}
    if body is not None:
        request['body'] = body
    p = subprocess.run([sys.executable, '-I', HELPER], input=json.dumps(request), capture_output=True, text=True,
                       timeout=120)
    out = json.loads(p.stdout)
    if p.returncode:
        refuse('the key helper refused: ' + out['error'], out['next'])
    return out


def main():
    cmd = sys.argv[1]
    req = json.loads(sys.stdin.read() or '{}')
    if cmd == 'start':
        PROBE
        out = ask('POST', '/v1/runs', {'ticket': req['ticket']})
        if out['status'] == 401:
            refuse('the host answered 401: the sign-in has ended', NEXT)
        print(json.dumps({'run': 'run-synthetic-1'}))
        return 0
    print(json.dumps({'run': req.get('run'), 'stopped': True}))
    return 0


sys.exit(main())
'''
SIGN_IN_NEXT = "'sign in to %s on %s yourself, then start again' % (req['harness'], HOST)"


class KeyHostExpiredLogin(Base):

    def key_driver(self, name, probe='pass', next_=SIGN_IN_NEXT, change=None):
        folder = self.tmp / name / 'adapters' / 'examplehost'
        folder.mkdir(parents=True)
        text = KEY_DRIVER.replace('PROBE', probe).replace('NEXT', next_)
        (folder / 'driver').write_text(change(text) if change else text)
        (folder / 'driver').chmod(0o755)
        (folder / 'fixtures').mkdir()
        (folder / 'fixtures' / 'reply.json').write_text('{"run": "synthetic"}')
        return folder / 'driver'

    def lesson(self, driver, *extra, openwiz=KEY_OPENWIZ, check=None):
        return self.wd('lesson', 'expired-login', '--state', self.state, '--driver', driver, '--harness',
                       'exampleagent', '--key-host', 'examplehost', '--openwiz', openwiz, *extra, check=check)

    def test_a_key_host_driver_that_turns_the_fake_hosts_401_into_the_sign_in_next_passes(self):
        self.begin()
        p = self.lesson(self.key_driver('fixed'), check=0)
        self.assertIn('expired-login pass', p.stdout)
        self.assertEqual(self.saved()['lessons']['expired-login'], 'pass')

    def test_a_key_host_driver_that_answers_a_run_after_the_401_fails_silent_start(self):
        self.begin()
        driver = self.key_driver('silent', change=lambda t: t.replace('== 401', '== 999'))
        p = self.lesson(driver, check=0)
        self.assertIn('expired-login fail: silent-start', p.stdout)
        self.assertEqual(self.saved()['lessons']['expired-login'], 'fail')

    def test_a_key_host_driver_whose_401_error_names_another_next_fails(self):
        self.begin()
        for name, next_ in (('retry', "'check the host, then retry'"),
                            ('other-harness', "'sign in to otheragent on examplehost yourself, then start again'")):
            with self.subTest(name):
                p = self.lesson(self.key_driver(name, next_=next_), check=0)
                self.assertIn('expired-login fail: no-sign-in-next', p.stdout)

    def test_a_key_host_driver_that_never_reaches_the_fake_host_proves_nothing(self):
        self.begin()
        driver = self.key_driver('no-host', probe="refuse('the sign-in has ended', %s)" % SIGN_IN_NEXT)
        p = self.lesson(driver, check=1)
        self.assertIn("never reached the kit's fake host through the key helper", p.stdout)
        self.assertNotIn('expired-login', self.saved()['lessons'])

    def test_the_key_host_probe_reaches_only_the_fake_host_and_never_a_key(self):
        import socket
        self.begin()
        self.env['EXAMPLEHOST_API_KEY'] = SECRET
        host_file = self.tmp / 'host-file'
        host_file.write_text('synthetic host file\n')
        tcp = socket.socket()
        tcp.bind(('127.0.0.1', 0))
        tcp.listen(5)
        tcp.setblocking(False)
        self.addCleanup(tcp.close)
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.bind(('127.0.0.1', 0))
        udp.setblocking(False)
        self.addCleanup(udp.close)
        unix = socket.socket(socket.AF_UNIX)
        unix.bind(str(self.tmp / 'host.sock'))
        unix.listen(5)
        unix.setblocking(False)
        self.addCleanup(unix.close)
        sock = '__import__("socket")'
        probes = {
            'another loopback port': '%s.create_connection(("127.0.0.1", %d), 2)' % (sock, tcp.getsockname()[1]),
            'a datagram': 's = %s.socket(2, 2); s.sendto(b"x", ("127.0.0.1", %d))'
                          % (sock, udp.getsockname()[1]),
            'a raw socket': '%s.socket(2, 3, 1)' % sock,
            'SCTP': '%s.socket(2, 1, 132)' % sock,
            'IPv6': '%s.socket(10, 1)' % sock,
            'a host socket': 's = %s.socket(1); s.connect(%r)' % (sock, str(self.tmp / 'host.sock')),
            'a listening port': 's = %s.socket(); s.bind(("127.0.0.1", 0)); s.listen(1)' % sock,
            'a host file': 'open(%r).read()' % str(host_file),
            'the real key': 'assert %r in json.dumps(dict(os.environ))' % SECRET,
            'the parent process environment': 'open("/proc/%d/environ" % os.getppid(), "rb").read()'}
        for n, (name, probe) in enumerate(probes.items()):
            with self.subTest(name):
                guarded = ('try:\n            %s\n        except Exception:\n            pass\n        else:\n'
                           "            refuse('the probe reached it', 'nothing')" % probe)
                p = self.lesson(self.key_driver('probe-%d' % n, probe=guarded), check=0)
                self.assertIn('expired-login pass', p.stdout)
        for listening in (tcp, unix):
            with self.assertRaises(BlockingIOError):
                listening.accept()
        with self.assertRaises(BlockingIOError):
            udp.recv(1)

    def run_in_process(self, *args, abi=None):
        """The probe in this process, with every program it starts seen: (exit code, stdout, launched argv)."""
        import contextlib
        import io
        from unittest import mock
        launched, out = [], io.StringIO()
        real_run, real_popen = subprocess.run, subprocess.Popen

        def run(argv, *a, **k):
            launched.append([str(x) for x in argv])
            return real_run(argv, *a, **k)

        def popen(argv, *a, **k):
            launched.append([str(x) for x in argv])
            return real_popen(argv, *a, **k)
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(wd.subprocess, 'run', run))
            stack.enter_context(mock.patch.object(wd.subprocess, 'Popen', popen))
            if abi is not None:
                stack.enter_context(mock.patch.object(wd, 'landlock_abi', return_value=abi))
            stack.enter_context(contextlib.redirect_stdout(out))
            code = wd.main(['lesson', 'expired-login', '--state', str(self.state), '--harness', 'exampleagent',
                            *map(str, args)])
        return code, out.getvalue(), launched

    def marked_checkout(self):
        """A checkout whose kit and helper each leave a mark outside any box, wherever they run unboxed."""
        marked = self.tmp / 'marked'
        if not marked.exists():
            shutil.copytree(KEY_OPENWIZ, marked)
            mark = ('try:\n    open(%r, "a").write(__file__ + "\\n")\nexcept OSError:\n    pass\n'
                    % str(self.tmp / 'checkout-ran'))
            for name in ('kit.py', 'hostkey.py'):
                f = marked / 'kernel' / 'driver-kit' / name
                first, _, rest = f.read_text().partition('\n')
                f.write_text(first + '\n' + mark + rest if first.startswith('#!') else mark + first + '\n' + rest)
        return marked

    def test_a_key_host_route_it_cannot_check_runs_nothing(self):
        # catches: a half-given or unregistered route launching the driver or anything else
        self.begin()
        driver = self.key_driver('refused')
        no_helper = self.tmp / 'no-helper'
        shutil.copytree(KEY_OPENWIZ, no_helper)
        (no_helper / 'kernel' / 'driver-kit' / 'hostkey.py').unlink()
        for name, args in (('an unregistered host', ['--key-host', 'otherhost', '--openwiz', KEY_OPENWIZ]),
                           ('no helper', ['--key-host', 'examplehost', '--openwiz', no_helper]),
                           ('no checkout', ['--key-host', 'examplehost']),
                           ('no key host', ['--openwiz', KEY_OPENWIZ])):
            with self.subTest(name):
                code, out, launched = self.run_in_process('--driver', driver, *args)
                self.assertEqual(code, 1, out)
                self.assertIn('key', out)
                self.assertNotIn('otherhost', out)
                self.assertEqual(launched, [])
        self.assertNotIn('expired-login', self.saved()['lessons'])

    def test_without_landlock_the_key_host_route_launches_nothing_and_runs_no_checkout_code(self):
        # catches: the checkout's kit or helper running in the caller's process, with the caller's environment,
        # before the probe knows it can box it (R1), and anything launched on a kernel that can't box it
        self.begin()
        self.env['DEVIN_API_KEY'] = SECRET
        code, out, launched = self.run_in_process('--driver', self.key_driver('old-kernel'), '--key-host',
                                                  'examplehost', '--openwiz', self.marked_checkout(), abi=0)
        self.assertEqual(code, 1, out)
        self.assertIn('cannot isolate', out)
        self.assertEqual(launched, [])
        self.assertFalse((self.tmp / 'checkout-ran').exists(), 'the checkout ran in the caller')
        self.assertNotIn('expired-login', self.saved()['lessons'])

    def test_the_checkout_code_runs_only_boxed_and_never_in_the_caller(self):
        # catches: the checkout's kit imported by the caller, or its helper run unboxed (R1)
        self.begin()
        self.env['DEVIN_API_KEY'] = SECRET
        p = self.lesson(self.key_driver('fixed'), openwiz=self.marked_checkout(), check=0)
        self.assertIn('expired-login pass', p.stdout)
        self.assertFalse((self.tmp / 'checkout-ran').exists(), 'the checkout ran outside a box')

    def test_neither_the_driver_nor_the_helper_reaches_any_address(self):
        # catches: TCP to the fake host's port on another address, or to any address at all, from the driver
        # or from a checkout helper (R2); and the helper seeing the caller's key or environment (R1)
        self.begin()
        self.env['EXAMPLEHOST_API_KEY'] = SECRET
        self.env['DEVIN_API_KEY'] = SECRET
        host_file = self.tmp / 'host-file'
        host_file.write_text('synthetic host file\n')
        port = 'int(os.environ.get("OPENWIZ_HOSTKEY_TEST_ORIGIN", ":4010").rpartition(":")[2])'
        connect = 's = __import__("socket").socket(); s.settimeout(2); s.connect(("%s", ' + port + '))'
        reach = {'the fake host': connect % '127.0.0.1',
                 'the same port on another loopback address': connect % '127.0.0.2',
                 'the same port on another address': connect % '192.0.2.1',
                 'a local socket pair': '__import__("socket").socketpair()'}
        for n, (name, probe) in enumerate(reach.items()):
            with self.subTest('driver: ' + name):
                guarded = ('try:\n            %s\n        except PermissionError:\n            pass\n'
                           '        except Exception:\n            refuse("the kernel let it try", "nothing")\n'
                           '        else:\n            refuse("the probe reached it", "nothing")' % probe)
                p = self.lesson(self.key_driver('reach-%d' % n, probe=guarded), check=0)
                self.assertIn('expired-login pass', p.stdout)
        # A checkout helper that, on any reach, answers 200 instead of the fake host's 401: the driver then
        # answers a run, and the lesson fails. Python itself sets LC_CTYPE in a C locale (PEP 538).
        helper = dict(reach, **{
            'the caller\'s key': 'assert any(%r in v for v in os.environ.values())' % SECRET,
            'any variable but the override': 'assert set(os.environ) - {"OPENWIZ_HOSTKEY_TEST_ORIGIN", "LC_CTYPE"}',
            'a host file': 'open(%r).read()' % str(host_file),
            'its parent\'s environment': 'assert open("/proc/%d/environ" % os.getppid(), "rb").read()'})
        evil = self.tmp / 'evil'
        shutil.copytree(KEY_OPENWIZ, evil)
        f = evil / 'kernel' / 'driver-kit' / 'hostkey.py'
        checks = ''.join('    try:\n        %s\n    except (PermissionError, AssertionError):\n        pass\n'
                         '    except Exception:\n        reached.append(%r)\n    else:\n        reached.append(%r)\n'
                         % (probe, name, name) for name, probe in helper.items())
        f.write_text(f.read_text().replace(
            'def main():\n', 'def main():\n    reached = []\n' + checks +
            '    if reached:\n        print(json.dumps({"status": 200, "body": {}}))\n        return 0\n'))
        p = self.lesson(self.key_driver('reach-helper'), openwiz=evil, check=0)
        self.assertIn('expired-login pass', p.stdout)

    def test_a_driver_that_takes_the_test_key_itself_proves_nothing(self):
        # catches: a driver that fetches the fake host's test key and calls it without the helper passing (R3)
        self.begin()
        take = ('import urllib.request\n        origin = os.environ.get("OPENWIZ_HOSTKEY_TEST_ORIGIN", '
                '"http://127.0.0.1:4010")\n        try:\n'
                '            key = json.loads(urllib.request.urlopen(origin + "/.openwiz/hostkey-test-key").read())'
                '["key"]\n            urllib.request.urlopen(urllib.request.Request(origin + "/v1/runs", b"{}", '
                '{"Authorization": "Bearer " + key}))\n        except Exception:\n            pass\n'
                '        refuse("the sign-in has ended", %s)' % SIGN_IN_NEXT)
        p = self.lesson(self.key_driver('takes-key', probe=take), check=1)
        self.assertIn("never reached the kit's fake host through the key helper", p.stdout)
        self.assertNotIn('expired-login', self.saved()['lessons'])

    def test_a_driver_that_names_the_sign_in_step_whatever_the_host_says_proves_nothing(self):
        # catches: an unconditional sign-in answer passing as 401 handling: the negative control runs start
        # again against a fake host answering 500 (R3)
        self.begin()
        driver = self.key_driver('always', change=lambda t: t.replace("out['status'] == 401", 'True'))
        p = self.lesson(driver, check=1)
        self.assertIn('names the sign-in step even when the host answers 500', p.stdout)
        self.assertNotIn('expired-login', self.saved()['lessons'])

    def test_a_driver_that_hangs_leaves_nothing_running(self):
        # catches: a timed-out start leaving its worker running after the probe exits (R4)
        self.begin()
        token = 'write-driver-test-worker-%d' % os.getpid()
        hang = ('subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)", %r], '
                'start_new_session=True)\n        __import__("time").sleep(600)' % token)
        driver = self.key_driver('hangs', probe=hang)

        def workers():
            found = []
            for pid in filter(str.isdigit, os.listdir('/proc')):
                try:
                    if token.encode() in Path('/proc/%s/cmdline' % pid).read_bytes() and alive(int(pid)):
                        found.append(int(pid))
                except OSError:
                    pass
            return found

        def kill_left():
            for pid in workers():
                os.kill(pid, signal.SIGKILL)
        self.addCleanup(kill_left)
        # The probe's 300-second wait for start, cut to 3 so the test is quick.
        run = ('import subprocess, sys\nsys.path.insert(0, %r)\nimport write_driver as wd\nreal = subprocess.run\n'
               'def run(*a, **k):\n    if k.get("timeout") == 300:\n        k["timeout"] = 3\n'
               '    return real(*a, **k)\nwd.subprocess.run = run\nsys.exit(wd.main(sys.argv[1:]))\n'
               % str(SCRIPT.parent))
        probe = subprocess.Popen([sys.executable, '-I', '-c', run, 'lesson', 'expired-login', '--state', self.state,
                                  '--driver', driver, '--harness', 'exampleagent', '--key-host', 'examplehost',
                                  '--openwiz', KEY_OPENWIZ], env=self.env, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, cwd=self.tmp)
        deadline = time.monotonic() + 30
        while not workers() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertTrue(workers(), 'the hanging driver never started its worker')
        out = probe.communicate(timeout=60)[0]
        self.assertEqual(probe.returncode, 1, out)
        self.assertEqual(workers(), [], 'the timed-out driver left its worker running')
        self.assertIn('did not answer', out)
        self.assertNotIn('expired-login', self.saved()['lessons'])

    def test_the_skill_teaches_the_key_host_route_in_place_of_out_of_reach(self):
        # catches: the skill text losing the route, its two refusals after start, or where it runs
        text = key_host_lines()
        self.assertNotIn('out of reach', text)
        self.assertIn('`$W lesson expired-login --state <state> --driver <driver> --harness <h> --key-host '
                      "<the host's registered name> --openwiz <openwiz> [--asked <id>]`", text)
        self.assertIn("the kit's fake host answering 401", text)
        self.assertIn('no real key, no live host and no network', text)
        self.assertIn('fail `start` with `next` exactly the contract\'s `sign_in_next`', text)
        self.assertIn('runs `start` again against the fake host answering 500', text)
        self.assertIn('A driver that never reaches the fake host through the helper, or that names the sign-in '
                      'step after the 500 too, proves nothing, and the lesson records nothing.', text)
        self.assertIn('This route needs Linux with Landlock; elsewhere it refuses and runs nothing, and on macOS '
                      'the lesson reads `not run` as step 4 says.', text)

    def test_the_contract_names_the_key_host_route(self):
        text = ' '.join(wd.CONTRACT.read_text().split())
        self.assertIn('**Key-host route.**', text)
        self.assertIn("the kit's fake host answering 401", text)
        self.assertIn('again against the fake host answering 500', text)
        self.assertIn('no process of the probe can open a socket', text)

    @unittest.skipUnless(os.environ.get('WRITE_DRIVER_OPENWIZ'),
                         'set WRITE_DRIVER_OPENWIZ to an OpenWiz checkout with the key helper to run the real fake host')
    def test_the_key_host_route_runs_against_the_real_kits_fake_host_and_helper(self):
        fork = self.tmp / 'fork'
        shutil.copytree(Path(os.environ['WRITE_DRIVER_OPENWIZ']).resolve() / 'kernel', fork / 'kernel')
        registry = fork / 'kernel' / 'driver-kit' / 'hosts.json'
        hosts = json.loads(registry.read_text())
        hosts['examplehost'] = json.loads((KEY_OPENWIZ / 'kernel' / 'driver-kit' / 'hosts.json').read_text())['examplehost']
        registry.write_text(json.dumps(hosts, indent=2))
        self.begin()
        for name, change, read, code in (('fixed', None, 'expired-login pass', 0),
                                         ('silent', lambda t: t.replace('== 401', '== 999'),
                                          'expired-login fail: silent-start', 0),
                                         ('always', lambda t: t.replace("out['status'] == 401", 'True'),
                                          'names the sign-in step even when the host answers 500', 1)):
            with self.subTest(name):
                p = self.lesson(self.key_driver(name, change=change), openwiz=fork, check=code)
                print(p.stdout, end='')
                self.assertIn(read, p.stdout)


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

    def test_a_refused_expired_login_rerun_voids_the_passing_lesson_and_the_pending_share(self):
        self.offer()
        driver = self.fixed_driver('no-harness', change=lambda t: t.replace(
            "    if cmd == 'start':\n", "    if cmd == 'start':\n        refuse('the harness is not signed in', "
            "'sign in to exampleagent on examplehost yourself, then start again')\n"))
        p = self.wd('lesson', 'expired-login', '--state', self.state, '--driver', driver, '--harness', 'exampleagent',
                    check=1)
        self.assertIn('never ran the stand-in', p.stdout)
        self.assertNotIn('expired-login', self.saved()['lessons'])
        self.reply('yes', 'share', 'reply', '--state', self.state, check=1)
        self.assertFalse([c for c in self.gh_calls() if c['argv'][:2] == ['issue', 'comment']])
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


class KeyHostCopy(Base):

    def copy(self, *args, openwiz=OPENWIZ, into=None, check=None):
        into = into or self.tmp / 'repo'
        return self.wd('copy', '--state', self.state, '--openwiz', openwiz, '--into', into, *args, check=check)

    def test_a_key_host_copy_names_the_host_its_variable_and_its_keychain_entry_on_one_line(self):
        self.begin()
        self.copy('--login', 'host', '--key-host', 'examplehost', check=0)
        lines = (self.tmp / 'repo' / 'adapters' / 'examplehost' / 'README.md').read_text().split('\n')
        self.assertEqual(lines[1:5], ['', 'Login: held by examplehost', '',
                                      'API key: through the key helper for `examplehost`: set `EXAMPLEHOST_API_KEY` '
                                      'yourself, or keep it in your keychain as `openwiz-examplehost`; the driver '
                                      'never sees it.'])
        self.assertEqual([x for x in lines if x.startswith('API key:')], [lines[4]])

    def test_a_key_host_copy_refuses_what_the_registry_does_not_hold(self):
        self.begin()
        broken = self.tmp / 'broken-openwiz'
        shutil.copytree(OPENWIZ, broken)
        cases = {'an unregistered host': (['--login', 'host', '--key-host', 'otherhost'], OPENWIZ),
                 'a machine login': (['--login', 'machine', '--key-host', 'examplehost'], OPENWIZ),
                 'both key options': (['--login', 'host', '--key-host', 'examplehost', '--key-variable',
                                       'EXAMPLEHOST_API_KEY'], OPENWIZ),
                 'no registry': (['--login', 'host', '--key-host', 'examplehost'], self.tmp / 'no-openwiz'),
                 'a broken registry': (['--login', 'host', '--key-host', 'examplehost'], broken)}
        shutil.copytree(OPENWIZ, self.tmp / 'no-openwiz')
        (self.tmp / 'no-openwiz' / 'kernel' / 'driver-kit' / 'hosts.json').unlink()
        (broken / 'kernel' / 'driver-kit' / 'hosts.json').write_text(
            '{"examplehost": {"origin": "https://api.examplehost.example", "variable": "EXAMPLEHOST_API_KEY=%s", '
            '"keychain": "openwiz-examplehost", "header": "authorization-bearer"}}' % SECRET)
        for name, (args, openwiz) in cases.items():
            with self.subTest(name):
                into = self.tmp / ('repo-' + name.replace(' ', '-'))
                p = self.copy(*args, openwiz=openwiz, into=into, check=1)
                self.assertIn('key host', p.stdout)
                self.assertNotIn('otherhost', p.stdout + p.stderr)
                self.assertFalse(into.exists())


def key_host_lines():
    skill = (SCRIPT.parents[1] / 'SKILL.md').read_text()
    start = skill.find('**A key host.**')
    if start < 0:
        return ''
    end = skill.find('\n3. ', start)
    return ' '.join(skill[start:end if end > 0 else None].split())


class KeyHost(unittest.TestCase):

    def test_a_key_host_driver_calls_only_the_helper_as_ky1_fixes_it(self):
        text = key_host_lines()
        for words in ("key helper, `hostkey.py` in OpenWiz's `kernel/driver-kit/`, run with `python3 -I`",
                      "is the only way the driver reaches the host",
                      "`host`, the host's registered name; `method`, `GET`, `POST` or `DELETE`; `path`, an absolute "
                      "path on the host; and, optionally, `body`, an object",
                      "`status`, the HTTP status, and `body`, the parsed JSON or `null`",
                      "exits 1 with driver v1's D3 error",
                      "sends it only over HTTPS to the address registered for that host",
                      "never names, reads, receives or prints the key, and never chooses the address",
                      "OpenWiz never stores a key"):
            self.assertIn(words, text)
        self.assertNotIn('a method and a path only', text)

    def test_a_key_host_driver_is_written_proved_and_proposed_in_openwiz(self):
        text = key_host_lines()
        for words in ('write the driver in an OpenWiz checkout at `adapters/<host>/`',
                      'add its row to `kernel/driver-kit/hosts.json` there',
                      'run the kit there',
                      'open the pull request to openwizdev/OpenWiz',
                      "Every other host's driver stays in the user's own repository"):
            self.assertIn(words, text)
        self.assertNotIn('Run the kit on a copy of the driver', text)

    def test_a_key_hosts_live_shape_goes_through_the_helper_with_a_yes_first(self):
        text = key_host_lines()
        self.assertIn("**live-shape** for a key host: the host's own tool is the helper", text)
        self.assertIn('ask first if it costs money or starts a machine', text)
        self.assertIn('save its `body`', text)

    def test_a_key_hosts_readme_line_comes_from_copy_key_host(self):
        self.assertIn("Run `copy` with `--key-host <the host's registered name>` instead of `--key-variable`",
                      key_host_lines())

    def test_adding_a_key_host_is_one_reviewed_row_in_the_registry(self):
        text = key_host_lines()
        self.assertIn('one reviewed row in `kernel/driver-kit/hosts.json`', text)
        self.assertIn('reviewed in that same pull request to openwizdev/OpenWiz', text)

    def test_the_key_stays_with_the_user_and_the_driver_never_sees_it(self):
        text = key_host_lines()
        self.assertIn("in the user's system keychain or in an environment variable they set", text)
        self.assertIn('the driver never sees it', text)
        self.assertIn("the kit's token check covers the key", text)

    def test_the_key_host_lines_never_ask_for_read_or_pass_a_key(self):
        text = key_host_lines()
        self.assertIn('ask for, read, print, store or pass the key', text)
        for tool in ('export ', 'secret-tool', 'security ', 'DEVIN_API_KEY', '=<'):
            self.assertNotIn(tool, text)
        skill = (SCRIPT.parents[1] / 'SKILL.md').read_text()
        self.assertIn('- **Never a login or key.** Never ask for, read, print, store or pass a login, token, key, '
                      'password, secret or cookie', skill)

    def test_a_host_that_cannot_wake_or_stop_the_same_run_ends_in_a_plain_no(self):
        text = key_host_lines()
        self.assertIn("can't wake the same run or stop it gets no driver", text)
        self.assertIn('say so plainly, run `$W stop-all`, and stop', text)

    def test_the_sample_key_host_driver_names_no_key_and_reaches_the_host_only_through_the_helper(self):
        driver = (FIXTURES / 'key-host' / 'driver.txt').read_text()
        self.assertIn("'kernel', 'driver-kit', 'hostkey.py'", driver)
        self.assertIn("{'host': HOST, 'method': method, 'path': path}", driver)
        for word in ('DEVIN_API_KEY', 'openwiz-devin', 'secret-tool', 'security', 'urllib', 'http.client',
                     'socket', 'Authorization', 'environ'):
            self.assertNotIn(word, driver)

    @unittest.skipUnless(os.environ.get('WRITE_DRIVER_OPENWIZ'),
                         'set WRITE_DRIVER_OPENWIZ to an OpenWiz checkout with the key helper to run the real kit')
    def test_the_skills_kit_step_runs_the_real_kits_key_check_on_a_driver_in_an_openwiz_fork(self):
        import importlib.machinery
        import importlib.util
        openwiz = Path(os.environ['WRITE_DRIVER_OPENWIZ']).resolve()
        tmp = Path(tempfile.mkdtemp(prefix='write-driver-key-host-'))
        self.addCleanup(shutil.rmtree, tmp, True)
        fork = tmp / 'fork'
        shutil.copytree(openwiz / 'kernel', fork / 'kernel')
        shutil.copytree(openwiz / 'adapters' / 'template', fork / 'adapters' / 'template')
        state, bin_ = tmp / 'wd-state', tmp / 'bin'
        bin_.mkdir()
        (bin_ / 'gh').write_text(FAKE_KIT_GH)
        (bin_ / 'gh').chmod(0o755)
        kits = fork / 'kernel' / 'driver-kit'

        def module(path):
            spec = importlib.util.spec_from_loader(path.name, importlib.machinery.SourceFileLoader(path.name, str(path)))
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            return m
        host = module(kits / 'kit.py').FakeHost(test_key='synthetic-canary-0123456789abcdef')
        self.addCleanup(host.close)
        env = {k: v for k, v in os.environ.items() if k not in ('OPENWIZ_GITHUB_APP_KEY', 'DEVIN_API_KEY')}
        env.update(KIT_TRACKER=module(kits / 'test_kit.py').tracker(str(tmp)), OPENWIZ_TEMPLATE_STATE=str(tmp / 'runs'),
                   PATH=os.pathsep.join([str(bin_), str(kits / 'fixtures'), env['PATH']]),
                   OPENWIZ_HOSTKEY_TEST_ORIGIN=host.origin)

        def wd(*args):
            return subprocess.run([sys.executable, '-I', str(SCRIPT), args[0], '--state', str(state), *map(str, args[1:])],
                                  env=env, capture_output=True, text=True, timeout=600)
        for args in (('begin',), ('host', '--host', 'devin', '--costly', 'no'),
                     ('copy', '--openwiz', fork, '--into', fork, '--login', 'host', '--key-host', 'devin')):
            self.assertEqual(wd(*args).returncode, 0, args)
        driver = fork / 'adapters' / 'devin' / 'driver'
        shutil.copy(FIXTURES / 'key-host' / 'driver.txt', driver)
        driver.chmod(0o755)
        readme = fork / 'adapters' / 'devin' / 'README.md'
        for runs, linked in enumerate((False, True), 1):
            with self.subTest(readme='a relative link' if linked else 'a file'):
                if linked:
                    (fork / 'docs').mkdir()
                    readme.rename(fork / 'docs' / 'devin-README.md')
                    readme.symlink_to(os.path.join('..', '..', 'docs', 'devin-README.md'))
                p = wd('kit', '--openwiz', fork, '--driver', driver, '--repo', 'example/site', '--ticket', 7,
                       '--harness', 'fake-harness', '--model', 'Synthetic 1', '--wait', 30)
                print(p.stdout, end='')
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                self.assertIn('the devin key reached its host only from the key helper, in its header', p.stdout)
                self.assertTrue(host.requests, 'the driver never reached the fake host')
                saved = json.loads((state / 'run.json').read_text())
                self.assertEqual([x['stopped'] for x in saved['started']], [True] * (runs - 1) + [False])
                self.assertEqual(sorted(x.name for x in state.iterdir()), ['run.json'])
                wd('stop-all')


FAKE_KIT_GH = r"""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
query = next((a[len('query='):] for a in args if a.startswith('query=')), '')
if args[:2] != ['api', 'graphql']:
    sys.exit(9)
with open(os.environ['KIT_TRACKER']) as f:
    tracker = json.load(f)
if 'object(expression' in query:
    row = '| Record authors | %s |' % ' '.join('`%s`' % a for a in tracker['record_authors'])
    print(json.dumps({'data': {'repository': {'object': {'text': row + '\n'}}}}))
else:
    nodes = [{'databaseId': c['id'], 'updatedAt': c['updated_at'], 'body': c['body'],
              'author': {'__typename': 'Bot' if c['author'].endswith('[bot]') else 'User',
                         'login': c['author'][:-5] if c['author'].endswith('[bot]') else c['author']}}
             for c in tracker['comments']]
    print(json.dumps({'data': {'repository': {'issue': {'comments': {
        'pageInfo': {'hasNextPage': False, 'endCursor': None}, 'nodes': nodes}}}}}))
"""

RECORDING_KIT = r"""import json, os, sys
driver = sys.argv[sys.argv.index('--driver') + 1]
top = os.path.dirname(driver)
seen = sorted(os.path.relpath(os.path.join(d, n), top) for d, _, names in os.walk(top, followlinks=True)
              for n in names)
with open(os.environ['RECORDING_KIT_OUT'], 'w') as f:
    json.dump({'files': seen, 'readme': open(os.path.join(top, 'README.md')).read()}, f)
for check in ('version', 'start', 'wake', 'stop', 'token'):
    print('pass %s: synthetic' % check)
"""


class KitStaging(Base):
    def test_the_kit_sees_the_drivers_readme_and_files_beside_what_it_runs(self):
        self.begin()
        openwiz = self.tmp / 'openwiz'
        shutil.copytree(OPENWIZ, openwiz)
        (openwiz / 'kernel' / 'driver-kit' / 'kit.py').write_text(RECORDING_KIT)
        self.wd('copy', '--state', self.state, '--openwiz', openwiz, '--into', openwiz, '--login', 'host',
                '--key-host', 'examplehost', check=0)
        folder = openwiz / 'adapters' / 'examplehost'
        (folder / 'fixtures' / 'kit-host.json').write_text('{"answers": []}')
        self.env['RECORDING_KIT_OUT'] = str(self.tmp / 'seen.json')
        self.wd('kit', '--state', self.state, '--openwiz', openwiz, '--driver', folder / 'driver', '--repo',
                'example-user/examplehost-driver-kit', '--ticket', 7, '--harness', 'exampleagent', '--model',
                'example-model', check=0)
        seen = json.loads((self.tmp / 'seen.json').read_text())
        self.assertEqual(seen['readme'], (folder / 'README.md').read_text())
        for name in ('README.md', 'schema.json', os.path.join('fixtures', 'kit-host.json')):
            self.assertIn(name, seen['files'])


LOOKING_KIT = r"""import json, os, sys
driver = sys.argv[sys.argv.index('--driver') + 1]
top = os.path.dirname(driver)
def read(name):
    try:
        with open(os.path.join(top, name)) as f:
            return f.read()
    except OSError:
        return None
with open(os.environ['LOOKING_KIT_OUT'], 'w') as f:
    json.dump({'readme': read('README.md'), 'fixture': read(os.path.join('fixtures', 'kit-host.json'))}, f)
for check in ('version', 'start', 'wake', 'stop', 'token'):
    print('pass %s: synthetic' % check)
"""

TWO_STARTS = """
def main():
    args = sys.argv[1:]
    driver = args[args.index('--driver') + 1]
    request = json.dumps({'repository': 'example-user/examplehost-driver-kit', 'ticket': 7, 'skill': 'build-ticket',
                          'harness': 'exampleagent', 'model': 'example-model'})
    subprocess.run([driver, 'start'], input=request, text=True, capture_output=True)
    env = dict(os.environ, OPENWIZ_HOSTKEY_TEST_ORIGIN='http://127.0.0.1:9')
    subprocess.run([driver, 'start'], input=request, text=True, capture_output=True, env=env)
    for check in ('version', 'start', 'wake', 'stop', 'token'):
        print('pass %s: synthetic' % check)


if __name__ == '__main__':
    main()
"""


class KitStagingSafety(Base):

    def driver_folder(self, kit_text):
        self.begin()
        openwiz = self.tmp / 'openwiz'
        shutil.copytree(OPENWIZ, openwiz)
        (openwiz / 'kernel' / 'driver-kit' / 'kit.py').write_text(kit_text)
        self.wd('copy', '--state', self.state, '--openwiz', openwiz, '--into', openwiz, '--login', 'host',
                '--key-host', 'examplehost', check=0)
        return openwiz, openwiz / 'adapters' / 'examplehost'

    def run_kit(self, openwiz, folder, check=None, driver=None):
        return self.wd('kit', '--state', self.state, '--openwiz', openwiz, '--driver', driver or folder / 'driver',
                       '--repo', 'example-user/examplehost-driver-kit', '--ticket', 7, '--harness', 'exampleagent',
                       '--model', 'example-model', check=check)

    def test_a_relative_readme_or_fixture_link_reads_the_same_file_in_the_kits_view(self):
        openwiz, folder = self.driver_folder(LOOKING_KIT)
        shared = openwiz / 'shared'
        shared.mkdir()
        (shared / 'README.md').write_text((folder / 'README.md').read_text())
        (shared / 'kit-host.json').write_text('{"answers": []}')
        (folder / 'README.md').unlink()
        (folder / 'README.md').symlink_to(os.path.join('..', '..', 'shared', 'README.md'))
        (folder / 'fixtures' / 'kit-host.json').unlink(missing_ok=True)
        (folder / 'fixtures' / 'kit-host.json').symlink_to(os.path.join('..', '..', '..', 'shared', 'kit-host.json'))
        self.env['LOOKING_KIT_OUT'] = str(self.tmp / 'seen.json')
        self.run_kit(openwiz, folder, check=0)
        seen = json.loads((self.tmp / 'seen.json').read_text())
        self.assertEqual(seen['readme'], (shared / 'README.md').read_text())
        self.assertEqual(seen['fixture'], '{"answers": []}')

    def test_a_link_at_the_proxys_name_is_refused_and_its_target_never_written(self):
        openwiz, folder = self.driver_folder(LOOKING_KIT)
        victim = self.tmp / 'victim.txt'
        victim.write_text('synthetic user file\n')
        victim.chmod(0o640)
        (folder / '.write-driver-proxy').symlink_to(victim)
        self.env['LOOKING_KIT_OUT'] = str(self.tmp / 'seen.json')
        p = self.run_kit(openwiz, folder)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn('could not run', p.stdout)
        self.assertEqual(victim.read_text(), 'synthetic user file\n')
        self.assertEqual(oct(victim.stat().st_mode & 0o777), '0o640')
        self.assertFalse((self.tmp / 'seen.json').exists(), 'the kit ran after a refused stage')

    def test_no_local_file_of_the_drivers_folder_is_copied_into_state_or_left_after_the_kit(self):
        marker = 'synthetic-local-marker-0123'
        openwiz, folder = self.driver_folder(LOOKING_KIT)
        (folder / '.env').write_text('EXAMPLE_SETTING=%s\n' % marker)
        self.env['LOOKING_KIT_OUT'] = str(self.tmp / 'seen.json')
        for p in (self.run_kit(openwiz, folder, check=0), self.wd('stop-all', '--state', self.state, check=0)):
            for path in self.state.rglob('*'):
                if path.is_file() and not path.is_symlink():
                    self.assertNotIn(marker, path.read_text(errors='replace'), path)
        self.assertEqual(sorted(x.name for x in self.state.iterdir()), ['run.json'])

    def test_a_failed_kit_run_leaves_no_stage_behind(self):
        openwiz, folder = self.driver_folder('import sys\nsys.exit(5)\n')
        self.assertEqual(self.run_kit(openwiz, folder).returncode, 2)
        self.assertEqual(sorted(x.name for x in self.state.iterdir()), ['run.json'])

    def test_a_start_under_the_kits_own_test_origin_never_reaches_stop_all(self):
        fixture = (OPENWIZ / 'kernel' / 'driver-kit' / 'kit.py').read_text()
        kit = fixture[:fixture.index('\ndef main():')] + TWO_STARTS
        for launch in (None, 'http://127.0.0.1:8'):
            with self.subTest(launch=launch):
                shutil.rmtree(self.tmp / 'openwiz', True)
                self.tearDown_state()
                self.env.pop('OPENWIZ_HOSTKEY_TEST_ORIGIN', None)
                if launch:
                    self.env['OPENWIZ_HOSTKEY_TEST_ORIGIN'] = launch
                openwiz, folder = self.driver_folder(kit)
                driver = self.tmp / 'two-runs-driver'
                driver.write_text(
                    '#!%s\nimport json, os, sys\n'
                    'run = "run-key" if os.environ.get("OPENWIZ_HOSTKEY_TEST_ORIGIN") == "http://127.0.0.1:9" '
                    'else "run-main"\n'
                    'if sys.argv[1] == "start":\n    print(json.dumps({"run": run}))\n'
                    'else:\n    open(%r, "a").write(sys.stdin.read() + "\\n")\n'
                    % (sys.executable, str(self.tmp / 'stopped')))
                driver.chmod(0o700)
                self.run_kit(openwiz, folder, check=0, driver=driver)
                self.assertNotIn('run-key', (self.state / 'run.json').read_text())
                self.env['OPENWIZ_HOSTKEY_TEST_ORIGIN'] = 'http://127.0.0.1:9'
                p = self.wd('stop-all', '--state', self.state, check=0)
                self.assertEqual(p.stdout.strip().split('\n')[-1], 'Stopped: everything it started (1)')
                self.assertEqual((self.tmp / 'stopped').read_text(), '{"run": "run-main"}\n')

    def tearDown_state(self):
        shutil.rmtree(self.state, True)
        (self.tmp / 'stopped').unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
