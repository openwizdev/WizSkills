#!/usr/bin/env python3
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / 'check' / 'integrity.py'
GIT_ENV = {
    'GIT_AUTHOR_NAME': 'Synthetic',
    'GIT_AUTHOR_EMAIL': 'synthetic@example.com',
    'GIT_COMMITTER_NAME': 'Synthetic',
    'GIT_COMMITTER_EMAIL': 'synthetic@example.com',
    'GIT_CONFIG_NOSYSTEM': '1',
    'GIT_CONFIG_GLOBAL': os.devnull,
}
PREFIXES = (
    'deleted test file: ',
    'deleted test function: ',
    'renamed test function: ',
    'new skip mark: ',
    'new mock: ',
    'ignored warning: ',
)


def findings(stdout):
    return [line for line in stdout.splitlines() if line.startswith(PREFIXES)]


class Repo:
    def __init__(self, test):
        self.dir = Path(tempfile.mkdtemp(prefix='integrity-'))
        test.addCleanup(shutil.rmtree, self.dir, True)
        self.git('init', '-q', '-b', 'main')
        self.git('commit', '--allow-empty', '-m', 'base')
        self.base = self.git('rev-parse', 'HEAD').strip()

    def git(self, *args):
        done = subprocess.run(
            ['git', '-C', str(self.dir), '-c', 'commit.gpgsign=false', *args],
            capture_output=True, text=True, env={**os.environ, **GIT_ENV},
        )
        if done.returncode:
            raise AssertionError(done.stderr or done.stdout)
        return done.stdout

    def write(self, rel, text):
        path = self.dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def remove(self, rel):
        (self.dir / rel).unlink()

    def commit(self, message):
        self.git('add', '-A')
        self.git('commit', '-m', message)
        return self.git('rev-parse', 'HEAD').strip()


def report(repo, base):
    if not SCRIPT.is_file():
        return 0, ''
    done = subprocess.run(
        [sys.executable, '-I', str(SCRIPT), '--base', base, '--head', 'HEAD', '--repo', str(repo.dir)],
        capture_output=True, text=True,
    )
    return done.returncode, done.stdout


class IntegrityReport(unittest.TestCase):
    def test_deleted_test_file_is_reported_with_path_and_line(self):
        repo = Repo(self)
        repo.write('tests/test_old.py', 'VALUE = 1\n')
        repo.write('pkg/widget.py', 'VALUE = 1\n')
        base = repo.commit('add')
        repo.remove('tests/test_old.py')
        repo.remove('pkg/widget.py')
        repo.commit('delete')
        code, out = report(repo, base)
        self.assertEqual(code, 0)
        self.assertEqual(findings(out), ['deleted test file: tests/test_old.py:1'])
        self.assertEqual(out, 'deleted test file: tests/test_old.py:1\n')

    def test_deleted_test_function_is_reported_with_its_old_line(self):
        repo = Repo(self)
        repo.write('tests/test_keep.py', 'def test_keep():\n    assert True\n\n\ndef test_gone():\n    assert True\n')
        base = repo.commit('add')
        repo.write('tests/test_keep.py', 'def test_keep():\n    assert True\n')
        repo.commit('delete function')
        code, out = report(repo, base)
        self.assertEqual(code, 0)
        self.assertEqual(findings(out), ['deleted test function: tests/test_keep.py:5 test_gone'])

    def test_renamed_test_function_is_reported_not_as_a_deletion(self):
        repo = Repo(self)
        repo.write('tests/test_names.py', 'def test_old_name():\n    assert True\n')
        base = repo.commit('add')
        repo.write('tests/test_names.py', 'def test_new_name():\n    assert True\n')
        repo.commit('rename')
        code, out = report(repo, base)
        self.assertEqual(code, 0)
        self.assertEqual(findings(out), [
            'renamed test function: tests/test_names.py:1 test_old_name -> test_new_name',
        ])

    def test_new_skip_xfail_and_unittest_skip_marks_are_reported(self):
        repo = Repo(self)
        base = repo.base
        repo.write('tests/test_skip.py', """import pytest
@pytest.mark.skip
def test_a():
    assert True
""")
        repo.write('tests/test_skipif.py', """import pytest
@pytest.mark.skipif(True, reason="synthetic")
def test_a():
    assert True
""")
        repo.write('tests/test_xfail.py', """import pytest
@pytest.mark.xfail
def test_a():
    assert True
""")
        repo.write('tests/test_unit.py', """import unittest
@unittest.skip("synthetic")
def test_a():
    assert True
""")
        repo.commit('marks')
        code, out = report(repo, base)
        self.assertEqual(code, 0)
        self.assertEqual(findings(out), [
            'new skip mark: tests/test_skip.py:2 pytest.mark.skip',
            'new skip mark: tests/test_skipif.py:2 pytest.mark.skipif',
            'new skip mark: tests/test_unit.py:2 unittest.skip',
            'new skip mark: tests/test_xfail.py:2 pytest.mark.xfail',
        ])

    def test_new_patch_of_production_code_is_reported(self):
        repo = Repo(self)
        base = repo.base
        repo.write('tests/test_spin.py',
                   'from unittest.mock import patch\n\n@patch("pkg.widget.spin")\n'
                   'def test_spin(fake):\n    assert fake is not None\n')
        repo.write('tests/test_env.py',
                   'def test_env(monkeypatch):\n    monkeypatch.setattr("pkg.widget.spin", lambda: None)\n')
        repo.commit('mocks')
        code, out = report(repo, base)
        self.assertEqual(code, 0)
        self.assertEqual(findings(out), [
            'new mock: tests/test_env.py:2 monkeypatch.setattr pkg.widget.spin',
            'new mock: tests/test_spin.py:3 patch pkg.widget.spin',
        ])

    def test_patch_of_a_test_helper_is_not_reported(self):
        repo = Repo(self)
        base = repo.base
        repo.write('tests/test_helper.py',
                   'from unittest.mock import patch\n\n@patch("tests.helper.fake")\n'
                   'def test_helper(fake):\n    assert fake is not None\n')
        repo.commit('helper')
        code, out = report(repo, base)
        self.assertEqual(code, 0)
        self.assertEqual(findings(out), [])
        self.assertEqual(out, '')

    def test_ignored_warning_is_reported_with_file_and_line(self):
        repo = Repo(self)
        base = repo.base
        repo.write('tests/conftest.py', 'import warnings\nwarnings.filterwarnings("ignore")\n')
        repo.write('pytest.ini', '[pytest]\nfilterwarnings = ignore\n')
        repo.commit('warnings')
        code, out = report(repo, base)
        self.assertEqual(code, 0)
        self.assertEqual(findings(out), [
            'ignored warning: pytest.ini:2',
            'ignored warning: tests/conftest.py:2',
        ])

    def test_clean_diff_reports_nothing(self):
        repo = Repo(self)
        repo.write('tests/test_old.py',
                   'import pytest\nfrom unittest.mock import patch\n\n'
                   '@pytest.mark.skip\ndef test_old():\n    assert False\n\n'
                   '@patch("pkg.widget.spin")\ndef test_patched(fake):\n    assert fake\n\n'
                   'def test_live():\n    assert 1 == 1\n')
        repo.write('pkg/widget.py', 'def spin():\n    return 1\n')
        base = repo.commit('seed')
        repo.write('tests/test_old.py',
                   'import pytest\nfrom unittest.mock import patch\n\n'
                   '@pytest.mark.skip\ndef test_old():\n    assert False\n\n'
                   '@patch("pkg.widget.spin")\ndef test_patched(fake):\n    assert fake\n\n'
                   'def test_live():\n    assert 1 == 2\n')
        repo.write('tests/test_new.py', 'def test_new():\n    assert 1 + 1 == 2\n')
        repo.write('pkg/widget.py', 'def spin():\n    return 2\n')
        repo.commit('edit')
        code, out = report(repo, base)
        self.assertEqual(code, 0)
        self.assertEqual(findings(out), [])
        self.assertEqual(out, '')

    def test_unreadable_diff_exits_nonzero_without_findings(self):
        repo = Repo(self)
        code, out = report(repo, 'no-such-rev')
        self.assertNotEqual(code, 0)
        self.assertEqual(findings(out), [])
        self.assertNotIn('deleted test', out)
        self.assertNotIn('new skip mark', out)
        self.assertNotIn('new mock', out)
        self.assertNotIn('ignored warning', out)


if __name__ == '__main__':
    unittest.main()
