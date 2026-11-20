#!/usr/bin/env python3
"""post.py on a synthetic GitHub (WS8, #1181): public records, read back.

python3 -I skills/launch-fleet/scripts/test-post.py
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
FLEET_MD = ('# Fleet settings\n\n## GitHub identity\n\n| Setting | Value |\n| --- | --- |\n'
            '| Record authors | `openwiz[bot]`, `synthetic-owner` |\n')


class World:
    """One synthetic repository and a `gh` on PATH that serves it."""

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
                     'launch-fleet: look: builder thr_abc and thr_def both match',
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

    def test_a_lost_response_is_recovered_by_read_back(self):
        w = World(self, comments={'12': [comment(4000, 'launch-fleet: starting')]}, faults={'post': 'lost'})
        code, out = w.run('post.py', 'comment', REPO, 12, 'launch-fleet: starting')
        self.assertEqual((code, out), (0, 'posted 5001'))
        self.assertEqual(len(w.writes()), 1)

    def test_a_failed_write_is_unknown_never_posted(self):
        w = World(self, faults={'post': 'fail'})
        code, out = w.run('post.py', 'comment', REPO, 12, 'launch-fleet: starting')
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('unknown: '), out)

    def test_identical_text_from_anyone_else_is_not_the_record(self):
        # The response is lost, and the only new comment with these words is not a record author's.
        w = World(self, me='someone-else', faults={'post': 'lost'})
        code, out = w.run('post.py', 'comment', REPO, 12, 'launch-fleet: starting')
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('unknown: '), out)

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


if __name__ == '__main__':
    unittest.main()
