#!/usr/bin/env python3
import argparse
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_CHECKER = "tools/comment-check/check.py"
REPORT = re.compile(r"^(.*):(\d+): (comment|escape-tag-reason|external-link|directive-reason|unreadable): ")
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
WORKAROUND = re.compile(r"\b(todo|fixme|xxx|hack|workaround|work around|kludge|for now|temporar\w*"
                        r"|do not (remove|move|touch|change)|don'?t (remove|move|touch|change)|important)\b", re.I)
JUSTIFICATION = re.compile(r"\b(because|on purpose|intentional\w*|deliberate\w*|so that|in order to|needed|needs to"
                           r"|otherwise|keep this|we (do|use|check|need|keep)|the reason|why)\b", re.I)
ALLOWED = [
    ("licence", re.compile(r"SPDX-License-Identifier:|\bCopyright\b|\bLicensed under\b")),
    ("external", re.compile(r"(#|//|/\*|<!--)\s*External:")),
    ("warning", re.compile(r"(#|//|/\*|<!--)\s*(SECURITY|SAFETY|PRIVACY|DATA LOSS):\s*\S")),
    ("private-record pointer", re.compile(r"https://github\.com/jparker2006/ClosedWiz/(issues|pull)/\d+#issuecomment-\d+")),
    ("escape", re.compile(r"(#|//|/\*|<!--)\s*comment-ok:\s*\S")),
    ("suppression", re.compile(r"(#|//)\s*(noqa|type: ignore|pylint:|eslint|shellcheck|ruff:|mypy:|pyright:"
                               r"|@ts-\w+|biome-ignore|prettier-ignore)\b.*\s(--|#)\s+\S")),
]
FIX = {
    "justification": "make the code say it: a clearer name, an extracted function, a type or a test that pins "
                     "the behaviour, then delete the comment",
    "workaround": "fix the cause, or turn the rule it guards into a test or a check (red first), then delete "
                  "the comment",
    "suppression": "remove the switch and fix the cause it hid; only a style rule keeps a switch, with "
                   "` -- <reason>`",
    "external-link": "link the outside source that shows the constraint, or turn the rule into a check and "
                     "delete the comment",
    "escape-tag-reason": "delete it, or turn what it meant into a name, a test or a check",
    "comment": "delete it, or turn what it meant into a name, a test or a check",
    "unreadable": "read the file yourself: the checker could not",
}


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout


def line_at(repo, head, path, number):
    if path.startswith('"'):
        return ""
    try:
        lines = git(repo, "show", f"{head}:{path}").decode("utf-8").splitlines()
    except (subprocess.CalledProcessError, UnicodeDecodeError):
        return ""
    return lines[number - 1].strip() if 0 < number <= len(lines) else ""


def kind_of(reason, text):
    if reason == "directive-reason":
        return "suppression"
    if reason != "comment":
        return reason
    if WORKAROUND.search(text):
        return "workaround"
    return "justification" if JUSTIFICATION.search(text) else "comment"


def added_lines(repo, base, head):
    names = git(repo, "diff", "-z", "--name-only", "--diff-filter=AMR", f"{base}...{head}").split(b"\0")
    for raw in filter(None, names):
        path = raw.decode("utf-8", "replace")
        patch = git(repo, "diff", "-U0", f"{base}...{head}", "--", f":(literal){path}").decode("utf-8", "replace")
        number = None
        for line in patch.splitlines():
            if (hunk := HUNK.match(line)):
                number = int(hunk.group(1))
            elif number is not None and line.startswith("+"):
                yield path, number, line[1:]
                number += 1


def comment_pass(repo, checker, base, head, docs, exclude):
    command = [sys.executable, "-I", str(checker), "diff", "--base", base, "--head", head]
    for path in docs:
        command += ["--docs", path]
    for pattern in exclude:
        command += ["--exclude", pattern]
    run = subprocess.run(command, cwd=repo, capture_output=True, text=True)
    if run.returncode not in (0, 1):
        return [f"unreadable: the checker exited {run.returncode}: {(run.stderr or run.stdout).strip()}"], [], 2
    findings, flagged = [], set()
    for line in run.stdout.splitlines():
        report = REPORT.match(line)
        if not report:
            continue
        path, number, reason = report.group(1), int(report.group(2)), report.group(3)
        flagged.add((path, number))
        text = line_at(repo, head, path, number)
        kind = kind_of(reason, text)
        excerpt = text if len(text) <= 80 else text[:77] + "..."
        findings.append(f"{path}:{number}: {kind}: {excerpt} Fix: {FIX[kind]}.")
    checks = []
    for path, number, text in added_lines(repo, base, head):
        if (path, number) in flagged:
            continue
        kind = next((name for name, form in ALLOWED if form.search(text)), None)
        if kind:
            checks.append(f"check {path}:{number}: {kind}: {text.strip()[:80]}")
    return findings, checks, 1 if findings else 0


def main():
    parser = argparse.ArgumentParser(description=(
        "review-ticket's comment pass: runs the reviewed repository's comments checker in diff mode between the "
        "pull request's base and head, prints each block it reports as a finding with its code fix, and a check "
        "line for each added line that wears an allowed form. Exits 1 with findings, 0 without, 2 when the "
        "checker or Git fails, 3 when there is no checker."))
    parser.add_argument("--base", required=True, help="the pull request's base revision")
    parser.add_argument("--head", default="HEAD", help="the pull request's head revision")
    parser.add_argument("--repo", default=".", help="the reviewed repository's checkout")
    parser.add_argument("--checker", help=f"the checker to run, if not the repository's {DEFAULT_CHECKER}")
    parser.add_argument("--docs", action="append", default=[], help="passed to the checker (repeatable)")
    parser.add_argument("--exclude", action="append", default=[], help="passed to the checker (repeatable)")
    args = parser.parse_args()
    repo = Path(args.repo).resolve()
    checker = Path(args.checker).resolve() if args.checker else repo / DEFAULT_CHECKER
    if not checker.is_file():
        if args.checker:
            print(f"no checker: {args.checker} is not a file; read the diff's comments yourself")
        else:
            print(f"no checker: {DEFAULT_CHECKER} is missing here and no --checker was given; "
                  "read the diff's comments yourself")
        return 3
    try:
        findings, checks, code = comment_pass(repo, checker, args.base, args.head, args.docs, args.exclude)
    except subprocess.CalledProcessError as error:
        print(f"unreadable: git failed: {error.stderr.decode('utf-8', 'replace').strip()}")
        return 2
    for line in findings + checks:
        print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
