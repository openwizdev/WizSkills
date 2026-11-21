# OpenWiz write-driver contract, version 1 (`openwiz.write-driver.v1`)

What the `write-driver` skill says and writes, pinned before the skill: the copy line, the throwaway ticket and its start record, the live lessons it checks, its safety rules, its final report with the time from paste to 5 of 5, and the share offer. Ticket WD1 (#1928) of spec #1927.

**Contract only.** It changes no code and no rule of the [driver contract](../kernel/driver.v1.md), the [driver kit](../kernel/driver-kit/README.md) or the [feedback contract](feedback.v1.md). It sends nothing and grants no live, spending or posting authority. Its consumers prove their own parts at their own seams, against the fixtures in [`fixtures/write-driver/`](fixtures/write-driver/): WD2 (#1929) the skill and its scripts in WizSkills, which carries a byte-identical copy of this file; WD3 (#1931) the end-to-end eval against the template's fake host; WD4 (#1932) the Drivers page's copy line.

Authority: Jake, 2026-11-20: a `write-driver` skill takes a user from one pasted line to a passing driver of their own, end to end, as fast as possible; it never handles a login or key, asks before every live step that could cost money or start a machine, and stops everything it started; it times every run and shares the time only on the user's yes, through their own login ([private record](https://github.com/jparker2006/ClosedWiz/issues/3065#issuecomment-7040932403)).

**Examples.** Every example and fixture is synthetic: the host `examplehost`, the account `example-user`, the harness `exampleagent`, every issue and pull request number, time, id and link. Only `openwizdev/OpenWiz` and `openwizdev/WizSkills` are real, because the forms need them.

## Words

| Word | Meaning here |
| --- | --- |
| **Host** | The place the user's driver runs agents on, named as its folder will be (`adapters/<host>/`): 1 to 40 lower-case letters, digits or `-`, starting with a letter and not ending with `-`. |
| **The four words** | The driver contract's commands `version`, `start`, `wake` and `stop` ([driver v1, section 1](../kernel/driver.v1.md#1-commands)). `schema` is the fifth command, which every driver copies unchanged from the template. |
| **The five checks** | The kit's checks, in the order it prints them: `version`, `start`, `wake`, `stop`, `token` ([driver v1, section 3](../kernel/driver.v1.md#3-the-kits-five-checks)). |
| **Paste** | The moment the skill first reads the copy line in the user's message. |
| **5 of 5** | One kit run against the real host printing a `pass` line for each of the five checks. |
| **Passing** | 5 of 5, with all three live lessons passing (section 3). The skill's goal, and what its share line calls 5 of 5. |
| **Throwaway ticket** | The one open issue the kit's live run uses, in a throwaway repository of the user's own. |
| **Start record** | The comment on the throwaway ticket that admits its builder, as a fleet's `launch-fleet: started` record does. |
| **Live lesson** | A case that broke a real driver while every test passed: the skill checks each one live. |
| **Safety ask** | A question the skill asks, and waits on, before a step. |
| **Final report** | The skill's last message of a run: its result, its time, and what it stopped. |
| **Share line** | The one public line the skill may post about a run, only on the user's yes. |
| **Driver times issue** | The open, pinned issue on `openwizdev/OpenWiz` titled exactly `Driver times`, where share lines go. |

## The forms

Every exact text below comes from this one block; [`check.py`](fixtures/write-driver/check.py) reads it, and a consumer reads it or copies it byte for byte. In a form, `<name>` is a value matching `fields.<name>` (a regular expression, matched whole), and a name used twice in one form is the same value both times. Every other character is literal. A text has no trailing newline unless the form shows one.

```write-driver-v1
{
 "words": [
  "version",
  "start",
  "wake",
  "stop"
 ],
 "checks": [
  "version",
  "start",
  "wake",
  "stop",
  "token"
 ],
 "lessons": [
  "live-shape",
  "wake-after-turn",
  "expired-login"
 ],
 "results": [
  "pass",
  "fail",
  "not run"
 ],
 "fields": {
  "host": "[a-z](?:[a-z0-9-]{0,38}[a-z0-9])?",
  "account": "[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})",
  "harness": "[a-z](?:[a-z0-9-]{0,38}[a-z0-9])?",
  "time": "1 minute|(?:[2-9]|[1-9][0-9]{1,3}) minutes",
  "k": "[0-5]",
  "count": "0|[1-9][0-9]{0,3}",
  "issue": "[1-9][0-9]{0,8}",
  "pr": "https://github\\.com/[A-Za-z0-9-]+/[A-Za-z0-9_.-]+/pull/[1-9][0-9]{0,8}",
  "step": "[^\\n:]{1,200}",
  "effect": "cost money|start a machine|cost money and start a machine",
  "what": "[^\\n]{1,300}",
  "error": "[^\\n]{1,300}"
 },
 "copy_line": "Write an OpenWiz driver for my host with the write-driver skill: https://github.com/openwizdev/WizSkills/tree/main/skills/write-driver",
 "fleet_file": "# Fleet settings\n\nA throwaway repository for the OpenWiz driver kit's live run.\n\n## GitHub identity\n\n| Setting | Value |\n| --- | --- |\n| Record authors | `<account>` |",
 "ticket_title": "Driver kit live run: <host>",
 "ticket_body": "## What to build\n\nNothing. This ticket exists only for the OpenWiz driver kit's live run of the <host> driver. As its builder, post your status note, change no file, open no pull request and end your turn. When woken, edit that same note and end your turn again.\n\n## Owned paths\n\n- `kit-run.md` (nothing to change: the kit reads only the builder's status note)\n\n## Acceptance criteria\n\n- [ ] none: the kit reads only the builder's status note",
 "ticket_labels": [
  "ready-for-agent"
 ],
 "start_record": "launch-fleet: started\n\nThe driver kit's live run of the <host> driver: nothing to build.",
 "ask": "Before I <step> on <host>: this may <effect>. Say yes to go ahead, or no to skip it.",
 "sign_in": "Your <harness> sign-in on <host> has ended. Sign in there yourself, then say done; I never see or handle it.",
 "sign_in_next": "sign in to <harness> on <host> yourself, then start again",
 "report_passed": "Your <host> driver passed 5 of 5 in <time>.",
 "report_not_passing": "Your <host> driver reached <k> of 5 after <time>; not passing yet.",
 "stopped": "Stopped: everything it started (<count>)",
 "not_stopped": "Not stopped: <what>",
 "pull_request": "Pull request: <pr>",
 "share_line": "<host>: 5 of 5 in <time>",
 "share_preview": "Share your time? I would post this one line, once, as <account> on openwizdev/OpenWiz#<issue> (Driver times), where anyone can read it:\n\n<host>: 5 of 5 in <time>\n\nSay yes to post it, or no to keep it to yourself."
}
```

## 1. The copy line

`copy_line` is the one line the Drivers page shows under "Write your own driver" and copies: exactly that text, one line, nothing before or after it. The user pastes it to their own agent; the link is the skill's folder in WizSkills, so an agent without the skill installed can read it there. Paste starts the clock (section 5).

## 2. The throwaway ticket and its start record

The kit's live run needs one open ticket whose builder posts a status note ([kit README, The throwaway ticket](../kernel/driver-kit/README.md#the-throwaway-ticket)). The skill makes it in a new private repository of the user's own, named `<host>-driver-kit`, through the user's own signed-in `gh`, with exactly:

- **`docs/agents/fleet.md`:** `fleet_file`, where `<account>` is the account the user's agents post as on GitHub (the signed-in `gh`'s own account name, never a credential). The kit and the builder both read the `Record authors` row, and a builder trusts only its record authors.
- **The ticket:** title `ticket_title`, body `ticket_body` and exactly the labels `ticket_labels`, with the same `<host>` in its title and body. The body asks the builder for its status note and nothing else, so a live run changes nothing in the repository. Its one owned path, `kit-run.md`, carries the note that nothing changes: `build-ticket`'s admission (`ticket.py read`) reads a ticket with no owned path as not ready, and its builder would then claim nothing.
- **The start record:** one comment on the ticket, `start_record`, posted by `<account>` after the ticket exists and before the kit runs `start`. A builder that runs `build-ticket` reads the ticket as not ready without a record author's `launch-fleet: started` comment, claims nothing and posts no status note, so the kit's start check could never pass. The `admission/` fixtures run the pinned `build-ticket` skill's own `ticket.py read` on exactly these forms, through that skill's synthetic `gh`: `ready: yes` with the start record, and `ready: no` without it or with it from another account. The check reads only `PATH` from its own environment and runs that Git and `ticket.py` with only that `PATH`, an empty temporary home and the fake `gh`'s world, no global or system Git config, and signing and hooks off, so a caller's signer, key or hook is never reached; `admission/caller-signs-and-hooks.json` proves it with a caller whose fake signer and fake hooks would each leave a marker, and every `admission/` reading names what it read from the environment: `PATH` alone.

The skill closes the ticket when the run ends, whatever the result, and keeps the repository: the user may delete it.

## 3. The live lessons

Three cases broke real drivers while their tests and the kit passed. The skill checks each one on the real host and keeps one record per lesson, as a JSON object with exactly the fields shown, each once and of its type (flags are `true` or `false`, `exit` an integer, `answer` an object of strings, `live` and `fixture` text or JSON); each reads `pass` or `fail` with the code below. A lesson the user skipped (a `no` to its safety ask) reads `not run`. A record of another lesson, with other or repeated fields, or a field of another type is `invalid` with `lesson-fields`.

| Lesson | What the skill does | Record | Reads `pass` when, else `fail` with |
| --- | --- | --- | --- |
| `live-shape` | Before the driver reads any reply from the host's own tool, the skill runs that command live and compares the reply's shape with the reply the driver's own tests feed it. It reads the live output, never the docs, for the shape. | `lesson`, `live` (the live reply, its values replaced by synthetic ones of the same type), `fixture` (the reply the driver's tests use) | Both are JSON (an object or array) with the same shape, or both text with the same skeleton; else `shape-differs` |
| `wake-after-turn` | It lets the run's first turn end, confirms on the host that the turn is no longer running, then runs `wake`. A wake while the first turn still runs proves nothing: the agent is already awake. | `lesson`, `turn_ended` (the host said the turn had ended before the wake), `wake` (`answered` or `error`), `note_edited`, `second_note` | `turn_ended` is true (else `turn-still-running`), `wake` answered and the same note was edited (else `not-woken`), and no second builder note appeared (else `second-note`) |
| `expired-login` | It runs the driver's `start` with a stand-in harness that prints a sign-in line and exits 1 at once, through the driver's own tests, never by signing the user out. A first turn that ends on an expired login must fail `start`, not answer a run whose note never comes. | `lesson`, `exit` (the driver's exit code), `answer` (its JSON answer), `left_running` | `exit` is 1 and not 0 (`0` is `silent-start`), `answer` is exactly `error` (one line, 1 to 300 characters) and `next`, with `next` exactly `sign_in_next` for the stand-in's harness and the host (else `no-sign-in-next`), and nothing it started still runs (else `left-running`) |

- **Shape.** A JSON reply's shape is the sorted list of its leaves, each as its path and its type (`string`, `number`, `bool`, `null`, `empty object` or `empty array`), never its value. A path is its steps, each a key or an array item, kept apart, so a key holding `.` is one step and never two. An array's shape is the union of its items' shapes. An empty object or array is a leaf of its own, so `{}`, `[]`, `[{}]` and a missing member all differ. A text reply's skeleton is its lines, each run of letters, digits, `.`, `_` or `-` written as `w`. A JSON reply nested under one more key than its fixture (as `sandbox` then `state` against `state`, or against one key named `sandbox.state`) or with another type at a leaf differs.
- When a lesson fails, the skill fixes the driver or its tests and checks that lesson again before it may claim passing.

## 4. Safety

- **W1. Never a login or key.** The skill never asks for, reads, prints, stores or passes a login, token, key, password, secret or cookie, for the host, the harness or GitHub. It uses only the person's own signed-in tools, as the driver does (driver v1, N1 to N3). A safety ask whose `<step>` names one is refused before it is shown (`credential`): any of those words, `passphrase`, `credential`, `apikey`, `pat`, `oauth` or `bearer`, in any case and even joined to other words by `_`, `-` or digits (`EXAMPLEHOST_API_TOKEN`).
- **W2. Sign-in is the user's.** When the user's real first turn ends on an expired sign-in, the skill says `sign_in` with the harness and the host, waits for `done`, and never helps by handling the sign-in itself.
- **W3. Ask before every costly or machine-starting step.** Before each step that could cost money or start a machine (a host command that creates a machine, a sandbox or a paid run, each kit run against such a host, each lesson that starts one), the skill says `ask`, with `<step>` naming that one step in plain words, `<host>` the host, and `<effect>` saying which: `cost money`, `start a machine` or both. One ask covers one step. Only an explicit `yes` in the user's next message goes ahead; anything else skips the step, and every check it would have proven reads `not run`. A step that can do neither still runs without asking.
- **W4. Stop everything it started.** The skill keeps a list as it goes of each driver run, machine, sandbox and process it started. At the end of every run, passing or not, it runs `stop` on each driver run and the host's own stop on each thing left, and closes the throwaway ticket.

| Ask form | Reading |
| --- | --- |
| `ask` | `valid`, kind `cost-or-machine`, with its `effect` |
| `sign_in` | `valid`, kind `sign-in` |
| `ask` with a credential word in its `<step>` | `invalid`, `credential`. The host and harness are identifiers their fields already validate, so a host named `key-host` is never read as a credential word |
| Anything else (no effect, no question, a step that tells instead of asks) | `invalid`, `ask-form` |

## 5. The clock and the final report

- **The clock** starts at paste and stops when the driver is passing: when the last of its 5 of 5 kit run and its three lessons passes. The time is whole minutes, rounded up, at least 1: `1 minute`, otherwise `<n> minutes`. A run that ends without passing stops the clock at its final report.
- **Every run says its time** in its final report, passing or not, as the report's first line.

The final report is exactly these lines, in order:

1. `report_passed` when the driver is passing; otherwise `report_not_passing`, where `<k>` is the number of `pass` results on the kit line.
2. `Kit: ` and each of the five checks in the kit's order as `<check> <result>`, joined by `, `; `<result>` is one of `results`.
3. `Live lessons: ` and each lesson in the order of `lessons` as `<lesson> <result>`, joined the same way.
4. `stopped` when every thing it started has stopped (`<count>` of them); otherwise `not_stopped`, saying what still runs and how the user stops it.
5. When passing only: `pull_request`, the driver's pull request in the user's own repository.

A `report_passed` first line with any check or lesson not `pass` is `invalid` with `report-not-passing`; a `report_not_passing` first line on a report that is passing, or whose `<k>` differs from the kit line, is `invalid` with `report-count`; any other shape is `invalid` with `report-form`.

## 6. The share offer

After a passing report whose fourth line is `stopped`, and only then, the skill offers to share the time. It first finds the Driver times issue: the one open, pinned issue on `openwizdev/OpenWiz` whose title is exactly `Driver times`. With none, or more than one, it makes no offer and says it can't find where times go.

- **The share line** is `share_line`, with the report's `<host>` and `<time>`: those three fields and nothing else. No account, harness, model, date, link, version or second line. Any other line is refused (`share-line`), never trimmed.
- **The preview** is `share_preview`: the account that would post it (the signed-in `gh`'s own account), the issue's number, and the exact share line on its own line.
- **Consent** is the feedback contract's [explicit yes](feedback.v1.md#preview-and-consent): the user's affirmative answer to that preview, in their next message. Anything else, silence included, is a no, and the skill says nothing more about sharing.
- **One post:** on the yes, one comment on the Driver times issue whose body is exactly the share line, through the user's own signed-in `gh`, and one attempt. If it fails, the skill says so and does not retry. It never posts through another account, the OpenWiz App or any token of its own.

A preview of any other form is refused (`share-preview`).

## 7. Reuse

The skill writes the driver from `adapters/template/`, keeps the four words and the `schema` command exactly as driver v1 defines them, and proves it with the kit's five checks, unchanged. This contract adds no command, field or check to either. A change to driver v1 or the kit is theirs, never this contract's; `check.py` fails if this block's four words stop being driver v1 commands or its five checks stop being the kit's, in the kit's order.

## Fixtures

[`fixtures/write-driver/`](fixtures/write-driver/) holds one or more fixtures per form, valid and refused, and `expected.json` gives each one's reading. `python3 -I contracts/fixtures/write-driver/check.py`, which CI's kernel kits step runs, reads every fixture under this contract, checks the reuse rule, and exits 0 only when every reading matches; a fixture on disk that `expected.json` doesn't list fails it.

| Folder | Covers |
| --- | --- |
| `copy-line/` | The copy line, and two that differ |
| `ticket/` | The throwaway repository's `fleet.md`, the ticket (as JSON with exactly `title`, `body` and `labels`) and its start record, each with refused variants |
| `lessons/` | Each live lesson passing, and each of its failures |
| `asks/` | Each safety ask (cost, machine, both, sign-in), and refused asks |
| `report/` | Passing and not-passing final reports with their times, and refused reports |
| `share/` | Share lines, a preview, and refused lines and previews carrying anything but the three fields |
| `admission/` | The throwaway ticket, `fleet.md` and start record through the pinned `build-ticket` `ticket.py read` and its synthetic `gh` (installed by `tools/wizskills/install.py`, as every CI job does; without it the check fails), and a caller whose fake signer and hooks must never run |
