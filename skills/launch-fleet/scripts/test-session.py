#!/usr/bin/env python3
"""session.py (#2324): the open chat is the fleet. Ticks run back to back in the foreground.

python3 -I skills/launch-fleet/scripts/test-session.py

Each case is a synthetic project: a bare origin whose default branch says `Host: local`, the existing fake
driver (fixtures/driver.py) as that host, and a synthetic GitHub this file keeps under a lock (FAKE_GH below,
on PATH as `gh`). `fleet.sh` and `merge.py` are stand-ins that read the same synthetic GitHub, so a test can
play each builder and reviewer by writing its status note. `host.py`, `post.py`, `status.py` and `brief.py`
are the real ones. Nothing reaches GitHub or a host.
"""
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent
REPO = 'synthetic-owner/synthetic-repo'
SPEC = '7'
HEAD = 'a' * 40
FLEET_MD = ('# Fleet settings\n\n## CI checks\n\n| Check | Runs |\n| --- | --- |\n| `check` | everything |\n\n'
            '## GitHub identity\n\n| Setting | Value |\n| --- | --- |\n| Record authors | `synthetic-owner` |\n')
_spec = importlib.util.spec_from_file_location('session_test_status', HERE / 'status.py')
status = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(status)

# The world, read and written only under its lock, so the session, its helpers and the test never race.
WORLD = r'''
import fcntl, json, os, sys
from contextlib import contextmanager
PATH = os.environ['FAKE_WORLD']
@contextmanager
def world():
    with open(PATH + '.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with open(PATH) as f:
            w = json.load(f)
        yield w
        with open(PATH + '.tmp', 'w') as f:
            json.dump(w, f)
        os.replace(PATH + '.tmp', PATH)
def records(w, n):
    return [c['body'].split('\n')[0] for c in w['comments'].get(str(n), [])
            if c['user']['login'] == 'synthetic-owner' and c['body'].startswith('launch-fleet: ')]
'''

FAKE_GH = WORLD + r'''
args = sys.argv[1:]
def flag(name):
    return next((a.split('=', 1)[1] for i, a in enumerate(args) if i and args[i - 1] in ('-f', '--raw-field')
                 and a.startswith(name + '=')), None)
def out(value):
    print(json.dumps(value)); sys.exit(0)
with world() as w:
    base = 'repos/%s/' % w['repo']
    if args[:2] == ['pr', 'view']:
        pr = w['prs'][args[2]]
        out({'state': pr['state'], 'statusCheckRollup': pr['checks']})
    path = next(a for a in args if a.startswith('repos/'))
    rest, method = path[len(base):].split('?')[0].split('/'), 'GET'
    if '--method' in args:
        method = args[args.index('--method') + 1]
    if rest == ['contents', 'docs', 'agents', 'fleet.md']:
        sys.stdout.write(w['fleet_md']); sys.exit(0)
    if rest[0] == 'issues' and rest[2:] == ['sub_issues']:
        page = [{'number': int(n), 'state': t['state'].lower()} for n, t in sorted(w['tickets'].items())]
        out([page] if '--slurp' in args else page)
    if rest[0] == 'issues' and rest[2:] == ['comments'] and method == 'POST':
        w['next_id'] += 1
        c = {'id': w['next_id'], 'body': flag('body'), 'user': {'login': w['me']},
             'created_at': '2026-01-01T00:00:00Z', 'updated_at': '2026-01-01T00:00:00Z'}
        w['comments'].setdefault(rest[1], []).append(c)
        out(c)
    if rest[0] == 'issues' and rest[2:] == ['comments']:
        page = w['comments'].get(rest[1], []) if 'page=2' not in path else []
        out([page] if '--slurp' in args else page)
    if rest[:2] == ['issues', 'comments']:
        c = next(c for items in w['comments'].values() for c in items if c['id'] == int(rest[2]))
        if method == 'PATCH':
            c['body'] = flag('body')
        out(c)
print('unexpected gh call: %s' % ' '.join(args), file=sys.stderr)
sys.exit(1)
'''

# fleet.sh's spec check and claim, read from the world as the real one reads GitHub.
FAKE_FLEET = WORLD + r'''
cmd, number = sys.argv[1], sys.argv[2]
if cmd == 'claim':
    print('go #%s' % number); sys.exit(0)
with world() as w:
    for n, t in sorted(w['tickets'].items(), key=lambda x: int(x[0])):
        if t['state'] != 'OPEN':
            continue
        starts = [r for r in records(w, n) if r.startswith(('launch-fleet: start', 'launch-fleet: started'))]
        if int(n) in w['questions']:
            print('needs-info #%s: a question for the orchestrator' % n)
        elif not starts:
            print('start #%s: %s (spec #%s)' % (n, t['title'], number))
        elif starts[-1] == 'launch-fleet: started' and n in w['branches']:
            print('check start #%s: thread run:%s, branch %s' % (n, n, w['branches'][n]))
        for p, pr in sorted(w['prs'].items()):
            if pr['ticket'] != int(n) or pr['state'] != 'OPEN' or pr['checks'][0]['conclusion'] != 'SUCCESS':
                continue
            at = '#%s for #%s at %s' % (p, n, pr['head'])
            if pr.get('verdict') == pr['head']:
                print('merge %s: APPROVE and CI green' % at)
            elif not [r for r in records(w, p) if r.startswith('launch-fleet: review start')]:
                print('review %s: first review' % at)
'''

FAKE_MERGE = WORLD + r'''
with open(os.path.join(os.environ['HOME'], 'merge.log'), 'a') as log:
    log.write(json.dumps(sys.argv[1:]) + '\n')
if sys.argv[1] == 'admit':
    print('base rule: no merge queue; mergeable: MERGEABLE'); sys.exit(0)
with world() as w:
    pr = w['prs'][sys.argv[3]]
    pr['state'] = 'MERGED'
    w['tickets'][str(pr['ticket'])]['state'] = 'CLOSED'
print('merged %s; cost posted 1' % ('f' * 40))
'''


def stamp():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class Session(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='session proof ')
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        git_env = dict(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1', GIT_AUTHOR_NAME='synthetic',
                       GIT_AUTHOR_EMAIL='synthetic@example.invalid', GIT_COMMITTER_NAME='synthetic',
                       GIT_COMMITTER_EMAIL='synthetic@example.invalid')
        writer = self.home / 'writer'
        (writer / 'docs/agents').mkdir(parents=True)
        (writer / 'docs/agents/host.md').write_text('# Host\n\nHost: local\n')
        for args in (['init', '-q', '--bare', '-b', 'trunk', str(self.home / 'origin.git')],
                     ['-C', str(writer), 'init', '-q', '-b', 'trunk'], ['-C', str(writer), 'add', '-A'],
                     ['-C', str(writer), 'commit', '-q', '-m', 'host'],
                     ['-C', str(writer), 'push', '-q', str(self.home / 'origin.git'), 'trunk'],
                     ['clone', '-q', str(self.home / 'origin.git'), str(self.home / 'checkout')]):
            subprocess.run(['git', *args], check=True, capture_output=True, env=dict(os.environ, **git_env))
        driver = self.home / 'adapters/local/driver'
        driver.parent.mkdir(parents=True)
        driver.write_text('#!/bin/sh\nFAKE_DRIVER_HOST=local exec "%s" -I "%s" "$@"\n'
                          % (sys.executable, HERE / 'fixtures/driver.py'))
        self.scripts = self.home / 'skill/scripts'
        self.scripts.mkdir(parents=True)
        shutil.copyfile(HERE / 'session.py', self.scripts / 'session.py')
        for name in ('host.py', 'post.py', 'status.py', 'brief.py', 'heartbeat.py'):
            (self.scripts / name).symlink_to(HERE / name)
        self.program(self.scripts / 'fleet.sh', FAKE_FLEET)
        self.program(self.scripts / 'merge.py', FAKE_MERGE)
        self.program(self.home / 'bin/gh', FAKE_GH)
        driver.chmod(0o755)
        self.world = self.home / 'world.json'
        self.world.write_text(json.dumps({'repo': REPO, 'me': 'synthetic-owner', 'fleet_md': FLEET_MD,
                                          'next_id': 100, 'comments': {}, 'tickets': {}, 'prs': {},
                                          'branches': {}, 'questions': []}))
        self.log = self.home / 'driver.log'
        self.env = dict(git_env, HOME=str(self.home), PATH='%s:%s' % (self.home / 'bin', os.environ['PATH']),
                        OPENWIZ_ADAPTERS=str(self.home / 'adapters'), FAKE_DRIVER_LOG=str(self.log),
                        FAKE_WORLD=str(self.world), LC_ALL='C')
        key = hashlib.sha256(('%s#%s' % (REPO.lower(), SPEC)).encode()).hexdigest()[:20]
        self.lock_dir = self.home / '.local/state/openwiz-heartbeat' / ('openwiz-heartbeat-' + key)

    def program(self, path, source):
        path.parent.mkdir(parents=True, exist_ok=True)
        (path.parent / (path.name + '.src')).write_text(source)
        path.write_text('#!/bin/sh\nexec "%s" -I "%s.src" "$@"\n' % (sys.executable, path))
        path.chmod(0o755)

    def change(self, edit):
        with open(str(self.world) + '.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            w = json.loads(self.world.read_text())
            edit(w)
            self.world.write_text(json.dumps(w))

    def tickets(self, *numbers):
        self.change(lambda w: w['tickets'].update({str(n): {'title': 'synthetic %d' % n, 'state': 'OPEN'}
                                                   for n in numbers}))

    def note(self, n, agent, pr=None):
        """The agent's run ends: its status note says done, as build-ticket and review-ticket write it."""
        fields = {'agent': agent, 'state': 'done', 'harness': 'Claude Code', 'model': 'Opus 5.5',
                  'skills': 'build-ticket@0.2.1', 'step': 'handed back', 'time': stamp()}
        if pr:
            fields['pr'] = 'https://github.com/%s/pull/%d' % (REPO, pr)

        def add(w):
            w['next_id'] += 1
            w['comments'].setdefault(str(n), []).append(
                {'id': w['next_id'], 'body': status.body(fields), 'user': {'login': 'synthetic-owner'}})
        self.change(add)

    def records(self, n):
        w = json.loads(self.world.read_text())
        return [c['body'] for c in w['comments'].get(str(n), []) if c['body'].startswith('launch-fleet: ')]

    def starts(self):
        lines = self.log.read_text().splitlines() if self.log.exists() else []
        return [json.loads(line)['input'] for line in lines if json.loads(line)['command'] == 'start']

    def command(self, *extra):
        return [sys.executable, '-I', str(self.scripts / 'session.py'), 'run', REPO, '--spec', SPEC,
                '--harness', 'claude', '--model', 'synthetic-builder', '--reviewer-harness', 'codex',
                '--reviewer-model', 'synthetic-reviewer', '--poll', '0.05', '--ci-poll', '0.05', *extra]

    def session(self, *extra, **env):
        process = subprocess.Popen(self.command(*extra), cwd=self.home / 'checkout', env=dict(self.env, **env),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        return process

    def until(self, condition, what, process):
        end = time.monotonic() + 30
        while not condition():
            self.assertIsNone(process.poll(), 'the session ended before %s: %s' % (what, process.stdout.read()
                                                                                  + process.stderr.read()))
            self.assertLess(time.monotonic(), end, 'timed out waiting for ' + what)
            time.sleep(0.02)

    def ended(self, process, code):
        out, err = process.communicate(timeout=30)
        self.assertEqual(process.returncode, code, out + err)
        return out

    def test_three_start_in_one_tick_a_fourth_waits_for_the_cap_then_starts_when_a_run_ends(self):
        self.tickets(1, 2, 3, 4)
        process = self.session()
        self.until(lambda: all(self.records(n) == ['launch-fleet: started'] for n in (1, 2, 3)), 'three starts',
                   process)
        self.assertEqual(sorted(s['ticket'] for s in self.starts()), [1, 2, 3])
        self.assertEqual({(s['skill'], s['harness'], s['model']) for s in self.starts()},
                         {('build-ticket', 'claude', 'synthetic-builder')})
        self.assertEqual(self.records(4), [])
        self.assertIsNone(process.poll())
        self.note(2, 'builder')
        self.until(lambda: self.records(4) == ['launch-fleet: started'], 'the fourth start', process)
        self.assertEqual([s['ticket'] for s in self.starts()][3:], [4])
        process.send_signal(signal.SIGINT)
        out = self.ended(process, 130)
        self.assertIn('session: tick 1: started #1, #2, #3; #4 waits for the cap (3)\n', out)
        self.assertIn('session: stopped on interrupt', out)
        self.assertIn('carry on: ' + ' '.join(self.command()[2:]), out)
        self.assertFalse(self.lock_dir.exists())

    def test_a_finished_build_gets_its_reviewer_and_an_approved_green_pull_request_merges(self):
        self.tickets(5)
        self.change(lambda w: w['branches'].update({'5': 'room/5-synthetic'}))
        process = self.session()
        self.until(lambda: self.records(5) == ['launch-fleet: start checked, branch room/5-synthetic'], 'check',
                   process)
        self.change(lambda w: w['prs'].update({'12': {'ticket': 5, 'head': HEAD, 'state': 'OPEN', 'checks': [
            {'__typename': 'CheckRun', 'name': 'check', 'status': 'COMPLETED', 'conclusion': 'SUCCESS'}]}}))
        self.note(5, 'builder', pr=12)
        self.until(lambda: self.records(12)[:1] and self.records(12)[0].startswith(
            'launch-fleet: review started ' + HEAD), 'the reviewer', process)
        self.assertEqual(self.starts()[1], {'repository': REPO, 'ticket': 12, 'skill': 'review-ticket',
                                            'harness': 'codex', 'model': 'synthetic-reviewer'})
        self.assertEqual(self.records(12)[0].split('\n')[1], 'Driver review: other-family')
        self.assertFalse((self.home / 'merge.log').exists())
        self.change(lambda w: w['prs']['12'].update(verdict=HEAD))
        self.note(12, 'reviewer')
        out = self.ended(process, 0)
        merges = [json.loads(line) for line in (self.home / 'merge.log').read_text().splitlines()]
        self.assertEqual([m[0] for m in merges], ['admit', 'merge'])
        self.assertEqual(merges[1][:5] + merges[1][6:], ['merge', REPO, '12', HEAD, 'check', '--ticket', '5',
                                                         '--base-rule-checked'])
        self.assertIn('session: done: every ticket of spec #7 is closed\n', out)

    def test_a_question_stops_the_session_before_anything_starts(self):
        self.tickets(8, 9)
        self.change(lambda w: w['questions'].append(8))
        out = self.ended(self.session(), 3)
        self.assertIn('session: stopped at tick 1: needs you: needs-info #8: a question for the orchestrator\n',
                      out)
        self.assertIn('carry on: ' + ' '.join(self.command()[2:]), out)
        self.assertEqual(self.starts(), [])

    def test_a_refused_start_stops_the_session_and_records_the_refusal(self):
        self.tickets(9)
        out = self.ended(self.session(FAKE_DRIVER_MODE='refuse'), 3)
        self.assertIn('session: stopped at tick 1: needs you: the local driver refused #9', out)
        self.assertEqual(self.records(9)[:1], ['launch-fleet: start refused: driver start failed'])

    def test_a_second_session_and_a_heartbeat_tick_refuse_through_the_shared_lock(self):
        self.tickets(6)
        process = self.session()
        self.until(lambda: self.records(6) == ['launch-fleet: started'], 'the start', process)
        second = subprocess.run(self.command(), cwd=self.home / 'checkout', env=self.env, capture_output=True,
                                text=True, timeout=30)
        self.assertEqual(second.returncode, 1, second.stdout + second.stderr)
        self.assertEqual(second.stdout, 'session: refused: a session or heartbeat tick already runs spec #7\n')
        (self.lock_dir / 'config.json').write_text('{}\n')
        tick = subprocess.run([sys.executable, '-I', str(self.scripts / 'heartbeat.py'), 'run', REPO, SPEC],
                              cwd=self.home / 'checkout', env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual((tick.returncode, tick.stdout), (1, 'heartbeat: a heartbeat operation is already running\n'))
        process.send_signal(signal.SIGINT)
        self.ended(process, 130)
        fd = os.open(self.lock_dir, os.O_RDONLY | os.O_DIRECTORY)  # a heartbeat tick holds it now
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            third = subprocess.run(self.command(), cwd=self.home / 'checkout', env=self.env, capture_output=True,
                                   text=True, timeout=30)
        finally:
            os.close(fd)
        self.assertEqual((third.returncode, third.stdout),
                         (1, 'session: refused: a session or heartbeat tick already runs spec #7\n'))
        self.assertEqual(len(self.starts()), 1)


if __name__ == '__main__':
    unittest.main()
