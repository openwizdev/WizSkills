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
        self.home = support.make_home(folder, **home)
        live = support.ghost_of(folder)
        before_skill = (live / "skill.json").read_bytes()
        before_lexicon = (live / "lexicon.json").read_bytes()
        env, log = support.fake_env(folder, reports)
        proc = support.run(support.LEARN, ["--home", str(self.home)], env)
        return proc, live, before_skill, before_lexicon, support.calls(log)

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
        self.assertEqual(sorted(after), ["never_suggest", "phrases", "tone"])
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

    def run_live(self, reports):
        folder = self.enterContext(support_tmp())
        house = support.make_home(folder)
        live = support.ghost_of(folder)
        env, log = support.fake_env(folder, reports, FAKE_LIVE=str(live / "skill.json"))
        proc = support.run(support.LEARN, ["--home", str(house)], env)
        return proc, live, support.calls(log)

    def assert_live_untouched(self, house):
        self.assertEqual((house / "skill.json").read_bytes(), support.SKILL)
        self.assertEqual((house / "lexicon.json").read_bytes(), support.LEXICON)
        self.assertEqual(sorted(path.name for path in house.iterdir()),
                         ["lexicon.json", "skill.json"])

    def test_the_second_bench_reads_a_staged_candidate_not_the_live_files(self):
        proc, house, rows = self.run_live([support.report(0.4, 6), support.report(0.8, 12)])
        self.assertEqual([row["skill"] for row in rows], ["old", "new"])
        self.assertEqual([row["live"] for row in rows], ["old", "old"],
                         "the live files must not change before the second report passes")
        self.assertEqual(proc.stdout, "kept\n")
        self.assertIn(b"all recs", (house / "skill.json").read_bytes())

    def test_a_cancelled_second_bench_leaves_the_live_files(self):
        proc, house, rows = self.run_live([support.report(0.4, 6), {"sigint": 1}])
        self.assertEqual(len(rows), 2)
        self.assert_live_untouched(house)
        self.assertNotEqual(proc.returncode, 0)

    def test_an_unreadable_second_report_leaves_the_live_files(self):
        proc, house, rows = self.run_live([support.report(0.4, 6), {"raw": "ff0a"}])
        self.assertEqual(len(rows), 2)
        self.assert_live_untouched(house)
        self.assertEqual(proc.stdout, "restored\n")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr, "")

    def test_the_log_is_unread_when_logging_is_off(self):
        folder = self.enterContext(support_tmp())
        house = support.make_home(folder, log=EVENT.encode(), logging=False)
        events = support.state_of(folder) / "ghost" / "events.jsonl"
        home_log = house / "log.jsonl"
        home_log.write_bytes(EVENT.replace("sug-dismissed", "sug-home").encode(), )
        (house / "logging.on").write_bytes(b"")
        events.chmod(0)
        home_log.chmod(0)
        try:
            env, calls = support.fake_env(
                folder, [support.report(0.4, 6), support.report(0.8, 12)])
            proc = support.run(support.LEARN, ["--home", str(house)], env)
            skill = json.loads((support.ghost_of(folder) / "skill.json").read_text(encoding="utf-8"))
            self.assertEqual(proc.stdout, "kept\n")
            self.assertNotIn("sug-dismissed", skill["never_suggest"])
            self.assertNotIn("sug-home", skill["never_suggest"])
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(support.calls(calls)[0]["args"][5], str(house / "replay.json"))
        finally:
            events.chmod(stat.S_IRUSR | stat.S_IWUSR)
            home_log.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def test_a_dismissal_id_never_enters_never_suggest(self):
        proc, house, _skill, _lexicon, rows = self.run_home(
            [support.report(0.4, 6), support.report(0.8, 12)],
            log=EVENT.encode(), logging=True)
        skill = json.loads((house / "skill.json").read_text(encoding="utf-8"))
        self.assertEqual(skill["never_suggest"], [],
                         "the engine filters by suggestion text, so an event id blocks nothing")
        self.assertEqual(proc.stdout, "kept\n")
        self.assertEqual([row["args"][5] for row in rows],
                         [str(self.home / "replay.json"), str(self.home / "replay.json")])
        self.assertFalse(any("http://" in " ".join(row["args"]) or "https://" in " ".join(row["args"])
                             for row in rows))

    def test_a_log_outside_the_state_directory_is_not_opened(self):
        folder = self.enterContext(support_tmp())
        house = support.make_home(folder, logging=True)
        outside = Path(folder) / "outside.jsonl"
        outside.write_bytes(EVENT.encode())
        outside.chmod(0)
        events = support.state_of(folder) / "ghost" / "events.jsonl"
        try:
            events.symlink_to(outside)
            env, log = support.fake_env(folder, [support.report(0.8, 12)])
            proc = support.run(support.LEARN, ["--home", str(house)], env)
            self.assertEqual(proc.stdout, "refused\n")
            self.assertEqual(support.calls(log), [])
            self.assertEqual((support.ghost_of(folder) / "skill.json").read_bytes(), support.SKILL)
        finally:
            outside.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def test_forget_leaves_no_trace_of_the_log_in_the_kept_skill(self):
        folder = self.enterContext(support_tmp())
        house = support.make_home(folder, log=EVENT.encode(), logging=True)
        live = support.ghost_of(folder)
        env, _log = support.fake_env(folder, [
            support.report(0.4, 6), support.report(0.8, 12),
            support.report(0.8, 12), support.report(0.8, 12),
        ])
        first = support.run(support.LEARN, ["--home", str(house)], env)
        self.assertEqual(first.stdout, "kept\n")
        self.assertNotIn(b"sug-dismissed", (live / "skill.json").read_bytes())
        events = live / "events.jsonl"
        events.unlink()
        second = support.run(support.LEARN, ["--home", str(house)], env)
        self.assertEqual(second.stdout, "kept\n")
        self.assertNotIn(b"sug-dismissed", (live / "skill.json").read_bytes())
        self.assertNotIn(b"sug-dismissed", (live / "lexicon.json").read_bytes())
        self.assertFalse(events.exists())

    def test_never_suggest_text_blocks_every_learned_phrase_containing_it(self):
        proc, live, _skill, _lexicon, _rows = self.run_home(
            [support.report(0.4, 6), support.report(0.8, 12)],
            skill=b'{"phrases":[],"tone":"","never_suggest":["RECS"]}\n')
        skill = json.loads((live / "skill.json").read_text(encoding="utf-8"))
        self.assertEqual(proc.stdout, "kept\n")
        self.assertEqual(skill["phrases"], ["j381 all"],
                         "the engine drops any suggestion containing a never_suggest entry")
        self.assertEqual(skill["never_suggest"], ["RECS"])

    def test_the_kept_skill_file_is_the_engines_file_and_shape(self):
        proc, live, _skill, _lexicon, rows = self.run_home(
            [support.report(0.4, 6), support.report(0.8, 12)])
        self.assertEqual(proc.stdout, "kept\n")
        self.assertEqual(rows[0]["home"], str(live),
                         "the first bench must read the engine's own skill file")
        skill = json.loads((live / "skill.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(skill), ["never_suggest", "phrases", "tone"])
        self.assertTrue(all(isinstance(item, str) for item in skill["phrases"] + skill["never_suggest"]))
        self.assertIsInstance(skill["tone"], str)
        self.assertFalse((self.home / "skill.json").exists())
        self.assertEqual(sorted(path.name for path in live.iterdir()), ["lexicon.json", "skill.json"])

    def test_a_skill_file_with_a_key_the_engine_refuses_is_refused(self):
        for extra in (b'"codes":[],', b'"lexicon":[],'):
            folder = self.enterContext(support_tmp())
            skill = b'{"phrases":[],' + extra + b'"tone":"","never_suggest":[]}\n'
            house = support.make_home(folder, skill=skill)
            env, log = support.fake_env(folder, [support.report(0.4, 6)])
            proc = support.run(support.LEARN, ["--home", str(house)], env)
            self.assertEqual(proc.stdout, "refused\n", extra)
            self.assertEqual(support.calls(log), [])
            self.assertEqual((support.ghost_of(folder) / "skill.json").read_bytes(), skill)

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
