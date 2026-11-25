#!/usr/bin/env python3
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "dream.py"
FIXTURES = HERE / "fixtures" / "dream"


def _make_link(
    fid,
    *,
    link_type="duplicates",
    owner="platform",
    route="ticket",
    ticket="Fix linked item",
    sources=2,
    confidence="high",
    ends=None,
    changes="Update open ticket example/beta#41.",
    why_keep="Might be intentional separation.",
):
    if ends is None:
        ends = [
            {"ref": f"example/alpha:src/{fid}.py#L1", "quote": f"def {fid}_a():", "seen": "2030-01-14"},
            {"ref": f"example/beta:src/{fid}.py#L1", "quote": f"def {fid}_b():", "seen": "2030-01-14"},
        ]
    return {
        "id": fid,
        "kind": "link",
        "repo": "example/beta",
        "paths": [f"src/{fid}.py"],
        "what": f"Link finding {fid}.",
        "evidence": [f"grep -F {fid} src/{fid}.py -> 1 match"],
        "why_keep": why_keep,
        "confidence": confidence,
        "size": "S",
        "ticket": ticket if route == "ticket" else None,
        "link_type": link_type,
        "ends": ends,
        "changes": changes,
        "sources": sources,
        "owner": owner,
        "route": route,
    }


def _make_verdict(fid, verdict="CONFIRMED", reason="Verified both ends.", blind=True, changes_confirmed=True):
    return {
        "id": fid,
        "verdict": verdict,
        "reason": reason,
        "evidence": [f"grep -F {fid} -> 1 match"],
        "blind": blind,
        "changes_confirmed": changes_confirmed,
    }


class DreamCycleMergeAndReportTests(unittest.TestCase):
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "-I", str(SCRIPT), *args],
            capture_output=True,
            text=True,
        )

    def test_merge_validates_dedupes_ranks_and_splits_batches(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            merged_file = out_dir / "merged.json"
            batches_dir = out_dir / "batches"

            proc = self._run(
                "merge", str(FIXTURES / "findings"),
                "--out", str(merged_file),
                "--batches-dir", str(batches_dir),
                "--batches", "2",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            merged = json.loads(merged_file.read_text(encoding="utf-8"))
            self.assertEqual(merged["schema"], "openwiz.dream-cycle.merged.v1")
            self.assertEqual(len(merged["dropped"]), 1)
            dropped = merged["dropped"][0]
            self.assertIn("scout_alpha.jsonl", dropped["file"])
            self.assertEqual(dropped["line"], 3)
            self.assertTrue(dropped["reason"])

            self.assertEqual(len(merged["findings"]), 5)
            self.assertEqual(merged["counts"], {"input": 7, "valid": 6, "dropped": 1, "merged": 5})
            deduped = [f for f in merged["findings"] if f["paths"] == ["src/legacy_export.py"]]
            self.assertEqual(len(deduped), 1)
            self.assertEqual(sorted(deduped[0]["merged_ids"]), ["alpha-001", "alpha-001-dup"])
            self.assertEqual(len(deduped[0]["evidence"]), 2)
            self.assertEqual(deduped[0]["confidence"], "high")

            # Deterministic ranking: delete before fix before link, high before medium
            kinds = [f["kind"] for f in merged["findings"]]
            self.assertEqual(kinds, ["delete", "delete", "fix", "fix", "link"])

            batch_files = sorted(batches_dir.glob("batch-*.jsonl"))
            self.assertEqual(len(batch_files), 2)
            batch_counts = [
                len([l for l in bf.read_text(encoding="utf-8").splitlines() if l.strip()])
                for bf in batch_files
            ]
            self.assertEqual(sum(batch_counts), 5)
            self.assertLessEqual(max(batch_counts) - min(batch_counts), 1)

    def test_report_applies_verdicts_excludes_unproven_tickets_and_renders_loops(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            merged_file = out_dir / "merged.json"
            batches_dir = out_dir / "batches"
            report_md = out_dir / "report.md"
            tickets_json = out_dir / "tickets.json"

            merge_proc = self._run(
                "merge", str(FIXTURES / "findings"),
                "--out", str(merged_file),
                "--batches-dir", str(batches_dir),
                "--batches", "2",
            )
            self.assertEqual(merge_proc.returncode, 0, merge_proc.stderr)

            report_proc = self._run(
                "report", str(merged_file), str(FIXTURES / "verdicts"),
                "--date", "2030-01-15",
                "--days", "14",
                "--scope", "example/alpha, example/beta, Loops",
                "--unconfirmed", str(FIXTURES / "unconfirmed.json"),
                "--out", str(report_md),
                "--tickets-out", str(tickets_json),
            )
            self.assertEqual(report_proc.returncode, 0, report_proc.stderr)

            report = report_md.read_text(encoding="utf-8")
            headings = (
                "# Dream cycle report — 2030-01-15",
                "## Areas",
                "## Top deletes",
                "## Top fixes",
                "## Top links",
                "## Rejected",
                "## Unconfirmed reads",
                "## Tickets filed",
            )
            positions = []
            for heading in headings:
                pos = report.find(heading)
                self.assertNotEqual(pos, -1, f"missing heading {heading!r}")
                positions.append(pos)
            self.assertEqual(positions, sorted(positions), "sections out of contract order")
            self.assertIn("Loops", report)
            self.assertIn("Flag --fast is parsed dynamically", report)
            self.assertIn("idle_prs", report)
            # Link card fields for cross-001
            self.assertIn("**`cross-001`** (`duplicates`, `PLAUSIBLE`, score ", report)
            self.assertIn("- **End 1:** `example/alpha:src/slug.py#L1-L20` (2030-01-14)", report)
            self.assertIn("- **Changes:** Open ticket example/beta#41", report)
            self.assertIn("- **Best reason not a link:** Repos currently avoid", report)

            tickets = json.loads(tickets_json.read_text(encoding="utf-8"))
            ticket_ids = {t["id"] for t in tickets}
            self.assertEqual(ticket_ids, {"alpha-001-dup", "loops-001"})
            self.assertNotIn("alpha-unproven", ticket_ids)
            self.assertNotIn("cross-001", ticket_ids)
            self.assertNotIn("alpha-002", ticket_ids)

    def test_merge_drops_duplicate_keys_and_invalid_link_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            fdir = out_dir / "findings"
            fdir.mkdir()
            valid = _make_link("link-ok-01")
            missing_changes = _make_link("link-bad-changes")
            del missing_changes["changes"]
            pattern_two_ends = _make_link("link-bad-pattern", link_type="pattern")
            ticket_route_null = _make_link("link-bad-ticket", route="ticket")
            ticket_route_null["ticket"] = None
            non_ticket_with_title = _make_link("link-bad-inbox", route="pillar-inbox")
            non_ticket_with_title["ticket"] = "Should be null"
            dup_key_raw = '{"id": "dup-k", "id": "dup-k2", "kind": "summary", "repo": "a/b", "paths": [], "what": "x", "evidence": ["cmd -> ok"], "why_keep": "", "confidence": "low", "size": "S", "ticket": null}'

            (fdir / "scout_links.jsonl").write_text(
                "\n".join([
                    json.dumps(valid),
                    json.dumps(missing_changes),
                    json.dumps(pattern_two_ends),
                    json.dumps(ticket_route_null),
                    json.dumps(non_ticket_with_title),
                    dup_key_raw,
                ]) + "\n",
                encoding="utf-8",
            )
            merged_file = out_dir / "merged.json"
            batches_dir = out_dir / "batches"
            proc = self._run(
                "merge", str(fdir),
                "--out", str(merged_file),
                "--batches-dir", str(batches_dir),
                "--batches", "1",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            merged = json.loads(merged_file.read_text(encoding="utf-8"))
            self.assertEqual(merged["counts"], {"input": 6, "valid": 1, "dropped": 5, "merged": 1})
            self.assertEqual([f["id"] for f in merged["findings"]], ["link-ok-01"])
            self.assertEqual([d["line"] for d in merged["dropped"]], [2, 3, 4, 5, 6])

    def test_report_rejects_confirmed_link_verdict_with_null_changes_confirmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            fdir = out_dir / "findings"
            vdir = out_dir / "verdicts"
            fdir.mkdir()
            vdir.mkdir()

            link_null = _make_link("link-null-cc", route="ticket", ticket="Should not be ticketed")
            link_ok = _make_link("link-true-cc", route="ticket", ticket="Confirmed link ticket")
            (fdir / "s.jsonl").write_text(
                json.dumps(link_null) + "\n" + json.dumps(link_ok) + "\n",
                encoding="utf-8",
            )
            (vdir / "v.jsonl").write_text(
                json.dumps(_make_verdict("link-null-cc", "CONFIRMED", changes_confirmed=None)) + "\n"
                + json.dumps(_make_verdict("link-true-cc", "CONFIRMED", changes_confirmed=True)) + "\n",
                encoding="utf-8",
            )

            merged_file = out_dir / "merged.json"
            report_md = out_dir / "report.md"
            tickets_json = out_dir / "tickets.json"
            self.assertEqual(
                self._run("merge", str(fdir), "--out", str(merged_file), "--batches-dir", str(out_dir / "b"), "--batches", "1").returncode,
                0,
            )
            proc = self._run(
                "report", str(merged_file), str(vdir),
                "--date", "2030-01-15",
                "--out", str(report_md),
                "--tickets-out", str(tickets_json),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            tickets = json.loads(tickets_json.read_text(encoding="utf-8"))
            self.assertEqual([t["id"] for t in tickets], ["link-true-cc"])
            report = report_md.read_text(encoding="utf-8")
            self.assertIn("link-null-cc", report)
            self.assertIn("changes_confirmed", report)
            self.assertNotIn("**`link-null-cc`** (`duplicates`, `CONFIRMED`", report)

    def test_report_caps_link_cards_at_15_and_ranks_by_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            fdir = out_dir / "findings"
            vdir = out_dir / "verdicts"
            fdir.mkdir()
            vdir.mkdir()

            links = []
            verdicts = []
            scores = {}
            for i in range(1, 18):
                fid = f"lnk-{i:02d}"
                if i == 17:
                    ends = [
                        {"ref": "a:f1#L1", "quote": "q1", "seen": "2030-01-14"},
                        {"ref": "b:f2#L1", "quote": "q2", "seen": "2030-01-14"},
                        {"ref": "c:f3#L1", "quote": "q3", "seen": "2030-01-14"},
                    ]
                    links.append(_make_link(fid, link_type="pattern", route="spec-candidate", sources=3, ends=ends))
                else:
                    links.append(_make_link(fid, route="ticket", ticket=f"Ticket {fid}"))
                verdicts.append(_make_verdict(fid, "CONFIRMED", changes_confirmed=True))
                scores[fid] = i * 2  # lnk-17 has highest score (34), lnk-01 lowest (2)

            (fdir / "s.jsonl").write_text("\n".join(json.dumps(x) for x in links) + "\n", encoding="utf-8")
            (vdir / "v.jsonl").write_text("\n".join(json.dumps(x) for x in verdicts) + "\n", encoding="utf-8")
            scores_file = out_dir / "scores.json"
            scores_file.write_text(json.dumps(scores), encoding="utf-8")

            merged_file = out_dir / "merged.json"
            report_md = out_dir / "report.md"
            tickets_json = out_dir / "tickets.json"
            self.assertEqual(
                self._run("merge", str(fdir), "--out", str(merged_file), "--batches-dir", str(out_dir / "b"), "--batches", "2").returncode,
                0,
            )
            proc = self._run(
                "report", str(merged_file), str(vdir),
                "--date", "2030-01-15",
                "--link-scores", str(scores_file),
                "--out", str(report_md),
                "--tickets-out", str(tickets_json),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            report = report_md.read_text(encoding="utf-8")
            top_links_section = report.split("## Top links")[1].split("## Rejected")[0]
            # Top card must be lnk-17 (score 34, pattern with 3 ends)
            self.assertIn("1. **`lnk-17`** (`pattern`, `CONFIRMED`, score 34", top_links_section)
            self.assertIn("- **End 3:** `c:f3#L1` (2030-01-14)", top_links_section)
            # 15th card must be lnk-03 (score 6); lnk-02 and lnk-01 must NOT render as cards
            self.assertIn("15. **`lnk-03`**", top_links_section)
            self.assertNotIn("16. **`lnk-02`**", top_links_section)
            self.assertNotIn("**`lnk-01`**", top_links_section)

    def test_report_routes_links_inboxes_controller_rejected_and_expired(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            fdir = out_dir / "findings"
            vdir = out_dir / "verdicts"
            inboxes_dir = out_dir / "inboxes"
            routes_json = out_dir / "routes.json"
            fdir.mkdir()
            vdir.mkdir()

            items = [
                _make_link("r-ticket", route="ticket", owner="platform", ticket="File this link ticket"),
                _make_link("r-inbox", route="pillar-inbox", owner="strategy"),
                _make_link("r-people", route="people-draft", owner="people/ops"),
                _make_link("r-question", route="question-comment", owner="delivery"),
                _make_link("r-spec", route="spec-candidate", owner="platform"),
                _make_link("r-rej-1", route="ticket", owner="platform", ticket="Rejected one"),
                _make_link("r-rej-2", route="ticket", owner="platform", ticket="Rejected two"),
            ]
            verdicts = [
                _make_verdict("r-ticket", "CONFIRMED", changes_confirmed=True),
                _make_verdict("r-inbox", "CONFIRMED", changes_confirmed=True),
                _make_verdict("r-people", "PLAUSIBLE", changes_confirmed=True),
                _make_verdict("r-question", "CONFIRMED", changes_confirmed=True),
                _make_verdict("r-spec", "PLAUSIBLE", changes_confirmed=True),
                _make_verdict("r-rej-1", "REJECTED", reason="Merely similar topics", changes_confirmed=False),
                _make_verdict("r-rej-2", "REJECTED", reason="Merely similar topics", changes_confirmed=False),
            ]
            (fdir / "s.jsonl").write_text("\n".join(json.dumps(x) for x in items) + "\n", encoding="utf-8")
            (vdir / "v.jsonl").write_text("\n".join(json.dumps(x) for x in verdicts) + "\n", encoding="utf-8")

            ledger_file = out_dir / "ledger.jsonl"
            ledger_entry = {
                "id": "old-link-01",
                "state": "expired",
                "link_type": "says-vs-does",
                "ends": [
                    {"ref": "a:README.md#L1", "quote": "old claim", "seen": "2029-12-01"},
                    {"ref": "a:src/app.py#L1", "quote": "old code", "seen": "2029-12-01"},
                ],
                "changes": "Old claim changed.",
                "owner": "product",
                "valid_from": "2030-01-15",
                "invalid_at": None,
                "reason": "Uncited for 30 days.",
                "superseded_by": None,
                "last_cited": "2029-12-10",
            }
            ledger_file.write_text(json.dumps(ledger_entry) + "\n", encoding="utf-8")

            merged_file = out_dir / "merged.json"
            report_md = out_dir / "report.md"
            tickets_json = out_dir / "tickets.json"
            self.assertEqual(
                self._run("merge", str(fdir), "--out", str(merged_file), "--batches-dir", str(out_dir / "b"), "--batches", "1").returncode,
                0,
            )
            proc = self._run(
                "report", str(merged_file), str(vdir),
                "--date", "2030-01-15",
                "--ledger", str(ledger_file),
                "--inboxes-dir", str(inboxes_dir),
                "--routes-out", str(routes_json),
                "--out", str(report_md),
                "--tickets-out", str(tickets_json),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

            # Ticket route only
            tickets = json.loads(tickets_json.read_text(encoding="utf-8"))
            self.assertEqual([t["id"] for t in tickets], ["r-ticket"])

            # One inbox file per owner in private run folder, sanitized filename
            inbox_files = sorted(p.name for p in inboxes_dir.glob("*.md"))
            self.assertEqual(inbox_files, ["people-ops.md", "strategy.md"])
            self.assertIn("r-inbox", (inboxes_dir / "strategy.md").read_text(encoding="utf-8"))
            people_text = (inboxes_dir / "people-ops.md").read_text(encoding="utf-8")
            self.assertIn("r-people", people_text)
            self.assertIn("DRAFT ONLY", people_text)

            # Controller routes listed in report and JSON
            routes = json.loads(routes_json.read_text(encoding="utf-8"))
            self.assertEqual([r["id"] for r in routes["question-comment"]], ["r-question"])
            self.assertEqual([r["id"] for r in routes["spec-candidate"]], ["r-spec"])

            report = report_md.read_text(encoding="utf-8")
            self.assertIn("### Rejected links by reason", report)
            self.assertIn("- Merely similar topics: 2", report)
            self.assertIn("### Expired links", report)
            self.assertIn("**`old-link-01`**", report)
            self.assertIn("Uncited for 30 days.", report)
            self.assertIn("### Controller link routes", report)
            self.assertIn("r-question", report)
            self.assertIn("r-spec", report)

    def test_report_canary_miss_warns_at_top_and_caps_links_at_plausible(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            fdir = out_dir / "findings"
            vdir = out_dir / "verdicts"
            fdir.mkdir()
            vdir.mkdir()

            del_finding = {
                "id": "del-001",
                "kind": "delete",
                "repo": "example/alpha",
                "paths": ["src/dead.py"],
                "what": "Dead file.",
                "evidence": ["git grep dead -> 0 matches"],
                "why_keep": "Could be imported dynamically.",
                "confidence": "high",
                "size": "S",
                "ticket": "Delete src/dead.py",
            }
            lnk_finding = _make_link("lnk-good", route="ticket", ticket="Link ticket should be capped")
            canary_junk = _make_link("canary-junk-01", route="ticket", ticket="Canary junk")

            (fdir / "s.jsonl").write_text(
                "\n".join(json.dumps(x) for x in (del_finding, lnk_finding, canary_junk)) + "\n",
                encoding="utf-8",
            )
            # Prover wrongly CONFIRMED the junk canary!
            (vdir / "v.jsonl").write_text(
                "\n".join(json.dumps(x) for x in (
                    _make_verdict("del-001", "CONFIRMED", blind=False, changes_confirmed=None),
                    _make_verdict("lnk-good", "CONFIRMED", blind=True, changes_confirmed=True),
                    _make_verdict("canary-junk-01", "CONFIRMED", blind=True, changes_confirmed=True),
                )) + "\n",
                encoding="utf-8",
            )
            canaries_file = out_dir / "canaries.json"
            canaries_file.write_text(
                json.dumps([{"id": "canary-junk-01", "expected": "REJECTED"}]),
                encoding="utf-8",
            )

            merged_file = out_dir / "merged.json"
            report_md = out_dir / "report.md"
            tickets_json = out_dir / "tickets.json"
            self.assertEqual(
                self._run("merge", str(fdir), "--out", str(merged_file), "--batches-dir", str(out_dir / "b"), "--batches", "1").returncode,
                0,
            )
            proc = self._run(
                "report", str(merged_file), str(vdir),
                "--date", "2030-01-15",
                "--canaries", str(canaries_file),
                "--out", str(report_md),
                "--tickets-out", str(tickets_json),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

            report = report_md.read_text(encoding="utf-8")
            # Warning near top of report (before ## Areas)
            top = report.split("## Areas")[0]
            self.assertIn("canary", top.lower())
            self.assertIn("PLAUSIBLE", top)
            # lnk-good is capped at PLAUSIBLE and NOT in tickets
            self.assertIn("**`lnk-good`** (`duplicates`, `PLAUSIBLE`", report)
            self.assertNotIn("**`lnk-good`** (`duplicates`, `CONFIRMED`", report)
            tickets = json.loads(tickets_json.read_text(encoding="utf-8"))
            self.assertEqual([t["id"] for t in tickets], ["del-001"])

    def test_report_second_check_most_conservative_verdict_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            fdir = out_dir / "findings"
            vdir = out_dir / "verdicts"
            fdir.mkdir()
            vdir.mkdir()

            lnk = _make_link("lnk-recheck", route="ticket", ticket="Should not be filed after reject")
            (fdir / "s.jsonl").write_text(json.dumps(lnk) + "\n", encoding="utf-8")
            # Earlier file REJECTED, later file CONFIRMED -> REJECTED must win
            (vdir / "batch_01.jsonl").write_text(
                json.dumps(_make_verdict("lnk-recheck", "REJECTED", reason="Second check rejected", changes_confirmed=False)) + "\n",
                encoding="utf-8",
            )
            (vdir / "batch_02.jsonl").write_text(
                json.dumps(_make_verdict("lnk-recheck", "CONFIRMED", reason="First check confirmed", changes_confirmed=True)) + "\n",
                encoding="utf-8",
            )

            merged_file = out_dir / "merged.json"
            report_md = out_dir / "report.md"
            tickets_json = out_dir / "tickets.json"
            self.assertEqual(
                self._run("merge", str(fdir), "--out", str(merged_file), "--batches-dir", str(out_dir / "b"), "--batches", "1").returncode,
                0,
            )
            proc = self._run(
                "report", str(merged_file), str(vdir),
                "--date", "2030-01-15",
                "--out", str(report_md),
                "--tickets-out", str(tickets_json),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(tickets_json.read_text(encoding="utf-8")), [])
            report = report_md.read_text(encoding="utf-8")
            self.assertIn("Second check rejected", report)
            self.assertIn("- Second check rejected: 1", report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
