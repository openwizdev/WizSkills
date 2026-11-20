#!/usr/bin/env python3
"""host.py (#1371): builders start, wake and stop through the chosen host's driver.

python3 -I skills/launch-fleet/scripts/test-host.py

Each case is a synthetic project checkout with `docs/agents/host.md`, an
adapters folder of synthetic drivers (fixtures/driver.py, one per host) that
log every call, and a private runs file. Nothing reaches GitHub or a host.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
REPO = 'synthetic-owner/synthetic-repo'


class Project:
    """A synthetic checkout, its adapters folder and its private runs file."""

    def __init__(self, test, setting='Host: local\n', hosts=('local', 'cloudroom')):
        self.dir = Path(tempfile.mkdtemp())
        test.addCleanup(subprocess.run, ['rm', '-rf', str(self.dir)])
        (self.dir / 'repo/docs/agents').mkdir(parents=True)
        if setting is not None:
            self.set(setting)
        for host in hosts:
            folder = self.dir / 'adapters' / host
            folder.mkdir(parents=True)
            (folder / 'driver').write_text('#!/bin/sh\nFAKE_DRIVER_HOST=%s exec "%s" -I "%s" "$@"\n'
                                           % (host, sys.executable, HERE / 'fixtures/driver.py'))
            (folder / 'driver').chmod(0o755)
        self.log = self.dir / 'driver.log'
        self.runs = self.dir / 'private/runs.json'
        self.runs.parent.mkdir()
        self.env = dict(os.environ, OPENWIZ_ADAPTERS=str(self.dir / 'adapters'), LAUNCH_FLEET_RUNS=str(self.runs),
                        FAKE_DRIVER_LOG=str(self.log))

    def set(self, setting):
        (self.dir / 'repo/docs/agents/host.md').write_text('# Host\n\nWhere this project\'s agents run.\n\n' + setting)

    def host(self, *args, **env):
        r = subprocess.run([sys.executable, '-I', str(HERE / 'host.py'), *map(str, args)], cwd=self.dir / 'repo',
                           capture_output=True, text=True, timeout=60, env=dict(self.env, **env))
        return r.returncode, r.stdout.strip(), r.stderr.strip()

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def saved(self):
        return json.loads(self.runs.read_text()) if self.runs.exists() else None


class Host(unittest.TestCase):
    def test_start_goes_through_the_chosen_driver_and_saves_its_run(self):
        p = Project(self)
        self.assertEqual(p.host('which'), (0, 'host: local', ''))
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'claude-opus-5-5'), (0, 'started #7 on local', ''))
        self.assertEqual(p.calls(), [{'host': 'local', 'command': 'start', 'input': {
            'repository': REPO, 'ticket': 7, 'skill': 'build-ticket', 'harness': 'claude', 'model': 'claude-opus-5-5'}}])
        self.assertEqual(p.saved(), {'repo': REPO, 'runs': {'7': {'host': 'local', 'run': 'local-run-7'}}})
        self.assertEqual(p.runs.stat().st_mode & 0o777, 0o600)
        self.assertEqual(p.host('wake', REPO, 7), (0, 'woke #7 on local', ''))
        self.assertEqual(p.host('stop', REPO, 7), (0, 'stopped #7 on local', ''))
        self.assertEqual([(c['host'], c['command'], c['input']) for c in p.calls()[1:]],
                         [('local', 'wake', {'run': 'local-run-7'}), ('local', 'stop', {'run': 'local-run-7'})])
        self.assertEqual(p.saved()['runs'], {'7': {'host': 'local', 'run': 'local-run-7', 'stopped': True}})
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'claude-opus-5-5'), (0, 'started #7 on local', ''))
        self.assertEqual(p.saved()['runs'], {'7': {'host': 'local', 'run': 'local-run-7'}})

    def test_changing_the_setting_switches_the_driver_and_each_run_keeps_its_own(self):
        p = Project(self)
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'claude-opus-5-5')[0], 0)
        p.set('Host: cloudroom\n')
        self.assertEqual(p.host('which'), (0, 'host: cloudroom', ''))
        self.assertEqual(p.host('start', REPO, 8, 'codex', 'gpt-6.1-sol'), (0, 'started #8 on cloudroom', ''))
        self.assertEqual(p.host('wake', REPO, 7), (0, 'woke #7 on local', ''))
        self.assertEqual(p.host('wake', REPO, 8), (0, 'woke #8 on cloudroom', ''))
        self.assertEqual([(c['host'], c['command'], c['input'].get('run') or c['input']['ticket']) for c in p.calls()],
                         [('local', 'start', 7), ('cloudroom', 'start', 8),
                          ('local', 'wake', 'local-run-7'), ('cloudroom', 'wake', 'cloudroom-run-8')])
        self.assertEqual(p.saved()['runs'], {'7': {'host': 'local', 'run': 'local-run-7'},
                                             '8': {'host': 'cloudroom', 'run': 'cloudroom-run-8'}})

    def test_a_ticket_never_gets_a_second_run(self):
        p = Project(self)
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'claude-opus-5-5')[0], 0)
        p.set('Host: cloudroom\n')
        code, out, _ = p.host('start', REPO, 7, 'claude', 'claude-opus-5-5')
        self.assertEqual((code, out), (1, 'refused: #7 already has a run on local; wake or stop it instead'))
        self.assertEqual(len(p.calls()), 1)

    def test_a_driver_refusal_or_an_unreadable_answer_saves_no_run(self):
        p = Project(self)
        code, out, _ = p.host('start', REPO, 7, 'claude', 'claude-opus-5-5', FAKE_DRIVER_MODE='refuse')
        self.assertEqual((code, out), (1, 'refused: the synthetic harness is not signed in; '
                                          'next: sign in to the harness, then start again'))
        self.assertIsNone(p.saved())
        code, out, _ = p.host('start', REPO, 7, 'claude', 'claude-opus-5-5', FAKE_DRIVER_MODE='garbage')
        self.assertEqual((code, out), (1, 'unknown: the local driver answered no run; a run may exist, '
                                          'so reconcile before any retry'))
        self.assertIsNone(p.saved())

    def test_no_run_or_no_setting_leaves_the_room_cli_route(self):
        p = Project(self, setting=None)
        self.assertEqual(p.host('which'), (0, 'host: none', ''))
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'claude-opus-5-5')[:2],
                         (1, 'refused: no host is chosen in docs/agents/host.md'))
        self.assertEqual(p.host('wake', REPO, 9)[:2], (1, 'no run: #9 was not started through a driver'))
        self.assertEqual(p.calls(), [])

    def test_a_broken_setting_or_driver_starts_nothing(self):
        cases = {'two lines': 'Host: local\nHost: cloudroom\n', 'bad name': 'Host: ../local\n',
                 'no driver': 'Host: boat\n', 'no line': 'Somewhere: local\n'}
        for name, setting in cases.items():
            with self.subTest(name):
                p = Project(self, setting=setting)
                code, out, err = p.host('start', REPO, 7, 'claude', 'claude-opus-5-5')
                self.assertEqual((code, out), (2, ''), err)
                self.assertTrue(err.startswith('host.py: '), err)
                self.assertEqual(p.calls(), [])
                self.assertIsNone(p.saved())
        p = Project(self)
        code, _, err = p.host('start', REPO, 7, 'claude', 'claude-opus-5-5', OPENWIZ_ADAPTERS='')
        self.assertEqual(code, 2)
        self.assertIn('OPENWIZ_ADAPTERS', err)
        self.assertEqual(p.calls(), [])


if __name__ == '__main__':
    unittest.main()
