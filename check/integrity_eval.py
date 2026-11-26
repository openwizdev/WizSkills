#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCRIPT = ROOT / 'check' / 'integrity.py'
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


class Repo:
    def __init__(self):
        self.dir = Path(tempfile.mkdtemp(prefix='integrity-eval-'))
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


def added(repo, mapping):
    for rel, text in mapping.items():
        repo.write(rel, text)
    repo.commit('add')
    return repo.base


def edited(repo, before, after):
    for rel, text in before.items():
        repo.write(rel, text)
    base = repo.commit('before')
    for rel, text in after.items():
        if text is None:
            repo.remove(rel)
        else:
            repo.write(rel, text)
    repo.commit('after')
    return base


def case_deleted_file(repo):
    return edited(repo, {'tests/test_old.py': 'VALUE = 1\n', 'pkg/widget.py': 'VALUE = 1\n'},
                  {'tests/test_old.py': None, 'pkg/widget.py': None})


def case_deleted_function(repo):
    return edited(
        repo,
        {'tests/test_keep.py': 'def test_keep():\n    assert True\n\n\ndef test_gone():\n    assert True\n'},
        {'tests/test_keep.py': 'def test_keep():\n    assert True\n'},
    )


def case_rename(repo):
    return edited(repo, {'tests/test_names.py': 'def test_old_name():\n    assert True\n'},
                  {'tests/test_names.py': 'def test_new_name():\n    assert True\n'})


def case_skips(repo):
    return added(repo, {
        'tests/test_skip.py': 'import pytest\n' '@pytest.mark.skip\n' 'def test_a():\n    assert True\n',
        'tests/test_skipif.py': 'import pytest\n' '@pytest.mark.skipif(True, reason="synthetic")\n'
                                'def test_a():\n    assert True\n',
        'tests/test_xfail.py': 'import pytest\n' '@pytest.mark.xfail\n' 'def test_a():\n    assert True\n',
        'tests/test_unit.py': 'import unittest\n' '@unittest.skip("synthetic")\n' 'def test_a():\n    assert True\n',
    })


def case_mocks(repo):
    return added(repo, {
        'tests/test_spin.py': 'from unittest.mock import patch\n\n@patch("pkg.widget.spin")\n'
                              'def test_spin(fake):\n    assert fake is not None\n',
        'tests/test_env.py': 'def test_env(monkeypatch):\n    monkeypatch.setattr("pkg.widget.spin", lambda: None)\n',
    })


def case_helper(repo):
    return added(repo, {
        'tests/test_helper.py': 'from unittest.mock import patch\n\n@patch("tests.helper.fake")\n'
                                'def test_helper(fake):\n    assert fake is not None\n',
    })


def case_warnings(repo):
    return added(repo, {
        'tests/conftest.py': 'import warnings\nwarnings.filterwarnings("ignore")\n',
        'pytest.ini': '[pytest]\nfilterwarnings = ignore\n',
    })


def case_clean(repo):
    body = ('import pytest\nfrom unittest.mock import patch\n\n'
            '@pytest.mark.skip\ndef test_old():\n    assert False\n\n'
            '@patch("pkg.widget.spin")\ndef test_patched(fake):\n    assert fake\n\n'
            'def test_live():\n    assert 1 == %s\n')
    return edited(repo, {
        'tests/test_old.py': body % '1',
        'pkg/widget.py': 'def spin():\n    return 1\n',
    }, {
        'tests/test_old.py': body % '2',
        'tests/test_new.py': 'def test_new():\n    assert 1 + 1 == 2\n',
        'pkg/widget.py': 'def spin():\n    return 2\n',
    })


def case_keyword(repo):
    return added(repo, {'tests/conftest.py': 'import warnings\nwarnings.filterwarnings(action="ignore")\n'})


def case_multiline(repo):
    return edited(repo, {'tests/conftest.py': 'import warnings\nwarnings.filterwarnings(\n    "error",\n)\n'},
                  {'tests/conftest.py': 'import warnings\nwarnings.filterwarnings(\n    "ignore",\n)\n'})


def case_config(repo):
    return added(repo, {
        'pytest.ini': '[pytest]\nfilterwarnings =\n    error::UserWarning\n    ignore::DeprecationWarning\n',
        'pyproject.toml': '[tool.pytest.ini_options]\nfilterwarnings = [\n    "error::UserWarning",\n'
                          '    "ignore::DeprecationWarning",\n]\n',
    })


def case_plus_line(repo):
    return added(repo, {'pytest.ini': '[pytest]\n++filterwarnings = ignore\n'})


def case_syntax(repo):
    return edited(repo, {'tests/test_keep.py': 'def test_keep():\n    assert True\n\ndef test_also():\n    assert True\n'},
                  {'tests/test_keep.py': 'def test_keep():\n    assert True\n\ndef test_also(\n    assert True\n'})


def case_repair(repo):
    return edited(repo, {'tests/test_keep.py': 'def test_keep(\n    assert True\n'},
                  {'tests/test_keep.py': 'def test_keep():\n    assert True\n'})


def case_gone_unparseable(repo):
    return edited(repo, {'tests/test_keep.py': 'def test_keep(\n    assert 1\ndef test_gone():\n    assert 1\n'},
                  {'tests/test_keep.py': 'def test_keep():\n    assert 1\n'})


def case_alias(repo):
    return added(repo, {
        'tests/test_alias.py': 'from pytest import mark\nfrom unittest.mock import patch as fake_patch\n'
                               '@mark.skip\n@fake_patch("pkg.widget.spin")\n'
                               'def test_a(fake):\n    assert fake\n',
    })


def case_inner(repo):
    return added(repo, {
        'tests/test_inner.py': 'def test_inner():\n    from unittest.mock import patch as fake_patch\n'
                               '    with fake_patch("pkg.widget.spin"):\n        assert True\n',
    })


def case_shadow(repo):
    return added(repo, {
        'tests/test_shadow.py': 'from unittest.mock import patch as fake_patch\n\n'
                                '@fake_patch("pkg.widget.spin")\n'
                                'def test_a(fake):\n    assert fake\n\n'
                                'def test_b():\n    from tests.helper import fake_patch\n    return fake_patch\n',
    })


def case_alias_helper(repo):
    return added(repo, {
        'tests/test_helper.py': 'from unittest.mock import patch as fake_patch\n\n'
                                '@fake_patch("tests.helper.fake")\n'
                                'def test_helper(fake):\n    assert fake is not None\n',
    })


def case_category(repo):
    return edited(
        repo,
        {'tests/conftest.py': 'import warnings\nwarnings.filterwarnings(\n    "ignore",\n'
                              '    category=DeprecationWarning,\n)\n'},
        {'tests/conftest.py': 'import warnings\nwarnings.filterwarnings(\n    "ignore",\n'
                              '    category=UserWarning,\n)\n'},
    )


CASES = (
    ('deleted-file', case_deleted_file, ['deleted test file: tests/test_old.py:1'], 0),
    ('deleted-function', case_deleted_function, ['deleted test function: tests/test_keep.py:5 test_gone'], 0),
    ('rename', case_rename, ['renamed test function: tests/test_names.py:1 test_old_name -> test_new_name'], 0),
    ('skips', case_skips, [
        'new skip mark: tests/test_skip.py:2 pytest.mark.skip',
        'new skip mark: tests/test_skipif.py:2 pytest.mark.skipif',
        'new skip mark: tests/test_unit.py:2 unittest.skip',
        'new skip mark: tests/test_xfail.py:2 pytest.mark.xfail',
    ], 0),
    ('mocks', case_mocks, [
        'new mock: tests/test_env.py:2 monkeypatch.setattr pkg.widget.spin',
        'new mock: tests/test_spin.py:3 patch pkg.widget.spin',
    ], 0),
    ('helper-not-reported', case_helper, [], 0),
    ('warnings', case_warnings, ['ignored warning: pytest.ini:2', 'ignored warning: tests/conftest.py:2'], 0),
    ('clean', case_clean, [], 0),
    ('keyword-ignore', case_keyword, ['ignored warning: tests/conftest.py:2'], 0),
    ('multiline-ignore', case_multiline, ['ignored warning: tests/conftest.py:3'], 0),
    ('continued-config', case_config, ['ignored warning: pyproject.toml:4', 'ignored warning: pytest.ini:4'], 0),
    ('plus-line', case_plus_line, ['ignored warning: pytest.ini:2'], 0),
    ('syntax-error', case_syntax, [], 0),
    ('repair-syntax', case_repair, [], 0),
    ('deleted-while-unparseable', case_gone_unparseable,
     ['deleted test function: tests/test_keep.py:3 test_gone'], 0),
    ('alias', case_alias, [
        'new mock: tests/test_alias.py:4 patch pkg.widget.spin',
        'new skip mark: tests/test_alias.py:3 pytest.mark.skip',
    ], 0),
    ('inner-alias', case_inner, ['new mock: tests/test_inner.py:3 patch pkg.widget.spin'], 0),
    ('shadow', case_shadow, ['new mock: tests/test_shadow.py:3 patch pkg.widget.spin'], 0),
    ('alias-helper', case_alias_helper, [], 0),
    ('category-edit', case_category, [], 0),
    ('unreadable', None, [], 1),
)


def findings(stdout):
    return [line for line in stdout.splitlines() if line.startswith(PREFIXES)]


def run_report(script, repo, base):
    done = subprocess.run(
        [sys.executable, '-I', str(script), '--base', base, '--head', 'HEAD', '--repo', str(repo.dir)],
        capture_output=True, text=True,
    )
    return done.returncode, findings(done.stdout)


def score(script):
    script = Path(script)
    started = time.perf_counter()
    true_positives = false_positives = false_negatives = 0
    failures = []
    case_failures = []
    for name, build, expected, expect_code in CASES:
        repo = Repo()
        try:
            if name == 'unreadable':
                code, got = run_report(script, repo, 'no-such-rev')
            else:
                base = build(repo)
                code, got = run_report(script, repo, base)
        finally:
            shutil.rmtree(repo.dir, True)
        exp, actual = set(expected), set(got)
        true_positives += len(exp & actual)
        false_positives += len(actual - exp)
        false_negatives += len(exp - actual)
        bad_code = (code != 0) if expect_code == 0 else code == 0
        if exp != actual or bad_code:
            failures.append({'case': name, 'expected': expected, 'actual': got, 'code': code})
        if bad_code:
            case_failures.append(name)
    expected_lines = true_positives + false_negatives
    predicted = true_positives + false_positives
    recall = 1.0 if expected_lines == 0 else true_positives / expected_lines
    precision = 1.0 if predicted == 0 else true_positives / predicted
    return {
        'script': str(script),
        'cases': len(CASES),
        'failed_cases': len(failures),
        'expected_lines': expected_lines,
        'true_positives': true_positives,
        'false_positives': false_positives,
        'false_negatives': false_negatives,
        'recall': recall,
        'precision': precision,
        'seconds': round(time.perf_counter() - started, 4),
        'case_failures': case_failures,
        'failures': failures,
    }


def main(argv):
    script = DEFAULT_SCRIPT
    repeat = 1
    args = list(argv[1:])
    while args:
        arg = args.pop(0)
        if arg == '--repeat':
            repeat = int(args.pop(0))
        elif arg == '--script':
            script = Path(args.pop(0))
        else:
            script = Path(arg)
    reports = [score(script) for _ in range(repeat)]
    seconds = sorted(item['seconds'] for item in reports)
    mid = seconds[len(seconds) // 2]
    shown = dict(reports[-1])
    shown['runs'] = repeat
    shown['seconds_min'] = seconds[0]
    shown['seconds_median'] = mid
    shown['seconds_max'] = seconds[-1]
    print(json.dumps(shown, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
