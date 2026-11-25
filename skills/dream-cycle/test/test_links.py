#!/usr/bin/env python3
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "links.py"
FIXTURES = HERE / "fixtures" / "links"
sys.path.insert(0, str(HERE))
from test_contract import SCHEMA_PATH, parse_json_strict, validate  # noqa: E402 -- sibling test_contract is loaded from HERE


def _run(*args):
    proc = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )
    try:
        data = json.loads(proc.stdout) if proc.stdout.strip() else None
    except ValueError:
        data = None
    return proc.returncode, data, proc.stderr


class DreamCycleLinksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = parse_json_strict(SCHEMA_PATH.read_text(encoding="utf-8"))

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _copy_fixture_org(self):
        dest = self.tmp / "links"
        shutil.copytree(FIXTURES, dest)
        return dest

    def test_candidates_pairs_org_and_suppresses_ubiquitous_name(self):
        code, data, err = _run(
            "candidates",
            "--settings", str(FIXTURES / "settings.json"),
            "--date", "2030-01-15",
        )
        self.assertEqual(code, 0, err)
        self.assertIsNotNone(data)
        self.assertEqual(data["schema"], "openwiz.dream-cycle.link-candidates.v1")
        self.assertEqual(data["unconfirmed"], [])

        candidates = data["candidates"]
        self.assertGreater(len(candidates), 0)

        for cand in candidates:
            self.assertNotIn("exampleorg", [e.lower() for e in cand.get("entities", [])])

        types = {c["link_type"] for c in candidates}
        self.assertIn("promise-to-work", types)
        self.assertIn("enemy-move-to-us", types)
        self.assertIn("says-vs-does", types)

        refs_sets = [frozenset(e["ref"].split("#L", 1)[0] for e in c["ends"]) for c in candidates]
        self.assertTrue(
            any("example/notes:scoreboard.md" in r and "example/alpha:README.md" in r for r in refs_sets),
            f"expected scoreboard-to-source pair in {refs_sets}",
        )
        self.assertTrue(
            any("example/notes:people/acme.md" in r and "example/alpha#64" in r for r in refs_sets),
            f"expected promise-to-open-issue pair in {refs_sets}",
        )
        self.assertTrue(
            any("example/notes:market/rival.md" in r and "example/alpha#70" in r for r in refs_sets),
            f"expected competitor-move-to-open-ticket pair in {refs_sets}",
        )

    def test_candidates_caps_per_entity_and_link_budget_and_watermarks(self):
        org = self._copy_fixture_org()
        (org / "org" / "notes" / "people" / "rare.md").write_text(
            "# Rare\nContact: rarewidget\n", encoding="utf-8"
        )
        for idx in range(7):
            (org / "org" / "alpha" / f"doc_{idx}.md").write_text(
                f"# Doc {idx}\nMentions rarewidget here.\n", encoding="utf-8"
            )
        settings_path = org / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        settings["link_budget"] = 8
        settings_path.write_text(json.dumps(settings), encoding="utf-8")

        code, data, err = _run("candidates", "--settings", str(settings_path), "--date", "2030-01-15")
        self.assertEqual(code, 0, err)
        self.assertLessEqual(len(data["candidates"]), 8)
        rare_count = sum(
            1 for c in data["candidates"]
            if "rarewidget" in [e.lower() for e in c.get("entities", [])]
        )
        self.assertLessEqual(rare_count, 5)

        wm_path = self.tmp / "watermarks.json"
        wm_path.write_text(json.dumps({
            "repos": {
                "example/notes": {"since": "2099-01-01"},
                "example/alpha": {"since": "2099-01-01"},
                "example/skills": {"since": "2099-01-01"},
            },
            "read_since": [],
        }), encoding="utf-8")
        code2, data2, err2 = _run(
            "candidates", "--settings", str(settings_path), "--watermarks", str(wm_path), "--date", "2030-01-15"
        )
        self.assertEqual(code2, 0, err2)
        self.assertEqual(data2["candidates"], [])

        wm_path.write_text(json.dumps({
            "repos": {
                "example/notes": {"since": "2099-01-01"},
                "example/alpha": {"since": "2099-01-01"},
                "example/skills": {"since": "2099-01-01"},
            },
            "read_since": ["example/notes:scoreboard.md"],
        }), encoding="utf-8")
        code3, data3, err3 = _run(
            "candidates", "--settings", str(settings_path), "--watermarks", str(wm_path), "--date", "2030-01-15"
        )
        self.assertEqual(code3, 0, err3)
        self.assertGreater(len(data3["candidates"]), 0)
        self.assertTrue(
            all(any("example/notes:scoreboard.md" in e["ref"] for e in c["ends"]) for c in data3["candidates"])
        )

    def test_gate_a_check_drops_invalid_with_reasons_and_passes_valid(self):
        code, data, err = _run(
            "check",
            str(FIXTURES / "gate_a_candidates.jsonl"),
            "--settings", str(FIXTURES / "settings.json"),
            "--ledger", str(FIXTURES / "ledger_seed.jsonl"),
        )
        self.assertEqual(code, 0, err)
        self.assertIsNotNone(data)
        self.assertEqual(data["unconfirmed"], [])

        passed_ids = [item["id"] for item in data["passed"]]
        self.assertEqual(passed_ids, ["ga-valid-exact", "ga-valid-ws", "ga-reject-changed"])

        dropped = {item["id"]: item["reason"] for item in data["dropped"]}
        self.assertIn("ga-paraphrased", dropped)
        self.assertIn("verbatim", dropped["ga-paraphrased"].lower())
        self.assertIn("ga-missing-end", dropped)
        self.assertIn("missing", dropped["ga-missing-end"].lower())
        self.assertIn("ga-closed-issue", dropped)
        self.assertIn("closed", dropped["ga-closed-issue"].lower())
        self.assertIn("ga-already-linked", dropped)
        self.assertIn("already linked", dropped["ga-already-linked"].lower())
        self.assertIn("ga-repeat-reject", dropped)
        self.assertIn("reject", dropped["ga-repeat-reject"].lower())
        self.assertIn("ga-empty-changes", dropped)
        self.assertIn("changes", dropped["ga-empty-changes"].lower())

    def test_score_formula_ties_drop_zero_and_rejects_null_changes_confirmed(self):
        code, data, err = _run(
            "score",
            str(FIXTURES / "score_links.jsonl"),
            "--verdicts", str(FIXTURES / "score_verdicts.jsonl"),
        )
        self.assertEqual(code, 0, err)
        self.assertIsNotNone(data)

        scored = data["scored"]
        scored_ids = [item["id"] for item in scored]
        self.assertEqual(scored_ids, ["sc-promise", "sc-tie-newer", "sc-tie-older", "sc-info"])
        scores = {item["id"]: item["score"] for item in scored}
        self.assertEqual(scores["sc-promise"], 18)
        self.assertEqual(scores["sc-tie-newer"], 8)
        self.assertEqual(scores["sc-tie-older"], 8)
        self.assertEqual(scores["sc-info"], 1)

        dropped = {item["id"]: item["reason"] for item in data["dropped"]}
        self.assertIn("sc-zero-impact", dropped)
        self.assertIn("sc-null-changes-confirmed", dropped)
        self.assertIn("changes_confirmed", dropped["sc-null-changes-confirmed"])

    def test_ledger_append_recheck_expiry_and_canaries(self):
        ledger_path = self.tmp / "ledger.jsonl"
        shutil.copy(FIXTURES / "ledger_seed.jsonl", ledger_path)
        initial_lines = ledger_path.read_text(encoding="utf-8").splitlines()

        code, data, err = _run(
            "ledger",
            "--ledger", str(ledger_path),
            "--settings", str(FIXTURES / "settings.json"),
            "--recheck",
            "--date", "2030-01-15",
        )
        self.assertEqual(code, 0, err)
        self.assertIsNotNone(data)
        self.assertEqual(data["unconfirmed"], [])
        self.assertEqual(data["kept"], ["led-keep-001"])

        expired = {item["id"]: item["reason"] for item in data["expired"]}
        self.assertEqual(set(expired), {"led-missing-end-001", "led-changed-quote-001", "led-uncited-001"})
        self.assertIn("30", expired["led-uncited-001"])

        final_lines = ledger_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(final_lines[:len(initial_lines)], initial_lines)
        self.assertEqual(len(final_lines), len(initial_lines) + 6)
        for line in final_lines:
            record = parse_json_strict(line)
            validate(self.schema, {"$ref": "#/$defs/ledger_entry"}, record)

        code_c, canaries, err_c = _run(
            "canaries",
            "--ledger", str(ledger_path),
            "--true-count", "2",
            "--junk-count", "2",
            "--seed", "2030-01-15",
        )
        self.assertEqual(code_c, 0, err_c)
        self.assertEqual([c["id"] for c in canaries["known_true"]], ["led-keep-001"])
        self.assertEqual(canaries["known_true"][0]["expected_verdict"], "CONFIRMED")
        self.assertEqual(len(canaries["known_junk"]), 2)
        self.assertTrue(all(c["expected_verdict"] == "REJECTED" for c in canaries["known_junk"]))

    def test_unread_repository_is_reported_unconfirmed_never_zero(self):
        org = self._copy_fixture_org()
        settings_path = org / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        settings["repos"].append({"name": "example/missing", "path": "org/does-not-exist"})
        settings_path.write_text(json.dumps(settings), encoding="utf-8")

        code, data, err = _run("candidates", "--settings", str(settings_path), "--date", "2030-01-15")
        self.assertEqual(code, 2, err)
        self.assertIsNotNone(data)
        sources = [item["source"] for item in data["unconfirmed"]]
        self.assertIn("example/missing", sources)

        ledger_path = self.tmp / "unconfirmed_ledger.jsonl"
        ledger_path.write_text(
            json.dumps({
                "id": "led-unread-001",
                "state": "accepted",
                "link_type": "says-vs-does",
                "ends": [
                    {"ref": "example/missing:README.md#L1", "quote": "Claim", "seen": "2030-01-14"},
                    {"ref": "example/alpha:README.md#L4", "quote": "Offline mode is not supported yet.", "seen": "2030-01-14"},
                ],
                "changes": "Fix claim.",
                "owner": "product",
                "valid_from": "2030-01-14",
                "invalid_at": None,
                "reason": "",
                "superseded_by": None,
                "last_cited": "2030-01-14",
            }) + "\n",
            encoding="utf-8",
        )
        code_l, data_l, err_l = _run(
            "ledger", "--ledger", str(ledger_path), "--settings", str(settings_path), "--recheck", "--date", "2030-01-15"
        )
        self.assertEqual(code_l, 2, err_l)
        self.assertEqual(data_l["expired"], [])
        self.assertEqual(data_l["kept"], ["led-unread-001"])
        self.assertIn("example/missing", [u["source"] for u in data_l["unconfirmed"]])

    def test_ledger_append_validates_schema_and_blocks_null_changes_confirmed(self):
        ledger_path = self.tmp / "append_ledger.jsonl"
        transitions = self.tmp / "transitions.jsonl"
        transitions.write_text(
            "\n".join([
                json.dumps({
                    "id": "led-new-001",
                    "state": "proposed",
                    "link_type": "says-vs-does",
                    "ends": [
                        {"ref": "example/notes:scoreboard.md#L7", "quote": "Supported fully", "seen": "2030-01-14"},
                        {"ref": "example/alpha:README.md#L4", "quote": "Offline mode is not supported yet.", "seen": "2030-01-14"},
                    ],
                    "changes": "Fix scoreboard row.",
                    "owner": "product",
                    "reason": "",
                    "superseded_by": None,
                    "last_cited": None,
                }),
                json.dumps({
                    "id": "led-bad-verdict",
                    "state": "accepted",
                    "link_type": "says-vs-does",
                    "ends": [
                        {"ref": "example/notes:scoreboard.md#L7", "quote": "Supported fully", "seen": "2030-01-14"},
                        {"ref": "example/alpha:README.md#L4", "quote": "Offline mode is not supported yet.", "seen": "2030-01-14"},
                    ],
                    "changes": "Fix scoreboard row.",
                    "owner": "product",
                    "reason": "",
                    "superseded_by": None,
                    "last_cited": "2030-01-15",
                }),
            ]) + "\n",
            encoding="utf-8",
        )
        verdicts = self.tmp / "verdicts.jsonl"
        verdicts.write_text(
            json.dumps({
                "id": "led-bad-verdict",
                "verdict": "CONFIRMED",
                "reason": "Missing changes_confirmed.",
                "evidence": ["grep -F Offline README.md -> 1 match"],
                "blind": True,
                "changes_confirmed": None,
            }) + "\n",
            encoding="utf-8",
        )

        code, data, err = _run(
            "ledger",
            "--ledger", str(ledger_path),
            "--append", str(transitions),
            "--verdicts", str(verdicts),
            "--date", "2030-01-15",
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(data["appended"], 1)
        self.assertEqual(len(data["rejected_verdicts"]), 1)
        self.assertEqual(data["rejected_verdicts"][0]["id"], "led-bad-verdict")

        lines = ledger_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        rec = parse_json_strict(lines[0])
        validate(self.schema, {"$ref": "#/$defs/ledger_entry"}, rec)
        self.assertEqual(rec["id"], "led-new-001")


if __name__ == "__main__":
    unittest.main(verbosity=2)
