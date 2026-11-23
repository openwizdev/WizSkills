import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / 'checklist_rules.py'
CHECKLIST = HERE.parent / 'skills' / 'build-ticket' / 'checklist.md'
spec = importlib.util.spec_from_file_location('wizskills_checklist_rules', SCRIPT)
rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rules)

TMP = '/' + 'tmp/'
CLOCK = 'time.' + 'monotonic()'
AT_LEAST = 'self.assert' + 'GreaterEqual(len(rows), 1)'
GIT_ENV = {'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_AUTHOR_NAME': 'Synthetic',
           'GIT_AUTHOR_EMAIL': 'synthetic@example.invalid', 'GIT_COMMITTER_NAME': 'Synthetic',
           'GIT_COMMITTER_EMAIL': 'synthetic@example.invalid'}
TAG = re.compile(r'^- \*\*([^*]+)\*\* \((judgment|mechanical, check `([a-z-]+)`|'
                 r'mechanical, follow-up openwizdev/OpenWiz#[1-9][0-9]*)\) \S')


def git(root, *args):
    run = subprocess.run(['git', *args], cwd=root, capture_output=True, text=True,
                         env={**os.environ, **GIT_ENV})
    if run.returncode:
        raise AssertionError(f'git {args[0]} failed: {run.stderr}')
    return run.stdout


def repo(tmp, base, head):
    root = Path(tmp)
    git(root, 'init', '-q', '-b', 'main')
    for files in (base, head):
        for rel, text in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text, encoding='utf-8')
        git(root, 'add', '-A')
        git(root, 'commit', '-q', '--allow-empty', '-m', 'step')
        if files is base:
            git(root, 'checkout', '-q', '-b', 'work')
    return root


def check(root, *args):
    run = subprocess.run([sys.executable, '-I', str(SCRIPT), *(args or ('diff', '--base', 'main'))],
                         cwd=root, capture_output=True, text=True, env={**os.environ, **GIT_ENV})
    return run.returncode, run.stdout.splitlines(), run.stderr


class Rules(unittest.TestCase):
    def run_case(self, base, head, *args):
        with tempfile.TemporaryDirectory() as tmp:
            return check(repo(tmp, base, head), *args)

    def assert_findings(self, head, expected, base=None):
        code, out, err = self.run_case(base or {'README.md': 'x\n'}, head)
        found = [line.split(':', 3)[1].strip() + ':' + line.split(':', 3)[2] for line in out[:-1]]
        self.assertEqual(found, expected, out)
        self.assertEqual(out[-1], f'checklist: fail ({len(expected)})' if expected else 'checklist: pass', out)
        self.assertEqual(code, 1 if expected else 0, err)

    def test_each_rule_refuses_its_planted_break(self):
        for rule, line in (('exact-counts', AT_LEAST),
                           ('exact-counts', 'assert len(rows) ' + '> 0'),
                           ('exact-counts', "assert.ok(rows.length " + ">= 1, 'rows')"),
                           ('clock', 'self.assertLess(' + CLOCK + ' - began, 2)'),
                           ('clock', 'assert.ok(Date.' + 'now() < deadline)'),
                           ('own-temp', "out = Path('" + TMP + "wizskills-run')"),
                           ('own-temp', 'log=' + TMP + 'run.log')):
            with self.subTest(rule=rule, line=line):
                self.assert_findings({'skills/a/tests/test_a.py': 'import x\n' + line + '\n'},
                                     [f'{rule} skills/a/tests/test_a.py:2'])

    def test_every_test_file_form_is_read(self):
        for rel in ('skills/a/scripts/test-host.py', 'skills/a/test/helpers.py', 'check/test_x.py',
                    'skills/a/scripts/test.sh', 'skills/a/scripts/loop.test.mjs', 'skills/a/scripts/test é.py'):
            with self.subTest(rel=rel):
                self.assert_findings({rel: AT_LEAST + '\n'}, [f'exact-counts {rel}:1'])

    def test_exact_count_per_line(self):
        self.assert_findings({'check/test_x.py': f'{AT_LEAST}\nok = 1\n{AT_LEAST}\n'},
                             ['exact-counts check/test_x.py:1', 'exact-counts check/test_x.py:3'])

    def test_only_added_lines_of_test_files(self):
        self.assert_findings({'check/test_x.py': f'{AT_LEAST}\nnew = 2\n', 'check/tool.py': AT_LEAST + '\n'}, [],
                             base={'check/test_x.py': AT_LEAST + '\n'})

    def test_the_good_forms_pass(self):
        good = ('self.assertEqual(len(rows), 2)', 'began = ' + CLOCK, 'self.assertGreater(after, before)',
                'tmp = tempfile.mkdtemp()', "self.assertEqual(path, Path(tmp, 'x'))")
        self.assert_findings({'check/test_x.py': '\n'.join(good) + '\n'}, [])

    def test_an_unreadable_diff_never_passes(self):
        for args in (('diff', '--base', 'no-such-rev'), ('diff',), ('tree',), ()):
            with self.subTest(args=args):
                code, out, _ = self.run_case({'README.md': 'x\n'}, {'check/test_x.py': 'x = 1\n'}, *args)
                self.assertEqual(code, 2, out)
                self.assertNotIn('checklist: pass', out)


class Checklist(unittest.TestCase):
    def test_every_line_has_exactly_one_tag_and_each_check_its_line(self):
        lines = [line for line in CHECKLIST.read_text(encoding='utf-8').splitlines() if line.startswith('- ')]
        self.assertEqual(len(lines), 37)
        named = {}
        for line in lines:
            with self.subTest(line=line[:40]):
                self.assertEqual(len(re.findall(r'\((?:judgment|mechanical)\b', line)), 1)
                tag = TAG.match(line)
                self.assertIsNotNone(tag)
                if tag[3]:
                    named.setdefault(tag[3], []).append(tag[1])
        self.assertEqual(named, {rule: [title] for rule, title in rules.RULES.items()})


if __name__ == '__main__':
    unittest.main()
