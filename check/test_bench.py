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
RERUN = SAVED / 'rerun'
READ_ONLY_FLAGS = {'-X', '--method', '-f', '-F', '--field', '--raw-field', '--input'}
ALPHA = 'suite alpha: python3 -I skills/alpha/test_alpha.py'
BETA = 'suite beta: sh skills/beta/test.sh'

FAKE_GH = r'''#!/usr/bin/env python3
import json, sys
from pathlib import Path
saved, calls = Path(sys.argv[0]).resolve().parent / 'saved', Path(sys.argv[0]).resolve().parent / 'calls.jsonl'
with calls.open('a') as f:
    f.write(json.dumps(sys.argv[1:]) + '\n')
path = sys.argv[-1]
attempts = {}
for run_json in saved.rglob('run.json'):
    run = json.loads(run_json.read_text())
    attempts[(str(run['id']), str(run['run_attempt']))] = (run, run_json.parent)
parts = path.split('?')[0].split('/')
if '/workflows/' in path:
    runs = [json.loads(p.read_text()) for p in sorted(saved.glob('*/run.json'))] if 'page=1&' in path + '&' else []
    print(json.dumps({'total_count': len(runs), 'workflow_runs': runs}))
elif parts[-1] == 'logs':
    sys.stdout.write(next(saved.rglob(f'{parts[-2]}.log')).read_text())
elif parts[-1] == 'jobs' and parts[-3] == 'attempts':
    print((attempts[(parts[-4], parts[-2])][1] / 'jobs.json').read_text())
elif parts[-2] == 'attempts':
    print(json.dumps(attempts[(parts[-3], parts[-1])][0]))
elif parts[-2] == 'runs':
    print(json.dumps(max((r for (i, _), (r, _) in attempts.items() if i == parts[-1]), key=lambda r: r['run_attempt'])))
else:
    sys.exit('fake gh: unexpected ' + path)
'''


def bench(*args, env=None):
    done = subprocess.run([sys.executable, '-I', str(BENCH), *args], capture_output=True, text=True, env=env)
    return done.returncode, done.stdout, done.stderr


def table(text):
    rows = [line.strip('|').split('|') for line in text.splitlines() if line.startswith('| ') and not line.startswith('| ---')]
    header = [cell.strip() for cell in rows[0]]
    return header, {cells[0].strip(): [c.strip() for c in cells[1:]] for cells in rows[1:]}


class SavedLogs(unittest.TestCase):
    def test_prints_each_step_and_suite_per_run_and_the_window_median(self):
        code, out, err = bench('--saved', str(SAVED), '--window', 'synthetic 2026-01-05')
        self.assertEqual(code, 0, err)
        self.assertIn('Window: synthetic 2026-01-05', out)
        header, rows = table(out)
        self.assertEqual(header, ['Phase', 'Median (s)', 'Known', '101/1', '102/1', '103/1'])
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

    def test_a_timed_end_line_still_ends_its_suite_timed_from_the_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(SAVED / '103', Path(tmp) / '103')
            log = Path(tmp) / '103' / '1030.log'
            text = log.read_text(encoding='utf-8')
            for end in ('test_alpha.py: fail (1)', 'test.sh: pass'):
                self.assertIn(end + '\n', text)
                text = text.replace(end + '\n', end + ' in 9.9s\n')
            log.write_text(text, encoding='utf-8')
            code, out, err = bench('--saved', tmp, '--window', 'timed end lines')
        self.assertEqual(code, 0, err)
        _, rows = table(out)
        self.assertEqual(rows[ALPHA], ['80.0', '1/1', '80.0'])
        self.assertEqual(rows[BETA], ['40.0', '1/1', '40.0'])

    def test_a_diagnostic_only_rules_log_stays_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / '105'
            root.mkdir()
            (root / 'run.json').write_text(json.dumps({
                'id': 105, 'event': 'pull_request', 'status': 'completed', 'conclusion': 'cancelled',
                'created_at': '2026-01-05T12:00:00Z', 'run_started_at': '2026-01-05T12:00:00Z',
                'run_attempt': 1,
            }), encoding='utf-8')
            (root / 'jobs.json').write_text(json.dumps({'jobs': [{
                'id': 1050, 'run_id': 105, 'name': 'check', 'status': 'completed', 'conclusion': 'cancelled',
                'created_at': '2026-01-05T12:00:00Z', 'started_at': '2026-01-05T12:00:02Z',
                'completed_at': '2026-01-05T12:00:10Z', 'steps': [],
            }]}), encoding='utf-8')
            (root / '1050.log').write_text(
                '2026-01-05T12:00:04.0000000Z ##[group]Run python3 check/run.py\n'
                '2026-01-05T12:00:04.1000000Z rules: frontmatter skills/alpha/SKILL.md:12: synthetic\n'
                '2026-01-05T12:00:04.2000000Z ##[error]The operation was canceled.\n',
                encoding='utf-8')
            code, out, err = bench('--saved', tmp, '--window', 'diagnostic only')
        self.assertEqual(code, 0, err)
        _, rows = table(out)
        self.assertEqual(rows['rules'], ['unknown', '0/1', 'unknown'])


def with_fake_gh(*args):
    with tempfile.TemporaryDirectory() as tmp:
        bin_dir = Path(tmp)
        shutil.copytree(SAVED, bin_dir / 'saved')
        (bin_dir / 'gh').write_text(FAKE_GH.replace('#!/usr/bin/env python3', '#!' + sys.executable, 1))
        (bin_dir / 'gh').chmod(0o755)
        env = {**os.environ, 'PATH': f'{bin_dir}{os.pathsep}{os.environ.get("PATH", "")}'}
        code, out, err = bench(*args, env=env)
        calls = [json.loads(line) for line in (bin_dir / 'calls.jsonl').read_text().splitlines()]
    return code, out, err, calls


class Reruns(unittest.TestCase):
    def test_each_attempt_is_timed_from_its_own_start(self):
        code, out, err = bench('--saved', str(RERUN), '--window', 'one run, two attempts')
        self.assertEqual(code, 0, err)
        header, rows = table(out)
        self.assertEqual(rows['total'], ['165.0', '2/2', '180.0', '150.0'])
        self.assertEqual(header, ['Phase', 'Median (s)', 'Known', '104/1', '104/2'])
        self.assertEqual(rows['queue wait'], ['4.0', '2/2', '5.0', '3.0'])
        self.assertEqual(rows[ALPHA], ['55.0', '2/2', '60.0', '50.0'])


class LiveWindow(unittest.TestCase):
    def test_reads_the_window_through_gh_get_only_and_keeps_successful_runs(self):
        code, out, err, calls = with_fake_gh('--from', '2026-01-05', '--to', '2026-01-05')
        self.assertEqual(code, 0, err)
        self.assertIn('Window: pull_request runs of openwizdev/WizSkills check created 2026-01-05..2026-01-05', out)
        header, rows = table(out)
        self.assertEqual(header, ['Phase', 'Median (s)', 'Known', '101/1'])
        self.assertEqual(rows[ALPHA], ['60.0', '1/1', '60.0'])
        for call in calls:
            self.assertEqual(call[0], 'api')
            self.assertFalse(READ_ONLY_FLAGS & set(call), call)
        self.assertIn('repos/openwizdev/WizSkills/actions/workflows/ci.yml/runs?event=pull_request'
                      '&status=completed&created=2026-01-05..2026-01-05&per_page=100&page=1', calls[0])
        self.assertEqual([c[-1] for c in calls[2:]], ['repos/openwizdev/WizSkills/actions/runs/101/attempts/1/jobs?per_page=100',
                                                      'repos/openwizdev/WizSkills/actions/jobs/1010/logs'])

    def test_a_pinned_attempt_replays_that_attempt_not_the_latest(self):
        code, out, err, calls = with_fake_gh('--runs', '104/1')
        self.assertEqual(code, 0, err)
        header, rows = table(out)
        self.assertEqual(header, ['Phase', 'Median (s)', 'Known', '104/1'])
        self.assertEqual(rows['queue wait'], ['5.0', '1/1', '5.0'])
        self.assertEqual(rows['total'], ['180.0', '1/1', '180.0'])
        self.assertEqual(rows[ALPHA], ['60.0', '1/1', '60.0'])
        self.assertEqual([c[-1] for c in calls], ['repos/openwizdev/WizSkills/actions/runs/104/attempts/1',
                                                  'repos/openwizdev/WizSkills/actions/runs/104/attempts/1/jobs?per_page=100',
                                                  'repos/openwizdev/WizSkills/actions/jobs/1041/logs'])
        for call in calls:
            self.assertFalse(READ_ONLY_FLAGS & set(call), call)

    def test_a_bare_run_id_is_pinned_to_its_latest_attempt_in_the_column(self):
        code, out, err, calls = with_fake_gh('--runs', '104')
        self.assertEqual(code, 0, err)
        header, rows = table(out)
        self.assertEqual(header, ['Phase', 'Median (s)', 'Known', '104/2'])
        self.assertEqual(rows['total'], ['150.0', '1/1', '150.0'])
        self.assertEqual(calls[1][-1], 'repos/openwizdev/WizSkills/actions/runs/104/attempts/2/jobs?per_page=100')

    def test_needs_a_window(self):
        code, _, err = bench()
        self.assertEqual(code, 2)
        self.assertIn('usage', err)


if __name__ == '__main__':
    unittest.main()
