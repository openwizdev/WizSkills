#!/usr/bin/env python3
"""Inventory command tests against fixture repositories (P2; red against DC1 stub)."""
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "inventory.py"

FAKE_GH_OK = """#!/usr/bin/env python3
import json, sys
args = " ".join(sys.argv[1:])
if "pulls" in args:
    print(json.dumps([
        {"number": 7, "title": "Old PR", "updated_at": "2029-12-01T00:00:00Z", "head": {"ref": "active-pr"}}
    ]))
elif "milestones" in args:
    print(json.dumps([
        {"number": 1, "title": "0.1.0", "open_issues": 0, "closed_issues": 3, "state": "open"}
    ]))
elif "issues" in args:
    print(json.dumps([
        {"number": 12, "title": "Idle issue", "updated_at": "2029-12-01T00:00:00Z"}
    ]))
else:
    print("[]")
"""

FAKE_GH_FAIL = """#!/usr/bin/env python3
import sys
print("gh api error: simulated offline failure", file=sys.stderr)
sys.exit(1)
"""


def _git(cwd, *args, env=None):
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=merged_env,
        check=True,
        capture_output=True,
        text=True,
    )


def _build_fixture_repo(root):
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Synthetic")
    _git(repo, "config", "user.email", "synthetic@example.invalid")

    old_env = {
        "GIT_AUTHOR_DATE": "2029-11-01T00:00:00Z",
        "GIT_COMMITTER_DATE": "2029-11-01T00:00:00Z",
    }
    (repo / "src" / "legacy").mkdir(parents=True)
    (repo / "src" / "legacy" / "old.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_old.py").write_text(
        "import unittest\n@unittest.skip('stale')\ndef test_x(): pass\n",
        encoding="utf-8",
    )
    (repo / "src" / "__pycache__").mkdir(parents=True)
    (repo / "src" / "__pycache__" / "old.pyc").write_bytes(b"\x00\x00")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial old commit", env=old_env)

    _git(repo, "checkout", "-b", "orphan-branch")
    (repo / "src" / "legacy" / "branch_only.py").write_text("X = 2\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "orphan branch commit", env=old_env)
    _git(repo, "checkout", "main")
    _git(repo, "remote", "add", "origin", "https://github.com/example/alpha.git")
    return repo


def _install_fake_gh(bin_dir, script_text):
    gh = bin_dir / "gh"
    gh.write_text(script_text, encoding="utf-8")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    return bin_dir


class DreamCycleInventoryTests(unittest.TestCase):
    # DC2 (#3090) removes expectedFailure when inventory.py is implemented.
    @unittest.expectedFailure
    def test_inventory_reports_all_seven_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _build_fixture_repo(root)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            _install_fake_gh(bin_dir, FAKE_GH_OK)
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"

            proc = subprocess.run(
                [sys.executable, "-I", str(SCRIPT), str(repo), "--days", "14"],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["schema"], "openwiz.dream-cycle.inventory.v1")
            self.assertEqual(data["unconfirmed"], [])
            sections = data["sections"]
            self.assertEqual(
                set(sections),
                {
                    "stale_paths",
                    "orphan_branches",
                    "idle_issues",
                    "idle_prs",
                    "empty_milestones",
                    "skipped_tests",
                    "generated_files",
                },
            )
            self.assertGreaterEqual(sections["stale_paths"]["total"], 1)
            self.assertGreaterEqual(sections["orphan_branches"]["total"], 1)
            self.assertGreaterEqual(sections["idle_issues"]["total"], 1)
            self.assertGreaterEqual(sections["idle_prs"]["total"], 1)
            self.assertGreaterEqual(sections["empty_milestones"]["total"], 1)
            self.assertGreaterEqual(sections["skipped_tests"]["total"], 1)
            self.assertGreaterEqual(sections["generated_files"]["total"], 1)

    # DC2 (#3090) removes expectedFailure when inventory.py is implemented.
    @unittest.expectedFailure
    def test_failed_gh_read_reports_unconfirmed_and_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _build_fixture_repo(root)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            _install_fake_gh(bin_dir, FAKE_GH_FAIL)
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"

            proc = subprocess.run(
                [sys.executable, "-I", str(SCRIPT), str(repo), "--days", "14"],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(proc.returncode, 2, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertTrue(data["unconfirmed"], "expected unconfirmed entries on gh failure")
            for section_name in ("idle_issues", "idle_prs", "empty_milestones"):
                section = data["sections"][section_name]
                self.assertEqual(section["status"], "unconfirmed")
                self.assertIsNone(section["total"])
                self.assertTrue(section["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
