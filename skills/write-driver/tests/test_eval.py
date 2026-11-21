import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location('test_write_driver', Path(__file__).with_name('test_write_driver.py'))
t = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(t)

SCRIPT = Path(os.environ.get('WRITE_DRIVER_EVAL_SCRIPT') or t.SCRIPT)
HOST, HARNESS, PR = 'examplehost', 'exampleagent', 'https://github.com/example-user/examplehost-driver/pull/1'
YES = {'kit': 'yes', 'expired-login': 'yes', 'host': 'yes', 'share': 'yes'}
HARNESS_TURN_UNTIL_STOPPED_OR_EVAL_TURN_SECONDS = '#!/bin/sh\nexec sleep "${EVAL_TURN_SECONDS:-300}"\n'
GRILL_SECONDS = 22 * 60 + 1
REPORTED_TIME = '23 minutes'


class Eval(t.Base):
    def setUp(self):
        super().setUp()
        (self.bin / HARNESS).write_text(HARNESS_TURN_UNTIL_STOPPED_OR_EVAL_TURN_SECONDS)
        (self.bin / HARNESS).chmod(0o755)
        self.repo = self.tmp / 'user-repo'
        self.driver = self.repo / 'adapters' / HOST / 'driver'
        self.asks = []
        self.addCleanup(self.stop_scripted_runs)

    def wd(self, *args, stdin='', check=None):
        p = subprocess.run([sys.executable, '-I', str(SCRIPT), *map(str, args)], input=stdin, env=self.env,
                           capture_output=True, text=True, timeout=120, cwd=self.tmp)
        for text in (p.stdout, p.stderr):
            self.assertNotIn(t.SECRET, text)
        if check is not None:
            self.assertEqual(p.returncode, check, p.stdout + p.stderr)
        return p

    def ask(self, operation, user, *step):
        p = self.wd('ask', '--state', self.state, '--operation', operation, *step, '--effect',
                    'cost money and start a machine')
        self.asks.append(p.stdout.strip())
        if p.returncode:
            return None
        self.reply(user[operation], 'reply', '--state', self.state, check=0)
        return 'ask-%d' % len(self.saved()['asks'])

    def asked(self, operation, user):
        return ['--asked', self.ask(operation, user) or 'ask-0']

    def answered_yes(self, ask_id):
        return ask_id is not None and self.saved()['asks'][-1]['answer'] == 'yes'

    def driver_call(self, word, request, **env):
        p = subprocess.run([str(self.driver), word], input=json.dumps(request), capture_output=True, text=True,
                           env=dict(self.env, **env), timeout=60)
        return json.loads(p.stdout)

    def request(self):
        return {'repository': 'example-user/%s-driver-kit' % HOST, 'ticket': 7, 'skill': 'build-ticket',
                'harness': HARNESS, 'model': 'example-model'}

    def session(self, skip=(), user=None):
        user = dict(YES, **(user or {}))
        self.paste_and_grill(skip)
        self.write(skip, user)
        self.prove(skip, user)
        return self.ship_and_share(user)

    def paste_and_grill(self, skip):
        if 'timer' not in skip:
            self.wd('begin', '--state', self.state, check=0)
            self.shift_paste(GRILL_SECONDS)
        self.wd('host', '--state', self.state, '--host', HOST, '--costly', 'yes')

    def write(self, skip, user):
        self.wd('copy', '--state', self.state, '--openwiz', t.OPENWIZ, '--into', self.repo, '--login', 'machine')
        if self.driver.exists():
            text = self.driver.read_text().replace("HOST = 'template'", "HOST = '%s'" % HOST)
            self.driver.write_text(text.replace('FIRST_TURN_CHECK = False', 'FIRST_TURN_CHECK = True'))
        ask_id = None if 'safety-ask' in skip else self.ask('host', user, '--step', 'start one run of %s' % HARNESS)
        if not self.answered_yes(ask_id):
            return
        live, fixture = self.tmp / 'live.json', self.tmp / 'fixture.json'
        answer = self.driver_call('start', self.request())
        live.write_text(json.dumps(answer))
        self.wd('started', 'run', '--state', self.state, '--driver', self.driver, '--run', answer['run'], check=0)
        fixture.write_text('{"run": "run-000000000000"}')
        if 'live-shape' not in skip:
            self.wd('lesson', 'live-shape', '--state', self.state, '--live', live, '--fixture', fixture)

    def prove(self, skip, user):
        self.env.update(FAKE_KIT_STARTS='1', FAKE_KIT_EXIT='0', FAKE_KIT_OUT=str(self.tmp / 'kit.out'),
                        FAKE_KIT_ARGV=str(self.tmp / 'kit.argv'))
        (self.tmp / 'kit.out').write_text(t.PASS5)
        kit = [] if 'safety-ask' in skip else self.asked('kit', user)
        self.wd('kit', '--state', self.state, '--openwiz', t.OPENWIZ, '--driver', self.driver, '--repo',
                'example-user/%s-driver-kit' % HOST, '--ticket', 7, '--harness', HARNESS, '--model', 'example-model',
                *kit)
        if 'wake-after-turn' not in skip and self.driver.exists():
            run = self.driver_call('start', self.request(), EVAL_TURN_SECONDS='0')['run']
            self.wd('started', 'run', '--state', self.state, '--driver', self.driver, '--run', run, check=0)
            ended = self.turn_ended(run)
            woke = self.driver_call('wake', {'run': run}).get('woke') is True
            self.wd('lesson', 'wake-after-turn', '--state', self.state, '--turn-ended', 'yes' if ended else 'no',
                    '--wake', 'answered' if woke else 'error', '--note-edited', 'yes', '--second-note', 'no')
        if 'expired-login' not in skip:
            login = [] if 'safety-ask' in skip else self.asked('expired-login', user)
            self.wd('lesson', 'expired-login', '--state', self.state, '--driver', self.driver, '--harness', HARNESS,
                    *login)

    def ship_and_share(self, user):
        self.wd('stop-all', '--state', self.state)
        report = self.wd('report', '--state', self.state, '--pr', PR).stdout
        offer = self.wd('share', 'offer', '--state', self.state)
        if offer.returncode == 0:
            self.reply(user['share'], 'share', 'reply', '--state', self.state)
        return report, offer

    def run_pids(self):
        folder = Path(self.env['OPENWIZ_EXAMPLEHOST_STATE'])
        return [int(p.read_text()) for p in folder.iterdir()] if folder.is_dir() else []

    def turn_ended(self, run):
        pid = int((Path(self.env['OPENWIZ_EXAMPLEHOST_STATE']) / run).read_text())
        deadline = time.monotonic() + 10
        while t.alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        return not t.alive(pid)

    def posts(self):
        return [c for c in self.gh_calls() if c['argv'][:2] == ['issue', 'comment']]

    def stop_scripted_runs(self):
        for pid in self.run_pids():
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                pass

    def fresh(self):
        self.doCleanups()
        self.setUp()


class EndToEnd(Eval):
    def test_paste_to_five_of_five_asks_stops_and_shares_on_yes(self):
        report, offer = self.session()
        lines = report.split('\n')
        self.assertEqual(lines[0], 'Your examplehost driver passed 5 of 5 in %s.' % REPORTED_TIME)
        self.assertEqual(lines[1], 'Kit: version pass, start pass, wake pass, stop pass, token pass')
        self.assertEqual(lines[2], 'Live lessons: live-shape pass, wake-after-turn pass, expired-login pass')
        self.assertEqual(lines[3], 'Stopped: everything it started (3)')
        self.assertEqual(lines[4], 'Pull request: ' + PR)
        self.assertEqual([a.split(':')[0] for a in self.asks],
                         ['Before I start one run of exampleagent on examplehost',
                          'Before I run the driver kit on examplehost',
                          'Before I run the expired sign-in check with your driver on examplehost'])
        self.assertTrue((self.tmp / 'kit.argv').exists())
        self.assertEqual(len(self.run_pids()), 3)
        self.assertFalse(any(t.alive(pid) for pid in self.run_pids()))
        share = 'examplehost: 5 of 5 in ' + REPORTED_TIME
        self.assertIn('\n\n%s\n\n' % share, offer.stdout)
        self.assertEqual([(c['argv'], c['stdin']) for c in self.posts()],
                         [(['issue', 'comment', '1966', '--repo', 'openwizdev/OpenWiz', '--body-file', '-'], share)])


class Red(Eval):
    def test_a_skipped_safety_ask_runs_no_costly_step(self):
        report, offer = self.session(skip={'safety-ask'})
        self.assertIn('not passing yet', report.split('\n')[0])
        self.assertFalse((self.tmp / 'kit.argv').exists(), 'the kit ran without an ask')
        self.assertIn('expired-login not run', report)
        self.assertNotEqual(offer.returncode, 0)
        self.assertEqual(self.posts(), [])

    def test_a_no_to_the_ask_skips_the_step(self):
        report, _ = self.session(user={'kit': 'hmm, maybe later'})
        self.assertIn('Kit: version not run, start not run', report)
        self.assertFalse((self.tmp / 'kit.argv').exists())
        self.assertIn('not passing yet', report)

    def test_each_skipped_live_lesson_keeps_it_from_passing(self):
        for lesson in ('live-shape', 'wake-after-turn', 'expired-login'):
            with self.subTest(lesson):
                self.fresh()
                report, offer = self.session(skip={lesson})
                self.assertIn('not passing yet', report.split('\n')[0])
                self.assertIn('%s not run' % lesson, report)
                self.assertNotEqual(offer.returncode, 0)
                self.assertEqual(self.posts(), [])

    def test_no_clock_at_paste_gives_no_report(self):
        report, offer = self.session(skip={'timer'})
        self.assertNotIn('Your examplehost driver', report)
        self.assertIn('run `begin` at paste first', report)
        self.assertFalse((self.tmp / 'kit.argv').exists())
        self.assertNotEqual(offer.returncode, 0)

    def test_a_declined_share_posts_nothing(self):
        for answer in ('no', 'no thanks, keep it private', 'maybe'):
            with self.subTest(answer):
                self.fresh()
                report, offer = self.session(user={'share': answer})
                self.assertIn('passed 5 of 5', report)
                self.assertEqual(offer.returncode, 0)
                self.assertEqual(self.posts(), [])
                self.assertFalse(any(t.alive(pid) for pid in self.run_pids()))


if __name__ == '__main__':
    unittest.main()
