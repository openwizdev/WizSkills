import json
import stat
import unittest
from pathlib import Path

import support

EVENT = (
    '{"schema":"openwiz.ghost.v1","kind":"event","at":"2026-01-01T00:00:00Z",'
    '"suggestion_id":"sug-dismissed","session_id":"session-1","surface":"cli",'
    '"outcome":"dismissed","tier":"recall","confidence":0.5,"latency_ms":1,'
    '"chars_accepted":0}\n'
)


class LearnPass(unittest.TestCase):
    def run_home(self, reports, **home):
        folder = self.enterContext(support_tmp())
        house = support.make_home(folder, **home)
        before_skill = (house / "skill.json").read_bytes()
        before_lexicon = (house / "lexicon.json").read_bytes()
        env, log = support.fake_env(folder, reports)
        proc = support.run(support.LEARN, ["--home", str(house)], env)
        return proc, house, before_skill, before_lexicon, support.calls(log)

    def test_a_worsening_change_is_reverted(self):
        proc, house, skill, lexicon, rows = self.run_home(
            [support.report(0.8, 12), support.report(0.4, 6)])
        self.assertEqual((house / "skill.json").read_bytes(), skill,
                         "a worsening change must be reverted")
        self.assertEqual((house / "lexicon.json").read_bytes(), lexicon)
        self.assertEqual(proc.stdout, "restored\n")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual([row["skill"] for row in rows], ["old", "new"])
        self.assertEqual(proc.stderr, "")

    def test_an_improving_change_is_kept(self):
        proc, house, skill, _lexicon, rows = self.run_home(
            [support.report(0.4, 6), support.report(0.8, 12)])
        after = json.loads((house / "skill.json").read_text(encoding="utf-8"))
        self.assertNotEqual((house / "skill.json").read_bytes(), skill)
        self.assertIn("all recs", after["phrases"])
        self.assertIn("J381", after["codes"])
        terms = json.loads((house / "lexicon.json").read_text(encoding="utf-8"))["terms"]
        self.assertEqual([term["term"] for term in terms], ["J381"])
        self.assertEqual(proc.stdout, "kept\n")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual([row["skill"] for row in rows], ["old", "new"])
        self.assertEqual([row["args"][:4] for row in rows],
                         [["ghost", "bench", "--source", "sent"],
                          ["ghost", "bench", "--source", "sent"]])

    def test_a_drop_in_only_characters_saved_is_reverted(self):
        proc, house, skill, lexicon, _rows = self.run_home(
            [support.report(0.8, 12), support.report(0.8, 6)])
        self.assertEqual((house / "skill.json").read_bytes(), skill)
        self.assertEqual((house / "lexicon.json").read_bytes(), lexicon)
        self.assertEqual(proc.stdout, "restored\n")

    def test_a_drop_in_only_acceptance_is_reverted(self):
        proc, house, skill, _lexicon, _rows = self.run_home(
            [support.report(0.8, 12), support.report(0.4, 12)])
        self.assertEqual((house / "skill.json").read_bytes(), skill)
        self.assertEqual(proc.stdout, "restored\n")

    def test_an_equal_bench_is_kept(self):
        proc, house, skill, _lexicon, _rows = self.run_home(
            [support.report(0.5, 8), support.report(0.5, 8)])
        self.assertNotEqual((house / "skill.json").read_bytes(), skill)
        self.assertEqual(proc.stdout, "kept\n")

    def test_a_bad_second_report_restores_the_files(self):
        proc, house, skill, lexicon, _rows = self.run_home(
            [support.report(0.5, 8), {"schema": "openwiz.ghost.v1"}])
        self.assertEqual((house / "skill.json").read_bytes(), skill)
        self.assertEqual((house / "lexicon.json").read_bytes(), lexicon)
        self.assertEqual(proc.stdout, "restored\n")
        self.assertEqual(proc.returncode, 0)

    def test_a_failed_first_bench_writes_nothing(self):
        proc, house, skill, lexicon, rows = self.run_home([{"exit": 1}])
        self.assertEqual((house / "skill.json").read_bytes(), skill)
        self.assertEqual((house / "lexicon.json").read_bytes(), lexicon)
        self.assertEqual(proc.stdout, "refused\n")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(len(rows), 1)

    def test_the_log_is_unread_when_logging_is_off(self):
        folder = self.enterContext(support_tmp())
        house = support.make_home(folder, log=EVENT.encode(), logging=False)
        log_path = house / "log.jsonl"
        log_path.chmod(0)
        try:
            env, calls = support.fake_env(
                folder, [support.report(0.4, 6), support.report(0.8, 12)])
            proc = support.run(support.LEARN, ["--home", str(house)], env)
            skill = json.loads((house / "skill.json").read_text(encoding="utf-8"))
            self.assertEqual(proc.stdout, "kept\n")
            self.assertNotIn("sug-dismissed", skill["never_suggest"])
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(support.calls(calls)[0]["args"][5], str(house / "replay.json"))
        finally:
            log_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def test_a_dismissal_in_the_log_is_kept_when_the_bench_improves(self):
        proc, house, _skill, _lexicon, rows = self.run_home(
            [support.report(0.4, 6), support.report(0.8, 12)],
            log=EVENT.encode(), logging=True)
        skill = json.loads((house / "skill.json").read_text(encoding="utf-8"))
        self.assertEqual(skill["never_suggest"], ["sug-dismissed"])
        self.assertEqual(proc.stdout, "kept\n")
        self.assertEqual([row["args"][5] for row in rows], [str(house / "replay.json"), str(house / "replay.json")])
        self.assertFalse(any("http://" in " ".join(row["args"]) or "https://" in " ".join(row["args"])
                             for row in rows))

    def test_a_log_outside_home_is_not_opened(self):
        folder = self.enterContext(support_tmp())
        house = support.make_home(folder, logging=True)
        outside = Path(folder) / "outside.jsonl"
        outside.write_bytes(EVENT.encode())
        outside.chmod(0)
        try:
            (house / "log.jsonl").symlink_to(outside)
            env, log = support.fake_env(folder, [support.report(0.8, 12)])
            proc = support.run(support.LEARN, ["--home", str(house)], env)
            self.assertEqual(proc.stdout, "refused\n")
            self.assertEqual(support.calls(log), [])
            self.assertEqual((house / "skill.json").read_bytes(), support.SKILL)
        finally:
            outside.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def test_a_repeated_key_in_the_bench_report_is_not_kept(self):
        duplicate = (
            '{"schema":"openwiz.ghost.v1","kind":"bench_report","source":"sent",'
            '"messages":2,"overall":{"shown":10,"accepted":8,"acceptance_rate":0.1,'
            '"acceptance_rate":0.9,"chars_saved_per_message":12,"suggestions_per_message":1,'
            '"p50_latency_ms":4,"p90_latency_ms":9},"per_tier":[],"per_surface":[]}\n'
        )
        proc, house, skill, _lexicon, _rows = self.run_home(
            [support.report(0.5, 8), duplicate])
        self.assertEqual((house / "skill.json").read_bytes(), skill)
        self.assertEqual(proc.stdout, "restored\n")

    def test_learn_does_not_import_a_network_library(self):
        text = (support.ROOT / "scripts" / "learn.py").read_text(encoding="utf-8")
        for name in ("socket", "urllib", "http.client", "requests"):
            self.assertNotIn("import " + name, text)
            self.assertNotIn("from " + name, text)


def support_tmp():
    import tempfile
    return tempfile.TemporaryDirectory()


if __name__ == "__main__":
    unittest.main()
