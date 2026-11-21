import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

HELP = [
    ('check/standalone.py', 'WizSkills standalone check (openwiz.wizskills.v1, WZ2 #2630).'),
    ('skills/image/scripts/contrast.py', 'WCAG 2 contrast of two sRGB colours'),
    ('skills/grill/scripts/records.py', 'Read a saved grill proposal and maintain its private decision request.'),
    ('skills/feedback/scripts/feedback.py', 'One consented feedback operation, under contracts/feedback.v1.md (#2292).'),
    ('skills/hill-climb/scripts/climb.py', 'Offline pair plans, Bradley-Terry fits'),
    ('skills/image/scripts/screenshot.py', "Capture phone + desktop evidence through Cloudroom's browser-harness."),
    ('skills/launch-fleet/scripts/self-grant.py', "Grant and record one of the fleet's four bounded self-grants (#1353, F4)."),
    ('skills/launch-fleet/scripts/github-app/mint-token.py', 'Mint one read-only installation token on the PC'),
    ('skills/launch-fleet/scripts/carried/alarm.py', 'One bounded CS5 observation/admission decision.'),
    ('skills/launch-fleet/scripts/carried/limits.py', 'Read factory stage goals; settings alone authorize no action.'),
    ('skills/launch-fleet/scripts/fixtures/test-o10-triage.py', 'O5/O10 consumer seam'),
    ('skills/launch-fleet/scripts/fixtures/reproduce-1273-ci.py', "Run only #1273's failed CI groups"),
    ('skills/review-ticket/scripts/review.py', 'Review mechanics for review-ticket: pin the head'),
    ('skills/to-tickets/scripts/approve.py', 'The machine plan approval (#1339, J202): check a plan graph and print its record.'),
    ('skills/to-tickets/scripts/request.py', 'Build one decision request from verified public wording and source inputs.'),
    ('skills/to-tickets/scripts/lead_time.py', "Spec lead time for the war room (#1353, F6): from the spec's creation to"),
]

USAGE = [
    ('skills/build-ticket/scripts/ticket.py', ['nonsense'], '  ticket.py read REPO N  '),
    ('skills/handoff/scripts/handoff.py', [], '  handoff.py private <owner/repo>  '),
    ('skills/launch-fleet/scripts/post.py', ['comment', 'synthetic/repo'], '  post.py comment OWNER/NAME NUMBER BODY  '),
]

REAL = [
    ('check/standalone.py', ['--tree', str(ROOT)], 0, ''),
    ('skills/image/scripts/contrast.py', ['#000000', '#ffffff', '--min', '4.5'], 0, '21.00:1 pass (needs 4.5:1)'),
    ('skills/grill/scripts/records.py', ['synthetic/private', '1', '/nonexistent', 'match', 'm', 'o'], 2, 'refused: invalid private target'),
    ('skills/feedback/scripts/feedback.py', ['status', 'op-missing'], 1, 'Not an operation id'),
    ('skills/hill-climb/scripts/climb.py', ['rank', '/nonexistent.json'], 2, 'No such file or directory'),
    ('skills/image/scripts/screenshot.py', ['--out', 'shot', '--ready-selector', 'body', 'notaurl'], 2, 'url must be HTTP(S)'),
    ('skills/launch-fleet/scripts/self-grant.py', ['synthetic/repo', '1', 'not-a-kind', 'reason'], 1, 'refused: not a self-grant kind'),
    ('skills/launch-fleet/scripts/github-app/mint-token.py', ['--installation-id', 'x', '--state-dir', '/nonexistent'], 1, '--repository is required'),
    ('skills/launch-fleet/scripts/carried/limits.py', ['--settings', '/nonexistent'], 1, 'limits: invalid settings'),
    ('skills/review-ticket/scripts/review.py', ['self-check', '/nonexistent'], 2, 'refused: cannot read /nonexistent'),
    ('skills/to-tickets/scripts/approve.py', ['--graph', 'g', '--revision', 'r', '--spec', 's', '--grill', 'x', '--number', '1'], 2, 'approve: usage:'),
    ('skills/to-tickets/scripts/request.py', [], 1, 'request: invalid input or unreadable revision'),
    ('skills/to-tickets/scripts/lead_time.py', ['/nonexistent'], 2, 'lead_time: [Errno 2]'),
    ('skills/build-ticket/scripts/ticket.py', ['read', 'synthetic/repo', '1'], 2, 'cannot read ticket #1'),
    ('skills/handoff/scripts/handoff.py', ['private', 'notarepo'], 2, "'notarepo' is not owner/name"),
    ('skills/launch-fleet/scripts/post.py', ['comment', 'synthetic/repo', '1', 'hello'], 1, 'refused: not a fleet record'),
]


class Commands(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        bin_dir = self.tmp / 'bin'
        bin_dir.mkdir()
        for tool in ('git',):
            found = shutil.which(tool)
            if found:
                (bin_dir / tool).symlink_to(found)
        env = {k: v for k, v in os.environ.items() if k not in ('GH_TOKEN', 'GITHUB_TOKEN')}
        self.env = dict(env, PATH=str(bin_dir), HOME=str(self.tmp), COLUMNS='200')

    def run_script(self, path, args):
        return subprocess.run([sys.executable, str(ROOT / path), *args], cwd=self.tmp, env=self.env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)

    def test_help_prints_each_description(self):
        for path, words in HELP:
            with self.subTest(path=path):
                result = self.run_script(path, ['--help'])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(words, ' '.join(result.stdout.split()))

    def test_usage_prints_each_command_list(self):
        for path, args, words in USAGE:
            with self.subTest(path=path):
                result = self.run_script(path, args)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn(words, result.stderr)

    def test_one_real_command_each(self):
        for path, args, code, words in REAL:
            with self.subTest(path=path):
                result = self.run_script(path, args)
                self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                self.assertIn(words, result.stdout + result.stderr)

    @unittest.skipIf(os.geteuid() == 0, 'root reads a folder whatever its mode')
    def test_standalone_refuses_a_tree_with_an_unreadable_folder(self):
        locked = self.tmp / 'tree' / 'skills' / 'demo' / 'locked'
        locked.mkdir(parents=True)
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o700)
        result = self.run_script('check/standalone.py', ['--tree', str(self.tmp / 'tree')])
        self.assertEqual((result.returncode, result.stdout), (1, ''), result.stderr)
        self.assertEqual(result.stderr, 'standalone: refused; unreadable tree or contract\n')


if __name__ == '__main__':
    unittest.main()
