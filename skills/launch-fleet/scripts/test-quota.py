import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / 'quota.py'
NOW = 1795464000


def run_cli(text, extra=()):
    return subprocess.run(
        [sys.executable, '-I', str(SCRIPT), 'check', '--now', str(NOW), *extra],
        input=text,
        text=True,
        capture_output=True,
        check=False,
    )


class QuotaCheckTest(unittest.TestCase):
    def test_individual_quota_reached_without_reset(self):
        r = run_cli('Error: Individual quota reached\n')
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.strip(), 'launch-fleet: start not tried: quota')
        self.assertEqual(r.stderr, '')

    def test_individual_quota_reached_with_utc_reset(self):
        r = run_cli('Individual quota reached. Resets at 2026-11-24T22:00:00Z.\n')
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.strip(), 'launch-fleet: start not tried: quota, resets 2026-11-24T22:00:00Z')

    def test_iso_offset_normalized_to_utc(self):
        r = run_cli('Individual quota reached; resets 2026-11-24T17:00:00-05:00\n')
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.strip(), 'launch-fleet: start not tried: quota, resets 2026-11-24T22:00:00Z')

    def test_relative_reset_duration(self):
        r = run_cli('Individual quota reached. Resets in 1h 30m.\n')
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.strip(), 'launch-fleet: start not tried: quota, resets 2026-11-24T21:30:00Z')

    def test_claude_usage_limit_with_reset(self):
        r = run_cli("You've hit your limit · resets 2026-11-24T23:15:00Z\n")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.strip(), 'launch-fleet: start not tried: quota, resets 2026-11-24T23:15:00Z')

    def test_quota_exceeded_relative_minutes(self):
        r = run_cli('Quota exceeded. Try again in 45m.\n')
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.strip(), 'launch-fleet: start not tried: quota, resets 2026-11-24T20:45:00Z')

    def test_malformed_reset_omits_reset_time(self):
        r = run_cli('Individual quota reached. Resets at 2026-99-99T99:99:99Z\n')
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.strip(), 'launch-fleet: start not tried: quota')

    def test_normal_output_passes(self):
        r = run_cli('Running cargo test --workspace\nall 42 tests passed\n')
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), 'ok')
        self.assertEqual(r.stderr, '')

    def test_empty_output_passes(self):
        r = run_cli('')
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), 'ok')

    def test_private_identifiers_never_echoed(self):
        r = run_cli('thread thr_secret12345 hit Individual quota reached with token ghp_secret999\n')
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.strip(), 'launch-fleet: start not tried: quota')
        self.assertNotIn('thr_secret', r.stdout + r.stderr)
        self.assertNotIn('ghp_secret', r.stdout + r.stderr)


if __name__ == '__main__':
    unittest.main()
