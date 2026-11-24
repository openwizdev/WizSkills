import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import context_budget  # noqa: E402 -- it follows the sys.path line that finds it

ROOT = HERE.parent
SCRIPT = HERE / 'context_budget.py'


def tree(skills):
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    for name, text in skills.items():
        folder = root / 'skills' / name
        folder.mkdir(parents=True)
        (folder / 'SKILL.md').write_bytes(text.encode('utf-8'))
    (root / 'check').mkdir()
    return tmp, root


def compare(base, head, *flags):
    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for name, sizes in (('base.json', base), ('head.json', head)):
            path = Path(tmp) / name
            path.write_text(json.dumps(sizes), encoding='utf-8')
            paths.append(str(path))
        return subprocess.run([sys.executable, '-I', str(SCRIPT), 'compare', *paths, *flags],
                              capture_output=True, text=True)


class BudgetFile(unittest.TestCase):
    def test_budget_file_equals_every_measured_skill_md(self):
        budget = ROOT / 'check' / 'context-budget.json'
        self.assertTrue(budget.is_file(), context_budget.HELP)
        recorded = json.loads(budget.read_text(encoding='utf-8'))
        self.assertEqual(recorded, context_budget.measure(ROOT), context_budget.HELP)
        self.assertEqual(budget.read_text(encoding='utf-8'), context_budget.render(recorded))

    def test_measure_counts_utf8_bytes_not_characters(self):
        tmp, root = tree({'alpha': 'é\n', 'beta': 'plain\n'})
        with tmp:
            self.assertEqual(context_budget.measure(root), {'alpha': 3, 'beta': 6})

    def test_editing_a_skill_without_writing_the_budget_is_caught(self):
        tmp, root = tree({'alpha': 'one\n'})
        with tmp:
            context_budget.write(root)
            budget = root / context_budget.BUDGET
            self.assertEqual(context_budget.load(budget), context_budget.measure(root))
            (root / 'skills' / 'alpha' / 'SKILL.md').write_text('one more line\n', encoding='utf-8')
            self.assertNotEqual(context_budget.load(budget), context_budget.measure(root))
            context_budget.write(root)
            self.assertEqual(context_budget.load(budget), {'alpha': 14})


class Ratchet(unittest.TestCase):
    def test_growth_fails_naming_the_skill_and_both_sizes(self):
        result = compare({'alpha': 100, 'beta': 50}, {'alpha': 120, 'beta': 50})
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('alpha: 100 -> 120 bytes (+20)', result.stdout)
        self.assertNotIn('beta', result.stdout)
        self.assertIn('context-increase', result.stdout)

    def test_new_skill_counts_as_growth_from_zero(self):
        result = compare({'alpha': 100}, {'alpha': 100, 'gamma': 40})
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('gamma: 0 -> 40 bytes (+40)', result.stdout)

    def test_label_accepts_growth(self):
        result = compare({'alpha': 100}, {'alpha': 120}, '--allow-increase')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('alpha: 100 -> 120 bytes (+20)', result.stdout)
        self.assertIn('accepted', result.stdout)

    def test_shrink_and_removal_pass(self):
        result = compare({'alpha': 100, 'beta': 50}, {'alpha': 80})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unreadable_budget_is_an_input_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / 'bad.json'
            bad.write_text('[1, 2]', encoding='utf-8')
            result = subprocess.run([sys.executable, '-I', str(SCRIPT), 'compare', str(bad), str(bad)],
                                    capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    def test_help_says_how_to_update_and_when_to_ask_for_the_label(self):
        result = subprocess.run([sys.executable, '-I', str(SCRIPT), '--help'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn('python3 -I check/run.py --write-context-budget', result.stdout)
        self.assertIn('context-increase', result.stdout)


if __name__ == '__main__':
    unittest.main()
