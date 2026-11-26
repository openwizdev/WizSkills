#!/usr/bin/env python3
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FEEDBACK = HERE.parent / "feedback.py"
LOOPS = 200


def load_fixtures():
    sys.path.insert(0, str(HERE))
    import test_public_records as records
    return records.BRIEF_BODY, records.APPROVAL


def brief(body, approval, **extra):
    base = {
        "number": 9200, "author": "synthetic-owner", "body": body,
        "labels": ["ready-for-agent"], "milestone": "9.4.2",
        "comments": [{"author": "synthetic-owner", "body": approval}],
    }
    base.update(extra)
    return {"report": 9101, "version": "9.4.2",
            "record_authors": ["openwiz[bot]", "Synthetic-Owner"], "brief": base}


def cases(body, approval):
    fresh = {"last_edited_at": "2026-11-01T09:00:00Z",
             "ready_labelled": [{"at": "2026-11-01T09:00:01Z", "by": "synthetic-owner"}]}
    stale = {"last_edited_at": "2026-11-01T09:00:00Z",
             "ready_labelled": [{"at": "2026-11-01T09:00:00Z", "by": "synthetic-owner"}]}
    return (
        ("six-field complete", brief(body, approval), 0),
        ("six-field without the ready label", brief(body, approval, labels=[]), 1),
        ("only last_edited_at", brief(body, approval, last_edited_at="2026-11-01T09:00:00Z"), 2),
        ("only ready_labelled", brief(body, approval, ready_labelled=fresh["ready_labelled"]), 2),
        ("both fields, label after the edit", brief(body, approval, **fresh), 0),
        ("both fields, label not after the edit", brief(body, approval, **stale), 1),
        ("both fields, ready_labelled not a list",
         brief(body, approval, last_edited_at="2026-11-01T09:00:00Z", ready_labelled="nope"), 2),
    )


def verify(payload, script):
    raw = json.dumps(payload)
    started = time.perf_counter()
    run = subprocess.run([sys.executable, "-I", str(script), "verify", "-"], input=raw,
                         capture_output=True, text=True)
    return run.returncode, (time.perf_counter() - started) * 1e6


def score(script):
    body, approval = load_fixtures()
    rows = []
    for name, payload, want in cases(body, approval):
        got, usec = verify(payload, script)
        rows.append({"name": name, "want": want, "got": got, "us": round(usec, 1), "ok": got == want})
    passed = sum(row["ok"] for row in rows)
    return {"script": str(script), "passed": passed, "total": len(rows), "cases": rows}


def bench(script):
    result = score(script)
    body, approval = load_fixtures()
    payload = cases(body, approval)[0][1]
    sample = [verify(payload, script)[1] for _ in range(LOOPS)]
    result["loops"] = LOOPS
    result["median_us"] = round(statistics.median(sample), 1)
    result["p95_us"] = round(sorted(sample)[int(0.95 * (len(sample) - 1))], 1)
    return result


def main():
    script = Path(sys.argv[1]) if len(sys.argv) > 1 else FEEDBACK
    result = bench(script)
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["passed"] == result["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
