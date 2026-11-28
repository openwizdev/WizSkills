import os
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


class QuotaRetirementTest(unittest.TestCase):
    def retire(self, error, state, *flags):
        with tempfile.TemporaryDirectory() as tmp:
            room = Path(tmp) / 'room-cli'
            calls = Path(tmp) / 'calls'
            room.write_text(
                '#!/bin/sh\n'
                'printf "%s\\n" "$*" >> "$CALLS"\n'
                '[ "$ARCHIVE_STATE" != refused ] || exit 1\n'
                'if [ "$ARCHIVE_STATE" = local ]; then\n'
                '  printf \'{"ok":true,"threadId":"thr_syn70","archivedThreadIds":["thr_syn70"]}\\n\'\n'
                '  exit 0\n'
                'fi\n'
                'printf \'{"id":"thr_syn70","state":"%s"}\\n\' "$ARCHIVE_STATE"\n',
                encoding='utf-8',
            )
            room.chmod(0o700)
            result = subprocess.run(
                [sys.executable, '-I', str(SCRIPT), 'retire', 'thr_syn70', *flags],
                input=error, text=True, capture_output=True,
                env={**os.environ, 'PATH': f'{tmp}:{os.environ["PATH"]}', 'CALLS': str(calls),
                     'ARCHIVE_STATE': state, 'LAUNCH_FLEET_NOW': str(NOW + 1800)},
                check=False,
            )
            return result, calls.read_text(encoding='utf-8').splitlines() if calls.exists() else []

    def test_quota_record_requires_confirmed_archive(self):
        for state in ('refused', 'queued', 'archived', 'local'):
            with self.subTest(state=state):
                result, calls = self.retire('Individual quota reached.', state)
                self.assertEqual(calls, ['thread archive thr_syn70 --json'])
                if state in ('archived', 'local'):
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stdout.strip(), 'launch-fleet: start not tried: quota')
                else:
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, '')
                self.assertNotIn('thr_syn70', result.stdout + result.stderr)

    def test_relative_reset_uses_the_error_time_or_is_omitted(self):
        error = 'Individual quota reached. Try again in 45m.'
        result, _ = self.retire(error, 'archived', '--now', str(NOW))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.strip(), 'launch-fleet: start not tried: quota, resets 2026-11-24T20:45:00Z')
        result, _ = self.retire(error, 'archived')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.strip(), 'launch-fleet: start not tried: quota')

    def test_non_quota_failure_is_not_archived(self):
        result, calls = self.retire('Disk quota exceeded', 'archived')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
