#!/usr/bin/env python3
"""Read-only dream-cycle inventory for one repository (dream-cycle.v1, DC2).

python3 -I inventory.py <repo> [--days 14] [--pr-idle-days 7] [--limit 20]

<repo> is a local clone path or owner/repo (cloned once into a temporary
folder). Reads are `git` and paginated REST `gh api` only. Prints one compact
JSON object; exits 0 when every section is confirmed, 2 when any read failed
or was partial (that section is `unconfirmed`, never zero), 1 on bad
arguments or an unreadable target. Python standard library only.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

SCHEMA = "openwiz.dream-cycle.inventory.v1"
SLUG = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
REMOTE = re.compile(r"github\.com[:/]+([A-Za-z0-9._-]+/[A-Za-z0-9._-]+?)(?:\.git)?/?$")
TEST_FILE = re.compile(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]*$|_test\.[^/]+$|\.(test|spec)\.[^/]+$")
# (marker, pattern, test files only); decorators and calls anchored to code, not strings.
MARKERS = [
    ("xfail", re.compile(r"^\s*@(pytest\.mark\.xfail|unittest\.expectedFailure)\b|\bpytest\.xfail\("), True),
    ("skip", re.compile(r"^\s*@(pytest\.mark\.skip(if)?|unittest\.skip(If|Unless)?)\b|\b(pytest\.skip|self\.skipTest)\(|"
                        r"^\s*(it|test|describe|context)\.skip\(|^\s*x(it|describe|test)\(|\{\s*skip:\s*true"), True),
    ("todo", re.compile(r"^\s*(it|test|describe)\.todo\(|\{\s*todo:\s*true"), True),
    (".only", re.compile(r"^\s*(it|test|describe|context)\.only\("), True),
    ("ignore", re.compile(r"^\s*#\[ignore(\s*=.*)?\]"), False),
]
PREFILTER = r"skip|xfail|expectedFailure|todo|\.only\(|#\[ignore|x(it|describe|test)\("
GENERATED_DIRS = ("__pycache__", "node_modules", ".pytest_cache", ".mypy_cache", ".tox", "dist", "build", "target")
GENERATED_SUFFIXES = (".pyc", ".pyo", ".class", ".o", ".egg-info", ".DS_Store")


class ReadError(Exception):
    pass


def line(text, cap=200):
    """One printable line, short enough for the contract's non_empty_line."""
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(text)).strip()
    return (text[:cap - 1] + "…" if len(text) > cap else text) or "unknown"


def run(cmd, cwd=None, ok=(0,)):
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=300,
                              encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReadError(f"{cmd[0]} failed: {exc}")
    if proc.returncode not in ok:
        detail = (proc.stderr.strip().splitlines() or [f"exit {proc.returncode}"])[-1]
        raise ReadError(f"{' '.join(cmd[:2])} failed: {detail}")
    return proc.stdout


def git(repo, *args, ok=(0,)):
    return run(["git", "-c", "core.quotePath=false", *args], cwd=repo, ok=ok)


def gh_list(slug, path):
    """All pages of a REST list; concatenated page arrays are joined."""
    if not slug:
        raise ReadError("no GitHub repository: origin is not a github.com remote")
    raw = run(["gh", "api", "--paginate", f"repos/{slug}/{path}"])
    out, pos, dec = [], 0, json.JSONDecoder()
    while True:
        while pos < len(raw) and raw[pos].isspace():
            pos += 1
        if pos == len(raw):
            break
        try:
            page, pos = dec.raw_decode(raw, pos)
        except ValueError:
            raise ReadError(f"gh api repos/{slug}/{path}: response is not JSON")
        if not isinstance(page, list) or not all(isinstance(x, dict) for x in page):
            raise ReadError(f"gh api repos/{slug}/{path}: response is not a list of objects")
        out.extend(page)
    return out


def parse_time(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def stale_paths(repo, cutoff, tracked):
    if git(repo, "rev-parse", "--is-shallow-repository").strip() == "true":
        raise ReadError("shallow clone: history is partial, fetch the full history")
    last = {}
    stamp = None
    for row in git(repo, "log", "--no-renames", "--diff-merges=dense-combined", "--name-only", "--format=%x01%ct", "HEAD").splitlines():
        if row.startswith("\x01"):
            stamp = int(row[1:])
        elif row and row not in last:
            last[row] = stamp
    folders = {}
    for path in tracked:
        if path not in last:
            raise ReadError(f"no commit found for tracked path {line(path, 120)}")
        if last[path] < cutoff.timestamp():
            folder = path.rsplit("/", 1)[0] if "/" in path else "."
            count, oldest = folders.get(folder, (0, last[path]))
            folders[folder] = (count + 1, min(oldest, last[path]))
    items = [{"folder": f, "count": c, "oldest": datetime.fromtimestamp(o, timezone.utc).strftime("%Y-%m-%d")}
             for f, (c, o) in folders.items()]
    items.sort(key=lambda i: (-i["count"], i["oldest"], i["folder"]))
    return sum(c for c, _ in folders.values()), items


def default_branch(repo):
    for args in (("symbolic-ref", "--short", "refs/remotes/origin/HEAD"), ("symbolic-ref", "--short", "HEAD")):
        try:
            name = git(repo, *args).strip()
        except ReadError:
            continue
        return name, (name.split("/", 1)[1] if args[2].startswith("refs/remotes") else name)
    raise ReadError("default branch unknown: no origin/HEAD and HEAD is detached")


def orphan_branches(repo, slug, pulls):
    ref, base = default_branch(repo)
    open_heads = {p.get("head", {}).get("ref") for p in pulls
                  if (p.get("head", {}).get("repo") or {}).get("full_name", slug) == slug}
    seen = {}
    rows = git(repo, "for-each-ref", "--format=%(refname)%09%(committerdate:short)",
               "refs/heads", "refs/remotes/origin").splitlines()
    for row in rows:
        refname, date = row.split("\t")
        name = refname.split("/", 3)[3] if refname.startswith("refs/remotes/") else refname[len("refs/heads/"):]
        if name in ("HEAD", base) or name in open_heads or name in seen:
            continue
        merged = subprocess.run(["git", "merge-base", "--is-ancestor", refname, ref], cwd=repo,
                                capture_output=True).returncode
        if merged not in (0, 1):
            raise ReadError(f"git merge-base failed for branch {line(name, 120)}")
        seen[name] = {"branch": name, "merged": merged == 0, "last_commit": date}
    items = sorted(seen.values(), key=lambda i: (i["merged"], i["last_commit"], i["branch"]))
    return len(items), items


def idle(rows, cutoff, extra=lambda r: {}):
    items = [{"number": r["number"], "title": line(r.get("title", ""), 120), "updated_at": r["updated_at"], **extra(r)}
             for r in rows if parse_time(r["updated_at"]) < cutoff]
    items.sort(key=lambda i: (i["updated_at"], i["number"]))
    return len(items), items


def skipped_tests(repo):
    raw = git(repo, "grep", "-n", "-I", "-E", PREFILTER, "HEAD", "--", ok=(0, 1))  # 1: no match
    items = []
    for row in raw.splitlines():
        _, path, num, text = row.split(":", 3)
        for marker, pattern, tests_only in MARKERS:
            if (not tests_only and path.endswith(".rs")) or (tests_only and TEST_FILE.search(path)):
                if pattern.search(text):
                    items.append({"path": path, "line": int(num), "marker": marker})
                    break
    items.sort(key=lambda i: (i["marker"], i["path"], i["line"]))
    return len(items), items


def generated_files(tracked):
    items = []
    for path in tracked:
        parts = path.split("/")
        kind = next((s for s in GENERATED_SUFFIXES if any(p.endswith(s) for p in parts)), None)
        kind = kind or next((d for d in GENERATED_DIRS if d in parts[:-1]), None)
        if kind:
            items.append({"path": path, "kind": kind})
    items.sort(key=lambda i: (i["kind"], i["path"]))
    return len(items), items


def resolve(target, workdir):
    """Return (local clone path, owner/repo or None); raise ReadError if unreadable."""
    if os.path.isdir(target):
        top = git(target, "rev-parse", "--show-toplevel").strip()
        git(top, "rev-parse", "--verify", "-q", "HEAD^{commit}")
        try:
            match = REMOTE.search(git(top, "remote", "get-url", "origin").strip())
        except ReadError:
            match = None
        return top, (match.group(1) if match else None)
    if SLUG.match(target):
        dest = os.path.join(workdir, "clone")
        run(["gh", "repo", "clone", target, dest, "--", "--quiet", "--no-checkout"])
        return dest, target
    raise ReadError(f"not a local git clone or owner/repo: {line(target, 120)}")


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        print(f"inventory.py: {message}", file=sys.stderr)
        sys.exit(1)


def positive(text):
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {value}")
    return value


def main(argv=None):
    parser = Parser(prog="inventory.py", description="Read-only dream-cycle inventory for one repository.")
    parser.add_argument("repo", help="Local clone path or owner/repo.")
    parser.add_argument("--days", type=positive, default=14, help="Staleness window in days (default: 14).")
    parser.add_argument("--pr-idle-days", type=positive, default=7, help="Idle pull request window in days (default: 7).")
    parser.add_argument("--limit", type=positive, default=20, help="Maximum top items per section (default: 20).")
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    cutoff, pr_cutoff = now - timedelta(days=args.days), now - timedelta(days=args.pr_idle_days)

    with tempfile.TemporaryDirectory(prefix="dream-inventory-") as workdir:
        try:
            repo, slug = resolve(args.repo, workdir)
            tracked = git(repo, "ls-tree", "-r", "--name-only", "HEAD").splitlines()
        except ReadError as exc:
            print(f"inventory.py: unreadable target: {exc}", file=sys.stderr)
            return 1

        reads = {}

        def read(name, fn):
            try:
                reads[name] = fn()
            except ReadError as exc:
                reads[name] = exc
            except (KeyError, TypeError, ValueError) as exc:
                reads[name] = ReadError(f"unexpected data: {exc!r}")
            return reads[name]

        pulls = read("pulls", lambda: gh_list(slug, "pulls?state=open&per_page=100"))
        issues = read("issues", lambda: [i for i in gh_list(slug, "issues?state=open&per_page=100")
                                         if "pull_request" not in i])
        miles = read("milestones", lambda: gh_list(slug, "milestones?state=open&per_page=100"))

        def needs(value, fn):
            if isinstance(value, ReadError):
                raise value
            return fn(value)

        read("stale_paths", lambda: stale_paths(repo, cutoff, tracked))
        read("orphan_branches", lambda: needs(pulls, lambda p: orphan_branches(repo, slug, p)))
        read("idle_issues", lambda: needs(issues, lambda i: idle(i, cutoff)))
        read("idle_prs", lambda: needs(pulls, lambda p: idle(p, pr_cutoff, lambda r: {"branch": r["head"]["ref"]})))
        read("empty_milestones", lambda: needs(miles, lambda ms: (lambda items: (len(items), items))(
            [{"number": m["number"], "title": line(m["title"], 120), "closed_issues": m.get("closed_issues", 0)}
             for m in ms if m["open_issues"] == 0])))
        read("skipped_tests", lambda: skipped_tests(repo))
        read("generated_files", lambda: generated_files(tracked))

    names = ["stale_paths", "orphan_branches", "idle_issues", "idle_prs",
             "empty_milestones", "skipped_tests", "generated_files"]
    sections, unconfirmed = {}, []
    for name in names:
        value = reads[name]
        if isinstance(value, ReadError):
            reason = line(value)
            sections[name] = {"status": "unconfirmed", "total": None, "items": [], "reason": reason}
            unconfirmed.append({"source": name, "reason": reason})
        else:
            total, items = value
            sections[name] = {"status": "ok", "total": total, "items": items[:args.limit], "reason": None}
    print(json.dumps({
        "schema": SCHEMA, "repo": slug or line(os.path.basename(repo), 120), "days": args.days,
        "pr_idle_days": args.pr_idle_days, "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sections": sections, "unconfirmed": unconfirmed,
    }, ensure_ascii=False, separators=(",", ":")))
    return 2 if unconfirmed else 0


if __name__ == "__main__":
    sys.exit(main())
