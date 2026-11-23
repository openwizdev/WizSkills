#!/usr/bin/env python3
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO = 'synthetic-owner/synthetic-repo'
FLEET_MD = ('# Fleet settings\n\n## GitHub identity\n\n| Setting | Value |\n| --- | --- |\n'
            '| Record authors | `openwiz[bot]`, `synthetic-owner` |\n')
FAKE_GH = '#!/bin/sh\nprintf "%s\\n" "$*" >> "$FAKE_GH_LOG"\necho "gh: refused in this test" >&2\nexit 1\n'


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
        self.assertEqual(attempt(post.authors, REPO), post.grants.record_authors(FLEET_MD))
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
