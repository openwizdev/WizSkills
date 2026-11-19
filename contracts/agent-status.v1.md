# OpenWiz agent status contract, version 1 (`openwiz.agent-status.v1`)

Agents say what they are doing on their tickets, in one public format that any agent host writes and the OpenWiz app reads. A ticket's state is one **state label**; who is on it, and their last step, is one **status comment** edited in place. Its schema is [agent-status.v1.schema.json](agent-status.v1.schema.json). Its writer and checker is [`skills/launch-fleet/scripts/status.py`](../skills/launch-fleet/scripts/status.py).

Authority: spec openwizdev/OpenWiz#1223 (the app, v1), ticket AP1 #1254. Writers: build-ticket, review-ticket and launch-fleet (AP2 #1255). Reader: the app's Agents page and spec pages (AP7 #1260). The app reads this contract, never an agent host.

## State labels

A ticket carries at most one of these four labels. `ready-for-agent` stays as it is beside them, and merged comes from GitHub (the ticket's closing pull request), never from a label.

| Label | Means | Colour | Description |
| --- | --- | --- | --- |
| `building` | A builder is working on the ticket | `fbca04` | An agent is building this ticket (openwiz.agent-status.v1) |
| `in-review` | Its pull request is handed back and in review | `0e8a16` | Its pull request is in review (openwiz.agent-status.v1) |
| `needs-you` | An agent waits on the user | `d93f0b` | An agent waits on the user (openwiz.agent-status.v1) |
| `held` | The ticket is held | `5319e7` | Held (openwiz.agent-status.v1) |

Setting a state removes the other three and adds the new one; setting `none` removes all four. A label missing from the repository is created once, with the colour and description above; an existing label keeps its own colour and description.

A ticket is **being worked on** (the app's pulse) while its state label is `building` or `in-review`.

## The status comment

One comment per ticket. Its first line is exactly the **marker**:

```text
<!-- openwiz.agent-status.v1 -->
```

The ticket's status comment is the **earliest** comment whose first line is the marker and whose author is one of the project's record authors: the `Record authors` row of `docs/agents/fleet.md`'s `## GitHub identity` table, compared case-insensitively. A comment with the marker from anyone else is ordinary discussion, never a status. Writers edit that one comment in place and post a new one only when there is none; they never post a second.

A marker of another version, `<!-- openwiz.agent-status.v<N> -->` with N other than 1, is shown as **unknown**: a reader never guesses at its fields.

After the marker, one heading line and then exactly seven field lines, in this order, each `- **<Name>:** <value>`:

| Name | Field | Value |
| --- | --- | --- |
| `Kind` | `kind` | `builder`, `reviewer` or `fleet` |
| `Harness` | `harness` | The agent's harness, as its fleet settings name it, for example `Claude Code` or `Codex` |
| `Model` | `model` | The agent's model and effort, for example `Opus 5.5 Medium` |
| `Last step` | `step` | One short public sentence: the agent's last step |
| `Time` | `time` | When that step happened, UTC, `YYYY-MM-DDTHH:MM:SSZ` |
| `Pull request` | `pr` | The ticket's pull request, `https://github.com/<owner>/<repo>/pull/<n>`, or `none` |
| `Preview` | `preview` | Optional: an `https://` preview link of that pull request, which the app shows as-is, or `none` |

Every value is one line of 1 to 300 characters with no control character. `harness` and `model` hold at most 60.

Example (synthetic):

```text
<!-- openwiz.agent-status.v1 -->
**Agent status**

- **Kind:** builder
- **Harness:** Claude Code
- **Model:** Opus 5.5 Medium
- **Last step:** opened the pull request; CI is running
- **Time:** 2030-01-02T03:04:05Z
- **Pull request:** https://github.com/example/site/pull/42
- **Preview:** https://42.example-site.pages.dev
```

## What it never holds

The status comment and the state labels are public. They never hold:

- **thread ids:** any `thr_` token, synthetic or not;
- **machine details:** a home folder or machine path (`/Users/…`, `/home/…`, `/root/…`, `/tmp/…`, `/var/…`, `/private/…`, `/mnt/…`, `/Volumes/…`, `/opt/…`, `/srv/…`, `/code/…`, `~/…`, `C:\…`), or a CloudRoom id (`proj_`, `prj_`, `mch_`, `usr_`, `acct_`, `auto_`, `cr_`);
- **private words:** anyone's exact words. A writer refuses any double quote mark (`"`, `“`, `”`) and any value that starts with `>`.

The writer refuses such text before any write: nothing is read or written on GitHub.

## The writer and the check

```sh
status.py write --repo <owner>/<name> --ticket <n> --state building|in-review|needs-you|held|none \
  --kind builder|reviewer|fleet --harness <text> --model <text> --step <text> \
  [--pr <pull request url>] [--preview <https url>] [--time <YYYY-MM-DDTHH:MM:SSZ>]
status.py check --repo <owner>/<name>
```

- **`write`** refuses a bad or private value (exit 2) before any call; reads the record authors from the repository's `docs/agents/fleet.md`; creates a missing state label once; swaps the ticket's state label; then edits the ticket's status comment, or posts it when there is none. It prints `#<n>: <state>, status comment <id> edited` or `… posted`. `--time` defaults to now.
- **`check`** reads every open issue, its labels and the pull requests that close it, and prints one line per mismatch, `#<n> <label>: <what GitHub shows>`. It writes nothing. Exit 0: no mismatch; 1: mismatches printed; 2: it could not read. A mismatch is:
  - more than one state label;
  - `building`, `in-review` or `needs-you` on an open ticket whose closing pull request has merged;
  - `in-review` with no open pull request closing the ticket.

  A ticket with no state label is not a mismatch: its writer sets one at its next step.
