#!/usr/bin/env python3
"""Synthetic posted-approval fixtures; no network or live session data.

Run: python3 skills/to-tickets/scripts/test_check_approval.py
CHECK_APPROVAL_SH can name another checker (including an always-pass mutant).
The two six-ticket shapes reproduce #172/#330's bad and corrected records;
people, titles, comment IDs and fingerprints below are synthetic.
"""
import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
CHECKER = Path(os.environ.get("CHECK_APPROVAL_SH", HERE / "check-approval.sh"))
LABELS = """# Triage labels

## Labels

| Role | Label here | Meaning |
| --- | --- | --- |
| `ready-for-agent` | `ready-for-agent` | Agent ticket |
| `ready-for-human` | `ready-for-human` | Human ticket |
"""
# #717: the factory's identity, the Record authors row launch-fleet reads.
FLEET = """# Fleet settings

## GitHub identity

| Setting | Value |
| --- | --- |
| App | Synthetic App |
| Record authors | `openwiz[bot]`, `synthetic-owner` |

## Standing merge rules
"""
FACTORY = {"login": "openwiz[bot]"}
OUTSIDER = {"login": "synthetic-outsider"}


def fixture(spec, label="ready-for-agent"):
    numbers = [173, 174, 176, 177, 180, 181] if spec == 172 else list(range(332, 338))
    rows = [f"| #{n} | Synthetic ticket {n} | none | {label} |" for n in numbers]
    body = (
        '**Plan graph approved by Robin, 2026-11-01, revision 2:** approved as proposed.\n'
        'Private record: https://github.com/jparker2006/ClosedWiz/issues/9001#issuecomment-9000000002\n\n'
        "| Ticket | Title | Blocked by | Label |\n| --- | --- | --- | --- |\n"
        + "\n".join(rows)
        + "\n\nFingerprint: `" + "a" * 64 + "`\n\n"
        '<details><summary>Revision text</summary>\n\n```text\n'
        'plan-graph revision v2\n```\n\n</details>\n'
    )
    return {
        "graph": {"subIssues": {"totalCount": 6, "nodes": [{"number": n} for n in numbers]}},
        "comments": [[{"id": 100, "user": dict(FACTORY), "body": body}]],
        "labels_doc": LABELS,
        "fleet_doc": FLEET,
        "tracker_doc": "# Tracker\n\n- **Private records:** `jparker2006/ClosedWiz`, permanently private.\n",
        "repo": {"isPrivate": False},
    }


def state_table(world):
    body = world["comments"][0][0]["body"]
    lines = []
    for line in body.splitlines():
        if line.startswith("| Ticket |"):
            line = "| Ticket | Title | State |"
        elif line.startswith("| ---"):
            line = "| --- | --- | --- |"
        elif line.startswith("| #"):
            cols = line.split("|")
            # #172's shape has five closed and one open ticket; #330 is all open.
            state = "closed" if "#17" in cols[1] or "#180" in cols[1] else "open"
            line = f"| {cols[1].strip()} | {cols[2].strip()} | {state} |"
        lines.append(line)
    world["comments"][0][0]["body"] = "\n".join(lines) + "\n"
    return world


FAKE_GH = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
w = json.loads(Path(os.environ["FAKE_WORLD"]).read_text())
n = os.environ["FAKE_SPEC"]
if args == ["repo", "view", "--json", "isPrivate"]:
    key = "repo"
elif args == ["api", "-H", "Accept: application/vnd.github.raw+json", "repos/{owner}/{repo}/contents/docs/agents/triage-labels.md"]:
    key = "labels_doc"
elif args == ["api", "-H", "Accept: application/vnd.github.raw+json", "repos/{owner}/{repo}/contents/docs/agents/issue-tracker.md"]:
    key = "tracker_doc"
elif args == ["api", "-H", "Accept: application/vnd.github.raw+json", "repos/{owner}/{repo}/contents/docs/agents/fleet.md"]:
    key = "fleet_doc"
elif args == ["issue", "view", n, "--json", "subIssues"]:
    key = "graph"
elif args == ["api", "--paginate", "repos/{owner}/{repo}/issues/" + n + "/comments?per_page=100"]:
    key = "comments"
else:
    sys.exit("unexpected gh call: " + repr(args))
if w.get("fail") == key:
    sys.exit("planted read failure")
if w.get("empty") == key:
    sys.exit(0)
if key in ("tracker_doc", "fleet_doc"):
    print(w[key], end="")
elif key == "labels_doc":
    print(Path(os.environ["FAKE_LABELS_FILE"]).read_text() if "FAKE_LABELS_FILE" in os.environ else w[key], end="")
elif key == "comments":
    for page in w[key]:
        print(json.dumps(page))
else:
    print(json.dumps(w[key]))
'''


class ApprovalTest(unittest.TestCase):
    def test_documented_handoff_from_plugin_consumer(self):
        with tempfile.TemporaryDirectory(prefix="approval-consumer-") as folder:
            tmp = Path(folder)
            installed = tmp / "plugin cache" / "to-tickets"
            (installed / "scripts").mkdir(parents=True)
            shutil.copy2(HERE.parent / "SKILL.md", installed / "SKILL.md")
            shutil.copy2(CHECKER, installed / "scripts" / "check-approval.sh")
            commands = re.findall(r'`(sh [^`]*scripts/check-approval\.sh"? <spec>)`',
                                  (installed / "SKILL.md").read_text())
            self.assertEqual(len(commands), 1)
            command = commands[0].replace("<this skill's folder>", str(installed)).replace("<spec>", "172")

            consumer = tmp / "consumer"
            settings = consumer / "docs" / "agents" / "triage-labels.md"
            settings.parent.mkdir(parents=True)
            settings.write_text(LABELS.replace("| `ready-for-agent` | `ready-for-agent` |",
                                               "| `ready-for-agent` | `consumer-ready` |"))
            world = fixture(172)
            world["comments"][0][0]["body"] = world["comments"][0][0]["body"].replace(
                "ready-for-agent", "consumer-ready")
            (consumer / "world.json").write_text(json.dumps(world))
            self.assertFalse((consumer / "skills").exists())
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            (fake_bin / "gh").write_text(FAKE_GH)
            (fake_bin / "gh").chmod(0o700)
            env = dict(os.environ, PATH=str(fake_bin) + os.pathsep + os.environ["PATH"],
                       FAKE_WORLD="world.json", FAKE_LOG=str(tmp / "calls"), FAKE_SPEC="172",
                       FAKE_LABELS_FILE="docs/agents/triage-labels.md")
            result = subprocess.run(["sh", "-c", command], cwd=consumer, env=env,
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout, "check-approval.sh: #172 approval table is valid\n")
            self.assertEqual(result.stderr, "")
            self.assertEqual([json.loads(line) for line in (tmp / "calls").read_text().splitlines()], [
                ["api", "-H", "Accept: application/vnd.github.raw+json", "repos/{owner}/{repo}/contents/docs/agents/triage-labels.md"],
                ["api", "-H", "Accept: application/vnd.github.raw+json", "repos/{owner}/{repo}/contents/docs/agents/issue-tracker.md"],
                ["api", "-H", "Accept: application/vnd.github.raw+json", "repos/{owner}/{repo}/contents/docs/agents/fleet.md"],
                ["issue", "view", "172", "--json", "subIssues"],
                ["api", "--paginate", "repos/{owner}/{repo}/issues/172/comments?per_page=100"],
                ["repo", "view", "--json", "isPrivate"],
            ])

    def run_check(self, world, spec=172, status=0, reason=None, argument=None):
        with tempfile.TemporaryDirectory(prefix="approval-fixture-") as folder:
            tmp = Path(folder)
            (tmp / "gh").write_text(FAKE_GH)
            (tmp / "gh").chmod(0o700)
            (tmp / "world.json").write_text(json.dumps(world))
            env = dict(os.environ, PATH=str(tmp) + os.pathsep + os.environ["PATH"],
                       FAKE_WORLD=str(tmp / "world.json"), FAKE_LOG=str(tmp / "calls"),
                       FAKE_SPEC=str(spec))
            result = subprocess.run(["sh", str(CHECKER), str(spec) if argument is None else argument],
                                    env=env, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, status, result.stdout + result.stderr)
            if status == 0:
                self.assertEqual(result.stdout, f"check-approval.sh: #{spec} approval table is valid\n")
                self.assertEqual(result.stderr, "")
            else:
                self.assertEqual(result.stdout, "")
                self.assertIn(reason, result.stderr)
            calls = [json.loads(line) for line in (tmp / "calls").read_text().splitlines()] if (tmp / "calls").exists() else []
            if status == 0:
                self.assertEqual(calls, [
                    ["api", "-H", "Accept: application/vnd.github.raw+json", "repos/{owner}/{repo}/contents/docs/agents/triage-labels.md"],
                    ["api", "-H", "Accept: application/vnd.github.raw+json", "repos/{owner}/{repo}/contents/docs/agents/issue-tracker.md"],
                ["api", "-H", "Accept: application/vnd.github.raw+json", "repos/{owner}/{repo}/contents/docs/agents/fleet.md"],
                    ["issue", "view", str(spec), "--json", "subIssues"],
                    ["api", "--paginate", f"repos/{{owner}}/{{repo}}/issues/{spec}/comments?per_page=100"],
                    ["repo", "view", "--json", "isPrivate"],
                ])
            return calls

    def test_configured_records_repository_differs_from_current_repository(self):
        w = fixture(172)
        w['tracker_doc'] = '# Tracker\n\n- **Private records:** `synthetic-records/archive`, permanently private.\n'
        w['comments'][0][0]['body'] = w['comments'][0][0]['body'].replace(
            'jparker2006/ClosedWiz', 'synthetic-records/archive')
        self.run_check(w)
        w['comments'][0][0]['body'] = w['comments'][0][0]['body'].replace(
            'synthetic-records/archive', 'unrelated-owner/archive')
        self.run_check(w, status=1, reason='public approval form')

    def test_missing_malformed_or_unreadable_records_configuration_refuses(self):
        for text in ('', '- **Private records:** `owner`\n',
                     '- **Private records:** `../archive`\n',
                     '- **Private records:** `owner/repo`\n' * 2):
            w = fixture(172)
            w['tracker_doc'] = text
            self.run_check(w, status=1, reason='private records')
        w = fixture(172)
        w['fail'] = 'tracker_doc'
        self.run_check(w, status=1, reason='private records')

    def test_public_and_private_approval_forms(self):
        public = fixture(172)["comments"][0][0]["body"]
        legacy = public.replace(
            "approved as proposed.\nPrivate record: https://github.com/jparker2006/ClosedWiz/issues/9001#issuecomment-9000000002",
            '\"approve\"')
        for private in (False, True):
            for body in (public, legacy):
                with self.subTest(private=private, legacy=body == legacy):
                    w = fixture(172)
                    w["repo"] = {"isPrivate": private}
                    w["comments"][0][0]["body"] = body
                    refused = not private and body == legacy
                    self.run_check(w, status=int(refused), reason="public approval form")

    def test_public_form_refusals(self):
        public = fixture(172)["comments"][0][0]["body"]
        pointer = "https://github.com/jparker2006/ClosedWiz/issues/9001#issuecomment-9000000002"
        for before, after in (
            ("approved as proposed.", '\"approve\"'),
            ("approved as proposed.", "“approve”"),
            ("approved as proposed.", " "),
            ("Private record: " + pointer, ""),
            ("Private record: " + pointer, "\nPrivate record: " + pointer),
            (pointer, pointer.replace("ClosedWiz", "OpenWiz")),
            (pointer, pointer.replace("9001#", "09001#")),
            (pointer, pointer.replace("9000000002", "09000000002")),
            (pointer, pointer.split("#")[0]),
            (pointer, pointer + " extra"),
            ("2026-11-01", "today"),
            ("revision 2", "revision 0"),
        ):
            with self.subTest(after=after):
                w = fixture(172)
                w["comments"][0][0]["body"] = public.replace(before, after, 1)
                self.run_check(w, status=1, reason="public approval form")
        for tail in ('\nRobin: \"approve\"\n', '\n**Robin:**\n> approve\n',
                     '\nThread thr_synapproval1\n'):
            with self.subTest(tail=tail):
                w = fixture(172)
                w["comments"][0][0]["body"] += tail
                self.run_check(w, status=1, reason="public approval form")
        w = fixture(172)
        w["comments"][0][0]["body"] = public.replace("/issues/9001#", "/pull/9001#")
        self.run_check(w)

    def test_attributed_quote_forms_throughout_comment(self):
        # R1: these are private records even after a valid public opening.
        # Check all T2 double-quote spellings, including escaped wire-like text.
        for lead in ("Robin:", "**Robin:**",
                     "**Plan graph approved by Robin, 2026-11-01, revision 1:**"):
            for quote in ('"', '“', '”', '\\"', '\\“', '\\”'):
                for private in (False, True, None):
                    with self.subTest(lead=lead, quote=quote, private=private):
                        w = fixture(172)
                        w["repo"] = {} if private is None else {"isPrivate": private}
                        w["comments"][0][0]["body"] += f"\n{lead} {quote}approve{quote}\n"
                        self.run_check(w, status=0 if private else 1,
                                       reason="public approval form")

    def test_unknown_visibility_is_public(self):
        for value in ({}, {"isPrivate": "true"}, {"isPrivate": None}, [],
                      [{"isPrivate": True}]):
            with self.subTest(value=value):
                w = fixture(172)
                w["repo"] = value
                self.run_check(w)
                w["comments"][0][0]["body"] = w["comments"][0][0]["body"].replace(
                    "approved as proposed.", '\"approve\"')
                self.run_check(w, status=1, reason="public approval form")
        for fault in ("fail", "empty"):
            w = fixture(172)
            w[fault] = "repo"
            self.run_check(w)
            w["comments"][0][0]["body"] = w["comments"][0][0]["body"].replace(
                "approved as proposed.", '\"approve\"')
            self.run_check(w, status=1, reason="public approval form")

    def test_latest_quoting_record_cannot_fall_back(self):
        w = fixture(172)
        latest = copy.deepcopy(w["comments"][0][0])
        latest["id"] = 102
        latest["body"] = latest["body"].replace("approved as proposed.", '\"approve\"')
        w["comments"].append([latest, {"id": 103, "user": dict(FACTORY), "body": "Progress only"}])
        self.run_check(w, status=1, reason="public approval form")

    def test_public_comment_templates(self):
        root = HERE.parents[2]
        found = []
        for name in ("to-spec", "to-tickets", "grill", "handoff", "setup"):
            for path in (root / "skills" / name).rglob("*.md"):
                text = path.read_text()
                self.assertNotIn('"<their words, exactly>"', text, str(path))
                if name == "to-tickets" and path.name == "changes.md":
                    c2 = text.split("**A wording-only change (C2).**", 1)[1].split(
                        "\nThe merges and their files,", 1)[0]
                    with self.subTest(path=str(path), rule="C2 source"):
                        self.assertNotRegex(c2, r'Jake[^"\n]*: *["“”]')
                    with self.subTest(path=str(path), rule="C2 standing approval"):
                        self.assertNotRegex(c2, r'["“”][^"“”]+["“”] as the user.s words')
                lines = text.splitlines()
                for i, line in enumerate(lines):
                    if re.search(r"\*\*(?:Spec confirmed|Plan graph approved|Approved on its own) by ", line):
                        with self.subTest(path=str(path), line=i + 1):
                            found.append(line)
                            self.assertTrue(line.startswith("**"), "approval templates need their own lines")
                            self.assertNotRegex(line, '["“”]')
                            self.assertTrue(lines[i + 1].startswith("Private record: "))
        self.assertEqual(len(found), 5)

    def test_historical_shapes(self):
        for spec in (172, 330):
            with self.subTest(spec=spec, shape="State"):
                self.run_check(state_table(fixture(spec)), spec, 1, "columns")
            with self.subTest(spec=spec, shape="corrected"):
                self.run_check(fixture(spec), spec)

    def test_trailing_table_whitespace(self):
        for suffix in (" ", "\t", " \t\r"):
            with self.subTest(suffix=repr(suffix)):
                w = fixture(172)
                w["comments"][0][0]["body"] = "\n".join(
                    line + suffix if line.startswith("|") else line
                    for line in w["comments"][0][0]["body"].splitlines())
                self.run_check(w)

    def test_escaped_title_pipes(self):
        for title in (r"Synthetic left \| right", r"Synthetic left \| middle \| right",
                      r"Synthetic backslashes \\\| right"):
            with self.subTest(title=title):
                w = fixture(172)
                w["comments"][0][0]["body"] = w["comments"][0][0]["body"].replace(
                    "Synthetic ticket 173", title)
                self.run_check(w)

    def test_unescaped_extra_cells_and_escaped_closing_pipe(self):
        for before, after in (
            ("Synthetic ticket 173", "Synthetic left | right"),
            ("Synthetic ticket 173", r"Synthetic backslashes \\| right"),
            ("none | ready-for-agent |", "none | ready-for-agent \\|"),
        ):
            with self.subTest(after=after):
                w = fixture(172)
                w["comments"][0][0]["body"] = w["comments"][0][0]["body"].replace(before, after)
                self.run_check(w, status=1, reason="table")

    def test_complete_unique_ticket_set(self):
        for name, edit in [
            ("missing", lambda lines: lines.pop(5)),
            ("duplicate", lambda lines: lines.insert(5, lines[5])),
            ("foreign", lambda lines: lines.__setitem__(5, lines[5].replace("#173", "#999"))),
        ]:
            with self.subTest(name=name):
                w = fixture(172)
                lines = w["comments"][0][0]["body"].splitlines()
                edit(lines)
                w["comments"][0][0]["body"] = "\n".join(lines)
                self.run_check(w, status=1, reason="tickets")

    def test_labels_and_columns(self):
        for before, after in [
            ("ready-for-agent", "open"),
            ("ready-for-agent", "ready-for-agent-extra"),
            ("ready-for-agent", "ready-for-\u0430gent"),
            ("ready-for-agent", "Held"),
            ("ready-for-agent", "held-extra"),
            ("ready-for-agent", "h\u0435ld"),
            ("ready-for-agent", "`held`"),
            ("Blocked by | Label", "Label | Blocked by"),
            ("Blocked by | Label", "Blocked by | State | Label"),
            ("none | ready-for-agent", "none | open | ready-for-agent"),
            ("| #173", "| [#173](https://example.invalid/173)"),
            ("| #173", "| #0173"),
        ]:
            with self.subTest(after=after):
                w = fixture(172)
                w["comments"][0][0]["body"] = w["comments"][0][0]["body"].replace(before, after)
                self.run_check(w, status=1, reason="table")
        w = fixture(172)
        w["comments"][0][0]["body"] = w["comments"][0][0]["body"].replace("ready-for-agent", "ready-for-human", 1)
        self.run_check(w)

    def test_held_row_is_valid(self):
        w = fixture(172)
        w["comments"][0][0]["body"] = w["comments"][0][0]["body"].replace(
            "ready-for-agent", "held", 1)
        self.run_check(w)

    def test_mixed_and_all_held_rows(self):
        w = fixture(172)
        w["comments"][0][0]["body"] = w["comments"][0][0]["body"].replace(
            "ready-for-agent", "held", 1).replace("ready-for-agent", "ready-for-human", 1)
        self.run_check(w)
        self.run_check(fixture(172, label="held"))

    def test_held_does_not_mask_invalid_fields(self):
        for before, after, reason in (
            ("Synthetic ticket 173", "", "row needs"),
            ("none | held", " | held", "row needs"),
            ("| #173", "| #0173", "row needs"),
            ("| #173", "| #174", "tickets"),
            ("| #173", "| #999", "tickets"),
            ("| #173 | Synthetic ticket 173 | none | held |\n", "", "tickets"),
            ("Blocked by | Label", "Label | Blocked by", "columns"),
            ("#issuecomment-9000000002", "", "public approval form"),
        ):
            with self.subTest(after=after, reason=reason):
                w = fixture(172, label="held")
                w["comments"][0][0]["body"] = w["comments"][0][0]["body"].replace(before, after)
                self.run_check(w, status=1, reason=reason)
        for read in ("labels_doc", "graph", "comments"):
            with self.subTest(read=read):
                w = fixture(172, label="held")
                w["fail"] = read
                self.run_check(w, status=1, reason="cannot read")
        w = fixture(172, label="held")
        w["labels_doc"] = ""
        self.run_check(w, status=1, reason="labels")

    def test_project_ready_label_mapping(self):
        for role, name in (("ready-for-agent", "ready: agent"), ("ready-for-human", "ready: human")):
            with self.subTest(role=role, shape="mapped label"):
                w = fixture(172)
                w["labels_doc"] = LABELS.replace(f"| `{role}` | `{role}` |", f"| `{role}` | `{name}` |")
                w["comments"][0][0]["body"] = w["comments"][0][0]["body"].replace("ready-for-agent", name)
                self.run_check(w)
                w["comments"][0][0]["body"] = w["comments"][0][0]["body"].replace(name, "held", 1)
                self.run_check(w)
            with self.subTest(role=role, shape="unmapped role name"):
                w["comments"][0][0]["body"] = w["comments"][0][0]["body"].replace(name, role)
                self.run_check(w, status=1, reason="ready label")

    def test_ready_label_mapping_must_be_readable_and_complete(self):
        for doc in ("", LABELS.replace("## Labels", "## Example"),
                    LABELS.replace("| `ready-for-human` | `ready-for-human` | Human ticket |", ""),
                    LABELS.replace("| `ready-for-agent` | `ready-for-agent` |", "| `ready-for-agent` | `` |"),
                    LABELS + "| `ready-for-agent` | `other` | Duplicate |\n"):
            with self.subTest(doc=doc):
                w = fixture(172)
                w["labels_doc"] = doc
                self.run_check(w, status=1, reason="labels")
        w = fixture(172)
        w["fail"] = "labels_doc"
        self.run_check(w, status=1, reason="labels")

    def test_only_operative_labels_table_is_read(self):
        w = fixture(172)
        w["labels_doc"] = ("# Examples\n| `ready-for-agent` | `wrong` | Example |\n" + LABELS
                           + "\n## References\n| `ready-for-human` | `wrong` | Example |\n")
        self.run_check(w)

    def test_latest_approval_not_latest_comment_or_revision(self):
        w = fixture(172)
        old = copy.deepcopy(w["comments"][0][0])
        state_table(w)
        # A later revision number in an older approval must not hide the bad newest record.
        old["id"] = 99
        old["body"] = old["body"].replace("revision 2", "revision 9")
        w["comments"] = [[w["comments"][0][0]], [old, {"id": 101, "user": dict(FACTORY), "body": "Progress only"}]]
        self.run_check(w, status=1, reason="columns")
        w["comments"][1].append({"id": 102, "user": dict(FACTORY), "body": fixture(172)["comments"][0][0]["body"]})
        self.run_check(w)

    def test_no_or_multiple_or_fenced_tables(self):
        for mode in ("no-approval", "no-table", "twice", "fenced", "indented"):
            with self.subTest(mode=mode):
                w = fixture(172)
                body = w["comments"][0][0]["body"]
                if mode == "no-approval":
                    w["comments"] = [[]]
                elif mode == "no-table":
                    w["comments"][0][0]["body"] = body.split("\n\n")[0]
                elif mode == "twice":
                    w["comments"][0][0]["body"] = body + "\n" + body
                elif mode == "fenced":
                    w["comments"][0][0]["body"] = body.split("\n\n")[0] + "\n\n```md\n" + body + "\n```"
                else:
                    w["comments"][0][0]["body"] = body.replace("\n|", "\n |")
                self.run_check(w, status=1, reason="approval" if mode == "no-approval" else "table")

    def test_unreadable_or_partial_reads(self):
        cases = []
        for read in ("graph", "comments"):
            for fault in ("fail", "empty"):
                w = fixture(172)
                w[fault] = read
                cases.append((f"{fault}-{read}", w))
        for graph in ({}, {"subIssues": {"totalCount": 7, "nodes": [{"number": 173}]}},
                      {"subIssues": {"totalCount": 2, "nodes": [{"number": 173}, {"number": 173}]}}):
            w = fixture(172)
            w["graph"] = graph
            cases.append(("graph-shape", w))
        for comments in ([], [{"message": "error"}], [[{"id": 1}]],
                         [[{"id": 1, "body": "Progress"}], [{"id": 1, "body": "Progress"}]]):
            w = fixture(172)
            w["comments"] = comments
            cases.append(("comments-shape", w))
        for name, w in cases:
            with self.subTest(name=name):
                self.run_check(w, status=1, reason="cannot read")

    def test_only_record_authors_approve(self):
        # #717 catches: a plan approval posted by anyone who can comment on a
        # public spec counted, so an outsider could approve a plan graph, or
        # hide the factory's refusal behind a newer valid-looking approval.
        good = fixture(172)["comments"][0][0]["body"]
        bad = state_table(fixture(172))["comments"][0][0]["body"]
        # REST names the App `openwiz[bot]`: a bare `openwiz`, even typed Bot,
        # is never the App on this REST read (orchestrator ruling on #717).
        for user in (OUTSIDER, {"login": "openwiz"}, {"login": "openwiz", "type": "Bot"},
                     {"login": "openwiz[bot]x"}, {"login": None},
                     {}, None, "openwiz[bot]", "missing"):
            with self.subTest(user=user, case="the outsider's approval is the only one"):
                w = fixture(172)
                if user == "missing":
                    del w["comments"][0][0]["user"]
                else:
                    w["comments"][0][0]["user"] = user
                self.run_check(w, status=1, reason="no posted plan graph approval")
            with self.subTest(user=user, case="a newer outsider approval hides a refused one"):
                w = fixture(172)
                w["comments"][0][0]["body"] = bad
                w["comments"].append([{"id": 101, "user": user, "body": good}])
                if user == "missing":
                    del w["comments"][1][0]["user"]
                self.run_check(w, status=1, reason="columns")
        # The factory's own records still count, its logins in any case.
        for login in ("openwiz[bot]", "OpenWiz[bot]", "synthetic-owner", "SYNTHETIC-OWNER"):
            with self.subTest(login=login):
                w = fixture(172)
                w["comments"][0][0]["user"] = {"login": login}
                w["comments"].append([{"id": 101, "user": OUTSIDER, "body": bad}])
                self.run_check(w)

    def test_record_authors_setting_must_be_whole(self):
        # #717 catches: a reader that trusts everyone, or keeps the logins
        # that did parse, when the Record authors row is missing or malformed.
        row = "| Record authors | `openwiz[bot]`, `synthetic-owner` |"
        for doc in ("", FLEET.replace(row + "\n", ""),
                    FLEET.replace("## GitHub identity", "## Example"),
                    FLEET.replace(row, "| Record authors | |"),
                    FLEET.replace(row, "| Record authors | openwiz[bot] |"),
                    FLEET.replace(row, "| Record authors | `openwiz[bot]`, synthetic-owner |"),
                    FLEET.replace(row, "| Record authors | `openwiz[bot]`; `synthetic-owner` |"),
                    FLEET.replace(row, "| Record authors | `openwiz[bot]`, `-bad` |"),
                    FLEET.replace(row, row + " extra |"),
                    FLEET.replace(row, row + "\n" + row)):
            with self.subTest(doc=doc):
                w = fixture(172)
                w["fleet_doc"] = doc
                self.run_check(w, status=1, reason="record authors")
        w = fixture(172)
        w["fail"] = "fleet_doc"
        self.run_check(w, status=1, reason="record authors")

    def test_bad_arguments_never_read(self):
        for argument in ("0", "-1", "172x", "01", ""):
            self.assertEqual(self.run_check(fixture(172), status=2, reason="usage:", argument=argument), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
