#!/usr/bin/env python3
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO = 'synthetic-owner/synthetic-repo'
SPEC = '7'
HEAD = 'a' * 40
MODELS = ('## Models\n\n| Role | Harness | Model | Effort | `room-cli thread spawn` flags |\n'
          '| --- | --- | --- | --- | --- |\n'
          '| Orchestrator | Claude Code | Table | High | `--provider claude-code --model synthetic-table-builder '
          '--reasoning-level high` |\n'
          '| Builder | Claude Code | Table | High | `--provider claude-code --model synthetic-table-builder '
          '--reasoning-level high` |\n'
          '| Reviewer | %s | Table | High | `--provider %s --model synthetic-table-reviewer --reasoning-level high` |\n\n')
FLEET_MD = ('# Fleet settings\n\n' + MODELS % ('Codex', 'codex') + '## CI checks\n\n| Check | Runs |\n| --- | --- |\n'
            '| `check` | everything |\n\n'
            '## GitHub identity\n\n| Setting | Value |\n| --- | --- |\n| Record authors | `synthetic-owner` |\n')
_spec = importlib.util.spec_from_file_location('session_test_status', HERE / 'status.py')
status = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(status)

WORLD = r'''
import fcntl, json, os, sys
from contextlib import contextmanager
from datetime import datetime, timezone
PATH = os.environ['FAKE_WORLD']
def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
@contextmanager
def world():
    with open(PATH + '.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with open(PATH) as f:
            w = json.load(f)
        try:
            yield w
        finally:
            with open(PATH + '.tmp', 'w') as f:
                json.dump(w, f)
            os.replace(PATH + '.tmp', PATH)
def records(w, n, start='launch-fleet: '):
    return [c['body'].split('\n')[0] for c in w['comments'].get(str(n), [])
            if c['user']['login'] == 'synthetic-owner' and c['body'].startswith(start)]
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
    if args[:2] == ['api', 'rate_limit']:
        if w['budget'] is None:
            sys.exit(1)
        reset = int(datetime.now(timezone.utc).timestamp()) + 3600
        pool = {'limit': 5000, 'remaining': w['budget'], 'reset': reset, 'used': 5000 - w['budget']}
        out({'resources': {'core': pool, 'graphql': pool}})
    path = next(a for a in args if a.startswith('repos/'))
    rest, method = path[len(base):].split('?')[0].split('/'), 'GET'
    if '--method' in args:
        method = args[args.index('--method') + 1]
    if rest == ['contents', 'docs', 'agents', 'fleet.md']:
        sys.stdout.write(w['fleet_md']); sys.exit(0)
    if rest == ['actions', 'runs']:
        wanted = path.split('status=')[1].split('&')[0]
        runs = [{'id': 900 + i} for i, job in enumerate(w['jobs']) if job['run_status'] == wanted]
        out([{'total_count': len(runs), 'workflow_runs': runs}])
    if rest[:2] == ['actions', 'runs'] and rest[3:] == ['jobs']:
        job = w['jobs'][int(rest[2]) - 900]
        out([{'total_count': 1, 'jobs': [{k: v for k, v in job.items() if k != 'run_status'}]}])
    if rest[0] == 'issues' and rest[2:] == ['sub_issues']:
        page = [{'number': int(n), 'state': t['state'].lower()} for n, t in sorted(w['tickets'].items())]
        out([page] if '--slurp' in args else page)
    if rest[0] == 'issues' and rest[2:] == ['comments'] and method == 'POST':
        w['next_id'] += 1
        c = {'id': w['next_id'], 'body': flag('body'), 'user': {'login': w['me']},
             'created_at': now(), 'updated_at': now()}
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

FAKE_FLEET = WORLD + r'''
args = sys.argv[1:]
if args[0] == 'claim':
    print('go #%s' % args[1]); sys.exit(0)
with world() as w:
    if args[0] == 'overload':
        os.execvp('sh', ['sh', os.environ['FAKE_REAL_FLEET'], *args])
    if not w['spec_open']:
        print('fleet done #%s: it is not an open spec; delete this fleet thread\'s loop and archive the thread'
              % w['spec'])
        sys.exit(0)
    for n, t in sorted(w['tickets'].items(), key=lambda x: int(x[0])):
        if t['state'] != 'OPEN':
            continue
        starts = records(w, n, ('launch-fleet: start', 'launch-fleet: started'))
        if int(n) in w['questions']:
            print('needs-info #%s: a question for the orchestrator' % n)
        elif not starts:
            if w['tickets'].get(w['blocked'].get(n, ''), {}).get('state', 'CLOSED') == 'CLOSED':
                print('start #%s: %s (spec #%s)' % (n, t['title'], w['spec']))
        elif starts[-1] == 'launch-fleet: started' and n in w['branches']:
            print('check start #%s: thread run:%s, branch %s' % (n, n, w['branches'][n]))
        for p, pr in sorted(w['prs'].items()):
            if pr['ticket'] != int(n) or pr['state'] != 'OPEN' or pr['checks'][0]['conclusion'] != 'SUCCESS':
                continue
            at = '#%s for #%s at %s' % (p, n, pr['head'])
            if records(w, p, 'VERDICT: APPROVE at ' + pr['head']):
                if not (args[0] == 'every' and p in w['every_hide']):
                    print('merge %s: APPROVE and CI green' % at)
            elif not records(w, p, 'launch-fleet: review start'):
                print('review %s: first review' % at)
    if w['tickets'] and all(t['state'] == 'CLOSED' for t in w['tickets'].values()):
        print('spec done #%s: every planned ticket is done; no follow-ups' % w['spec'])
'''

FAKE_MERGE = WORLD + r'''
args = sys.argv[1:]
with open(os.path.join(os.environ['HOME'], 'merge.log'), 'a') as log:
    log.write(json.dumps(args) + '\n')
with world() as w:
    pr = w['prs'][args[2]]
    if args[0] == 'admit':
        print('admit: the merge queue re-tests it' if w['queue'] else 'base rule: no merge queue; mergeable: MERGEABLE')
    elif args[0] == 'read' and args[3] != pr['head']:
        print('stop: #%s is at %s, not %s' % (args[2], pr['head'], args[3]))
    elif args[0] == 'read':
        print('merged ' + 'f' * 40 if pr['state'] == 'MERGED' else 'queued' if pr.get('queued') else
              'open, the merge queue is on; it left the queue at 2026-01-01T00:00:00Z: synthetic')
    elif w['queue']:
        pr['queued'] = True
        print('queued; recorded 1')
    else:
        pr['state'] = 'MERGED'
        w['tickets'][str(pr['ticket'])]['state'] = 'CLOSED'
        print('merged %s; cost posted 1' % ('f' * 40))
'''

HOLDER = r'''
import fcntl, os, sys, time
from pathlib import Path
folder = Path(sys.argv[1])
folder.mkdir(mode=0o700, parents=True)
fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
Path(sys.argv[2]).touch()
while not Path(sys.argv[3]).exists():
    time.sleep(0.01)
folder.rmdir()
os.close(fd)
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
        for name in ('host.py', 'post.py', 'status.py', 'brief.py', 'heartbeat.py', 'ops-starts.py', 'effects.py',
                     'records.py', 'grants.py'):
            (self.scripts / name).symlink_to(HERE / name)
        self.program(self.scripts / 'fleet.sh', FAKE_FLEET)
        (self.scripts / 'merge.py').write_text(FAKE_MERGE)
        self.program(self.home / 'bin/gh', FAKE_GH)
        for name in ('claude', 'codex'):
            self.program(self.home / 'bin' / name, 'import sys\nsys.exit(0)\n')
        driver.chmod(0o755)
        self.world = self.home / 'world.json'
        self.world.write_text(json.dumps({'repo': REPO, 'me': 'synthetic-owner', 'fleet_md': FLEET_MD,
                                          'next_id': 100, 'comments': {}, 'tickets': {}, 'prs': {},
                                          'branches': {}, 'questions': [], 'spec': SPEC, 'spec_open': True,
                                          'queue': False, 'every_hide': [], 'blocked': {}, 'budget': 5000,
                                          'jobs': []}))
        self.log = self.home / 'driver.log'
        path = [d for d in os.environ['PATH'].split(os.pathsep)
                if not any(os.path.exists(os.path.join(d, name)) for name in ('claude', 'codex'))]
        self.env = dict(git_env, HOME=str(self.home), PATH=os.pathsep.join([str(self.home / 'bin'), *path]),
                        FAKE_REAL_FLEET=str(HERE / 'fleet.sh'),
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

    def note(self, n, agent, pr=None, harness='Claude Code'):
        fields = {'agent': agent, 'state': 'done', 'harness': harness, 'model': 'Opus 5.5',
                  'skills': 'build-ticket@0.2.1', 'step': 'handed back', 'time': stamp()}
        if pr:
            fields['pr'] = 'https://github.com/%s/pull/%d' % (REPO, pr)
        self.comment(n, status.body(fields))

    def comment(self, n, body):
        def add(w):
            w['next_id'] += 1
            w['comments'].setdefault(str(n), []).append(
                {'id': w['next_id'], 'body': body, 'user': {'login': 'synthetic-owner'}, 'created_at': stamp()})
        self.change(add)

    def green(self, p, n):
        self.change(lambda w: w['prs'].update({str(p): {'ticket': n, 'head': HEAD, 'state': 'OPEN', 'checks': [
            {'__typename': 'CheckRun', 'name': 'check', 'status': 'COMPLETED', 'conclusion': 'SUCCESS'}]}}))

    def approved(self, verdict_first=False, assigned=HEAD, reviewer='Codex'):
        self.tickets(5)
        self.comment(5, 'launch-fleet: start checked, branch room/5-synthetic')
        self.note(5, 'builder', pr=12)
        self.green(12, 5)
        records = ['launch-fleet: review started %s\nDriver review: other-family' % assigned,
                   'VERDICT: APPROVE at ' + HEAD]
        for body in reversed(records) if verdict_first else records:
            self.comment(12, body)
        self.note(5, 'reviewer', harness=reviewer)

    def guard(self):
        now = int(time.time())
        pool = {'remaining': 1000, 'limit': 1000, 'reset_at': now + 3600, 'retry_after': 0}
        seen = self.home / 'observation.json'
        seen.write_text(json.dumps({'repository': REPO, 'observed_at': now, 'complete': True,
                                    'queue': {'complete': True, 'jobs': []},
                                    'budgets': {'rest': pool, 'graphql': pool}}))
        return {'LAUNCH_FLEET_OVERLOAD_INPUT': str(seen), 'LAUNCH_FLEET_OVERLOAD_STATE': str(self.home / 'pause.json')}

    def merges(self):
        path = self.home / 'merge.log'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

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

    def carry_on(self):
        return 'carry on: ' + shlex.join(['python3', '-I', str((self.scripts / 'session.py').resolve()),
                                          *self.command()[3:]])

    def session(self, *extra, **env):
        process = subprocess.Popen(self.command(*extra), cwd=self.home / 'checkout', env=dict(self.env, **env),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        return process

    def until(self, condition, what, process):
        end = time.monotonic() + 30
        while not condition():
            if process.poll() is not None:
                self.fail('the session ended before %s: %s' % (what, process.stdout.read() + process.stderr.read()))
            self.assertLess(time.monotonic(), end, 'timed out waiting for ' + what)
            time.sleep(0.02)

    def ended(self, process, code, timeout=30):
        out, err = process.communicate(timeout=timeout)
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
        self.assertIn(self.carry_on() + '\n', out)
        self.assertFalse(self.lock_dir.exists())

    def test_a_finished_build_gets_its_reviewer_and_an_approved_green_pull_request_merges(self):
        self.tickets(5)
        self.change(lambda w: w['branches'].update({'5': 'room/5-synthetic'}))
        process = self.session('--idle', '10')
        self.until(lambda: self.records(5) == ['launch-fleet: start checked, branch room/5-synthetic'], 'check',
                   process)
        self.green(12, 5)
        self.note(5, 'builder', pr=12)
        self.until(lambda: self.records(12)[:1] and self.records(12)[0].startswith(
            'launch-fleet: review started ' + HEAD), 'the reviewer', process)
        self.assertEqual(self.starts()[1], {'repository': REPO, 'ticket': 12, 'skill': 'review-ticket',
                                            'harness': 'codex', 'model': 'synthetic-table-reviewer'})
        self.assertEqual(self.records(12)[0].split('\n')[1], 'Driver review: other-family')
        self.assertEqual(self.merges(), [])
        time.sleep(1)
        self.comment(12, 'VERDICT: APPROVE at ' + HEAD)
        time.sleep(1)
        self.assertEqual(self.merges(), [])
        self.note(5, 'reviewer', harness='Codex')
        out = self.ended(process, 0)
        merges = self.merges()
        self.assertEqual([m[0] for m in merges], ['admit', 'merge'])
        self.assertEqual(merges[1][:5] + merges[1][6:], ['merge', REPO, '12', HEAD, 'check', '--ticket', '5',
                                                         '--base-rule-checked'])
        self.assertIn('#12 merged', out)
        self.assertIn('session: done: spec done #7: every planned ticket is done; no follow-ups\n', out)

    def test_a_spec_whose_planned_tickets_are_done_ends_the_session_as_done(self):
        self.tickets(5)
        self.change(lambda w: w['tickets']['5'].update(state='CLOSED'))
        out = self.ended(self.session(), 0)
        self.assertIn('session: done: spec done #7: every planned ticket is done; no follow-ups\n', out)

    def test_a_spec_gone_from_the_open_list_with_open_tickets_is_not_done(self):
        self.tickets(5)
        self.change(lambda w: w.update(spec_open=False))
        out = self.ended(self.session(), 3)
        self.assertIn('needs you: spec #7 is not an open spec, but its tickets are not all closed', out)
        self.change(lambda w: w['tickets']['5'].update(state='CLOSED'))
        out = self.ended(self.session(), 0)
        self.assertIn('session: done: every ticket of spec #7 is closed\n', out)

    def test_an_approval_from_before_the_current_review_assignment_merges_nothing(self):
        self.approved(verdict_first=True)
        out = self.ended(self.session(**self.guard()), 3)
        self.assertIn("needs you: #12 was not merged: its newest VERDICT is older than its current review "
                      "assignment", out)
        self.assertNotIn('merge', [m[0] for m in self.merges()])

    def test_a_merge_waits_when_the_overload_guard_pauses_or_cannot_see(self):
        self.approved()
        self.change(lambda w: w['jobs'].append({'id': 77, 'name': 'check', 'status': 'queued', 'run_status': 'queued',
                                                'created_at': '2026-01-01T00:00:00Z', 'started_at': None}))
        out = self.ended(self.session(), 3)
        self.assertIn('needs you: fleet.sh overload merge-batch did not admit a merge batch: paused: escalate '
                      '(required_job_wait)', out)
        self.change(lambda w: w.update(jobs=[]))
        out = self.ended(self.session(), 3)
        self.assertIn('did not admit a merge batch: paused: escalate (required_job_wait)', out)
        self.assertEqual(self.merges(), [])

    def test_a_merge_waits_when_the_overload_observation_is_unknown(self):
        self.approved()
        self.change(lambda w: w.update(budget=None))
        out = self.ended(self.session(), 3)
        self.assertIn('did not admit a merge batch: paused: unknown (observation_unknown)', out)
        self.assertEqual(self.merges(), [])

    def test_an_approval_for_another_head_or_from_another_reviewer_merges_nothing(self):
        self.approved(assigned='b' * 40)
        out = self.ended(self.session(**self.guard()), 3)
        self.assertIn('needs you: #12 was not merged: its current review assignment is not for ' + HEAD, out)
        self.assertNotIn('merge', [m[0] for m in self.merges()])

    def test_an_approval_without_the_selected_reviewers_note_merges_nothing(self):
        self.approved(reviewer='Claude Code')
        out = self.ended(self.session(**self.guard()), 3)
        self.assertIn("needs you: #12 was not merged: no done note from its selected codex reviewer", out)
        self.assertNotIn('merge', [m[0] for m in self.merges()])

    def test_a_landing_during_a_working_build_unblocks_the_next_ticket(self):
        self.approved()
        self.tickets(6, 7)
        self.comment(6, 'launch-fleet: started')
        self.change(lambda w: w.update(queue=True, blocked={'7': '5'}))
        process = self.session('--idle', '8', **self.guard())
        self.until(lambda: json.loads(self.world.read_text())['prs']['12'].get('queued'), 'the queue', process)
        time.sleep(1)

        def land(w):
            w['prs']['12']['state'] = 'MERGED'
            w['tickets']['5']['state'] = 'CLOSED'
        self.change(land)
        self.until(lambda: self.records(7) == ['launch-fleet: started'], 'the unblocked start', process)
        time.sleep(0.5)
        process.send_signal(signal.SIGINT)
        out = self.ended(process, 130)
        self.assertIn('#12 merged', out)

    def test_an_old_queue_receipt_does_not_hold_a_corrected_head(self):
        self.tickets(5)
        self.comment(5, 'launch-fleet: start checked, branch room/5-synthetic')
        self.note(5, 'builder', pr=12)
        self.green(12, 5)
        self.comment(12, 'launch-fleet: merge queued %s: synthetic' % ('b' * 40))
        process = self.session()
        self.until(lambda: self.records(12)[-1:] and self.records(12)[-1].startswith(
            'launch-fleet: review started ' + HEAD), 'the reviewer of the corrected head', process)
        process.send_signal(signal.SIGINT)
        self.ended(process, 130)

    def test_the_models_rule_can_make_a_review_wait(self):
        self.tickets(5)
        self.comment(5, 'launch-fleet: start checked, branch room/5-synthetic')
        self.note(5, 'builder', pr=12)
        self.green(12, 5)
        self.change(lambda w: w.update(fleet_md=w['fleet_md'].replace(MODELS % ('Codex', 'codex'),
                                                                      MODELS % ('Claude Code', 'claude-code'))))
        out = self.ended(self.session('--idle', '5'), 3)
        self.assertIn('needs you: the review of #12 waits: ops-starts: review_of_claude_built waits', out)
        self.assertEqual(self.starts(), [])

    def test_with_one_harness_the_reviewer_uses_the_checked_builders_model(self):
        (self.home / 'bin/codex').unlink()
        self.tickets(5)
        self.comment(5, 'launch-fleet: start checked, branch room/5-synthetic')
        self.note(5, 'builder', pr=12)
        self.green(12, 5)
        process = self.session()
        self.until(lambda: self.starts(), 'the reviewer', process)
        self.assertEqual(self.starts(), [{'repository': REPO, 'ticket': 12, 'skill': 'review-ticket',
                                          'harness': 'claude', 'model': 'synthetic-table-builder'}])
        self.until(lambda: self.records(12)[:1] and self.records(12)[0].startswith('launch-fleet: review started'),
                   'the record', process)
        self.assertEqual(self.records(12)[0].split('\n')[1], 'Driver review: same-family')
        process.send_signal(signal.SIGINT)
        self.ended(process, 130)

    def test_without_a_queue_a_merge_line_missing_from_every_merges_nothing(self):
        self.approved()
        self.change(lambda w: w['every_hide'].append('12'))
        out = self.ended(self.session(**self.guard()), 3)
        self.assertIn('needs you: #12 was not merged: fleet.sh every no longer prints its merge line', out)
        self.assertEqual([m[0] for m in self.merges()], ['admit'])

    def test_a_queued_merge_is_reported_merged_only_once_it_lands(self):
        self.approved()
        self.change(lambda w: w.update(queue=True))
        process = self.session(**self.guard())
        self.until(lambda: json.loads(self.world.read_text())['prs']['12'].get('queued'), 'the queue', process)
        time.sleep(0.5)
        self.assertIsNone(process.poll())

        def land(w):
            w['prs']['12']['state'] = 'MERGED'
            w['tickets']['5']['state'] = 'CLOSED'
        self.change(land)
        out = self.ended(process, 0)
        self.assertIn('#12 queued', out)
        self.assertLess(out.index('#12 queued'), out.index('#12 merged'))
        self.assertEqual(out.count('#12 merged'), 1)
        self.assertIn('session: done: spec done #7', out)

    def test_the_reviewer_is_the_other_family_of_the_checked_builder(self):
        self.tickets(5)
        self.comment(5, 'launch-fleet: start checked, branch room/5-synthetic')
        self.note(5, 'builder', pr=12, harness='Codex')
        self.green(12, 5)
        process = self.session()
        self.until(lambda: self.records(12)[:1] and self.records(12)[0].startswith(
            'launch-fleet: review started ' + HEAD), 'the reviewer', process)
        self.assertEqual(self.starts(), [{'repository': REPO, 'ticket': 12, 'skill': 'review-ticket',
                                          'harness': 'claude', 'model': 'synthetic-table-builder'}])
        self.assertEqual(self.records(12)[0].split('\n')[1], 'Driver review: other-family')
        process.send_signal(signal.SIGINT)
        self.ended(process, 130)

    def test_a_resumed_session_counts_the_builders_still_running(self):
        self.tickets(1, 2, 3, 4)
        for n in (1, 2, 3):
            self.comment(n, 'launch-fleet: started')
        process = self.session()
        time.sleep(1)
        self.assertIsNone(process.poll(), process.poll() is not None and process.communicate())
        self.assertEqual((self.records(4), self.starts()), ([], []))
        self.note(1, 'builder')
        self.until(lambda: self.records(4) == ['launch-fleet: started'], 'the fourth start', process)
        process.send_signal(signal.SIGINT)
        self.ended(process, 130)

    def test_an_interrupt_during_a_start_stops_at_once_and_the_start_finishes(self):
        self.tickets(3)
        hold = self.home / 'hold'
        hold.touch()
        process = self.session(FAKE_DRIVER_HOLD=str(hold))
        self.until(lambda: len(self.starts()) == 1, 'the start', process)
        time.sleep(0.3)
        process.send_signal(signal.SIGINT)
        out = self.ended(process, 130, timeout=10)
        self.assertIn('session: stopped on interrupt at tick 1', out)
        self.assertIn("#3's start had not answered", out)
        self.assertIn(self.carry_on() + '\n', out)
        self.assertFalse(self.lock_dir.exists())
        hold.unlink()
        runs = self.home / '.local/state/openwiz-heartbeat' / (
            'runs-%s.json' % hashlib.sha256(REPO.lower().encode()).hexdigest()[:20])
        end = time.monotonic() + 20
        while not (runs.exists() and 'local-run-3' in runs.read_text()):
            self.assertLess(time.monotonic(), end, 'the interrupted start never finished')
            time.sleep(0.05)
        while str(self.scripts / 'host.py') in subprocess.run(['ps', '-eo', 'args'], capture_output=True,
                                                              text=True).stdout:
            self.assertLess(time.monotonic(), end, 'the interrupted start never exited')
            time.sleep(0.05)
        self.assertEqual(self.records(3), ['launch-fleet: starting'])

    def test_a_run_that_ends_before_its_start_answers_still_counts_as_ended(self):
        self.tickets(3)
        hold = self.home / 'hold'
        hold.touch()
        process = self.session('--idle', '20', FAKE_DRIVER_HOLD=str(hold))
        self.until(lambda: len(self.starts()) == 1, 'the start', process)
        self.note(3, 'builder')
        time.sleep(1.1)
        hold.unlink()
        out = self.ended(process, 3)
        self.assertIn('needs you: nothing is due on spec #7 and no run or check is going\n', out)

    def test_checks_that_never_finish_stop_the_session_after_idle(self):
        self.tickets(4)
        process = self.session('--idle', '1')
        self.until(lambda: self.records(4) == ['launch-fleet: started'], 'the start', process)
        self.change(lambda w: w['prs'].update({'13': {'ticket': 4, 'head': HEAD, 'state': 'OPEN', 'checks': [
            {'__typename': 'CheckRun', 'name': 'check', 'status': 'IN_PROGRESS', 'conclusion': None}]}}))
        self.note(4, 'builder', pr=13)
        out = self.ended(process, 3)
        self.assertIn('needs you: nothing moved on spec #7 for 1 seconds\n', out)

    def test_a_question_stops_the_session_before_anything_starts(self):
        self.tickets(8, 9)
        self.change(lambda w: w['questions'].append(8))
        out = self.ended(self.session(), 3)
        self.assertIn('session: stopped at tick 1: needs you: needs-info #8: a question for the orchestrator\n',
                      out)
        self.assertIn(self.carry_on() + '\n', out)
        self.assertEqual(self.starts(), [])

    def test_a_refused_start_stops_the_session_and_records_the_refusal(self):
        self.tickets(9)
        out = self.ended(self.session(FAKE_DRIVER_MODE='refuse'), 3)
        self.assertIn("session: stopped at tick 1: needs you: stopped (driver start failed): the local driver "
                      "refused #9's start 3 times", out)
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
        fd = os.open(self.lock_dir, os.O_RDONLY | os.O_DIRECTORY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            third = subprocess.run(self.command(), cwd=self.home / 'checkout', env=self.env, capture_output=True,
                                   text=True, timeout=30)
        finally:
            os.close(fd)
        self.assertEqual((third.returncode, third.stdout),
                         (1, 'session: refused: a session or heartbeat tick already runs spec #7\n'))
        self.assertEqual(len(self.starts()), 1)

    def test_a_lock_folder_removed_under_a_contender_is_not_a_second_lock(self):
        holder, ready, release = self.home / 'holder.py', self.home / 'ready', self.home / 'release'
        holder.write_text(HOLDER)
        owner = subprocess.Popen([sys.executable, '-I', str(holder), str(self.lock_dir), str(ready), str(release)])
        self.addCleanup(lambda: owner.poll() is None and owner.kill())
        end = time.monotonic() + 10
        while not ready.exists():
            self.assertLess(time.monotonic(), end)
            time.sleep(0.01)
        spec = importlib.util.spec_from_file_location('session_under_test', HERE / 'session.py')
        session = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(session)
        session.STATE = self.lock_dir.parent
        real, calls = os.open, []

        def handoff(path, *rest, **kw):
            fd = real(path, *rest, **kw)
            if Path(path) == self.lock_dir and not calls:
                calls.append(path)
                release.touch()
                owner.wait(timeout=10)
            return fd
        with mock.patch.object(os, 'open', handoff):
            with session.lock(REPO, SPEC):
                pass_through = os.open
                with mock.patch.object(os, 'open', real):
                    third = subprocess.run(self.command(), cwd=self.home / 'checkout', env=self.env,
                                           capture_output=True, text=True, timeout=30)
                self.assertIs(os.open, pass_through)
        self.assertEqual(calls, [self.lock_dir])
        self.assertEqual((third.returncode, third.stdout),
                         (1, 'session: refused: a session or heartbeat tick already runs spec #7\n'))


if __name__ == '__main__':
    unittest.main()
