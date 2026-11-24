#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "inventory.py"
FIXTURES = HERE / "fixtures" / "inventory"
sys.path.insert(0, str(HERE))
from test_contract import SCHEMA_PATH, parse_json_strict, validate  # noqa: E402

SECTIONS = {
    "stale_paths", "orphan_branches", "idle_issues", "idle_prs",
    "empty_milestones", "skipped_tests", "generated_files",
}
OLD = {"GIT_AUTHOR_DATE": "2020-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2020-01-01T00:00:00Z"}
OLDER = {"GIT_AUTHOR_DATE": "2019-06-01T00:00:00Z", "GIT_COMMITTER_DATE": "2019-06-01T00:00:00Z"}


def _git(cwd, *args, env=None):
    subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **(env or {})},
                   check=True, capture_output=True, text=True)


def _write(repo, rel, text):
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _build_fixture_repo(root):
    """Synthetic repository: old and fresh paths, test markers, generated files, branches."""
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Synthetic")
    _git(repo, "config", "user.email", "synthetic@example.invalid")
    _write(repo, "src/legacy/older.py", "A = 0\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "older commit", env=OLDER)
    _write(repo, "src/legacy/old.py", "VALUE = 1\n")
    _write(repo, "tests/test_old.py",
           "import unittest\n@unittest.skip('stale')\ndef test_x(): pass\n"
           "@pytest.mark.xfail\ndef test_y(): pass\n")
    _write(repo, "web/app.test.js", "it.only('runs alone', () => {});\ntest.todo('later');\n")
    _write(repo, "core/lib.rs", "#[test]\n#[ignore]\nfn slow() {}\n")
    _write(repo, "docs/notes.md", "TODO: skip this later\n")
    _write(repo, "src/check.py", 'TEMPLATE = "@unittest.skip(\'not a test\')"\n')
    (repo / "src" / "__pycache__").mkdir(parents=True)
    (repo / "src" / "__pycache__" / "old.pyc").write_bytes(b"\x00\x00")
    _write(repo, "node_modules/pkg/index.js", "module.exports = 1;\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial old commit", env=OLD)

    for branch in ("orphan-branch", "active-pr"):
        _git(repo, "checkout", "-b", branch, "main")
        _write(repo, f"src/{branch}.py", "X = 2\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", f"{branch} commit", env=OLD)
    _git(repo, "checkout", "-b", "merged-branch", "main")
    _write(repo, "src/merged.py", "M = 3\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "merged branch commit", env=OLD)
    _git(repo, "checkout", "main")
    _git(repo, "merge", "--no-ff", "-m", "merge", "merged-branch", env=OLD)
    _write(repo, "src/fresh.py", "NEW = 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fresh commit")
    _git(repo, "remote", "add", "origin", "https://github.com/example/alpha.git")
    return repo


def _run(root, repo_arg, gh_data, *extra):
    """Run inventory.py with the synthetic gh on PATH; return (exit code, JSON or None, stderr)."""
    bin_dir = root / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    shutil.copy(FIXTURES / "fake_gh.py", gh)
    gh.chmod(0o755)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = root / "gh_data.json"
    data.write_text((FIXTURES / gh_data).read_text(encoding="utf-8").replace("NOW", now), encoding="utf-8")
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
           "FAKE_GH_DATA": str(data), "FAKE_GH_LOG": str(root / "gh.log")}
    proc = subprocess.run([sys.executable, "-I", str(SCRIPT), str(repo_arg), *extra],
                          capture_output=True, text=True, env=env)
    try:
        out = json.loads(proc.stdout)
    except ValueError:
        out = None
    return proc.returncode, out, proc.stderr


class DreamCycleInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = parse_json_strict(SCHEMA_PATH.read_text(encoding="utf-8"))

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = _build_fixture_repo(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def assertInventory(self, data):
        self.assertIsNotNone(data, "stdout is not JSON")
        validate(self.schema, {"$ref": "#/$defs/inventory"}, data)

    def test_inventory_reports_all_seven_sections(self):
        code, data, err = _run(self.root, self.repo, "gh_ok.json", "--days", "14")
        self.assertEqual(code, 0, err)
        self.assertInventory(data)
        self.assertEqual(data["repo"], "example/alpha")
        self.assertEqual((data["days"], data["pr_idle_days"]), (14, 7))
        self.assertEqual(data["unconfirmed"], [])
        s = data["sections"]
        self.assertEqual(set(s), SECTIONS)
        self.assertTrue(all(sec["status"] == "ok" for sec in s.values()))

        stale = {i["folder"]: i for i in s["stale_paths"]["items"]}
        self.assertEqual(stale["src/legacy"], {"folder": "src/legacy", "count": 2, "oldest": "2019-06-01"})
        stale_count = sum(i["count"] for i in s["stale_paths"]["items"])
        self.assertEqual(s["stale_paths"]["total"], stale_count)
        self.assertNotIn("fresh", json.dumps(s["stale_paths"]))
        self.assertEqual(stale["src"]["count"], 2)  # check.py and merged.py; fresh.py is recent

        self.assertEqual(s["orphan_branches"]["total"], 2)
        branches = {i["branch"]: i for i in s["orphan_branches"]["items"]}
        self.assertEqual(branches["orphan-branch"], {"branch": "orphan-branch", "merged": False, "last_commit": "2020-01-01"})
        self.assertTrue(branches["merged-branch"]["merged"])
        self.assertNotIn("active-pr", branches)
        self.assertNotIn("main", branches)

        self.assertEqual([(i["number"], i["title"]) for i in s["idle_issues"]["items"]], [(12, "Idle issue")])
        self.assertEqual([i["number"] for i in s["idle_prs"]["items"]], [7])
        self.assertEqual([i["title"] for i in s["empty_milestones"]["items"]], ["0.1.0"])

        skipped = sorted((i["path"], i["line"], i["marker"]) for i in s["skipped_tests"]["items"])
        self.assertEqual(skipped, [
            ("core/lib.rs", 2, "ignore"),
            ("tests/test_old.py", 2, "skip"),
            ("tests/test_old.py", 4, "xfail"),
            ("web/app.test.js", 1, ".only"),
            ("web/app.test.js", 2, "todo"),
        ])
        self.assertEqual(s["skipped_tests"]["total"], 5)

        generated = {i["path"]: i["kind"] for i in s["generated_files"]["items"]}
        self.assertEqual(generated, {"src/__pycache__/old.pyc": ".pyc", "node_modules/pkg/index.js": "node_modules"})

    def test_limit_caps_items_but_not_totals(self):
        code, data, err = _run(self.root, self.repo, "gh_ok.json", "--limit", "1")
        self.assertEqual(code, 0, err)
        self.assertInventory(data)
        self.assertEqual(len(data["sections"]["skipped_tests"]["items"]), 1)
        self.assertEqual(data["sections"]["skipped_tests"]["total"], 5)
        self.assertEqual(len(data["sections"]["orphan_branches"]["items"]), 1)
        self.assertEqual(data["sections"]["orphan_branches"]["total"], 2)

    def test_failed_gh_read_reports_unconfirmed_and_exits_2(self):
        code, data, err = _run(self.root, self.repo, "gh_fail.json", "--days", "14")
        self.assertEqual(code, 2, err)
        self.assertInventory(data)
        sources = {u["source"] for u in data["unconfirmed"]}
        self.assertEqual(sources, {"orphan_branches", "idle_issues", "idle_prs", "empty_milestones"})
        for name in sources:
            section = data["sections"][name]
            self.assertEqual(section["status"], "unconfirmed")
            self.assertIsNone(section["total"])
            self.assertIn("simulated offline failure", section["reason"])
        self.assertEqual(data["sections"]["stale_paths"]["status"], "ok")

    def test_partial_gh_failure_marks_only_dependent_sections(self):
        code, data, err = _run(self.root, self.repo, "gh_pulls_fail.json")
        self.assertEqual(code, 2, err)
        self.assertInventory(data)
        self.assertEqual({u["source"] for u in data["unconfirmed"]}, {"orphan_branches", "idle_prs"})
        self.assertEqual(data["sections"]["idle_issues"]["total"], 1)
        self.assertEqual(data["sections"]["empty_milestones"]["total"], 0)

    def test_reads_are_paginated_rest_calls(self):
        _run(self.root, self.repo, "gh_ok.json")
        calls = (self.root / "gh.log").read_text(encoding="utf-8").splitlines()
        self.assertTrue(calls)
        for call in calls:
            self.assertTrue(call.startswith("api --paginate repos/example/alpha/"), call)
            self.assertNotIn("graphql", call)

    def test_shallow_clone_history_is_unconfirmed(self):
        shallow = self.root / "shallow"
        _git(self.root, "clone", "-q", "--depth", "1", f"file://{self.repo}", str(shallow))
        _git(shallow, "remote", "set-url", "origin", "git@github.com:example/alpha.git")
        code, data, err = _run(self.root, shallow, "gh_ok.json")
        self.assertEqual(code, 2, err)
        self.assertInventory(data)
        self.assertEqual(data["repo"], "example/alpha")
        self.assertEqual(data["sections"]["stale_paths"]["status"], "unconfirmed")
        self.assertIn("shallow", data["sections"]["stale_paths"]["reason"])

    def test_no_github_remote_is_unconfirmed_not_zero(self):
        _git(self.repo, "remote", "remove", "origin")
        code, data, err = _run(self.root, self.repo, "gh_ok.json")
        self.assertEqual(code, 2, err)
        self.assertInventory(data)
        for name in ("orphan_branches", "idle_issues", "idle_prs", "empty_milestones"):
            self.assertEqual(data["sections"][name]["status"], "unconfirmed")

    def test_bad_arguments_and_unreadable_target_exit_1(self):
        for args in (["--days", "0"], ["--limit", "-1"]):
            with self.subTest(args=args):
                code, data, _ = _run(self.root, self.repo, "gh_ok.json", *args)
                self.assertEqual(code, 1)
                self.assertIsNone(data)
        not_repo = self.root / "plain"
        not_repo.mkdir()
        code, data, err = _run(self.root, not_repo, "gh_ok.json")
        self.assertEqual(code, 1)
        self.assertIsNone(data)
        self.assertTrue(err.strip())


if __name__ == "__main__":
    unittest.main(verbosity=2)
