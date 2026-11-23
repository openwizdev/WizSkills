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
            if isinstance(text, bytes):
                (root / rel).write_bytes(text)
            else:
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
        found = [line.removeprefix('checklist: ').rsplit(': ', 1)[0] for line in out[:-1]]
        self.assertEqual((found, out[-1:]), (expected, [f'checklist: fail ({len(expected)})' if expected
                                                          else 'checklist: pass']), err)
        self.assertEqual(code, 1 if expected else 0, err)

    def test_each_rule_refuses_its_planted_break(self):
        for rule, line in (('exact-counts', AT_LEAST),
                           ('exact-counts', 'assert le' + 'n(rows) > 0'),
                           ('exact-counts', "assert.ok(rows.leng" + "th >= 1, 'rows')"),
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

    def test_a_binary_or_non_test_change_is_never_decoded(self):
        self.assert_findings({'skills/a/references/shot.png': b'\x89PNG\r\n\x1a\n\xff\x00\xfe',
                              'skills/a/notes.txt': b'caf\xe9 ' + AT_LEAST.encode() + b'\n'}, [])

    def test_patch_content_is_never_read_as_a_header(self):
        for text in ('++ counter;\n', '++ b/x\n' + AT_LEAST + '\n', '-- a/x\n', 'diff --git a/x b/x\n'):
            with self.subTest(text=text):
                count = text.count('\n')
                self.assert_findings({'skills/a/scripts/loop.test.mjs': text},
                                     [f'exact-counts skills/a/scripts/loop.test.mjs:{count}'] if AT_LEAST in text else [])

    def test_a_path_with_a_space_is_named_exactly(self):
        self.assert_findings({'check/test two.py': AT_LEAST + '\n'}, ['exact-counts check/test two.py:1'])

    def test_only_test_source_is_read(self):
        for rel in ('skills/a/test/README.md', 'skills/a/tests/fixtures/data.json', 'skills/a/test/notes.txt',
                    'skills/a/scripts/test-plan.md'):
            with self.subTest(rel=rel):
                self.assert_findings({rel: AT_LEAST + "\nout = '" + TMP + "x'\n"}, [])

    def test_text_and_unique_allocation_are_not_breaks(self):
        good = ('assert le' + 'n(rows) == 2, "expected count > 1"',
                "self.assertEqual(le" + "n(rows), 2, 'more than 0 > rows')",
                'assert status == "' + CLOCK + ' was replaced"',
                "self.assertIn('Date." + "now() < x', out)",
                'tmp = tempfile.mkdtemp(dir="' + TMP + '")',
                "root = tempfile.mkdtemp(dir='/' + 'tmp')",
                'work=$(mktemp -d ' + TMP + 'run.XXXXXX)',
                'x = 1  # asse' + 'rt le' + 'n(rows) > 0',
                "self.assertEqual(le" + "n(rows), 2)  # " + CLOCK,
                "self.assertTrue(4 <= le" + "n(rows) <= 7)",
                "redact('logs in " + TMP + "synthetic-run')")
        for line in good:
            with self.subTest(line=line):
                self.assert_findings({'check/test_x.py': line + '\n'}, [])
        self.assert_findings({'skills/a/scripts/test.sh': "echo 'asse" + "rt [ $(wc" + " -l) -ge 1 ]'\n"}, [])
        self.assert_findings({'skills/a/scripts/x.test.mjs': '// asse' + 'rt.ok(rows.leng' + 'th > 0)\n'}, [])

    def test_an_unreadable_diff_never_passes(self):
        for args in (('diff', '--base', 'no-such-rev'), ('diff',), ('tree',), ('diff', '--base', 'main', 'x')):
            with self.subTest(args=args):
                code, out, _ = self.run_case({'README.md': 'x\n'}, {'check/test_x.py': 'x = 1\n'}, *args)
                self.assertEqual(code, 2, out)
                self.assertNotIn('checklist: pass', out)


class Checklist(unittest.TestCase):
    def problems(self, text):
        lines = [line for line in text.splitlines() if line.startswith('- ')]
        bad = [line[:40] for line in lines
               if len(re.findall(r'\((?:judgment|mechanical)\b', line)) != 1 or not TAG.match(line)]
        named = {}
        for tag in filter(None, map(TAG.match, lines)):
            if tag[3]:
                named.setdefault(tag[3], []).append(tag[1])
        return bad, named

    def test_every_line_has_exactly_one_tag_and_each_check_its_line(self):
        self.assertEqual(self.problems(CHECKLIST.read_text(encoding='utf-8')),
                         ([], {rule: [title] for rule, title in rules.RULES.items()}))

    def test_a_new_tagged_line_passes_and_an_untagged_one_fails(self):
        text = CHECKLIST.read_text(encoding='utf-8')
        checks = {rule: [title] for rule, title in rules.RULES.items()}
        for line, bad in (('- **A new lesson.** (judgment) Do the thing. (#1 R1)', []),
                          ('- **A new lesson.** Do the thing. (#1 R1)', ['- **A new lesson.** Do the thing. (#1 R1'])):
            with self.subTest(line=line):
                self.assertEqual(self.problems(text + '\n' + line + '\n'), (bad, checks))

if __name__ == '__main__':
    unittest.main()
