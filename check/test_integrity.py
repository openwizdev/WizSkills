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

    def write_bytes(self, rel, data):
        path = self.dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def remove(self, rel):
        (self.dir / rel).unlink()

    def commit(self, message):
        self.git('add', '-A')
        self.git('commit', '-m', message)
        return self.git('rev-parse', 'HEAD').strip()


def report(repo, base, summary=None):
    if not SCRIPT.is_file():
        return 0, ''
    env = {key: value for key, value in os.environ.items() if key != 'GITHUB_STEP_SUMMARY'}
    if summary:
        env['GITHUB_STEP_SUMMARY'] = str(summary)
    done = subprocess.run(
        [sys.executable, '-I', str(SCRIPT), '--base', base, '--head', 'HEAD', '--repo', str(repo.dir)],
        capture_output=True, text=True, env=env,
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

    def test_keyword_ignore_warning_is_reported(self):
        repo = Repo(self)
        repo.write('tests/conftest.py', 'import warnings\nwarnings.filterwarnings(action="ignore")\n')
        repo.commit('warn')
        code, out = report(repo, repo.base)
        self.assertEqual(code, 0)
        self.assertEqual(findings(out), ['ignored warning: tests/conftest.py:2'])

    def test_ignore_argument_on_its_own_line_is_reported(self):
        repo = Repo(self)
        repo.write('tests/conftest.py', 'import warnings\nwarnings.filterwarnings(\n    "error",\n)\n')
        base = repo.commit('error')
        repo.write('tests/conftest.py', 'import warnings\nwarnings.filterwarnings(\n    "ignore",\n)\n')
        repo.commit('ignore')
        code, out = report(repo, base)
        self.assertEqual(code, 0)
        self.assertEqual(findings(out), ['ignored warning: tests/conftest.py:3'])

    def test_editing_an_existing_ignore_category_is_not_a_new_warning(self):
        repo = Repo(self)
        repo.write('tests/conftest.py',
                   'import warnings\nwarnings.filterwarnings(\n    "ignore",\n'
                   '    category=DeprecationWarning,\n)\n')
        base = repo.commit('seed')
        repo.write('tests/conftest.py',
                   'import warnings\nwarnings.filterwarnings(\n    "ignore",\n'
                   '    category=UserWarning,\n)\n')
        repo.commit('edit')
        code, out = report(repo, base)
        self.assertEqual(code, 0)
        self.assertEqual(findings(out), [])
        self.assertEqual(out, '')

    def test_continued_pytest_ignore_filter_is_reported(self):
        repo = Repo(self)
        repo.write('pytest.ini',
                   '[pytest]\nfilterwarnings =\n    error::UserWarning\n    ignore::DeprecationWarning\n')
        repo.write('pyproject.toml',
                   '[tool.pytest.ini_options]\nfilterwarnings = [\n    "error::UserWarning",\n'
                   '    "ignore::DeprecationWarning",\n]\n')
        repo.commit('config')
        code, out = report(repo, repo.base)
        self.assertEqual(code, 0)
        self.assertEqual(findings(out), [
            'ignored warning: pyproject.toml:4',
            'ignored warning: pytest.ini:4',
        ])

    def test_added_line_of_plus_signs_still_reports_its_warning(self):
        repo = Repo(self)
        repo.write('pytest.ini', '[pytest]\n++filterwarnings = ignore\n')
        repo.commit('plus')
        code, out = report(repo, repo.base)
        self.assertEqual(code, 0)
        self.assertEqual(findings(out), ['ignored warning: pytest.ini:2'])

    def test_unparseable_test_file_is_not_reported_as_deleted_functions(self):
        repo = Repo(self)
        repo.write('tests/test_keep.py', 'def test_keep():\n    assert True\n\ndef test_also():\n    assert True\n')
        base = repo.commit('add')
        repo.write('tests/test_keep.py', 'def test_keep():\n    assert True\n\ndef test_also(\n    assert True\n')
        repo.commit('break')
        code, out = report(repo, base)
        self.assertEqual(code, 0)
        self.assertEqual(findings(out), [])
        self.assertEqual(out, '')

    def test_repairing_a_syntax_error_is_not_a_deleted_function(self):
        repo = Repo(self)
        repo.write('tests/test_keep.py', 'def test_keep(\n    assert True\n')
        base = repo.commit('bad')
        repo.write('tests/test_keep.py', 'def test_keep():\n    assert True\n')
        repo.commit('fix')
        code, out = report(repo, base)
        self.assertEqual(code, 0)
        self.assertEqual(findings(out), [])
        self.assertEqual(out, '')

    def test_deleted_function_in_an_unparseable_file_is_still_reported(self):
        repo = Repo(self)
        repo.write('tests/test_keep.py', 'def test_keep(\n    assert 1\ndef test_gone():\n    assert 1\n')
        base = repo.commit('bad')
        repo.write('tests/test_keep.py', 'def test_keep():\n    assert 1\n')
        repo.commit('drop')
        code, out = report(repo, base)
        self.assertEqual(code, 0)
        self.assertEqual(findings(out), ['deleted test function: tests/test_keep.py:3 test_gone'])

    def test_aliased_skip_and_patch_are_reported(self):
        repo = Repo(self)
        repo.write('tests/test_alias.py',
                   'from pytest import mark\nfrom unittest.mock import patch as fake_patch\n'
                   '@mark.skip\n@fake_patch("pkg.widget.spin")\n'
                   'def test_a(fake):\n    assert fake\n')
        repo.commit('alias')
        code, out = report(repo, repo.base)
        self.assertEqual(code, 0)
        self.assertEqual(findings(out), [
            'new mock: tests/test_alias.py:4 patch pkg.widget.spin',
            'new skip mark: tests/test_alias.py:3 pytest.mark.skip',
        ])

    def test_patch_imported_inside_the_test_is_reported(self):
        repo = Repo(self)
        repo.write('tests/test_inner.py',
                   'def test_inner():\n'
                   '    from unittest.mock import patch as fake_patch\n'
                   '    with fake_patch("pkg.widget.spin"):\n'
                   '        assert True\n')
        repo.commit('inner')
        code, out = report(repo, repo.base)
        self.assertEqual(code, 0)
        self.assertEqual(findings(out), ['new mock: tests/test_inner.py:3 patch pkg.widget.spin'])

    def test_later_import_does_not_hide_an_earlier_patch(self):
        repo = Repo(self)
        repo.write('tests/test_shadow.py',
                   'from unittest.mock import patch as fake_patch\n\n'
                   '@fake_patch("pkg.widget.spin")\n'
                   'def test_a(fake):\n'
                   '    assert fake\n\n'
                   'def test_b():\n'
                   '    from tests.helper import fake_patch\n'
                   '    return fake_patch\n')
        repo.commit('shadow')
        code, out = report(repo, repo.base)
        self.assertEqual(code, 0)
        self.assertEqual(findings(out), ['new mock: tests/test_shadow.py:3 patch pkg.widget.spin'])

    def test_aliased_patch_of_a_test_helper_is_not_reported(self):
        repo = Repo(self)
        repo.write('tests/test_helper.py',
                   'from unittest.mock import patch as fake_patch\n\n'
                   '@fake_patch("tests.helper.fake")\n'
                   'def test_helper(fake):\n    assert fake is not None\n')
        repo.commit('helper')
        code, out = report(repo, repo.base)
        self.assertEqual(code, 0)
        self.assertEqual(findings(out), [])
        self.assertEqual(out, '')


    def test_hyphenated_and_bare_test_scripts_are_test_files(self):
        repo = Repo(self)
        repo.write('skills/x/scripts/test-merge.py', 'def test_merge():\n    assert True\n')
        repo.write('skills/x/scripts/test.sh', 'echo ok\n')
        repo.write('skills/x/scripts/test.py', 'def test_all():\n    assert True\n')
        repo.write('skills/x/scripts/test-loop.sh', 'echo ok\n')
        repo.write('skills/x/scripts/test-status.py',
                   'from unittest import mock\nimport status\n\n\n'
                   'def test_keep():\n    assert True\n\n\ndef test_gone():\n    assert True\n')
        repo.write('skills/x/scripts/testing.py', 'VALUE = 1\n')
        base = repo.commit('scripts')
        for rel in ('test-merge.py', 'test.sh', 'test.py', 'test-loop.sh', 'testing.py'):
            repo.remove('skills/x/scripts/' + rel)
        repo.write('skills/x/scripts/test-status.py',
                   'from unittest import mock\nimport status\n\n\n'
                   '@mock.patch.object(status, "run")\ndef test_keep(run):\n    assert run\n')
        repo.commit('drop')
        code, out = report(repo, base)
        self.assertEqual(code, 0)
        self.assertEqual(findings(out), [
            'deleted test file: skills/x/scripts/test-loop.sh:1',
            'deleted test file: skills/x/scripts/test-merge.py:1',
            'deleted test file: skills/x/scripts/test.py:1',
            'deleted test file: skills/x/scripts/test.sh:1',
            'deleted test function: skills/x/scripts/test-merge.py:1 test_merge',
            'deleted test function: skills/x/scripts/test-status.py:9 test_gone',
            'deleted test function: skills/x/scripts/test.py:1 test_all',
            'new mock: skills/x/scripts/test-status.py:5 patch.object',
        ])

    def test_line_separators_inside_a_changed_line_keep_the_report_and_its_line_numbers(self):
        repo = Repo(self)
        repo.write('tests/test_keep.py', 'def test_keep():\n    assert True\n\n\ndef test_gone():\n    assert True\n')
        base = repo.commit('base')
        repo.write('tests/test_keep.py', 'def test_keep():\n    assert True\n')
        repo.write_bytes('tests/fixtures/stderr.txt', 'a\rb\u2028c\u2029d\x0be\x0cf\x1cg\x85h\n'.encode('utf-8'))
        repo.write_bytes('pytest.ini', b'[pytest]\r\n# a\rb\nfilterwarnings = ignore\n')
        repo.write_bytes('tests/test_cr.py', b'import pytest\n# a\rb\n'
                         b'@pytest.mark.skip\ndef test_a():\n    assert True\n')
        repo.commit('separators')
        code, out = report(repo, base)
        self.assertEqual(code, 0, out)
        self.assertEqual(findings(out), [
            'deleted test function: tests/test_keep.py:5 test_gone',
            'ignored warning: pytest.ini:3',
            'new skip mark: tests/test_cr.py:3 pytest.mark.skip',
        ])

    def test_bare_ignore_in_an_ini_list_is_reported_and_docs_are_not(self):
        repo = Repo(self)
        base = repo.base
        repo.write('pytest.ini', '[pytest]\nfilterwarnings =\n    ignore\n')
        repo.write('docs/guide.md', 'Run `python3 -W ignore x.py`, or set `filterwarnings = ignore`.\n')
        repo.write('skills/x/SKILL.md', 'Never pass -W ignore.\n')
        repo.commit('ini and docs')
        code, out = report(repo, base)
        self.assertEqual(code, 0)
        self.assertEqual(findings(out), ['ignored warning: pytest.ini:3'])

    def test_expected_failure_and_bare_skip_marks_are_reported(self):
        repo = Repo(self)
        base = repo.base
        repo.write('tests/test_expected.py', 'import unittest\n\n\nclass T(unittest.TestCase):\n'
                   '    @unittest.expectedFailure\n    def test_a(self):\n        assert False\n')
        repo.write('tests/test_module.py', 'import pytest\npytestmark = pytest.mark.skip\n\n\n'
                   'def test_a():\n    assert True\n')
        repo.write('tests/test_param.py', 'import pytest\n\n\n'
                   '@pytest.mark.parametrize("n", [1, pytest.param(2, marks=pytest.mark.skip)])\n'
                   'def test_n(n):\n    assert n\n')
        repo.commit('marks')
        code, out = report(repo, base)
        self.assertEqual(code, 0)
        self.assertEqual(findings(out), [
            'new skip mark: tests/test_expected.py:5 unittest.expectedFailure',
            'new skip mark: tests/test_module.py:2 pytest.mark.skip',
            'new skip mark: tests/test_param.py:4 pytest.mark.skip',
        ])

    def test_an_http_client_patch_call_is_not_a_mock(self):
        repo = Repo(self)
        base = repo.base
        repo.write('tests/test_api.py', 'import requests\n\n\ndef test_api(client):\n'
                   '    client.patch("/items/1")\n    requests.patch("https://example.com/items/1")\n')
        repo.commit('api')
        code, out = report(repo, base)
        self.assertEqual(code, 0)
        self.assertEqual(findings(out), [])

    def test_the_step_summary_shows_each_finding_on_its_own_line(self):
        repo = Repo(self)
        base = repo.base
        repo.write('tests/test_skip.py', 'import pytest\n'
                   '@pytest.mark.skip\ndef test_a():\n    assert True\n\n\n'
                   '@pytest.mark.xfail\ndef test_b():\n    assert True\n')
        repo.commit('marks')
        summary = repo.dir.parent / (repo.dir.name + '-summary.md')
        self.addCleanup(lambda: summary.unlink(missing_ok=True))
        code, out = report(repo, base, summary)
        self.assertEqual(code, 0)
        written = summary.read_text(encoding='utf-8') if summary.exists() else ''
        self.assertEqual(written, '## Test integrity\n\n```text\n' + out + '```\n')

if __name__ == '__main__':
    unittest.main()
