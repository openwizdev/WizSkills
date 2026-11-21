"""write-driver's end-to-end eval (WD3): a scripted agent follows SKILL.md's steps, in order, through the skill's
script, and a scripted user answers each ask, against the synthetic template host and fake `gh` that the skill's
own tests use. No model, no network, no real host: it proves the scripts end to end, not that a model follows
SKILL.md.

    python3 -I skills/write-driver/tests/test_eval.py

Linux only, as test_write_driver.py: the expired-login probe needs Landlock and the stop checks read /proc.
WRITE_DRIVER_EVAL_SCRIPT runs the eval against another copy of write_driver.py (a planted mutant, for red runs).
"""
import json
import os
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_write_driver as t  # noqa: E402  the skill's own fakes and helpers, reused

SCRIPT = Path(os.environ.get('WRITE_DRIVER_EVAL_SCRIPT') or t.SCRIPT)
HOST, HARNESS, PR = 'examplehost', 'exampleagent', 'https://github.com/example-user/examplehost-driver/pull/1'
YES = {'kit': 'yes', 'expired-login': 'yes', 'host': 'yes', 'share': 'yes'}
# The scripted harness: the kit's run keeps working until it is stopped; a wake-after-turn run's first turn ends.
AGENT = '#!/bin/sh\nexec sleep "${EVAL_TURN_SECONDS:-300}"\n'


class Eval(t.Base):
    """One scripted session per test: paste to share, on a host whose steps cost money."""

    def setUp(self):
        super().setUp()
        (self.bin / HARNESS).write_text(AGENT)
        (self.bin / HARNESS).chmod(0o755)
        self.said = []  # every line the agent says to the user, in order
        self.repo = self.tmp / 'user-repo'
        self.driver = self.repo / 'adapters' / HOST / 'driver'
        self.env['OPENWIZ_EXAMPLEHOST_STATE'] = str(self.tmp / 'driver-state')

    def wd(self, *args, stdin='', check=None):
        p = subprocess.run([sys.executable, '-I', str(SCRIPT), *map(str, args)], input=stdin, env=self.env,
                           capture_output=True, text=True, timeout=120, cwd=self.tmp)
        for text in (p.stdout, p.stderr):
            self.assertNotIn(t.SECRET, text)
        self.said.append(p.stdout + p.stderr)
        if check is not None:
            self.assertEqual(p.returncode, check, p.stdout + p.stderr)
        return p

    def asked(self, operation, user, **step):
        """Say the ask, end the turn, take the scripted user's next message; return the ask's id."""
        extra = ['--step', step['step']] if step else []
        p = self.wd('ask', '--state', self.state, '--operation', operation, *extra, '--effect',
                    'cost money and start a machine')
        if p.returncode:  # no run to ask in: the faulty agent goes on regardless
            return p.stdout.strip(), None
        self.reply(user[operation], 'reply', '--state', self.state, check=0)
        return p.stdout.strip(), 'ask-%d' % len(self.saved()['asks'])

    def driver_call(self, word, request, **env):
        p = subprocess.run([str(self.driver), word], input=json.dumps(request), capture_output=True, text=True,
                           env=dict(self.env, **env), timeout=60)
        return json.loads(p.stdout)

    def session(self, skip=(), user=YES):
        """SKILL.md's steps 1 to 5, as an agent that follows it; `skip` names the steps a faulty agent leaves out."""
        user = dict(YES, **user) if user is not YES else user
        self.asks = []
        if 'timer' not in skip:
            self.wd('begin', '--state', self.state, check=0)
            self.shift_paste(22 * 60 + 30)  # the user reads and answers the grill: 22.5 minutes from paste
        self.wd('host', '--state', self.state, '--host', HOST, '--costly', 'yes')
        # 2. Write: the template copy, then the adaptation SKILL.md's step 2.3 makes (its host, its first-turn check).
        self.wd('copy', '--state', self.state, '--openwiz', t.OPENWIZ, '--into', self.repo, '--login', 'machine')
        if self.driver.exists():
            text = self.driver.read_text().replace("HOST = 'template'", "HOST = '%s'" % HOST)
            self.driver.write_text(text.replace('FIRST_TURN_CHECK = False', 'FIRST_TURN_CHECK = True'))
        live = self.tmp / 'live.json'
        fixture = self.tmp / 'fixture.json'
        fixture.write_text('{"run": "run-000000000000"}')
        if 'safety-ask' in skip:
            ask_id = None
        else:
            text, ask_id = self.asked('host', user, step='start one run of %s' % HARNESS)
            self.asks.append(text)
        if ask_id and self.saved()['asks'][-1]['answer'] == 'yes':  # a host step it runs itself only after a yes
            live.write_text(json.dumps(self.driver_call('start', self.request())))
            self.record_runs(live)
        if 'live-shape' not in skip and live.exists():
            self.wd('lesson', 'live-shape', '--state', self.state, '--live', live, '--fixture', fixture)
        # 3. Prove: the kit (it starts one run of its own and leaves it to stop-all), then the two other lessons.
        self.env.update(FAKE_KIT_STARTS='1', FAKE_KIT_EXIT='0', FAKE_KIT_OUT=str(self.tmp / 'kit.out'),
                        FAKE_KIT_ARGV=str(self.tmp / 'kit.argv'))
        (self.tmp / 'kit.out').write_text(t.PASS5)
        kit = [] if 'safety-ask' in skip else ['--asked', self.ask_for('kit', user)]
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
            login = [] if 'safety-ask' in skip else ['--asked', self.ask_for('expired-login', user)]
            self.wd('lesson', 'expired-login', '--state', self.state, '--driver', self.driver, '--harness', HARNESS,
                    *login)
        # 4. Ship and report; 5. share, only on yes.
        self.wd('stop-all', '--state', self.state)
        report = self.wd('report', '--state', self.state, '--pr', PR).stdout
        offer = self.wd('share', 'offer', '--state', self.state)
        if offer.returncode == 0:
            self.reply(user['share'], 'share', 'reply', '--state', self.state)
        return report, offer

    def ask_for(self, operation, user):
        text, ask_id = self.asked(operation, user)
        self.asks.append(text)
        return ask_id or 'ask-0'

    def request(self):
        return {'repository': 'example-user/%s-driver-kit' % HOST, 'ticket': 7, 'skill': 'build-ticket',
                'harness': HARNESS, 'model': 'example-model'}

    def record_runs(self, live):
        run = json.loads(live.read_text()).get('run')
        if run:
            self.wd('started', 'run', '--state', self.state, '--driver', self.driver, '--run', run, check=0)

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

    def tearDown(self):
        for pid in self.run_pids():  # never leave a scripted run behind, even when a test fails
            try:
                os.killpg(pid, 9)
            except OSError:
                pass


class EndToEnd(Eval):
    def test_paste_to_five_of_five_asks_stops_and_shares_on_yes(self):
        # catches: the scripts not reaching 5 of 5 on the template host, a report without its time or pull
        # request, a costly step run unasked, a lesson not run, a run left going, or a share that differs from
        # its preview or goes anywhere but #1966
        report, offer = self.session()
        lines = report.split('\n')
        self.assertEqual(lines[0], 'Your examplehost driver passed 5 of 5 in 23 minutes.')
        self.assertEqual(lines[1], 'Kit: version pass, start pass, wake pass, stop pass, token pass')
        self.assertEqual(lines[2], 'Live lessons: live-shape pass, wake-after-turn pass, expired-login pass')
        self.assertEqual(lines[3], 'Stopped: everything it started (3)')
        self.assertEqual(lines[4], 'Pull request: ' + PR)
        self.assertEqual([a.split(':')[0] for a in self.asks],
                         ['Before I start one run of exampleagent on examplehost',
                          'Before I run the driver kit on examplehost',
                          'Before I run the expired sign-in check with your driver on examplehost'])
        self.assertTrue((self.tmp / 'kit.argv').exists())
        self.assertFalse(any(t.alive(pid) for pid in self.run_pids()))
        self.assertEqual(len(self.run_pids()), 3)
        share = 'examplehost: 5 of 5 in 23 minutes'
        self.assertIn('\n\n%s\n\n' % share, offer.stdout)
        self.assertEqual([(c['argv'], c['stdin']) for c in self.posts()],
                         [(['issue', 'comment', '1966', '--repo', 'openwizdev/OpenWiz', '--body-file', '-'], share)])


class Red(Eval):
    """Each faulty session must not read as passing, and must leave the user's world as the skill promises."""

    def test_a_skipped_safety_ask_runs_no_costly_step(self):
        # catches: a costly host's kit or expired-login probe running with no ask answered yes
        report, offer = self.session(skip={'safety-ask'})
        self.assertIn('not passing yet', report.split('\n')[0])
        self.assertFalse((self.tmp / 'kit.argv').exists(), 'the kit ran without an ask')
        self.assertIn('expired-login not run', report)
        self.assertNotEqual(offer.returncode, 0)
        self.assertEqual(self.posts(), [])

    def test_a_no_to_the_ask_skips_the_step(self):
        # catches: a step that goes ahead on anything but a plain yes
        report, _ = self.session(user={'kit': 'hmm, maybe later'})
        self.assertIn('Kit: version not run, start not run', report)
        self.assertFalse((self.tmp / 'kit.argv').exists())
        self.assertIn('not passing yet', report)

    def test_each_skipped_live_lesson_keeps_it_from_passing(self):
        # catches: a report that reads passing, or offers a share, without all three live lessons
        for lesson in ('live-shape', 'wake-after-turn', 'expired-login'):
            with self.subTest(lesson):
                self.setUp()
                report, offer = self.session(skip={lesson})
                self.assertIn('not passing yet', report.split('\n')[0])
                self.assertIn('%s not run' % lesson, report)
                self.assertNotEqual(offer.returncode, 0)
                self.assertEqual(self.posts(), [])
                self.tearDown()

    def test_no_clock_at_paste_gives_no_report(self):
        # catches: a run that reports a time (or passes) with no clock started at paste
        report, offer = self.session(skip={'timer'})
        self.assertNotIn('Your examplehost driver', report)
        self.assertIn('run `begin` at paste first', report)
        self.assertFalse((self.tmp / 'kit.argv').exists())
        self.assertNotEqual(offer.returncode, 0)

    def test_a_declined_share_posts_nothing(self):
        # catches: a share posted on a no, or on anything but a plain yes
        for answer in ('no', 'no thanks, keep it private', 'maybe'):
            with self.subTest(answer):
                self.setUp()
                report, offer = self.session(user={'share': answer})
                self.assertIn('passed 5 of 5', report)
                self.assertEqual(offer.returncode, 0)
                self.assertEqual(self.posts(), [])
                self.assertFalse(any(t.alive(pid) for pid in self.run_pids()))
                self.tearDown()


if __name__ == '__main__':
    unittest.main()
