#!/usr/bin/env python3
"""Triage's feedback path (openwiz.feedback-loop.v1, FL3 #1845).

python3 -I feedback.py plan <case.json | ->

The case is one JSON object: the report as GitHub shows it ("number",
"pull_request", "title", "body", "labels", "milestone", "comments"), triage's "criteria"
(the contract's six codes, each true, false or null for can't tell), and, for a
report going to a fleet, "version" (the next release, X.Y.Z) and "brief"
("title", "body"). It prints the outcome as one JSON object: the report's exact
labels and milestone, "report_comments" (always empty: triage never replies on
a report), the brief to create or null, and the owner's private note or null.

It sends nothing. A report goes to a fleet only when every code is exactly true
and its words show no instruction or private-looking text; anything else is
held for the owner. Exit 0 prints the outcome, 1 refuses (last line says why),
2 is unreadable input. Python 3 standard library only.
"""
import json
import re
import sys

CODES = ("defect", "reproducible", "small", "no_guarded_change", "no_instructions", "nothing_private")
MARKER = re.compile(r"^OpenWiz feedback operation [0-9a-f]{32}$")
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
LINK_LINE = re.compile(r"^Report: #", re.M)
URL = re.compile(r"\b(?:https?|ftp|file)://\S+|\bwww\.\S+", re.I)
# A backstop under triage's own reading, which the report's words may steer:
# text addressed to an agent, or anything to run or follow.
INSTRUCTION = re.compile(
    r"```|`[^`\n]*[\s|;&$<>/\\=][^`\n]*`|https?://|\bwww\.|^\s*\$ |\b(?:agents?|assistants?|AI|LLMs?|claude|codex|gpt)\b\s*[,:(]"
    r"|\b(?:system|assistant|developer)\s*:|\bignore (?:all|any|previous|prior|your|the above)\b"
    r"|\b(?:run|execute|curl|wget|sudo|pip install|npm install)\b.*(?:\||&&|\.sh\b)",
    re.I | re.M)
PRIVATE = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_\w{20,}|sk-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16}|xox[abpr]-[\w-]{10,})"
    r"|(?:^|[\s(\"'])(?:/Users/|/home/|/root/|~/|[A-Za-z]:\\)"
    r"|\bthr_[A-Za-z0-9]+|\b[\w.+-]+@[\w-]+\.[\w.-]+\b|-----BEGIN [A-Z ]*PRIVATE KEY-----",
    re.M)


class Refused(Exception):
    pass


class Unreadable(Exception):
    pass


def is_report(report):
    if report.get("pull_request"):
        return False
    lines = report["body"].split("\n")
    marked = len(lines) >= 3 and lines[-2] == "" and bool(MARKER.match(lines[-1]))
    return "feedback" in report["labels"] or marked


def words(report):
    """The report's own words and its comments', without the marker line."""
    body = report["body"]
    lines = body.split("\n")
    if lines and MARKER.match(lines[-1]):
        body = "\n".join(lines[:-1])
    return "\n".join([report["title"], body] + [c["body"] for c in report.get("comments", [])])


def copied(report, text):
    """Whether the brief repeats a whole line of the report (its marker included).
    A report with a link or code in it is already held, so lines are enough."""
    return any(line.strip() in text for line in report["body"].split("\n") if len(line.strip()) >= 24)


def plan(case):
    report, criteria = case["report"], case["criteria"]
    if not is_report(report):
        raise Refused(f"#{report['number']} is not a report: no feedback label and no marker line last")
    if report["milestone"] is not None or "needs-triage" in report["labels"]:
        raise Refused(f"#{report['number']} is already triaged: it has a milestone or needs-triage")
    failed = [code for code in CODES if criteria.get(code) is not True]
    text = words(report)
    if INSTRUCTION.search(text) and "no_instructions" not in failed:
        failed.append("no_instructions")
    if PRIVATE.search(text) and "nothing_private" not in failed:
        failed.append("nothing_private")
    if failed:
        return {"outcome": "held", "report": report["number"], "report_labels": ["feedback", "needs-triage"],
                "report_milestone": None, "report_comments": [], "brief": None,
                "note": f"#{report['number']} held for the owner: not " + ", ".join(failed)}
    version, brief = case.get("version"), case.get("brief")
    if not isinstance(version, str) or not VERSION.match(version):
        raise Refused("the fleet outcome needs the next release's version, X.Y.Z, as the milestone")
    if not isinstance(brief, dict) or not isinstance(brief.get("title"), str) or not isinstance(brief.get("body"), str):
        raise Unreadable("the brief needs a title and a body")
    title, body = brief["title"], brief["body"]
    if not title.strip() or "\n" in title:
        raise Refused("the brief needs a one-line title in triage's own words")
    link = f"\n\nReport: #{report['number']}"
    if not body.endswith(link) or len(LINK_LINE.findall(body)) != 1 or not body[:-len(link)].strip():
        raise Refused(f"the brief must end with a blank line and then its only report link, {link.strip()}, "
                      "with no trailing newline")
    if URL.search(body) or "```" in body:
        raise Refused("the brief carries a link or a code block; a brief copies no link, command or code")
    rest = body[:-len(link)]
    if copied(report, rest):
        raise Refused("the brief copies the report's words; write it in triage's own words")
    return {"outcome": "fleet", "report": report["number"], "report_labels": ["feedback"],
            "report_milestone": version, "report_comments": [], "note": None,
            "brief": {"title": title, "body": body, "labels": ["ready-for-agent"], "milestone": version}}


CASE_KEYS = {"report", "criteria", "version", "brief"}
REPORT_KEYS = {"number", "author", "pull_request", "title", "body", "labels", "milestone", "comments"}


def unique(pairs):
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise Unreadable("a key appears twice")
    return dict(pairs)


def read(path):
    """The case, in exactly its shape: known keys, each once, each of its type."""
    try:
        raw = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
        case = json.loads(raw, object_pairs_hook=unique)
    except (OSError, UnicodeDecodeError, ValueError) as err:
        raise Unreadable(f"cannot read the case: {err.__class__.__name__}")
    if not isinstance(case, dict) or not CASE_KEYS >= set(case) or not {"report", "criteria"} <= set(case):
        raise Unreadable("the case holds a report, criteria and, for a fleet, version and brief, nothing else")
    report, criteria, brief = case["report"], case["criteria"], case.get("brief")
    if not isinstance(report, dict) or not REPORT_KEYS >= set(report):
        raise Unreadable("the report holds only " + ", ".join(sorted(REPORT_KEYS)))
    shapes = {"number": int, "title": str, "body": str, "labels": list}
    if any(type(report.get(key)) is not kind for key, kind in shapes.items()):
        raise Unreadable("the report needs number, title, body and labels")
    if not all(isinstance(label, str) for label in report["labels"]):
        raise Unreadable("the report's labels must be names")
    if type(report.get("pull_request", False)) is not bool:
        raise Unreadable("the report's pull_request must be true or false")
    comments = report.get("comments", [])
    if not isinstance(comments, list) or not all(
            isinstance(c, dict) and type(c.get("body")) is str and set(c) <= {"author", "body"} for c in comments):
        raise Unreadable("the report's comments are objects with a body and an author")
    if report.get("milestone") is not None and not isinstance(report["milestone"], str):
        raise Unreadable("the report's milestone must be a title or null")
    report.setdefault("milestone", None)
    if not isinstance(criteria, dict) or not set(CODES) >= set(criteria) or any(
            value is not None and type(value) is not bool for value in criteria.values()):
        raise Unreadable("criteria holds only the six codes, each true, false or null")
    if brief is not None and (not isinstance(brief, dict) or set(brief) != {"title", "body"}):
        raise Unreadable("the brief holds exactly a title and a body")
    return case


def main(argv):
    if len(argv) != 2 or argv[0] != "plan":
        print("usage: feedback.py plan <case.json | ->", file=sys.stderr)
        return 2
    try:
        print(json.dumps(plan(read(argv[1])), ensure_ascii=True, indent=2))
        return 0
    except Refused as why:
        print(f"feedback: refused: {why}", file=sys.stderr)
        return 1
    except Unreadable as why:
        print(f"feedback: {why}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
