import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github' / 'workflows' / 'ci.yml'
JOB = 'check'
STEP_NAME = 'Comment check'
SYNTHETIC = ['-c', 'user.name=synthetic', '-c', 'user.email=synthetic@example.com']
OLD = '# an old note nobody added in this pull request\nx = 1\n'


def job_steps(text, job):
    lines = text.split('\n')
    start = lines.index(f'  {job}:')
    end = next((i for i in range(start + 1, len(lines)) if re.match(r'^ {0,2}\S', lines[i])), len(lines))
    steps, current = [], None
    for line in lines[start + 1:end]:
        if line.startswith('      - '):
            current = [line]
            steps.append(current)
        elif current is not None and (line.startswith('        ') or not line.strip()):
            current.append(line)
        else:
            current = None
    return steps


def step_fields(step):
    fields, block = {}, None
    for line in step:
        if block is not None and (line.startswith('          ') or not line.strip()):
            block.append(line[10:])
            continue
        block = None
        m = re.match(r'^ {6}(?:- | {2})([A-Za-z-]+):\s*(.*)$', line)
        if m:
            key, value = m.groups()
            if value in ('|', '>'):
                block = []
                fields[key] = block
            else:
                fields[key] = value
    return {k: '\n'.join(v).strip() if isinstance(v, list) else v for k, v in fields.items()}


def the_step():
    steps = [step_fields(s) for s in job_steps(WORKFLOW.read_text(), JOB)]
    found = [s for s in steps if s.get('name') == STEP_NAME]
    if len(found) != 1:
        raise AssertionError(f'{JOB} job has {len(found)} steps named {STEP_NAME!r}, want exactly 1')
    return found[0]


def git(cwd, *args):
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class CommentCheckStep(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo)
        (self.repo / 'tools' / 'comment-check').mkdir(parents=True)
        shutil.copy(ROOT / 'tools' / 'comment-check' / 'check.py', self.repo / 'tools' / 'comment-check' / 'check.py')
        (self.repo / 'skills').mkdir()
        (self.repo / 'skills' / 'area.py').write_text(OLD)
        git(self.repo, 'init', '-q', '-b', 'main')
        git(self.repo, 'add', '-A')
        git(self.repo, *SYNTHETIC, 'commit', '-qm', 'base')

    def pull_request(self, added):
        (self.repo / 'skills' / 'area.py').write_text(OLD + added)
        git(self.repo, *SYNTHETIC, 'commit', '-qam', 'head')
        step = the_step()
        self.assertEqual(step.get('if'), "github.event_name == 'pull_request'")
        checks = [line for line in step['run'].split('\n') if 'check.py diff' in line]
        self.assertEqual(len(checks), 1, step['run'])
        return subprocess.run(['bash', '-euo', 'pipefail', '-c', checks[0]], cwd=self.repo,
                              env=dict(os.environ), capture_output=True, text=True)

    def test_a_pull_request_adding_a_disallowed_comment_fails(self):
        result = self.pull_request('y = 2  # we had to do this because the old way broke\n')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip().split('\n'), [
            'skills/area.py:3: comment: a comment outside the allowed kinds: delete it, or turn what it meant into a name, a test or a check'])

    def test_a_reasoned_escape_tag_passes(self):
        result = self.pull_request('# comment-ok: the synthetic runner reads this line as its job name\ny = 2\n')
        self.assertEqual((result.returncode, result.stdout), (0, ''), result.stderr)

    def test_an_escape_tag_without_a_reason_fails(self):
        result = self.pull_request('# comment-ok:\ny = 2\n')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('skills/area.py:3: escape-tag-reason:', result.stdout)

    def test_an_old_comment_never_fails_a_pull_request(self):
        result = self.pull_request('y = 2\n')
        self.assertEqual((result.returncode, result.stdout), (0, ''), result.stderr)

    def test_the_step_runs_these_proofs_before_the_check(self):
        lines = the_step()['run'].split('\n')
        self.assertEqual(lines[:2], ['python3 -I tools/comment-check/test_ci.py', 'python3 -I tools/comment-check/test_commands.py'])


if __name__ == '__main__':
    unittest.main()
