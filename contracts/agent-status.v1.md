# OpenWiz agent status contract, version 1 (`openwiz:status v1`)

Agents say what they are doing on their tickets, in one public format that any agent host writes and the OpenWiz app reads. The truth about a ticket's work is one **status note** per agent, edited in place. People set labels; agents don't set state labels. Building, in review and merged are read from GitHub. Its schema is [agent-status.v1.schema.json](agent-status.v1.schema.json). Its writer and checker is [`skills/launch-fleet/scripts/status.py`](../skills/launch-fleet/scripts/status.py).

Authority: spec openwizdev/OpenWiz#1223 (the app, v1), revision 4, and ticket AP1 #1254; the records spec's design B. Writers: build-ticket, review-ticket and launch-fleet (AP2 #1255). Readers: the app's pages (AP6 #1259, AP7 #1260). The app reads this contract, never an agent host.

## Labels

People set only five labels. They are gates, never an agent's progress:

| Label | Means |
| --- | --- |
| `spec` | The issue is a spec |
| `ready-for-agent` | Approved: an agent can take it once its blockers have merged |
| `ready-for-human` | A person has to act |
| `needs-info` | Waiting on the user (shown as "needs you"). The writer also sets it while an agent's note is `asking` and clears it when that note leaves `asking` |
| `held` | Held |

There are no `building`, `in-review` or `needs-you` labels; a writer never sets one.

## Read from GitHub

| What | Read from |
| --- | --- |
| Building | A live `working` note from a builder on the ticket |
| In review | An open pull request that closes the ticket, with its reviews and checks |
| Merged | The ticket's closing pull request has merged |
| Waiting on the user | `needs-info`, or a live `asking` note |

## The status note

One comment per agent on the ticket it works on. Its first line is exactly the **marker**:

```text
<!-- openwiz:status v1 -->
```

Then one `key: value` line per field, in this order, each key once; optional fields are left out when empty:

| Key | Required | Value |
| --- | --- | --- |
| `agent` | yes | The agent's kind: `builder`, `reviewer` or `fleet` |
| `state` | yes | `working`, `asking`, `done` or `stopped`; `stopped` may carry its reason, `stopped (<why>)` |
| `harness` | yes | The agent's harness, as its fleet settings name it, for example `Claude Code` or `Codex` |
| `model` | yes | The agent's model and effort, for example `Opus 5.5 Medium` |
| `step` | yes | One short public sentence: the agent's last step |
| `time` | yes | When that step happened, UTC, `YYYY-MM-DDTHH:MM:SSZ` |
| `pr` | no | The ticket's pull request: `https://github.com/<owner>/<repo>/pull/<n>` |
| `preview` | no | An `https://` preview link of that pull request, which the app shows as-is |

Every value is one line of 1 to 300 characters with no control character; `harness` and `model` hold at most 60, and a `stopped` reason at most 100 with no parentheses.

Example (synthetic):

```text
<!-- openwiz:status v1 -->
agent: builder
state: working
harness: Claude Code
model: Opus 5.5 Medium
step: opened the pull request; CI is running
time: 2030-01-02T03:04:05Z
pr: https://github.com/example/site/pull/42
preview: https://42.example-site.pages.dev
```

A note counts only when its author is one of the project's record authors: the `Record authors` row of `docs/agents/fleet.md`'s `## GitHub identity` table, compared case-insensitively. A comment with the marker from anyone else is ordinary discussion. A marker of another version, `<!-- openwiz:status v<N> -->` with N other than 1, or a note that doesn't read as above, is shown as **unknown**: a reader never guesses at its fields.

## Claims

- **Live:** a note is live while its state is `working` or `asking` and GitHub's `updated_at` for it is less than 30 minutes old.
- **Lapsed:** a `working` or `asking` note not edited for 30 minutes has lapsed. Its claim is gone; the note itself stays until its agent edits it again or the fleet stops it.
- **The oldest live note wins:** among the live notes of one kind (`agent`) on one ticket, the one with the lowest comment id holds the claim. Notes of other kinds don't compete: a fleet note never blocks a builder.
- **Re-read before each write:** a writer reads the ticket's comments again just before it writes. It stops (the fence) when its own note is gone, is no longer its kind, is `stopped`, or an older live note of its kind exists. An agent that stops posts a new note if it starts again.

## What it never holds

The status note is public. It never holds:

- **thread ids:** any `thr_` token, synthetic or not;
- **machine details:** a home folder or machine path (`/Users/…`, `/home/…`, `/root/…`, `/tmp/…`, `/var/…`, `/private/…`, `/mnt/…`, `/Volumes/…`, `/opt/…`, `/srv/…`, `/code/…`, `~/…`, `C:\…`), or a CloudRoom id (`proj_`, `prj_`, `mch_`, `usr_`, `acct_`, `auto_`, `cr_`);
- **private words:** anyone's exact words. A writer refuses any double quote mark (`"`, `“`, `”`) and any value that starts with `>`.

The writer refuses such text before any call to GitHub.

## The writer and the check

```sh
status.py write --repo <owner>/<name> --ticket <n> --agent builder|reviewer|fleet \
  --state working|asking|done|stopped [--why <text>] --harness <text> --model <text> --step <text> \
  [--pr <pull request url>] [--preview <https url>] [--time <YYYY-MM-DDTHH:MM:SSZ>] [--note <comment id>]
status.py check --repo <owner>/<name>
```

- **`write`** refuses a bad or private value (exit 2) before any call; reads the record authors from the repository's `docs/agents/fleet.md`; re-reads the ticket and its comments; then:
  - with `--note`, edits that note, unless the fence stops it (exit 3, nothing written);
  - without `--note`, posts the agent's note, unless the new note would be `working` or `asking` while an older live note of its kind holds the claim (exit 3, nothing written). After posting it reads the comments back; if an older live note of its kind appeared meanwhile, it edits its own to `stopped (lost claim)` and exits 3;
  - adds `needs-info` when the state is `asking`, and removes it when the note was `asking` and no longer is. It touches no other label.

  It prints `#<n>: <agent> <state>, status note <id> posted` or `… edited`. The agent keeps the id and passes it as `--note` on every later write. `--time` defaults to now.
- **`check`** reads every open issue, its labels, its comments and the pull requests that close it, and prints one line per mismatch, `#<n> note <id> <agent> <state>: <what GitHub shows>`. It writes nothing. Exit 0: no mismatch; 1: mismatches printed; 2: it could not read. A mismatch is:
  - a `working` or `asking` note on a ticket whose closing pull request has merged;
  - a lapsed claim: a `working` or `asking` note not edited for 30 minutes;
  - a live `asking` note on a ticket without `needs-info`;
  - a live note of a kind whose claim an older live note holds.
