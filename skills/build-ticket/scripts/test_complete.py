#!/usr/bin/env python3
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / 'complete.py'
FIXTURES = HERE / 'fixtures' / 'complete'
SKILL = HERE.parent / 'SKILL.md'
SUM = 'criterion without evidence: The adder returns the sum of two numbers'
EMPTY = 'criterion without evidence: An empty input prints `usage` and exits 2'
KEPT = 'criterion without evidence: The existing tests still pass'
RED = 'no red-first evidence'
NOTE = 'no changelog line'
PROVE = ('- `prove.py --base origin/main --test test_adder.py -- python3 -I test_adder.py` printed '
         '`{"base": "aaaa", "head": "bbbb", "base_runs": [%s], "head_runs": ["passed", "passed"]}`')


def check(ticket, description, paths):
    return subprocess.run(
        [sys.executable, '-I', str(SCRIPT), '--ticket', str(ticket), '--description', str(description),
         '--diff', str(paths)], capture_output=True, text=True)


def case(name):
    return check(FIXTURES / 'ticket.md', FIXTURES / name / 'description.md', FIXTURES / name / 'paths.txt')


class Fixtures(unittest.TestCase):
    def expect(self, name, code, lines):
        done = case(name)
        self.assertEqual((done.returncode, done.stdout.splitlines()), (code, lines), done.stderr)

    def test_a_complete_hand_back_is_ok(self):
        self.expect('complete', 0, ['complete: ok'])

    def test_a_no_changelog_mention_stands_in_for_the_note(self):
        self.expect('no-changelog-mention', 0, ['complete: ok'])

    def test_a_heading_inside_a_code_fence_does_not_end_the_evidence(self):
        self.expect('fenced-heading', 0, ['complete: ok'])

    def test_a_criterion_no_line_names_is_a_gap(self):
        self.expect('criterion-gap', 1, [KEPT])

    def test_evidence_without_a_failing_first_run_is_a_gap(self):
        done = case('no-red')
        self.assertEqual((done.returncode, done.stdout.splitlines()), (1, [RED]))
        self.assertEqual(done.stderr.splitlines(), ["proof: S1 of spec #100: the adder's tests, red then green."])

    def test_look_alike_paths_are_not_the_changelog_note(self):
        self.expect('no-changelog', 1, [NOTE])

    def test_another_tickets_note_is_not_the_changelog_note(self):
        self.expect('wrong-ticket-note', 1, [NOTE])

    def test_every_gap_prints_its_own_line(self):
        self.expect('every-gap', 1, [SUM, EMPTY, KEPT, RED, NOTE])


class Written(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='complete-test-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.paths = self.tmp / 'paths.txt'
        self.paths.write_text('changes/101.md\n', encoding='utf-8')

    def run_with(self, evidence, ticket=None, head='Closes #101'):
        description = self.tmp / 'description.md'
        description.write_text(f'{head}\n\n## Evidence\n\n{evidence}\n', encoding='utf-8')
        if ticket is None:
            ticket = FIXTURES / 'ticket.md'
        else:
            (self.tmp / 'ticket.md').write_text(ticket, encoding='utf-8')
            ticket = self.tmp / 'ticket.md'
        done = check(ticket, description, self.paths)
        return done.returncode, done.stdout.splitlines()

    def test_a_prove_line_with_a_failed_base_is_red_first(self):
        named = '\n- criteria 1 to 3 pass'
        self.assertEqual(self.run_with(PROVE % '"failed", "failed"' + named), (0, ['complete: ok']))
        self.assertEqual(self.run_with(PROVE % '"passed", "failed"' + named), (1, [RED]))

    def test_a_number_names_only_its_own_criterion(self):
        before = 'Before: `test_adder.py` printed FAILED (failures=13)\n'
        table = {
            'criterion 1, 2 and 3: ok': [],
            'AC1 ok\nAC 2 ok\nac #3 ok': [],
            'Criteria 1-3: ok': [],
            'criterion 1: ok\ncriterion 2: ok': [KEPT],
            'criterion 13: ok\ncriterion 2 and 3: ok': [SUM],
            '1. ok\n2. ok\n3. ok': [SUM, EMPTY, KEPT],
            'criterion 2: ok\nTHE   EXISTING tests still pass: ok': [SUM],
            'the adder returns the sum\ncriterion 2 and 3': [SUM],
        }
        for evidence, gaps in table.items():
            with self.subTest(evidence=evidence):
                self.assertEqual(self.run_with(before + evidence),
                                 (1, gaps) if gaps else (0, ['complete: ok']))

    def test_the_before_run_must_name_a_failure(self):
        named = '\ncriteria 1, 2 and 3: ok'
        table = {
            'Before: `test_adder.py` printed `FAILED (failures=2)`': True,
            '- **Before:** the run was red': True,
            'Before (the test commit):\n\n```\nAssertionError: 3 != 4\n```\n\nAfter: OK': True,
            'Before: n/a': False,
            'Before: nothing to run\n\nAfter: no test failed': False,
            'After: `test_adder.py` printed OK; it never failed before': False,
        }
        for evidence, red in table.items():
            with self.subTest(evidence=evidence):
                self.assertEqual(self.run_with(evidence + named), (0, ['complete: ok']) if red else (1, [RED]))

    def test_inline_after_ends_the_before_run(self):
        named = '\n- Criteria 1-3: error handling verified.'
        table = {
            'Before: n/a. After: no test failed.': (1, [RED]),
            'Before: n/a. After: OK.': (1, [RED]),
            'Before: n/a.\nNo run. After: no test failed.': (1, [RED]),
            '- **Before:** n/a. **After:** no test failed.': (1, [RED]),
            'Before: FAILED (failures=2). After: OK.': (0, ['complete: ok']),
        }
        for evidence, expected in table.items():
            with self.subTest(evidence=evidence):
                self.assertEqual(self.run_with(evidence + named), expected)

    def test_subheadings_open_and_close_the_before_run(self):
        named = '\nCriteria 1, 2 and 3 pass.'
        table = {
            '### Before\nFAILED (failures=2)\n\n### After\nOK.': (0, ['complete: ok']),
            'Before: n/a\n\n### After\nNo test failed.': (1, [RED]),
            '### Before\nn/a\n\n### After\nNo test failed.': (1, [RED]),
        }
        for evidence, expected in table.items():
            with self.subTest(evidence=evidence):
                self.assertEqual(self.run_with(evidence + named), expected)

    def test_dash_separators_do_not_supply_criterion_numbers(self):
        before = 'Before: FAILED (failures=2)\n\nAfter: OK.\n'
        table = {
            '- Criterion 1 - 3 tests passed.': [EMPTY, KEPT],
            '- AC1 - 5 assertions green.': [EMPTY, KEPT],
            '- Criteria 1 -3 tests passed.': [EMPTY, KEPT],
            '## Self-check\n- Criterion 1- 3 tests passed.': [EMPTY, KEPT],
            '- Criteria 1 – 3 tests passed.': [EMPTY, KEPT],
        }
        for evidence, gaps in table.items():
            with self.subTest(evidence=evidence):
                self.assertEqual(self.run_with(before + evidence), (1, gaps))

    def test_tight_dash_and_word_ranges_include_intermediate_criteria(self):
        before = 'Before: FAILED (failures=2)\n\nAfter: OK.\n'
        for evidence in ('Criteria 1-3 pass.', 'Criteria 1–3 pass.', 'CRITERIA 1 TO 3 pass.',
                         '## Self-check\n- Criteria 1–#3 pass.'):
            with self.subTest(evidence=evidence):
                self.assertEqual(self.run_with(before + evidence), (0, ['complete: ok']))

    def test_without_a_closes_line_any_tickets_note_counts(self):
        evidence = 'Before: FAILED\ncriteria 1, 2 and 3: ok'
        self.assertEqual(self.run_with(evidence, head='No closing line'), (0, ['complete: ok']))
        self.paths.write_text('changes/notes.md\n', encoding='utf-8')
        self.assertEqual(self.run_with(evidence, head='No closing line'), (1, [NOTE]))
        self.assertEqual(self.run_with(evidence, head='Closes openwizdev/Synthetic#101'), (1, [NOTE]))
        self.paths.write_text('./changes/101.md\n', encoding='utf-8')
        self.assertEqual(self.run_with(evidence, head='Closes openwizdev/Synthetic#101'), (0, ['complete: ok']))

    def test_an_unreadable_input_exits_2_and_names_no_gap(self):
        evidence = 'Before: FAILED\ncriteria 1, 2 and 3: ok'
        for ticket in ('## Proof\n\nred then green\n', '## Acceptance criteria\n\nnone yet\n\n## Proof\n\nred\n'):
            with self.subTest(ticket=ticket):
                self.assertEqual(self.run_with(evidence, ticket=ticket), (2, []))
        done = check(FIXTURES / 'ticket.md', self.tmp / 'absent.md', self.paths)
        self.assertEqual((done.returncode, done.stdout), (2, ''))
        self.assertIn('complete: unreadable:', done.stderr)
        done = subprocess.run([sys.executable, '-I', str(SCRIPT), '--ticket', str(FIXTURES / 'ticket.md')],
                              capture_output=True, text=True)
        self.assertEqual((done.returncode, done.stdout), (2, ''))


class Skill(unittest.TestCase):
    def test_step_4_runs_the_completion_check_before_the_self_review(self):
        text = SKILL.read_text(encoding='utf-8')
        step = text[text.index('## 4. Check and hand back'):text.index('## 5. Until it merges')]
        lines = [line for line in step.splitlines() if 'scripts/complete.py' in line]
        self.assertEqual(len(lines), 1)
        self.assertIn('complete: ok', lines[0])
        self.assertLess(step.index(lines[0]), step.index('Review yourself first'))


if __name__ == '__main__':
    unittest.main()
