#!/usr/bin/env python3
import base64
import http.server
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO = 'synthetic-owner/synthetic-repo'
FLEET_MD = ('# Fleet settings\n\n## GitHub identity\n\n| Setting | Value |\n| --- | --- |\n'
            '| Record authors | `openwiz[bot]`, `synthetic-owner` |\n')
FAKE_GH = '#!/bin/sh\nprintf "%s\\n" "$*" >> "$FAKE_GH_LOG"\necho "gh: refused in this test" >&2\nexit 1\n'
SIGNED_IN_GH = ('#!/bin/sh\nprintf "%s\\n" "$*" >> "$FAKE_GH_LOG"\ncat > /dev/null\n'
                'if [ "$*" = "auth git-credential get" ]; then\n'
                '  printf "username=x-access-token\\npassword=synthetic-token\\n"\nfi\nexit 0\n')
BASIC = 'Basic ' + base64.b64encode(b'x-access-token:synthetic-token').decode()


def load(name):
    spec = importlib.util.spec_from_file_location('fr6_' + name.replace('-', '_'), HERE / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def attempt(read, *args):
    try:
        return read(*args)
    except Exception as error:
        return f'raised {type(error).__name__}: {error}'


class Origin:

    def __init__(self, test):
        self.tmp = Path(tempfile.mkdtemp())
        test.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / 'bin').mkdir()
        (self.tmp / 'bin/gh').write_text(FAKE_GH)
        (self.tmp / 'bin/gh').chmod(0o755)
        self.log = self.tmp / 'gh.log'
        self.env = dict(os.environ, PATH=f'{self.tmp / "bin"}:{os.environ["PATH"]}', FAKE_GH_LOG=str(self.log),
                        XDG_CACHE_HOME=str(self.tmp / 'cache'), GIT_CONFIG_NOSYSTEM='1',
                        GIT_CONFIG_GLOBAL=str(self.tmp / 'gitconfig'), GIT_CONFIG_COUNT='1',
                        GIT_CONFIG_KEY_0=f'url.file://{self.tmp / "origins"}/.insteadOf',
                        GIT_CONFIG_VALUE_0='https://github.com/')
        self.env.pop('GIT_DIR', None)
        self.bare = self.tmp / 'origins' / f'{REPO}.git'
        self.work = self.tmp / 'work'
        self.git(None, 'init', '--quiet', '--bare', '--initial-branch=main', str(self.bare))
        self.git(None, 'clone', '--quiet', str(self.bare), str(self.work))

    def git(self, cwd, *args):
        run = subprocess.run(['git', '-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid',
                              *args], cwd=cwd, env=self.env, capture_output=True, text=True, timeout=60)
        if run.returncode != 0:
            raise AssertionError(f'test setup: git {args}: {run.stderr}')
        return run.stdout

    def commit(self, files, branch='main'):
        self.git(self.work, 'checkout', '--quiet', '-B', branch)
        for path, text in files.items():
            (self.work / path).parent.mkdir(parents=True, exist_ok=True)
            (self.work / path).write_text(text)
        self.git(self.work, 'add', '-A')
        self.git(self.work, 'commit', '--quiet', '-m', 'synthetic')
        self.git(self.work, 'push', '--quiet', 'origin', branch)

    def default(self, branch):
        self.git(None, '--git-dir', str(self.bare), 'symbolic-ref', 'HEAD', f'refs/heads/{branch}')

    def read(self, path='docs/agents/fleet.md', *extra, repo=REPO):
        run = subprocess.run([sys.executable, '-I', str(HERE / 'gitread.py'), 'show', repo, path, *extra],
                             env=self.env, capture_output=True, text=True, timeout=60)
        return run.returncode, run.stdout, run.stderr

    def gh_calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def cache(self, repo=REPO):
        return self.tmp / 'cache/launch-fleet/git' / f'{repo}.git'

    def behind_http(self, test, gh=FAKE_GH):
        (self.tmp / 'bin/gh').write_text(gh)
        hits, origins = [], self.tmp / 'origins'

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.serve()

            def do_POST(self):
                self.serve()

            def serve(self):
                hits.append(self.path)
                if self.headers.get('Authorization') != BASIC:
                    self.send_response(401)
                    self.send_header('WWW-Authenticate', 'Basic realm="synthetic"')
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                body = self.rfile.read(int(self.headers.get('Content-Length') or 0))
                path, _, query = self.path.partition('?')
                cgi = dict(os.environ, GIT_PROJECT_ROOT=str(origins), GIT_HTTP_EXPORT_ALL='1', PATH_INFO=path,
                           QUERY_STRING=query, REQUEST_METHOD=self.command, REMOTE_USER='x-access-token',
                           CONTENT_TYPE=self.headers.get('Content-Type') or '', CONTENT_LENGTH=str(len(body)),
                           HTTP_CONTENT_ENCODING=self.headers.get('Content-Encoding') or '',
                           HTTP_GIT_PROTOCOL=self.headers.get('Git-Protocol') or '')
                out = subprocess.run(['git', 'http-backend'], input=body, env=cgi, capture_output=True,
                                     timeout=60).stdout
                head, _, payload = out.partition(b'\r\n\r\n')
                headers = [line.split(': ', 1) for line in head.decode().split('\r\n') if ': ' in line]
                status = next((int(v.split()[0]) for k, v in headers if k == 'Status'), 200)
                self.send_response(status)
                for key, value in headers:
                    if key != 'Status':
                        self.send_header(key, value)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        test.addCleanup(server.server_close)
        test.addCleanup(server.shutdown)
        self.env['GIT_CONFIG_KEY_0'] = f'url.http://127.0.0.1:{server.server_address[1]}/.insteadOf'
        return hits


class GitRead(unittest.TestCase):
    def setUp(self):
        self.o = Origin(self)
        self.o.commit({'docs/agents/fleet.md': FLEET_MD})

    def test_a_fresh_read_fetches_the_default_branch_and_prints_the_file(self):
        self.assertEqual(self.o.read(), (0, FLEET_MD, ''))
        cache = self.o.tmp / 'cache/launch-fleet/git' / f'{REPO}.git'
        self.assertTrue((cache / 'shallow').is_file(), 'the cache fetches with --depth 1')
        self.assertEqual(self.o.gh_calls(), [])

    def test_a_read_within_the_max_age_never_fetches(self):
        self.assertEqual(self.o.read()[0], 0)
        self.o.commit({'docs/agents/fleet.md': 'moved on\n'})
        self.assertEqual(self.o.read(), (0, FLEET_MD, ''))
        shutil.rmtree(self.o.bare)
        self.assertEqual(self.o.read(), (0, FLEET_MD, ''))
        self.assertEqual(self.o.gh_calls(), [])

    def test_past_the_max_age_a_moved_default_branch_is_read_afresh(self):
        self.assertEqual(self.o.read()[0], 0)
        self.o.commit({'docs/agents/fleet.md': 'tip moved\n'})
        self.assertEqual(self.o.read('docs/agents/fleet.md', '--max-age', '0'), (0, 'tip moved\n', ''))
        self.o.commit({'docs/agents/fleet.md': 'on trunk\n'}, branch='trunk')
        self.o.default('trunk')
        self.assertEqual(self.o.read('docs/agents/fleet.md', '--max-age', '0'), (0, 'on trunk\n', ''))
        self.assertEqual(self.o.gh_calls(), [])

    def test_a_missing_path_is_an_error_never_empty_text(self):
        for path in ('docs/agents/absent.md', 'docs/agents', 'docs/../README.md', '/etc/passwd'):
            with self.subTest(path=path):
                code, out, err = self.o.read(path)
                self.assertEqual((code, out), (2, ''))
                self.assertTrue(err.startswith('gitread: '), err)

    def test_a_failed_fetch_is_an_error_never_the_stale_copy(self):
        code, out, err = self.o.read(repo='synthetic-owner/never-created')
        self.assertEqual((code, out), (2, ''))
        self.assertIn('could not fetch', err)
        self.assertEqual(self.o.read()[0], 0)
        shutil.rmtree(self.o.bare)
        code, out, err = self.o.read('docs/agents/fleet.md', '--max-age', '0')
        self.assertEqual((code, out), (2, ''))
        self.assertIn('could not fetch', err)
        self.assertEqual(self.o.gh_calls(), [])

    def test_a_cache_it_cannot_verify_is_an_error(self):
        self.assertEqual(self.o.read()[0], 0)
        cache = self.o.tmp / 'cache/launch-fleet/git' / f'{REPO}.git'
        self.assertTrue((cache / 'gitread-fetched').is_file(), 'a read leaves a stamped cache')
        self.o.git(None, '--git-dir', str(cache), 'config', 'gitread.repo', 'synthetic-owner/other')
        code, out, err = self.o.read()
        self.assertEqual((code, out), (2, ''))
        self.assertIn('not a verified cache', err)
        self.o.git(None, '--git-dir', str(cache), 'config', 'gitread.repo', REPO)
        stamp = (cache / 'gitread-fetched').read_text().split()[0]
        (cache / 'gitread-fetched').write_text(f'{stamp} {"0" * 40}\n')
        code, out, err = self.o.read()
        self.assertEqual((code, out), (2, ''))
        self.assertIn('does not hold', err)
        shutil.rmtree(cache)
        cache.mkdir()
        code, out, _ = self.o.read()
        self.assertEqual((code, out), (2, ''))
        shutil.rmtree(self.o.tmp / 'cache')
        (self.o.tmp / 'cache').write_text('not a folder\n')
        code, out, err = self.o.read()
        self.assertEqual((code, out), (2, ''))
        self.assertIn('could not use the cache', err)

    def test_the_cache_is_owner_only_under_any_umask(self):
        saved = os.umask(0o022)
        self.addCleanup(os.umask, saved)
        self.assertEqual(self.o.read(), (0, FLEET_MD, ''))
        root = self.o.tmp / 'cache/launch-fleet/git'
        self.assertEqual(root.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.o.cache() / 'gitread-fetched').read_text().count(' '), 1)

    def test_a_cache_path_it_cannot_trust_is_refused(self):
        root = self.o.tmp / 'cache/launch-fleet/git'
        root.mkdir(parents=True)
        root.chmod(0o755)
        code, out, err = self.o.read()
        self.assertEqual((code, out), (2, ''))
        self.assertIn('open to other users', err)
        self.assertFalse((root / 'synthetic-owner').exists(), 'nothing is fetched into an open cache')
        root.rmdir()
        (self.o.tmp / 'elsewhere').mkdir(mode=0o700)
        root.symlink_to(self.o.tmp / 'elsewhere')
        code, out, err = self.o.read()
        self.assertEqual((code, out), (2, ''))
        self.assertIn('is a symlink', err)
        self.assertEqual(list((self.o.tmp / 'elsewhere').iterdir()), [])
        root.unlink()
        root.mkdir(mode=0o700)
        (root / 'synthetic-owner').mkdir()
        self.o.cache().symlink_to(self.o.tmp / 'elsewhere')
        code, out, err = self.o.read()
        self.assertEqual((code, out), (2, ''))
        self.assertIn('is a symlink', err)
        self.assertEqual(list((self.o.tmp / 'elsewhere').iterdir()), [])
        self.o.cache().unlink()
        gitread = load('gitread')
        with mock.patch.dict(os.environ, self.o.env, clear=True), \
                mock.patch('os.geteuid', return_value=os.geteuid() + 1):
            with self.assertRaisesRegex(gitread.Error, 'not owned by you'):
                gitread.show(REPO, 'docs/agents/fleet.md')
        self.assertFalse(self.o.cache().exists())

    def test_inherited_git_storage_settings_never_move_the_cache(self):
        outside = self.o.tmp / 'outside'
        outside.mkdir()
        self.o.env.update(GIT_OBJECT_DIRECTORY=str(outside / 'objects'),
                          GIT_ALTERNATE_OBJECT_DIRECTORIES=str(outside / 'alternates'),
                          GIT_INDEX_FILE=str(outside / 'index'), GIT_SHALLOW_FILE=str(outside / 'shallow'))
        self.assertEqual(self.o.read(), (0, FLEET_MD, ''))
        self.assertEqual(sorted(p.name for p in outside.rglob('*')), [], 'nothing is written outside the cache')
        self.assertTrue((self.o.cache() / 'shallow').is_file())
        self.assertEqual(self.o.read(), (0, FLEET_MD, ''))

    def test_a_signed_in_gh_lends_git_its_credential_for_this_fetch(self):
        hits = self.o.behind_http(self, gh=SIGNED_IN_GH)
        origin = self.o.env['GIT_CONFIG_KEY_0'][len('url.http://'):-len('/.insteadOf')]
        (self.o.tmp / 'stale-credentials').write_text(f'http://x-access-token:stale@{origin}\n')
        (self.o.tmp / 'gitconfig').write_text(f'[credential]\n\thelper = store --file {self.o.tmp}/stale-credentials\n')
        self.assertEqual(self.o.read(), (0, FLEET_MD, ''))
        self.assertEqual(self.o.gh_calls(), ['auth git-credential get', 'auth git-credential store'])
        self.assertEqual(hits[0], f'/{REPO}.git/info/refs?service=git-upload-pack')
        self.assertEqual(self.o.read('docs/agents/fleet.md', '--max-age', '0'), (0, FLEET_MD, ''))

    def test_the_credential_never_reaches_a_trace_or_an_error(self):
        hits = self.o.behind_http(self, gh=SIGNED_IN_GH)
        traces = self.o.tmp / 'traces'
        traces.mkdir()
        self.o.env.update(GIT_TRACE_REDACT='0', GIT_CURL_VERBOSE='1', GIT_TRACE_CURL=str(traces / 'curl'),
                          GIT_TRACE=str(traces / 'trace'), GIT_TRACE_PACKET=str(traces / 'packet'),
                          GIT_TRACE2_EVENT=str(traces / 'event'))
        (self.o.tmp / 'gitconfig').write_text(f'[trace2]\n\tnormalTarget = {traces}/normal\n'
                                              f'\tperfTarget = {traces}/perf\n')
        secret = BASIC.split()[1]
        self.assertEqual(self.o.read(), (0, FLEET_MD, ''))
        self.assertTrue(hits)
        code, out, err = self.o.read(repo='synthetic-owner/never-created')
        self.assertEqual((code, out), (2, ''))
        self.assertEqual(err, 'gitread: could not fetch the default branch of synthetic-owner/never-created\n')
        self.assertEqual(sorted(p.name for p in traces.iterdir()), [], 'git writes no trace')
        self.assertNotIn(secret, err)

    def test_local_only_refuses_any_origin_that_is_not_a_local_folder(self):
        hits = self.o.behind_http(self, gh=SIGNED_IN_GH)
        self.o.env['GITREAD_LOCAL_ONLY'] = '1'
        code, out, err = self.o.read()
        self.assertEqual((code, out, hits), (2, '', []), err)
        self.assertEqual(err, f'gitread: could not fetch the default branch of {REPO}\n')
        self.o.env.update(GIT_ALLOW_PROTOCOL='http:file', GIT_CONFIG_COUNT='2',
                          GIT_CONFIG_KEY_1='protocol.http.allow', GIT_CONFIG_VALUE_1='always')
        (self.o.tmp / 'gitconfig').write_text('[protocol "http"]\n\tallow = always\n[protocol]\n\tallow = always\n')
        code, out, err = self.o.read('docs/agents/fleet.md', '--max-age', '0')
        self.assertEqual((code, out, hits), (2, '', []), 'an inherited protocol setting never opens the guard')
        self.o.env['GIT_CONFIG_KEY_0'] = f'url.file://{self.o.tmp / "origins"}/.insteadOf'
        self.assertEqual(self.o.read('docs/agents/fleet.md', '--max-age', '0'), (0, FLEET_MD, ''))

    def test_a_failed_fetch_holds_its_cooldown_under_the_lock(self):
        hits = self.o.behind_http(self)
        code, out, err = self.o.read()
        self.assertEqual((code, out), (2, ''))
        self.assertIn('could not fetch', err)
        self.assertEqual(len(hits), 1)
        code, out, err = self.o.read()
        self.assertEqual(len(hits), 1, 'a read inside the cooldown never fetches again')
        self.assertEqual((code, out), (2, ''))
        self.assertIn('last fetch', err)
        self.assertEqual(self.o.gh_calls(), ['auth git-credential get'])
        (self.o.tmp / 'bin/gh').write_text(SIGNED_IN_GH)
        self.assertEqual(self.o.read('docs/agents/fleet.md', '--max-age', '0'), (0, FLEET_MD, ''))
        self.assertEqual(self.o.read(), (0, FLEET_MD, ''))
        self.assertEqual(len(self.o.gh_calls()), 3)

    def test_a_fresh_stamp_must_name_the_pinned_tip(self):
        self.assertEqual(self.o.read()[0], 0)
        old = (self.o.cache() / 'gitread-fetched').read_text().split()[1]
        self.o.commit({'docs/agents/fleet.md': 'moved on\n'})
        self.assertEqual(self.o.read('docs/agents/fleet.md', '--max-age', '0'), (0, 'moved on\n', ''))
        when = (self.o.cache() / 'gitread-fetched').read_text().split()[0]
        (self.o.cache() / 'gitread-fetched').write_text(f'{when} {old}\n')
        code, out, err = self.o.read()
        self.assertEqual((code, out), (2, ''))
        self.assertIn('does not match', err)

    def test_bad_arguments_are_refused(self):
        for args in (('show', REPO), ('cat', REPO, 'x'), ('show', '../x', 'x'),
                     ('show', REPO, 'x', '--max-age'), ('show', REPO, 'x', '--max-age', '-1')):
            with self.subTest(args=args):
                run = subprocess.run([sys.executable, '-I', str(HERE / 'gitread.py'), *args], env=self.o.env,
                                     capture_output=True, text=True, timeout=60)
                self.assertEqual((run.returncode, run.stdout), (2, ''))


class NoContentsReads(unittest.TestCase):

    def setUp(self):
        self.o = Origin(self)
        self.o.commit({'docs/agents/fleet.md': FLEET_MD})
        self.saved = dict(os.environ)
        os.environ.clear()
        os.environ.update(self.o.env)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self.saved)))

    def test_post_authors_reads_fleet_md_from_git(self):
        post = load('post')
        self.assertEqual(attempt(post.authors, REPO), frozenset({'openwiz[bot]', 'synthetic-owner'}))
        self.assertEqual(self.o.gh_calls(), [])
        shutil.rmtree(self.o.bare)
        shutil.rmtree(self.o.tmp / 'cache')
        with self.assertRaises(post.Stop):
            post.authors(REPO)
        self.assertEqual(self.o.gh_calls(), [])

    def test_ops_starts_read_fleet_reads_fleet_md_from_git(self):
        starts = load('ops-starts')
        self.assertEqual(attempt(starts.read_fleet, REPO), FLEET_MD)
        self.assertEqual(self.o.gh_calls(), [])
        shutil.rmtree(self.o.bare)
        shutil.rmtree(self.o.tmp / 'cache')
        with self.assertRaises(ValueError):
            starts.read_fleet(REPO)
        self.assertEqual(self.o.gh_calls(), [])


if __name__ == '__main__':
    unittest.main()
