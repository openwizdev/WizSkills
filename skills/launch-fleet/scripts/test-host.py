#!/usr/bin/env python3
"""host.py (#1371): builders start, wake and stop through the chosen host's driver; a refused start or
wake is tried twice more, then reported on the ticket once, and a later success clears it (#1446).

python3 -I skills/launch-fleet/scripts/test-host.py

Each case is a synthetic project checkout with `docs/agents/host.md`, an
adapters folder of synthetic drivers (fixtures/driver.py, one per host) that
log every call, a private runs file and a synthetic GitHub (fixtures/fake_github.py on PATH as `gh`).
Nothing reaches GitHub or a host.
"""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent
REPO = 'synthetic-owner/synthetic-repo'


def front_version(text):
    found = re.search(r'''(?m)^version: (["']?)([0-9]+\.[0-9]+\.[0-9]+)\1$''', text)
    return found and found.group(2)


# launch-fleet's own installed version, its SKILL.md front matter, which the status writer
# binds (#1663); the bundle's version can differ from it.
VERSION = front_version((HERE.parent / 'SKILL.md').read_text())
FLEET_MD = ('# Fleet settings\n\n## GitHub identity\n\n| Setting | Value |\n| --- | --- |\n'
            '| Record authors | `openwiz[bot]`, `synthetic-owner` |\n')
MARK = 'launch-fleet: driver start failed'
NEXT = 'sign in to the harness, then start again'


class Project:
    """A synthetic project: a bare origin whose default branch is `trunk`, a fleet checkout cloned from it,
    an adapters folder and a private runs file. set() changes the setting on the default branch only."""

    def __init__(self, test, setting='Host: local\n', hosts=('local', 'cloudroom'), repo=REPO):
        self.dir = Path(tempfile.mkdtemp())
        test.addCleanup(subprocess.run, ['rm', '-rf', str(self.dir)])
        test.addCleanup(subprocess.run, ['chmod', '-R', 'u+w', str(self.dir)])
        self.git_env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1',
                            GIT_AUTHOR_NAME='synthetic', GIT_AUTHOR_EMAIL='synthetic@example.invalid',
                            GIT_COMMITTER_NAME='synthetic', GIT_COMMITTER_EMAIL='synthetic@example.invalid')
        self.git('init', '-q', '--bare', '-b', 'trunk', str(self.dir / 'origin.git'))
        self.git('clone', '-q', str(self.dir / 'origin.git'), str(self.dir / 'writer'))
        (self.dir / 'writer/docs/agents').mkdir(parents=True)
        (self.dir / 'writer/README.md').write_text('synthetic\n')
        self.git('-C', str(self.dir / 'writer'), 'add', '-A')
        self.git('-C', str(self.dir / 'writer'), 'commit', '-q', '-m', 'start')
        self.git('-C', str(self.dir / 'writer'), 'push', '-q', 'origin', 'trunk')
        if setting is not None:
            self.set(setting)
        self.git('clone', '-q', str(self.dir / 'origin.git'), str(self.dir / 'repo'))
        for host in hosts:
            folder = self.dir / 'adapters' / host
            folder.mkdir(parents=True)
            (folder / 'driver').write_text('#!/bin/sh\nFAKE_DRIVER_HOST=%s exec "%s" -I "%s" "$@"\n'
                                           % (host, sys.executable, HERE / 'fixtures/driver.py'))
            (folder / 'driver').chmod(0o755)
        self.log = self.dir / 'driver.log'
        self.runs = self.dir / 'private/runs.json'
        self.runs.parent.mkdir()
        bin_dir = self.dir / 'bin'
        bin_dir.mkdir()
        (bin_dir / 'gh').write_text('#!/bin/sh\nexec "%s" -I "%s" "$@"\n' % (sys.executable, HERE / 'fixtures/fake_github.py'))
        (bin_dir / 'gh').chmod(0o755)
        self.world = self.dir / 'world.json'
        self.world.write_text(json.dumps({'repo': repo, 'me': 'openwiz[bot]', 'fleet_md': FLEET_MD, 'next_id': 5000,
                                          'comments': {}, 'writes': [], 'faults': {}}))
        self.env = dict(self.git_env, OPENWIZ_ADAPTERS=str(self.dir / 'adapters'), LAUNCH_FLEET_RUNS=str(self.runs),
                        FAKE_DRIVER_LOG=str(self.log), PATH='%s:%s' % (bin_dir, os.environ['PATH']),
                        FAKE_WORLD=str(self.world), LAUNCH_FLEET_HARNESS='Claude Code',
                        LAUNCH_FLEET_MODEL='Opus 5.5 Medium', LAUNCH_FLEET_SKILLS='launch-fleet@' + VERSION)

    def git(self, *args):
        subprocess.run(['git', *args], check=True, env=self.git_env, capture_output=True, timeout=60)

    def set(self, setting):
        """Change the setting on origin's default branch; the fleet checkout keeps what it had."""
        (self.dir / 'writer/docs/agents/host.md').write_text('# Host\n\nWhere this project\'s agents run.\n\n' + setting)
        self.git('-C', str(self.dir / 'writer'), 'add', '-A')
        self.git('-C', str(self.dir / 'writer'), 'commit', '-q', '-m', 'host')
        self.git('-C', str(self.dir / 'writer'), 'push', '-q', 'origin', 'trunk')

    def fleet(self, text):
        (self.dir / 'writer/docs/agents/fleet.md').write_text(text)
        self.git('-C', str(self.dir / 'writer'), 'add', '-A')
        self.git('-C', str(self.dir / 'writer'), 'commit', '-q', '-m', 'fleet')
        self.git('-C', str(self.dir / 'writer'), 'push', '-q', 'origin', 'trunk')

    def host(self, *args, **env):
        r = subprocess.run([sys.executable, '-I', str(HERE / 'host.py'), *map(str, args)], cwd=self.dir / 'repo',
                           capture_output=True, text=True, timeout=60, env=dict(self.env, **env))
        return r.returncode, r.stdout.strip(), r.stderr.strip()

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def saved(self):
        return json.loads(self.runs.read_text()) if self.runs.exists() else None

    def labels(self):
        path = Path(str(self.runs) + '.requesters')
        return json.loads(path.read_text()) if path.exists() else None

    def github(self):
        return json.loads(self.world.read_text())

    def fault(self, **faults):
        world = self.github()
        world['faults'] = faults
        self.world.write_text(json.dumps(world))

    def ticket(self, n=7):
        """#N's comments as GitHub holds them: (first line, the rest) of each, oldest first."""
        return [tuple(c['body'].split('\n', 1)) if '\n' in c['body'] else (c['body'], '')
                for c in self.github()['comments'].get(str(n), [])]

    def fleet_notes(self, n=7):
        """The `state:` of each fleet status note on #N, oldest first."""
        return [next(line[len('state: '):] for line in body.split('\n') if line.startswith('state: '))
                for first, body in self.ticket(n) if first == '<!-- openwiz:status v1 -->' and 'agent: fleet' in body]

    def driver_log(self):
        """The owner-only driver log's entries (#1446, the decision on R3): the driver's own words live only here."""
        log = self.runs.with_name('driver-failures.log')
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def failure(self, command='start', entry=0, n=7):
        """The one failure comment #N should hold: a fixed reason, the exit category and a pointer to a log entry."""
        return (MARK, "The local driver refused to %s this ticket's builder 3 times (exit 1: refused). Its own words "
                      "are kept off this public ticket: the fleet's owner can read them in the private driver log, "
                      "`driver-failures.log` beside `LAUNCH_FLEET_RUNS`, entry %s for #%s."
                % (command, self.driver_log()[entry]['time'], n))

    def failures(self, n=7):
        """The failure comments on #N: each one's first line and text."""
        return [(first, rest.strip()) for first, rest in self.ticket(n) if first.startswith(MARK)]


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
        # R1: the default branch decides, not the fleet checkout's older copy.
        self.assertIn('Host: local', (p.dir / 'repo/docs/agents/host.md').read_text())
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

    def test_an_unreadable_answer_saves_no_run_and_is_never_retried(self):
        # A refusal is tested in Failures below. An unknown answer may mean a run exists: one call, no retry (#1446).
        p = Project(self)
        code, out, _ = p.host('start', REPO, 7, 'claude', 'claude-opus-5-5', FAKE_DRIVER_MODE='garbage')
        self.assertEqual((code, out), (1, 'unknown: the local driver answered no run; a run may exist, '
                                          'so reconcile before any retry'))
        self.assertIsNone(p.saved())
        self.assertEqual(len(p.calls()), 1)
        code, out, _ = p.host('start', REPO, 7, 'claude', 'claude-opus-5-5', FAKE_DRIVER_MODE='extra')
        self.assertEqual((code, out), (1, 'unknown: the local driver answered no run; a run may exist, '
                                          'so reconcile before any retry'))
        self.assertIsNone(p.saved())
        self.assertEqual(len(p.calls()), 2)
        self.assertEqual(p.github()['writes'], [])
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'claude-opus-5-5')[0], 0)
        self.assertEqual(p.host('wake', REPO, 7, FAKE_DRIVER_MODE='extra')[:2],
                         (1, 'unknown: the local driver answered no run; a run may exist, so reconcile before any retry'))

    def test_starts_at_once_keep_every_run(self):
        p = Project(self)
        hold = p.dir / 'hold'
        hold.touch()
        slow = subprocess.Popen([sys.executable, '-I', str(HERE / 'host.py'), 'start', REPO, '7', 'claude', 'm'],
                                cwd=p.dir / 'repo', env=dict(p.env, FAKE_DRIVER_HOLD=str(hold)),
                                stdout=subprocess.PIPE, text=True)
        self.addCleanup(slow.kill)
        for _ in range(500):  # until #7's driver has its call (it logs before it waits)
            if p.calls():
                break
            time.sleep(0.02)
        self.assertEqual(len(p.calls()), 1)
        self.assertEqual(p.host('start', REPO, 8, 'claude', 'm'), (0, 'started #8 on local', ''))
        hold.unlink()
        self.assertEqual((slow.communicate(timeout=60)[0].strip(), slow.returncode), ('started #7 on local', 0))
        self.assertEqual(p.saved()['runs'], {'7': {'host': 'local', 'run': 'local-run-7'},
                                             '8': {'host': 'local', 'run': 'local-run-8'}})

    def test_unwritable_run_state_starts_nothing_and_a_lost_save_keeps_the_run(self):
        # R3: the private state is checked before the driver runs; a save lost after a start names the run.
        p = Project(self)
        code, out, err = p.host('start', REPO, 7, 'claude', 'm', LAUNCH_FLEET_RUNS=str(p.dir / 'missing/runs.json'))
        self.assertEqual((code, out), (2, ''))
        self.assertTrue(err.startswith('host.py: '), err)
        self.assertEqual(p.calls(), [])
        code, out, _ = p.host('start', REPO, 7, 'claude', 'm', FAKE_DRIVER_BREAK=str(p.runs.parent))
        self.assertEqual((code, out), (1, 'unknown: #7 started on local but its run was not saved; save run '
                                          'local-run-7 on host local for #7 privately before anything else'))
        self.assertEqual(len(p.calls()), 1)

    def test_start_sends_the_named_skill_to_the_driver(self):
        for skill, who in (('review-ticket', 'reviewer-7'), ('launch-fleet', 'fleet-7')):
            with self.subTest(skill):
                p = Project(self)
                self.assertEqual(p.host('start', REPO, 7, 'claude', 'claude-opus-5-5', skill),
                                 (0, 'started #7 on local', ''))
                self.assertEqual(p.calls(), [{'host': 'local', 'command': 'start', 'input': {
                    'repository': REPO, 'ticket': 7, 'skill': skill, 'harness': 'claude', 'model': 'claude-opus-5-5'}}])
                self.assertEqual(p.saved(), {'repo': REPO, 'runs': {'7': {'host': 'local', 'run': 'local-run-7'}}})
                self.assertEqual(p.labels(), {'repo': REPO, 'requesters': {'7': {
                    'host': 'local', 'requester': who, 'run': 'local-run-7'}}})

    def test_start_without_a_skill_sends_todays_exact_bytes(self):
        p = Project(self)
        raw = p.dir / 'raw-start'
        (p.dir / 'adapters/local/driver').write_text(
            '#!/bin/sh\ncat > "%s"\nprintf \'{"run": "local-run-7"}\\n\'\n' % raw)
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'claude-opus-5-5'), (0, 'started #7 on local', ''))
        self.assertEqual(raw.read_bytes(), b'{"repository": "synthetic-owner/synthetic-repo", "ticket": 7, '
                                           b'"skill": "build-ticket", "harness": "claude", "model": "claude-opus-5-5"}')

    def test_a_skill_outside_the_driver_schema_starts_nothing(self):
        for skill in ('', 'Review-Ticket', 'review_ticket', '-review', 'review-', '../review-ticket', 'a' * 61):
            with self.subTest(skill):
                p = Project(self)
                code, out, err = p.host('start', REPO, 7, 'claude', 'claude-opus-5-5', skill)
                self.assertEqual((code, out), (2, ''), err)
                self.assertTrue(err.startswith('host.py: usage: '), err)
                self.assertEqual(p.calls(), [])
                self.assertIsNone(p.saved())
        p = Project(self)
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'claude-opus-5-5', 'a' * 60)[0], 0)
        self.assertEqual(p.calls()[0]['input']['skill'], 'a' * 60)

    def test_wake_and_stop_take_no_skill(self):
        p = Project(self)
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'claude-opus-5-5')[0], 0)
        for kind in ('wake', 'stop'):
            with self.subTest(kind):
                code, out, err = p.host(kind, REPO, 7, 'review-ticket')
                self.assertEqual((code, out), (2, ''), err)
        self.assertEqual([c['command'] for c in p.calls()], ['start'])

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


STOPPED = 'stopped (driver start failed)'


TOKEN = 'synthetic-ga4-token-0123456789'
WRITE = {'metadata': 'read', 'contents': 'write', 'issues': 'write', 'pull_requests': 'write', 'checks': 'read',
         'actions': 'read'}
NOTE = "openwiz: no openwiz[bot] token (unavailable); using the owner's GitHub account"


class Token(unittest.TestCase):

    def service(self, p):
        private = p.dir / 'token-private'
        private.mkdir(mode=0o700)
        p.service_log = p.dir / 'service.log'
        return dict(OPENWIZ_TOKEN_SERVICE=str(HERE / 'fixtures/token_service.py'), OPENWIZ_TOKEN_SERVICE_ROUTE='local',
                    OPENWIZ_AGENT_TOKEN_DIR=str(private), FAKE_SERVICE_LOG=str(p.service_log))

    def requests(self, p):
        return [json.loads(line) for line in p.service_log.read_text().splitlines()] if p.service_log.exists() else []

    def exposed(self, p, *outputs):
        texts = [*outputs, p.log.read_text() if p.log.exists() else '', p.runs.read_text() if p.runs.exists() else '',
                 p.world.read_text(), *(json.dumps(r['argv']) for r in self.requests(p))]
        return [t for t in texts if TOKEN in t]

    def test_a_driver_start_and_a_wake_each_get_the_builders_token_from_the_helper(self):
        p = Project(self)
        env = self.service(p)
        started = p.host('start', REPO, 7, 'claude', 'claude-opus-5-5', **env)
        self.assertEqual(started, (0, 'started #7 on local', ''))
        self.assertEqual([r['request'] for r in self.requests(p)], [{
            'schema': 'openwiz.token-service.v1', 'kind': 'request', 'requester': 'builder-7',
            'repositories': [REPO], 'permissions': WRITE}])
        held = [f for f in (p.dir / 'token-private').iterdir()]
        self.assertEqual(len(held), 1)
        self.assertEqual(held[0].stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(held[0].read_text())['token'], TOKEN)
        self.assertEqual(p.calls()[0]['input'], {'repository': REPO, 'ticket': 7, 'skill': 'build-ticket',
                                                 'harness': 'claude', 'model': 'claude-opus-5-5'})
        held[0].unlink()
        woke = p.host('wake', REPO, 7, **env)
        self.assertEqual(woke, (0, 'woke #7 on local', ''))
        self.assertEqual([r['request']['requester'] for r in self.requests(p)], ['builder-7', 'builder-7'])
        self.assertEqual(self.exposed(p, *started[1:], *woke[1:]), [])

    def builder(self, p):
        (p.dir / 'bin/gh').write_text(
            '#!/bin/sh\nif [ -n "${FAKE_GH_PROBE:-}" ]; then\n'
            '  { [ "${GH_TOKEN:-}" = %s ] && printf app || printf owner\n'
            '    [ -n "${OPENWIZ_GITHUB_APP_KEY+set}" ] && printf " key\\n" || printf " no-key\\n"; } >> "$FAKE_GH_PROBE"\n'
            'fi\nexec "%s" -I "%s" "$@"\n' % (TOKEN, sys.executable, HERE / 'fixtures/fake_github.py'))
        p.first = p.dir / 'builder.log'
        return dict(FAKE_DRIVER_BUILDER=str(p.first), OPENWIZ_GITHUB_APP_KEY='synthetic-legacy-sentinel')

    def seen(self, p):
        first = [json.loads(line) for line in p.first.read_text().splitlines()] if p.first.exists() else []
        gh = p.first.with_name(p.first.name + '.gh')
        return first, gh.read_text().splitlines() if gh.exists() else []

    def test_the_drivers_builder_does_its_first_github_operation_as_the_app_without_the_legacy_key(self):
        p = Project(self)
        env = dict(self.service(p), **self.builder(p))
        started = p.host('start', REPO, 7, 'claude', 'claude-opus-5-5', **env)
        self.assertEqual(started, (0, 'started #7 on local', ''))
        woke = p.host('wake', REPO, 7, **env)
        self.assertEqual(woke, (0, 'woke #7 on local', ''))
        self.assertEqual(self.seen(p), (
            [{'command': 'start', 'git_helper_is_the_apps': True, 'legacy_key': False},
             {'command': 'wake', 'git_helper_is_the_apps': True, 'legacy_key': False}],
            ['app no-key', 'app no-key']))
        self.assertEqual({r['request']['requester'] for r in self.requests(p)}, {'builder-7'})
        self.assertEqual([r['legacy_key'] for r in self.requests(p)], [False] * len(self.requests(p)))
        self.assertEqual(self.exposed(p, *started[1:], *woke[1:]), [])

    def git_probe(self, p):
        p.git_log = p.dir / 'git-probe.log'
        real = subprocess.run(['sh', '-c', 'command -v git'], capture_output=True, text=True).stdout.strip()
        (p.dir / 'bin/git').write_text(
            '#!/bin/sh\n{ [ -n "${OPENWIZ_GITHUB_APP_KEY+set}" ] && printf key || printf no-key\n'
            '  [ "${GH_TOKEN:-}" = %s ] && printf " token\\n" || printf " no-token\\n"; } >> "%s"\n'
            'exec "%s" "$@"\n' % (TOKEN, p.git_log, real))
        (p.dir / 'bin/git').chmod(0o755)

    def probed(self, p):
        return set(p.git_log.read_text().splitlines()) if p.git_log.exists() else set()

    def test_with_a_service_no_git_child_gets_the_legacy_key_or_the_app_token(self):
        p = Project(self)
        env = dict(self.service(p), **self.builder(p))
        self.git_probe(p)
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'claude-opus-5-5', **env), (0, 'started #7 on local', ''))
        self.assertEqual(p.host('wake', REPO, 7, **env), (0, 'woke #7 on local', ''))
        self.assertEqual(self.probed(p), {'no-key no-token'})
        self.assertEqual(self.seen(p), (
            [{'command': 'start', 'git_helper_is_the_apps': True, 'legacy_key': False},
             {'command': 'wake', 'git_helper_is_the_apps': True, 'legacy_key': False}],
            ['app no-key', 'app no-key']))

    def test_with_no_service_git_children_keep_the_environment_as_today(self):
        p = Project(self)
        env = dict(self.service(p), **self.builder(p))
        env['OPENWIZ_TOKEN_SERVICE'] = ''
        self.git_probe(p)
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'claude-opus-5-5', **env), (0, 'started #7 on local', ''))
        self.assertEqual(self.probed(p), {'key no-token'})

    def test_a_refused_token_falls_back_with_one_note_and_the_start_goes_on(self):
        p = Project(self)
        env = dict(self.service(p), FAKE_SERVICE_REFUSE='1')
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'claude-opus-5-5', **env), (0, 'started #7 on local', NOTE))
        self.assertEqual(p.host('wake', REPO, 7, **env), (0, 'woke #7 on local', NOTE))
        self.assertEqual(len(self.requests(p)), 2)
        self.assertEqual(list((p.dir / 'token-private').iterdir()), [])

    def test_with_no_service_no_helper_runs_and_starts_are_as_today(self):
        p = Project(self)
        env = self.service(p)
        (p.dir / 'token-private').rmdir()
        env.update(self.builder(p), OPENWIZ_TOKEN_SERVICE='')
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'claude-opus-5-5', **env), (0, 'started #7 on local', ''))
        self.assertEqual(p.host('wake', REPO, 7, **env), (0, 'woke #7 on local', ''))
        self.assertEqual(self.seen(p), (
            [{'command': 'start', 'git_helper_is_the_apps': False, 'legacy_key': True},
             {'command': 'wake', 'git_helper_is_the_apps': False, 'legacy_key': True}],
            ['owner key', 'owner key']))
        self.assertEqual(self.requests(p), [])
        self.assertFalse((p.dir / 'token-private').exists())


    def test_each_skill_started_without_a_roster_asks_for_its_own_role_at_the_same_scope(self):
        p = Project(self)
        env = self.service(p)
        for n, skill in ((7, 'build-ticket'), (8, 'review-ticket'), (9, 'launch-fleet'), (10, 'grill')):
            self.assertEqual(p.host('start', REPO, n, 'claude', 'claude-opus-5-5', skill, **env),
                             (0, 'started #%s on local' % n, ''))
        for held in (p.dir / 'token-private').iterdir():
            held.unlink()
        for n in (7, 8, 9, 10):
            self.assertEqual(p.host('wake', REPO, n, **env), (0, 'woke #%s on local' % n, ''))
        wanted = ['builder-7', 'reviewer-8', 'fleet-9', 'builder-10']
        self.assertEqual([r['request'] for r in self.requests(p)],
                         [{'schema': 'openwiz.token-service.v1', 'kind': 'request', 'requester': who,
                           'repositories': [REPO], 'permissions': WRITE} for who in wanted * 2])
        folder = p.runs.parent / 'agent-token-bin'
        self.assertEqual({path.relative_to(folder).as_posix(): re.findall(r'--requester (\S+)', path.read_text())
                          for path in folder.glob('*/*')},
                         {'%s/%s' % (shim, name): [who] for who, shim in zip(wanted, (
                             'synthetic-owner--synthetic-repo-7', 'synthetic-owner--synthetic-repo-reviewer-8',
                             'synthetic-owner--synthetic-repo-fleet-9', 'synthetic-owner--synthetic-repo-10'))
                          for name in ('gh', 'git')})


    def test_the_run_map_keeps_the_shape_an_older_host_reads_beside_a_reviewer_and_a_fleet(self):
        p = Project(self)
        env = self.service(p)
        for n, skill in ((7, 'build-ticket'), (8, 'review-ticket'), (9, 'launch-fleet')):
            self.assertEqual(p.host('start', REPO, n, 'claude', 'claude-opus-5-5', skill, **env),
                             (0, 'started #%s on local' % n, ''))
        runs = p.saved()['runs']
        self.assertEqual(runs, {n: {'host': 'local', 'run': 'local-run-%s' % n} for n in ('7', '8', '9')})
        older = {'host', 'run'}, {'host', 'run', 'stopped'}
        self.assertTrue(all(set(v) in older for v in runs.values()))
        self.assertEqual(p.host('stop', REPO, 7, **env), (0, 'stopped #7 on local', ''))
        self.assertEqual(p.saved()['runs']['7'], {'host': 'local', 'run': 'local-run-7', 'stopped': True})
        self.assertEqual(sorted(p.labels()['requesters']), ['8', '9'])

    def test_a_label_for_another_run_is_ignored_and_a_restart_as_a_builder_drops_it(self):
        p = Project(self)
        env = self.service(p)
        self.assertEqual(p.host('start', REPO, 8, 'claude', 'claude-opus-5-5', 'review-ticket', **env),
                         (0, 'started #8 on local', ''))
        p.runs.write_text(json.dumps({'repo': REPO, 'runs': {'8': {'host': 'local', 'run': 'older-host-run'}}}))
        self.assertEqual(p.host('wake', REPO, 8, **env), (0, 'woke #8 on local', ''))
        self.assertEqual(self.requests(p)[-1]['request']['requester'], 'builder-8')
        self.assertEqual(p.host('stop', REPO, 8, **env), (0, 'stopped #8 on local', ''))
        self.assertEqual(p.host('start', REPO, 8, 'claude', 'claude-opus-5-5', **env), (0, 'started #8 on local', ''))
        self.assertEqual(p.labels(), {'repo': REPO, 'requesters': {}})

    def test_a_label_for_another_ticket_or_role_is_an_unreadable_requesters_file(self):
        for label in ({'requester': 'fleet-8'}, {'requester': 'builder-7'}, {'requester': 'reviewer-7', 'role': 'x'}):
            with self.subTest(label):
                p = Project(self)
                p.runs.write_text(json.dumps({'repo': REPO, 'runs': {'7': {'host': 'local', 'run': 'local-run-7'}}}))
                Path(str(p.runs) + '.requesters').write_text(json.dumps({'repo': REPO, 'requesters': {
                    '7': dict({'host': 'local', 'run': 'local-run-7'}, **label)}}))
                code, out, err = p.host('wake', REPO, 7, **self.service(p))
                self.assertEqual((code, out, p.calls(), self.requests(p)), (2, '', [], []))
                self.assertIn('is not a requesters file for %s' % REPO, err)


class Version(unittest.TestCase):
    def test_the_installed_version_reads_plain_or_quoted(self):
        for line in ('version: 0.2.0', 'version: "0.2.0"', "version: '0.2.0'"):
            with self.subTest(line):
                self.assertEqual(front_version('---\nname: launch-fleet\n%s\n---\n' % line), '0.2.0')
        for line in ('version: "0.2.0\'', 'version: 0.2', 'name: launch-fleet'):
            with self.subTest(line):
                self.assertIsNone(front_version('---\n%s\n---\n' % line))


class Failures(unittest.TestCase):
    """#1446: a refused start or wake is tried three times in all, then reported on the ticket once."""

    def test_a_refused_start_is_tried_three_times_with_backoff_then_reported_once(self):
        p = Project(self)
        began = time.monotonic()
        code, out, _ = p.host('start', REPO, 7, 'claude', 'm', FAKE_DRIVER_MODE='refuse')
        self.assertGreaterEqual(time.monotonic() - began, 3, 'two waits, of 1 and 2 seconds')
        self.assertEqual((code, out), (1, '%s: the local driver refused #7\'s start 3 times; next: %s' % (STOPPED, NEXT)))
        self.assertEqual([c['command'] for c in p.calls()], ['start'] * 3)
        self.assertIsNone(p.saved())
        self.assertEqual(p.fleet_notes(), [STOPPED])
        self.assertEqual(p.failures(), [p.failure()])
        # The fleet tries again later and the driver still refuses: no second note or comment.
        writes = len(p.github()['writes'])
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'm', FAKE_DRIVER_MODE='refuse')[:2], (code, out))
        self.assertEqual(len(p.calls()), 6)
        self.assertEqual(len(p.github()['writes']), writes)
        self.assertEqual((p.fleet_notes(), len(p.failures())), ([STOPPED], 1))

    def test_a_refused_reviewer_start_is_reported_as_the_reviewers(self):
        p = Project(self)
        self.assertEqual(p.host('start', REPO, 31, 'claude', 'm', 'review-ticket', FAKE_DRIVER_MODE='refuse')[0], 1)
        steps = lambda: [next(line[len('step: '):] for line in body.split('\n') if line.startswith('step: '))
                         for first, body in p.ticket(31) if first == '<!-- openwiz:status v1 -->']
        self.assertEqual(steps(), ["the local driver refused this pull request's reviewer's start 3 times; the "
                                   "reason is in a comment here"])
        self.assertEqual(p.failures(31), [(MARK, "The local driver refused to start this pull request's reviewer 3 "
                                                 "times (exit 1: refused). Its own words are kept off this public pull "
                                                 "request: the fleet's owner can read them in the private driver log, "
                                                 "`driver-failures.log` beside `LAUNCH_FLEET_RUNS`, entry %s for #31."
                                           % p.driver_log()[0]['time'])])
        self.assertEqual(p.host('start', REPO, 31, 'claude', 'm', 'review-ticket'), (0, 'started #31 on local', ''))
        self.assertEqual(steps()[1:], ["the local driver started this pull request's reviewer on a later try"])

    def test_the_drivers_own_words_stay_in_the_owners_log_never_on_the_ticket(self):
        # The orchestrator's decision on R3 at 90aed73: no free text of the driver's ever reaches the ticket.
        p = Project(self)
        words = 'reach svc:made-up-pass-44@example.invalid, then ask the synthetic operator'
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'm', FAKE_DRIVER_MODE='refuse', FAKE_DRIVER_NEXT=words)[0], 1)
        world = json.dumps(p.github())
        for part in ('made-up-pass-44', 'synthetic operator', 'not signed in'):
            self.assertNotIn(part, world)
        self.assertEqual(p.failures(), [p.failure()])
        log = p.runs.with_name('driver-failures.log')
        self.assertEqual(log.stat().st_mode & 0o777, 0o600)
        entry = p.driver_log()[0]
        self.assertEqual({k: entry[k] for k in ('repo', 'ticket', 'host', 'command', 'exit', 'error', 'next')},
                         {'repo': REPO, 'ticket': 7, 'host': 'local', 'command': 'start', 'exit': 1,
                          'error': 'the synthetic harness is not signed in', 'next': words})
        # A later refusal adds its own entry; the one comment keeps pointing at the first.
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'm', FAKE_DRIVER_MODE='refuse')[0], 1)
        self.assertEqual((len(p.driver_log()), p.failures()), (2, [p.failure()]))

    def test_a_start_that_succeeds_on_a_retry_reports_nothing(self):
        p = Project(self)
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'm', FAKE_DRIVER_REFUSALS='2'), (0, 'started #7 on local', ''))
        self.assertEqual([c['command'] for c in p.calls()], ['start'] * 3)
        self.assertEqual(p.saved()['runs'], {'7': {'host': 'local', 'run': 'local-run-7'}})
        self.assertEqual(p.github()['writes'], [])

    def test_a_later_success_clears_the_stopped_state_once(self):
        p = Project(self)
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'm', FAKE_DRIVER_MODE='refuse')[0], 1)
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'm'), (0, 'started #7 on local', ''))
        self.assertEqual(p.fleet_notes(), [STOPPED, 'done'])
        self.assertEqual(p.failures(), [(MARK + ', cleared', p.failure()[1] + '\n\nCleared: the local driver started '
                                                                       'it later.')])
        writes = len(p.github()['writes'])
        self.assertEqual(p.host('wake', REPO, 7), (0, 'woke #7 on local', ''))
        self.assertEqual(len(p.github()['writes']), writes)

    def test_a_refused_wake_is_retried_reported_and_cleared(self):
        p = Project(self)
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'm')[0], 0)
        code, out, _ = p.host('wake', REPO, 7, FAKE_DRIVER_MODE='refuse')
        self.assertEqual((code, out), (1, '%s: the local driver refused #7\'s wake 3 times; next: %s' % (STOPPED, NEXT)))
        self.assertEqual([c['command'] for c in p.calls()], ['start', 'wake', 'wake', 'wake'])
        self.assertEqual(p.fleet_notes(), [STOPPED])
        self.assertEqual(p.failures(), [p.failure('wake')])
        self.assertEqual(p.host('wake', REPO, 7, FAKE_DRIVER_MODE='refuse')[0], 1)
        self.assertEqual((p.fleet_notes(), len(p.failures())), ([STOPPED], 1))
        self.assertEqual(p.host('wake', REPO, 7), (0, 'woke #7 on local', ''))
        self.assertEqual(p.fleet_notes(), [STOPPED, 'done'])
        self.assertEqual([first for first, _ in p.failures()], [MARK + ', cleared'])

    def test_a_stop_is_never_retried(self):
        p = Project(self)
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'm')[0], 0)
        code, out, _ = p.host('stop', REPO, 7, FAKE_DRIVER_MODE='refuse')
        self.assertEqual((code, out), (1, 'refused: the synthetic harness is not signed in; next: ' + NEXT))
        self.assertEqual([c['command'] for c in p.calls()], ['start', 'stop'])
        self.assertEqual(p.github()['writes'], [])

    def test_a_credential_or_private_id_in_the_drivers_text_never_reaches_the_ticket(self):
        secret = 'synthetic-secret-value-0123'
        token, thread = 'gh' + 'p_synthetic0123456789abcdef', 'thr' + '_synthetic1'  # no literal in the diff
        leaks = {'a token': 'export token=%s and retry' % token,
                 'a thread id': 'resume %s by hand' % thread, 'a machine path': 'edit /srv/synthetic/driver.conf',
                 'a secret value': 'use %s to sign in' % secret,
                 # R3 of the re-check at 004afb6: a URL's user info, password or not, from the driver's own config.
                 'a URL password': 'sign in at https://svc-account:made-up-pass-42@example.invalid/login',
                 'a URL user': 'open ssh://made-up-user@example.invalid to sign in',
                 # The decision on R3: a schemeless endpoint, as libcurl guesses its protocol.
                 'a schemeless URL password': 'set the endpoint to svc:made-up-pass-43@example.invalid/api'}
        for name, text in leaks.items():
            with self.subTest(name):
                p = Project(self)
                code, out, _ = p.host('start', REPO, 7, 'claude', 'm', FAKE_DRIVER_MODE='refuse', FAKE_DRIVER_NEXT=text,
                                      SYNTHETIC_API_TOKEN=secret)
                world = json.dumps(p.github())
                for part in (token, thread, '/srv/', secret, 'made-up-pass-42', 'made-up-user', 'made-up-pass-43'):
                    self.assertNotIn(part, world)  # the ticket first: the public boundary
                withheld = 'withheld, as it held a credential, a private id or a machine path; run the driver by hand'
                self.assertEqual((code, out), (1, '%s: the local driver refused #7\'s start 3 times; next: %s'
                                               % (STOPPED, withheld)))
                self.assertEqual(p.failures(), [p.failure()])
                self.assertEqual(p.driver_log()[0]['next'], text)  # the raw words, only in the owner's log

    def test_a_report_github_lost_is_written_by_the_next_failure(self):
        p = Project(self)
        p.fault(post='fail')
        code, out, _ = p.host('start', REPO, 7, 'claude', 'm', FAKE_DRIVER_MODE='refuse')
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('%s: the local driver refused #7\'s start 3 times; next: %s; unknown: the ticket\'s '
                                       'report is incomplete (' % (STOPPED, NEXT)), out)
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'm', FAKE_DRIVER_MODE='refuse')[0], 1)
        self.assertEqual((p.fleet_notes(), len(p.failures())), ([STOPPED], 1))

    def test_a_lost_note_write_still_posts_the_failure_comment_in_the_same_run(self):
        # R1 of the review at 1f9c7f6: the note and the comment are written apart, so one failing never hides the other.
        p = Project(self)
        p.fault(post='fail')  # the first POST is the fleet note's
        code, out, _ = p.host('start', REPO, 7, 'claude', 'm', FAKE_DRIVER_MODE='refuse')
        self.assertEqual(p.failures(), [p.failure()])
        self.assertEqual(p.fleet_notes(), [])
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('%s: the local driver refused #7\'s start 3 times; next: %s; unknown: the ticket\'s '
                                       'report is incomplete (the fleet note was not written: ' % (STOPPED, NEXT)), out)
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'm', FAKE_DRIVER_MODE='refuse')[0], 1)
        self.assertEqual((p.fleet_notes(), len(p.failures())), ([STOPPED], 1))

    def test_a_clearing_github_lost_keeps_the_saved_run_and_the_next_success_clears(self):
        p = Project(self)
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'm', FAKE_DRIVER_MODE='refuse')[0], 1)
        p.fault(patch='fail')
        code, out, _ = p.host('start', REPO, 7, 'claude', 'm')
        self.assertEqual(code, 0)
        self.assertEqual(out.split('\n')[0], 'started #7 on local')
        self.assertTrue(out.split('\n')[1].startswith('unknown: the failure report on #7 was not cleared ('), out)
        self.assertEqual(p.saved()['runs'], {'7': {'host': 'local', 'run': 'local-run-7'}})
        self.assertEqual(p.fleet_notes(), [STOPPED, 'done'])  # R1's cause on the clearing route: written apart
        self.assertEqual(p.host('wake', REPO, 7), (0, 'woke #7 on local', ''))
        self.assertEqual(p.fleet_notes(), [STOPPED, 'done'])
        self.assertEqual([first for first, _ in p.failures()], [MARK + ', cleared'])

    def test_no_fleet_identity_still_starts_retries_and_comments_but_writes_no_note(self):
        # J87 planner ruling, relayed by the fleet manager: unset identity skips only the fleet note, with a warning.
        p = Project(self)
        unset = dict(LAUNCH_FLEET_HARNESS='', LAUNCH_FLEET_MODEL='', LAUNCH_FLEET_SKILLS='')
        code, out, err = p.host('start', REPO, 7, 'claude', 'm', FAKE_DRIVER_MODE='refuse', **unset)
        self.assertEqual((code, out), (1, '%s: the local driver refused #7\'s start 3 times; next: %s' % (STOPPED, NEXT)))
        self.assertEqual([c['command'] for c in p.calls()], ['start'] * 3)
        self.assertEqual(p.fleet_notes(), [])
        self.assertEqual(p.failures(), [p.failure()])
        self.assertEqual(err, 'host.py: warning: LAUNCH_FLEET_HARNESS, LAUNCH_FLEET_MODEL, LAUNCH_FLEET_SKILLS '
                              'unset, so the fleet status note was not written')
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'm', **unset)[:2], (0, 'started #7 on local'))
        self.assertEqual([first for first, _ in p.failures()], [MARK + ', cleared'])
        self.assertEqual(p.fleet_notes(), [])
        self.assertEqual(p.host('wake', REPO, 7, LAUNCH_FLEET_MODEL=''), (0, 'woke #7 on local', ''))

ROSTER = HERE / 'fixtures/roster'


def host_module():
    spec = importlib.util.spec_from_file_location('launch_fleet_host_roster', HERE / 'host.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Roster(unittest.TestCase):

    def project(self, case, hosts, setting='Host: local\n'):
        repo = json.loads((ROSTER / case / 'case.json').read_text()).get('repository', REPO)
        p = Project(self, setting=setting, hosts=hosts, repo=repo)
        p.fleet((ROSTER / case / 'fleet.md').read_text())
        return p, repo

    def test_every_fixture_reads_picks_and_refuses_as_the_roster_contract_says(self):
        api = host_module()
        cases = sorted(path.parent.name for path in ROSTER.glob('*/case.json'))
        self.assertEqual(cases, ['long-model', 'mixed', 'namespaced', 'no-roster', 'other-user', 'role-not-allowed',
                                 'starting'])
        for case in cases:
            with self.subTest(case):
                want = json.loads((ROSTER / case / 'case.json').read_text())
                entries = api.roster((ROSTER / case / 'fleet.md').read_text())
                self.assertEqual(entries, want['roster'])
                for p in want.get('picks', []):
                    self.assertEqual(api.pick(entries, want['repository'], p['ticket'], p['role'], p['choice']),
                                     {key: p[key] for key in ('pick', 'waits', 'look')}, p['ticket'])
        refusals = json.loads((ROSTER / 'invalid/refusals.json').read_text())
        self.assertEqual(sorted(refusals), sorted(path.name for path in (ROSTER / 'invalid').glob('*.md')))
        for name, line in refusals.items():
            with self.subTest(name):
                with self.assertRaises(api.Outcome) as refused:
                    api.roster((ROSTER / 'invalid' / name).read_text())
                self.assertEqual(str(refused.exception), line)

    def test_each_role_starts_on_its_first_allowed_entry_and_never_on_one_without_that_role(self):
        p, repo = self.project('mixed', ('local', 'cloudroom', 'demo-bot'))
        self.assertEqual(p.host('which'), (0, 'host: local', ''))
        self.assertEqual(p.host('roster'), (0, "roster: each start goes to its picked entry's driver", ''))
        self.assertEqual(p.host('start', repo, 7, 'claude', 'claude-opus-5-5'),
                         (0, 'started #7 on cloudroom as Claude Code via syn-owner, Opus 5.5 default effort', ''))
        self.assertEqual(p.host('start', repo, 8, 'codex', 'gpt-6.2-sol'),
                         (0, 'started #8 on local as Own computer via syn-owner, Sol 6.2 default effort', ''))
        self.assertEqual(p.host('start', repo, 9, 'codex', 'gpt-6.2-sol', 'review-ticket'),
                         (0, 'started #9 on cloudroom as Codex via syn-owner, Sol 6.2 default effort', ''))
        self.assertEqual(p.host('start', repo, 10, 'claude', 'claude-opus-5-5', 'launch-fleet'),
                         (0, 'started #10 on demo-bot as Demo Bot via syn-owner, Opus 5.5 default effort', ''))
        self.assertEqual([(c['host'], c['input']['ticket'], c['input']['skill'], c['input']['harness'],
                           c['input']['model']) for c in p.calls()],
                         [('cloudroom', 7, 'build-ticket', 'claude', 'claude-opus-5-5'),
                          ('local', 8, 'build-ticket', 'codex', 'gpt-6.2-sol'),
                          ('cloudroom', 9, 'review-ticket', 'codex', 'gpt-6.2-sol'),
                          ('demo-bot', 10, 'launch-fleet', 'claude', 'claude-opus-5-5')])
        self.assertEqual(p.saved(), {'repo': repo, 'runs': {
            '7': {'host': 'cloudroom', 'role': 'builder', 'run': 'cloudroom-run-7'},
            '8': {'host': 'local', 'role': 'builder', 'run': 'local-run-8'},
            '9': {'host': 'cloudroom', 'role': 'reviewer', 'run': 'cloudroom-run-9'},
            '10': {'host': 'demo-bot', 'role': 'orchestrator', 'run': 'demo-bot-run-10'}}})
        self.assertEqual(p.host('wake', repo, 10), (0, 'woke #10 on demo-bot', ''))
        self.assertEqual(p.host('stop', repo, 9), (0, 'stopped #9 on cloudroom', ''))
        self.assertEqual(p.saved()['runs']['9'], {'host': 'cloudroom', 'role': 'reviewer', 'run': 'cloudroom-run-9',
                                                  'stopped': True})

    def test_a_role_no_entry_may_take_waits_and_starts_nothing(self):
        p, repo = self.project('role-not-allowed', ('local', 'demo-bot'))
        self.assertEqual(p.host('start', repo, 2002, 'claude', 'claude-opus-5-5', 'review-ticket'),
                         (1, 'roster: no entry may take the reviewer role with Claude Code', ''))
        self.assertEqual(p.host('start', repo, 2001, 'codex', 'gpt-6.2-sol'),
                         (1, 'roster: no entry may take the builder role with Codex', ''))
        self.assertEqual(p.host('start', repo, 2005, 'claude', 'claude-opus-5-5', 'grill'),
                         (1, 'refused: the Roster gives no role to the grill skill', ''))
        self.assertEqual((p.calls(), p.saved()), ([], None))
        self.assertEqual(p.host('start', repo, 2004, 'claude', 'claude-opus-5-5', 'launch-fleet'),
                         (0, 'started #2004 on demo-bot as Demo Bot via syn-owner, Opus 5.5 default effort', ''))
        p, repo = self.project('namespaced', ('local', 'cloudroom'))
        self.assertEqual(p.host('start', repo, 4002, 'codex', 'vendor/demo', 'review-ticket'),
                         (1, "roster: driver v1 can't start codex vendor/demo; choose another model in the Models "
                             "table", ''))
        self.assertEqual((p.calls(), p.saved()), ([], None))

    def test_a_broken_roster_starts_nothing_and_never_falls_back_to_the_host_setting(self):
        refusals = json.loads((ROSTER / 'invalid/refusals.json').read_text())
        for name in ('role.md', 'heading-form.md'):
            with self.subTest(name):
                p = Project(self)
                p.fleet((ROSTER / 'invalid' / name).read_text())
                self.assertEqual(p.host('start', REPO, 7, 'claude', 'claude-opus-5-5'), (1, refusals[name], ''))
                self.assertEqual(p.host('which'), (0, 'host: local', ''))
                self.assertEqual(p.host('roster'), (1, refusals[name], ''))
                self.assertEqual((p.calls(), p.saved()), ([], None))

    def test_a_bot_entrys_start_carries_its_owners_app_token_and_its_label_on_a_project_that_isnt_ours(self):
        p, repo = self.project('other-user', ('local', 'helper-bot'))
        env = dict(Token().service(p), **Token().builder(p))
        started = p.host('start', repo, 10, 'codex', 'gpt-6.2-sol', 'launch-fleet', **env)
        self.assertEqual(started, (0, 'started #10 on helper-bot as Helper Bot via syn-maker, Sol 6.2 default effort',
                                   ''))
        self.assertEqual(p.calls()[0], {'host': 'helper-bot', 'command': 'start', 'input': {
            'repository': 'syn-maker/garden', 'ticket': 10, 'skill': 'launch-fleet', 'harness': 'codex',
            'model': 'gpt-6.2-sol'}})
        self.assertEqual(Token().requests(p)[0]['request'], {
            'schema': 'openwiz.token-service.v1', 'kind': 'request', 'requester': 'orchestrator-10',
            'repositories': ['syn-maker/garden'], 'permissions': WRITE})
        woke = p.host('wake', repo, 10, **env)
        self.assertEqual(woke, (0, 'woke #10 on helper-bot', ''))
        self.assertEqual(Token().seen(p), (
            [{'command': 'start', 'git_helper_is_the_apps': True, 'legacy_key': False},
             {'command': 'wake', 'git_helper_is_the_apps': True, 'legacy_key': False}],
            ['app no-key', 'app no-key']))
        requests = Token().requests(p)
        self.assertEqual({(r['request']['requester'], tuple(r['request']['repositories'])) for r in requests},
                         {('orchestrator-10', ('syn-maker/garden',))})
        self.assertEqual([r['legacy_key'] for r in requests], [False] * len(requests))
        self.assertNotIn('synthetic-owner', json.dumps([requests, p.calls()]))
        self.assertEqual(Token().exposed(p, *started[1:], *woke[1:]), [])

    def test_with_no_roster_starts_are_as_today_but_for_the_token_role(self):
        p = Project(self)
        p.fleet((ROSTER / 'no-roster/fleet.md').read_text())
        env = Token().service(p)
        self.assertEqual(p.host('which'), (0, 'host: local', ''))
        self.assertEqual(p.host('roster'), (0, 'roster: none', ''))
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'claude-opus-5-5', 'review-ticket', **env),
                         (0, 'started #7 on local', ''))
        self.assertEqual(p.host('start', REPO, 8, 'codex', 'vendor/demo', 'grill', **env),
                         (0, 'started #8 on local', ''))
        self.assertEqual(p.saved(), {'repo': REPO, 'runs': {'7': {'host': 'local', 'run': 'local-run-7'},
                                                            '8': {'host': 'local', 'run': 'local-run-8'}}})
        self.assertEqual([r['request']['requester'] for r in Token().requests(p)], ['reviewer-7', 'builder-8'])
        for held in (p.dir / 'token-private').iterdir():
            held.unlink()
        self.assertEqual(p.host('wake', REPO, 7, **env), (0, 'woke #7 on local', ''))
        self.assertEqual([r['request']['requester'] for r in Token().requests(p)][-1], 'reviewer-7')


    def shims(self, p):
        folder = p.runs.parent / 'agent-token-bin'
        found = {}
        for path in sorted(folder.glob('*/*')) if folder.exists() else []:
            found[path.relative_to(folder).as_posix()] = re.findall(r'--requester (\S+)', path.read_text())
        return found

    def test_a_refused_start_never_changes_a_running_agents_shims_and_each_role_keeps_its_own(self):
        p, repo = self.project('mixed', ('local', 'cloudroom', 'demo-bot'))
        env = Token().service(p)
        self.assertEqual(p.host('start', repo, 9, 'codex', 'gpt-6.2-sol', 'review-ticket', **env)[0], 0)
        running = self.shims(p)
        self.assertEqual(sorted(set(sum(running.values(), []))), ['reviewer-9'])
        self.assertEqual(len(running), 2)
        p.fleet((ROSTER / 'no-roster/fleet.md').read_text())
        self.assertEqual(p.host('start', repo, 9, 'codex', 'gpt-6.2-sol', 'review-ticket', **env),
                         (1, 'refused: #9 already has a run on cloudroom; wake or stop it instead', ''))
        self.assertEqual(self.shims(p), running)
        self.assertEqual(p.host('stop', repo, 9, **env), (0, 'stopped #9 on cloudroom', ''))
        p.fleet((ROSTER / 'mixed/fleet.md').read_text())
        self.assertEqual(p.host('start', repo, 9, 'claude', 'claude-opus-5-5', **env)[0], 0)
        after = self.shims(p)
        self.assertEqual({k: v for k, v in after.items() if k in running}, running)
        self.assertEqual(sorted(set(sum((v for k, v in after.items() if k not in running), []))), ['builder-9'])


if __name__ == '__main__':
    unittest.main()
