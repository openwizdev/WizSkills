import contextlib
import importlib.util
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('wizskills_run', HERE / 'run.py')
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


def listed(name):
    return [command[-1] for command in run.SUITES.get(name, [])]


class CheckSuites(unittest.TestCase):
    def test_every_check_test_runs_in_the_check_suite(self):
        tests = sorted(p.relative_to(HERE.parent).as_posix() for p in HERE.glob('test*.py'))
        self.assertIn('check/test_notice.py', tests)
        self.assertEqual(sorted(listed('check')), tests)

    def test_an_unlisted_check_test_fails_the_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'check').mkdir()
            (root / 'check' / 'test_synthetic.py').write_text('', encoding='utf-8')
            (root / 'skills').mkdir()
            out = io.StringIO()
            saved = run.SUITES
            run.SUITES = {}
            try:
                with contextlib.redirect_stdout(out):
                    ok = run.suites(root)
            finally:
                run.SUITES = saved
        self.assertFalse(ok)
        self.assertIn('suite inventory: check/test_synthetic.py: unlisted', out.getvalue())


SYNTHETIC = {
    'alpha': [['python3', '-I', 'skills/alpha/test_one.py'],
              ['python3', '-I', 'skills/alpha/test_two.py']],
    'beta': [['python3', '-I', 'skills/beta/test_three.py']],
    'gamma': [['python3', '-I', 'skills/gamma/test_four.py']],
}
SUITE_LINE = re.compile(r'suite (\S+): (.+): (pass|fail \(\d+\)) in \d+\.\d+s')


class CheckShards(unittest.TestCase):
    def check(self, *argv, root=None, suites=None):
        out = io.StringIO()
        saved = run.ROOT, run.SUITES
        if root is not None:
            run.ROOT, run.SUITES = root, suites
        try:
            with contextlib.redirect_stdout(out):
                code = run.main(list(argv))
        finally:
            run.ROOT, run.SUITES = saved
        return code, out.getvalue().splitlines()

    def synthetic(self, tmp, failing=()):
        root = Path(tmp)
        (root / 'check').mkdir()
        for commands in SYNTHETIC.values():
            for command in commands:
                path = root / command[-1]
                path.parent.mkdir(parents=True, exist_ok=True)
                code = 3 if path.stem in failing else 0
                path.write_text(f"open('ran.log', 'a').write({path.stem!r} + '\\n')\n"
                                f"raise SystemExit({code})\n", encoding='utf-8')
        return root

    def ran(self, root):
        log = root / 'ran.log'
        lines = log.read_text(encoding='utf-8').splitlines() if log.exists() else []
        log.unlink(missing_ok=True)
        return lines

    def test_list_covers_every_suite_exactly_once(self):
        p = subprocess.run([sys.executable, '-I', str(HERE / 'run.py'), '--list'],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        shards = json.loads(p.stdout)
        names = [shard['name'] for shard in shards]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(names[:2], ['rules', 'standalone'])
        self.assertEqual([shard['skill'] for shard in shards[:2]], [None, None])
        self.assertEqual(shards[1]['commands'], [['python3', '-I', 'check/standalone.py', '--tree', '.']])
        listed_commands = sorted((shard['skill'], tuple(command))
                                 for shard in shards[2:] for command in shard['commands'])
        expected = sorted((name, tuple(command))
                          for name, commands in run.SUITES.items() for command in commands)
        self.assertEqual(listed_commands, expected)
        for shard in shards:
            self.assertEqual(set(shard), {'name', 'skill', 'commands', 'env'})
            self.assertEqual(shard['env'], {})

    def test_a_shard_runs_only_its_own_suites(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.synthetic(tmp)
            code, lines = self.check('--shard', 'beta', root=root, suites=SYNTHETIC)
            self.assertEqual(code, 0, lines)
            self.assertEqual(self.ran(root), ['test_three'])
            self.assertFalse([line for line in lines if line.startswith(('rules', 'standalone'))])
            self.assertEqual(lines[-1], 'check: pass')
            code, lines = self.check('--shard', 'gamma,alpha', root=root, suites=SYNTHETIC)
            self.assertEqual(code, 0, lines)
            self.assertEqual(self.ran(root), ['test_one', 'test_two', 'test_four'])
            code, lines = self.check('--shard', 'standalone', root=root, suites=SYNTHETIC)
            self.assertEqual(self.ran(root), [])
            self.assertIn('standalone: missing check/standalone.py', lines)
            self.assertEqual(code, 1)

    def test_every_shard_together_runs_what_a_plain_run_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.synthetic(tmp, failing={'test_two'})
            plain_code, plain = self.check(root=root, suites=SYNTHETIC)
            plain_ran = self.ran(root)
            names = ','.join(['rules', 'standalone', *SYNTHETIC])
            code, lines = self.check('--shard', names, root=root, suites=SYNTHETIC)
            self.assertEqual(self.ran(root), plain_ran)
            self.assertEqual(plain_ran, ['test_one', 'test_two', 'test_three', 'test_four'])
            elapsed = re.compile(r' in \d+\.\d+s$')
            self.assertEqual([elapsed.sub('', line) for line in lines],
                             [elapsed.sub('', line) for line in plain])
            self.assertEqual((code, plain_code), (1, 1))

    def test_a_plain_run_adds_only_elapsed_seconds_to_suite_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.synthetic(tmp, failing={'test_three'})
            code, lines = self.check(root=root, suites=SYNTHETIC)
        self.assertEqual(code, 1)
        results = [SUITE_LINE.fullmatch(line) for line in lines if line.startswith('suite ')
                   and not line.endswith(': running')]
        self.assertTrue(all(results), lines)
        self.assertEqual([m.group(1, 3) for m in results],
                         [('alpha', 'pass'), ('alpha', 'pass'), ('beta', 'fail (3)'), ('gamma', 'pass')])
        self.assertIn('suite alpha: python3 -I skills/alpha/test_one.py: running', lines)
        self.assertTrue(lines[0].startswith('rules: '))
        self.assertIn('standalone: missing check/standalone.py', lines)
        self.assertEqual(lines[-1], 'check: fail')

    def test_the_suite_inventory_guard_runs_with_any_shard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.synthetic(tmp)
            (root / 'skills' / 'gamma' / 'test_unlisted.py').write_text('', encoding='utf-8')
            code, lines = self.check('--shard', 'beta', root=root, suites=SYNTHETIC)
            self.assertEqual(self.ran(root), ['test_three'])
        self.assertEqual(code, 1)
        self.assertIn('suite inventory: skills/gamma/test_unlisted.py: unlisted', lines)
        self.assertEqual(lines[-1], 'check: fail')

    def test_list_refuses_while_a_test_file_is_unlisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.synthetic(tmp)
            code, lines = self.check('--list', root=root, suites=SYNTHETIC)
            self.assertEqual(code, 0)
            self.assertEqual([shard['name'] for shard in json.loads('\n'.join(lines))],
                             ['rules', 'standalone', 'alpha', 'beta', 'gamma'])
            (root / 'skills' / 'gamma' / 'test_unlisted.py').write_text('', encoding='utf-8')
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code, lines = self.check('--list', root=root, suites=SYNTHETIC)
            self.assertEqual(self.ran(root), [])
        self.assertEqual((code, lines), (1, []))
        self.assertEqual(err.getvalue().splitlines(),
                         ['suite inventory: skills/gamma/test_unlisted.py: unlisted'])

    def test_an_unknown_shard_or_argument_exits_2_and_runs_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.synthetic(tmp)
            for argv in (['--shard', 'nope'], ['--shard', 'beta,nope'], ['--shard', ''],
                         ['--shard', 'beta,'], ['--shard'], ['--list', 'beta'],
                         ['--list', '--shard', 'beta'], ['--bogus']):
                with self.subTest(argv=argv):
                    with contextlib.redirect_stderr(io.StringIO()):
                        code, lines = self.check(*argv, root=root, suites=SYNTHETIC)
                    self.assertEqual((code, lines, self.ran(root)), (2, [], []))


if __name__ == '__main__':
    unittest.main()
