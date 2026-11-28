import atexit
import base64
import json
import os
import re
import shlex
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

HELPER = Path(__file__).with_name("review.py")
SKILLS = "example/skills"
PRODUCT = "example/product"


def template():
    root = Path(tempfile.mkdtemp())
    atexit.register(subprocess.run, ["rm", "-rf", str(root)])

    def git(*args):
        return subprocess.run(["git", "-C", str(root), "-c", "user.name=Builder", "-c",
                               "user.email=builder@example.com", *args],
                              check=True, capture_output=True, text=True).stdout.strip()

    def commit(message, files, branch):
        for name, text in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text)
        git("add", "-A")
        git("commit", "-qm", message)
        git("branch", "-f", branch)
        return git("rev-parse", "HEAD")
    git("init", "-q", "-b", "main")
    base = commit("base", {"README.md": "pantry\n"}, "base")
    old = commit("export", {"src/export.rs": "fn export() {}\n", "src/cli.rs": "fn main() {}\n"}, "old")
    head = commit("refuse overwrite", {"src/export.rs": "fn export() { refuse(); }\n"}, "head")
    newer = commit("newer", {"src/export.rs": "fn export() { refuse(); redact(); }\n"}, "newer")
    git("checkout", "-q", base)
    main = commit("vendor", {f"vendor/v{n}.rs": f"// {n}\n" for n in range(320)}, "main")
    git("checkout", "-q", head)
    git("merge", "-q", "--no-edit", "main")
    git("branch", "-f", "merged")
    merged = git("rev-parse", "HEAD")
    unrelated = git("commit-tree", git("rev-parse", "base^{tree}"), "-m", "replaced history")
    git("branch", "-f", "unrelated", unrelated)
    return root, base, old, head, newer, main, merged, unrelated


ORIGIN, BASE, OLD, HEAD, NEWER, MAIN, MERGED, UNRELATED = template()
FLEET = """# Fleet settings

## CI checks

| Check | Runs | Required by fleet on |
| --- | --- | --- |
| `check` | Every suite | Pull requests to `main` |

## GitHub identity

| Setting | Value |
| --- | --- |
| Record authors | `example[bot]`, `owner` |
"""
LABELS = """| Role | Label here | Meaning |
| --- | --- | --- |
| `needs-triage` | `triage: new` | Sort it |
| `needs-info` | `needs-info` | Waiting |
"""
DESCRIPTION = """Closes example/product#41

## Summary

Export writes one zip.

## Rulings

1. Name the zip cookbook.zip. Why: the importer reads that name. Cost if wrong: low: one rename.

## Facts

- **Head:** `bbbb`
"""
FULL = f"""VERDICT: CHANGES at {OLD}

Full review by Codex, Sol 6.2, Medium. CI green on this commit: check.

Intent: export writes the whole cookbook to one zip and refuses to overwrite.

- **R1 [blocking]** `src/export.rs:48` (Spec) An existing zip is overwritten. Fix: refuse with status 3.
  Class: files
  User path: a cook exports twice; the first export is lost.
- **R2 [polish]** `src/cli.rs:30` (Sweep) Help wording. Fix: say export. Polish issue: #58.
- **R3 [blocking]** `src/export.rs:71` (Sweep) Token written to the log. Fix: redact it.
  Class: credential
  Risk: privacy: a cook's sync token reaches a shared log.

- **Ruling 1** upheld: the importer reads cookbook.zip.

Disproved: 0 candidate findings dropped.

Checked: Standards (AGENTS.md), Spec (#41, spec #38), full sweep. Ran: `cargo test` (31 passed).

Next: the builder fixes or disputes R1 and R3 once, then one re-check.
"""
RECHECK = f"""VERDICT: APPROVE at {HEAD}

Re-check of R1, R3 and the code changed since aaaaaaa, by Codex, Sol 6.2, Medium. CI green on this commit: check.

Intent: export writes the whole cookbook to one zip and refuses to overwrite.

- **R1 [blocking]** still open after the re-check: the web export still overwrites. Logged as follow-up #61.
  Class: files
  User path: a cook exports twice from the web page; the first export is lost.
- **R2 [polish]** Polish issue: #58.
- **R3 [blocking]** resolved at bbbbbbb: the log line is redacted.
  Class: credential
- **R4 [polish]** `src/export.rs:52` (Sweep) Typo. Fix: file exists. Polish issue: #60.

- **Ruling 1** upheld: the importer reads cookbook.zip.

Disproved: 0 candidate findings dropped.

Checked: R1, R3 and the changed code. Ran: `cargo test` (33 passed).

Next: none open. It merges by the project's merge rules.
"""
LATE_PRE = ("- **R5 [pre-existing]** `src/cli.rs:12` (Sweep) Help exits 0 on a bad flag. Fix: exit 2. "
            "Pre-existing issue: #62.\n  Late: the first review read the CLI only for the export flag.")
FAKE_GH = r'''#!/usr/bin/env python3
import base64, json, os, sys
from pathlib import Path
path = Path(os.environ["FIXTURE"])
w = json.loads(path.read_text())
args = sys.argv[1:]
w["calls"].append(args)
def done(value, code=0):
    path.write_text(json.dumps(w))
    if value is not None:
        print(json.dumps(value))
    sys.exit(code)
if args[:1] != ["api"]:
    done(None, 3)
fields = [args[i + 1] for i, a in enumerate(args) if a == "-f"]
url = [a for a in args[1:] if not a.startswith("-") and a not in ("POST", *fields)][-1]
post = "POST" in args
parts = url.split("?")[0].split("/")
repo = "/".join(parts[1:3])
if post:
    payload = {} if fields else json.loads(sys.stdin.read())
    for field in fields:
        key, _, value = field.partition("=")
        if key.endswith("[]"):
            payload.setdefault(key[:-2], []).append(value)
        else:
            payload[key] = value
    if parts[3:4] == ["issues"] and len(parts) == 6:
        w["writes"] += 1
        if w.get("fail_post"):
            done(None, 1)
        item = {"id": 900 + len(w["comments"].get(repo + "#" + parts[4], [])),
                "body": payload["body"], "user": {"login": "example[bot]"}}
        w["comments"].setdefault(repo + "#" + parts[4], []).append(item)
        done(None if w.get("lose") else item, 1 if w.get("lose") else 0)
    w["writes"] += 1
    issues = w["issues"].setdefault(repo, [])
    item = {"number": 70 + len(issues), "title": payload["title"], "body": payload["body"],
            "labels": [{"name": n} for n in payload.get("labels", [])]}
    issues.append(item)
    done(None if w.get("lose") else item, 1 if w.get("lose") else 0)
if len(parts) == 3:
    done({"full_name": repo, "default_branch": "main"})
if parts[3] == "pulls":
    if w.get("pull_sequence"):
        done(w["pull_sequence"].pop(0))
    pr = w["pulls"].get(parts[4])
    done(pr, 0) if pr else done(None, 1)
if parts[3:5] == ["issues", "comments"]:
    found = [c for cs in w["comments"].values() for c in cs if str(c["id"]) == parts[5]]
    done(found[0]) if found else done(None, 1)
if parts[3] == "contents":
    ref = url.split("?ref=")[1]
    text = w["files"].get(repo + "@" + ref + ":" + "/".join(parts[4:]))
    if text is None:
        done(None, 1)
    done({"encoding": "base64", "content": base64.b64encode(text.encode()).decode()})
if parts[3] == "commits":
    done({"check_runs": w["checks"].get(parts[4], [])})
if parts[3] == "compare":
    found = w["compare"].get(parts[4])
    done({"files": [{"filename": f} for f in found]}) if found is not None else done(None, 1)
if parts[3] == "issues" and len(parts) == 6:
    w.update(w.pop("after_comments", {}))
    done([w["comments"].get(repo + "#" + parts[4], [])])
if parts[3] == "issues" and len(parts) == 4:
    if w["writes"] and w.get("hidden_issue_reads", 0):
        w["hidden_issue_reads"] -= 1
        done([[]])
    done([w["issues"].get(repo, [])])
done(None, 4)
'''


def green(sha):
    return {sha: [{"name": "check", "status": "completed", "conclusion": "success"}]}


def report(body, login="example[bot]"):
    return {"id": 800, "body": body, "user": {"login": login}}


class Review(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(0o755)
        self.fixture = root / "world.json"
        self.env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "FIXTURE": str(self.fixture),
                    "XDG_STATE_HOME": str(root / "state")}
        self.root = root
        self.repo = root / "repo"
        subprocess.run(["git", "clone", "-q", "--no-local", str(ORIGIN), str(self.repo)], check=True)
        self.world({})

    def tearDown(self):
        self.dir.cleanup()

    def world(self, changes, *, pr=None, comments=None):
        for n, c in enumerate(comments or []):
            c["id"] = 800 + n
        w = {
            "calls": [], "writes": 0, "issues": {},
            "pulls": {"7": {"number": 7, "state": "open", "draft": False, "merged": False,
                            "body": DESCRIPTION, "head": {"sha": HEAD},
                            "base": {"ref": "main", "sha": BASE, "repo": {"full_name": SKILLS}}, **(pr or {})}},
            "files": {f"{SKILLS}@main:docs/agents/fleet.md": FLEET,
                      f"{PRODUCT}@main:docs/agents/triage-labels.md": LABELS},
            "checks": green(HEAD),
            "comments": {f"{SKILLS}#7": comments or []},
        }
        w.update(changes)
        self.fixture.write_text(json.dumps(w))

    def state(self):
        return json.loads(self.fixture.read_text())

    def run_helper(self, *args, stdin=None, cwd=None):
        if args[0] in ("pin", "check", "post") and "--head" not in args:
            args = (*args, "--head", self.state()["pulls"]["7"]["head"]["sha"])
        return subprocess.run([sys.executable, "-I", str(HELPER), *args], input=stdin, text=True,
                              capture_output=True, env=self.env, timeout=30, cwd=cwd or self.repo)

    def file(self, name, text):
        path = self.root / name
        path.write_text(text)
        return str(path)

    def test_first_review_pins_the_head_and_its_ticket(self):
        out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(),
                         f"review full #7 at {HEAD}; ticket {PRODUCT}#41; checks check")

    def test_required_check_not_green_stops(self):
        cases = {
            "pending": {HEAD: [{"name": "check", "status": "in_progress", "conclusion": None}]},
            "failed": {HEAD: [{"name": "check", "status": "completed", "conclusion": "failure"}]},
            "missing": {HEAD: [{"name": "lint", "status": "completed", "conclusion": "success"}]},
            "old head": green(OLD),
        }
        for name, checks in cases.items():
            with self.subTest(name):
                self.world({"checks": checks})
                out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
                self.assertEqual(out.returncode, 1)
                self.assertTrue(out.stdout.startswith("stop: check is not green at " + HEAD), out.stdout)

    def test_settings_come_from_the_base_branch(self):
        relaxed = FLEET.replace("| `check` | Every suite | Pull requests to `main` |\n", "")
        self.world({"files": {f"{SKILLS}@main:docs/agents/fleet.md": FLEET,
                              f"{SKILLS}@{HEAD}:docs/agents/fleet.md": relaxed},
                    "checks": {HEAD: []}})
        out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
        self.assertEqual(out.returncode, 1)
        self.assertIn("check is not green", out.stdout)
        reads = [c[-1] for c in self.state()["calls"] if "/contents/" in c[-1]]
        self.assertEqual(reads, [f"repos/{SKILLS}/contents/docs/agents/fleet.md?ref=main"])

    def test_draft_closed_and_ticketless_pull_requests_stop(self):
        cases = {
            "draft": ({"draft": True}, "stop: draft"),
            "closed": ({"state": "closed"}, "stop: closed; archive your own thread"),
            "merged": ({"state": "closed", "merged": True}, "stop: merged; archive your own thread"),
            "no ticket": ({"body": "## Summary\n\nNo closing line.\n"}, "stop: no Closes line names a ticket"),
        }
        for name, (pr, expected) in cases.items():
            with self.subTest(name):
                self.world({}, pr=pr)
                out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
                self.assertEqual(out.returncode, 1)
                self.assertEqual(out.stdout.strip(), expected)

    def test_an_assigned_ticket_is_taken_only_from_its_exact_refs_line(self):
        refs = DESCRIPTION.replace("Closes example/product#41", "Refs example/product#41")
        self.world({}, pr={"body": refs})
        out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7", "--ticket", f"{PRODUCT}#41")
        self.assertEqual((out.returncode, out.stdout.strip()),
                         (0, f"review full #7 at {HEAD}; ticket {PRODUCT}#41; checks check"), out.stderr)
        out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
        self.assertEqual((out.returncode, out.stdout.strip()), (1, "stop: no Closes line names a ticket"))
        self.world({}, pr={"body": refs.replace("\n", "\r\n")})
        out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7", "--ticket", f"{PRODUCT}#41")
        self.assertEqual(out.stdout.strip(), f"review full #7 at {HEAD}; ticket {PRODUCT}#41; checks check")
        both = "Closes example/skills#9\n" + refs
        self.world({}, pr={"body": both})
        out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7", "--ticket", f"{PRODUCT}#41")
        self.assertEqual(out.stdout.strip(), f"review full #7 at {HEAD}; ticket {PRODUCT}#41; checks check")
        stop = f"stop: no Refs {PRODUCT}#41 line names the assigned ticket"
        for name, body in {"other number": refs.replace("#41", "#42"), "unqualified": refs.replace(PRODUCT, ""),
                           "other repository": refs.replace(PRODUCT, SKILLS), "more on the line":
                           refs.replace("#41", "#41 and #42"), "inside a sentence": "See Refs example/product#41.\n",
                           "only a Closes line": DESCRIPTION}.items():
            with self.subTest(name):
                self.world({}, pr={"body": body})
                out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7", "--ticket", f"{PRODUCT}#41")
                self.assertEqual((out.returncode, out.stdout.strip()), (1, stop))
        for bad in ("#41", "example/product", "example/product#0", "example/product#41 ", "example_org/product#41",
                    "ex\u00e4mple/product#41", "-example/product#41", "example-/product#41", "exa--mple/product#41",
                    "example/prod\u00fcct#41"):
            with self.subTest(bad):
                self.world({}, pr={"body": refs.replace(f"{PRODUCT}#41", bad)})
                out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7", f"--ticket={bad}")
                self.assertEqual((out.returncode, out.stdout), (2, ""))
                self.assertIn("--ticket must be OWNER/NAME#N", out.stderr)
                self.assertEqual(self.state()["calls"], [])

    def test_check_and_post_take_the_assigned_ticket_from_its_refs_line(self):
        refs = DESCRIPTION.replace("Closes example/product#41", "Refs example/product#41")
        self.world({"checks": green(OLD)}, pr={"head": {"sha": OLD}, "body": refs})
        path = self.file("r.md", FULL)
        for command in ("check", "post"):
            with self.subTest(command):
                out = self.run_helper(command, path, "--repo", SKILLS, "--pr", "7")
                self.assertEqual((out.returncode, out.stdout.strip()), (1, "stop: no Closes line names a ticket"))
        out = self.run_helper("post", path, "--repo", SKILLS, "--pr", "7", "--ticket", f"{PRODUCT}#42")
        self.assertEqual((out.returncode, out.stdout.strip()),
                         (1, f"stop: no Refs {PRODUCT}#42 line names the assigned ticket"))
        self.assertEqual(self.state()["writes"], 0)
        out = self.run_helper("check", path, "--repo", SKILLS, "--pr", "7", "--ticket", f"{PRODUCT}#41")
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "report ok"), out.stdout + out.stderr)
        out = self.run_helper("post", path, "--repo", SKILLS, "--pr", "7", "--ticket", f"{PRODUCT}#41")
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "posted 900"), out.stdout + out.stderr)
        self.assertEqual(self.state()["writes"], 1)

    def test_missing_or_malformed_record_authors_trust_nobody(self):
        for name, row in {"absent": "", "empty": "| Record authors | |\n",
                          "malformed": "| Record authors | everyone |\n"}.items():
            with self.subTest(name):
                fleet = FLEET.replace("| Record authors | `example[bot]`, `owner` |\n", row)
                self.world({"files": {f"{SKILLS}@main:docs/agents/fleet.md": fleet}})
                out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
                self.assertEqual(out.returncode, 2)
                self.assertIn("record authors", out.stderr)
                self.assertEqual(out.stdout, "")

    def test_a_verdict_from_anyone_else_is_ignored(self):
        self.world({}, comments=[report(FULL.replace(OLD, HEAD), login="stranger")])
        out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
        self.assertEqual(out.stdout.split(";")[0], f"review full #7 at {HEAD}")

    def test_recheck_names_last_read_open_ids_and_next_id(self):
        self.world({}, comments=[report(FULL)])
        out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(),
                         f"review re-check #7 at {HEAD}; ticket {PRODUCT}#41; checks check; "
                         f"last read {OLD}; open R1 and R3; next id R4")

    def test_approval_never_carries_to_a_new_head(self):
        self.world({"checks": green(NEWER)}, pr={"head": {"sha": NEWER}}, comments=[report(FULL), report(RECHECK)])
        out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(out.stdout.startswith(f"review re-check #7 at {NEWER}"), out.stdout)
        self.assertIn(f"last read {HEAD}; open none; next id R5", out.stdout)

    def test_fresh_round_leads_to_a_final_check_and_park_stops(self):
        fresh = RECHECK.replace("VERDICT: APPROVE", "VERDICT: CHANGES").replace(
            "- **R3 [blocking]** resolved at bbbbbbb: the log line is redacted.",
            "- **R3 [blocking]** still open after the re-check: still logged.\n"
            "  Risk: privacy: a cook's sync token reaches a shared log.").replace(
            "Next: none open. It merges by the project's merge rules.",
            "Next: a fresh, stronger builder fixes R3 once, then one final check.")
        self.world({"checks": green(NEWER)}, pr={"head": {"sha": NEWER}}, comments=[report(FULL), report(fresh)])
        out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
        self.assertTrue(out.stdout.startswith(f"review final #7 at {NEWER}"), out.stdout)
        self.assertIn("open R3", out.stdout)
        parked = fresh.replace(HEAD, NEWER).replace(
            "Next: a fresh, stronger builder fixes R3 once, then one final check.",
            "Next: park R3 as a decision for Jake.")
        self.world({"checks": green(NEWER)}, pr={"head": {"sha": NEWER}},
                   comments=[report(FULL), report(fresh), report(parked)])
        out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
        self.assertEqual(out.returncode, 1)
        self.assertEqual(out.stdout.strip(), "stop: R3 is parked as a decision for Jake")

    def test_a_report_at_this_head_is_not_repeated(self):
        self.world({}, comments=[report(FULL.replace(OLD, HEAD))])
        out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
        self.assertEqual(out.returncode, 1)
        self.assertEqual(out.stdout.strip(), f"stop: already reported at {HEAD}")

    def test_valid_reports_pass(self):
        self.world({"checks": green(OLD)}, pr={"head": {"sha": OLD}})
        out = self.run_helper("check", self.file("full.md", FULL), "--repo", SKILLS, "--pr", "7")
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "report ok"), out.stdout + out.stderr)
        self.world({}, comments=[report(FULL)])
        out = self.run_helper("check", self.file("recheck.md", RECHECK), "--repo", SKILLS, "--pr", "7")
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "report ok"), out.stdout + out.stderr)

    def test_full_review_report_problems(self):
        self.world({"checks": green(OLD)}, pr={"head": {"sha": OLD}})
        cases = {
            "wrong head": (FULL.replace(f"CHANGES at {OLD}", f"CHANGES at {NEWER}"),
                           f"VERDICT names {NEWER}, not the pinned head {OLD}"),
            "blocker without its line": (FULL.replace("  User path: a cook exports twice; the first export is lost.\n", ""),
                                         "R1: a new blocking finding needs its User path: or Risk: line"),
            "polish without issue": (FULL.replace(" Polish issue: #58.", ""),
                                     "R2: a new polish finding ends with Polish issue: #<n>"),
            "approve with open blocker": (FULL.replace("VERDICT: CHANGES", "VERDICT: APPROVE"),
                                          "VERDICT is CHANGES exactly while a blocker is open"),
            "next names wrong ids": (FULL.replace("R1 and R3 once", "R1 once"),
                                     "Next: names R1, but the open blockers are R1 and R3"),
            "unmarked ruling": (FULL.replace("- **Ruling 1** upheld: the importer reads cookbook.zip.\n", ""),
                                "Ruling 1: listed in the description but not marked"),
            "unknown ruling": (FULL.replace("- **Ruling 1** upheld", "- **Ruling 1** upheld: ok.\n- **Ruling 2** upheld"),
                               "Ruling 2: marked but not listed in the description"),
            "fresh at a full review": (FULL.replace("Next: the builder fixes or disputes R1 and R3 once, then one re-check.",
                                                    "Next: a fresh, stronger builder fixes R3 once, then one final check."),
                                       "a full review's Next: is the builder line or none open"),
            "ids out of order": (FULL.replace("**R3 [blocking]**", "**R4 [blocking]**").replace("R1 and R3", "R1 and R4"),
                                 "ids run R1, R2, ... with no gap or repeat"),
            "wrong second line": (FULL.replace("Full review by", "Re-check of R1 by"),
                                  "the second paragraph starts Full review by"),
            "no intent": (FULL.replace("Intent: ", "Aim: "), "no Intent: paragraph"),
        }
        for name, (text, problem) in cases.items():
            with self.subTest(name):
                out = self.run_helper("check", self.file("r.md", text), "--repo", SKILLS, "--pr", "7")
                self.assertEqual(out.returncode, 1, out.stdout)
                self.assertIn(problem, out.stdout.splitlines())

    def test_recheck_report_problems(self):
        self.world({}, comments=[report(FULL)])
        cases = {
            "user path left open": (RECHECK.replace(" Logged as follow-up #61.", "").replace(
                "VERDICT: APPROVE", "VERDICT: CHANGES").replace(
                "Next: none open. It merges by the project's merge rules.",
                "Next: a fresh, stronger builder fixes R1 once, then one final check."),
                "R1: only a Risk: blocker goes to the fresh round; log a User path: blocker"),
            "risk logged": (RECHECK.replace("- **R3 [blocking]** resolved at bbbbbbb: the log line is redacted.",
                                            "- **R3 [blocking]** still open after the re-check: no. Logged as follow-up #62.\n"
                                            "  Risk: privacy: a cook's sync token reaches a shared log."),
                            "R3: a Risk: blocker is never logged"),
            "earlier id dropped": (RECHECK.replace("- **R2 [polish]** Polish issue: #58.\n", ""),
                                   "R2: a re-check gives every earlier id its status"),
            "earlier id as new": (RECHECK.replace("- **R3 [blocking]** resolved at bbbbbbb: the log line is redacted.",
                                                  "- **R3 [polish]** `a.rs:1` (Sweep) New thing. Fix: x. Polish issue: #63."),
                                  "R3: an earlier id takes a status, not a new finding"),
            "builder line at re-check": (RECHECK.replace(" Logged as follow-up #61.", "").replace(
                "VERDICT: APPROVE", "VERDICT: CHANGES").replace(
                "Next: none open. It merges by the project's merge rules.",
                "Next: the builder fixes or disputes R1 once, then one re-check."),
                "a re-check's Next: is the fresh line or none open"),
        }
        for name, (text, problem) in cases.items():
            with self.subTest(name):
                out = self.run_helper("check", self.file("r.md", text), "--repo", SKILLS, "--pr", "7")
                self.assertEqual(out.returncode, 1, out.stdout)
                self.assertIn(problem, out.stdout.splitlines())

    def test_private_material_is_refused(self):
        self.world({"checks": green(OLD)}, pr={"head": {"sha": OLD}})
        for name, leak in {"token": "ghp_" + "A1b2C3d4E5f6G7h8", "thread": "thr_" + "a1b2c3d4"}.items():
            with self.subTest(name):
                text = FULL.replace("Ran: `cargo test`", f"Ran: `cargo test` {leak}")
                out = self.run_helper("check", self.file("r.md", text), "--repo", SKILLS, "--pr", "7")
                self.assertIn("private material: a token or thread id", out.stdout.splitlines())

    def test_a_recheck_raises_new_findings_only_in_changed_code_or_as_a_stated_risk(self):
        self.world({}, comments=[report(FULL)])
        unchanged = "- **R4 [polish]** `src/cli.rs:12` (Sweep) Typo. Fix: file exists. Polish issue: #60."
        risk = ("- **R4 [blocking]** `src/cli.rs:12` (Sweep) The sync token is printed. Fix: redact it.\n"
                "  Class: credential\n  Risk: privacy: a cook's sync token reaches the terminal log.")
        fresh = ("VERDICT: CHANGES", "Next: a fresh, stronger builder fixes R4 once, then one final check.")
        old_r4 = "- **R4 [polish]** `src/export.rs:52` (Sweep) Typo. Fix: file exists. Polish issue: #60."
        merge = ("VERDICT: APPROVE", "Next: none open. It merges by the project's merge rules.")
        refused = (f"R4: `src/cli.rs` is unchanged since {OLD[:7]}; a re-check raises a new finding there "
                   "only as a Risk: security, privacy or data-loss blocker")
        cases = {
            "polish on unchanged code": (unchanged, merge, 1, refused),
            "polish with risk on unchanged code": (unchanged + "\n  Risk: privacy: the token reaches the log.",
                                                  merge, 1, refused),
            "user path on unchanged code": (risk.replace("Risk: privacy: a cook's sync token reaches the terminal log.",
                                                         "User path: a cook sees the token in the terminal."),
                                            fresh, 1, refused),
            "stated risk on unchanged code": (risk + "\n  Late: the first review never opened the CLI.", fresh, 0,
                                              "report ok; late: 1; held back: 0"),
            "polish on changed code": (old_r4, merge, 0, "report ok"),
        }
        for name, (line, (verdict, nxt), code, expected) in cases.items():
            with self.subTest(name):
                text = (RECHECK.replace(old_r4, line).replace("VERDICT: APPROVE", verdict)
                        .replace("Next: none open. It merges by the project's merge rules.", nxt))
                out = self.run_helper("check", self.file("r.md", text), "--repo", SKILLS, "--pr", "7")
                self.assertEqual(out.returncode, code, out.stdout + out.stderr)
                self.assertIn(expected, out.stdout.splitlines())

    def test_a_recheck_after_a_large_main_merge_reads_only_the_pull_requests_own_changes(self):
        merged = RECHECK.replace(f"APPROVE at {HEAD}", f"APPROVE at {MERGED}")
        self.world({"checks": green(MERGED), "compare": {f"{OLD}...{MERGED}": [
            "src/export.rs", *(f"vendor/v{n}.rs" for n in range(320))]}},
            pr={"head": {"sha": MERGED}, "base": {"ref": "main", "sha": MAIN}}, comments=[report(FULL)])
        out = self.run_helper("check", self.file("r.md", merged), "--repo", SKILLS, "--pr", "7")
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "report ok"), out.stdout + out.stderr)
        for path in ("vendor/v7.rs", "src/cli.rs"):
            with self.subTest(path):
                line = f"- **R4 [polish]** `{path}:1` (Sweep) Typo. Fix: file exists. Polish issue: #60."
                text = merged.replace(
                    "- **R4 [polish]** `src/export.rs:52` (Sweep) Typo. Fix: file exists. Polish issue: #60.", line)
                out = self.run_helper("check", self.file("r.md", text), "--repo", SKILLS, "--pr", "7")
                self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
                self.assertEqual(out.stdout.splitlines(), [
                    f"R4: `{path}` is unchanged since {OLD[:7]}; a re-check raises a new finding there "
                    "only as a Risk: security, privacy or data-loss blocker"])

    def test_a_recheck_counts_a_moved_submodule_pointer_that_gitmodules_ignores(self):
        def git(*args):
            return subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=Builder", "-c",
                                   "user.email=builder@example.com", *args],
                                  check=True, capture_output=True, text=True).stdout.strip()

        def pointer(message, sha):
            git("update-index", "--add", "--cacheinfo", f"160000,{sha},lib")
            git("commit", "-qm", message)
            return git("rev-parse", "HEAD")
        (self.repo / ".gitmodules").write_text('[submodule "lib"]\n\tpath = lib\n\turl = ./lib\n\tignore = all\n')
        git("add", ".gitmodules")
        base = pointer("lib at one", "1" * 40)
        last = pointer("lib at two", "2" * 40)
        head = pointer("lib at three", "3" * 40)
        self.world({"checks": green(head)}, pr={"head": {"sha": head}, "base": {"ref": "main", "sha": base}},
                   comments=[report(FULL.replace(OLD, last))])
        text = RECHECK.replace(HEAD, head).replace(
            "- **R4 [polish]** `src/export.rs:52` (Sweep) Typo. Fix: file exists. Polish issue: #60.",
            "- **R4 [polish]** `lib:1` (Sweep) The pointer moved past the fixed release. Polish issue: #60.")
        for command in ("check", "post"):
            with self.subTest(command):
                out = self.run_helper(command, self.file("r.md", text), "--repo", SKILLS, "--pr", "7")
                self.assertEqual((out.returncode, out.stdout.strip()),
                                 (0, "report ok" if command == "check" else "posted 901"), out.stdout + out.stderr)

    def test_a_recheck_fetches_a_missing_commit_and_names_one_it_cannot_read(self):
        subprocess.run(["rm", "-rf", str(self.repo)], check=True)
        subprocess.run(["git", "clone", "-q", "--no-local", "--single-branch", "-b", "base", str(ORIGIN),
                        str(self.repo)], check=True)
        self.world({}, comments=[report(FULL)])
        out = self.run_helper("check", self.file("r.md", RECHECK), "--repo", SKILLS, "--pr", "7")
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "report ok"), out.stdout + out.stderr)
        gone = "d" * 40
        cases = {
            "last read": ({}, FULL.replace(OLD, gone), gone),
            "head": ({"head": {"sha": gone}}, FULL, gone),
            "base": ({"base": {"ref": "main", "sha": gone}}, FULL, gone),
        }
        for name, (pr, earlier, missing) in cases.items():
            with self.subTest(name):
                self.world({"checks": green(pr.get("head", {}).get("sha", HEAD))}, pr=pr, comments=[report(earlier)])
                text = RECHECK.replace(HEAD, pr.get("head", {}).get("sha", HEAD))
                out = self.run_helper("check", self.file("r.md", text), "--repo", SKILLS, "--pr", "7")
                self.assertEqual((out.returncode, out.stdout), (2, ""), out.stderr)
                self.assertEqual(out.stderr.strip(), f"refused: cannot read the pull request's own changes: "
                                 f"commit {missing} is not in this checkout and origin does not give it")

    def test_a_recheck_names_the_revisions_and_gits_failure_when_the_diff_fails(self):
        self.world({}, pr={"base": {"ref": "main", "sha": UNRELATED}}, comments=[report(FULL)])
        out = self.run_helper("check", self.file("r.md", RECHECK), "--repo", SKILLS, "--pr", "7")
        self.assertEqual((out.returncode, out.stdout), (2, ""), out.stderr)
        self.assertEqual(out.stderr.strip(), f"refused: cannot read the pull request's own changes: git diff "
                         f"{UNRELATED}...{OLD} failed: fatal: {UNRELATED}...{OLD}: no merge base")

    def late_report(self, *findings, held=1):
        r4 = "- **R4 [polish]** `src/export.rs:52` (Sweep) Typo. Fix: file exists. Polish issue: #60."
        text = RECHECK.replace(r4, "\n".join((r4, *findings)))
        if held is not None:
            text = text.replace("Checked: R1", f"{held} findings on unchanged code held back as pre-existing.\n\n"
                                "Checked: R1")
        if any("Risk:" in x for x in findings):
            text = text.replace("VERDICT: APPROVE", "VERDICT: CHANGES").replace(
                "Next: none open. It merges by the project's merge rules.",
                "Next: a fresh, stronger builder fixes R6 once, then one final check.")
        return text

    def test_a_late_finding_on_unchanged_code_is_held_back_as_pre_existing_and_counted(self):
        self.world({}, comments=[report(FULL)])
        risk = ("- **R6 [blocking]** `src/cli.rs:9` (Sweep) The sync token is printed. Fix: redact it.\n"
                "  Class: credential\n"
                "  Late: the first review read the CLI only for the export flag.\n"
                "  Risk: privacy: a cook's sync token reaches the terminal log.")
        cases = {
            "pre-existing": (self.late_report(LATE_PRE), "report ok; late: 1; held back: 1"),
            "pre-existing and a risk": (self.late_report(LATE_PRE, risk), "report ok; late: 2; held back: 1"),
            "risk only": (self.late_report(risk.replace("R6", "R5"), held=None).replace("fixes R6", "fixes R5"),
                          "report ok; late: 1; held back: 0"),
        }
        for name, (text, expected) in cases.items():
            with self.subTest(name):
                out = self.run_helper("check", self.file("r.md", text), "--repo", SKILLS, "--pr", "7")
                self.assertEqual((out.returncode, out.stdout.strip()), (0, expected), out.stdout + out.stderr)

    def test_a_late_finding_needs_its_late_line_and_never_blocks_without_a_risk(self):
        self.world({}, comments=[report(FULL)])
        no_late = LATE_PRE.replace("\n  Late: the first review read the CLI only for the export flag.", "")
        risk = ("- **R5 [blocking]** `src/cli.rs:9` (Sweep) The sync token is printed. Fix: redact it.\n"
                "  Class: credential\n"
                "  Risk: privacy: a cook's sync token reaches the terminal log.")
        user = LATE_PRE.replace("[pre-existing]", "[blocking]").replace(" Pre-existing issue: #62.", "") + \
            "\n  Class: input\n  User path: a cook mistypes a flag and the script carries on."
        unchanged = (f"R5: `src/cli.rs` is unchanged since {OLD[:7]}; a re-check raises a new finding there "
                     "only as a Risk: security, privacy or data-loss blocker")
        needs = f"R5: a new finding on code unchanged since {OLD[:7]} needs its Late: line"
        cases = {
            "pre-existing without Late:": (self.late_report(no_late), needs),
            "risk blocker without Late:": (self.late_report(risk, held=None).replace("fixes R6", "fixes R5"), needs),
            "late blocker with a user path": (self.late_report(user, held=None).replace(
                "VERDICT: APPROVE", "VERDICT: CHANGES").replace(
                "Next: none open. It merges by the project's merge rules.",
                "Next: a fresh, stronger builder fixes R5 once, then one final check."), unchanged),
            "late polish": (self.late_report(LATE_PRE.replace("[pre-existing]", "[polish]").replace(
                "Pre-existing issue", "Polish issue"), held=None), unchanged),
            "pre-existing with a risk": (self.late_report(
                LATE_PRE + "\n  Risk: privacy: a cook's sync token reaches the terminal log."),
                "R5: a finding with a Risk: line is graded blocking"),
            "pre-existing without its issue": (self.late_report(LATE_PRE.replace(" Pre-existing issue: #62.", "")),
                                               "R5: a new pre-existing finding ends with Pre-existing issue: #<n>"),
            "pre-existing on changed code": (self.late_report(LATE_PRE.replace("src/cli.rs:12", "src/export.rs:9"),
                                                              held=None),
                                             "R5: Late: and [pre-existing] are only for a re-check's new finding "
                                             "on unchanged code"),
            "unknown hyphenated grade": (self.late_report(LATE_PRE.replace("[pre-existing]", "[pre-exist-ing]"),
                                                          held=None), "R5: the grade is blocking, polish or pre-existing"),
            "held-back line missing": (self.late_report(LATE_PRE, held=None),
                                       "the report says `1 findings on unchanged code held back as pre-existing.`"),
            "held-back count wrong": (self.late_report(LATE_PRE, held=2),
                                      "the report says `1 findings on unchanged code held back as pre-existing.`"),
        }
        for name, (text, problem) in cases.items():
            with self.subTest(name):
                out = self.run_helper("check", self.file("r.md", text), "--repo", SKILLS, "--pr", "7")
                self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
                self.assertIn(problem, out.stdout.splitlines())

    def test_a_first_review_has_no_late_or_pre_existing_finding(self):
        self.world({"checks": green(OLD)}, pr={"head": {"sha": OLD}})
        r2 = "- **R2 [polish]** `src/cli.rs:30` (Sweep) Help wording. Fix: say export. Polish issue: #58."
        for name, line in {"pre-existing": LATE_PRE.replace("R5", "R4"),
                           "Late: on polish": r2.replace("R2", "R4") + "\n  Late: no reason."}.items():
            with self.subTest(name):
                text = FULL.replace("reaches a shared log.\n", "reaches a shared log.\n" + line.replace(
                    "src/cli.rs:12", "src/cli.rs:40") + "\n", 1)
                out = self.run_helper("check", self.file("r.md", text), "--repo", SKILLS, "--pr", "7")
                self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
                self.assertIn("R4: Late: and [pre-existing] are only for a re-check's new finding on unchanged code",
                              out.stdout.splitlines())

    def test_a_pre_existing_finding_keeps_its_grade_and_issue_at_the_final_check(self):
        fresh = self.late_report(LATE_PRE).replace(
            "- **R3 [blocking]** resolved at bbbbbbb: the log line is redacted.",
            "- **R3 [blocking]** still open after the re-check: still logged.\n"
            "  Risk: privacy: a cook's sync token reaches a shared log.").replace(
            "VERDICT: APPROVE", "VERDICT: CHANGES").replace(
            "Next: none open. It merges by the project's merge rules.",
            "Next: a fresh, stronger builder fixes R3 once, then one final check.")
        self.world({"checks": green(NEWER)}, pr={"head": {"sha": NEWER}}, comments=[report(FULL), report(fresh)])
        final = fresh.replace(HEAD, NEWER).replace("Re-check of R1, R3", "Final check of R3").replace(
            "1 findings on unchanged code held back as pre-existing.\n\n", "").replace(
            "Next: a fresh, stronger builder fixes R3 once, then one final check.",
            "Next: park R3 as a decision for Jake.")
        status = "- **R5 [pre-existing]** Pre-existing issue: #62."
        final = final.replace(LATE_PRE, status).replace(
            "- **R4 [polish]** `src/export.rs:52` (Sweep) Typo. Fix: file exists. Polish issue: #60.",
            "- **R4 [polish]** Polish issue: #60.")
        cases = {
            "kept": (final, 0, "report ok"),
            "regraded": (final.replace(status, "- **R5 [polish]** Polish issue: #62."), 1,
                         "R5: keeps its earlier grade, pre-existing"),
            "polish status": (final.replace(status, "- **R5 [pre-existing]** Polish issue: #62."), 1,
                              "R5: a pre-existing finding's status is Pre-existing issue: #<n>"),
        }
        for name, (text, code, expected) in cases.items():
            with self.subTest(name):
                out = self.run_helper("check", self.file("r.md", text), "--repo", SKILLS, "--pr", "7")
                self.assertEqual(out.returncode, code, out.stdout + out.stderr)
                self.assertIn(expected, out.stdout.splitlines())

    def three_heads(self):
        def git(*args):
            return subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=Builder", "-c",
                                   "user.email=builder@example.com", *args],
                                  check=True, capture_output=True, text=True).stdout.strip()

        def commit(message, changed):
            lines = (self.repo / "src/export.rs").read_text().splitlines() if changed else []
            lines = lines or [f"line {n}" for n in range(1, 61)]
            for n in changed:
                lines[n - 1] += " edited"
            (self.repo / "src").mkdir(exist_ok=True)
            (self.repo / "src/export.rs").write_text("\n".join(lines) + "\n")
            git("add", "-A")
            git("commit", "-qm", message)
            return git("rev-parse", "HEAD")
        git("checkout", "-q", BASE)
        first = commit("sixty lines", [])
        second = commit("fix round", [1, 10, 52])
        (self.repo / "src/share.rs").write_text("fn share() {}\n")
        git("add", "-A")
        git("commit", "-qm", "fresh round")
        third = git("rev-parse", "HEAD")
        return first, second, third

    def test_a_late_finding_is_judged_by_its_line_not_its_file(self):
        first, second, _ = self.three_heads()
        self.world({"checks": green(second)}, pr={"head": {"sha": second}}, comments=[report(FULL.replace(OLD, first))])
        pre = LATE_PRE.replace("src/cli.rs:12", "src/export.rs:{}")
        polish = "- **R5 [polish]** `src/export.rs:{}` (Sweep) Typo. Fix: file exists. Polish issue: #63."
        only = "R5: Late: and [pre-existing] are only for a re-check's new finding on unchanged code"
        cases = {
            "pre-existing on an untouched line of a changed file": (pre.format(20), 1, 0, "report ok; late: 1; held back: 1"),
            "pre-existing on the edited line": (pre.format(1), None, 1, only),
            "polish on the edited line": (polish.format(10), None, 0, "report ok"),
            "polish on an untouched line of a changed file": (polish.format(30), None, 1,
                f"R5: `src/export.rs:30` is unchanged since {first[:7]}; a re-check raises a new finding there "
                "only as a Risk: security, privacy or data-loss blocker"),
            "a line past the file's end counts as changed": (pre.format(99), None, 1, only),
        }
        for name, (line, held, code, expected) in cases.items():
            with self.subTest(name):
                text = self.late_report(line, held=held).replace(HEAD, second)
                out = self.run_helper("check", self.file("r.md", text), "--repo", SKILLS, "--pr", "7")
                self.assertEqual(out.returncode, code, out.stdout + out.stderr)
                self.assertIn(expected, out.stdout.splitlines())

    def test_late_is_measured_from_the_first_verdict_at_every_check(self):
        first, second, third = self.three_heads()
        full = FULL.replace(OLD, first)
        fresh = RECHECK.replace(HEAD, second).replace("VERDICT: APPROVE", "VERDICT: CHANGES").replace(
            "- **R3 [blocking]** resolved at bbbbbbb: the log line is redacted.",
            "- **R3 [blocking]** still open after the re-check: still logged.\n"
            "  Risk: privacy: a cook's sync token reaches a shared log.").replace(
            "Next: none open. It merges by the project's merge rules.",
            "Next: a fresh, stronger builder fixes R3 once, then one final check.")
        r4 = "- **R4 [polish]** `src/export.rs:52` (Sweep) Typo. Fix: file exists. Polish issue: #60."
        final = fresh.replace(second, third).replace("Re-check of R1, R3", "Final check of R3").replace(
            r4, "- **R4 [polish]** Polish issue: #60.").replace(
            "Next: a fresh, stronger builder fixes R3 once, then one final check.",
            "Next: park R3 as a decision for Jake.")
        pre = LATE_PRE.replace("src/cli.rs:12", "src/export.rs:{}")
        held = "Checked: R1"
        only = "R5: Late: and [pre-existing] are only for a re-check's new finding on unchanged code"
        log = (f"**Orchestrator decision:** log and merge: R3 at {third}. Polish issues: #64. "
               "Why: the log stays local.")
        approve = final.replace("VERDICT: CHANGES", "VERDICT: APPROVE").replace(
            "- **R3 [blocking]** still open after the re-check: still logged.\n"
            "  Risk: privacy: a cook's sync token reaches a shared log.",
            "- **R3 [polish]** Polish issue: #64.").replace(
            "Next: park R3 as a decision for Jake.", "Next: none open. It merges by the project's merge rules.")
        worlds = {
            "final check": ([full, fresh], final, third),
            "log and merge": ([full, fresh, final, log], approve, third),
        }
        for mode, (comments, text, head) in worlds.items():
            for line, code, expected in ((10, 1, only), (40, 0, "report ok; late: 1; held back: 1")):
                with self.subTest(mode=mode, line=line):
                    self.world({"checks": green(head)}, pr={"head": {"sha": head}},
                               comments=[report(c) if c.startswith("VERDICT") else {"body": c, "user": {"login": "owner"}}
                                         for c in comments])
                    body = text.replace("- **R4 [polish]** Polish issue: #60.",
                                        "- **R4 [polish]** Polish issue: #60.\n" + pre.format(line))
                    if code == 0:
                        body = body.replace(held, "1 findings on unchanged code held back as pre-existing.\n\n" + held)
                    out = self.run_helper("check", self.file("r.md", body), "--repo", SKILLS, "--pr", "7")
                    self.assertEqual(out.returncode, code, out.stdout + out.stderr)
                    self.assertIn(expected, out.stdout.splitlines())

    def test_a_risk_line_never_rides_on_a_non_blocking_finding(self):
        risk = "\n  Risk: privacy: a cook's sync token reaches the terminal log."
        late_polish = LATE_PRE.replace("[pre-existing]", "[polish]").replace("Pre-existing issue", "Polish issue")
        changed_polish = "- **R5 [polish]** `src/export.rs:9` (Sweep) Typo. Fix: file exists. Polish issue: #63."
        stays = "R5: a finding with a Risk: line is graded blocking"
        cases = {
            "late polish": (late_polish + risk, None),
            "late pre-existing": (LATE_PRE + risk, 1),
            "polish on changed code": (changed_polish + risk, None),
        }
        self.world({}, comments=[report(FULL)])
        for name, (line, held) in cases.items():
            with self.subTest(name):
                text = self.late_report(line, held=held).replace("fixes R6", "fixes R5")
                out = self.run_helper("check", self.file("r.md", text), "--repo", SKILLS, "--pr", "7")
                self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
                self.assertIn(stays, out.stdout.splitlines())
        with self.subTest("polish at a full review"):
            self.world({"checks": green(OLD)}, pr={"head": {"sha": OLD}})
            text = FULL.replace("Polish issue: #58.", "Polish issue: #58." + risk.replace("terminal", "shared"))
            out = self.run_helper("check", self.file("r.md", text), "--repo", SKILLS, "--pr", "7")
            self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
            self.assertIn("R2: a finding with a Risk: line is graded blocking", out.stdout.splitlines())

    def hand_back(self, code_line):
        upstream, work = self.root / "upstream", self.root / "work"

        def git(where, *args):
            return subprocess.run(["git", "-C", str(where), "-c", "user.name=Builder", "-c",
                                   "user.email=builder@example.com", *args],
                                  check=True, capture_output=True, text=True).stdout.strip()
        for d in (upstream, work):
            if d.exists():
                subprocess.run(["rm", "-rf", str(d)], check=True)
        upstream.mkdir()
        git(upstream, "init", "-q", "-b", "main")
        (upstream / "export.py").write_text("def export():\n    pass\n")
        git(upstream, "add", "-A")
        git(upstream, "commit", "-qm", "base")
        git(self.root, "clone", "-q", str(upstream), str(work))
        git(work, "checkout", "-qb", "room/41-export")
        (work / "export.py").write_text(f"def export():\n    {code_line}\n")
        git(work, "commit", "-qam", "#41 green: export refuses an existing zip")
        return work, git(work, "rev-parse", "HEAD")

    def builder_pass(self, work, description):
        skill = HELPER.parent.parent.parent / "build-ticket"
        text = (skill / "SKILL.md").read_text()
        line = re.search(r"`(python3 -I <this skill's folder>/\.\./review-ticket/scripts/review\.py "
                         r"self-check <description file>)`", text)
        self.assertIsNotNone(line, "build-ticket's SKILL.md names no self-check line")
        argv = shlex.split(line[1].replace("<this skill's folder>", str(skill))
                           .replace("<description file>", self.file("description.md", description)))
        return subprocess.run(argv, text=True, capture_output=True, env=self.env, timeout=30, cwd=work)

    def test_the_builders_own_pass_catches_a_planted_checklist_miss(self):
        clean = "raise FileExistsError('cookbook.zip')"
        work, head = self.hand_back(clean)

        def description(head):
            return (f"Closes example/product#41\n\n## Summary\n\nExport refuses an existing zip.\n\n"
                    f"## Rulings\n\n1. Name the zip cookbook.zip. Why: the importer reads that name. "
                    f"Cost if wrong: low: one rename.\n\n## Self-check\n\n"
                    f"- Undo and rerun: `git revert --no-commit HEAD && python3 -m unittest test_export` "
                    f"printed `FAILED (failures=1)`.\n- Consumers: n/a: nothing else reads export.py.\n\n"
                    f"## Facts\n\n- **Head:** `{head}`\n"
                    f"- **Tests:** `test_export_refuses`. catches: a second export overwriting the first.\n")
        good = description(head)
        out = self.builder_pass(work, good)
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "self-check: ok"), out.stdout + out.stderr)
        rulings = ("## Rulings\n\n1. Name the zip cookbook.zip. Why: the importer reads that name. "
                   "Cost if wrong: low: one rename.\n\n")
        planted = {
            "no Closes line": (lambda h: description(h).replace("Closes example/product#41\n", ""), clean,
                               "no Closes line names the ticket; the review cannot start"),
            "no Rulings section": (lambda h: description(h).replace(rulings, ""), clean,
                                   "no ## Rulings section with numbered rulings or exactly none"),
            "stale head": (lambda h: description(OLD), clean, "the description does not name the head {head}"),
            "stale head cited in Evidence": (lambda h: description(OLD).replace(
                "## Summary", f"## Evidence\n\nCurrent commit: `{h}`.\n\n## Summary"), clean,
                "the description does not name the head {head}"),
            "test annotation in Gaps": (lambda h: description(h).replace(
                " catches: a second export overwriting the first.",
                "\n- **Gaps:** Example catches: a second export overwriting the first."), clean,
                "no `catches: <the bug>` or `no new test: <why>` line"),
            "only a fenced ruling": (lambda h: description(h).replace(
                rulings, "## Rulings\n\n```markdown\n1. Sample only.\n```\n\n"), clean,
                "no ## Rulings section with numbered rulings or exactly none"),
            "no test-rule line": (lambda h: description(h).replace(" catches: a second export overwriting the first.",
                                                                   ""), clean,
                                  "no `catches: <the bug>` or `no new test: <why>` line"),
            "token in the diff": (description, "token = '" + "ghp_" + "A1b2C3d4E5f6G7h8'",
                                  "private material (a token or thread id) in export.py"),
            "thread id in the description": (lambda h: description(h).replace("## Summary", "## Summary " + "thr_" + "a1b2c3d4"),
                                             clean, "private material (a token or thread id) in the description"),
        }
        for name, (text, code_line, expected) in planted.items():
            with self.subTest(name):
                work, head = self.hand_back(code_line)
                out = self.builder_pass(work, text(head))
                self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
                self.assertEqual(out.stdout.splitlines(), ["miss: " + expected.format(head=head), "self-check: 1 miss"])
        work, head = self.hand_back(clean)
        out = self.builder_pass(work, description(head).replace(rulings, "## Rulings\n\nnone\n\n"))
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "self-check: ok"), out.stdout)
        out = self.run_helper("self-check", self.file("d.md", description(head)), "--base", "origin/gone", cwd=work)
        self.assertEqual((out.returncode, out.stdout), (2, ""), out.stdout)
        self.assertIn("cannot read origin/gone...HEAD with git", out.stderr)

    def test_report_ignores_fenced_examples_next_to_real_rulings(self):
        body = DESCRIPTION.replace("## Rulings\n", "## Rulings\n\n```markdown\n"
                                   "## Example\n2. Sample only.\n~~~\n3. Also a sample.\n```\n")
        self.world({"checks": green(OLD)}, pr={"head": {"sha": OLD}, "body": body})
        out = self.run_helper("check", self.file("r.md", FULL), "--repo", SKILLS, "--pr", "7")
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "report ok"), out.stdout + out.stderr)

    def test_the_builders_own_pass_needs_a_self_check_line_for_each_probe(self):
        work, head = self.hand_back("raise FileExistsError('cookbook.zip')")
        probes = ("## Self-check\n\n"
                  "- Undo and rerun: `git revert --no-commit HEAD && python3 -m unittest test_export` printed "
                  "`FAILED (failures=1)` at its assertion.\n"
                  "- Error paths: `python3 export.py --to cookbook.zip; echo $?` printed `3`.\n"
                  "- Consumers: n/a: nothing else reads export.py.\n\n")
        base = (f"Closes example/product#41\n\n## Summary\n\nExport refuses an existing zip.\n\n"
                f"## Rulings\n\nnone\n\n{probes}## Facts\n\n- **Head:** `{head}`\n"
                f"- **Tests:** `test_export_refuses`. catches: a second export overwriting the first.\n")
        out = self.builder_pass(work, base)
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "self-check: ok"), out.stdout + out.stderr)
        at_end = base.replace(probes, "") + "\n" + probes.rstrip("\n")
        out = self.builder_pass(work, at_end)
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "self-check: ok"), out.stdout + out.stderr)
        with self.subTest("a level-one heading after the section"):
            out = self.builder_pass(work, at_end + "\n\n# Appendix\n\nNotes for the next ticket.\n")
            self.assertEqual((out.returncode, out.stdout.strip()), (0, "self-check: ok"), out.stdout + out.stderr)
        marker = "thr_" + "a1b2c3d4"

        def bad(line):
            return (f"the ## Self-check line at description line {line} has neither a `command` with what it "
                    "printed nor n/a: <why>")
        missing = "no ## Self-check section with one line per probe"
        empty = "the ## Self-check section has no probe lines"
        planted = {
            "no section": (base.replace(probes, ""), [missing]),
            "a deeper heading only": (base.replace("## Self-check", "### Self-check"), [missing]),
            "an empty section": (base.replace(probes, "## Self-check\n\n"), [empty]),
            "a blank section at the end": (base.replace(probes, "") + "\n## Self-check\n  \n", [empty]),
            "a line with no command": (
                base.replace("- Consumers: n/a: nothing else reads export.py.", "- Consumers: checked, all fine."),
                [bad(15)]),
            "a command with no output": (base.replace(" printed `3`.", "."), [bad(14)]),
            "printed with only a full stop after it": (base.replace(" printed `3`.", " printed."), [bad(14)]),
            "n/a with no reason": (base.replace("n/a: nothing else reads export.py.", "n/a:"), [bad(15)]),
            "n/a with only a full stop": (base.replace("n/a: nothing else reads export.py.", "n/a: ."), [bad(15)]),
            "a private value in a malformed line": (
                base.replace("- Consumers: n/a: nothing else reads export.py.", f"- Consumers: {marker} checked"),
                [bad(15), "private material (a token or thread id) in the description"]),
            "a fenced template with no real section": (
                base.replace(probes, "```markdown\n## Self-check\n- Undo: `git revert` printed `FAILED`.\n"
                                     "## Facts\n```\n\n"),
                [missing]),
            "no section and no Closes line": (
                base.replace(probes, "").replace("Closes example/product#41\n", ""),
                ["no Closes line names the ticket; the review cannot start", missing]),
        }
        for name, (text, expected) in planted.items():
            with self.subTest(name):
                out = self.builder_pass(work, text)
                self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
                self.assertNotIn(marker, out.stdout + out.stderr)
                n = len(expected)
                self.assertEqual(out.stdout.splitlines(),
                                 [f"miss: {m}" for m in expected] + [f"self-check: {n} miss{'es' if n > 1 else ''}"])

    def test_post_writes_once_and_reads_back(self):
        self.world({"checks": green(OLD)}, pr={"head": {"sha": OLD}})
        path = self.file("r.md", FULL)
        out = self.run_helper("post", path, "--repo", SKILLS, "--pr", "7")
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "posted 900"), out.stdout + out.stderr)
        again = self.run_helper("post", path, "--repo", SKILLS, "--pr", "7")
        self.assertEqual(again.stdout.strip(), "already posted 900")
        self.assertEqual(self.state()["writes"], 1)

    def test_post_refuses_a_duplicate_report_for_an_earlier_head(self):
        self.world({}, comments=[report(FULL)])
        out = self.run_helper("post", self.file("r.md", FULL), "--repo", SKILLS, "--pr", "7")
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn(f"VERDICT names {OLD}, not the pinned head {HEAD}", out.stdout.splitlines())
        self.assertEqual(self.state()["writes"], 0)

    def test_post_rechecks_live_admission_after_reading_the_comments(self):
        red = {OLD: [{"name": "check", "status": "completed", "conclusion": "failure"}]}
        cases = {
            "draft and red": ({"draft": True}, red, "stop: draft"),
            "red": ({}, red, f"stop: check is not green at {OLD}"),
            "head moved": ({"head": {"sha": HEAD}}, green(HEAD), f"stop: the head is {HEAD}, not the assigned {OLD}"),
            "ticket changed": ({"body": DESCRIPTION.replace("#41", "#42")}, green(OLD), "stop: the ticket changed"),
        }
        pr = {**self.state()["pulls"]["7"], "head": {"sha": OLD}}
        for name, (update, checks, message) in cases.items():
            with self.subTest(name):
                self.world({"checks": green(OLD), "after_comments": {
                    "pulls": {"7": {**pr, **update}}, "checks": checks,
                }}, pr=pr)
                out = self.run_helper("post", self.file("r.md", FULL), "--repo", SKILLS, "--pr", "7", "--head", OLD)
                self.assertEqual((out.returncode, out.stdout.strip()), (1, message), out.stdout + out.stderr)
                self.assertEqual(self.state()["writes"], 0)

    def test_post_refuses_a_failing_report_with_zero_writes(self):
        self.world({"checks": green(OLD)}, pr={"head": {"sha": OLD}})
        out = self.run_helper("post", self.file("r.md", FULL.replace(" Polish issue: #58.", "")),
                              "--repo", SKILLS, "--pr", "7")
        self.assertEqual(out.returncode, 1)
        self.assertEqual(self.state()["writes"], 0)

    def test_lost_response_is_recovered_by_read_back(self):
        self.world({"checks": green(OLD), "lose": True}, pr={"head": {"sha": OLD}})
        path = self.file("r.md", FULL)
        out = self.run_helper("post", path, "--repo", SKILLS, "--pr", "7")
        self.assertEqual(out.stdout.strip(), "posted 900", out.stdout + out.stderr)
        self.run_helper("post", path, "--repo", SKILLS, "--pr", "7")
        self.assertEqual(self.state()["writes"], 1)

    def test_unconfirmed_post_is_unknown(self):
        self.world({"checks": green(OLD), "fail_post": True}, pr={"head": {"sha": OLD}})
        out = self.run_helper("post", self.file("r.md", FULL), "--repo", SKILLS, "--pr", "7")
        self.assertEqual(out.returncode, 1)
        self.assertEqual(out.stdout.strip(), "unknown: not found on read-back; read the comments before posting again")

    def follow_up(self, *extra):
        finding = self.file("finding.md", "`src/cli.rs:30` (Sweep) Help wording. Fix: say export.")
        return self.run_helper("follow-up", "--repo", PRODUCT, "--ticket", "41", "--spec", "38",
                               "--pr", f"{SKILLS}#7", "--head", OLD, "--id", "R2",
                               "--title", "Help says zip archive file", "--finding", finding, *extra)

    def test_follow_up_is_filed_once_for_triage(self):
        out = self.follow_up()
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "filed #70"), out.stdout + out.stderr)
        issue = self.state()["issues"][PRODUCT][0]
        self.assertEqual(issue["title"], "Help says zip archive file (polish for #41, R2)")
        self.assertEqual([x["name"] for x in issue["labels"]], ["triage: new"])
        self.assertTrue(issue["body"].startswith("Follow-up of #41 (spec #38)\n\n"))
        self.assertIn(f"Found in pull request {SKILLS}#7 at {OLD}; it is polish", issue["body"])
        self.assertEqual(self.follow_up().stdout.strip(), "already filed #70")
        self.assertEqual(self.state()["writes"], 1)

    def test_logged_blocker_follow_up(self):
        out = self.follow_up("--logged", "re-check", "--user-path", "a cook exports twice; one is lost")
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "filed #70"), out.stdout + out.stderr)
        issue = self.state()["issues"][PRODUCT][0]
        self.assertEqual(issue["title"], "Follow-up of #41 (spec #38)")
        self.assertIn("User path: a cook exports twice; one is lost\n", issue["body"])
        self.assertIn(f"Still open after the re-check of pull request {SKILLS}#7 at {OLD}; logged, "
                      "so it did not block the merge.", issue["body"])

    def test_logged_blockers_with_the_same_title_are_filed_separately(self):
        logged = ("--logged", "re-check", "--user-path", "a cook exports twice; one is lost")
        self.assertEqual(self.follow_up(*logged).stdout.strip(), "filed #70")
        self.assertEqual(self.follow_up(*logged, "--id", "R3").stdout.strip(), "filed #71")
        self.assertEqual(self.follow_up(*logged).stdout.strip(), "already filed #70")
        issues = self.state()["issues"][PRODUCT]
        self.assertEqual([issue["title"] for issue in issues], ["Follow-up of #41 (spec #38)"] * 2)
        self.assertEqual(self.state()["writes"], 2)

    def test_logged_blocker_retry_recognizes_an_existing_legacy_title(self):
        self.world({"issues": {PRODUCT: [{"number": 69, "title": "Help says zip archive file (follow-up for #41, R2)"}]}})
        out = self.follow_up("--logged", "re-check", "--user-path", "a cook exports twice; one is lost")
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "already filed #69"), out.stdout + out.stderr)
        self.assertEqual(self.state()["writes"], 0)

    def test_follow_up_reads_again_when_the_first_listing_is_stale(self):
        self.world({"hidden_issue_reads": 1, "lose": True})
        out = self.follow_up()
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "filed #70"), out.stdout + out.stderr)
        self.assertEqual(self.state()["writes"], 1)

    def test_follow_up_that_stays_invisible_reports_an_unknown_write(self):
        self.world({"hidden_issue_reads": 10})
        out = self.follow_up()
        self.assertEqual((out.returncode, out.stdout.strip()),
                         (1, "unknown: not found on read-back; list the issues before filing again"))
        self.assertEqual(self.state()["writes"], 1)

    def test_follow_up_label_must_be_unique(self):
        for name, labels in {"none": LABELS.replace("| `needs-triage` | `triage: new` | Sort it |\n", ""),
                             "two": LABELS + "| `needs-triage` | `new` | Again |\n"}.items():
            with self.subTest(name):
                self.world({"files": {f"{PRODUCT}@main:docs/agents/triage-labels.md": labels,
                                      f"{SKILLS}@main:docs/agents/fleet.md": FLEET}})
                out = self.follow_up()
                self.assertEqual(out.returncode, 2)
                self.assertIn("needs-triage label", out.stderr)
                self.assertEqual(self.state()["writes"], 0)


    def parked_world(self, decision=None, head=NEWER, author="owner", extra=None):
        fresh = RECHECK.replace("VERDICT: APPROVE", "VERDICT: CHANGES").replace(
            "- **R3 [blocking]** resolved at bbbbbbb: the log line is redacted.",
            "- **R3 [blocking]** still open after the re-check: still logged.\n"
            "  Risk: privacy: a cook's sync token reaches a shared log.").replace(
            "Next: none open. It merges by the project's merge rules.",
            "Next: a fresh, stronger builder fixes R3 once, then one final check.")
        parked = fresh.replace(HEAD, NEWER).replace("Re-check of R1, R3", "Final check of R3").replace(
            "Next: a fresh, stronger builder fixes R3 once, then one final check.",
            "Next: park R3 as a decision for Jake.")
        comments = [report(FULL), report(fresh), report(parked)]
        if decision:
            comments.append({"body": decision, "user": {"login": author}})
        comments += extra or []
        self.world({"checks": {**green(NEWER), **green("d" * 40)}}, pr={"head": {"sha": head}}, comments=comments)
        return parked

    def test_fix_once_more_decision_admits_a_check_of_the_new_head(self):
        self.parked_world(f"**Orchestrator decision:** fix once more: R3 at {NEWER}. Why: one line.", head="d" * 40)
        out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertTrue(out.stdout.startswith(f"review final #7 at {'d' * 40}"), out.stdout)
        self.assertIn(f"last read {NEWER}; open R3", out.stdout)

    def test_log_and_merge_decision_admits_one_same_head_polish_report(self):
        parked = self.parked_world(f"**Orchestrator decision:** log and merge: R3 at {NEWER}. Polish issues: #64. "
                                   "Why: the log stays local.")
        out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertTrue(out.stdout.startswith(f"review log-and-merge #7 at {NEWER}"), out.stdout)
        approve = parked.replace("VERDICT: CHANGES", "VERDICT: APPROVE").replace(
            "- **R3 [blocking]** still open after the re-check: still logged.\n"
            "  Risk: privacy: a cook's sync token reaches a shared log.",
            "- **R3 [polish]** Polish issue: #64.").replace(
            "Next: park R3 as a decision for Jake.", "Next: none open. It merges by the project's merge rules.").replace(
            "- **R4 [polish]** `src/export.rs:52` (Sweep) Typo. Fix: file exists. Polish issue: #60.",
            "- **R4 [polish]** Polish issue: #60.")
        posted = self.run_helper("post", self.file("approve.md", approve), "--repo", SKILLS, "--pr", "7")
        self.assertEqual(posted.stdout.strip(), "posted 904", posted.stdout + posted.stderr)
        wrong = approve.replace("Polish issue: #64.", "Polish issue: #65.")
        self.world({**self.state(), "comments": {f"{SKILLS}#7": self.state()["comments"][f"{SKILLS}#7"][:4]}})
        out = self.run_helper("check", self.file("wrong.md", wrong), "--repo", SKILLS, "--pr", "7")
        self.assertIn("R3: the decision grades it polish with Polish issue: #64", out.stdout.splitlines())

    def test_a_log_and_merge_check_raises_no_new_finding_on_unchanged_code(self):
        parked = self.parked_world(f"**Orchestrator decision:** log and merge: R3 at {NEWER}. Polish issues: #64. "
                                   "Why: the log stays local.")
        approve = parked.replace("VERDICT: CHANGES", "VERDICT: APPROVE").replace(
            "- **R3 [blocking]** still open after the re-check: still logged.\n"
            "  Risk: privacy: a cook's sync token reaches a shared log.",
            "- **R3 [polish]** Polish issue: #64.").replace(
            "Next: park R3 as a decision for Jake.", "Next: none open. It merges by the project's merge rules.").replace(
            "- **R4 [polish]** `src/export.rs:52` (Sweep) Typo. Fix: file exists. Polish issue: #60.",
            "- **R4 [polish]** Polish issue: #60.\n"
            "- **R5 [polish]** `src/export.rs:52` (Sweep) Typo. Fix: file exists. Polish issue: #61.")
        out = self.run_helper("check", self.file("approve.md", approve), "--repo", SKILLS, "--pr", "7")
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn(f"R5: `src/export.rs` is unchanged since {NEWER[:7]}; a re-check raises a new finding there "
                      "only as a Risk: security, privacy or data-loss blocker", out.stdout.splitlines())
        self.assertFalse([c for c in self.state()["calls"] if "/compare/" in " ".join(c)], self.state()["calls"])

    def test_unmatched_or_unauthorized_decisions_keep_the_park(self):
        for name, (decision, author) in {
            "stranger": (f"**Orchestrator decision:** fix once more: R3 at {NEWER}. Why: x.", "stranger"),
            "other ids": (f"**Orchestrator decision:** fix once more: R1 at {NEWER}. Why: x.", "owner"),
            "other head": (f"**Orchestrator decision:** fix once more: R3 at {HEAD}. Why: x.", "owner"),
        }.items():
            with self.subTest(name):
                self.parked_world(decision, head="d" * 40, author=author)
                out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
                self.assertEqual((out.returncode, out.stdout.strip()), (1, "stop: R3 is parked as a decision for Jake"))

    def test_an_earlier_blocker_cannot_be_closed_as_polish(self):
        cases = {
            "polish status": RECHECK.replace("- **R3 [blocking]** resolved at bbbbbbb: the log line is redacted.",
                                             "- **R3 [blocking]** Polish issue: #62."),
            "polish grade": RECHECK.replace("- **R3 [blocking]** resolved at bbbbbbb: the log line is redacted.",
                                            "- **R3 [polish]** Polish issue: #62."),
        }
        problems = {"polish status": "R3: a blocker's status is resolved, withdrawn, still open, disputed or logged",
                    "polish grade": "R3: keeps its earlier grade, blocking"}
        for name, text in cases.items():
            with self.subTest(name):
                self.world({}, comments=[report(FULL)])
                out = self.run_helper("post", self.file("r.md", text), "--repo", SKILLS, "--pr", "7")
                self.assertEqual(out.returncode, 1, out.stdout)
                self.assertIn(problems[name], out.stdout.splitlines())
                self.assertEqual(self.state()["writes"], 0)

    def test_v2_ruling_mark_refusals(self):
        self.world({"checks": green(OLD)}, pr={"head": {"sha": OLD}, "body": DESCRIPTION.replace(
            "1. Name the zip", "2. Keep one zip. Why: one file. Cost if wrong: low: two files.\n1. Name the zip")})
        two = FULL.replace("- **Ruling 1** upheld: the importer reads cookbook.zip.",
                           "- **Ruling 1** overturned as R1: wrong.\n- **Ruling 2** overturned as R1: wrong.")
        out = self.run_helper("check", self.file("r.md", two), "--repo", SKILLS, "--pr", "7")
        self.assertIn("R1: named by two overturned rulings", out.stdout.splitlines())
        none = FULL.replace("- **Ruling 1** upheld: the importer reads cookbook.zip.",
                            "- **Ruling 1** upheld: ok.\n- **Ruling 2** upheld: ok.\n\nRulings: none.")
        out = self.run_helper("check", self.file("r.md", none), "--repo", SKILLS, "--pr", "7")
        self.assertIn("Rulings: none. stands beside a ruling mark", out.stdout.splitlines())

    def test_a_report_carries_one_disproved_line_before_checked(self):
        line = "Disproved: 0 candidate findings dropped.\n\n"
        checked = {"full": "Checked: Standards", "re-check": "Checked: R1, R3"}
        bad = {
            "none": ("", "no Disproved: line; write Disproved: <n> candidate findings dropped. before Checked:"),
            "two": (line + line, "2 Disproved: lines; write exactly one"),
            "leading zero": ("Disproved: 02 candidate findings dropped.\n\n",
                             "the Disproved: line reads Disproved: <n> candidate findings dropped."),
            "other words": ("Disproved: 1 candidate finding dropped.\n\n",
                            "the Disproved: line reads Disproved: <n> candidate findings dropped."),
            "inside checked": ("Disproved: 1 candidate findings dropped.\n",
                               "the Disproved: line is its own paragraph before Checked:"),
        }
        for mode, text in {"full": FULL, "re-check": RECHECK}.items():
            if mode == "full":
                self.world({"checks": green(OLD)}, pr={"head": {"sha": OLD}})
            else:
                self.world({}, comments=[report(FULL)])
            bare = text.replace(line, "")
            for name, (insert, problem) in bad.items():
                with self.subTest(mode=mode, case=name):
                    out = self.run_helper("check", self.file("r.md", bare.replace(checked[mode], insert + checked[mode])),
                                          "--repo", SKILLS, "--pr", "7")
                    self.assertEqual(out.returncode, 1, out.stdout)
                    self.assertIn(problem, out.stdout.splitlines())
            with self.subTest(mode=mode, case="after checked"):
                out = self.run_helper("check", self.file("r.md", bare.replace("\n\nNext: ", "\n\n" + line + "Next: ")),
                                      "--repo", SKILLS, "--pr", "7")
                self.assertIn("the Disproved: line is its own paragraph before Checked:", out.stdout.splitlines())
            for count in ("0", "1", "12"):
                with self.subTest(mode=mode, count=count):
                    good = text.replace("Disproved: 0 ", f"Disproved: {count} ")
                    out = self.run_helper("check", self.file("r.md", good), "--repo", SKILLS, "--pr", "7")
                    self.assertEqual((out.returncode, out.stdout.strip()), (0, "report ok"), out.stdout + out.stderr)

    def test_the_verdict_contracts_examples_meet_the_disproved_rule(self):
        sys.path.insert(0, str(HELPER.parent))
        import review
        contract = (HELPER.parent.parent / "references" / "verdict.md").read_text()
        first, again = re.findall(r"```md\n(.*?)```", contract, re.S)
        head = review.parse(first)["head"]
        self.world({"checks": green(head)}, pr={"head": {"sha": head}})
        skill = re.findall(r"```md\n(.*?)```", (HELPER.parent.parent / "SKILL.md").read_text(), re.S)
        for name, text in {"verdict.md": first, "SKILL.md": skill[0]}.items():
            with self.subTest(name):
                out = self.run_helper("check", self.file("first.md", text), "--repo", SKILLS, "--pr", "7")
                self.assertEqual((out.returncode, out.stdout.strip()), (0, "report ok"), out.stdout + out.stderr)
        problems = review.check(again, DESCRIPTION, "re-check", review.parse(again)["head"], review.parse(first))
        self.assertEqual([p for p in problems if "Disproved" in p], [])
        problems = review.check(again.replace("Disproved: 1 candidate findings dropped.\n\n", ""), DESCRIPTION,
                                "re-check", review.parse(again)["head"], review.parse(first))
        self.assertIn("no Disproved: line; write Disproved: <n> candidate findings dropped. before Checked:", problems)

    def test_a_blocker_names_exactly_one_class_from_the_verdict_format(self):
        self.world({"checks": green(OLD)}, pr={"head": {"sha": OLD}})
        line = "  Class: files\n"
        missing = "R1: a blocker names its class: one Class: line from references/verdict.md"
        unknown = "R1: Class: {} is not a word from references/verdict.md; use Class: other: <word> when none fits"
        cases = {
            "no class": (FULL.replace(line, ""), 1, missing),
            "unknown word": (FULL.replace(line, "  Class: memory\n"), 1, unknown.format("memory")),
            "capitalised word": (FULL.replace(line, "  Class: Files\n"), 1, unknown.format("Files")),
            "two words": (FULL.replace(line, "  Class: files state\n"), 1, unknown.format("files state")),
            "other with a spaced word": (FULL.replace(line, "  Class: other: race window\n"), 1,
                                         unknown.format("other: race window")),
            "two class lines": (FULL.replace(line, line + "  Class: state\n"), 1,
                                "R1: a blocker carries exactly one Class: line"),
            "class as finding text": (FULL.replace(line, "").replace("Fix: refuse with status 3.",
                                                                     "Fix: refuse with status 3. Class: files"), 1, missing),
            "other with one word": (FULL.replace(line, "  Class: other: race-window\n"), 0, "report ok"),
            "every listed word": (FULL.replace(line, "  Class: error-path\n"), 0, "report ok"),
        }
        for name, (text, code, expected) in cases.items():
            with self.subTest(name):
                out = self.run_helper("check", self.file("r.md", text), "--repo", SKILLS, "--pr", "7")
                self.assertEqual(out.returncode, code, out.stdout + out.stderr)
                self.assertIn(expected, out.stdout.splitlines())
        for word in ("input", "error-path", "guard", "output", "state", "files", "process", "credential"):
            with self.subTest(word):
                out = self.run_helper("check", self.file("r.md", FULL.replace(line, f"  Class: {word}\n")),
                                      "--repo", SKILLS, "--pr", "7")
                self.assertEqual((out.returncode, out.stdout.strip()), (0, "report ok"), out.stdout + out.stderr)

    def test_only_a_blocker_is_asked_for_its_class(self):
        self.world({"checks": green(OLD)}, pr={"head": {"sha": OLD}})
        out = self.run_helper("check", self.file("r.md", FULL), "--repo", SKILLS, "--pr", "7")
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "report ok"), out.stdout + out.stderr)
        late = ("- **R2 [pre-existing]** `src/cli.rs:30` (Sweep) Help wording. Fix: say export. "
                "Pre-existing issue: #58.\n  Late: the first review read only the export.")
        text = FULL.replace("- **R2 [polish]** `src/cli.rs:30` (Sweep) Help wording. Fix: say export. Polish issue: #58.",
                            late)
        out = self.run_helper("check", self.file("r.md", text), "--repo", SKILLS, "--pr", "7")
        self.assertEqual([x for x in out.stdout.splitlines() if x.startswith("R2:") and "Class" in x], [])
        self.assertIn("R1: a blocker names its class: one Class: line from references/verdict.md",
                      self.run_helper("check", self.file("r.md", text.replace("  Class: files\n", "")),
                                      "--repo", SKILLS, "--pr", "7").stdout.splitlines())

    def test_a_blocker_keeps_its_class_at_every_later_status(self):
        self.world({}, comments=[report(FULL)])
        resolved = "- **R3 [blocking]** resolved at bbbbbbb: the log line is redacted.\n"
        cases = {
            "resolved without its class": (RECHECK.replace(resolved + "  Class: credential\n", resolved),
                                           "R3: a blocker names its class: one Class: line from references/verdict.md"),
            "logged without its class": (RECHECK.replace("  Class: files\n", ""),
                                         "R1: a blocker names its class: one Class: line from references/verdict.md"),
            "resolved with another class": (RECHECK.replace("  Class: credential\n", "  Class: output\n"),
                                            "R3: keeps its earlier class, credential"),
        }
        for name, (text, problem) in cases.items():
            with self.subTest(name):
                out = self.run_helper("check", self.file("r.md", text), "--repo", SKILLS, "--pr", "7")
                self.assertEqual(out.returncode, 1, out.stdout)
                self.assertIn(problem, out.stdout.splitlines())
        self.world({}, comments=[report(FULL.replace("  Class: credential\n", ""))])
        out = self.run_helper("check", self.file("r.md", RECHECK), "--repo", SKILLS, "--pr", "7")
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "report ok"), out.stdout + out.stderr)

    def test_the_verdict_formats_first_example_passes_and_needs_its_class(self):
        page = (HELPER.parent.parent / "references" / "verdict.md").read_text()
        example = re.search(r"```md\n(VERDICT: CHANGES at ([0-9a-f]{40})\n.*?)```", page, re.S)
        self.world({"checks": green(example[2])}, pr={"head": {"sha": example[2]}})
        out = self.run_helper("check", self.file("r.md", example[1]), "--repo", SKILLS, "--pr", "7")
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "report ok"), out.stdout + out.stderr)
        self.assertIn("  Class: files\n", example[1])
        out = self.run_helper("check", self.file("r.md", example[1].replace("  Class: files\n", "")),
                              "--repo", SKILLS, "--pr", "7")
        self.assertEqual(out.stdout.splitlines(),
                         ["R1: a blocker names its class: one Class: line from references/verdict.md"])

    def test_the_skills_own_example_names_its_blockers_class(self):
        page = (HELPER.parent.parent / "SKILL.md").read_text()
        example = re.search(r"```md\n(VERDICT: CHANGES at ([0-9a-f]{40})\n.*?)```", page, re.S)
        self.world({"checks": green(example[2])}, pr={"head": {"sha": example[2]}})
        out = self.run_helper("check", self.file("r.md", example[1]), "--repo", SKILLS, "--pr", "7")
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "report ok"), out.stdout + out.stderr)

    def test_the_recheck_guides_example_keeps_its_blockers_class(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("review_module", HELPER)
        review = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(review)
        md = r"```md\n(VERDICT: (?:CHANGES|APPROVE) at ([0-9a-f]{40})\n.*?)```"
        first = re.search(md, (HELPER.parent.parent / "SKILL.md").read_text(), re.S)
        again = re.search(md, (HELPER.parent.parent / "references" / "re-checks.md").read_text(), re.S)
        problems = review.check(again[1], DESCRIPTION, "re-check", again[2], review.parse(first[1]))
        self.assertEqual(problems, [])

    def test_record_author_row_is_parsed_whole(self):
        row = "| Record authors | `example[bot]`, `owner` |\n"
        for name, bad in {"missing comma": "| Record authors | `example[bot]` `owner` |\n",
                          "two rows": row + "| Record authors | `owner` |\n",
                          "extra cell": "| Record authors | `example[bot]`, `owner` | extra |\n"}.items():
            with self.subTest(name):
                self.world({"files": {f"{SKILLS}@main:docs/agents/fleet.md": FLEET.replace(row, bad)}},
                           comments=[report(FULL.replace(OLD, HEAD))])
                out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
                self.assertEqual((out.returncode, out.stdout), (2, ""), out.stdout)
                self.assertIn("record authors", out.stderr)

    def test_additional_required_check_outside_the_table(self):
        fleet = FLEET.replace("| `check` | Every suite | Pull requests to `main` |\n",
                              "| `ci` | Every lane | `main`, `release-*` |\n\n"
                              "**Additional public check: `privacy` (O3).** It checks the public tree.\n")
        checks = {HEAD: [{"name": "ci", "status": "completed", "conclusion": "success"},
                         {"name": "privacy", "status": "completed", "conclusion": "failure"}]}
        self.world({"files": {f"{SKILLS}@main:docs/agents/fleet.md": fleet}, "checks": checks})
        out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
        self.assertEqual((out.returncode, out.stdout.strip()), (1, f"stop: privacy is not green at {HEAD}"))

    def test_identical_text_from_anyone_else_is_not_a_post(self):
        self.world({"checks": green(OLD)}, pr={"head": {"sha": OLD}},
                   comments=[{"body": FULL, "user": {"login": "stranger"}}])
        out = self.run_helper("post", self.file("r.md", FULL), "--repo", SKILLS, "--pr", "7")
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "posted 901"), out.stdout + out.stderr)
        self.assertEqual(self.state()["writes"], 1)

    def test_commands_are_bound_to_the_assigned_head(self):
        out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7", "--head", NEWER)
        self.assertEqual((out.returncode, out.stdout.strip()),
                         (1, f"stop: the head is {HEAD}, not the assigned {NEWER}"))

    def test_pin_reads_one_snapshot(self):
        later = {**self.state()["pulls"]["7"], "draft": True, "head": {"sha": NEWER}, "body": "Closes #99\n"}
        self.world({"pull_sequence": [self.state()["pulls"]["7"], later] * 3, "checks": {**green(HEAD), **green(NEWER)}})
        out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7", "--head", HEAD)
        self.assertEqual(out.stdout.strip(), f"review full #7 at {HEAD}; ticket {PRODUCT}#41; checks check")

    def test_post_repeats_admission_before_writing(self):
        for name, (pr, checks) in {
            "draft": ({"draft": True, "head": {"sha": OLD}}, green(OLD)),
            "failed check": ({"head": {"sha": OLD}},
                             {OLD: [{"name": "check", "status": "completed", "conclusion": "failure"}]}),
        }.items():
            with self.subTest(name):
                self.world({"checks": checks}, pr=pr)
                out = self.run_helper("post", self.file("r.md", FULL), "--repo", SKILLS, "--pr", "7")
                self.assertEqual(out.returncode, 1, out.stdout)
                self.assertTrue(out.stdout.startswith("stop: "), out.stdout)
                self.assertEqual(self.state()["writes"], 0)

    def pacer(self, value=None):
        path = self.root / "state" / "launch-fleet" / "writes.json"
        if value is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value))
        self.assertTrue(path.exists(), "no write went through the pacer")
        return json.loads(path.read_text())

    def test_a_recorded_cooldown_refuses_a_follow_up_without_filing(self):
        until = int(time.time()) + 3600
        self.pacer({"accounts": {}, "inflight": [], "until": until})
        out = self.follow_up()
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(until))
        self.assertEqual((out.returncode, out.stdout, out.stderr),
                         (1, f"refused: write paced, retry after {stamp}\n", ""))
        self.assertEqual(self.state()["writes"], 0)
        self.assertEqual([c for c in self.state()["calls"] if "POST" in c], [])
        self.assertEqual(self.state()["issues"], {})

    def test_an_admitted_follow_up_takes_one_pacer_slot_and_keeps_its_read_back(self):
        out = self.follow_up()
        self.assertEqual((out.returncode, out.stdout), (0, "filed #70\n"), out.stderr)
        state = self.pacer()
        self.assertEqual((len(state["accounts"]["shared"]), state["inflight"], state["until"]), (1, [], 0))
        issue = self.state()["issues"][PRODUCT][0]
        self.assertEqual((issue["title"], [x["name"] for x in issue["labels"]]),
                         ("Help says zip archive file (polish for #41, R2)", ["triage: new"]))
        self.assertEqual(issue["body"], "Follow-up of #41 (spec #38)\n\n`src/cli.rs:30` (Sweep) Help wording. "
                                        f"Fix: say export. Found in pull request {SKILLS}#7 at {OLD}; it is polish "
                                        "and did not block the merge.\n")
        self.world({"hidden_issue_reads": 10})
        out = self.follow_up()
        self.assertEqual((out.returncode, out.stdout),
                         (1, "unknown: not found on read-back; list the issues before filing again\n"))
        self.assertEqual(self.state()["writes"], 1)
        self.assertEqual(len(self.pacer()["accounts"]["shared"]), 2)


COMMENTS = Path(__file__).with_name("comments.py")
CHECKER = Path(__file__).with_name("fixtures") / "comment-check" / "check.py"
SHA = "1234567890" * 4



class CommentPass(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.repo)])
        self.git("init", "-q")
        self.write({"tools/comment-check/check.py": CHECKER.read_text(encoding="utf-8"),
                    "old.py": "x = 1  # workaround kept from before\n"})
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=Builder", "-c", "user.email=b@example.com",
                        *args], check=True, capture_output=True)

    def write(self, files):
        for name, text in files.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    def comment_pass(self, files, *args):
        self.write(files)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "head")
        out = subprocess.run([sys.executable, "-I", str(COMMENTS), "--base", "HEAD^", "--repo", str(self.repo),
                              *args], text=True, capture_output=True, timeout=60)
        findings = [line for line in out.stdout.splitlines() if not line.startswith("check ")]
        return out.returncode, findings, out.stdout + out.stderr

    def kinds(self, files, *args):
        code, findings, out = self.comment_pass(files, *args)
        return code, [f.split(": ", 2)[:2] for f in findings], out

    def assert_code_fix(self, finding):
        fix = finding.split(" Fix: ", 1)[1]
        self.assertRegex(fix, r"\b(name|extract|type|test|check|delete|remove|fix the cause)")
        self.assertNotRegex(fix.lower(), r"reword|rephrase|clarify|shorten|rewrite the comment")

    def test_a_justification_comment_is_a_finding_that_names_the_code_fix(self):
        code, findings, out = self.comment_pass({"src/prices.py": (
            "_cache = {}\n\n# We check the cache first on purpose: the suite timed out without it.\n"
            "def lookup(sku):\n    return _cache.get(sku)\n")})
        self.assertEqual(code, 1, out)
        self.assertEqual(len(findings), 1, out)
        self.assertTrue(findings[0].startswith("src/prices.py:3: justification: "), out)
        self.assert_code_fix(findings[0])

    def test_only_allowed_kinds_give_no_finding_and_each_gets_a_check_line(self):
        code, findings, out = self.comment_pass({"tools/sync.py": (
            "#!/usr/bin/env python3\n# SPDX-License-Identifier: MIT\nimport subprocess\n\n"
            "# External: the vendor API rejects a batch over 100 items, https://example.com/vendor/limits\n"
            "LIMIT = 100\n\n# SECURITY: the token never reaches the log; send() redacts it first.\nA = 1\n\n"
            "# comment-ok: the synthetic runner reads this line as its job name\nB = 2\n"
            "import os  # noqa: E402 -- the path is set up above\nURL = 'https://example.com/#anchor'\n")})
        self.assertEqual((code, findings), (0, []), out)
        for kind in ("2: licence", "5: external", "8: warning", "11: escape", "13: suppression"):
            self.assertIn(f"check tools/sync.py:{kind}: ", out)

    def test_a_workaround_comment_and_a_bare_suppression_are_findings(self):
        code, kinds, out = self.kinds({"src/app.py": (
            "import os\n# TODO: hack for now, the writer races the reader\nx = os.getcwd()\n"
            "y = x.upper()  # type: ignore\n")})
        self.assertEqual(kinds, [["src/app.py:2", "workaround"], ["src/app.py:4", "suppression"]], out)
        for finding in out.splitlines():
            self.assert_code_fix(finding)

    def test_an_unearned_escape_tag_and_external_link_are_findings(self):
        code, kinds, out = self.kinds({"src/app.py": (
            "# comment-ok:\nA = 1\n# External: our runner, https://github.com/openwizdev/OpenWiz/issues/12\nB = 2\n")})
        self.assertEqual(kinds, [["src/app.py:1", "escape-tag-reason"], ["src/app.py:3", "external-link"]], out)

    def test_old_comments_never_count(self):
        self.assertEqual(self.kinds({"old.py": "x = 2  # workaround kept from before\n"})[:2], (1, [
            ["old.py:1", "workaround"]]))
        self.assertEqual(self.kinds({"new.py": "y = 1\n"})[:2], (0, []))

    def test_r1_spaced_and_accented_paths_are_read(self):
        text = "# Workaround for the old runner\nprint(1)\n"
        code, kinds, out = self.kinds({"task runner.py": text, "café.py": text})
        self.assertEqual(sorted(kinds), [["café.py:1", "workaround"], ["task runner.py:1", "workaround"]], out)

    def test_r2_script_yaml_docstring_and_pinned_action(self):
        code, kinds, out = self.kinds({
            "index.html": "<p>hi</p>\n<script>\n// Workaround for the old runner\n</script>\n"
                          '<script type="application/json">\n{"a": "// not script"}\n</script>\n',
            "config.yml": "text: |\n  # Shown to the user as text\n",
            "tool.py": '# SPDX-License-Identifier: MIT\n"""Workaround for the old runner."""\nprint(1)\n',
            ".github/workflows/check.yml": f"steps:\n  - uses: owner/action@{SHA} # v7.0.1\n"})
        self.assertEqual(sorted(kinds), [["index.html:3", "workaround"], ["tool.py:2", "workaround"]], out)

    def test_r3_two_block_comments_on_one_line_are_two_findings(self):
        code, kinds, out = self.kinds({"app.js": (
            "let a = /* first workaround */ 1, b = /* second workaround */ 2;\n"
            "let c = /* SAFETY: synthetic invariant */ 1, d = /* third workaround */ 2;\n")})
        self.assertEqual(kinds, [["app.js:1", "workaround"], ["app.js:1", "workaround"], ["app.js:2", "workaround"]],
                         out)

    def test_r4_licence_and_generated_files_are_excluded(self):
        code, kinds, out = self.kinds({
            "generated.py": "# @generated\n# Workaround for the old runner\nx = 1\n",
            "LICENSE.py": "# Distribution terms\nx = 1\n",
            "late.py": "x = 1\n" * 5 + "# DO NOT EDIT: workaround for the old runner\n"})
        self.assertEqual(kinds, [["late.py:6", "workaround"]], out)

    def test_a_repository_with_no_checker_gets_one_line(self):
        self.git("rm", "-q", "tools/comment-check/check.py")
        self.git("commit", "-q", "-m", "no checker")
        code, findings, out = self.comment_pass({"src/app.py": "# workaround for the old runner\nx = 1\n"})
        self.assertEqual((code, out.splitlines()), (3, [
            "no checker: the base revision has no tools/comment-check/check.py and no --checker was given; "
            "read the diff's comments yourself"]))

    def test_another_checker_location_is_used_with_checker(self):
        self.git("rm", "-q", "tools/comment-check/check.py")
        self.git("commit", "-q", "-m", "no checker")
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(outside)])
        (outside / "comments.py").write_text(CHECKER.read_text(encoding="utf-8"), encoding="utf-8")
        code, kinds, out = self.kinds({"src/app.py": "# workaround for the old runner\nx = 1\n"},
                                      "--checker", str(outside / "comments.py"))
        self.assertEqual(kinds, [["src/app.py:1", "workaround"]], out)

    def planted(self):
        mark = Path(tempfile.mkdtemp()) / "ran"
        self.addCleanup(subprocess.run, ["rm", "-rf", str(mark.parent)])
        return mark, f"import pathlib\npathlib.Path({str(mark)!r}).write_text('ran')\n"

    def test_a_checker_the_pull_request_changes_never_runs(self):
        mark, planted = self.planted()
        code, kinds, out = self.kinds({"tools/comment-check/check.py": planted,
                                       "src/app.py": "# workaround for the old runner\nx = 1\n"})
        self.assertFalse(mark.exists(), "the pull request's checker ran")
        self.assertEqual(kinds, [["src/app.py:1", "workaround"]], out)

    def test_a_checker_the_pull_request_adds_never_runs(self):
        self.git("rm", "-q", "tools/comment-check/check.py")
        self.git("commit", "-q", "-m", "no checker")
        mark, planted = self.planted()
        code, findings, out = self.comment_pass({"tools/comment-check/check.py": planted,
                                                 "src/app.py": "# workaround for the old runner\nx = 1\n"})
        self.assertFalse(mark.exists(), "the pull request's checker ran")
        self.assertEqual((code, len(out.splitlines())), (3, 1), out)
        self.assertTrue(out.startswith("no checker: "), out)

    def test_a_checker_inside_the_reviewed_checkout_is_refused(self):
        mark, planted = self.planted()
        code, findings, out = self.comment_pass({"lint/comments.py": planted},
                                                "--checker", str(self.repo / "lint" / "comments.py"))
        self.assertFalse(mark.exists(), "a checker from the reviewed checkout ran")
        self.assertEqual((code, len(out.splitlines())), (2, 1), out)
        self.assertTrue(out.startswith("refused: "), out)


RULES = ("# Review rules\n\n## Never flag\n\n- style-only renames in tests: declined 4, 2026-11-20\n\n"
         "## Path rules\n\n- `src/export/**`: an export never overwrites an existing file\n"
         "- `docs/*.md`: every page links back to the index\n- `**/cli.rs`: every flag has help text\n\n"
         "## Severity examples\n\n- Blocking: an export silently replaces the last one\n")


class ReviewRules(unittest.TestCase):

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.repo)])
        self.git("init", "-q", "-b", "main")

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=Builder", "-c", "user.email=b@example.com",
                        *args], check=True, capture_output=True)

    def commit(self, files, branch):
        for name, text in files.items():
            (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / name).write_text(text, encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", branch)
        self.git("branch", "-f", branch)

    def rules(self, base_files, head_files, *findings):
        self.commit({"README.md": "pantry\n", **base_files}, "base")
        self.commit(head_files, "head")
        args = [a for f in findings for a in ("--finding", f)]
        out = subprocess.run([sys.executable, "-I", str(HELPER), "rules", "--base", "base", "--head", "head", *args],
                             text=True, capture_output=True, timeout=60, cwd=self.repo)
        return out.returncode, out.stdout.splitlines(), out.stdout + out.stderr

    CHANGED = {"src/export/zip/write.rs": "fn write() {}\n", "src/cli.rs": "fn main() {}\n",
               "tests/export.rs": "fn renamed() {}\n"}

    def test_a_never_flag_class_skips_its_planted_finding(self):
        code, lines, out = self.rules({"docs/agents/review-rules.md": RULES}, self.CHANGED,
                                      "Style-only renames in tests", "unchecked error")
        self.assertEqual(code, 0, out)
        self.assertIn("never flag: style-only renames in tests (declined 4, 2026-11-20)", lines)
        self.assertIn("skip: Style-only renames in tests", lines)
        self.assertIn("report: unchecked error", lines)

    def test_without_the_file_the_same_finding_is_reported(self):
        code, lines, out = self.rules({}, self.CHANGED, "style-only renames in tests")
        self.assertEqual(code, 0, out)
        self.assertEqual(lines, ["review rules: none at base", "report: style-only renames in tests"])

    def test_path_rules_apply_only_where_a_changed_path_matches(self):
        code, lines, out = self.rules({"docs/agents/review-rules.md": RULES},
                                      {**self.CHANGED, "docs/guide/page.md": "x\n"})
        self.assertEqual(code, 0, out)
        rules = [x for x in lines if x.startswith("path rule: ")]
        self.assertEqual(rules, ["path rule: `src/export/**`: an export never overwrites an existing file",
                                 "path rule: `**/cli.rs`: every flag has help text"])

    def test_the_head_cannot_change_its_own_rules(self):
        widened = RULES.replace("## Path rules", "- unchecked error: declined 1, 2026-11-21\n\n## Path rules")
        code, lines, out = self.rules({"docs/agents/review-rules.md": RULES},
                                      {**self.CHANGED, "docs/agents/review-rules.md": widened}, "unchecked error")
        self.assertEqual(code, 0, out)
        self.assertIn("report: unchecked error", lines)

    def test_an_unreadable_line_refuses(self):
        bad = RULES.replace("declined 4, 2026-11-20", "declined often")
        code, lines, out = self.rules({"docs/agents/review-rules.md": bad}, self.CHANGED, "unchecked error")
        self.assertEqual(code, 2, out)
        self.assertIn("style-only renames in tests: declined often", out)

    def test_the_shipped_template_has_no_rules(self):
        shipped = (HELPER.parents[2] / "setup" / "templates" / "review-rules.md").read_text(encoding="utf-8")
        code, lines, out = self.rules({"docs/agents/review-rules.md": shipped}, {**self.CHANGED, "<glob>": "x\n"},
                                      "style-only renames in tests")
        self.assertEqual(code, 0, out)
        self.assertEqual(lines, ["report: style-only renames in tests"])


class ReadOnlyCheckout(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.run_dir = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.repo), str(self.run_dir)])
        self.git("init", "-q")
        (self.repo / "a.txt").write_text("a\n", encoding="utf-8")
        (self.repo / "dirty.txt").write_text("base\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        (self.repo / "dirty.txt").write_text("already dirty\n", encoding="utf-8")
        self.snap = self.run_dir / "checkout.json"
        self.snapshot = self.helper("snapshot", str(self.snap))

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=Reviewer", "-c",
                               "user.email=r@example.com", *args], check=True, capture_output=True, text=True)

    def helper(self, *args):
        return subprocess.run([sys.executable, "-I", str(HELPER), *args], cwd=self.repo, text=True,
                              capture_output=True, timeout=60)

    def verify(self):
        out = self.helper("verify", str(self.snap))
        return out.returncode, out.stdout.strip(), out.stderr

    def test_an_untouched_checkout_passes(self):
        self.assertEqual((self.snapshot.returncode, self.snapshot.stdout.strip()), (0, "snapshot: ok"))
        self.assertEqual(self.verify()[:2], (0, "verify: ok"))

    def test_scratch_worktree_under_the_temp_folder_is_ignored(self):
        scratch = self.run_dir / "undo"
        self.git("worktree", "add", "-q", "--detach", str(scratch))
        (scratch / "a.txt").write_text("undone\n", encoding="utf-8")
        (scratch / "new.txt").write_text("scratch\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(scratch), "-c", "user.name=Reviewer", "-c", "user.email=r@example.com",
                        "commit", "-qam", "undo"], check=True, capture_output=True)
        self.assertEqual(self.verify()[:2], (0, "verify: ok"))

    def test_an_edited_file_fails_and_is_named(self):
        (self.repo / "a.txt").write_text("edited\n", encoding="utf-8")
        (self.repo / "dirty.txt").write_text("edited again\n", encoding="utf-8")
        self.assertEqual(self.verify()[:2], (1, "reviewer changed the checkout: a.txt, dirty.txt"))

    def test_a_new_untracked_file_fails_and_is_named(self):
        (self.repo / "notes").mkdir()
        (self.repo / "notes" / "fix.py").write_text("x = 1\n", encoding="utf-8")
        self.assertEqual(self.verify()[:2], (1, "reviewer changed the checkout: notes/fix.py"))

    def test_a_new_commit_fails_and_names_its_files(self):
        (self.repo / "a.txt").write_text("committed\n", encoding="utf-8")
        self.git("commit", "-qm", "reviewer fix", "a.txt")
        self.assertEqual(self.verify()[:2], (1, "reviewer changed the checkout: HEAD, a.txt"))

    def test_an_empty_commit_still_fails(self):
        self.git("commit", "-q", "--allow-empty", "-m", "empty")
        self.assertEqual(self.verify()[:2], (1, "reviewer changed the checkout: HEAD"))

    def test_a_missing_or_broken_snapshot_refuses(self):
        for bad in ("{", '{"top": "/tmp/x", "head": "--evil", "status": {}}',
                    '{"top": "/tmp/x", "head": "' + "a" * 40 + '", "status": [], "extra": 1}'):
            self.snap.write_text(bad, encoding="utf-8")
            code, out, err = self.verify()
            self.assertEqual((code, out), (2, ""))
            self.assertTrue(err.startswith("refused: "), err)
        self.snap.unlink()
        self.assertEqual(self.verify()[0], 2)

    def test_a_snapshot_inside_the_checkout_refuses(self):
        out = self.helper("snapshot", str(self.repo / "snap.json"))
        self.assertEqual(out.returncode, 2, out.stdout + out.stderr)
        self.assertFalse((self.repo / "snap.json").exists())


def extract_backticks(text, pattern):
    return [match.group(1) for match in re.finditer(r"`([^`\n]+)`", text) if re.search(pattern, match.group(1))]


def extract_backtick(text, pattern):
    matches = extract_backticks(text, pattern)
    return matches[0] if matches else None


def instruction_source_errors(text):
    errors = []
    if re.search(r"\bHEAD:", text):
        errors.append("reads from HEAD:")
    if "git show origin/<base>:<path>" not in text:
        errors.append("missing git show origin/<base>:<path>")
    para = next((p for p in text.split("\n\n") if "git show origin/<base>:<path>" in p), "")
    for name in ("AGENTS.md", "CLAUDE.md", "docs/agents/fleet.md"):
        if name not in para:
            errors.append(f"base-branch instruction rule omits {name}")
    if "outside the reviewed checkout" not in text:
        errors.append("tooling not pinned outside the reviewed checkout")
    if not extract_backtick(text, r"worktree add --detach \"\$base_tree\" origin/<base>"):
        errors.append("missing clean fetched-base worktree setup")
    context_cmds = extract_backticks(text, r"\$C reviewer\b")
    if not context_cmds or any("$base_tree" not in cmd for cmd in context_cmds):
        errors.append("context command not pinned to clean fetched-base worktree")
    check_cmds = extract_backticks(text, r"\$C check\b")
    if not check_cmds or any("$base_tree" not in cmd for cmd in check_cmds):
        errors.append("public-write check not pinned to clean fetched-base worktree")
    return errors


class InstructionSources(unittest.TestCase):

    CONTEXT_HELPER = HELPER.parents[2] / "launch-fleet" / "scripts" / "context.py"

    def git(self, repo, *args):
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        return subprocess.run(
            ["git", "-C", str(repo), "-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.com",
             "-c", "core.hooksPath=/dev/null", *args],
            check=True, capture_output=True, text=True, env=env,
        ).stdout.strip()

    def write_files(self, root, files):
        for rel, content in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    def run_skill_sh(self, cwd, command, env):
        return subprocess.run(["/bin/sh", "-c", command], cwd=cwd, env=env, capture_output=True, text=True, timeout=30)

    def test_skill_reads_instruction_files_from_base_branch_not_head(self):
        skill = (HELPER.parent.parent / "SKILL.md").read_text(encoding="utf-8")
        self.assertEqual(instruction_source_errors(skill), [])
        for bad in (
            skill + "\nRead `AGENTS.md` with `git rev-parse HEAD:<path>`.\n",
            skill.replace("origin/<base>:<path>", "HEAD:<path>"),
            skill + "\nCheck `git show HEAD:AGENTS.md`.\n",
        ):
            self.assertIn("reads from HEAD:", instruction_source_errors(bad))

    def test_review_workflow_enforces_fetched_base_provenance_for_instructions_context_and_privacy(self):
        skill = (HELPER.parent.parent / "SKILL.md").read_text(encoding="utf-8")
        setup_cmd = extract_backtick(skill, r"worktree add --detach \"\$base_tree\" origin/<base>")
        show_cmd = extract_backtick(skill, r"git show origin/<base>:<path>")
        context_cmd = extract_backtick(skill, r"\$C reviewer\b")
        check_cmd = extract_backtick(skill, r"\$C check\b")
        self.assertIsNotNone(show_cmd, "SKILL.md missing git show command")
        self.assertIsNotNone(context_cmd, "SKILL.md missing $C reviewer command")
        self.assertIsNotNone(check_cmd, "SKILL.md missing $C check command")

        base_fleet = (
            "# Fleet settings\n\n"
            "## Models\n\n| Role | Model |\n| --- | --- |\n| Reviewer | BaseModel |\n\n"
            "## Supporting edits\n\nBase supporting rule.\n\n"
            "## Test commands\n\nBase test command.\n\n"
            "## CI checks\n\nBase CI checks.\n\n"
            "## Approval rules\n\nBase approval rules.\n"
        )
        base_card = "# Public writes\n\nBase public-writes card.\n"
        base_checker = (
            "import argparse\n"
            "from pathlib import Path\n"
            "p = argparse.ArgumentParser()\n"
            "p.add_argument('--title-file', type=Path, required=True)\n"
            "p.add_argument('--body-file', type=Path, required=True)\n"
            "a = p.parse_args()\n"
            "if 'BASE_PRIVACY_TRIGGER' in a.body_file.read_text(encoding='utf-8'):\n"
            "    print('T3 pr-body:1')\n"
            "    raise SystemExit(1)\n"
            "raise SystemExit(0)\n"
        )

        for with_base_checker in (True, False):
            with self.subTest(with_base_checker=with_base_checker), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                bare = root / "origin.git"
                checkout = root / "checkout"
                base_tree = root / "base-tree"
                pr_marker = root / "pr-checker-ran"
                hook_marker = root / "pr-hook-ran"

                subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(bare)], check=True)
                subprocess.run(["git", "clone", "-q", str(bare), str(checkout)], check=True)

                stale_files = {
                    "AGENTS.md": "STALE_BASE_AGENTS\n",
                    "CLAUDE.md": "STALE_BASE_CLAUDE\n",
                    "sub/CLAUDE.md": "STALE_BASE_SUB_CLAUDE\n",
                    "docs/agents/fleet.md": base_fleet.replace("BaseModel", "StaleLocalBaseModel"),
                    "docs/agents/public-writes.md": "# Public writes\n\nStale local card.\n",
                    "GLOSSARY.md": "# Glossary\n",
                }
                self.write_files(checkout, stale_files)
                self.git(checkout, "add", "-A")
                self.git(checkout, "commit", "-qm", "stale-base")
                stale_sha = self.git(checkout, "rev-parse", "HEAD")

                base_files = {
                    "AGENTS.md": "BASE_AGENTS_INSTRUCTIONS\n",
                    "CLAUDE.md": "BASE_ROOT_CLAUDE\n",
                    "sub/CLAUDE.md": "BASE_SUB_CLAUDE\n",
                    "docs/agents/fleet.md": base_fleet,
                    "docs/agents/public-writes.md": base_card,
                    "GLOSSARY.md": "# Glossary\n",
                }
                if with_base_checker:
                    base_files["tools/privacy-check/check.py"] = base_checker
                self.write_files(checkout, base_files)
                self.git(checkout, "add", "-A")
                self.git(checkout, "commit", "-qm", "base")
                self.git(checkout, "push", "-q", "origin", "main")
                base_sha = self.git(checkout, "rev-parse", "origin/main")

                self.git(checkout, "checkout", "-qb", "pr-branch")
                pr_checker = (
                    "from pathlib import Path\n"
                    f"Path({str(pr_marker)!r}).write_text('pwned', encoding='utf-8')\n"
                    "raise SystemExit(0)\n"
                )
                pr_hook = f"#!/bin/sh\necho pwned > {shlex.quote(str(hook_marker))}\n"
                self.write_files(checkout, {
                    "AGENTS.md": "PR_POISONED_AGENTS\n",
                    "CLAUDE.md": "PR_POISONED_ROOT_CLAUDE\n",
                    "sub/CLAUDE.md": "PR_POISONED_SUB_CLAUDE\n",
                    "docs/agents/fleet.md": base_fleet.replace("BaseModel", "PRPoisonedModel"),
                    "docs/agents/public-writes.md": "# Public writes\n\nPR_POISONED_CARD\n",
                    "tools/privacy-check/check.py": pr_checker,
                    ".githooks/post-checkout": pr_hook,
                })
                (checkout / ".githooks/post-checkout").chmod(0o755)
                self.git(checkout, "add", "-A")
                self.git(checkout, "commit", "-qm", "pr")
                pr_sha = self.git(checkout, "rev-parse", "HEAD")
                self.git(checkout, "push", "-q", "origin", "HEAD:refs/pull/42/head")
                self.git(checkout, "checkout", "-q", "main")
                self.git(checkout, "branch", "-D", "pr-branch")
                self.git(checkout, "reset", "--hard", stale_sha)
                self.git(checkout, "update-ref", "refs/remotes/origin/main", stale_sha)
                self.git(checkout, "config", "core.hooksPath", ".githooks")

                self.write_files(checkout, {
                    "docs/agents/fleet.md": base_fleet.replace("BaseModel", "UNSAVED_LOCAL_DRAFT"),
                    "docs/agents/public-writes.md": "# Public writes\n\nUNSAVED_LOCAL_CARD\n",
                    "tools/privacy-check/check.py": pr_checker,
                    ".githooks/post-checkout": pr_hook,
                })
                (checkout / ".githooks/post-checkout").chmod(0o755)

                base_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
                env = {
                    **base_env,
                    "TMPDIR": str(root),
                    "C": f"{shlex.quote(sys.executable)} -I {shlex.quote(str(self.CONTEXT_HELPER))}",
                    "base_tree": str(base_tree),
                }

                if setup_cmd:
                    setup_script = setup_cmd.replace("<base>", "main") + '\nprintf "\\n%s\\n" "$base_tree"'
                    setup = self.run_skill_sh(checkout, setup_script, env)
                    self.assertEqual(setup.returncode, 0, setup.stdout + setup.stderr)
                    base_tree = Path(setup.stdout.splitlines()[-1])
                    env["base_tree"] = str(base_tree)
                    self.assertEqual(self.git(base_tree, "rev-parse", "HEAD"), base_sha)
                    self.assertFalse(hook_marker.exists(), "worktree setup ran a hook")

                ctx = self.run_skill_sh(checkout, context_cmd, env)
                self.assertEqual(ctx.returncode, 0, ctx.stdout + ctx.stderr)
                self.assertIn("BaseModel", ctx.stdout)
                self.assertIn("Base public-writes card.", ctx.stdout)
                self.assertNotIn("StaleLocalBaseModel", ctx.stdout)
                self.assertNotIn("UNSAVED_LOCAL_DRAFT", ctx.stdout)
                self.assertNotIn("UNSAVED_LOCAL_CARD", ctx.stdout)
                self.assertNotIn("PRPoisonedModel", ctx.stdout)
                expected_fleet_blob = self.git(checkout, "rev-parse", "origin/main:docs/agents/fleet.md")
                expected_card_blob = self.git(checkout, "rev-parse", "origin/main:docs/agents/public-writes.md")
                self.assertIn(f"docs/agents/fleet.md {expected_fleet_blob}", ctx.stdout)
                self.assertIn(f"docs/agents/public-writes.md {expected_card_blob}", ctx.stdout)

                self.git(checkout, "checkout", "--force", "--detach", pr_sha)

                for rel, expected in (
                    ("AGENTS.md", "BASE_AGENTS_INSTRUCTIONS\n"),
                    ("CLAUDE.md", "BASE_ROOT_CLAUDE\n"),
                    ("sub/CLAUDE.md", "BASE_SUB_CLAUDE\n"),
                    ("docs/agents/fleet.md", base_fleet),
                ):
                    cmd = show_cmd.replace("<base>", "main").replace("<path>", rel)
                    shown = self.run_skill_sh(checkout, cmd, env)
                    self.assertEqual(shown.returncode, 0, shown.stderr)
                    self.assertEqual(shown.stdout, expected)

                ctx_after = self.run_skill_sh(checkout, context_cmd, env)
                self.assertEqual(ctx_after.returncode, 0, ctx_after.stdout + ctx_after.stderr)
                self.assertIn("BaseModel", ctx_after.stdout)
                self.assertNotIn("PRPoisonedModel", ctx_after.stdout)
                self.assertNotIn("PR_POISONED_CARD", ctx_after.stdout)

                clean_report = root / "clean.md"
                clean_report.write_text("VERDICT: APPROVE\n\nSynthetic clean report.\n", encoding="utf-8")
                bad_report = root / "bad.md"
                bad_report.write_text(
                    "BASE_PRIVACY_TRIGGER\n" if with_base_checker else "thr_" + "planted1\n",
                    encoding="utf-8",
                )

                for report_path, expected_code, expected_text in (
                    (clean_report, 0, "check: ok"),
                    (bad_report, 1, "project privacy check T3" if with_base_checker else "thread id"),
                ):
                    cmd = re.sub(r"<[^>]+>", shlex.quote(str(report_path)), check_cmd)
                    checked = self.run_skill_sh(checkout, cmd, env)
                    self.assertEqual(checked.returncode, expected_code, checked.stdout + checked.stderr)
                    self.assertIn(expected_text, checked.stdout)
                    self.assertFalse(pr_marker.exists(), "PR checkout privacy checker ran")

                if setup_cmd and base_tree.exists():
                    self.git(checkout, "worktree", "remove", "--force", str(base_tree))


if __name__ == "__main__":
    unittest.main()
