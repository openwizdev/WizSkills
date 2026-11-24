#!/usr/bin/env python3
"""Merge findings and render dream-cycle reports (stub; implemented by DC3 #3091)."""
import argparse
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="dream.py",
        description="Merge dream-cycle findings and render reports (DC3 stub).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    merge_p = sub.add_parser("merge", help="Validate, dedupe, rank findings and split prover batches.")
    merge_p.add_argument("findings_dir", help="Directory containing scout *.jsonl findings files.")
    merge_p.add_argument("--out", required=True, help="Output path for merged findings JSON.")
    merge_p.add_argument("--batches-dir", required=True, help="Output directory for prover batch JSONL files.")
    merge_p.add_argument("--batches", type=int, default=4, help="Number of prover batches (default: 4).")

    report_p = sub.add_parser("report", help="Apply prover verdicts and render the dated private report.")
    report_p.add_argument("merged_file", help="Path to merged findings JSON.")
    report_p.add_argument("verdicts_dir", help="Directory containing prover *.jsonl verdict files.")
    report_p.add_argument("--date", required=True, help="Report date (YYYY-MM-DD).")
    report_p.add_argument("--out", required=True, help="Output path for the rendered Markdown report.")
    report_p.add_argument("--tickets-out", required=True, help="Output path for the CONFIRMED ticket list JSON.")
    report_p.add_argument("--days", type=int, default=14, help="Staleness window N days (default: 14).")
    report_p.add_argument("--scope", default="", help="Comma-separated repositories and areas (e.g. Loops).")
    report_p.add_argument("--unconfirmed", help="Optional JSON file listing unconfirmed reads.")

    parser.parse_args(argv)
    print("dream.py: not implemented (DC3 #3091)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
