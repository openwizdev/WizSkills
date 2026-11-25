#!/usr/bin/env python3
import argparse
from collections import Counter, defaultdict
from datetime import date
import json
from pathlib import Path
import re
import sys

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
LINE_RE = re.compile(r"^[^\x00-\x1f\x7f]+$")
LINE_OR_EMPTY_RE = re.compile(r"^[^\x00-\x1f\x7f]*$")
EVIDENCE_RE = re.compile(r"^[^\x00-\x1f\x7f]+ -> [^\x00-\x1f\x7f]+$")
ISO_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
LINK_REF_RE = re.compile(r"^[^\s\x00-\x1f\x7f]+$")

KINDS = ("delete", "fix", "link", "summary")
KIND_RANK = {k: i for i, k in enumerate(KINDS)}
CONFIDENCES = ("high", "medium", "low")
CONFIDENCE_RANK = {c: i for i, c in enumerate(CONFIDENCES)}
CONFIDENCE_WEIGHT = {"high": 3, "medium": 2, "low": 1}
SIZES = ("S", "M", "L")
SIZE_RANK = {s: i for i, s in enumerate(SIZES)}
VERDICTS = ("CONFIRMED", "PLAUSIBLE", "REJECTED")
VERDICT_RANK = {"CONFIRMED": 0, "PLAUSIBLE": 1, "REJECTED": 2}

LINK_TYPES = frozenset({
    "says-vs-does",
    "promise-to-work",
    "need-to-person",
    "enemy-move-to-us",
    "spend-to-use",
    "answers",
    "pattern",
    "duplicates",
    "drifted-copy",
    "contradicts",
    "unknown",
})
LINK_TYPE_PRIORITY = {
    "says-vs-does": 0,
    "promise-to-work": 1,
}
LINK_ROUTES = frozenset({
    "ticket",
    "pillar-inbox",
    "people-draft",
    "question-comment",
    "spec-candidate",
})
LEDGER_STATES = frozenset({
    "proposed",
    "accepted",
    "rejected",
    "later",
    "expired",
    "superseded",
})

BASE_FINDING_KEYS = frozenset({
    "id", "kind", "repo", "paths", "what", "evidence",
    "why_keep", "confidence", "size", "ticket",
})
LINK_ONLY_KEYS = frozenset({
    "link_type", "ends", "changes", "sources", "owner", "route",
})
VERDICT_KEYS = frozenset({
    "id", "verdict", "reason", "evidence", "blind", "changes_confirmed",
})
LINK_END_KEYS = frozenset({"ref", "quote", "seen"})

MAX_LINK_CARDS = 15


def _no_duplicates(pairs):
    seen = set()
    out = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"duplicate key: {key}")
        seen.add(key)
        out[key] = value
    return out


def parse_json_strict(raw):
    return json.loads(raw, object_pairs_hook=_no_duplicates)


def _valid_iso_date(val):
    if not isinstance(val, str) or ISO_DATE_RE.fullmatch(val) is None:
        return False
    try:
        date.fromisoformat(val)
        return True
    except ValueError:
        return False


def _is_non_empty_line(val, max_len=500):
    return isinstance(val, str) and 1 <= len(val) <= max_len and LINE_RE.fullmatch(val) is not None


def _is_line_or_empty(val, max_len=500):
    return isinstance(val, str) and len(val) <= max_len and LINE_OR_EMPTY_RE.fullmatch(val) is not None


def _is_evidence_entry(val):
    return isinstance(val, str) and 6 <= len(val) <= 500 and EVIDENCE_RE.fullmatch(val) is not None


def _validate_link_end(end, idx):
    if not isinstance(end, dict):
        return f"ends[{idx}]: must be an object"
    keys = set(end)
    missing = sorted(LINK_END_KEYS - keys)
    if missing:
        return f"ends[{idx}]: missing keys {missing}"
    extra = sorted(keys - LINK_END_KEYS)
    if extra:
        return f"ends[{idx}]: extra keys {extra}"
    ref = end["ref"]
    if not (isinstance(ref, str) and 1 <= len(ref) <= 300 and LINK_REF_RE.fullmatch(ref)):
        return f"ends[{idx}].ref: must be a non-empty string with no whitespace"
    if not _is_non_empty_line(end["quote"]):
        return f"ends[{idx}].quote: must be a non-empty single line"
    if not _valid_iso_date(end["seen"]):
        return f"ends[{idx}].seen: must be YYYY-MM-DD"
    return None


def validate_finding(record):
    if not isinstance(record, dict):
        return "line must be a JSON object"
    keys = set(record)
    missing_base = sorted(BASE_FINDING_KEYS - keys)
    if missing_base:
        return f"missing required keys: {missing_base}"

    kind = record["kind"]
    if not isinstance(kind, str) or kind not in KINDS:
        return f"invalid kind: {kind!r}"

    if kind == "link":
        missing_link = sorted(LINK_ONLY_KEYS - keys)
        if missing_link:
            return f"link missing required keys: {missing_link}"
        allowed = BASE_FINDING_KEYS | LINK_ONLY_KEYS
    else:
        allowed = BASE_FINDING_KEYS

    extra = sorted(keys - allowed)
    if extra:
        return f"extra keys not allowed: {extra}"

    fid = record["id"]
    if not (isinstance(fid, str) and ID_RE.fullmatch(fid)):
        return f"invalid id: {fid!r}"
    if not _is_non_empty_line(record["repo"]):
        return "repo must be a non-empty single line"

    paths = record["paths"]
    if not isinstance(paths, list) or not all(_is_non_empty_line(p) for p in paths):
        return "paths must be an array of non-empty single lines"
    if kind == "delete" and len(paths) < 1:
        return "delete finding requires at least one path"

    if not _is_non_empty_line(record["what"]):
        return "what must be a non-empty single line"

    evidence = record["evidence"]
    if not isinstance(evidence, list) or len(evidence) < 1 or not all(_is_evidence_entry(e) for e in evidence):
        return "evidence must be a non-empty array of '<command> -> <short result>' entries"

    why_keep = record["why_keep"]
    if not _is_line_or_empty(why_keep):
        return "why_keep must be a single line"
    if kind in ("delete", "link") and len(why_keep) < 1:
        return f"{kind} finding requires non-empty why_keep"

    if record["confidence"] not in CONFIDENCES:
        return f"invalid confidence: {record['confidence']!r}"
    if record["size"] not in SIZES:
        return f"invalid size: {record['size']!r}"

    ticket = record["ticket"]
    if ticket is not None and not _is_non_empty_line(ticket, max_len=160):
        return "ticket must be null or a 1-160 char single line"

    if kind == "link":
        link_type = record["link_type"]
        if not isinstance(link_type, str) or link_type not in LINK_TYPES:
            return f"invalid link_type: {link_type!r}"
        ends = record["ends"]
        if not isinstance(ends, list):
            return "ends must be an array"
        if link_type == "pattern":
            if len(ends) < 3:
                return "pattern link requires at least 3 ends"
        else:
            if len(ends) != 2:
                return f"link_type {link_type!r} requires exactly 2 ends (got {len(ends)})"
        for idx, end in enumerate(ends):
            err = _validate_link_end(end, idx)
            if err:
                return err
        if not _is_non_empty_line(record["changes"]):
            return "changes must be a non-empty single line"
        sources = record["sources"]
        if type(sources) is not int or sources < 1:
            return "sources must be an integer >= 1"
        if not _is_non_empty_line(record["owner"]):
            return "owner must be a non-empty single line"
        route = record["route"]
        if not isinstance(route, str) or route not in LINK_ROUTES:
            return f"invalid route: {route!r}"
        if route == "ticket" and ticket is None:
            return "link with route 'ticket' requires a non-null ticket title"
        if route != "ticket" and ticket is not None:
            return f"link with route {route!r} must have ticket: null"

    return None


def validate_verdict(record):
    if not isinstance(record, dict):
        return "verdict line must be a JSON object"
    keys = set(record)
    missing = sorted(VERDICT_KEYS - keys)
    if missing:
        return f"missing required keys: {missing}"
    extra = sorted(keys - VERDICT_KEYS)
    if extra:
        return f"extra keys not allowed: {extra}"
    if not (isinstance(record["id"], str) and ID_RE.fullmatch(record["id"])):
        return f"invalid id: {record['id']!r}"
    if record["verdict"] not in VERDICTS:
        return f"invalid verdict: {record['verdict']!r}"
    if not _is_non_empty_line(record["reason"]):
        return "reason must be a non-empty single line"
    evidence = record["evidence"]
    if not isinstance(evidence, list) or len(evidence) < 1 or not all(_is_evidence_entry(e) for e in evidence):
        return "evidence must be a non-empty array of '<command> -> <short result>' entries"
    if type(record["blind"]) is not bool:
        return "blind must be a boolean"
    cc = record["changes_confirmed"]
    if cc is not None and type(cc) is not bool:
        return "changes_confirmed must be a boolean or null"
    if record["verdict"] == "CONFIRMED" and cc is False:
        return "CONFIRMED verdict cannot have changes_confirmed: false"
    return None


def _dedupe_winner_key(finding):
    return (
        CONFIDENCE_RANK[finding["confidence"]],
        -len(finding["evidence"]),
        KIND_RANK[finding["kind"]],
        SIZE_RANK[finding["size"]],
        finding["id"],
    )


def _rank_key(finding):
    return (
        KIND_RANK[finding["kind"]],
        CONFIDENCE_RANK[finding["confidence"]],
        SIZE_RANK[finding["size"]],
        -len(finding["evidence"]),
        finding["id"],
    )


def cmd_merge(args):
    findings_dir = Path(args.findings_dir)
    if not findings_dir.is_dir():
        print(f"merge: findings_dir is not a directory: {findings_dir}", file=sys.stderr)
        return 1
    if args.batches < 1:
        print("merge: --batches must be >= 1", file=sys.stderr)
        return 1

    input_count = 0
    valid_records = []
    dropped = []
    seen_ids = {}

    for path in sorted(findings_dir.glob("*.jsonl")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for lineno, raw in enumerate(text.splitlines(), 1):
            if not raw.strip():
                continue
            input_count += 1
            try:
                record = parse_json_strict(raw)
            except (ValueError, json.JSONDecodeError) as exc:
                dropped.append({"file": path.name, "line": lineno, "reason": f"invalid JSON: {exc}"})
                continue
            err = validate_finding(record)
            if err:
                dropped.append({"file": path.name, "line": lineno, "reason": err})
                continue
            dedupe_key = (record["repo"], tuple(sorted(record["paths"])))
            prev_key = seen_ids.get(record["id"])
            if prev_key is not None and prev_key != dedupe_key:
                dropped.append({
                    "file": path.name,
                    "line": lineno,
                    "reason": f"duplicate finding id {record['id']!r} with different target",
                })
                continue
            seen_ids[record["id"]] = dedupe_key
            valid_records.append(record)

    groups = defaultdict(list)
    for rec in valid_records:
        key = (rec["repo"], tuple(sorted(rec["paths"])))
        groups[key].append(rec)

    merged_findings = []
    for group in groups.values():
        ordered = sorted(group, key=_dedupe_winner_key)
        winner = dict(ordered[0])
        merged_ev = []
        seen_ev = set()
        for item in ordered:
            for ev in item["evidence"]:
                if ev not in seen_ev:
                    seen_ev.add(ev)
                    merged_ev.append(ev)
        winner["evidence"] = merged_ev
        winner["merged_ids"] = sorted({item["id"] for item in ordered})
        merged_findings.append(winner)

    merged_findings.sort(key=_rank_key)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    merged_doc = {
        "schema": "openwiz.dream-cycle.merged.v1",
        "findings": merged_findings,
        "dropped": dropped,
        "counts": {
            "input": input_count,
            "valid": len(valid_records),
            "dropped": len(dropped),
            "merged": len(merged_findings),
        },
    }
    out_path.write_text(json.dumps(merged_doc, indent=2) + "\n", encoding="utf-8")

    batches_dir = Path(args.batches_dir)
    batches_dir.mkdir(parents=True, exist_ok=True)
    for old_batch in batches_dir.glob("batch-*.jsonl"):
        if old_batch.is_file():
            old_batch.unlink()

    buckets = [[] for _ in range(args.batches)]
    for idx, finding in enumerate(merged_findings):
        buckets[idx % args.batches].append(finding)

    for idx, bucket in enumerate(buckets, 1):
        batch_file = batches_dir / f"batch-{idx:02d}.jsonl"
        content = "".join(json.dumps(item) + "\n" for item in bucket)
        batch_file.write_text(content, encoding="utf-8")

    print(
        f"merge: input={input_count} valid={len(valid_records)} "
        f"dropped={len(dropped)} merged={len(merged_findings)} batches={args.batches}"
    )
    return 0


def _load_link_scores(path_str):
    if not path_str:
        return {}
    path = Path(path_str)
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    scores = {}
    try:
        data = parse_json_strict(text)
    except ValueError:
        for line in text.splitlines():
            if not line.strip():
                continue
            item = parse_json_strict(line)
            if isinstance(item, dict) and "id" in item and type(item.get("score")) is int and item["score"] >= 1:
                scores[item["id"]] = item["score"]
        return scores

    if isinstance(data, dict):
        for k, v in data.items():
            if type(v) is int and v >= 1:
                scores[k] = v
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and "id" in item and type(item.get("score")) is int and item["score"] >= 1:
                scores[item["id"]] = item["score"]
    return scores


def _default_link_score(finding):
    explicit = finding.get("score")
    if type(explicit) is int and explicit >= 1:
        return explicit
    lt = finding.get("link_type", "unknown")
    route = finding.get("route", "")
    if lt in ("says-vs-does", "promise-to-work", "spend-to-use"):
        impact = 3
    elif route in ("ticket", "spec-candidate", "pillar-inbox", "people-draft"):
        impact = 2
    else:
        impact = 1
    sources = finding.get("sources", 1)
    conf_w = CONFIDENCE_WEIGHT.get(finding.get("confidence", "low"), 1)
    return max(1, impact * sources * conf_w)


def _load_unconfirmed(path_str):
    if not path_str:
        return []
    data = parse_json_strict(Path(path_str).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("unconfirmed file must be a JSON array")
    return data


def _load_rejected_links(path_str):
    if not path_str:
        return []
    text = Path(path_str).read_text(encoding="utf-8").strip()
    if not text:
        return []
    try:
        data = parse_json_strict(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("rejected"), list):
            return data["rejected"]
        return []
    except ValueError:
        out = []
        for line in text.splitlines():
            if line.strip():
                out.append(parse_json_strict(line))
        return out


def _load_expired_links(ledger_path_str):
    if not ledger_path_str:
        return []
    path = Path(ledger_path_str)
    latest_open = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        entry = parse_json_strict(raw)
        if not isinstance(entry, dict) or "id" not in entry:
            continue
        if entry.get("invalid_at") is None:
            latest_open[entry["id"]] = entry
        elif latest_open.get(entry["id"], {}).get("valid_from") == entry.get("valid_from"):
            latest_open.pop(entry["id"], None)
    expired = [e for e in latest_open.values() if e.get("state") == "expired"]
    expired.sort(key=lambda e: (e.get("valid_from", ""), e["id"]))
    return expired


def _evaluate_canaries(canaries_path_str, verdicts_by_id):
    if not canaries_path_str:
        return set(), []
    data = parse_json_strict(Path(canaries_path_str).read_text(encoding="utf-8"))
    canary_ids = set()
    missed = []

    if isinstance(data, dict) and isinstance(data.get("missed"), list):
        for item in data["missed"]:
            if isinstance(item, str):
                canary_ids.add(item)
                missed.append({"id": item, "expected": "expected", "actual": "missed"})
            elif isinstance(item, dict) and "id" in item:
                canary_ids.add(item["id"])
                missed.append({
                    "id": item["id"],
                    "expected": item.get("expected", "expected"),
                    "actual": item.get("actual", "missed"),
                })
        entries = data.get("canaries", [])
    elif isinstance(data, dict):
        entries = data.get("canaries", [])
    elif isinstance(data, list):
        entries = data
    else:
        raise ValueError("canaries file must be a JSON array or object")

    already_missed = {m["id"] for m in missed}
    for entry in entries:
        if not isinstance(entry, dict) or "id" not in entry:
            continue
        cid = entry["id"]
        canary_ids.add(cid)
        expected = entry.get("expected")
        if expected is None:
            kind = entry.get("kind")
            expected = "CONFIRMED" if kind == "true" else "REJECTED" if kind == "junk" else None
        if expected is None or cid in already_missed:
            continue
        actual_rec = verdicts_by_id.get(cid)
        actual = actual_rec["verdict"] if actual_rec else "MISSING"
        if actual != expected:
            missed.append({"id": cid, "expected": expected, "actual": actual})
    return canary_ids, missed


def _sanitize_owner_filename(owner):
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", owner.strip()).strip(".-")
    return cleaned or "unknown"


def _newest_end_seen(finding):
    dates = [e.get("seen", "") for e in finding.get("ends", []) if isinstance(e, dict)]
    return max(dates) if dates else ""


def _render_link_card(index, finding, verdict_str, score):
    lines = [
        f"{index}. **`{finding['id']}`** (`{finding['link_type']}`, `{verdict_str}`, score {score}, owner `{finding['owner']}`, route `{finding['route']}`)"
    ]
    for end_idx, end in enumerate(finding["ends"], 1):
        lines.append(f"   - **End {end_idx}:** `{end['ref']}` ({end['seen']}) — \"{end['quote']}\"")
    lines.append(f"   - **Changes:** {finding['changes']}")
    lines.append(f"   - **Best reason not a link:** {finding['why_keep']}")
    return "\n".join(lines)


def _render_standard_item(index, finding, verdict_str):
    paths_str = ", ".join(finding["paths"]) if finding["paths"] else "(area)"
    ev_str = "; ".join(finding["evidence"])
    lines = [
        f"{index}. **`{finding['id']}`** (`{verdict_str}`, {finding['confidence']}, {finding['size']}) — `{finding['repo']}`: `{paths_str}`",
        f"   - **What:** {finding['what']}",
        f"   - **Evidence:** `{ev_str}`",
    ]
    if finding.get("why_keep"):
        lines.append(f"   - **Why keep:** {finding['why_keep']}")
    return "\n".join(lines)


def _write_owner_inboxes(inboxes_dir, inbox_items, report_date, canary_missed):
    if not inbox_items:
        return 0
    inboxes_dir.mkdir(parents=True, exist_ok=True)
    base_resolved = inboxes_dir.resolve()
    by_owner = defaultdict(list)
    for item in inbox_items:
        by_owner[item["finding"]["owner"]].append(item)

    written = 0
    used_names = set()
    for owner in sorted(by_owner):
        safe = _sanitize_owner_filename(owner)
        candidate = safe
        suffix = 2
        while candidate in used_names:
            candidate = f"{safe}-{suffix}"
            suffix += 1
        used_names.add(candidate)
        target = (inboxes_dir / f"{candidate}.md").resolve()
        if not target.is_relative_to(base_resolved):
            raise ValueError(f"refused inbox path outside run folder for owner {owner!r}")
        lines = [
            f"# Dream cycle inbox — {owner} ({report_date})",
            "",
            "Private run-folder inbox. Never written to a pillar repository; people drafts are DRAFT ONLY and never sent automatically.",
            "",
        ]
        if canary_missed:
            lines.append("> **WARNING:** Prover missed canary check — all links in this run are capped at `PLAUSIBLE`.")
            lines.append("")
        for idx, item in enumerate(by_owner[owner], 1):
            f = item["finding"]
            lines.append(_render_link_card(idx, f, item["verdict"], item["score"]))
            if f["route"] == "people-draft":
                lines.append("   - **Draft status:** DRAFT ONLY — never sent automatically.")
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        written += 1
    return written


def cmd_report(args):
    if not _valid_iso_date(args.date):
        print(f"report: invalid --date (expected YYYY-MM-DD): {args.date!r}", file=sys.stderr)
        return 1

    merged_path = Path(args.merged_file)
    verdicts_dir = Path(args.verdicts_dir)
    if not merged_path.is_file():
        print(f"report: merged_file not found: {merged_path}", file=sys.stderr)
        return 1
    if not verdicts_dir.is_dir():
        print(f"report: verdicts_dir is not a directory: {verdicts_dir}", file=sys.stderr)
        return 1

    try:
        merged_doc = parse_json_strict(merged_path.read_text(encoding="utf-8"))
        if not isinstance(merged_doc, dict) or merged_doc.get("schema") != "openwiz.dream-cycle.merged.v1":
            raise ValueError("merged_file schema must be openwiz.dream-cycle.merged.v1")
        findings = merged_doc["findings"]
        unconfirmed = _load_unconfirmed(args.unconfirmed)
        link_scores = _load_link_scores(args.link_scores)
        extra_rejected_links = _load_rejected_links(args.rejected_links)
        expired_links = _load_expired_links(args.ledger)
    except (OSError, ValueError, KeyError) as exc:
        print(f"report: failed to load input: {exc}", file=sys.stderr)
        return 1

    finding_by_id = {}
    alias_to_id = {}
    for f in findings:
        finding_by_id[f["id"]] = f
        alias_to_id[f["id"]] = f["id"]
        for mid in f.get("merged_ids", []):
            alias_to_id.setdefault(mid, f["id"])

    verdicts_by_id = {}
    invalid_verdicts = []
    for path in sorted(verdicts_dir.glob("*.jsonl")):
        if not path.is_file():
            continue
        for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not raw.strip():
                continue
            try:
                rec = parse_json_strict(raw)
            except (ValueError, json.JSONDecodeError) as exc:
                invalid_verdicts.append({
                    "source": f"verdict {path.name}:{lineno}",
                    "reason": f"invalid JSON: {exc}",
                })
                continue
            err = validate_verdict(rec)
            if err:
                invalid_verdicts.append({
                    "source": f"verdict {path.name}:{lineno}",
                    "reason": err,
                })
                continue

            target_id = alias_to_id.get(rec["id"], rec["id"])
            target_finding = finding_by_id.get(target_id)
            if (
                target_finding is not None
                and target_finding.get("kind") == "link"
                and rec["verdict"] == "CONFIRMED"
                and rec["changes_confirmed"] is not True
            ):
                invalid_verdicts.append({
                    "source": f"verdict {rec['id']} ({path.name}:{lineno})",
                    "reason": "rejected CONFIRMED link verdict: changes_confirmed must be true, got null",
                })
                continue

            existing = verdicts_by_id.get(target_id)
            if existing is None or VERDICT_RANK[rec["verdict"]] > VERDICT_RANK[existing["verdict"]]:
                verdicts_by_id[target_id] = rec

    try:
        canary_ids, canary_missed = _evaluate_canaries(args.canaries, verdicts_by_id)
    except (OSError, ValueError) as exc:
        print(f"report: failed to evaluate canaries: {exc}", file=sys.stderr)
        return 1

    active_findings = [f for f in findings if f["id"] not in canary_ids]

    confirmed_count = 0
    plausible_count = 0
    rejected_count = 0
    unproven_count = 0

    deletes = []
    fixes = []
    link_items = []
    rejected_items = []
    rejected_link_reasons = Counter()
    tickets = []
    inbox_items = []
    controller_routes = {"question-comment": [], "spec-candidate": []}

    for f in active_findings:
        v = verdicts_by_id.get(f["id"])
        if v is None:
            unproven_count += 1
            continue

        eff_verdict = v["verdict"]
        if canary_missed and f["kind"] == "link" and eff_verdict == "CONFIRMED":
            eff_verdict = "PLAUSIBLE"

        if eff_verdict == "CONFIRMED":
            confirmed_count += 1
        elif eff_verdict == "PLAUSIBLE":
            plausible_count += 1
        elif eff_verdict == "REJECTED":
            rejected_count += 1
            rejected_items.append((f, v))
            if f["kind"] == "link":
                rejected_link_reasons[v["reason"]] += 1
            continue

        if f["kind"] == "delete":
            deletes.append((f, eff_verdict, v))
        elif f["kind"] == "fix":
            fixes.append((f, eff_verdict, v))
        elif f["kind"] == "link":
            score = link_scores.get(f["id"], _default_link_score(f))
            item = {"finding": f, "verdict": eff_verdict, "verdict_rec": v, "score": score}
            link_items.append(item)
            route = f["route"]
            if route in ("pillar-inbox", "people-draft"):
                inbox_items.append(item)
            elif route in ("question-comment", "spec-candidate"):
                controller_routes[route].append({
                    "id": f["id"],
                    "link_type": f["link_type"],
                    "verdict": eff_verdict,
                    "score": score,
                    "owner": f["owner"],
                    "route": route,
                    "ends": f["ends"],
                    "changes": f["changes"],
                    "why_keep": f["why_keep"],
                })

        if eff_verdict == "CONFIRMED" and f.get("ticket"):
            t_entry = {
                "id": f["id"],
                "kind": f["kind"],
                "repo": f["repo"],
                "paths": f["paths"],
                "ticket": f["ticket"],
                "what": f["what"],
                "evidence": f["evidence"],
                "why_keep": f["why_keep"],
                "confidence": f["confidence"],
                "size": f["size"],
                "verdict_reason": v["reason"],
                "verdict_evidence": v["evidence"],
                "merged_ids": f.get("merged_ids", [f["id"]]),
            }
            if f["kind"] == "link":
                t_entry.update({
                    "link_type": f["link_type"],
                    "ends": f["ends"],
                    "changes": f["changes"],
                    "owner": f["owner"],
                    "route": f["route"],
                    "score": link_scores.get(f["id"], _default_link_score(f)),
                })
            tickets.append(t_entry)

    for rej in extra_rejected_links:
        if isinstance(rej, dict) and rej.get("reason"):
            rejected_link_reasons[rej["reason"]] += 1

    deletes.sort(key=lambda x: (VERDICT_RANK[x[1]], _rank_key(x[0])))
    fixes.sort(key=lambda x: (VERDICT_RANK[x[1]], _rank_key(x[0])))

    def _link_sort_key(item):
        f = item["finding"]
        return (
            -item["score"],
            LINK_TYPE_PRIORITY.get(f["link_type"], 2),
            VERDICT_RANK[item["verdict"]],
            tuple(-ord(c) for c in _newest_end_seen(f)),
            f["id"],
        )

    link_items.sort(key=_link_sort_key)
    inbox_items.sort(key=_link_sort_key)
    for route_name in controller_routes:
        controller_routes[route_name].sort(key=lambda r: (-r["score"], r["id"]))

    scope_list = [s.strip() for s in args.scope.split(",") if s.strip()] if args.scope else []
    area_order = list(scope_list)
    for f in active_findings:
        if f["repo"] not in area_order:
            area_order.append(f["repo"])
    scope_display = ", ".join(area_order) if area_order else "(none)"

    area_counts = {a: {"delete": 0, "fix": 0, "link": 0, "summary": 0} for a in area_order}
    for f in active_findings:
        area_counts[f["repo"]][f["kind"]] += 1

    all_unconfirmed = list(unconfirmed) + invalid_verdicts
    unconfirmed_label = "unconfirmed read" if len(all_unconfirmed) == 1 else "unconfirmed reads"

    lines = [f"# Dream cycle report — {args.date}", ""]
    if canary_missed:
        missed_str = ", ".join(f"`{m['id']}` (expected {m['expected']}, got {m['actual']})" for m in canary_missed)
        lines.append(
            f"> **WARNING: Prover missed canary check** ({missed_str}) — all links in this run are capped at `PLAUSIBLE`."
        )
        lines.append("")

    lines.extend([
        f"- **Date:** {args.date}",
        f"- **Scope:** {scope_display}",
        f"- **Window:** {args.days} days",
        (
            f"- **Counts:** {len(active_findings)} merged findings "
            f"({confirmed_count} confirmed, {plausible_count} plausible, "
            f"{rejected_count} rejected, {unproven_count} unproven); "
            f"{len(tickets)} tickets to file; {len(all_unconfirmed)} {unconfirmed_label}"
        ),
        "",
        "## Areas",
        "",
        "| Area | Deletes | Fixes | Links | Summaries |",
        "| --- | ---: | ---: | ---: | ---: |",
    ])
    for area in area_order:
        c = area_counts[area]
        lines.append(f"| {area} | {c['delete']} | {c['fix']} | {c['link']} | {c['summary']} |")

    lines.extend(["", "## Top deletes", ""])
    if deletes:
        for idx, (f, ver, _) in enumerate(deletes, 1):
            lines.append(_render_standard_item(idx, f, ver))
    else:
        lines.append("_None._")

    lines.extend(["", "## Top fixes", ""])
    if fixes:
        for idx, (f, ver, _) in enumerate(fixes, 1):
            lines.append(_render_standard_item(idx, f, ver))
    else:
        lines.append("_None._")

    lines.extend(["", "## Top links", ""])
    shown_links = link_items[:MAX_LINK_CARDS]
    if shown_links:
        for idx, item in enumerate(shown_links, 1):
            lines.append(_render_link_card(idx, item["finding"], item["verdict"], item["score"]))
        if len(link_items) > MAX_LINK_CARDS:
            lines.append("")
            lines.append(f"_(Showing top {MAX_LINK_CARDS} of {len(link_items)} links.)_")
    else:
        lines.append("_None._")

    if rejected_link_reasons:
        lines.extend(["", "### Rejected links by reason", ""])
        for reason, count in sorted(rejected_link_reasons.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"- {reason}: {count}")

    if expired_links:
        lines.extend(["", "### Expired links", ""])
        for entry in expired_links:
            lines.append(
                f"- **`{entry['id']}`** (`{entry.get('link_type', 'unknown')}`, "
                f"owner `{entry.get('owner', 'unknown')}`, expired {entry.get('valid_from', '')}): "
                f"{entry.get('reason', '')}"
            )

    ctrl_total = len(controller_routes["question-comment"]) + len(controller_routes["spec-candidate"])
    if ctrl_total > 0:
        lines.extend(["", "### Controller link routes", ""])
        for route_name in ("question-comment", "spec-candidate"):
            for r in controller_routes[route_name]:
                lines.append(
                    f"- **`{r['id']}`** (`{route_name}`, `{r['verdict']}`, score {r['score']}, "
                    f"owner `{r['owner']}`): {r['changes']}"
                )

    lines.extend(["", "## Rejected", ""])
    if rejected_items:
        for f, v in rejected_items:
            lines.append(f"- **`{f['id']}`** (`{f['repo']}`): {v['reason']}")
    else:
        lines.append("_None._")

    lines.extend(["", "## Unconfirmed reads", ""])
    if all_unconfirmed:
        for entry in all_unconfirmed:
            if isinstance(entry, dict) and entry.get("repo"):
                lines.append(f"- **`{entry['repo']}` (`{entry.get('source', 'unknown')}`):** {entry.get('reason', '')}")
            elif isinstance(entry, dict):
                lines.append(f"- **`{entry.get('source', 'unknown')}`:** {entry.get('reason', '')}")
            else:
                lines.append(f"- {entry}")
    else:
        lines.append("_None._")

    lines.extend(["", "## Tickets filed", ""])
    if tickets:
        for t in tickets:
            lines.append(f"- `{t['repo']}` — {t['ticket']} (`{t['id']}`)")
    else:
        lines.append("_None._")

    report_path = Path(args.out)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    tickets_path = Path(args.tickets_out)
    tickets_path.parent.mkdir(parents=True, exist_ok=True)
    tickets_path.write_text(json.dumps(tickets, indent=2) + "\n", encoding="utf-8")

    inboxes_dir = Path(args.inboxes_dir) if args.inboxes_dir else report_path.parent / "inboxes"
    inboxes_written = _write_owner_inboxes(inboxes_dir, inbox_items, args.date, bool(canary_missed))

    if args.routes_out:
        routes_path = Path(args.routes_out)
        routes_path.parent.mkdir(parents=True, exist_ok=True)
        routes_path.write_text(json.dumps(controller_routes, indent=2) + "\n", encoding="utf-8")

    print(
        f"report: merged={len(active_findings)} confirmed={confirmed_count} "
        f"plausible={plausible_count} rejected={rejected_count} unproven={unproven_count} "
        f"tickets={len(tickets)} unconfirmed={len(all_unconfirmed)} "
        f"inboxes={inboxes_written} controller_routes={ctrl_total} "
        f"expired_links={len(expired_links)} canary_missed={len(canary_missed)}"
    )
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="dream.py",
        description="Merge dream-cycle findings and render dated private reports.",
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
    report_p.add_argument("--link-scores", help="Optional JSON/JSONL file mapping link ids to integer scores.")
    report_p.add_argument("--rejected-links", help="Optional JSON/JSONL file of Gate A rejected links with reasons.")
    report_p.add_argument("--ledger", help="Optional append-only link ledger JSONL for expired links.")
    report_p.add_argument("--canaries", help="Optional JSON file of seeded canary checks.")
    report_p.add_argument("--inboxes-dir", help="Optional private run folder for per-owner link inboxes.")
    report_p.add_argument("--routes-out", help="Optional JSON output path for controller link routes.")

    args = parser.parse_args(argv)
    if args.command == "merge":
        return cmd_merge(args)
    if args.command == "report":
        return cmd_report(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
