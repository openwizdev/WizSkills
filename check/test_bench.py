import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = HERE / 'bench.py'
SAVED = HERE / 'fixtures' / 'bench'
ALPHA = 'suite alpha: python3 -I skills/alpha/test_alpha.py'
BETA = 'suite beta: sh skills/beta/test.sh'

FAKE_GH = r'''#!/usr/bin/env python3
import json, sys
from pathlib import Path
saved, calls = Path(sys.argv[0]).resolve().parent / 'saved', Path(sys.argv[0]).resolve().parent / 'calls.jsonl'
with calls.open('a') as f:
    f.write(json.dumps(sys.argv[1:]) + '\n')
path = sys.argv[-1]
if '/workflows/' in path:
    runs = [json.loads(p.read_text()) for p in sorted(saved.glob('*/run.json'))] if 'page=1&' in path + '&' else []
    print(json.dumps({'total_count': len(runs), 'workflow_runs': runs}))
elif path.endswith('/jobs?per_page=100'):
    print((saved / path.split('/')[-2] / 'jobs.json').read_text())
elif path.endswith('/logs'):
    job = path.split('/')[-2]
    sys.stdout.write(next(saved.glob(f'*/{job}.log')).read_text())
else:
    sys.exit('fake gh: unexpected ' + path)
'''


def bench(*args, env=None):
    done = subprocess.run([sys.executable, '-I', str(BENCH), *args], capture_output=True, text=True, env=env)
    return done.returncode, done.stdout, done.stderr


def table(text):
    """The bench's Markdown table as {phase: [median, known, per-run...]}."""
    rows = [line.strip('|').split('|') for line in text.splitlines() if line.startswith('| ')]
    header = [cell.strip() for cell in rows[0]]
    return header, {cells[0].strip(): [c.strip() for c in cells[1:]] for cells in rows[1:]}


class SavedLogs(unittest.TestCase):
    def test_prints_each_step_and_suite_per_run_and_the_window_median(self):
        code, out, err = bench('--saved', str(SAVED), '--window', 'synthetic 2026-01-05')
        self.assertEqual(code, 0, err)
        self.assertIn('Window: synthetic 2026-01-05', out)
        header, rows = table(out)
        self.assertEqual(header, ['Phase', 'Median (s)', 'Known', '101', '102', '103'])
        self.assertEqual(rows, {
            'queue wait': ['4.0', '3/3', '4.0', '6.0', '2.0'],
            'setup': ['6.0', '3/3', '5.0', '6.0', '7.0'],
            'changeset gate': ['1.0', '3/3', '1.0', '1.0', '2.0'],
            'comment check': ['4.0', '3/3', '4.0', '3.0', '5.0'],
            'browser tools': ['24.0', '3/3', '20.0', '24.0', '30.0'],
            'rules': ['1.0', '3/3', '0.5', '1.5', '1.0'],
            'standalone': ['2.5', '3/3', '2.0', '3.0', '2.5'],
            ALPHA: ['70.0', '2/3', '60.0', 'unknown', '80.0'],
            BETA: ['35.0', '2/3', '30.0', 'unknown', '40.0'],
            'total': ['180.0', '3/3', '180.0', '200.0', '180.0'],
        })

    def test_a_suite_without_its_end_line_is_unknown_never_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(SAVED / '102', Path(tmp) / '102')
            code, out, err = bench('--saved', tmp, '--window', 'one cancelled run')
        self.assertEqual(code, 0, err)
        _, rows = table(out)
        self.assertEqual(rows[ALPHA], ['unknown', '0/1', 'unknown'])
        self.assertNotIn(BETA, rows)
        self.assertEqual(rows['rules'], ['1.5', '1/1', '1.5'])


class LiveWindow(unittest.TestCase):
    def test_reads_the_window_through_gh_get_only_and_keeps_successful_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp)
            shutil.copytree(SAVED, bin_dir / 'saved')
            (bin_dir / 'gh').write_text(FAKE_GH.replace('#!/usr/bin/env python3', '#!' + sys.executable, 1))
            (bin_dir / 'gh').chmod(0o755)
            env = {**os.environ, 'PATH': f'{bin_dir}{os.pathsep}{os.environ.get("PATH", "")}'}
            code, out, err = bench('--from', '2026-01-05', '--to', '2026-01-05', env=env)
            calls = [json.loads(line) for line in (bin_dir / 'calls.jsonl').read_text().splitlines()]
        self.assertEqual(code, 0, err)
        self.assertIn('Window: pull_request runs of openwizdev/WizSkills check created 2026-01-05..2026-01-05', out)
        header, rows = table(out)
        self.assertEqual(header, ['Phase', 'Median (s)', 'Known', '101'])
        self.assertEqual(rows[ALPHA], ['60.0', '1/1', '60.0'])
        for call in calls:
            self.assertEqual(call[0], 'api')
            self.assertFalse({'-X', '--method', '-f', '-F', '--field', '--raw-field', '--input'} & set(call), call)
        self.assertIn('repos/openwizdev/WizSkills/actions/workflows/ci.yml/runs?event=pull_request'
                      '&status=completed&created=2026-01-05..2026-01-05&per_page=100&page=1', calls[0])
        self.assertEqual([c[-1] for c in calls[2:]], ['repos/openwizdev/WizSkills/actions/runs/101/jobs?per_page=100',
                                                      'repos/openwizdev/WizSkills/actions/jobs/1010/logs'])

    def test_needs_a_window(self):
        code, _, err = bench()
        self.assertEqual(code, 2)
        self.assertIn('usage', err)


if __name__ == '__main__':
    unittest.main()
