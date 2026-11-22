#!/usr/bin/env python3
import json
import re
import sys

CODES = ("defect", "reproducible", "small", "no_guarded_change", "no_instructions", "nothing_private")
MARKER = re.compile(r"^OpenWiz feedback operation [0-9a-f]{32}$")
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
LINK_LINE = re.compile(r"^Report: #", re.M)
DESTINATION = "openwizdev/OpenWiz"
CLOSING = re.compile(r"^Closes openwizdev/OpenWiz#", re.M)
DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
POINTER = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(?:issues|pull)/[1-9][0-9]*#issuecomment-[1-9][0-9]*$")
REPO = re.compile(r"^openwizdev/[A-Za-z0-9_.-]+$")
APPROVAL_LINE = re.compile(r"^\*\*Approved on its own by [^\n\"“”]+, [0-9]{4}-[0-9]{2}-[0-9]{2}:\*\* [^\n\"“”]+\n"
                           r"Private record: https://github\.com/\S+#issuecomment-[1-9][0-9]*$", re.M)
URL = re.compile(r"\b(?:https?|ftp|file)://\S+|\bwww\.\S+", re.I)
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
    body = report["body"]
    lines = body.split("\n")
    if lines and MARKER.match(lines[-1]):
        body = "\n".join(lines[:-1])
    return "\n".join([report["title"], body] + [c["body"] for c in report.get("comments", [])])


def copied(report, text):
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
    if not failed and not case.get("owned_paths"):
        failed.append("scoped (no owned paths)")
    if failed:
        return {"outcome": "held", "report": report["number"], "report_labels": ["feedback", "needs-triage"],
                "report_milestone": None, "report_comments": [], "brief": None,
                "note": f"#{report['number']} held for the owner: not " + ", ".join(failed)}
    version, brief = case.get("version"), case.get("brief")
    if not isinstance(version, str) or not VERSION.match(version):
        raise Refused("the fleet outcome needs the next release's version, X.Y.Z, as the milestone")
    if not isinstance(brief, dict) or not isinstance(brief.get("title"), str) or not isinstance(brief.get("body"), str):
        raise Unreadable("the brief needs a title and a body")
    title, words_ = brief["title"], brief["body"].strip()
    if not title.strip() or "\n" in title:
        raise Refused("the brief needs a one-line title in triage's own words")
    if not words_:
        raise Refused("the brief needs triage's own words")
    if LINK_LINE.search(words_):
        raise Refused("triage's words carry a report link; the helper writes the only one, last")
    if re.search(r"^#+ ", words_, re.M):
        raise Refused("triage's words carry a section heading; the helper writes the owned paths and closing sections")
    if CLOSING.search(words_) or re.search(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+\S*#[0-9]", words_, re.I):
        raise Refused("triage's words carry a closing line; the helper writes both")
    if URL.search(words_) or "```" in words_:
        raise Refused("the brief carries a link or a code block; a brief copies no link, command or code")
    if copied(report, words_):
        raise Refused("the brief copies the report's words; write it in triage's own words")
    paths = owned(case.get("owned_paths"))
    relies = relied(case.get("relies_on", []))
    approval = approval_record(case.get("approval"), paths, relies)
    n = report["number"]
    body = (f"{words_}\n\n## Owned paths\n\n" + "\n".join(f"- {p}" for p in paths) + "\n\n"
            f"**Relies on:** {relies}\n\n"
            "## Closing\n\nThe fix's pull request description carries both of these lines, each on its own line, "
            f"with this brief's number in the first:\n\nCloses {DESTINATION}#<this brief>\n"
            f"Closes {DESTINATION}#{n}\n\nReport: #{n}")
    return {"outcome": "fleet", "report": n, "report_labels": ["feedback"],
            "report_milestone": version, "report_comments": [], "note": None,
            "brief": {"title": title, "body": body, "labels": ["ready-for-agent"], "milestone": version,
                      "approval": approval}}


def owned(paths):
    if not isinstance(paths, list) or not paths:
        raise Refused("the fleet outcome needs owned paths, read fresh from the code")
    bullets = []
    for entry in paths:
        if not isinstance(entry, dict) or not {"path"} <= set(entry) <= {"path", "repo"}:
            raise Unreadable("each owned path is {\"path\"} or {\"path\", \"repo\"}")
        path, repo = entry["path"], entry.get("repo")
        parts = path.rstrip("/").split("/") if isinstance(path, str) else [""]
        if (not isinstance(path, str) or path.startswith("/") or any(p in ("", ".", "..") for p in parts)
                or re.search(r"[\s`]", path)):
            raise Refused(f"owned paths must be plain relative paths: {json.dumps(path)}")
        if repo is not None and not (isinstance(repo, str) and REPO.match(repo)):
            raise Refused(f"owned paths' repository must be an openwizdev one: {json.dumps(repo)}")
        bullets.append(f"`{path}`" + (f" in `{repo}`" if repo else ""))
    return bullets


def relied(paths):
    if not isinstance(paths, list) or not all(isinstance(p, str) and p and not re.search(r"[\s`]", p) for p in paths):
        raise Refused("relies on is a list of plain paths, empty for nothing")
    return ", ".join(f"`{p}`" for p in paths) or "nothing"


def approval_record(approval, paths, relies):
    if not isinstance(approval, dict) or set(approval) != {"owner", "date", "record"} or not all(
            isinstance(v, str) for v in approval.values()):
        raise Refused("the fleet outcome needs the standing approval: owner, date and its private record")
    owner, date, record = approval["owner"], approval["date"], approval["record"]
    if not owner.strip() or re.search(r"[\n\"“”*]", owner) or not DATE.match(date) or not POINTER.match(record):
        raise Refused("the standing approval needs a plain owner name, a YYYY-MM-DD date and a private "
                      "record comment URL")
    return (f"**Approved on its own by {owner}, {date}:** a small, clear user report fixed under {owner}'s "
            f"standing approval for the feedback loop (FL1).\nPrivate record: {record}\n\n"
            "Approved brief: this issue\nOwned paths: " + ", ".join(paths) + f"\nRelies on: {relies}")


def owned_section(body):
    lines = body.split("\n")
    start = next((i for i, line in enumerate(lines) if re.match(r"^## Owned paths\s*$", line)), None)
    if start is None:
        return None
    section = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        if line.startswith("- "):
            section.append(line[2:])
    for bullet in section:
        repos = re.findall(r"\bin `([^`]+)`", bullet)
        paths = [p for p in re.findall(r"`([^`]+)`", bullet) if p not in repos]
        if len(repos) > 1 or any(not REPO.match(r) for r in repos) or not paths or any(
                p.startswith("/") or " " in p or any(x in ("", ".", "..") for x in p.rstrip("/").split("/"))
                for p in paths):
            return None
    return section or None


def verify(case):
    report, brief, authors = case["report"], case["brief"], {a.lower() for a in case["record_authors"]}
    missing = []
    if brief["author"].lower() not in authors:
        missing.append("a brief whose author is a record author")
    if not brief["body"].endswith(f"\n\nReport: #{report}") or len(LINK_LINE.findall(brief["body"])) != 1:
        missing.append(f"the report link, Report: #{report}, as its only and last line")
    if owned_section(brief["body"]) is None:
        missing.append("owned paths launch-fleet can read")
    closing = CLOSING.findall(brief["body"])
    if f"\nCloses {DESTINATION}#{report}\n" not in brief["body"] or f"\nCloses {DESTINATION}#<this brief>\n" not in brief["body"] or len(closing) != 2:
        missing.append("both closing lines in full")
    if "ready-for-agent" not in brief["labels"]:
        missing.append("the ready-for-agent label")
    newest = max(brief["ready_labelled"], key=lambda e: e["at"], default=None)
    if newest is None or (newest["by"] or "").lower() not in authors:
        missing.append("the ready-for-agent label last added by a record author")
    elif brief["last_edited_at"] is not None and newest["at"] <= brief["last_edited_at"]:
        missing.append(f"the ready-for-agent label added after the brief's last edit at {brief['last_edited_at']} "
                       "(remove it and add it again; an edit in the label's own second can't be ordered)")
    if brief["milestone"] != case["version"]:
        missing.append(f"the milestone {case['version']}")
    if not any(c["author"].lower() in authors and APPROVAL_LINE.search(c["body"]) for c in brief["comments"]):
        missing.append("a record author's approval record")
    if missing:
        raise Refused(f"brief #{brief['number']} lacks " + "; ".join(missing))
    return {"verified": brief["number"], "report": report}


CASE_KEYS = {"report", "criteria", "version", "brief", "owned_paths", "relies_on", "approval"}
REPORT_KEYS = {"number", "author", "pull_request", "title", "body", "labels", "milestone", "comments"}


def unique(pairs):
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise Unreadable("a key appears twice")
    return dict(pairs)


def read(path):
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


BRIEF_KEYS = {"number", "author", "body", "labels", "milestone", "comments", "last_edited_at", "ready_labelled"}


def is_time(value):
    return isinstance(value, str) and TIME.fullmatch(value) is not None


def read_brief(path):
    try:
        raw = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
        case = json.loads(raw, object_pairs_hook=unique)
    except (OSError, UnicodeDecodeError, ValueError) as err:
        raise Unreadable(f"cannot read the brief: {err.__class__.__name__}")
    if not isinstance(case, dict) or set(case) != {"report", "version", "record_authors", "brief"}:
        raise Unreadable("verify reads exactly report, version, record_authors and brief")
    brief, authors = case["brief"], case["record_authors"]
    if type(case["report"]) is not int or not isinstance(case["version"], str) or not isinstance(authors, list) \
            or not authors or not all(isinstance(a, str) and a for a in authors):
        raise Unreadable("verify needs a report number, a version and the record authors")
    if not isinstance(brief, dict) or set(brief) != BRIEF_KEYS:
        raise Unreadable("the brief holds exactly " + ", ".join(sorted(BRIEF_KEYS)))
    if type(brief["number"]) is not int or not isinstance(brief["author"], str) or not isinstance(brief["body"], str) \
            or not isinstance(brief["labels"], list) or not all(isinstance(x, str) for x in brief["labels"]) \
            or not (brief["milestone"] is None or isinstance(brief["milestone"], str)) \
            or not isinstance(brief["comments"], list) or not all(
                isinstance(c, dict) and set(c) == {"author", "body"} and all(isinstance(v, str) for v in c.values())
                for c in brief["comments"]) \
            or not (brief["last_edited_at"] is None or is_time(brief["last_edited_at"])) \
            or not isinstance(brief["ready_labelled"], list) or not all(
                isinstance(e, dict) and set(e) == {"at", "by"} and is_time(e["at"])
                and (e["by"] is None or isinstance(e["by"], str)) for e in brief["ready_labelled"]):
        raise Unreadable("the brief's fields have the wrong types")
    return case


def main(argv):
    commands = {"plan": lambda path: plan(read(path)), "verify": lambda path: verify(read_brief(path))}
    if len(argv) != 2 or argv[0] not in commands:
        print("usage: feedback.py plan|verify <file | ->", file=sys.stderr)
        return 2
    try:
        print(json.dumps(commands[argv[0]](argv[1]), ensure_ascii=True, indent=2))
        return 0
    except Refused as why:
        print(f"feedback: refused: {why}", file=sys.stderr)
        return 1
    except Unreadable as why:
        print(f"feedback: {why}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
