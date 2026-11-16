"""The test of check-helpers.sh (ClosedWiz#206, spec claim W2), through a fake
`gh` (fake_gh.py) over a synthetic repository.

Each case builds the repository as it was when the lead took its snapshot
(BEFORE) and as it is once the swarm is done (AFTER), runs `snapshot` on the
first and `check` on the second, in a scratch folder whose PATH holds only
the fake `gh`, `jq` and the few tools the check uses, so the real `gh` is
never reached. It asserts the exit code and, for exit 0 or 1, the exact
stdout and an empty stderr; for exit 2, an empty stdout and the expected
reason on stderr. A case can also name the exact reads each step made.

Prints one "FAIL [<case>] <why>" line per failure, then "PASS: <n> cases" (exit
0) or "FAIL: <k> of <n> cases" (exit 1); fewer cases run than written is a
failure too. CHECK_HELPERS_SH=<file> runs the cases against another script;
TEST_ONLY=<case> runs only that case; LIST_CASES=1 prints every case's name;
TEST_JOBS=<n> runs n cases at a time (default 4; each has its own folder).

Usage: python3 -I skills/build-ticket/scripts/test/test_check_helpers.py
"""

import concurrent.futures
import copy
import functools
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SCRIPT = pathlib.Path(os.environ.get("CHECK_HELPERS_SH") or HERE.parent / "check-helpers.sh").resolve()
FAKE = HERE / "fake_gh.py"
RECORDS = HERE.parents[2] / "launch-fleet" / "SKILL.md"
TOOLS = ["mkdir", "jq", "mktemp", "rm", "cat", "cp", "head", "sed"]

REPO = "example/widgets"
# The default Record authors setting the fake serves (#717).
FLEET = ("# Fleet settings\n\n## GitHub identity\n\n| Setting | Value |\n| --- | --- |\n"
         "| Record authors | `openwiz[bot]`, `robin` |\n\n## Standing merge rules\n")
LEAD = "room/12-widget-store-ab12"   # the builder's branch for ticket #12
OUTSIDE = "feature/widget-store"      # pull request #32's branch, outside room/12-


def sha(text):
    """A full commit made of TEXT repeated."""
    return (text * 40)[:40]


def comment(cid, body, at="2026-11-01T10:00:00Z"):
    return {"id": cid, "body": body, "updated_at": at}


def base():
    """The repository before the swarm: ticket #12, its pull request #31,
    another pull request #32 whose branch is outside room/12-, and other
    tickets' branches."""
    return {
        "repo": REPO,
        "issues": {
            "12": {"pull": False, "comments": [
                comment(1201, "launch-fleet: starting"),
                comment(1202, "launch-fleet: started, thread thr_synb12"),
                comment(1203, "Which seam should the check use? Recommendation: the CLI.")]},
            "31": {"pull": True, "comments": [
                comment(3101, f"launch-fleet: review started {sha('12a')}, thread thr_synr31"),
                comment(3102, f"VERDICT: CHANGES at {sha('12a')}")]},
            "32": {"pull": True, "comments": []},
            "40": {"pull": False, "comments": [comment(4001, "Another ticket.")]},
        },
        "pulls": {
            "31": {"state": "open", "merged": False, "head": LEAD,
                   "reviews": [{"id": 3150, "body": "", "state": "COMMENTED", "submitted_at": "2026-11-01T10:00:00Z"}],
                   "review_comments": [comment(3160, "A synthetic note on one line.")]},
            "32": {"state": "open", "merged": False, "head": OUTSIDE, "reviews": [], "review_comments": []},
        },
        "refs": {
            LEAD: sha("12a"),
            "room/120-gadget-cd34": sha("c0"),
            "room/1-docs-ef56": sha("d0"),
            "room/12a-other-0f0f": sha("e0"),
            OUTSIDE: sha("f1"),
            OUTSIDE + "-2": sha("f2"),
            "main": sha("0e"),
        },
    }


# Changes to a repository, for BEFORE and AFTER.
def chain(*changes):
    def run(w):
        for change in changes:
            change(w)
    return run


def add_ref(name, commit):
    return lambda w: w["refs"].__setitem__(name, commit)


def del_ref(name):
    return lambda w: w["refs"].pop(name)


def add_comment(n, cid, body, at="2026-11-01T11:00:00Z"):
    return lambda w: w["issues"][str(n)]["comments"].append(comment(cid, body, at))


def find(items, cid):
    return next(c for c in items if c["id"] == cid)


def edit_comment(n, cid, body=None, at="2026-11-01T11:30:00Z"):
    def run(w):
        c = find(w["issues"][str(n)]["comments"], cid)
        if body is not None:
            c["body"] = body
        c["updated_at"] = at
    return run


def del_comment(n, cid):
    return lambda w: w["issues"][str(n)]["comments"].remove(find(w["issues"][str(n)]["comments"], cid))


def add_review(p, rid, state="COMMENTED", body="Looks fine."):
    return lambda w: w["pulls"][str(p)]["reviews"].append(
        {"id": rid, "body": body, "state": state, "submitted_at": "2026-11-01T11:00:00Z"})


def set_review(p, rid, state):
    return lambda w: find(w["pulls"][str(p)]["reviews"], rid).__setitem__("state", state)


def add_inline(p, cid, body):
    return lambda w: w["pulls"][str(p)]["review_comments"].append(comment(cid, body, "2026-11-01T11:00:00Z"))


def edit_inline(p, cid, body):
    def run(w):
        c = find(w["pulls"][str(p)]["review_comments"], cid)
        c["body"], c["updated_at"] = body, "2026-11-01T11:30:00Z"
    return run


def set_pull(p, state, merged):
    def run(w):
        w["pulls"][str(p)]["state"], w["pulls"][str(p)]["merged"] = state, merged
    return run


NOTHING = chain()
BUILDER = ["12"]
REVIEWER = ["12", "31"]
CLEAN_B = "clean #12: nothing changed but the writes you named (branches 1, comments 3)\n"
CLEAN_R = "clean #12: nothing changed but the writes you named (branches 1, comments 7, pull request #31)\n"


def hits(*lines):
    return "".join(f"hit #12: {line}\n" for line in lines)


CASES = []


def add_case(name, want, out="", err="", step="check", snap=BUILDER, before=NOTHING, after=NOTHING, check=(),
         fault=None, env=None, drop=(), snapfile=None, logs=None, raw=None, records=lambda text: text,
         no_paths=False, own_folder=False):
    """One case. WANT is the exit code of STEP, the step under test (`check`,
    after a snapshot that must pass, or `snapshot`). OUT is the exact stdout
    (exit 0 or 1); ERR a part of stderr (exit 2). FAULT is (step, "line=kind").
    ENV is (step or "both", {var: value}). DROP leaves tools off PATH.
    SNAPFILE turns the snapshot's text into the file `check` reads. LOGS is
    the exact reads of (snapshot, check). RAW, for a snapshot step, is its
    whole argument list, in place of `snapshot SNAP...`. RECORDS changes the
    adjacent Records document, or None omits it. NO_PATHS forbids path separators
    in either output stream. OWN_FOLDER runs the script by filename from its
    own folder, as its usage header shows."""
    assert step in ("snapshot", "check")
    CASES.append(dict(name=name, want=want, out=out, err=err, step=step, snap=list(snap), before=before,
                      after=after, check=list(check), fault=fault, env=env, drop=set(drop), snapfile=snapfile,
                      logs=logs, raw=raw, records=records, no_paths=no_paths, own_folder=own_folder))


case = add_case

# #446: the usage header's invocation must still read the adjacent Records.
# Isolate filename resolution from unrelated changes to the live Records table.
FOLDER_RECORDS = """# Synthetic Records fixture

## Records

| On | Record | Means |
| --- | --- | --- |
| A ticket | `launch-fleet: archived` | A fixture record |
"""
case("446: named loop record by absolute path from another folder", 0,
     CLEAN_B.replace("comments 3", "comments 4"), records=lambda _: FOLDER_RECORDS,
     after=add_comment(12, 1204, "launch-fleet: archived"), check=["--loop-comment", "1204"])
case("446: named loop record from the script's own folder", 0,
     CLEAN_B.replace("comments 3", "comments 4"), own_folder=True, records=lambda _: FOLDER_RECORDS,
     after=add_comment(12, 1204, "launch-fleet: archived"), check=["--loop-comment", "1204"])
case("446: invalid loop record from the script's own folder", 1,
     hits("comment 1204 on #12 is new"), own_folder=True, records=lambda _: FOLDER_RECORDS,
     after=add_comment(12, 1204, "launch-fleet: invented"), check=["--loop-comment", "1204"])
case("446: missing Records from the script's own folder", 2,
     err="can't read launch-fleet Records:", own_folder=True, records=None,
     after=add_comment(12, 1204, "launch-fleet: archived"), check=["--loop-comment", "1204"])

# ---- W2b: a clean swarm passes ----
case("clean: nothing changed (builder)", 0, CLEAN_B,
     logs=(["repo view", "issue 12", "refs room/12-", "comments 12"], ["refs room/12-", "comments 12"]))
case("clean: nothing changed (reviewer)", 0, CLEAN_R, snap=REVIEWER,
     logs=(["repo view", "issue 12", "pull 31", "refs room/12-", "comments 12", "comments 31", "reviews 31",
            "review comments 31"],
           ["pull 31", "refs room/12-", "comments 12", "comments 31", "reviews 31", "review comments 31"]))
case("clean: GH_REPO names the repository, so no repo view", 0, CLEAN_B, env=("snapshot", {"GH_REPO": REPO}),
     logs=(["issue 12", "refs room/12-", "comments 12"], ["refs room/12-", "comments 12"]))
case("clean: the lead pushed its own commit", 0, CLEAN_B,
     after=add_ref(LEAD, sha("12b")), check=["--own", LEAD, sha("12b")])
case("clean: the lead's first push, during the swarm", 0, CLEAN_B,
     before=del_ref(LEAD), after=add_ref(LEAD, sha("12b")), check=["--own", LEAD, sha("12b")])
case("clean: --own names a branch that did not move", 0, CLEAN_B, check=["--own", LEAD, sha("12b")])
case("clean: the lead's own new comment", 0,
     CLEAN_B.replace("comments 3", "comments 4"),
     after=add_comment(12, 1204, "Question: synthetic?"), check=["--own-comment", "1204"])
case("clean: the lead's own comments, new, edited and deleted", 0,
     CLEAN_B,
     after=chain(add_comment(12, 1204, "A"), edit_comment(12, 1203, "Edited."), del_comment(12, 1203)),
     check=["--own-comment", "1204", "--own-comment", "1203"])
case("clean: the reviewer's own report on the pull request", 0,
     CLEAN_R.replace("comments 7", "comments 8"), snap=REVIEWER,
     after=add_comment(31, 3103, f"VERDICT: APPROVE at {sha('12a')}"), check=["--own-comment", "3103"])
case("clean: the loop's new records and an edited claim, named", 0,
     CLEAN_B.replace("comments 3", "comments 5"),
     after=chain(add_comment(12, 1204, f"launch-fleet: start checked, thread thr_synb12, branch {LEAD}"),
                 add_comment(12, 1205, "launch-fleet: archived"),
                 edit_comment(12, 1201, "launch-fleet: start failed: synthetic")),
     check=["--loop-comment", "1204", "--loop-comment", "1205", "--loop-comment", "1201"])
case("clean: the loop's record on the pull request, named", 0, CLEAN_R.replace("comments 7", "comments 8"),
     snap=REVIEWER, after=add_comment(31, 3103, f"launch-fleet: findings sent {sha('12a')}"),
     check=["--loop-comment", "3103"])
case("clean: every record form the loop writes, named", 0, CLEAN_R.replace("comments 7", "comments 29"), snap=REVIEWER,
     after=chain(*[add_comment(12 if i < 9 else 31, 5000 + i, body) for i, body in enumerate([
         "launch-fleet: starting", "launch-fleet: started, thread thr_synb12",
         f"launch-fleet: start checked, thread thr_synb12, branch {LEAD}", "launch-fleet: start refused: synthetic",
         "launch-fleet: start failed: synthetic", "launch-fleet: start withdrawn", "launch-fleet: held for #40",
         "launch-fleet: noted #40", "launch-fleet: asked the orchestrator",
         f"launch-fleet: review starting {sha('12a')}", f"launch-fleet: review started {sha('12a')}, thread thr_synr31",
         f"launch-fleet: review refused {sha('12a')}: synthetic", f"launch-fleet: review failed {sha('12a')}: synthetic",
         f"launch-fleet: review withdrawn {sha('12a')}", f"launch-fleet: re-check sent {sha('12a')}, thread thr_synr31",
         f"launch-fleet: review told again {sha('12a')}, thread thr_synr31", f"launch-fleet: CI failure sent {sha('12a')}",
         f"launch-fleet: findings sent {sha('12a')}", f"launch-fleet: merge blocked {sha('12a')}: synthetic",
         "launch-fleet: look: synthetic", "launch-fleet: told the user", "launch-fleet: archived"])]),
     check=[x for i in range(22) for x in ("--loop-comment", str(5000 + i))])
# #1273: public forms and legacy reads differ only with positive private metadata.
for body in ("launch-fleet: started", f"launch-fleet: start checked, branch {LEAD}",
             f"launch-fleet: review given up {sha('12a')}: no verdict"):
    case("1273: public record exemption: " + body, 0, CLEAN_B.replace("comments 3", "comments 4"),
         before=lambda w: w.update(private=False), after=add_comment(12, 1204, body), check=["--loop-comment", "1204"])
for body in ("launch-fleet: started, thread thr_synbuilder", "launch-fleet: look: inspect thr_synbuilder"):
    case("1273: public record refuses thread: " + body, 1, hits("comment 1204 on #12 is new"),
         before=lambda w: w.update(private=False), after=add_comment(12, 1204, body), check=["--loop-comment", "1204"])

# #490: fixed forms require newline or end, as before #444.
# Exact fixture examples independent of the table parser.
for form in ("starting", "start withdrawn", "asked the orchestrator", "told the user", "archived"):
    for suffix in (". Synthetic detail.", ": synthetic detail", ", synthetic detail", " synthetic detail", "! Synthetic detail.", "; synthetic detail", "\nSynthetic detail."):
        newline = suffix.startswith("\n")
        case(f"490: same-line or newline details: {form}{suffix!r}", 0 if newline else 1,
             CLEAN_B.replace("comments 3", "comments 4") if newline else hits("comment 1204 on #12 is new"),
             after=add_comment(12, 1204, "launch-fleet: " + form + suffix), check=["--loop-comment", "1204"])
case("490: edited records accept newline details before and after", 0, CLEAN_B,
     before=edit_comment(12, 1201, "launch-fleet: asked the orchestrator\nSynthetic question."),
     after=edit_comment(12, 1201, "launch-fleet: told the user\nSynthetic answer."), check=["--loop-comment", "1201"])
for old, new in (
    ("launch-fleet: archived, says a helper", "launch-fleet: archived"),
    ("launch-fleet: archived", "launch-fleet: archived, says a helper"),
    ("launch-fleet: asked the orchestrator. Synthetic question.", "launch-fleet: told the user: synthetic answer"),
):
    case(f"490: edited same-line details hit: {old!r} -> {new!r}", 1,
         hits("comment 1201 on #12 was edited"),
         before=edit_comment(12, 1201, old), after=edit_comment(12, 1201, new), check=["--loop-comment", "1201"])
for edited in (False, True):
    case(f"290: merge queued on a pull request, edited={edited}", 0,
         CLEAN_R.replace("comments 7", "comments 8"), snap=REVIEWER,
         before=add_comment(31, 3103, f"launch-fleet: merge queued {sha('12a')}: approved") if edited else NOTHING,
         after=edit_comment(31, 3103, f"launch-fleet: merge queued {sha('12b')}: approved") if edited else
               add_comment(31, 3103, f"launch-fleet: merge queued {sha('12a')}: approved"),
         check=["--loop-comment", "3103"])
case("290: an unnamed merge queued record still hits", 1, hits("comment 3103 on #31 is new"), snap=REVIEWER,
     after=add_comment(31, 3103, f"launch-fleet: merge queued {sha('12a')}: approved"))

# #1129: commit-only metadata is valid, but grants no ticket/PR exemption.
for number, cid, snap in ((12, 1204, BUILDER), (31, 3103, REVIEWER)):
    for body in (
        "launch-fleet: nightly telling 123 attempt 1, thread thr_synnightly",
        "launch-fleet: nightly told 123 attempt 1",
        "launch-fleet: nightly uncertain 123 attempt 1",
    ):
        case(f"1129: commit-only record on #{number} hits: {body}", 1,
             hits(f"comment {cid} on #{number} is new"), snap=snap,
             after=add_comment(number, cid, body), check=["--loop-comment", str(cid)])
    for old, new in (
        ("launch-fleet: archived", "launch-fleet: nightly told 123 attempt 1"),
        ("launch-fleet: nightly told 123 attempt 1", "launch-fleet: archived"),
    ):
        case(f"1129: edited commit-only record on #{number} hits: {old!r} -> {new!r}", 1,
             hits(f"comment {cid} on #{number} was edited"), snap=snap,
             before=add_comment(number, cid, old), after=edit_comment(number, cid, new),
             check=["--loop-comment", str(cid)])

for scope in ("An unknown scope", "A run’s commit", "A run's commits"):
    case("1129: unknown Records scope fails closed: " + scope, 2, err="unknown Records scope",
         records=lambda text, scope=scope: text.replace("| A run's commit |", f"| {scope} |"),
         after=add_comment(12, 1204, "launch-fleet: archived"), check=["--loop-comment", "1204"])
for name, records, reason in (
    ("scope with an extra cell", lambda text: text.replace("| A run's commit |", "| A run's | commit |"),
     "malformed Records row"),
    ("unquoted commit-only form", lambda text: text.replace("`nightly told <run> attempt <attempt>`",
                                                          "nightly told <run> attempt <attempt>"),
     "malformed record form"),
):
    case("1129: malformed Records fail closed: " + name, 2, err=reason,
         records=records, after=add_comment(12, 1204, "launch-fleet: archived"),
         check=["--loop-comment", "1204"])

# Change the source table beside a copied checker: no second list can pass.
case("290: a new ticket form in Records is accepted", 0, CLEAN_B.replace("comments 3", "comments 4"),
     records=lambda text: text.replace("| A ticket |", "| A ticket | `launch-fleet: synthetic notice <why>` | Test |\n| |", 1),
     after=add_comment(12, 1204, "launch-fleet: synthetic notice fixture"), check=["--loop-comment", "1204"])
case("290: a removed Records form is refused", 1, hits("comment 1204 on #12 is new"),
     records=lambda text: text.replace("`launch-fleet: asked the orchestrator`", "`launch-fleet: synthetic question`"),
     after=add_comment(12, 1204, "launch-fleet: asked the orchestrator"), check=["--loop-comment", "1204"])
case("290: record-looking prose outside Records grants no exemption", 1, hits("comment 1204 on #12 is new"),
     records=lambda text: text + "\n`launch-fleet: synthetic prose`\n",
     after=add_comment(12, 1204, "launch-fleet: synthetic prose"), check=["--loop-comment", "1204"])
for body in ("launch-fleet: needs approval: synthetic", "launch-fleet: spec summary",
             "launch-fleet: archivedness", "launch-fleet: asked the orchestratorish",
             "launch-fleet: merge queuedness", "launch-fleet: merge queued_suffix",
             "launch-fleet: archivedé", "prefix launch-fleet: archived"):
    case("290: unknown or spec-only form: " + body, 1, hits("comment 1204 on #12 is new"),
         after=add_comment(12, 1204, body), check=["--loop-comment", "1204"])
for name, records in (
    ("missing file", None),
    ("missing section", lambda text: text.replace("## Records", "## Not records")),
    ("empty section", lambda text: text.split("## Records")[0] + "## Records\n\n## The check\n"),
    ("duplicate section", lambda text: text + "\n## Records\n"),
    ("malformed row", lambda text: text.replace("`launch-fleet: archived`", "archived")),
):
    case("290: unreadable Records: " + name, 2, err="can't read launch-fleet Records",
         records=records, no_paths=True, after=add_comment(12, 1204, "launch-fleet: archived"),
         check=["--loop-comment", "1204"])

case("clean: other tickets' branches and main move", 0, CLEAN_B,
     after=chain(add_ref("room/120-gadget-cd34", sha("c1")), add_ref("room/123-new-1a1a", sha("c2")),
                 add_ref("room/1-new-2b2b", sha("c3")), del_ref("room/12a-other-0f0f"),
                 add_ref("room/12a-more-3c3c", sha("c4")), add_ref("main", sha("0f"))))
case("clean: a comment on another issue is not read", 0, CLEAN_B, after=add_comment(40, 4002, "Elsewhere."))
case("clean: everything at once that is the lead's or the loop's", 0,
     CLEAN_R.replace("comments 7", "comments 9"), snap=REVIEWER,
     after=chain(add_ref(LEAD, sha("12b")), add_comment(12, 1204, "launch-fleet: noted #40"),
                 add_comment(31, 3103, "Mine."), add_ref("room/120-gadget-cd34", sha("c1"))),
     check=["--own-comment", "3103", "--own", LEAD, sha("12b"), "--loop-comment", "1204"])
case("clean: pages of one item each", 0, CLEAN_R, snap=REVIEWER,
     env=("both", {"FAKE_GH_PAGE": "1"}))
case("clean: a pull request whose branch is outside room/12-", 0,
     "clean #12: nothing changed but the writes you named (branches 2, comments 3, pull request #32)\n",
     snap=["12", "32"], after=add_ref(OUTSIDE + "-2", sha("f3")),
     logs=(["repo view", "issue 12", "pull 32", "refs room/12-", f"refs {OUTSIDE}", "comments 12", "comments 32",
            "reviews 32", "review comments 32"],
           ["pull 32", "refs room/12-", f"refs {OUTSIDE}", "comments 12", "comments 32", "reviews 32",
            "review comments 32"]))
case("clean: --own on the pull request's own branch, outside room/12-", 0,
     "clean #12: nothing changed but the writes you named (branches 2, comments 3, pull request #32)\n",
     snap=["12", "32"], after=add_ref(OUTSIDE, sha("f9")), check=["--own", OUTSIDE, sha("f9")])

# ---- W2a: a helper's write is caught ----
HELPER = "room/12-helper-scout-1-x9y8"
case("hit: a helper's new branch", 1, hits(f"branch {HELPER} is new, at {sha('5c')}"),
     after=add_ref(HELPER, sha("5c")))
case("hit: a helper's commit on the lead's branch", 1,
     hits(f"branch {LEAD} moved from {sha('12a')} to {sha('5d')}"), after=add_ref(LEAD, sha("5d")))
case("hit: the lead's branch moved to a commit that is not the lead's", 1,
     hits(f"branch {LEAD} moved from {sha('12a')} to {sha('5d')}"),
     after=add_ref(LEAD, sha("5d")), check=["--own", LEAD, sha("12b")])
case("hit: the lead's branch moved back to an older commit", 1,
     hits(f"branch {LEAD} moved from {sha('12a')} to {sha('11')}"), after=add_ref(LEAD, sha("11")))
case("hit: the lead's branch deleted", 1, hits(f"branch {LEAD} was deleted; it was at {sha('12a')}"),
     after=del_ref(LEAD), check=["--own", LEAD, sha("12a")])
case("hit: an older branch for the ticket moved", 1,
     hits(f"branch room/12-old-try-9z9z moved from {sha('0a')} to {sha('0b')}"),
     before=add_ref("room/12-old-try-9z9z", sha("0a")), after=add_ref("room/12-old-try-9z9z", sha("0b")))
case("hit: a helper's branch beside the lead's own push", 1, hits(f"branch {HELPER} is new, at {sha('5c')}"),
     after=chain(add_ref(LEAD, sha("12b")), add_ref(HELPER, sha("5c"))), check=["--own", LEAD, sha("12b")])
case("hit: --own names the helper's branch, not the commit on it", 1,
     hits(f"branch {HELPER} is new, at {sha('5c')}"), after=add_ref(HELPER, sha("5c")),
     check=["--own", HELPER, sha("5e")])
case("hit: a new comment on the ticket", 1, hits("comment 1204 on #12 is new"),
     after=add_comment(12, 1204, "Helper report: PASS."))
case("hit: a new comment on the pull request", 1, hits("comment 3103 on #31 is new"), snap=REVIEWER,
     after=add_comment(31, 3103, "Helper: R1 reproduces."))
case("hit: an edited comment", 1, hits("comment 1203 on #12 was edited"),
     after=edit_comment(12, 1203, "Changed by a helper."))
case("hit: a comment edited without changing its words", 1, hits("comment 1203 on #12 was edited"),
     after=edit_comment(12, 1203))
case("hit: a deleted comment", 1, hits("comment 1203 on #12 was deleted"), after=del_comment(12, 1203))
case("hit: a deleted loop record", 1, hits("comment 1201 on #12 was deleted"), after=del_comment(12, 1201))
case("hit: a comment made to look like the loop's", 1,
     hits("comment 1203 on #12 was edited"), after=edit_comment(12, 1203, "launch-fleet: archived"))
case("hit: comments that only nearly look like the loop's, even named", 1,
     hits("comment 1204 on #12 is new", "comment 1205 on #12 is new", "comment 1206 on #12 is new",
          "comment 1207 on #12 is new", "comment 1208 on #12 is new", "comment 1209 on #12 is new"),
     after=chain(add_comment(12, 1204, "Launch-fleet: archived"), add_comment(12, 1205, " launch-fleet: archived"),
                 add_comment(12, 1206, "launch-fleet archived"), add_comment(12, 1207, "`launch-fleet: archived`"),
                 add_comment(12, 1208, "launch-fleet: archived, says a helper"),
                 add_comment(12, 1209, "launch-fleet:archived")),
     check=[x for i in range(1204, 1210) for x in ("--loop-comment", str(i))])
case("hit: a helper's comment that starts launch-fleet:", 1, hits("comment 1204 on #12 is new"),
     after=add_comment(12, 1204, "launch-fleet: helper report: PASS"))
case("hit: a loop record not named with --loop-comment", 1, hits("comment 1204 on #12 is new"),
     after=add_comment(12, 1204, "launch-fleet: archived"))
case("hit: an edited loop record not named", 1, hits("comment 1201 on #12 was edited"),
     after=edit_comment(12, 1201, "launch-fleet: start failed: synthetic"))
case("hit: --loop-comment on a form the loop never writes", 1, hits("comment 1204 on #12 is new"),
     after=add_comment(12, 1204, "launch-fleet: helper report: PASS"), check=["--loop-comment", "1204"])
case("hit: --loop-comment on a comment that is not a record", 1, hits("comment 1204 on #12 is new"),
     after=add_comment(12, 1204, "Helper report: PASS."), check=["--loop-comment", "1204"])
case("hit: --loop-comment on a comment edited into a record", 1, hits("comment 1203 on #12 was edited"),
     after=edit_comment(12, 1203, "launch-fleet: archived"), check=["--loop-comment", "1203"])
case("hit: --loop-comment on a record edited into another form", 1, hits("comment 1201 on #12 was edited"),
     after=edit_comment(12, 1201, "launch-fleet: helper says PASS"), check=["--loop-comment", "1201"])
case("hit: --loop-comment on a deleted loop record", 1, hits("comment 1201 on #12 was deleted"),
     after=del_comment(12, 1201), check=["--loop-comment", "1201"])
case("hit: --loop-comment covers only the comment it names", 1, hits("comment 1205 on #12 is new"),
     after=chain(add_comment(12, 1204, "launch-fleet: archived"), add_comment(12, 1205, "launch-fleet: archived")),
     check=["--loop-comment", "1204"])
case("hit: --loop-comment never covers a review comment with the same id", 1,
     hits("review comment 3161 on #31 is new"), snap=REVIEWER,
     after=add_inline(31, 3161, "launch-fleet: archived"), check=["--loop-comment", "3161"])
case("hit: --own-comment covers only the comment it names", 1, hits("comment 1205 on #12 is new"),
     after=chain(add_comment(12, 1204, "Mine."), add_comment(12, 1205, "A helper's.")),
     check=["--own-comment", "1204"])
case("hit: --own-comment never covers a review with the same id", 1, hits("review 3151 on #31 is new"),
     snap=REVIEWER, after=add_review(31, 3151), check=["--own-comment", "3151"])
case("hit: a new review", 1, hits("review 3151 on #31 is new"), snap=REVIEWER, after=add_review(31, 3151))
case("hit: a review dismissed", 1, hits("review 3150 on #31 was edited"), snap=REVIEWER,
     after=set_review(31, 3150, "DISMISSED"))
case("hit: a new review comment", 1, hits("review comment 3161 on #31 is new"), snap=REVIEWER,
     after=add_inline(31, 3161, "Helper: see here."))
case("hit: an edited review comment", 1, hits("review comment 3160 on #31 was edited"), snap=REVIEWER,
     after=edit_inline(31, 3160, "Changed."))
case("hit: the pull request merged", 1, hits("pull request #31 was merged"), snap=REVIEWER,
     after=set_pull(31, "closed", True))
case("hit: the pull request closed", 1, hits("pull request #31 was closed"), snap=REVIEWER,
     after=set_pull(31, "closed", False))
case("hit: the pull request reopened", 1, hits("pull request #31 was reopened"), snap=REVIEWER,
     before=set_pull(31, "closed", False), after=set_pull(31, "open", False))
case("hit: a commit on the pull request's branch outside room/12-", 1,
     hits(f"branch {OUTSIDE} moved from {sha('f1')} to {sha('5f')}"), snap=["12", "32"],
     after=add_ref(OUTSIDE, sha("5f")))
case("hit: every kind at once, in order", 1,
     hits(f"branch {HELPER} is new, at {sha('5c')}", f"branch {LEAD} moved from {sha('12a')} to {sha('5d')}",
          "pull request #31 was merged", "comment 1203 on #12 was deleted",
          "comment 1204 on #12 is new", "comment 3103 on #31 is new",
          "review 3151 on #31 is new", "review comment 3161 on #31 is new"),
     snap=REVIEWER,
     after=chain(add_ref(HELPER, sha("5c")), add_ref(LEAD, sha("5d")), set_pull(31, "closed", True),
                 del_comment(12, 1203), add_comment(31, 3103, "x"), add_review(31, 3151), add_inline(31, 3161, "y"),
                 add_comment(12, 1204, "launch-fleet: archived")))
case("hit: on pages of one item each", 1, hits("comment 1204 on #12 is new"),
     after=add_comment(12, 1204, "x"), env=("both", {"FAKE_GH_PAGE": "1"}))

# ---- W2c: arguments ----
case("args: none", 2, step="snapshot", err="usage: check-helpers.sh", raw=[])
case("args: an unknown command", 2, step="snapshot", err="usage: check-helpers.sh", raw=["snap", "12"])
case("args: snapshot without a ticket", 2, step="snapshot", err="usage: check-helpers.sh", snap=[])
case("args: a ticket that is not a number", 2, step="snapshot", err="the ticket must be a number, not 'x'", snap=["x"])
case("args: a ticket with a leading zero", 2, step="snapshot", err="the ticket must be a number, not '012'", snap=["012"])
case("args: a ticket of 16 digits", 2, step="snapshot", err="the ticket must be a number", snap=["1234567890123456"])
case("args: a pull request that is not a number", 2, step="snapshot", err="the pull request must be a number, not '3a'", snap=["12", "3a"])
case("args: three numbers", 2, step="snapshot", err="usage: check-helpers.sh", snap=["12", "31", "32"])
case("args: the ticket as its own pull request", 2, step="snapshot", err="the ticket and the pull request are both #12", snap=["12", "12"])
case("args: check without a file", 2, err="usage: check-helpers.sh", snapfile="__no-file-argument__")
case("args: --own without a commit", 2, err="--own needs a branch and a commit", check=["--own", LEAD])
case("args: --own with a short commit", 2, err="'12a12a1' is not a full commit", check=["--own", LEAD, "12a12a1"])
case("args: --own with an upper-case commit", 2, err="is not a full commit", check=["--own", LEAD, "A" * 40])
case("args: --own with an empty branch", 2, err="--own needs a branch", check=["--own", "", sha("12b")])
case("args: --own on another ticket's branch", 2,
     err="--own: room/120-gadget-cd34 is not a branch this check reads", check=["--own", "room/120-gadget-cd34", sha("c1")])
case("args: --own on the bare prefix", 2, err="--own: room/12- is not a branch this check reads",
     check=["--own", "room/12-", sha("c1")])
case("args: --own on a pull request branch the snapshot has no pull request for", 2,
     err=f"--own: {OUTSIDE} is not a branch this check reads", check=["--own", OUTSIDE, sha("f9")])
case("args: --own twice", 2, err="--own is given twice",
     check=["--own", LEAD, sha("12b"), "--own", LEAD, sha("12c")])
case("args: --own-comment that is not an id", 2, err="--own-comment: '12x' is not a comment id",
     check=["--own-comment", "12x"])
case("args: --own-comment without an id", 2, err="--own-comment needs a comment id", check=["--own-comment"])
case("args: --loop-comment that is not an id", 2, err="--loop-comment: '0' is not a comment id",
     check=["--loop-comment", "0"])
case("args: --loop-comment without an id", 2, err="--loop-comment needs a comment id", check=["--loop-comment"])
case("args: an unknown flag", 2, err="usage: check-helpers.sh", check=["--force"])
case("args: GH_REPO not owner/name", 2, step="snapshot", err="the repository must be owner/name, not 'widgets'",
     env=("snapshot", {"GH_REPO": "widgets"}))
case("args: GH_REPO with three parts", 2, step="snapshot", err="the repository must be owner/name", env=("snapshot", {"GH_REPO": "a/b/c"}))
case("args: no repository found", 2, step="snapshot", err="set GH_REPO=owner/name, or run inside a clone", fault=("snapshot", "repo view=fail"))
case("args: the ticket is a pull request", 2, step="snapshot", err="#31 is not an issue", snap=["31"])
case("args: no such ticket", 2, step="snapshot", err="can't read #99: gh failed", snap=["99"])
case("args: the pull request is an issue", 2, step="snapshot", err="can't read pull request #40: gh failed", snap=["12", "40"])
case("args: no gh", 2, step="snapshot", err="gh is not installed", drop=["gh"])
case("args: no jq", 2, step="snapshot", err="jq is not installed", drop=["jq"])

# ---- W2c: a failed or partial read, in either step ----
for step in ("snapshot", "check"):
    s = f"{step}: "
    case = functools.partial(add_case, step=step)
    case(s + "the branches can't be read", 2, err="can't read the branches under room/12-: gh failed",
         fault=(step, "refs room/12-=fail"))
    case(s + "the branches: no answer", 2, err="can't read the branches under room/12-: the answer is not a whole list",
         fault=(step, "refs room/12-=empty"))
    case(s + "the branches: an error object", 2, err="the branches under room/12-: the answer is not a whole list",
         fault=(step, "refs room/12-=object"))
    case(s + "the branches: a branch outside the prefix", 2,
         err="a branch that is not under room/12-, or not a commit", fault=(step, "refs room/12-=outside"))
    case(s + "the branches: one that is not a commit", 2,
         err="a branch that is not under room/12-, or not a commit", fault=(step, "refs room/12-=nullbody"))
    case(s + "the branches: one without its name", 2,
         err="a branch that is not under room/12-, or not a commit", fault=(step, "refs room/12-=noid"))
    case(s + "the branches: one twice", 2, err="can't read the branches under room/12-: a branch twice",
         fault=(step, "refs room/12-=twice"))
    case(s + "the comments fail after the first page", 2, err="can't read the comments on #12: gh failed",
         fault=(step, "comments 12=cut"), env=(step, {"FAKE_GH_PAGE": "1"}))
    case(s + "the comments: no answer", 2, err="can't read the comments on #12: the answer is not a whole list",
         fault=(step, "comments 12=empty"))
    case(s + "the comments: cut short", 2, err="can't read the comments on #12: the answer is not a whole list",
         fault=(step, "comments 12=truncated"))
    case(s + "the comments: an error object", 2, err="can't read the comments on #12: the answer is not a whole list",
         fault=(step, "comments 12=object"))
    case(s + "the comments: null", 2, err="can't read the comments on #12: the answer is not a whole list",
         fault=(step, "comments 12=null"))
    case(s + "the comments: a page again", 2, err="can't read the comments on #12: a comment twice",
         fault=(step, "comments 12=repeat"))
    case(s + "the comments: one without its id", 2, err="a comment without its id, body or time",
         fault=(step, "comments 12=noid"))
    case(s + "the comments: one without its body", 2, err="a comment without its id, body or time",
         fault=(step, "comments 12=nullbody"))
    case(s + "the pull request can't be read", 2, err="can't read pull request #31: gh failed", snap=REVIEWER,
         fault=(step, "pull 31=fail"))
    case(s + "the pull request: cut short", 2, err="can't read pull request #31: the answer is not JSON", snap=REVIEWER,
         fault=(step, "pull 31=truncated"))
    case(s + "the pull request: no answer", 2, err="can't read pull request #31: the answer is not one JSON value",
         snap=REVIEWER, fault=(step, "pull 31=empty"))
    case(s + "the pull request: two answers", 2, err="can't read pull request #31: the answer is not one JSON value",
         snap=REVIEWER, fault=(step, "pull 31=two"))
    case(s + "the pull request: another number", 2, err="can't read pull request #31: not a pull request",
         snap=REVIEWER, fault=(step, "pull 31=noid"))
    case(s + "the comments on the pull request fail", 2, err="can't read the comments on #31: gh failed",
         snap=REVIEWER, fault=(step, "comments 31=fail"))
    case(s + "the reviews fail after the first page", 2, err="can't read the reviews on #31: gh failed", snap=REVIEWER,
         fault=(step, "reviews 31=cut"), env=(step, {"FAKE_GH_PAGE": "1"}), before=add_review(31, 3151))
    case(s + "the reviews: one without its body", 2, err="a review without its id, body or state", snap=REVIEWER,
         fault=(step, "reviews 31=nullbody"))
    case(s + "the review comments: no answer", 2,
         err="can't read the review comments on #31: the answer is not a whole list", snap=REVIEWER,
         fault=(step, "review comments 31=empty"))
    case(s + "the review comments: a page again", 2, err="a review comment twice", snap=REVIEWER,
         fault=(step, "review comments 31=repeat"))
    case(s + "the pull request's own branch can't be read", 2, err=f"can't read branch {OUTSIDE}: gh failed",
         snap=["12", "32"], fault=(step, f"refs {OUTSIDE}=fail"))
case = add_case
case("snapshot: the ticket can't be read", 2, step="snapshot", err="can't read #12: gh failed", fault=("snapshot", "issue 12=fail"))
case("snapshot: the ticket: an error object", 2, step="snapshot", err="can't read #12: #12 is not an issue",
     fault=("snapshot", "issue 12=object"))
case("snapshot: the ticket: no answer", 2, step="snapshot", err="can't read #12: the answer is not one JSON value",
     fault=("snapshot", "issue 12=empty"))
case("snapshot: the ticket: two answers", 2, step="snapshot", err="can't read #12: the answer is not one JSON value",
     fault=("snapshot", "issue 12=two"))

# ---- W2c: the snapshot file ----
def edit_snapshot(change):
    def run(text):
        s = json.loads(text)
        change(s)
        return json.dumps(s)
    return run


# #717 catches: --loop-comment excused any comment in a record's form, so a
# helper, or anyone who can comment on a public ticket, could post a
# launch-fleet record and have it pass as the loop's. Only the record
# authors' records are excused; their logins match in any case.
def add_comment_by(n, cid, body, user):
    def run(w):
        w["issues"][str(n)]["comments"].append(dict(comment(cid, body, "2026-11-01T11:00:00Z"), user=user))
    return run


# REST names the App `openwiz[bot]`: a bare `openwiz`, even typed Bot, is
# never the App on this REST read (orchestrator ruling on #717).
for user in ({"login": "synthetic-outsider"}, {"login": "openwiz"}, {"login": "openwiz", "type": "Bot"}, None, {}):
    case(f"717: hit: --loop-comment on a record by {user}", 1, hits("comment 1204 on #12 is new"),
         after=add_comment_by(12, 1204, "launch-fleet: archived", user), check=["--loop-comment", "1204"])
case("717: hit: --loop-comment on an outsider's record edited into another record", 1,
     hits("comment 1205 on #12 was edited"),
     before=add_comment_by(12, 1205, "launch-fleet: archived", {"login": "synthetic-outsider"}),
     after=edit_comment(12, 1205, "launch-fleet: told the user"), check=["--loop-comment", "1205"])
for login in ("openwiz[bot]", "OpenWiz[bot]", "ROBIN"):
    case(f"717: the factory's record by {login} is excused", 0, CLEAN_B.replace("comments 3", "comments 4"),
         after=add_comment_by(12, 1204, "launch-fleet: archived", {"login": login}), check=["--loop-comment", "1204"],
         logs=(["repo view", "issue 12", "refs room/12-", "comments 12"], ["refs room/12-", "comments 12", "fleet"]))
ROW = "| Record authors | `openwiz[bot]`, `robin` |"
for name, doc in (("no Record authors row", lambda f: f.replace(ROW, "")),
                  ("an empty Record authors row", lambda f: f.replace(ROW, "| Record authors | |")),
                  ("a malformed login", lambda f: f.replace(ROW, "| Record authors | `openwiz[bot]`, robin |")),
                  ("two Record authors rows", lambda f: f.replace(ROW, ROW + "\n" + ROW)),
                  ("a cell after the value", lambda f: f.replace(ROW, ROW + " extra |"))):
    case(f"717: --loop-comment with {name}", 2, err="record authors",
         before=lambda w, doc=doc: w.update(fleet=doc(FLEET)),
         after=add_comment(12, 1204, "launch-fleet: archived"), check=["--loop-comment", "1204"])
case("717: --loop-comment when the record authors can't be read", 2, err="record authors",
     fault=("check", "fleet=fail"), after=add_comment(12, 1204, "launch-fleet: archived"),
     check=["--loop-comment", "1204"])
# A snapshot saved before #717 holds no authors: it must still check, with no
# comment read as edited only because its author is now known.
case("717: a snapshot without comment authors still checks", 0, CLEAN_B,
     snapfile=edit_snapshot(lambda s: [v.pop("author", None) for v in s["comments"].values()]))

case("file: missing", 2, err="no snapshot file", snapfile=lambda text: None)
case("file: empty, as a failed snapshot leaves it", 2, err="is not a snapshot check-helpers.sh wrote",
     snapfile=lambda text: "")
case("file: cut short", 2, err="is not a snapshot check-helpers.sh wrote", snapfile=lambda text: text[: len(text) // 2])
case("file: two snapshots", 2, err="not one JSON object", snapfile=lambda text: text + text)
case("file: a list", 2, err="not a snapshot", snapfile=lambda text: "[" + text + "]")
case("file: another version", 2, err="not a snapshot", snapfile=edit_snapshot(lambda s: s.update(check_helpers=2)))
case("file: an extra key", 2, err="not a snapshot", snapfile=edit_snapshot(lambda s: s.update(extra=1)))
case("file: a key missing", 2, err="not a snapshot", snapfile=edit_snapshot(lambda s: s.pop("comments")))
case("file: the ticket as text", 2, err="not a snapshot", snapfile=edit_snapshot(lambda s: s.update(ticket="12")))
case("file: a pull request with an unknown state", 2, err="not a snapshot", snap=REVIEWER,
     snapfile=edit_snapshot(lambda s: s["pull"].update(state="merged")))
case("file: a branch that is not a commit", 2, err="a branch the snapshot should not hold",
     snapfile=edit_snapshot(lambda s: s["branches"].update({LEAD: "12a"})))
case("file: a branch outside room/12-", 2, err="a branch the snapshot should not hold",
     snapfile=edit_snapshot(lambda s: s["branches"].update({"main": sha("0e")})))
case("file: a comment on another issue", 2, err="a comment the snapshot should not hold",
     snapfile=edit_snapshot(lambda s: s["comments"].update({"comment 4001 on #40": {"at": "t", "body": "b"}})))
case("file: a review on the ticket", 2, err="a comment the snapshot should not hold",
     snapfile=edit_snapshot(lambda s: s["comments"].update(
         {"review 1 on #12": {"state": "COMMENTED", "at": "t", "body": "b"}})))
case("file: a comment without its body", 2, err="a comment the snapshot should not hold",
     snapfile=edit_snapshot(lambda s: s["comments"]["comment 1203 on #12"].pop("body")))
case("file: the repository not owner/name", 2, err="the snapshot's repository is not owner/name",
     snapfile=edit_snapshot(lambda s: s.update(repo="a/b/c")))
case("file: written by a snapshot that failed", 2, err="is not a snapshot check-helpers.sh wrote",
     fault=("snapshot", "comments 12=cut"), snapfile="__keep-failed-snapshot__")


# ---- The runner ----
failures = []  # (case index, line); list.append is safe across the worker threads
INDEX = {c["name"]: i for i, c in enumerate(CASES)}


def fail(name, why):
    failures.append((INDEX[name], f"FAIL [{name}] {why}"))


def tool_dir(root, drop):
    bin_dir = root / "bin"
    bin_dir.mkdir()
    for tool in TOOLS:
        if tool in drop:
            continue
        real = shutil.which(tool)
        if real is None:
            sys.exit(f"setup: {tool} is missing")
        (bin_dir / tool).symlink_to(real)
    if "gh" not in drop:
        gh = bin_dir / "gh"
        gh.write_text(f'#!/bin/sh\nexec "{sys.executable}" -I "{FAKE}" "$@"\n')
        gh.chmod(0o755)
    return bin_dir


def step_env(c, step, bin_dir, world, log):
    env = {"PATH": str(bin_dir), "HOME": str(log.parent), "LC_ALL": "C",
           "FAKE_GH_WORLD": str(world), "FAKE_GH_LOG": str(log)}
    if c["fault"] and c["fault"][0] == step:
        env["FAKE_GH_FAULT"] = c["fault"][1]
    if c["env"] and c["env"][0] in (step, "both"):
        env.update(c["env"][1])
    return env


def run(sh, script, args, env, cwd):
    return subprocess.run([sh, str(script), *args], env=env, cwd=cwd, capture_output=True, text=True, timeout=60)


def verdict_stderr(r):
    # #1686 adds local artifact receipts; all other stderr remains an error.
    prefixes = ("check-helpers.sh: snapshot saved: ", "check-helpers.sh: window saved: ")
    kept = []
    for line in r.stderr.splitlines(keepends=True):
        prefix = next((p for p in prefixes if line.startswith(p)), None)
        if prefix is None:
            kept.append(line)
        elif not pathlib.Path(line[len(prefix):].strip()).is_file():
            kept.append("missing saved artifact: " + line)
    return "".join(kept)


def assert_result(c, step, r):
    r.stderr = verdict_stderr(r)
    name, want = c["name"], c["want"]
    if c["no_paths"] and "/" in r.stdout + r.stderr:
        fail(name, f"{step} printed a path separator")
    if r.returncode != want:
        fail(name, f"{step} exited {r.returncode}, not {want}; stdout {r.stdout!r}; stderr {r.stderr!r}")
        return
    if want == 2:
        if r.stdout:
            fail(name, f"{step} printed {r.stdout!r} on stdout as it failed")
        if not r.stderr.startswith("check-helpers.sh: ") or c["err"] not in r.stderr:
            fail(name, f"{step}'s stderr {r.stderr!r} does not hold {c['err']!r}")
    else:
        if r.stdout != c["out"]:
            fail(name, f"{step} printed {r.stdout!r}, not {c['out']!r}")
        if r.stderr:
            fail(name, f"{step} wrote {r.stderr!r} on stderr")


def lines(path):
    return path.read_text().splitlines() if path.exists() else []


def run_case(c, sh):
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        bin_dir = tool_dir(root, c["drop"])
        before, after = copy.deepcopy(base()), copy.deepcopy(base())
        c["before"](before)
        c["before"](after)
        c["after"](after)
        (root / "before.json").write_text(json.dumps(before))
        (root / "after.json").write_text(json.dumps(after))
        snap_log, check_log = root / "snapshot.log", root / "check.log"
        work = root / "work"
        work.mkdir()
        # Keep the script/table layout while running outside the repository.
        script = root / "skills/build-ticket/scripts/check-helpers.sh"
        script.parent.mkdir(parents=True)
        script.write_text(SCRIPT.read_text())
        if c["records"] is not None:
            records = root / "skills/launch-fleet/SKILL.md"
            records.parent.mkdir(parents=True)
            records.write_text(c["records"](RECORDS.read_text()))

        if c["own_folder"]:
            work = script.parent
            script = script.name

        args = ["snapshot", *c["snap"]] if c["raw"] is None else c["raw"]
        r = run(sh, script, args, step_env(c, "snapshot", bin_dir, root / "before.json", snap_log), work)
        if c["step"] == "snapshot":
            assert_result(c, "snapshot", r)
            return
        if c["snapfile"] == "__keep-failed-snapshot__":
            if r.returncode != 2 or r.stdout:
                fail(c["name"], f"the planted snapshot failure exited {r.returncode} with stdout {r.stdout!r}")
                return
            text = r.stdout
        elif r.returncode != 0 or verdict_stderr(r):
            fail(c["name"], f"snapshot exited {r.returncode}; stderr {r.stderr!r}")
            return
        else:
            text = r.stdout
        snap_file = root / "snapshot.json"
        args = ["check", str(snap_file), *c["check"]]
        if c["snapfile"] == "__no-file-argument__":
            args = ["check"]
        elif callable(c["snapfile"]):
            text = c["snapfile"](text)
        if text is not None:
            snap_file.write_text(text)
        r = run(sh, script, args, step_env(c, "check", bin_dir, root / "after.json", check_log), work)
        assert_result(c, "check", r)
        if c["logs"]:
            for step, log, want in (("snapshot", snap_log, c["logs"][0]), ("check", check_log, c["logs"][1])):
                if lines(log) != want:
                    fail(c["name"], f"{step} made the reads {lines(log)}, not exactly {want}")


def main():
    sh = shutil.which("sh")
    if sh is None or not FAKE.is_file():
        sys.exit("setup: sh or the fake gh is missing")
    only = os.environ.get("TEST_ONLY")
    names = [c["name"] for c in CASES]
    if len(set(names)) != len(names):
        sys.exit("setup: two cases share a name")
    if os.environ.get("LIST_CASES"):
        print("\n".join(names))
        return 0
    chosen = [c for c in CASES if not only or c["name"] == only]
    if only and len(chosen) != 1:
        print(f"FAIL: TEST_ONLY={only!r} names no case")
        return 1
    def one(c):
        try:
            run_case(c, sh)
        except Exception as e:  # a case that can't even run is a failed case, never a crash
            fail(c["name"], f"the case raised {e!r}")

    jobs = int(os.environ.get("TEST_JOBS") or 4)
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        list(pool.map(one, chosen))
    for _, line in sorted(failures):
        print(line)
    failed = {i for i, _ in failures}
    if failures:
        print(f"FAIL: {len(failed)} of {len(chosen)} cases")
        return 1
    print(f"PASS: {len(chosen)} cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
