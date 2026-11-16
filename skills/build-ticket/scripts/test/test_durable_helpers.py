"""#1686: durable snapshots and frozen end states, through the fake gh only."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("fixtures", HERE / "test_check_helpers.py")
f = importlib.util.module_from_spec(spec)
sys.dont_write_bytecode = True
spec.loader.exec_module(f)


class DurableChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.scratch = self.root / "scratch"
        self.scratch.mkdir()
        self.bin = f.tool_dir(self.root, set())
        self.world = f.base()
        self.world_file = self.root / "world.json"
        self.log = self.root / "gh.log"
        self.env = {"PATH": str(self.bin), "HOME": str(self.home), "LC_ALL": "C",
                    "FAKE_GH_WORLD": str(self.world_file), "FAKE_GH_LOG": str(self.log),
                    "TMPDIR": str(self.scratch)}

    def run_check(self, *args):
        self.world_file.write_text(json.dumps(self.world))
        return subprocess.run([shutil.which("sh"), str(f.SCRIPT), *map(str, args)],
                              cwd=self.root, env=self.env, capture_output=True, text=True, timeout=60)

    def saved(self, result, kind):
        prefix = f"check-helpers.sh: {kind} saved: "
        paths = [Path(line[len(prefix):]) for line in result.stderr.splitlines() if line.startswith(prefix)]
        self.assertEqual(len(paths), 1, result.stderr)
        path = paths[0]
        self.assertTrue(path.resolve().is_relative_to(self.home.resolve()), path)
        self.assertTrue(path.is_file(), path)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        return path

    def snapshot(self):
        result = self.run_check("snapshot", "12", "31")
        self.assertEqual(result.returncode, 0, result.stderr)
        path = self.saved(result, "snapshot")
        self.assertEqual(json.loads(path.read_text()), json.loads(result.stdout))
        return path

    def finish(self, snapshot, code=0):
        result = self.run_check("check", snapshot)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result, self.saved(result, "window")

    def test_snapshot_survives_temporary_directory_wipe(self):
        snapshot = self.snapshot()
        shutil.rmtree(self.scratch)
        self.scratch.mkdir()
        self.finish(snapshot)

    def test_fleet_and_branch_writes_after_end_do_not_change_original_window(self):
        snapshot = self.snapshot()
        original, end = self.finish(snapshot)
        f.chain(f.add_comment(12, 1204, "launch-fleet: archived"),
                f.add_ref(f.LEAD, f.sha("ff")), f.del_comment(12, 1203),
                f.set_pull(31, "closed", True))(self.world)
        # A fresh window sees all of those changes.
        current, _ = self.finish(snapshot, 1)
        self.assertIn("comment 1204 on #12 is new", current.stdout)
        calls = self.log.read_text()
        shutil.rmtree(self.scratch)
        self.scratch.mkdir()
        replay = self.run_check("check", snapshot, "--ended", end)
        self.assertEqual(replay.returncode, 0, replay.stderr)
        self.assertEqual(replay.stdout, original.stdout)
        self.assertEqual(self.log.read_text(), calls, "a replay must not read a later state")

    def test_helper_write_inside_window_still_hits_with_a_valid_fleet_prefix(self):
        snapshot = self.snapshot()
        f.add_comment(12, 1204, "launch-fleet: archived")(self.world)
        original, end = self.finish(snapshot, 1)
        self.assertEqual(original.stdout, "hit #12: comment 1204 on #12 is new\n")
        f.del_comment(12, 1204)(self.world)
        replay = self.run_check("check", snapshot, "--ended", end)
        self.assertEqual(replay.returncode, 1, replay.stderr)
        self.assertEqual(replay.stdout, original.stdout)
        named = self.run_check("check", snapshot, "--ended", end, "--loop-comment", "1204")
        self.assertEqual(named.returncode, 0, named.stderr)

    def test_durable_save_failure_is_not_a_success(self):
        (self.home / ".openwiz").write_text("blocked")
        result = self.run_check("snapshot", "12")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("can't save", result.stderr)

    def test_window_save_failure_never_reports_clean(self):
        snapshot = self.snapshot()
        store = self.home / ".openwiz/helper-checks/example/widgets/12"
        # Keep the start file readable, but make its parent store unusable.
        copy = self.root / "before.json"
        copy.write_text(snapshot.read_text())
        shutil.rmtree(store)
        store.write_text("blocked")
        result = self.run_check("check", copy)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("can't save window", result.stderr)

    def test_repository_dot_components_cannot_escape_durable_storage(self):
        for repo in ("../widgets", "example/..", "./widgets", "example/."):
            with self.subTest(repo=repo):
                self.world["repo"] = repo
                result = self.run_check("snapshot", "12")
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertIn("the repository must be owner/name", result.stderr)

    def test_every_in_window_write_is_preserved_after_later_reverts(self):
        snapshot = self.snapshot()
        f.chain(f.add_ref(f.LEAD, f.sha("cc")), f.del_comment(12, 1203),
                f.add_review(31, 3151), f.edit_inline(31, 3160, "helper edit"),
                f.set_pull(31, "closed", True))(self.world)
        original, end = self.finish(snapshot, 1)
        self.assertEqual(original.stdout, f.hits(
            f"branch {f.LEAD} moved from {f.sha('12a')} to {f.sha('cc')}",
            "pull request #31 was merged", "comment 1203 on #12 was deleted",
            "review 3151 on #31 is new", "review comment 3160 on #31 was edited"))
        self.world = f.base()
        replay = self.run_check("check", snapshot, "--ended", end)
        self.assertEqual(replay.returncode, 1, replay.stderr)
        self.assertEqual(replay.stdout, original.stdout)

    def test_invalid_or_mismatched_window_fails_closed(self):
        snapshot = self.snapshot()
        _, end = self.finish(snapshot)
        invalid = self.root / "invalid.json"
        invalid.write_text("{}")
        second = copy.deepcopy(json.loads(snapshot.read_text()))
        second["branches"][f.LEAD] = f.sha("bb")
        other = self.root / "other.json"
        other.write_text(json.dumps(second))
        bad_after = self.root / "bad-after.json"
        value = json.loads(end.read_text())
        value["after"]["branches"][f.LEAD] = "not-a-commit"
        bad_after.write_text(json.dumps(value))
        foreign = self.root / "foreign.json"
        value = json.loads(end.read_text())
        value["after"]["repo"] = "example/elsewhere"
        foreign.write_text(json.dumps(value))
        for start, ended in ((snapshot, invalid), (other, end), (snapshot, bad_after),
                             (snapshot, foreign), (snapshot, self.root / "missing")):
            with self.subTest(start=start, ended=ended):
                result = self.run_check("check", start, "--ended", ended)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
