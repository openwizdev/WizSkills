#!/usr/bin/env python3
import fcntl
import json
import os
import runpy
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent
git_origin = runpy.run_path(str(HERE / 'fixtures/git_origin.py'))['env']
REPO = 'synthetic-owner/synthetic-repo'
FLEET_MD = ('# Fleet settings\n\n## GitHub identity\n\n| Setting | Value |\n| --- | --- |\n'
            '| Record authors | `openwiz[bot]`, `synthetic-owner` |\n')


class World:

    def __init__(self, test, **extra):
        self.dir = Path(tempfile.mkdtemp())
        test.addCleanup(subprocess.run, ['rm', '-rf', str(self.dir)])
        bin_dir = self.dir / 'bin'
        bin_dir.mkdir()
        gh = bin_dir / 'gh'
        gh.write_text('#!/bin/sh\nexec "%s" -I "%s" "$@"\n' % (sys.executable, HERE / 'fixtures/fake_github.py'))
        gh.chmod(0o755)
        for name in ('room-cli', 'claude', 'codex', 'boat'):
            (bin_dir / name).write_text('#!/bin/sh\necho "stub: no %s in tests" >&2\nexit 1\n' % name)
            (bin_dir / name).chmod(0o755)
        self.path = self.dir / 'world.json'
        value = {'repo': REPO, 'me': 'openwiz[bot]', 'fleet_md': FLEET_MD, 'next_id': 5000,
                 'comments': {}, 'writes': [], 'faults': {}}
        value.update(extra)
        self.save(value)
        self.env = dict(os.environ, PATH='%s:%s' % (bin_dir, os.environ['PATH']), FAKE_WORLD=str(self.path))
        self.env['XDG_STATE_HOME'] = str(self.dir / 'state')
        self.env.update(git_origin(self.dir, {value['repo']: value['fleet_md']}))

    def load(self):
        return json.loads(self.path.read_text())

    def save(self, value):
        self.path.write_text(json.dumps(value))

    def update(self, **changes):
        value = self.load()
        value.update(changes)
        self.save(value)

    def run(self, script, *args, cwd=None):
        r = subprocess.run([sys.executable, '-I', str(HERE / script), *map(str, args)], capture_output=True,
                           text=True, env=self.env, cwd=cwd or self.dir, timeout=60)
        return r.returncode, r.stdout.strip()

    def writes(self):
        return self.load()['writes']

    def bodies(self, number):
        return [c['body'] for c in self.load()['comments'].get(str(number), [])]

    def log_gh_calls(self, hide_post_on=None):
        log, hide = self.dir / 'calls.log', self.dir / 'hide.py'
        hide.write_text('import json, os, sys\nw = json.load(open(os.environ["FAKE_WORLD"]))\n'
                        'w["comments"][sys.argv[1]] = []\njson.dump(w, open(os.environ["FAKE_WORLD"], "w"))\n')
        drop = ('' if hide_post_on is None else 'case " $* " in *" POST repos/%s/issues/%d/comments "*) "%s" -I "%s" %d;; esac\n'
                % (REPO, hide_post_on, sys.executable, hide, hide_post_on))
        (self.dir / 'bin' / 'gh').write_text(
            '#!/bin/sh\nprintf "%%s\\n" "$*" >> "%s"\n"%s" -I "%s" "$@"\ncode=$?\n%sexit $code\n'
            % (log, sys.executable, HERE / 'fixtures/fake_github.py', drop))
        self.calls_log = log

    def comment_route_calls(self):
        out = []
        for line in self.calls_log.read_text().splitlines():
            words = line.split(' ')
            route = next(w for w in words if w.startswith('repos/')).split('?')[0].split('/')
            if route[3:4] == ['issues'] and route[5:] == ['comments']:
                method = words[words.index('--method') + 1] if '--method' in words else 'GET'
                out.append((method, int(route[4])))
        return out


def comment(cid, body, login='openwiz[bot]'):
    return {'id': cid, 'body': body, 'user': {'login': login}, 'created_at': '2026-01-01T00:00:00Z'}


class Post(unittest.TestCase):
    def test_a_record_is_posted_once_and_read_back(self):
        w = World(self)
        code, out = w.run('post.py', 'comment', REPO, 12, 'launch-fleet: starting')
        self.assertEqual((code, out), (0, 'posted 5001'))
        self.assertEqual(w.bodies(12), ['launch-fleet: starting'])
        self.assertEqual(len(w.writes()), 1)

    def test_private_identities_are_refused_with_zero_writes(self):
        w = World(self)
        for body in ('launch-fleet: started, thread thr_synthetic1',
                     'launch-fleet: look: builder thr' + '_synabc and thr' + '_syndef both match',
                     'launch-fleet: started\n\nwith gho_synthetictoken0123456789',
                     '**Needs you:** loop loop_synthetic9 refused'):
            with self.subTest(body=body):
                code, out = w.run('post.py', 'comment', REPO, 12, body)
                self.assertEqual(code, 1)
                self.assertTrue(out.startswith('refused: '), out)
        self.assertEqual(w.writes(), [])

    def test_only_fleet_records_are_posted(self):
        w = World(self)
        for body in ('Looks good to me', '', 'VERDICT: APPROVE at ' + 'a' * 40, ' launch-fleet starting'):
            with self.subTest(body=body):
                code, out = w.run('post.py', 'comment', REPO, 12, body)
                self.assertEqual(code, 1)
                self.assertTrue(out.startswith('refused: '), out)
        self.assertEqual(w.writes(), [])
        self.assertEqual(w.run('post.py', 'comment', REPO, 3, '**Needs you:** spec #3 changed since revision 2')[0], 0)

    def test_a_lost_response_is_unknown_and_left_for_reconciliation(self):
        w = World(self, comments={'12': [comment(4000, 'launch-fleet: starting')]}, faults={'post': 'lost'})
        code, out = w.run('post.py', 'comment', REPO, 12, 'launch-fleet: starting')
        self.assertEqual((code, out.split(' ')[0]), (1, 'unknown:'), out)
        self.assertEqual(len(w.writes()), 1)

    def test_another_wakes_identical_record_is_never_adopted(self):
        w = World(self, faults={'post': 'fail'})
        inject = w.dir / 'other_wake.py'
        inject.write_text('import json, os\nw = json.load(open(os.environ["FAKE_WORLD"]))\n'
                          'w["comments"].setdefault("12", []).append(%r)\n'
                          'json.dump(w, open(os.environ["FAKE_WORLD"], "w"))\n' % comment(8001, 'launch-fleet: starting'))
        gh = w.dir / 'bin' / 'gh'
        head, rest = gh.read_text().split('\n', 1)
        gh.write_text('%s\ncase " $* " in *" POST "*) "%s" -I "%s";; esac\n%s' % (head, sys.executable, inject, rest))
        code, out = w.run('post.py', 'comment', REPO, 12, 'launch-fleet: starting')
        self.assertEqual((code, out.split(' ')[0]), (1, 'unknown:'), out)

    def test_a_failed_write_is_unknown_never_posted(self):
        w = World(self, faults={'post': 'fail'})
        code, out = w.run('post.py', 'comment', REPO, 12, 'launch-fleet: starting')
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('unknown: '), out)

    def test_identical_text_from_anyone_else_is_not_the_record(self):
        w = World(self, me='someone-else')
        code, out = w.run('post.py', 'comment', REPO, 12, 'launch-fleet: starting')
        self.assertEqual((code, out), (1, 'unknown: the record on #12 could not be read back; read #12 before any retry'))
        self.assertEqual(w.writes(), [{'post': 12, 'body': 'launch-fleet: starting'}])
        self.assertEqual([(c['id'], c['user']['login']) for c in w.load()['comments']['12']], [(5001, 'someone-else')])

    def test_without_record_authors_nothing_is_trusted(self):
        for fleet_md in (None, '# Fleet settings\n', FLEET_MD.replace('`openwiz[bot]`, ', '`openwiz[bot]` ')):
            with self.subTest(fleet_md=fleet_md):
                w = World(self, fleet_md=fleet_md)
                code, out = w.run('post.py', 'comment', REPO, 12, 'launch-fleet: starting')
                self.assertEqual(code, 1)
                self.assertTrue(out.startswith('refused: '), out)
                self.assertEqual(w.writes(), [])

    def test_an_edit_is_read_back(self):
        w = World(self, comments={'12': [comment(4000, 'launch-fleet: starting')]})
        self.assertEqual(w.run('post.py', 'edit', REPO, 4000, 'launch-fleet: started'), (0, 'edited 4000'))
        self.assertEqual(w.bodies(12), ['launch-fleet: started'])

    def test_a_lost_edit_is_recovered_and_a_failed_one_is_unknown(self):
        w = World(self, comments={'12': [comment(4000, 'launch-fleet: starting')]}, faults={'patch': 'lost'})
        self.assertEqual(w.run('post.py', 'edit', REPO, 4000, 'launch-fleet: started'), (0, 'edited 4000'))
        w.update(faults={'patch': 'fail'})
        code, out = w.run('post.py', 'edit', REPO, 4000, 'launch-fleet: start checked, branch room/12-x')
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('unknown: '), out)

    def test_another_authors_comment_is_never_edited(self):
        w = World(self, comments={'12': [comment(4000, 'launch-fleet: starting', login='someone-else')]})
        code, out = w.run('post.py', 'edit', REPO, 4000, 'launch-fleet: started')
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('refused: '), out)
        self.assertEqual(w.writes(), [])



class SelfGrant(unittest.TestCase):

    def test_each_kind_is_recorded_with_its_reason(self):
        w = World(self)
        cases = [('supporting-edit', 'two lines in check/run.py, which runs the new test',
                  'launch-fleet: granted supporting edit: two lines in check/run.py, which runs the new test'),
                 ('dependency-wiring', 'the spec-approved pinned parser in the build file',
                  'launch-fleet: granted dependency wiring: the spec-approved pinned parser in the build file'),
                 ('read-route', 'the issue timeline, under the API rules',
                  'launch-fleet: granted read route: the issue timeline, under the API rules')]
        for kind, reason, body in cases:
            with self.subTest(kind=kind):
                self.assertEqual(w.run('self-grant.py', REPO, 12, kind, reason)[0], 0)
                self.assertEqual(w.bodies(12)[-1:], [body])
        code, out = w.run('self-grant.py', REPO, 12, 'spec-change', 'the proof table names the after bench', '--spec', 3)
        self.assertEqual(code, 0, out)
        self.assertEqual(w.bodies(3), ['launch-fleet: spec changed for #12: the proof table names the after bench'])
        self.assertEqual(w.bodies(12)[-1], 'launch-fleet: granted spec change on #3: the proof table names the after bench')
        self.assertEqual(len(w.writes()), 5)

    def test_the_spec_record_reads_back_before_the_ticket_grant_is_posted(self):
        w = World(self)
        w.log_gh_calls()
        code, out = w.run('self-grant.py', REPO, 12, 'spec-change', 'the proof names the after bench', '--spec', 3)
        self.assertEqual(code, 0, out)
        self.assertEqual(w.comment_route_calls(), [('GET', 3), ('POST', 3), ('GET', 3), ('GET', 12), ('POST', 12), ('GET', 12)])

    def test_a_posted_spec_change_missing_from_read_back_posts_no_grant(self):
        w = World(self)
        w.log_gh_calls(hide_post_on=3)
        code, out = w.run('self-grant.py', REPO, 12, 'spec-change', 'the proof names the after bench', '--spec', 3)
        self.assertEqual((code, out), (1, 'unknown: the record on #3 could not be read back; read #3 before any retry'))
        self.assertEqual(w.writes(), [{'post': 3, 'body': 'launch-fleet: spec changed for #12: the proof names the after bench'}])
        self.assertEqual(w.comment_route_calls(), [('GET', 3), ('POST', 3), ('GET', 3)])

    def test_a_model_or_effort_change_or_any_other_ask_is_refused(self):
        w = World(self)
        for kind, why in (('model', 'refused: a model or effort change is never a self-grant; ask Jake'),
                          ('effort', 'refused: a model or effort change is never a self-grant; ask Jake'),
                          ('contract', 'refused: not a self-grant kind; ask the orchestrator'),
                          ('spend', 'refused: not a self-grant kind; ask the orchestrator')):
            with self.subTest(kind=kind):
                self.assertEqual(w.run('self-grant.py', REPO, 12, kind, 'a stronger fixer round'), (1, why))
        for args in ((REPO, 12, 'spec-change', 'no spec named'), (REPO, 12, 'read-route', ''),
                     (REPO, 12, 'read-route', 'two\nlines'), (REPO, 12, 'read-route', 'x', '--spec', 12)):
            with self.subTest(args=args):
                self.assertEqual(w.run('self-grant.py', *args)[0], 2)
        self.assertEqual(w.writes(), [])

    def test_a_spec_change_not_read_back_records_no_grant(self):
        w = World(self, faults={'post': 'fail'})
        code, out = w.run('self-grant.py', REPO, 12, 'spec-change', 'the proof names the after bench', '--spec', 3)
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('unknown: '), out)
        self.assertEqual(w.bodies(12), [])


STATE = 'launch-fleet/writes.json'
SECONDARY = ('{"message": "You have exceeded a secondary rate limit and have been temporarily blocked from '
             'content creation. Please retry your request again later."}')


def paced_world(test, login='synthetic-owner', post_answer=None):
    w = World(test)
    gh = w.dir / 'bin' / 'gh'
    fake = gh.read_text().split('\n', 1)[1]
    answer = ''
    if post_answer is not None:
        status, headers = post_answer[:2]
        said = post_answer[2] if len(post_answer) > 2 else SECONDARY
        reply = w.dir / 'reply.txt'
        reply.write_text('%s\r\n%s\r\n%s' % (status, ''.join(h + '\r\n' for h in headers), said))
        answer = ('case " $* " in *" POST "*) if [ ! -e "%s.used" ]; then : > "%s.used"; cat "%s"; '
                  'echo "gh: request failed (%s)" >&2; exit 1; fi;; esac\n' % (reply, reply, reply, status.split()[1]))
    gh.write_text('#!/bin/sh\n%s%s' % (answer, fake))
    (w.dir / 'gh').mkdir()
    (w.dir / 'gh' / 'hosts.yml').write_text('github.com:\n    git_protocol: https\n    users:\n        %s:\n'
                                            '    user: %s\n' % (login, login))
    w.env['GH_CONFIG_DIR'] = str(w.dir / 'gh')
    for name in ('GH_TOKEN', 'GITHUB_TOKEN'):
        w.env.pop(name, None)
    return w


RUNNER = ('import importlib.util, os, sys\n'
          'spec = importlib.util.spec_from_file_location("post", sys.argv[1])\n'
          'post = importlib.util.module_from_spec(spec)\n'
          'spec.loader.exec_module(post)\n'
          'exec(sys.argv[2])\n'
          'sys.exit(post.main(sys.argv[3:]))\n')


def patched(w, code, *args):
    return subprocess.Popen([sys.executable, '-I', '-c', RUNNER, str(HERE / 'post.py'), code, *map(str, args)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=w.env, cwd=w.dir)


def state(w):
    path = w.dir / 'state' / STATE
    return json.loads(path.read_text()) if path.exists() else {'accounts': {}, 'inflight': [], 'until': 0}


def seed(w, value):
    path = w.dir / 'state' / STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def post_stamp(at):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(at))


def full(times, account='shared', inflight=(), until=0):
    return {'accounts': {account: list(times)}, 'inflight': [list(e) for e in inflight], 'until': until}


class Pacer(unittest.TestCase):

    def test_host_projects_keep_writer_state_and_clis_inside_the_project(self):
        p = runpy.run_path(str(HERE / 'test-host.py'))['Project'](self, hosts=('local',))
        self.assertEqual(p.env.get('XDG_STATE_HOME'), str(p.dir / 'state'))
        for name in ('room-cli', 'claude', 'codex', 'boat'):
            found = subprocess.run(['sh', '-c', 'command -v "$1"', 'sh', name], env=p.env, capture_output=True,
                                   text=True).stdout.strip()
            self.assertEqual(found, str(p.dir / 'stubs' / name))
            run = subprocess.run([found or name, 'start'], env=p.env, capture_output=True, text=True)
            self.assertEqual((run.returncode, run.stdout), (1, ''))

    def test_agent_and_host_clis_resolve_to_stubs_inside_the_world(self):
        w = World(self)
        for name in ('room-cli', 'claude', 'codex', 'boat'):
            found = subprocess.run(['sh', '-c', 'command -v "$1"', 'sh', name], env=w.env, capture_output=True,
                                   text=True).stdout.strip()
            self.assertEqual(found, str(w.dir / 'bin' / name))
            run = subprocess.run([found or name, 'start'], env=w.env, capture_output=True, text=True)
            self.assertEqual((run.returncode, run.stdout), (1, ''))

    def test_a_full_minute_bucket_refuses_without_writing(self):
        w = paced_world(self)
        now = time.time()
        seed(w, full(now - 1 - i * 0.1 for i in range(60)))
        code, out = w.run('post.py', 'comment', REPO, 12, 'launch-fleet: starting')
        self.assertEqual(code, 1)
        self.assertRegex(out, r'^refused: write paced, retry after \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$')
        self.assertEqual(w.writes(), [])
        self.assertEqual(len(state(w)['accounts'].get('shared', [])), 60)

    def test_a_full_hour_bucket_refuses_without_writing(self):
        w = paced_world(self)
        now = time.time()
        seed(w, full(now - 120 - i for i in range(400)))
        code, out = w.run('post.py', 'comment', REPO, 12, 'launch-fleet: starting')
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('refused: write paced, retry after '), out)
        self.assertEqual(w.writes(), [])

    def test_writes_are_bucketed_by_the_credential_gh_uses_not_the_stored_login(self):
        w = paced_world(self)
        w.env['GH_TOKEN'] = 'synthetic-credential-a'
        self.assertEqual(w.run('post.py', 'comment', REPO, 12, 'launch-fleet: starting'), (0, 'posted 5001'))
        [key_a] = state(w)['accounts']
        now = time.time()
        seed(w, {'accounts': {key_a: [now - 1] * 60}, 'inflight': [], 'until': 0})
        w.env['GH_TOKEN'] = 'synthetic-credential-b'
        self.assertEqual(w.run('post.py', 'comment', REPO, 12, 'launch-fleet: started'), (0, 'posted 5002'))
        self.assertEqual(len(state(w)['accounts']), 2)
        refused = []
        for env in ({'GH_TOKEN': 'synthetic-credential-a'},
                    {'GH_TOKEN': 'synthetic-credential-a', 'GITHUB_TOKEN': 'synthetic-credential-b'},
                    {'GITHUB_TOKEN': 'synthetic-credential-a'}):
            for name in ('GH_TOKEN', 'GITHUB_TOKEN'):
                w.env.pop(name, None)
            w.env.update(env)
            code, out = w.run('post.py', 'comment', REPO, 12, 'launch-fleet: started')
            refused.append((code, out.split(' ')[0]))
            self.assertNotIn('synthetic-credential', out)
        self.assertEqual(refused, [(1, 'refused:')] * 3)
        self.assertEqual(len(w.writes()), 2)
        text = (w.dir / 'state' / STATE).read_text()
        self.assertNotIn('synthetic-credential', text)
        self.assertNotIn('synthetic-owner', text)

    def test_writes_with_no_known_credential_share_one_bucket(self):
        w = paced_world(self, login='synthetic-first')
        self.assertEqual(w.run('post.py', 'comment', REPO, 12, 'launch-fleet: starting'), (0, 'posted 5001'))
        [key] = state(w)['accounts']
        now = time.time()
        seed(w, {'accounts': {key: [now - 1] * 60}, 'inflight': [], 'until': 0})
        (w.dir / 'gh' / 'hosts.yml').write_text('github.com:\n    user: synthetic-second\n')
        code, out = w.run('post.py', 'comment', REPO, 12, 'launch-fleet: started')
        self.assertEqual((code, out.split(' ')[0]), (1, 'refused:'), out)
        self.assertEqual(len(w.writes()), 1)

    def test_a_slot_freeing_inside_the_window_is_waited_for_then_written(self):
        w = paced_world(self)
        now = time.time()
        oldest = now - 58
        seed(w, full([oldest] + [now - 1] * 59))
        self.assertEqual(w.run('post.py', 'comment', REPO, 12, 'launch-fleet: starting'), (0, 'posted 5001'))
        times = state(w)['accounts'].get('shared', [])
        self.assertEqual(len(times), 61)
        self.assertGreaterEqual(max(times), oldest + 60)
        self.assertEqual(len(w.writes()), 1)
        self.assertEqual(state(w)['inflight'], [])

    def test_a_secondary_limit_retry_after_is_waited_out_by_the_next_process(self):
        w = paced_world(self, post_answer=('HTTP/2.0 403 Forbidden', ['Retry-After: 2', 'X-Ratelimit-Remaining: 4000']))
        before = time.time()
        code, out = w.run('post.py', 'comment', REPO, 12, 'launch-fleet: starting')
        self.assertEqual((code, out.split(' ')[0]), (1, 'unknown:'), out)
        self.assertIn('secondary', out)
        self.assertEqual(w.writes(), [])
        until = state(w)['until']
        self.assertGreaterEqual(until, before + 2)
        self.assertEqual(w.run('post.py', 'comment', REPO, 12, 'launch-fleet: starting'), (0, 'posted 5001'))
        self.assertGreaterEqual(max(state(w)['accounts'].get('shared', [])), until)
        self.assertEqual(len(w.writes()), 1)

    def test_a_long_secondary_wait_refuses_every_write_without_writing(self):
        for status, headers in (('HTTP/2.0 403 Forbidden', ['Retry-After: 120']),
                                ('HTTP/2.0 429 Too Many Requests', [])):
            with self.subTest(status=status):
                w = paced_world(self, post_answer=(status, headers))
                w.update(comments={'12': [comment(4000, 'launch-fleet: starting')]})
                before = time.time()
                self.assertEqual(w.run('post.py', 'comment', REPO, 12, 'launch-fleet: starting')[0], 1)
                self.assertGreaterEqual(state(w)['until'], before + 60)
                code, out = w.run('post.py', 'comment', REPO, 12, 'launch-fleet: started')
                self.assertEqual(code, 1)
                self.assertTrue(out.startswith('refused: write paced, retry after '), out)
                code, out = w.run('post.py', 'edit', REPO, 4000, 'launch-fleet: started')
                self.assertEqual(code, 1)
                self.assertTrue(out.startswith('refused: write paced, retry after '), out)
                self.assertEqual(w.writes(), [])

    def test_a_plain_403_records_no_wait(self):
        w = paced_world(self, post_answer=('HTTP/2.0 403 Forbidden', ['Content-Type: application/json'],
                                           '{"message": "Resource not accessible by integration"}'))
        earlier = time.time() - 5
        seed(w, full([], until=earlier))
        code, out = w.run('post.py', 'comment', REPO, 12, 'launch-fleet: starting')
        self.assertEqual(code, 1)
        self.assertNotIn('secondary', out)
        self.assertEqual(state(w)['until'], earlier)
        self.assertEqual(w.run('post.py', 'comment', REPO, 12, 'launch-fleet: starting'), (0, 'posted 5001'))
        self.assertEqual(state(w)['until'], earlier)

    def test_a_secondary_limit_holds_the_slot_until_its_wait_is_saved(self):
        w = paced_world(self, post_answer=('HTTP/2.0 403 Forbidden', ['Retry-After: 120']))
        w.update(comments={'12': [comment(4000, 'launch-fleet: starting')]})
        holder = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(60)'])
        self.addCleanup(holder.kill)
        seed(w, full([], inflight=[(holder.pid, time.time())] * 19))
        queued = ('import contextlib, subprocess\n'
                  'plain = post.pacer_state\n'
                  'queued = []\n'
                  '@contextlib.contextmanager\n'
                  'def watched(*a, **k):\n'
                  '    with plain(*a, **k) as s:\n'
                  '        yield s\n'
                  '    if not queued and os.path.exists(%r):\n'
                  '        queued.append(subprocess.run([sys.executable, "-I", sys.argv[1], "edit", %r, "4000",\n'
                  '                                      "launch-fleet: started"], capture_output=True, text=True))\n'
                  '        print("queued:", queued[0].stdout.strip(), file=sys.stderr)\n'
                  'post.pacer_state = watched\n' % (str(w.dir / 'reply.txt.used'), REPO))
        run = patched(w, queued, 'comment', REPO, 12, 'launch-fleet: started')
        out, err = run.communicate(timeout=60)
        self.assertTrue(out.startswith('unknown: ') and 'secondary' in out, out)
        self.assertIn('queued: refused: write paced, retry after ', err)
        self.assertEqual(w.writes(), [])

    def test_a_secondary_wait_outlives_a_settlement_that_cannot_get_the_state_lock(self):
        w = paced_world(self, post_answer=('HTTP/2.0 403 Forbidden', ['Retry-After: 120']))
        seed(w, full([]))
        hold = ('import fcntl, subprocess\n'
                'post.SLOT_WAIT_SECONDS = 1\n'
                'plain = post.subprocess.run\n'
                'held = []\n'
                'def run(*a, **k):\n'
                '    r = plain(*a, **k)\n'
                '    if "POST" in a[0]:\n'
                '        held.append(open(%r, "a"))\n'
                '        fcntl.flock(held[0], fcntl.LOCK_EX)\n'
                '    return r\n'
                'post.subprocess.run = run\n' % str(w.dir / 'state' / (STATE + '.lock')))
        before = time.time()
        run = patched(w, hold, 'comment', REPO, 12, 'launch-fleet: starting')
        out, err = run.communicate(timeout=60)
        self.assertTrue(out.startswith('unknown: ') and 'secondary' in out, out)
        self.assertEqual((run.returncode, err), (1, ''))
        code, after = w.run('post.py', 'comment', REPO, 12, 'launch-fleet: starting')
        self.assertEqual(w.writes(), [])
        self.assertEqual(code, 1)
        self.assertTrue(after.startswith('refused: write paced, retry after '), after)
        self.assertGreaterEqual(after.split(' ')[-1], post_stamp(before + 120))
        self.assertNotIn('could not be recorded', out)

    def test_a_saved_aside_wait_is_folded_into_the_state_then_removed(self):
        for hold, answer in (('%r' % (time.time() - 1), (0, 'posted 5001')), ('[' * 1500, None), ('"soon"', None)):
            with self.subTest(hold=hold[:20]):
                w = paced_world(self)
                seed(w, full([]))
                folder = w.dir / 'state' / 'launch-fleet'
                (folder / 'writes.json.hold.synthetic').write_text(hold)
                code, out = w.run('post.py', 'comment', REPO, 12, 'launch-fleet: starting')
                if answer:
                    self.assertEqual((code, out), answer)
                    self.assertEqual(state(w)['until'], float(hold))
                    self.assertEqual(sorted(p.name for p in folder.iterdir()), ['writes.json', 'writes.json.lock'])
                else:
                    self.assertEqual(code, 1)
                    self.assertTrue(out.startswith('refused: ') and str(w.dir) not in out, out)
                    self.assertEqual(w.writes(), [])

    def test_a_write_refuses_when_its_window_ends_before_the_state_lock_frees(self):
        w = paced_world(self)
        seed(w, full([]))
        lock = open(w.dir / 'state' / (STATE + '.lock'), 'a')
        self.addCleanup(lock.close)
        fcntl.flock(lock, fcntl.LOCK_EX)
        started = time.monotonic()
        run = patched(w, 'post.SLOT_WAIT_SECONDS = 1', 'comment', REPO, 12, 'launch-fleet: starting')
        try:
            out, err = run.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            fcntl.flock(lock, fcntl.LOCK_UN)
            out, err = run.communicate(timeout=60)
        took = time.monotonic() - started
        self.assertRegex(out.strip(), r'^refused: write paced, retry after \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$')
        self.assertLess(took, 10)
        self.assertEqual((run.returncode, err), (1, ''))
        fcntl.flock(lock, fcntl.LOCK_UN)
        self.assertEqual((w.writes(), state(w)), ([], full([])))

    def test_a_write_refuses_when_its_window_ends_with_the_in_flight_cap_still_full(self):
        w = paced_world(self)
        w.update(comments={'12': [comment(4000, 'launch-fleet: starting')]})
        holder = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(60)'])
        self.addCleanup(holder.kill)
        seed(w, full([], inflight=[(holder.pid, time.time())] * 20))
        run = patched(w, 'post.SLOT_WAIT_SECONDS = 1', 'edit', REPO, 4000, 'launch-fleet: started')
        try:
            out, err = run.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            holder.kill()
            out, err = run.communicate(timeout=60)
        self.assertTrue(out.startswith('refused: write paced, retry after '), out)
        self.assertEqual((run.returncode, err, w.writes()), (1, '', []))

    def test_a_planted_temp_file_link_is_never_followed(self):
        w = paced_world(self)
        victim = w.dir / 'victim.txt'
        victim.write_text('keep me')
        plant = ('folder = os.path.join(os.environ["XDG_STATE_HOME"], "launch-fleet")\n'
                 'os.makedirs(folder)\n'
                 'os.symlink(%r, os.path.join(folder, "writes.json.%%d.tmp" %% os.getpid()))\n' % str(victim))
        run = patched(w, plant, 'comment', REPO, 12, 'launch-fleet: starting')
        out, err = run.communicate(timeout=60)
        self.assertEqual((out.strip(), err), ('posted 5001', ''))
        self.assertEqual(victim.read_text(), 'keep me')
        path = w.dir / 'state' / STATE
        self.assertFalse(path.is_symlink())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(len(state(w)['accounts']['shared']), 1)

    def test_a_failed_state_save_leaves_no_temp_file(self):
        w = paced_world(self)
        fail = ('plain = {"replace": os.replace, "rename": os.rename}\n'
                'def refusing(name):\n'
                '    def move(src, dst, *a, **k):\n'
                '        if str(dst).endswith("writes.json"):\n'
                '            raise OSError("synthetic")\n'
                '        return plain[name](src, dst, *a, **k)\n'
                '    return move\n'
                'os.replace, os.rename = refusing("replace"), refusing("rename")\n')
        run = patched(w, fail, 'comment', REPO, 12, 'launch-fleet: starting')
        out, err = run.communicate(timeout=60)
        self.assertEqual((run.returncode, err), (1, ''))
        self.assertTrue(out.startswith('refused: '), out)
        self.assertNotIn(str(w.dir), out)
        self.assertEqual(w.writes(), [])
        self.assertEqual(sorted(p.name for p in (w.dir / 'state' / 'launch-fleet').iterdir()), ['writes.json.lock'])

    def test_processes_racing_for_the_last_slot_get_one_write(self):
        w = paced_world(self)
        now = time.time()
        seed(w, full([now - 1] * 59))
        reads = w.dir / 'reads'
        gh = w.dir / 'bin' / 'gh'
        gh.write_text(gh.read_text().replace('exec ', '', 1) + '\ncode=$?\ncase " $* " in *" --paginate "*) '
                      'printf x >> "%s";; esac\nexit $code\n' % reads)
        lock = open(w.dir / 'state' / (STATE + '.lock'), 'a')
        self.addCleanup(lock.close)
        fcntl.flock(lock, fcntl.LOCK_EX)
        runs = [subprocess.Popen([sys.executable, '-I', str(HERE / 'post.py'), 'comment', REPO, '12',
                                  'launch-fleet: starting'], stdout=subprocess.PIPE, text=True, env=w.env, cwd=w.dir)
                for _ in range(8)]
        waited = time.monotonic() + 20
        while time.monotonic() < waited and (not reads.exists() or len(reads.read_text()) < 8):
            time.sleep(0.05)
        self.assertEqual(reads.read_text() if reads.exists() else '', 'x' * 8)
        fcntl.flock(lock, fcntl.LOCK_UN)
        outs = [(r.communicate(timeout=60)[0].strip(), r.returncode) for r in runs]
        self.assertEqual(sorted((out.split(' ')[0], code) for out, code in outs),
                         [('posted', 0)] + [('refused:', 1)] * 7, outs)
        self.assertEqual(len(w.writes()), 1)
        self.assertEqual(len(state(w)['accounts'].get('shared', [])), 60)

    def test_a_write_waits_while_another_process_holds_the_state_lock(self):
        w = paced_world(self)
        seed(w, full([]))
        lock = open(w.dir / 'state' / (STATE + '.lock'), 'a')
        self.addCleanup(lock.close)
        fcntl.flock(lock, fcntl.LOCK_EX)
        run = subprocess.Popen([sys.executable, '-I', str(HERE / 'post.py'), 'comment', REPO, '12',
                                'launch-fleet: starting'], stdout=subprocess.PIPE, text=True, env=w.env, cwd=w.dir)
        try:
            run.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            pass
        self.assertIsNone(run.returncode)
        self.assertEqual((w.writes(), state(w)), ([], full([])))
        fcntl.flock(lock, fcntl.LOCK_UN)
        self.assertEqual((run.communicate(timeout=60)[0].strip(), run.returncode), ('posted 5001', 0))
        self.assertEqual(len(w.writes()), 1)

    def test_an_edit_is_unpaced_but_waits_for_the_in_flight_cap(self):
        w = paced_world(self)
        w.update(comments={'12': [comment(4000, 'launch-fleet: starting')]})
        holder = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(60)'])
        self.addCleanup(holder.kill)
        now = time.time()
        seed(w, full((now - 1 for _ in range(60)), inflight=[(holder.pid, now)] * 20))
        edit = subprocess.Popen([sys.executable, '-I', str(HERE / 'post.py'), 'edit', REPO, '4000',
                                 'launch-fleet: started'], stdout=subprocess.PIPE, text=True, env=w.env, cwd=w.dir)
        try:
            edit.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            pass
        self.assertIsNone(edit.returncode)
        self.assertEqual(w.writes(), [])
        holder.kill()
        holder.wait()
        self.assertEqual((edit.communicate(timeout=60)[0].strip(), edit.returncode), ('edited 4000', 0))
        self.assertEqual(w.writes(), [{'patch': 4000, 'body': 'launch-fleet: started'}])
        self.assertEqual(len(state(w)['accounts'].get('shared', [])), 60)
        self.assertEqual(state(w)['inflight'], [])

    def test_an_unreadable_state_file_refuses_without_writing(self):
        now = time.time()
        for text in ('{', '[]', '{"accounts": {}, "inflight": [], "until": "soon"}',
                     '{"accounts": {"a": ["x"]}, "inflight": [], "until": 0}',
                     '{"accounts": {}, "inflight": [], "until": 0, "extra": 1}',
                     '{"accounts": {}, "inflight": [], "until": Infinity}',
                     '{"accounts": {}, "inflight": [], "until": 9e99, "until": 0}',
                     '{"accounts": {"shared": [], "shared": []}, "inflight": [], "until": 0}',
                     '{"accounts": {}, "inflight": [[99999999999999999999, %r]], "until": 0}' % now,
                     '{"accounts": {}, "inflight": [[-1, %r]], "until": 0}' % now,
                     '{"accounts": {}, "inflight": [], "until": 1e300}',
                     '{"accounts": {}, "inflight": [], "until": 1%s}' % ('0' * 400),
                     '{"accounts": {"shared": [1e300]}, "inflight": [], "until": 0}',
                     '{"accounts": {}, "inflight": [[%d, 1e300]], "until": 0}' % os.getpid(),
                     '[' * 1500 + ']' * 1500,
                     '{"accounts": {"shared": %s}, "inflight": [], "until": 0}' % ('[' * 1500 + ']' * 1500),
                     '{"a": ' * 1500 + '0' + '}' * 1500):
            with self.subTest(text=text[:120]):
                w = paced_world(self)
                path = w.dir / 'state' / STATE
                path.parent.mkdir(parents=True)
                path.write_text(text)
                r = subprocess.run([sys.executable, '-I', str(HERE / 'post.py'), 'comment', REPO, '12',
                                    'launch-fleet: starting'], capture_output=True, text=True, env=w.env, cwd=w.dir,
                                   timeout=60)
                self.assertEqual((r.returncode, r.stderr), (1, ''))
                self.assertTrue(r.stdout.startswith('refused: '), r.stdout)
                self.assertNotIn(str(w.dir), r.stdout)
                self.assertEqual(w.writes(), [])
                self.assertEqual(path.read_text(), text)

    def test_an_invalid_utf8_byte_in_the_state_or_a_hold_refuses_without_writing(self):
        for name, data in (('writes.json', b'{"accounts": {"\xff": []}, "inflight": [], "until": 0}'),
                           ('writes.json.hold.synthetic', b'1\xff')):
            with self.subTest(name=name):
                w = paced_world(self)
                seed(w, full([]))
                folder = w.dir / 'state' / 'launch-fleet'
                (folder / name).write_bytes(data)
                before = {p.name: p.read_bytes() for p in folder.iterdir()}
                r = subprocess.run([sys.executable, '-I', str(HERE / 'post.py'), 'comment', REPO, '12',
                                    'launch-fleet: starting'], capture_output=True, text=True, env=w.env, cwd=w.dir,
                                   timeout=60)
                self.assertEqual((r.returncode, r.stderr), (1, ''))
                self.assertEqual(r.stdout, "refused: the write pacer's state file is unreadable; nothing was written\n")
                self.assertEqual(w.writes(), [])
                self.assertEqual({p.name: p.read_bytes() for p in folder.iterdir()}, before)

    def test_a_hold_published_after_the_hold_scan_refuses_the_write(self):
        w = paced_world(self)
        seed(w, full([]))
        folder = w.dir / 'state' / 'launch-fleet'
        scanned = w.dir / 'scanned'
        pause = ('plain = post.holds\n'
                 'def holds(path):\n'
                 '    found = plain(path)\n'
                 '    if not os.path.exists(%r):\n'
                 '        open(%r, "w").close()\n'
                 '        sys.stdin.readline()\n'
                 '    return found\n'
                 'post.holds = holds\n' % (str(scanned), str(scanned)))
        writer = subprocess.Popen([sys.executable, '-I', '-c', RUNNER, str(HERE / 'post.py'), pause, 'comment', REPO,
                                   '12', 'launch-fleet: starting'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, env=w.env, cwd=w.dir)
        self.addCleanup(writer.kill)
        waited = time.monotonic() + 20
        while time.monotonic() < waited and not scanned.exists() and writer.poll() is None:
            time.sleep(0.05)
        self.assertTrue(scanned.exists())
        publish = ('import time\n'
                   'post.SLOT_WAIT_SECONDS = 0\n'
                   'sys.exit(0 if post.settle([1, 0.0], time.time() + 120) else 3)\n')
        before = time.time()
        published = patched(w, publish)
        self.assertEqual(published.communicate(timeout=60), ('', ''))
        self.assertEqual(published.returncode, 0)
        self.assertEqual(len([p for p in folder.iterdir() if p.name.startswith('writes.json.hold.')]), 1)
        self.assertIsNone(writer.poll())
        out, err = writer.communicate('go\n', timeout=60)
        self.assertEqual((writer.returncode, err), (1, ''))
        self.assertTrue(out.startswith('refused: write paced, retry after '), out)
        self.assertGreaterEqual(out.split(' ')[-1].strip(), post_stamp(before + 120))
        self.assertEqual(w.writes(), [])

if __name__ == '__main__':
    unittest.main()
