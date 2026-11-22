import contextlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
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
        standalone = ['python3', '-I', 'check/standalone.py', '--tree', '.']
        self.assertEqual(shards[1]['commands'], [{'suite': standalone, 'argv': standalone, 'cwd': '.'}])
        # A split suite (WQ2) is in each of its part shards `<row>.<n>`, and only there.
        whole = [s for s in shards[2:] if '.' not in s['name']]
        listed_commands = sorted((shard['skill'], tuple(command['suite']))
                                 for shard in whole for command in shard['commands'])
        split = {(row, tuple(suite)) for row, (suite, _) in run.PARTS.items()}
        expected = sorted((name, tuple(command)) for name, commands in run.SUITES.items()
                          for command in commands if (name, tuple(command)) not in split)
        self.assertEqual(listed_commands, expected)
        for row, (suite, count) in run.PARTS.items():
            self.assertEqual([(s['name'], s['skill'], [c['suite'] for c in s['commands']])
                              for s in shards if s['name'].startswith(row + '.')],
                             [(f'{row}.{n}', row, [suite]) for n in range(1, count + 1)])
        for shard in shards:
            self.assertEqual(set(shard), {'name', 'skill', 'commands', 'env'})
            if '.' not in shard['name']:
                self.assertEqual(shard['env'], {})
            for command in shard['commands']:
                self.assertEqual(set(command), {'suite', 'argv', 'cwd'})

    def test_every_listed_command_runs_as_listed(self):
        special = {
            'huntr': [['sh', 'skills/huntr/scripts/test.sh']],
            'unit': [['python3', '-I', 'skills/unit/test_unit.py'],
                     ['python3', '-I', '-m', 'unittest', 'discover', '-s', 'skills/unit/empty']],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'check').mkdir()
            consumer = root / 'check/fixtures/huntr-project/docs/agents'
            consumer.mkdir(parents=True)
            (consumer / 'huntr.md').write_text('synthetic consumer\n', encoding='utf-8')
            huntr = root / 'skills/huntr/scripts/test.sh'
            huntr.parent.mkdir(parents=True)
            huntr.write_text('set -eu\ntest -f docs/agents/huntr.md\n'
                             'echo huntr >> "$(dirname "$0")/../../../ran.log"\n', encoding='utf-8')
            (root / 'skills/unit/empty').mkdir(parents=True)
            (root / 'skills/unit/test_unit.py').write_text(
                'import unittest\n\nclass Unit(unittest.TestCase):\n    def test_it(self):\n'
                "        open('ran.log', 'a').write('unit\\n')\n", encoding='utf-8')
            (root / 'skills/unit/empty/test_empty.py').write_text(
                'import unittest\n\nclass Empty(unittest.TestCase):\n    pass\n', encoding='utf-8')
            code, lines = self.check('--list', root=root, suites=special)
            self.assertEqual(code, 0, lines)
            listed = [command for shard in json.loads('\n'.join(lines))[2:] for command in shard['commands']]
            for command in listed:
                self.assertIsInstance(command, dict)
            self.assertEqual([command['suite'] for command in listed], [*special['huntr'], *special['unit']])
            self.assertEqual(listed[0]['cwd'], 'check/fixtures/huntr-project')
            codes = []
            for command in listed:
                argv = [sys.executable if command['argv'][0] == 'python3' else command['argv'][0],
                        *command['argv'][1:]]
                codes.append(subprocess.run(argv, cwd=root / command['cwd'], capture_output=True).returncode)
            self.assertEqual(self.ran(root), ['huntr', 'unit'])
            self.assertEqual([code == 0 for code in codes], [True, True, False])
            from_root = subprocess.run(special['huntr'][0], cwd=root, capture_output=True)
            self.assertNotEqual(from_root.returncode, 0)

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

    def test_list_refuses_while_a_suite_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.synthetic(tmp)
            (root / 'skills' / 'beta' / 'test_three.py').unlink()
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code, lines = self.check('--list', root=root, suites=SYNTHETIC)
        self.assertEqual((code, lines), (1, []))
        self.assertEqual(err.getvalue().splitlines(),
                         ['suite beta: python3 -I skills/beta/test_three.py: missing'])

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


# A fleet.sh that does nothing: each part still selects and counts its cases.
FAKE_FLEET = '#!/bin/sh\nexit 0\n'


def part_record(path):
    """A launch-fleet test.sh part's TEST_SHARD_RAN record: its counts and groups."""
    record = {'groups_ran': []}
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        key, value = line.split()[:2]
        if key == 'group':
            record['groups_ran'].append(int(value))
        else:
            record[key] = int(value)
    return record


class SplitSuites(unittest.TestCase):
    """The parts of each split suite together run exactly the whole suite's cases (WQ2)."""

    def test_the_parts_of_launch_fleet_test_sh_run_every_case_once(self):
        p = subprocess.run([sys.executable, '-I', str(HERE / 'run.py'), '--list'],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        suite = ['sh', 'skills/launch-fleet/scripts/test.sh']
        parts = [shard for shard in json.loads(p.stdout)
                 if any(command['suite'] == suite for command in shard['commands'])]
        self.assertTrue(parts and all(shard['name'].startswith('launch-fleet.') for shard in parts),
                        f'launch-fleet test.sh is not split into parts: {[s["name"] for s in parts]}')
        for shard in parts:
            self.assertEqual(shard['skill'], 'launch-fleet')
            self.assertEqual([command['suite'] for command in shard['commands']], [suite])
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp, 'fleet.sh')
            fake.write_text(FAKE_FLEET, encoding='utf-8')
            def one(shard):
                record = Path(tmp, shard['name'] + '.ran')
                command = shard['commands'][0]
                env = {**run.clean_env(), **shard['env'], 'FLEET_SH': str(fake),
                       'TEST_SHARD_RAN': str(record), 'TEST_JOBS': '1'}
                subprocess.run(command['argv'], cwd=HERE.parent / command['cwd'], env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.assertTrue(record.is_file(), f'{shard["name"]} wrote no record')
                return shard['name'], part_record(record)
            with ThreadPoolExecutor(max_workers=os.cpu_count() or 1) as pool:
                records = dict(pool.map(one, parts))
        totals = {(r['total'], r['groups']) for r in records.values()}
        self.assertEqual(len(totals), 1, totals)
        (total, groups), = totals
        ran = [g for r in records.values() for g in r['groups_ran']]
        self.assertEqual(sorted(ran), list(range(1, groups + 1)),
                         'every group of the whole suite runs in exactly one part')
        self.assertEqual(sum(r['cases'] for r in records.values()), total,
                         "the parts' cases add up to the whole suite's")


if __name__ == '__main__':
    unittest.main()
