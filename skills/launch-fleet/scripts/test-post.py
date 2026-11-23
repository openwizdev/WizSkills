#!/usr/bin/env python3
import json
import os
import runpy
from pathlib import Path
import subprocess
import sys
import tempfile
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
        self.path = self.dir / 'world.json'
        value = {'repo': REPO, 'me': 'openwiz[bot]', 'fleet_md': FLEET_MD, 'next_id': 5000,
                 'comments': {}, 'writes': [], 'faults': {}}
        value.update(extra)
        self.save(value)
        self.env = dict(os.environ, PATH='%s:%s' % (bin_dir, os.environ['PATH']), FAKE_WORLD=str(self.path))
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

if __name__ == '__main__':
    unittest.main()
