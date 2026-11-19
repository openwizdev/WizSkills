"""Review mechanics for review-ticket: pin the head, check and post the report, file a follow-up.

  pin --repo O/R --pr N              which review is due at the exact head, or why none is
  check REPORT --repo O/R --pr N     the report's contract lines against the PR and earlier reports
  post REPORT --repo O/R --pr N      check, post once, read back
  follow-up --repo TICKET_REPO ...   file one polish issue or logged blocker for triage, once

Settings are read from the base branch, never the pull request's head. Only
comments by the `Record authors` row of docs/agents/fleet.md count. Exit 0
done, 1 a stop, report problems or an unknown write, 2 a refusal (unreadable
or invalid settings, arguments). Python 3.11+ standard library and `gh`.
"""
import argparse
import base64
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

SHA = re.compile(r"[0-9a-f]{40}")
VERDICT = re.compile(r"VERDICT: (APPROVE|CHANGES) at ([0-9a-f]{40})")
FINDING = re.compile(r"- \*\*(R[1-9][0-9]*) \[([a-z]+)\]\*\* (.*)")
NEW = re.compile(r"`[^`\s]+:[1-9][0-9]*` \((?:Standards|Spec|Sweep)\) \S")
STATUSES = ("resolved at ", "withdrawn: ", "still open after the ", "disputed, kept: ", "Polish issue: #")
OPEN = ("still open after the ", "disputed, kept: ")
USER = re.compile(r"User path: \S.*")
RISK = re.compile(r"Risk: (?:security|privacy|data loss): \S.*")
POLISH = re.compile(r"Polish issue: #[1-9][0-9]*\.?$")
LOGGED = re.compile(r".*\bLogged as follow-up #[1-9][0-9]*\.$")
MARK = re.compile(r"- \*\*Ruling ([1-9][0-9]*)\*\* (?:upheld|overturned as (R[1-9][0-9]*)): \S.*")
IDS = r"R[1-9][0-9]*(?:(?:, R[1-9][0-9]*)* and R[1-9][0-9]*)?"
NEXT = {"builder": rf"Next: the builder fixes or disputes ({IDS}) once, then one re-check\.",
        "fresh": rf"Next: a fresh, stronger builder fixes ({IDS}) once, then one final check\.",
        "park": rf"Next: park ({IDS}) as a decision for Jake\.",
        "merge": r"Next: none open\. It merges by the project's merge rules\."}
ROUNDS = {"full": ("Full review by ", ("builder", "merge"), "the builder line or none open"),
          "re-check": ("Re-check of ", ("fresh", "merge"), "the fresh line or none open"),
          "final": ("Final check of ", ("park", "merge"), "the park line or none open")}
CLOSES = re.compile(r"(?im)^\s*(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+((?:[\w.-]+/[\w.-]+)?#[1-9][0-9]*)\b")
LOGIN = re.compile(r"`([A-Za-z0-9](?:[A-Za-z0-9-]{0,38})(?:\[bot\])?)`")
PRIVATE = re.compile(r"\b(?:gh[pousr]_|github_pat_|sk-)[A-Za-z0-9_-]{8,}|\bthr_[A-Za-z0-9]{4,}|(?i:\bbearer\s+[A-Za-z0-9._-]{8,})")


class Refusal(Exception):
    pass


class Stop(Exception):
    pass


def gh(*args, data=None):
    try:
        out = subprocess.run(["gh", "api", *args], input=data, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return 1, None
    try:
        return out.returncode, json.loads(out.stdout) if out.stdout.strip() else None
    except json.JSONDecodeError:
        return 1, None


def get(url):
    code, value = gh(url)
    if code or value is None:
        raise Refusal(f"cannot read {url.split('?')[0]}")
    return value


def pages(url):
    code, value = gh("--paginate", "--slurp", url)
    if code or not isinstance(value, list):
        raise Refusal(f"cannot read {url.split('?')[0]}")
    return [item for page in value for item in page]


def setting(repo, ref, path):
    data = get(f"repos/{repo}/contents/{path}?ref={quote(ref, safe='')}")
    return base64.b64decode(data["content"]).decode()


def section(text, heading):
    lines, inside = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = line.strip() == heading
        elif inside:
            lines.append(line)
    return lines


def cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")] if line.strip().startswith("|") else []


def record_authors(fleet):
    for line in section(fleet, "## GitHub identity"):
        row = cells(line)
        if row[:1] == ["Record authors"] and len(row) == 2:
            names = LOGIN.findall(row[1])
            if names and LOGIN.sub("", row[1]).replace(",", "").strip() == "":
                return {n.lower() for n in names}
    raise Refusal("docs/agents/fleet.md has no valid record authors row; trust nobody and ask on the ticket")


def required_checks(fleet):
    names = [m[1] for line in section(fleet, "## CI checks")
             if (row := cells(line)) and (m := re.fullmatch(r"`([^`]+)`", row[0]))]
    if not names:
        raise Refusal("docs/agents/fleet.md's ## CI checks table names no required check")
    return names


def ids_text(ids):
    ids = list(ids)
    return "none" if not ids else ids[0] if len(ids) == 1 else ", ".join(ids[:-1]) + " and " + ids[-1]


def parse(text):
    lines = text.replace("\r\n", "\n").split("\n")
    paras = [p.strip() for p in "\n".join(lines).split("\n\n") if p.strip()]
    verdict = VERDICT.fullmatch(lines[0].strip()) if lines else None
    findings = []
    for i, raw in enumerate(lines):
        m = FINDING.fullmatch(raw.strip())
        if not m:
            continue
        more = []
        for line in lines[i + 1:]:
            if not line.strip() or not line[:1].isspace():
                break
            more.append(line.strip())
        rest = m[3]
        findings.append({"id": m[1], "grade": m[2], "new": bool(NEW.match(rest)),
                         "status": next((s for s in STATUSES if rest.startswith(s)), None),
                         "user": any(USER.fullmatch(x) for x in more), "risk": any(RISK.fullmatch(x) for x in more),
                         "polish": bool(POLISH.search(rest)), "logged": bool(LOGGED.fullmatch(rest))})
    nxt = paras[-1] if paras and paras[-1].startswith("Next:") else None
    state = next((s for s, p in NEXT.items() if nxt and re.fullmatch(p, nxt)), None)
    named = re.findall(r"R[1-9][0-9]*", nxt or "") if state != "merge" else []
    return {"verdict": verdict[1] if verdict else None, "head": verdict[2] if verdict else None,
            "paras": paras, "findings": findings, "state": state, "named": named,
            "marks": [(int(m[1]), m[2]) for x in lines if (m := MARK.fullmatch(x.strip()))],
            "no_rulings": any(x.strip() == "Rulings: none." for x in lines),
            "none": any(x.strip() == "No findings." for x in lines)}


def open_blockers(report):
    return [f["id"] for f in report["findings"] if f["grade"] == "blocking" and not f["logged"]
            and (f["new"] or (f["status"] or "").startswith(OPEN))]


def description_rulings(text):
    lines, fenced, fence = text.splitlines(), [], False
    for line in lines:
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
        fenced.append(fence)
    heads = [i for i, x in enumerate(lines) if x.strip() == "## Rulings" and not fenced[i]]
    numbers = []
    for line, quoted in zip(lines[heads[0] + 1:] if heads else [], fenced[heads[0] + 1:] if heads else []):
        if re.match(r"#{1,2} ", line) and not quoted:
            break
        if m := re.match(r"([1-9][0-9]*)\. ", line.strip()):
            numbers.append(int(m[1]))
    return numbers


def check(text, description, mode, head, earlier):
    """Every contract line the report breaks; empty when it passes."""
    r, problems = parse(text), []
    if r["verdict"] is None:
        problems.append("the first line is VERDICT: APPROVE or CHANGES at the 40-character head")
    elif r["head"] != head:
        problems.append(f"VERDICT names {r['head']}, not the pinned head {head}")
    start, allowed, wording = ROUNDS[mode]
    second = r["paras"][1] if len(r["paras"]) > 1 else ""
    if not second.startswith(start):
        problems.append(f"the second paragraph starts {start.strip()}")
    elif "CI green on this commit: " not in second:
        problems.append("the second paragraph says CI green on this commit: <the required checks>")
    if not any(p.startswith("Intent: ") for p in r["paras"]):
        problems.append("no Intent: paragraph")
    ids = [f["id"] for f in r["findings"]]
    if not ids and not r["none"]:
        problems.append("no findings and no No findings. line")
    if ids != [f"R{n}" for n in range(1, len(ids) + 1)]:
        problems.append("ids run R1, R2, ... with no gap or repeat")
    before = {f["id"] for f in earlier["findings"]} if earlier else set()
    problems += [f"{i}: a re-check gives every earlier id its status"
                 for i in sorted(before - set(ids), key=lambda x: int(x[1:]))]
    for f in r["findings"]:
        i, blocking = f["id"], f["grade"] == "blocking"
        if f["grade"] not in ("blocking", "polish"):
            problems.append(f"{i}: the grade is blocking or polish")
        elif i in before and f["new"]:
            problems.append(f"{i}: an earlier id takes a status, not a new finding")
        elif i in before and not (f["status"] or f["logged"]):
            problems.append(f"{i}: an earlier id takes one status from the table")
        elif i not in before and not f["new"]:
            problems.append(f"{i}: a new finding names `file:line` and its check (Standards, Spec or Sweep)")
        elif f["new"] and blocking and not (f["user"] or f["risk"]):
            problems.append(f"{i}: a new blocking finding needs its User path: or Risk: line")
        elif f["new"] and not blocking and not f["polish"]:
            problems.append(f"{i}: a new polish finding ends with Polish issue: #<n>")
        if f["logged"] and (f["risk"] or not blocking):
            problems.append(f"{i}: a Risk: blocker is never logged" if f["risk"] else f"{i}: only a blocker is logged")
        elif blocking and not f["new"] and (f["logged"] or (f["status"] or "").startswith(OPEN)) \
                and not (f["user"] or f["risk"]):
            problems.append(f"{i}: an open or logged blocker restates its User path: or Risk: line")
    opened = open_blockers(r)
    risky = {f["id"] for f in r["findings"] if f["risk"]}
    if mode != "full":
        problems += [f"{i}: only a Risk: blocker goes to the fresh round; log a User path: blocker"
                     for i in opened if i not in risky]
    if r["verdict"] and (r["verdict"] == "CHANGES") != bool(opened):
        problems.append("VERDICT is CHANGES exactly while a blocker is open")
    if r["state"] is None:
        problems.append("the last paragraph is one of the four Next: lines")
    elif r["state"] not in allowed:
        problems.append(f"a {'full review' if mode == 'full' else mode.replace('final', 'final check')}'s "
                        f"Next: is {wording}")
    elif set(r["named"]) != set(opened):
        problems.append(f"Next: names {ids_text(r['named'])}, but the open blockers are {ids_text(opened)}")
    listed, marked = description_rulings(description), [n for n, _ in r["marks"]]
    problems += [f"Ruling {n}: listed in the description but not marked" for n in listed if n not in marked]
    problems += [f"Ruling {n}: marked but not listed in the description" for n in sorted(set(marked) - set(listed))]
    problems += [f"Ruling {n}: marked twice" for n in sorted({n for n in marked if marked.count(n) > 1})]
    problems += [f"Ruling {n}: overturned as {i}, which is not a finding" for n, i in r["marks"] if i and i not in ids]
    if not listed and not r["no_rulings"]:
        problems.append("with no rulings listed, the report says Rulings: none.")
    if PRIVATE.search(text):
        problems.append("private material: a token or thread id")
    return problems


def review_state(repo, number, skip=None):
    """The pull request, its settings and record-author reports (skipping an identical `skip` body)."""
    pr = get(f"repos/{repo}/pulls/{number}")
    fleet = setting(repo, pr["base"]["ref"], "docs/agents/fleet.md")
    authors = record_authors(fleet)
    reports = []
    for c in pages(f"repos/{repo}/issues/{number}/comments?per_page=100"):
        body = (c.get("body") or "").replace("\r\n", "\n")
        login = ((c.get("user") or {}).get("login") or "").lower()
        if login in authors and body.startswith("VERDICT: ") and body.strip() != (skip or "").strip():
            reports.append(parse(body) | {"id": c.get("id")})
    head, last = pr["head"]["sha"], reports[-1] if reports else None
    if last is None:
        mode = "full"
    elif last["state"] == "park":
        raise Stop(f"stop: {ids_text(last['named'])} is parked as a decision for Jake")
    elif last["state"] is None:
        raise Stop("stop: the last report has no Next: line; ask the orchestrator")
    else:
        mode = "final" if last["state"] == "fresh" else "re-check"
    return {"pr": pr, "fleet": fleet, "authors": authors, "head": head, "last": last, "mode": mode}


def pin(repo, number):
    pr = get(f"repos/{repo}/pulls/{number}")
    if pr.get("state") != "open":
        raise Stop(f"stop: {'merged' if pr.get('merged') else 'closed'}; archive your own thread")
    if pr.get("draft"):
        raise Stop("stop: draft")
    ticket = CLOSES.search(pr.get("body") or "")
    if not ticket:
        raise Stop("stop: no Closes line names a ticket")
    ref = ticket[1] if not ticket[1].startswith("#") else repo + ticket[1]
    s = review_state(repo, number)
    head = s["head"]
    runs = get(f"repos/{repo}/commits/{head}/check-runs?per_page=100").get("check_runs", [])
    names, bad = required_checks(s["fleet"]), []
    for name in names:
        mine = [x for x in runs if x.get("name") == name]
        latest = max(mine, key=lambda x: (x.get("started_at") or "", x.get("id") or 0), default=None)
        if not latest or (latest.get("status"), latest.get("conclusion")) != ("completed", "success"):
            bad.append(name)
    if bad:
        raise Stop(f"stop: {', '.join(bad)} is not green at {head}")
    line = f"review {s['mode']} #{number} at {head}; ticket {ref}; checks {', '.join(names)}"
    if s["last"] is not None:
        if s["last"]["head"] == head:
            raise Stop(f"stop: already reported at {head}")
        ids = [int(f["id"][1:]) for f in s["last"]["findings"]]
        line += (f"; last read {s['last']['head']}; open {ids_text(open_blockers(s['last']))}; "
                 f"next id R{max(ids, default=0) + 1}")
    return line


def report_problems(path, repo, number):
    text = Path(path).read_text(encoding="utf-8").replace("\r\n", "\n")
    s = review_state(repo, number, skip=text)
    problems = check(text, s["pr"].get("body") or "", s["mode"], s["head"], s["last"])
    if s["last"] and s["last"]["head"] == s["head"]:
        problems.append(f"already reported at {s['head']}")
    return text, s, problems


def find_comment(repo, number, text):
    for c in pages(f"repos/{repo}/issues/{number}/comments?per_page=100"):
        if (c.get("body") or "").replace("\r\n", "\n").strip() == text.strip():
            return c
    return None


def post(path, repo, number):
    text, s, problems = report_problems(path, repo, number)
    found = find_comment(repo, number, text)
    if found:
        return f"already posted {found['id']}"
    if problems:
        raise Stop("\n".join(problems))
    gh("-X", "POST", f"repos/{repo}/issues/{number}/comments", "--input", "-", data=json.dumps({"body": text}))
    found = find_comment(repo, number, text)
    if not found:
        raise Stop("unknown: not found on read-back; read the comments before posting again")
    if ((found.get("user") or {}).get("login") or "").lower() not in s["authors"]:
        raise Stop(f"posted {found['id']} by an account that is not a record author; it will not count")
    return f"posted {found['id']}"


def follow_up(a):
    repo = a.repo
    labels = setting(repo, get(f"repos/{repo}")["default_branch"], "docs/agents/triage-labels.md")
    found = [row[1].strip("` ") for line in labels.splitlines()
             if len(row := cells(line)) >= 2 and row[0] == "`needs-triage`"]
    if len(found) != 1 or not found[0]:
        raise Refusal("docs/agents/triage-labels.md names no single needs-triage label; the project needs the setup skill")
    if re.search(r"[`$\"]", a.title):
        raise Refusal("keep backticks, $ and double quotes out of the title")
    finding = Path(a.finding).read_text(encoding="utf-8").strip()
    finding += "" if finding.endswith(".") else "."
    head = f"Follow-up of #{a.ticket} (spec #{a.spec})\n\n"
    if a.logged:
        if not a.user_path:
            raise Refusal("a logged blocker carries its --user-path")
        title = f"{a.title} (follow-up for #{a.ticket}, {a.id})"
        body = (head + f"{finding}\nUser path: {a.user_path}\n\nStill open after the {a.logged} of pull request "
                f"{a.pr} at {a.head}; logged, so it did not block the merge.\n")
    else:
        title = f"{a.title} (polish for #{a.ticket}, {a.id})"
        body = head + f"{finding} Found in pull request {a.pr} at {a.head}; it is polish and did not block the merge.\n"
    if PRIVATE.search(title + body):
        raise Refusal("private material: a token or thread id")
    url = f"repos/{repo}/issues?state=all&per_page=100&labels={quote(found[0], safe='')}"

    def existing():
        return next((i for i in pages(url) if i.get("title") == title), None)
    if issue := existing():
        return f"already filed #{issue['number']}"
    gh("-X", "POST", f"repos/{repo}/issues", "--input", "-",
       data=json.dumps({"title": title, "body": body, "labels": [found[0]]}))
    if issue := existing():
        return f"filed #{issue['number']}"
    raise Stop("unknown: not found on read-back; list the issues before filing again")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("pin", "check", "post"):
        c = sub.add_parser(name)
        if name != "pin":
            c.add_argument("report")
        c.add_argument("--repo", required=True)
        c.add_argument("--pr", required=True, type=int)
    f = sub.add_parser("follow-up")
    for name in ("repo", "ticket", "spec", "pr", "head", "id", "title", "finding"):
        f.add_argument("--" + name, required=True)
    f.add_argument("--logged", choices=("re-check", "final check"))
    f.add_argument("--user-path")
    a = p.parse_args(argv)
    try:
        if a.command == "pin":
            print(pin(a.repo, a.pr))
        elif a.command == "check":
            problems = report_problems(a.report, a.repo, a.pr)[2]
            print("\n".join(problems) if problems else "report ok")
            return 1 if problems else 0
        elif a.command == "post":
            print(post(a.report, a.repo, a.pr))
        else:
            print(follow_up(a))
    except Stop as e:
        print(e)
        return 1
    except Refusal as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
