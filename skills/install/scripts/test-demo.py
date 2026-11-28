#!/usr/bin/env python3
import json
from pathlib import Path
import runpy
import shlex
import subprocess
import sys
import unittest

INSTALL = Path(__file__).resolve().parents[1]
FIXTURE = runpy.run_path(str(INSTALL / 'tests/test_first_fleet.py'))
Journey, REPO, github = (FIXTURE[key] for key in ('Journey', 'REPO', 'github'))


class Demo(unittest.TestCase):
    def demo(self, journey, *flags):
        return subprocess.run(
            [sys.executable, '-I', '-B', str(INSTALL / 'scripts/demo.py'),
             '--state', str(journey.state), '--repo', REPO, *flags],
            cwd=journey.dir, env=journey.env(), capture_output=True, text=True, timeout=60)

    def world(self, journey):
        return json.loads(journey.repos.read_text())

    def preview(self, journey):
        preview = self.demo(journey)
        self.assertEqual(preview.returncode, 12, preview.stdout + preview.stderr)
        self.assertIn('app.py', preview.stdout)
        self.assertIn('tests/test_check.py', preview.stdout)
        self.assertIn('.github/workflows/check.yml', preview.stdout)
        self.assertEqual(self.world(journey)['repos'], {})
        self.assertEqual(journey.gh_creates(), [])
        self.assertFalse(journey.state.exists())
        return preview.stdout.split('Confirmation: ')[1].splitlines()[0]

    def test_preview_to_passing_check(self):
        journey = Journey(self)
        confirmation = self.preview(journey)
        for flags in (('--yes',), ('--yes', '--confirm', '0' * 64),
                      ('--confirm', confirmation)):
            with self.subTest(flags=flags):
                result = self.demo(journey, *flags)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.world(journey)['repos'], {})
        journey.state.write_text(json.dumps({'host': {'agents': 'local', 'harnesses': ['claude-code', 'codex']}}))
        options = FIXTURE['offering'](FIXTURE['OPUS'], FIXTURE['SOL'])
        journey.options.write_text(json.dumps(dict(options, source='local')))
        journey.state.chmod(0o600)
        approved = ('--yes', '--confirm', confirmation)
        result = self.demo(journey, *approved)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        main = self.world(journey)['repos'][REPO.lower()]['branches']['main']
        self.assertEqual(set(main), {'README.md', 'app.py', 'tests/test_check.py', '.github/workflows/check.yml'})
        self.assertTrue(self.world(journey)['repos'][REPO.lower()]['private'])
        self.assertIn('Run first_fleet.py select', result.stdout)
        selected = journey.helper(['select', '--repo', REPO])
        self.assertEqual(selected.returncode, 0, selected.stdout + selected.stderr)
        self.assertEqual(json.loads(journey.state.read_text())['repo'], REPO)
        journey.world['files'] = main
        journey.save_world()
        defaults = journey.helper(['defaults', '--options', str(journey.options)])
        self.assertEqual(defaults.returncode, 12, defaults.stdout + defaults.stderr)
        self.assertIn('Recommended setup', defaults.stdout)
        project = journey.dir / 'demo'
        for name, source in main.items():
            path = project / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
        app = subprocess.run([sys.executable, 'app.py'], cwd=project, capture_output=True, text=True, timeout=30)
        self.assertEqual((app.returncode, app.stdout), (0, 'Hello, OpenWiz!\n'), app.stderr)
        workflow = main['.github/workflows/check.yml']
        self.assertRegex(workflow, r'\njobs:\n  check:\n')
        (command,) = [line.split('- run: ', 1)[1] for line in workflow.splitlines() if '- run: ' in line]
        argv = shlex.split(command)
        self.assertEqual(argv, ['python3', '-m', 'unittest', 'discover', '-s', 'tests'])
        ran = subprocess.run(argv, cwd=project, env=journey.env(), capture_output=True, text=True, timeout=30)
        self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
        self.assertIn('Ran 1 test', ran.stderr)
        (project / 'app.py').write_text(main['app.py'].replace('Hello,', 'Goodbye,'))
        broken = subprocess.run(argv, cwd=project, env=journey.env(), capture_output=True, text=True, timeout=30)
        self.assertEqual(broken.returncode, 1, broken.stdout + broken.stderr)
        self.assertIn('AssertionError', broken.stderr)

    def test_retry_after_a_failed_read_keeps_owner_data(self):
        journey = Journey(self)
        confirmation = self.preview(journey)
        fault = {'method': 'GET', 'path': f'repos/{REPO}/git/ref/heads/main', 'mode': 500, 'times': 1}
        journey.repos.write_text(github(faults=[fault]))
        flags = ('--yes', '--confirm', confirmation)
        first = self.demo(journey, *flags)
        self.assertEqual(first.returncode, 6, first.stdout + first.stderr)
        world = self.world(journey)
        main = world['repos'][REPO.lower()]['branches']['main']
        self.assertEqual(set(main), {'README.md'})
        main['notes.txt'] = 'Existing owner work.\n'
        journey.repos.write_text(json.dumps(world))
        for _ in range(2):
            finished = self.demo(journey, *flags)
            self.assertEqual(finished.returncode, 0, finished.stdout + finished.stderr)
        final = self.world(journey)
        self.assertEqual(final['repos'][REPO.lower()]['branches']['main']['notes.txt'], 'Existing owner work.\n')
        writes = [entry for entry in final['log'] if entry[0] != 'GET']
        self.assertEqual(writes, [['POST', 'user/repos'], *[
            ['POST', f'graphql createCommitOnBranch {REPO} {path}']
            for path in ('tests/test_check.py', 'app.py', '.github/workflows/check.yml')
        ]])

    def test_own_repository_uses_existing_select(self):
        steps = (INSTALL / 'SKILL.md').read_text().split('### 2. Choose a start\n', 1)[1].split('\n### 3.', 1)[0]
        self.assertLess(steps.index('**Demo repository**'), steps.index('**A repository they have:**'))
        self.assertIn('first_fleet.py select --repo <owner>/<name>', steps)
        journey = Journey(self)
        confirmation = self.preview(journey)
        files = {'README.md': 'Existing owner work.\n'}
        existing = FIXTURE['demo_repository'](branches={'main': files})
        journey.repos.write_text(github([existing]))
        refused = self.demo(journey, '--yes', '--confirm', confirmation)
        self.assertEqual(refused.returncode, 5, refused.stdout + refused.stderr)
        before = self.world(journey)
        self.assertEqual(before['repos'][REPO.lower()]['branches']['main'], files)
        self.assertTrue(all(entry[0] == 'GET' for entry in before['log']))
        selected = journey.helper(['select', '--repo', REPO])
        self.assertEqual(selected.returncode, 0, selected.stdout)
        self.assertEqual(json.loads(journey.state.read_text())['repo'], REPO)
        self.assertEqual(self.world(journey), before)


if __name__ == '__main__':
    unittest.main()
