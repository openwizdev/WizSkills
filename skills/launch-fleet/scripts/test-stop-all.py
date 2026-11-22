#!/usr/bin/env python3
import fcntl
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
REPO = 'synthetic-owner/synthetic-repo'
SPEC = '7'
AGENT_CLIS = ('claude codex cursor-agent agent pi opencode copilot goose gemini kimi qwen cline kilo crush vibe '
              'auggie kiro-cli junie amp agy oz sculpt hermes acpx droid').split()
MANAGER = r"""
import sys
from pathlib import Path
name, *args = sys.argv[1:]
table = Path.home() / 'crontab'
if name == 'crontab' and args == ['-l']:
    print(table.read_text(), end='')
elif name == 'crontab' and args == ['-']:
    table.write_text(sys.stdin.read())
elif name == 'systemctl':
    sys.exit(1)
"""
REFUSER = ('#!/bin/sh\ncat > /dev/null\nprintf \'{"host": "refuser", "command": "%s"}\\n\' "$1" >> "$FAKE_DRIVER_LOG"\n'
           'echo \'{"error": "the synthetic host is down", "next": "try again later"}\'\nexit 1\n')
BROKEN = ('#!/bin/sh\ncat > /dev/null\nprintf \'{"host": "broken", "command": "%s"}\\n\' "$1" >> "$FAKE_DRIVER_LOG"\n'
          'echo \'stopped, probably\'\nexit 0\n')


class Home:
    def __init__(self, test, runs):
        self.test = test
        self.dir = Path(tempfile.mkdtemp())
        test.addCleanup(shutil.rmtree, self.dir, True)
        self.stubs, self.bin, self.adapters = self.dir / 'stubs', self.dir / 'bin', self.dir / 'adapters'
        for folder in (self.stubs, self.bin, self.dir / 'private', self.dir / 'checkout'):
            folder.mkdir()
        self.cli_log, self.log = self.dir / 'agent-cli.log', self.dir / 'driver.log'
        self.log.touch()
        for name in AGENT_CLIS:
            self.program(self.stubs / name, 'echo "%s $*" >> %s\necho "refused: real agent CLI blocked" >&2\nexit 1'
                         % (name, shlex.quote(str(self.cli_log))))
        for name in ('crontab', 'systemctl', 'launchctl'):
            self.program(self.bin / name, 'exec %s -I -c %s %s "$@"' % (shlex.quote(sys.executable),
                                                                     shlex.quote(MANAGER), name))
        (self.dir / 'crontab').write_text('15 3 * * * /bin/true\n')
        for host in ('local', 'cloudroom'):
            self.program(self.adapters / host / 'driver', 'FAKE_DRIVER_HOST=%s exec %s -I %s "$@"'
                         % (host, shlex.quote(sys.executable), shlex.quote(str(HERE / 'fixtures/driver.py'))))
        for host, script in (('refuser', REFUSER), ('broken', BROKEN)):
            self.program(self.adapters / host / 'driver', script[len('#!/bin/sh\n'):])
        self.runs = self.dir / 'private/runs.json'
        if runs is not None:
            self.runs.write_text(json.dumps({'repo': REPO, 'runs': runs}))
            self.runs.chmod(0o600)
        self.env = {'HOME': str(self.dir), 'PATH': os.pathsep.join([str(self.stubs), str(self.bin), os.defpath]),
                    'OPENWIZ_ADAPTERS': str(self.adapters), 'LAUNCH_FLEET_RUNS': str(self.runs),
                    'FAKE_DRIVER_LOG': str(self.log), 'LC_ALL': 'C'}

    def program(self, path, script):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#!/bin/sh\n' + script + '\n')
        path.chmod(0o700)

    def run(self, script, *args):
        return subprocess.run([sys.executable, '-I', str(HERE / script), *args], cwd=self.dir / 'checkout',
                              env=self.env, capture_output=True, text=True, timeout=60)

    def install_heartbeat(self):
        r = self.run('heartbeat.py', 'install', REPO, SPEC, 'codex', 'synthetic-model', '--yes')
        self.test.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.test.assertEqual(self.heartbeat(), 'heartbeat: active (cron)')

    def heartbeat(self):
        r = self.run('heartbeat.py', 'status', REPO, SPEC)
        self.test.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout.splitlines()[0]

    def stop_all(self, *args, expected):
        r = self.run('stop-all.py', REPO, SPEC, *args)
        self.test.assertEqual(r.returncode, expected, r.stdout + r.stderr)
        return r.stdout.splitlines()

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def saved(self):
        return json.loads(self.runs.read_text())['runs']

    def no_agent_cli(self):
        self.test.assertFalse(self.cli_log.exists(), 'an agent CLI was started')


LIVE = {'11': {'host': 'local', 'run': 'local-run-11'}, '12': {'host': 'cloudroom', 'run': 'cloudroom-run-12'},
        '13': {'host': 'local', 'run': 'local-run-13', 'stopped': True}}
MIXED = {'21': {'host': 'refuser', 'run': 'refuser-run-21'}, '22': {'host': 'broken', 'run': 'broken-run-22'},
         '23': {'host': 'gone', 'run': 'gone-run-23'}, '24': {'host': 'local', 'run': 'local-run-24'}}


class StopAll(unittest.TestCase):
    def test_every_live_run_is_stopped_once_and_the_heartbeat_paused(self):
        home = Home(self, LIVE)
        home.install_heartbeat()
        out = home.stop_all(expected=0)
        self.assertEqual(out, ['heartbeat: paused', '#11 on local: stopped', '#12 on cloudroom: stopped',
                               'stop-all: 2 stopped, 0 not stopped'])
        self.assertEqual(home.calls(), [
            {'host': 'local', 'command': 'stop', 'input': {'run': 'local-run-11'}},
            {'host': 'cloudroom', 'command': 'stop', 'input': {'run': 'cloudroom-run-12'}}])
        self.assertEqual(home.heartbeat(), 'heartbeat: paused (cron)')
        self.assertEqual((home.dir / 'crontab').read_text(), '15 3 * * * /bin/true\n')
        self.assertEqual(home.saved(), {n: dict(run, stopped=True) for n, run in LIVE.items()})
        self.assertEqual(home.stop_all(expected=0), ['heartbeat: paused', 'stop-all: no live runs'])
        self.assertEqual(len(home.calls()), 2)
        home.no_agent_cli()

    def test_a_refused_failed_or_missing_driver_is_reported_and_the_others_still_stop(self):
        home = Home(self, MIXED)
        home.install_heartbeat()
        out = home.stop_all(expected=1)
        self.assertEqual(out, [
            'heartbeat: paused',
            '#21 on refuser: not stopped: the driver refused stop (refused: the synthetic host is down; '
            'next: try again later)',
            '#22 on broken: not stopped: the driver failed stop (unknown: the broken driver answered no run; a run '
            'may exist, so reconcile before any retry)',
            '#23 on gone: not stopped: the driver is missing',
            '#24 on local: stopped',
            'stop-all: 1 stopped, 3 not stopped'])
        self.assertEqual([(c['host'], c['command']) for c in home.calls()],
                         [('refuser', 'stop'), ('broken', 'stop'), ('local', 'stop')])
        self.assertEqual(home.saved(), dict(MIXED, **{'24': dict(MIXED['24'], stopped=True)}))
        self.assertEqual(home.heartbeat(), 'heartbeat: paused (cron)')
        home.no_agent_cli()

    def test_dry_run_stops_nothing_and_prints_the_same_list(self):
        home = Home(self, MIXED)
        home.install_heartbeat()
        before = home.runs.read_text()
        out = home.stop_all('--dry-run', expected=0)
        self.assertEqual(out, ['heartbeat: would pause', '#21 on refuser: would stop', '#22 on broken: would stop',
                               '#23 on gone: would stop', '#24 on local: would stop',
                               'stop-all: dry run, 4 live runs, nothing stopped'])
        self.assertEqual(home.calls(), [])
        self.assertEqual(home.runs.read_text(), before)
        self.assertEqual(home.heartbeat(), 'heartbeat: active (cron)')
        real = home.stop_all(expected=1)
        self.assertEqual([line.split(': ')[0] for line in out[1:-1]], [line.split(': ')[0] for line in real[1:-1]])
        home.no_agent_cli()

    def test_no_live_runs_prints_that_and_exits_0(self):
        for runs in (None, {}, {'13': LIVE['13']}):
            with self.subTest(runs=runs):
                home = Home(self, runs)
                self.assertEqual(home.stop_all(expected=0), ['heartbeat: not installed', 'stop-all: no live runs'])
                self.assertEqual(home.stop_all('--dry-run', expected=0),
                                 ['heartbeat: not installed', 'stop-all: no live runs'])
                self.assertEqual(home.calls(), [])
                home.no_agent_cli()

    def test_a_heartbeat_that_will_not_pause_fails_the_command_but_the_runs_still_stop(self):
        home = Home(self, LIVE)
        home.install_heartbeat()
        state = next((home.dir / '.local/state/openwiz-heartbeat').glob('openwiz-heartbeat-*'))
        running_tick = os.open(state, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, running_tick)
        fcntl.flock(running_tick, fcntl.LOCK_EX | fcntl.LOCK_NB)
        out = home.stop_all(expected=1)
        self.assertEqual(out, ['heartbeat: not paused (heartbeat: a heartbeat operation is already running)',
                               '#11 on local: stopped', '#12 on cloudroom: stopped',
                               'stop-all: 2 stopped, 0 not stopped'])
        self.assertEqual(len(home.calls()), 2)
        home.no_agent_cli()

    def test_an_unreadable_runs_file_stops_nothing(self):
        for text in ('{"repo": "someone/else", "runs": {}}', 'not json',
                     '{"repo": "%s", "runs": {"11": {"host": "local"}}}' % REPO):
            with self.subTest(text=text):
                home = Home(self, {})
                home.install_heartbeat()
                home.runs.write_text(text)
                r = home.run('stop-all.py', REPO, SPEC)
                self.assertEqual((r.returncode, r.stdout), (2, ''))
                self.assertIn('is not a runs file for %s' % REPO, r.stderr)
                self.assertEqual(home.heartbeat(), 'heartbeat: active (cron)')
                self.assertEqual(home.calls(), [])

    def test_usage(self):
        home = Home(self, {})
        for args in ([], [REPO], ['not-a-repo', SPEC], [REPO, '0'], [REPO, SPEC, '--now']):
            with self.subTest(args=args):
                r = home.run('stop-all.py', *args)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertEqual(r.stdout, '')


if __name__ == '__main__':
    unittest.main()
