from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / 'quota.py'
NOW = 1795550400


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
        r = run_cli('thread THREADSECRET hit Individual quota reached with token TOKENSECRET\n')
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.strip(), 'launch-fleet: start not tried: quota')
        self.assertNotIn('THREADSECRET', r.stdout + r.stderr)
        self.assertNotIn('TOKENSECRET', r.stdout + r.stderr)

    def test_compact_relative_duration_and_fractional_iso(self):
        r = run_cli('Individual quota reached. Resets in 1h30m.\n')
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.strip(), 'launch-fleet: start not tried: quota, resets 2026-11-24T21:30:00Z')
        r = run_cli('Individual quota reached. Resets at 2026-11-24T22:00:00.000Z.\n')
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.strip(), 'launch-fleet: start not tried: quota, resets 2026-11-24T22:00:00Z')

    def test_missing_file_exits_two_and_overflow_omits_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run_cli('', extra=('--file', str(Path(tmp) / 'missing.txt')))
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, '')
        r = run_cli('Individual quota reached. Resets in 9999999999999999999d.\n')
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.strip(), 'launch-fleet: start not tried: quota')

    def test_builders_probe_archives_errored_thread(self):
        builders = (HERE.parent / 'references/builders.md').read_text(encoding='utf-8')
        self.assertIn('archive that errored thread', builders)
        self.assertNotIn('archive or stop that errored thread', builders)


if __name__ == '__main__':
    unittest.main()
