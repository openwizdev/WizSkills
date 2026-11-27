#!/usr/bin/env python3
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / 'prove.py'
FIXTURES = HERE / 'fixtures' / 'prove'
COMMAND = [sys.executable, '-m', 'unittest', 'test_calc']
ENV = {**os.environ, 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1',
       'GIT_AUTHOR_NAME': 'Synthetic', 'GIT_AUTHOR_EMAIL': 'synthetic@example.com',
       'GIT_COMMITTER_NAME': 'Synthetic', 'GIT_COMMITTER_EMAIL': 'synthetic@example.com'}


def load():
    spec = importlib.util.spec_from_file_location('prove', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Repo(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='prove-test-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo, self.scratch = self.tmp / 'repo', self.tmp / 'scratch'
        self.scratch.mkdir()
        self.env = {**ENV, 'TMPDIR': str(self.scratch)}

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.repo), *args], env=self.env, check=True,
                              capture_output=True, text=True).stdout.strip()

    def build(self, case):
        self.repo.mkdir()
        self.git('init', '-q', '-b', 'main')
        for side in ('base', 'head'):
            for old in self.repo.iterdir():
                if old.name != '.git':
                    shutil.rmtree(old) if old.is_dir() else old.unlink()
            shutil.copytree(FIXTURES / case / side, self.repo, dirs_exist_ok=True)
            self.git('add', '-A')
            self.git('commit', '-q', '-m', side)
        return self.git('rev-parse', 'HEAD^'), self.git('rev-parse', 'HEAD')

    def prove(self, *args, command=COMMAND):
        return subprocess.run([sys.executable, '-I', str(SCRIPT), *args, '--', *command],
                              cwd=self.repo, env=self.env, capture_output=True, text=True, timeout=120)

    def run_case(self, case, *extra):
        base, head = self.build(case)
        done = self.prove('--base', 'HEAD^', '--test', 'test_calc.py', *extra)
        lines = done.stdout.splitlines()
        self.assertEqual(len(lines), 1, done.stdout + done.stderr)
        result = json.loads(lines[0])
        self.assertEqual((result['base'], result['head']), (base, head))
        self.assertGone()
        return done, result

    def assertGone(self):
        listed = self.git('worktree', 'list', '--porcelain').count('worktree ')
        self.assertEqual(listed, 1, 'a throwaway worktree is still registered')
        self.assertEqual(list(self.scratch.iterdir()), [], 'a throwaway worktree is still on disk')

    def test_red_then_green_exits_0(self):
        done, result = self.run_case('red-green')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(result['base_runs'], ['failed', 'failed'])
        self.assertEqual(result['head_runs'], ['passed', 'passed'])
        self.assertEqual((result['verdict'], result['broke']), ('pass', None))

    def test_base_that_cannot_import_is_error_not_red(self):
        done, result = self.run_case('base-error')
        self.assertEqual(done.returncode, 1)
        self.assertEqual(result['base_runs'], ['error', 'error'])
        self.assertEqual((result['verdict'], result['broke']), ('fail', 'base'))
        self.assertIn('base must be failed 2 of 2', done.stderr)

    def test_test_that_already_passes_on_base_exits_1(self):
        done, result = self.run_case('base-passes')
        self.assertEqual(done.returncode, 1)
        self.assertEqual(result['base_runs'], ['passed', 'passed'])
        self.assertEqual(result['broke'], 'base')

    def test_flaky_head_one_of_two_exits_1(self):
        done, result = self.run_case('flaky-head')
        self.assertEqual(done.returncode, 1)
        self.assertEqual(result['base_runs'], ['failed', 'failed'])
        self.assertEqual(result['head_runs'], ['passed', 'failed'])
        self.assertEqual(result['broke'], 'head')
        self.assertIn('head must be passed 2 of 2', done.stderr)

    def test_timeout_is_error(self):
        done, result = self.run_case('timeout', '--timeout', '2')
        self.assertEqual(done.returncode, 1)
        self.assertEqual(result['base_runs'], ['failed', 'failed'])
        self.assertEqual(result['head_runs'], ['error', 'error'])
        self.assertIn('head run 1: error (timeout)', done.stderr)

    def test_new_test_is_copied_but_base_code_is_not_changed(self):
        self.build('red-green')
        probe = [sys.executable, '-c', 'import sys; print(open("calc.py").read()); sys.exit(3)']
        done = self.prove('--base', 'HEAD^', '--test', 'test_calc.py', command=probe)
        self.assertEqual(done.returncode, 1)
        self.assertEqual(done.stderr.count('a - b'), 2, done.stderr)
        self.assertEqual(done.stderr.count('a + b'), 2, done.stderr)
        self.assertGone()

    def test_unknown_base_refuses_with_2_and_leaves_nothing(self):
        self.build('red-green')
        done = self.prove('--base', 'no-such-ref', '--test', 'test_calc.py')
        self.assertEqual((done.returncode, done.stdout), (2, ''))
        self.assertIn('no-such-ref', done.stderr)
        self.assertGone()

    def test_bad_test_paths_refuse_with_2(self):
        self.build('red-green')
        for path in ('missing.py', '../outside.py', '/etc/hosts'):
            with self.subTest(path=path):
                done = self.prove('--base', 'HEAD^', '--test', path)
                self.assertEqual((done.returncode, done.stdout), (2, ''))
        self.assertGone()

    def test_missing_command_refuses_with_2(self):
        self.build('red-green')
        done = subprocess.run([sys.executable, '-I', str(SCRIPT), '--base', 'HEAD^', '--test', 'test_calc.py'],
                              cwd=self.repo, env=self.env, capture_output=True, text=True)
        self.assertEqual(done.returncode, 2)
        self.assertIn('after --', done.stderr)

    def test_command_not_on_path_refuses_with_2_and_leaves_nothing(self):
        self.build('red-green')
        done = self.prove('--base', 'HEAD^', '--test', 'test_calc.py', command=['prove-missing-synthetic'])
        self.assertEqual((done.returncode, done.stdout), (2, ''))
        self.assertIn('prove: cannot run prove-missing-synthetic:', done.stderr)
        self.assertNotIn('Traceback', done.stderr)
        self.assertGone()


    def test_help_says_refusals_leave_stdout_empty(self):
        done = subprocess.run([sys.executable, '-I', str(SCRIPT), '--help'],
                              env=self.env, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('exit 2 leaves stdout empty', ' '.join(done.stdout.lower().split()))


PYTEST_PASS = """============================= test session starts ==============================
collected 2 items

test_a.py ..                                                             [100%]

============================== 2 passed in 0.01s ===============================
"""
PYTEST_ASSERT = """test_a.py:4: AssertionError
=========================== short test summary info ============================
FAILED test_a.py::test_bad - assert 1 == 2
========================= 1 failed, 1 passed in 0.02s ==========================
"""
PYTEST_RAISES = """=========================== short test summary info ============================
FAILED test_a.py::test_bad - assert 1 == 2
FAILED test_a.py::test_exc - NameError: name 'x' is not defined
========================= 2 failed, 1 passed in 0.02s ==========================
"""
PYTEST_COLLECT = """E   ModuleNotFoundError: No module named 'calc'
=========================== short test summary info ============================
ERROR test_b.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
=============================== 1 error in 0.07s ===============================
"""
PYTEST_QUIET = """FAILED test_a.py::test_bad - assert 1 == 2
1 failed, 1 passed in 0.01s
"""
PYTEST_SPACE = """=========================== short test summary info ============================
FAILED test_a.py::test_bad[hello world] - assert 1 == 2
============================== 1 failed in 0.02s ===============================
"""
UNITTEST_OK = "..\n----------------------------------------------------------------------\nRan 2 tests in 0.000s\n\nOK\n"
UNITTEST_FAIL = "F.\n----------------------------------------------------------------------\nRan 2 tests in 0.000s\n\nFAILED (failures=1)\n"
UNITTEST_ERRORS = "E.\n----------------------------------------------------------------------\nRan 2 tests in 0.000s\n\nFAILED (errors=1)\n"
UNITTEST_IMPORT = ("E\n======================================================================\nERROR: test_calc (unittest.loader._FailedTest.test_calc)\n"
                   "ImportError: Failed to import test module: test_calc\n\nRan 1 test in 0.000s\n\nFAILED (errors=1)\n")
UNITTEST_NONE = "\n----------------------------------------------------------------------\nRan 0 tests in 0.000s\n\nOK\n"
UNITTEST_UNEXPECTED = ("F.\n----------------------------------------------------------------------\nRan 2 tests in 0.000s\n\n"
                       "FAILED (failures=1, unexpected successes=1)\n")
CARGO_OK = "running 2 tests\ntest a ... ok\ntest b ... ok\n\ntest result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s\n"
CARGO_FAIL = ("running 2 tests\ntest a ... ok\ntest b ... FAILED\n\nthread 'b' panicked at src/lib.rs:9:5:\nassertion `left == right` failed\n"
              "test result: FAILED. 1 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s\n\n"
              "error: test failed, to rerun pass `--lib`\n")
CARGO_BUILD = "error[E0425]: cannot find function `add` in this scope\nerror: could not compile `calc` (lib test) due to 1 previous error\n"
NODE_PASS = "✔ ok (0.4ms)\nℹ tests 1\nℹ suites 0\nℹ pass 1\nℹ fail 0\nℹ cancelled 0\nℹ skipped 0\n"
NODE_ASSERT = ("ℹ tests 2\nℹ suites 0\nℹ pass 1\nℹ fail 1\nℹ cancelled 0\n\n✖ failing tests:\n\n"
               "test at a.test.mjs:2:38\n✖ bad (0.58ms)\n  AssertionError [ERR_ASSERTION]: 1 == 2\n    code: 'ERR_ASSERTION',\n")
NODE_THROWS = ("ℹ tests 1\nℹ suites 0\nℹ pass 0\nℹ fail 1\nℹ cancelled 0\n\n✖ failing tests:\n\n"
               "test at c.test.mjs:2:1\n✖ throws (0.53ms)\n  TypeError [Error]: nope\n")
NODE_IMPORT = ("  code: 'ERR_MODULE_NOT_FOUND',\n✖ b.test.mjs (31ms)\nℹ tests 1\nℹ suites 0\nℹ pass 0\nℹ fail 1\n"
               "ℹ cancelled 0\n\n✖ failing tests:\n\ntest at b.test.mjs:1:1\n✖ b.test.mjs (31ms)\n  'test failed'\n")
NODE_TAP = ("TAP version 13\nnot ok 1 - bad\n  ---\n  failureType: 'testCodeFailure'\n  error: '1 == 2'\n  code: 'ERR_ASSERTION'\n  ...\n"
            "1..1\n# tests 1\n# suites 0\n# pass 0\n# fail 1\n# cancelled 0\n")
NODE_SUBTEST = ("▶ parent\n  ✖ inner (1ms)\n✖ parent (2ms)\n"
                "ℹ tests 2\nℹ suites 0\nℹ pass 0\nℹ fail 2\nℹ cancelled 0\n\n✖ failing tests:\n\n"
                "test at a.test.mjs:4:11\n✖ inner (1ms)\n  AssertionError [ERR_ASSERTION]: 1 !== 2\n")
NODE_SUBTEST_TAP = ("TAP version 13\n    not ok 1 - inner\n      ---\n      failureType: 'testCodeFailure'\n"
                    "      code: 'ERR_ASSERTION'\n      ...\n"
                    "not ok 1 - parent\n  ---\n  failureType: 'subtestsFailed'\n  error: '1 subtest failed'\n"
                    "  code: 'ERR_TEST_FAILURE'\n  ...\n"
                    "# tests 2\n# suites 0\n# pass 0\n# fail 2\n# cancelled 0\n")
NODE_SUBTEST_THROWS = ("▶ parent\n  ✖ inner (1ms)\n✖ parent (2ms)\n"
                       "ℹ tests 2\nℹ suites 0\nℹ pass 0\nℹ fail 2\nℹ cancelled 0\n\n✖ failing tests:\n\n"
                       "test at a.test.mjs:3:11\n✖ inner (1ms)\n  TypeError: nope\n")


NODE_MIXED_SUBTEST = """▶ parent
  ✖ asserting leaf (1ms)
  ✖ throwing leaf (1ms)
✖ parent (2ms)
ℹ tests 3
ℹ suites 0
ℹ pass 0
ℹ fail 3
ℹ cancelled 0

✖ failing tests:

test at a.test.mjs:4:11
✖ asserting leaf (1ms)
  AssertionError [ERR_ASSERTION]: 1 !== 2

test at a.test.mjs:5:11
✖ throwing leaf (1ms)
  TypeError [Error]: 1 subtest failed
"""
NODE_SPEC_HOOK = """▶ suite
  ▶ parent
    ✖ leaf (1ms)
  ✖ parent (2ms)
✖ suite (3ms)
ℹ tests 2
ℹ suites 1
ℹ pass 0
ℹ fail 2
ℹ cancelled 0

✖ failing tests:

test at a.test.mjs:4:11
✖ leaf (1ms)
  AssertionError [ERR_ASSERTION]: 1 !== 2

test at a.test.mjs:1:1
✖ suite (3ms)
  AssertionError [ERR_ASSERTION]: 3 !== 4
      at SuiteContext.<anonymous> (file:///synthetic/a.test.mjs:2:22)
      at TestHook.run (node:internal/test_runner/test:1402:25)
"""
NODE_SUITE_TAP = """TAP version 13
# Subtest: suite
    # Subtest: parent
        # Subtest: leaf
        not ok 1 - leaf
          ---
          type: 'test'
          failureType: 'testCodeFailure'
          error: '1 !== 2'
          code: 'ERR_ASSERTION'
          name: 'AssertionError'
          ...
        1..1
    not ok 1 - parent
      ---
      type: 'test'
      failureType: 'subtestsFailed'
      error: '1 subtest failed'
      code: 'ERR_TEST_FAILURE'
      ...
    1..1
not ok 1 - suite
  ---
  type: 'suite'
  failureType: 'subtestsFailed'
  error: '1 subtest failed'
  code: 'ERR_TEST_FAILURE'
  ...
1..1
# tests 2
# suites 1
# pass 0
# fail 2
# cancelled 0
"""


class Classify(unittest.TestCase):
    def check(self, rows):
        self.assertTrue(SCRIPT.is_file(), 'prove.py is missing')
        prove = load()
        for name, code, out, want in rows:
            with self.subTest(name):
                self.assertEqual(prove.classify(code, out), want)

    def test_pytest(self):
        self.check([('passed', 0, PYTEST_PASS, 'passed'),
                    ('assertion', 1, PYTEST_ASSERT, 'failed'),
                    ('quiet assertion', 1, PYTEST_QUIET, 'failed'),
                    ('a test that raises is not red', 1, PYTEST_RAISES, 'error'),
                    ('collection error', 2, PYTEST_COLLECT, 'error'),
                    ('no tests ran', 5, '===== no tests ran in 0.01s =====\n', 'error'),
                    ('passed summary but non-zero exit', 1, PYTEST_PASS, 'error'),
                    ('parametrized id with a space', 1, PYTEST_SPACE, 'failed'),
                    ('brackets in the test path', 1,
                     PYTEST_ASSERT.replace('test_a.py', 'tests[legacy]/test_a.py'), 'failed'),
                    ('separator in the id and the assertion', 1,
                     PYTEST_SPACE.replace('test_a.py', 'tests[legacy]/test_a.py')
                     .replace('hello world', 'New York - Boston').replace('1 == 2', '5 - 3 == 0'),
                     'failed'),
                    ('exception after an id with the separator', 1,
                     PYTEST_SPACE.replace('hello world', 'New York - Boston')
                     .replace('assert 1 == 2', 'TypeError: a - b'), 'error')])

    def test_unittest(self):
        self.check([('ok', 0, UNITTEST_OK, 'passed'),
                    ('failure', 1, UNITTEST_FAIL, 'failed'),
                    ('errors', 1, UNITTEST_ERRORS, 'error'),
                    ('import failure', 1, UNITTEST_IMPORT, 'error'),
                    ('zero tests', 0, UNITTEST_NONE, 'error'),
                    ('unexpected successes', 1, UNITTEST_UNEXPECTED, 'error')])

    def test_cargo(self):
        self.check([('ok', 0, CARGO_OK, 'passed'),
                    ('failed', 101, CARGO_FAIL, 'failed'),
                    ('does not build', 101, CARGO_BUILD, 'error'),
                    ('built one target, broke another', 101, CARGO_OK + CARGO_BUILD, 'error')])

    def test_node(self):
        self.check([('pass', 0, NODE_PASS, 'passed'),
                    ('assertion', 1, NODE_ASSERT, 'failed'),
                    ('a test that throws is not red', 1, NODE_THROWS, 'error'),
                    ('file does not import', 1, NODE_IMPORT, 'error'),
                    ('tap assertion', 1, NODE_TAP, 'failed'),
                    ('subtest assertion', 1, NODE_SUBTEST, 'failed'),
                    ('tap subtest assertion', 1, NODE_SUBTEST_TAP, 'failed'),
                    ('a subtest that throws is not red', 1, NODE_SUBTEST_THROWS, 'error'),
                    ('an assertion can mention a failed subtest', 1,
                     NODE_SUBTEST.replace('1 !== 2', '1 subtest failed'), 'failed'),
                    ('a thrown exception can mention a failed subtest', 1, NODE_MIXED_SUBTEST, 'error'),
                    ('spec suite hook mixed with a test assertion is an error', 1, NODE_SPEC_HOOK, 'error'),
                    ('tap suite aggregate is outside the test failure count', 1, NODE_SUITE_TAP, 'failed'),
                    ('tap suite hook failures are errors', 1,
                     NODE_SUITE_TAP.replace("type: 'suite'\n  failureType: 'subtestsFailed'",
                                            "type: 'suite'\n  failureType: 'hookFailed'"), 'error')])

    def test_unrecognised_and_timeout_are_error(self):
        self.check([('no summary, exit 1', 1, 'Traceback (most recent call last):\nAssertionError\n', 'error'),
                    ('no summary, exit 0', 0, 'all good\n', 'error'),
                    ('timeout', None, UNITTEST_FAIL, 'error')])


if __name__ == '__main__':
    unittest.main()
