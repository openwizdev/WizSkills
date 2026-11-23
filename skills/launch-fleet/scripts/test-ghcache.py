#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ['FAKE_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\n')
world = json.load(open(os.environ['FAKE_WORLD']))
headers = [args[i + 1] for i, a in enumerate(args) if a == '-H']
sent = [h.split(':', 1)[1].strip() for h in headers if h.lower().startswith('if-none-match:')]
answer = world.get(args[-1])
if args[0] != 'api' or '--include' not in args or answer is None:
    print('gh: synthetic failure', file=sys.stderr)
    sys.exit(1)
status = answer.get('status', 200)
if status == 200 and (world.get('always304') or (sent and sent[0] == answer.get('etag'))):
    status = 304
out = ['HTTP/2.0 %d %s' % (status, {200: 'OK', 304: 'Not Modified', 403: 'Forbidden'}[status])]
if answer.get('etag'):
    out.append('Etag: %s' % answer['etag'])
if answer.get('link'):
    out.append('Link: %s' % answer['link'])
sys.stdout.write('\r\n'.join(out) + '\r\n\r\n')
if status != 304:
    sys.stdout.write(answer['body'])
sys.exit(0 if status == 200 else 1)
'''

ISSUE = 'repos/synthetic-org/project/issues/7'
COMMENTS = 'repos/synthetic-org/project/issues/7/comments?per_page=100'
PAGE2 = 'https://api.github.com/repositories/1/issues/7/comments?per_page=100&page=2'


class GhCache(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        bin_dir = self.tmp / 'bin'
        bin_dir.mkdir()
        (bin_dir / 'gh').write_text(FAKE_GH)
        (bin_dir / 'gh').chmod(0o755)
        self.log = self.tmp / 'log'
        self.world_file = self.tmp / 'world.json'
        self.cache = self.tmp / 'cache'
        self.saved_env = dict(os.environ)
        os.environ.update(PATH='%s:%s' % (bin_dir, os.environ.get('PATH', '/usr/bin:/bin')),
                          FAKE_LOG=str(self.log), FAKE_WORLD=str(self.world_file),
                          XDG_CACHE_HOME=str(self.cache))
        os.environ.pop('OPENWIZ_GITHUB_APP_KEY', None)
        self.world({ISSUE: {'etag': '"a1"', 'body': '{"number": 7, "title": "first"}'}})
        import ghcache
        self.ghcache = ghcache

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved_env)

    def world(self, world):
        self.world_file.write_text(json.dumps(world))

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def sent_tags(self):
        return [[a.split(':', 1)[1].strip() for a in c if a.lower().startswith('if-none-match:')]
                for c in self.calls()]

    def entries(self):
        rest = self.cache / 'launch-fleet' / 'rest'
        return sorted(p for p in rest.iterdir() if not p.name.startswith('.')) if rest.is_dir() else []

    def test_first_read_saves_the_etag_and_the_second_gets_a_304(self):
        self.assertEqual(self.ghcache.get(ISSUE), {'number': 7, 'title': 'first'})
        self.assertEqual(len(self.entries()), 1)
        self.assertEqual(json.loads(self.entries()[0].read_text())['etag'], '"a1"')
        self.assertEqual(self.ghcache.get(ISSUE), {'number': 7, 'title': 'first'})
        self.assertEqual(self.sent_tags(), [[], ['"a1"']])

    def test_a_changed_answer_replaces_the_saved_one(self):
        self.ghcache.get(ISSUE)
        self.world({ISSUE: {'etag': '"b2"', 'body': '{"number": 7, "title": "second"}'}})
        self.assertEqual(self.ghcache.get(ISSUE), {'number': 7, 'title': 'second'})
        self.assertEqual(self.ghcache.get(ISSUE), {'number': 7, 'title': 'second'})
        self.assertEqual(self.sent_tags(), [[], ['"a1"'], ['"b2"']])
        self.assertEqual(len(self.entries()), 1)

    def test_pages_reads_every_page_and_revalidates_each(self):
        self.world({COMMENTS: {'etag': '"p1"', 'body': '[{"id": 1}, {"id": 2}]',
                               'link': '<%s>; rel="next", <%s>; rel="last"' % (PAGE2, PAGE2)},
                    PAGE2: {'etag': '"p2"', 'body': '[{"id": 3}]'}})
        self.assertEqual(self.ghcache.pages(COMMENTS), [{'id': 1}, {'id': 2}, {'id': 3}])
        self.assertEqual(self.ghcache.pages(COMMENTS), [{'id': 1}, {'id': 2}, {'id': 3}])
        self.assertEqual([c[-1] for c in self.calls()], [COMMENTS, PAGE2, COMMENTS, PAGE2])
        self.assertEqual(self.sent_tags(), [[], [], ['"p1"'], ['"p2"']])

    def test_a_damaged_entry_raises(self):
        self.ghcache.get(ISSUE)
        entry = self.entries()[0]
        saved = json.loads(entry.read_text())
        saved['body'] = '[]'
        entry.write_text(json.dumps(saved))
        with self.assertRaises(self.ghcache.Error):
            self.ghcache.get(ISSUE)
        entry.write_text('{not json')
        with self.assertRaises(self.ghcache.Error):
            self.ghcache.get(ISSUE)

    def test_an_entry_with_a_repeated_key_or_a_symlink_raises(self):
        self.ghcache.get(ISSUE)
        entry = self.entries()[0]
        good = entry.read_text()
        entry.write_text(good[:-1] + ', "etag": "\\"forged\\""}')
        with self.assertRaises(self.ghcache.Error):
            self.ghcache.get(ISSUE)
        (self.tmp / 'elsewhere').write_text(good)
        entry.symlink_to(self.tmp / 'elsewhere')
        with self.assertRaises(self.ghcache.Error):
            self.ghcache.get(ISSUE)
        self.assertEqual(self.sent_tags(), [[]])

    def test_a_304_without_an_entry_raises(self):
        self.world({ISSUE: {'etag': '"a1"', 'body': '{}'}, 'always304': True})
        with self.assertRaises(self.ghcache.Error):
            self.ghcache.get(ISSUE)

    def test_a_403_raises_without_the_body(self):
        self.world({ISSUE: {'status': 403, 'body': '{"message": "synthetic-secret-body"}'}})
        with self.assertRaises(self.ghcache.Error) as raised:
            self.ghcache.get(ISSUE)
        self.assertIn('403', str(raised.exception))
        self.assertNotIn('synthetic-secret-body', str(raised.exception))
        self.assertEqual(self.entries(), [])

    def test_reads_only_and_keys_on_the_media_type(self):
        self.ghcache.get(ISSUE)
        self.ghcache.get(ISSUE, accept='application/vnd.github.full+json')
        self.assertEqual(len(self.entries()), 2)
        for call in self.calls():
            self.assertIn('GET', call[call.index('--method') + 1:][:1])
        self.assertEqual(self.sent_tags(), [[], []])

    def test_an_answer_without_an_etag_is_not_saved(self):
        self.world({ISSUE: {'body': '{"number": 7}'}})
        self.assertEqual(self.ghcache.get(ISSUE), {'number': 7})
        self.assertEqual(self.entries(), [])

    def test_cli_get_prints_the_body(self):
        script = [sys.executable, '-I', str(HERE / 'ghcache.py'), 'get', ISSUE]
        for _ in range(2):
            run = subprocess.run(script, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(run.stdout), {'number': 7, 'title': 'first'})
        self.world({ISSUE: {'status': 403, 'body': '{"message": "no"}'}})
        run = subprocess.run(script, capture_output=True, text=True)
        self.assertEqual((run.returncode, run.stdout), (1, ''))


if __name__ == '__main__':
    unittest.main()
