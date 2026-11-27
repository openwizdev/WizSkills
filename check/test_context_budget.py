import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPT = HERE / 'context_budget.py'


def git(repo, *args):
    subprocess.run(
        ['git', '-c', 'user.name=test', '-c', 'user.email=test@example.com', '-c', 'commit.gpgsign=false', *args],
        cwd=repo, check=True, capture_output=True, text=True,
    )


def commit_files(repo, files, message):
    skills = repo / 'skills'
    if skills.exists():
        for path in sorted(skills.rglob('*'), reverse=True):
            if path.is_file() or path.is_symlink():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
    for rel, content in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, tuple) and content[0] == 'symlink':
            target.symlink_to(content[1])
        else:
            target.write_bytes(content.encode('utf-8'))
    git(repo, 'add', '-A')
    git(repo, 'commit', '--allow-empty', '-m', message)


def repo_with_commits(*commits):
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    git(root, 'init', '-b', 'main')
    for idx, files in enumerate(commits, 1):
        commit_files(root, files, f'commit {idx}')
    return tmp, root


def run_compare(repo, base, head, *flags):
    return subprocess.run(
        [sys.executable, '-I', str(SCRIPT), 'compare', base, head, '--repo', str(repo), *flags],
        capture_output=True, text=True,
    )


class ContextBudget(unittest.TestCase):
    def test_no_checked_in_budget_file_or_write_flag(self):
        self.assertFalse((ROOT / 'check' / 'context-budget.json').exists())
        result = subprocess.run(
            [sys.executable, '-I', str(HERE / 'run.py'), '--write-context-budget'],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    def test_growth_fails_naming_the_skill_and_both_sizes(self):
        tmp, repo = repo_with_commits(
            {'skills/alpha/SKILL.md': 'one\n', 'skills/beta/SKILL.md': 'plain\n'},
            {'skills/alpha/SKILL.md': 'one more line\n', 'skills/beta/SKILL.md': 'plain\n'},
        )
        with tmp:
            result = run_compare(repo, 'HEAD^1', 'HEAD')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('alpha: 4 -> 14 bytes (+10)', result.stdout)
        self.assertNotIn('beta', result.stdout)
        self.assertIn('context-increase', result.stdout)

    def test_counts_utf8_bytes_not_characters(self):
        tmp, repo = repo_with_commits(
            {'skills/alpha/SKILL.md': 'aa\n'},
            {'skills/alpha/SKILL.md': 'éé\n'},
        )
        with tmp:
            result = run_compare(repo, 'HEAD^1', 'HEAD')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('alpha: 3 -> 5 bytes (+2)', result.stdout)

    def test_new_skill_counts_as_growth_from_zero(self):
        tmp, repo = repo_with_commits(
            {'skills/alpha/SKILL.md': 'one\n'},
            {'skills/alpha/SKILL.md': 'one\n', 'skills/gamma/SKILL.md': 'new skill\n'},
        )
        with tmp:
            result = run_compare(repo, 'HEAD^1', 'HEAD')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('gamma: 0 -> 10 bytes (+10)', result.stdout)

    def test_label_accepts_growth(self):
        tmp, repo = repo_with_commits(
            {'skills/alpha/SKILL.md': 'one\n'},
            {'skills/alpha/SKILL.md': 'one more line\n'},
        )
        with tmp:
            result = run_compare(repo, 'HEAD^1', 'HEAD', '--allow-increase')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('alpha: 4 -> 14 bytes (+10)', result.stdout)
        self.assertIn('accepted', result.stdout)

    def test_shrink_removal_and_nested_fixture_pass(self):
        tmp, repo = repo_with_commits(
            {'skills/alpha/SKILL.md': 'one more line\n', 'skills/beta/SKILL.md': 'plain\n'},
            {'skills/alpha/SKILL.md': 'one\n', 'skills/alpha/fixtures/nested/SKILL.md': 'big fixture text\n'},
        )
        with tmp:
            result = run_compare(repo, 'HEAD^1', 'HEAD')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('no skill grew', result.stdout)

    def test_unreadable_rev_is_an_input_error(self):
        tmp, repo = repo_with_commits({'skills/alpha/SKILL.md': 'one\n'})
        with tmp:
            missing = run_compare(repo, 'HEAD^1', 'HEAD')
            flag_like = run_compare(repo, '--all', 'HEAD')
        self.assertEqual(missing.returncode, 2, missing.stdout + missing.stderr)
        self.assertIn('context budget: unreadable', missing.stderr)
        self.assertEqual(flag_like.returncode, 2, flag_like.stdout + flag_like.stderr)
        self.assertIn('context budget: unreadable', flag_like.stderr)

    def test_symlink_skill_md_fails_closed(self):
        tmp, repo = repo_with_commits(
            {'skills/alpha/SKILL.md': 'one\n'},
            {'skills/alpha/target.md': 'one more line\n', 'skills/alpha/SKILL.md': ('symlink', 'target.md')},
        )
        with tmp:
            result = run_compare(repo, 'HEAD^1', 'HEAD')
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('context budget: unreadable', result.stderr)

    def test_help_explains_label_without_budget_file(self):
        result = subprocess.run([sys.executable, '-I', str(SCRIPT), '--help'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('context-increase', result.stdout)
        self.assertNotIn('context-budget.json', result.stdout)
        self.assertNotIn('--write-context-budget', result.stdout)


if __name__ == '__main__':
    unittest.main()
