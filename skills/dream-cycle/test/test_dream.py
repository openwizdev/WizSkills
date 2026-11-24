#!/usr/bin/env python3
"""Merge and report command tests against fixture findings (P3; red against DC1 stub)."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "dream.py"
FIXTURES = HERE / "fixtures" / "dream"


class DreamCycleMergeAndReportTests(unittest.TestCase):
    # DC3 (#3091) removes expectedFailure when dream.py is implemented.
    @unittest.expectedFailure
    def test_merge_validates_dedupes_ranks_and_splits_batches(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            merged_file = out_dir / "merged.json"
            batches_dir = out_dir / "batches"

            proc = subprocess.run(
                [
                    sys.executable, "-I", str(SCRIPT),
                    "merge", str(FIXTURES / "findings"),
                    "--out", str(merged_file),
                    "--batches-dir", str(batches_dir),
                    "--batches", "2",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            merged = json.loads(merged_file.read_text(encoding="utf-8"))
            self.assertEqual(merged["schema"], "openwiz.dream-cycle.merged.v1")
            # 1 invalid line (alpha-bad) dropped with file, line and reason.
            self.assertEqual(len(merged["dropped"]), 1)
            dropped = merged["dropped"][0]
            self.assertIn("scout_alpha.jsonl", dropped["file"])
            self.assertEqual(dropped["line"], 3)
            self.assertTrue(dropped["reason"])

            # alpha-001 and alpha-001-dup share (example/alpha, [src/legacy_export.py])
            # so 6 valid lines dedupe to 5 merged findings.
            self.assertEqual(len(merged["findings"]), 5)
            deduped = [f for f in merged["findings"] if f["paths"] == ["src/legacy_export.py"]]
            self.assertEqual(len(deduped), 1)
            self.assertEqual(sorted(deduped[0]["merged_ids"]), ["alpha-001", "alpha-001-dup"])
            self.assertEqual(len(deduped[0]["evidence"]), 2)
            self.assertEqual(deduped[0]["confidence"], "high")

            batch_files = sorted(batches_dir.glob("batch-*.jsonl"))
            self.assertEqual(len(batch_files), 2)
            batch_counts = [
                len([l for l in bf.read_text(encoding="utf-8").splitlines() if l.strip()])
                for bf in batch_files
            ]
            self.assertEqual(sum(batch_counts), 5)
            self.assertLessEqual(max(batch_counts) - min(batch_counts), 1)

    # DC3 (#3091) removes expectedFailure when dream.py is implemented.
    @unittest.expectedFailure
    def test_report_applies_verdicts_excludes_unproven_tickets_and_renders_loops(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            merged_file = out_dir / "merged.json"
            batches_dir = out_dir / "batches"
            report_md = out_dir / "report.md"
            tickets_json = out_dir / "tickets.json"

            merge_proc = subprocess.run(
                [
                    sys.executable, "-I", str(SCRIPT),
                    "merge", str(FIXTURES / "findings"),
                    "--out", str(merged_file),
                    "--batches-dir", str(batches_dir),
                    "--batches", "2",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(merge_proc.returncode, 0, merge_proc.stderr)

            report_proc = subprocess.run(
                [
                    sys.executable, "-I", str(SCRIPT),
                    "report", str(merged_file), str(FIXTURES / "verdicts"),
                    "--date", "2030-01-15",
                    "--days", "14",
                    "--scope", "example/alpha, example/beta, Loops",
                    "--unconfirmed", str(FIXTURES / "unconfirmed.json"),
                    "--out", str(report_md),
                    "--tickets-out", str(tickets_json),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(report_proc.returncode, 0, report_proc.stderr)

            report = report_md.read_text(encoding="utf-8")
            for heading in (
                "# Dream cycle report — 2030-01-15",
                "## Areas",
                "## Top deletes",
                "## Top fixes",
                "## Top links",
                "## Rejected",
                "## Unconfirmed reads",
                "## Tickets filed",
            ):
                self.assertIn(heading, report)
            self.assertIn("Loops", report)
            self.assertIn("Flag --fast is parsed dynamically", report)
            self.assertIn("idle_prs", report)

            tickets = json.loads(tickets_json.read_text(encoding="utf-8"))
            ticket_ids = {t["id"] for t in tickets}
            # Only CONFIRMED findings with a ticket title enter tickets.json.
            self.assertEqual(ticket_ids, {"alpha-001-dup", "loops-001"})
            # Unproven (alpha-unproven), PLAUSIBLE (cross-001), REJECTED (alpha-002) never ticketed.
            self.assertNotIn("alpha-unproven", ticket_ids)
            self.assertNotIn("cross-001", ticket_ids)
            self.assertNotIn("alpha-002", ticket_ids)


if __name__ == "__main__":
    unittest.main(verbosity=2)
