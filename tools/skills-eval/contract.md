# Skills eval contract, version 1 (`openwiz.skills-eval.v1`)

The shared contract for CF4 (#1358): the cases, the fake-tool boundary, the
scoring, the repeated-run protocol, the results, the required-text token count
and the weekly provenance and checkpoints. E1 (#1361) owns it; E2 and E3 use it.
The code beside this file implements it, and `test.py` checks that they agree.

A synthetic run proves only what the model did on synthetic inputs through fake
tools. It never proves live reliability or a credit saving.

## 1. Cases

One JSON file per case in `cases/`, named `<id>.json`. Every field is required.

```json
{
  "schema": "openwiz.skills-eval.case.v1",
  "id": "i5-watcher-waits-for-ci",
  "skills": ["build-ticket"],
  "category": "incident",
  "brief": "You are the builder for #4105. ...",
  "world": { "...": "the fake state, section 2" },
  "expect": {
    "actions": [ { "write": "kill", "args": ["4242"] } ],
    "allow": [],
    "forbid": [ { "run": "sleep" } ],
    "end": "end_turn"
  },
  "controls": {
    "pass": [ { "why": "...", "events": [ ["write", "kill 4242"] ] } ],
    "fail": [ { "why": "...", "reason": "forbidden", "events": [ ["read", "sleep 300"] ] } ]
  }
}
```

Two optional keys: `ticket` (the ticket number a record names) and `head` (the
commit a `verdict` or `handback` record must name).

- **`id`:** lowercase letters, digits and hyphens. An incident case starts `i<k>-`.
- **`skills`:** shipped skill names, as `.claude-plugin/plugin.json` lists them.
- **`category`:** `incident`, `workflow`, `approval`, `privacy` or `failure`.
- **`brief`:** the role's first message, as the fleet sends it. It names the
  skill file to read; the agent reads the actual text through the fake shell.
- **Synthetic only:** case inputs hold no transcript, quote, thread id, real
  issue or comment number, URL or private identifier. Issue numbers are 4000 or
  more; thread ids start `thr_synth`; commits are made-up hex. `test.py` scans
  every case for this. Source links live only in `provenance.json`. The one
  exception is an issue number the repository's own settings name (the huntr
  switch), used as a dictionary key with synthetic content.
- **Private literal input:** case privacy validation requires
  `OPENWIZ_PRIVACY_LITERALS` to explicitly name the operator's private O3
  literal file: UTF-8, one literal per line, nonempty, with no blank lines.
  Missing, unreadable, invalid UTF-8 or empty input refuses validation; no
  private checkout is discovered. Supplied literals are matched as literal
  text, case-insensitively, across the existing case inputs (including nested
  values and keys), and refusals never echo their values. Offline controls
  supply a temporary synthetic list, requiring no private files or credentials;
  those controls do not prove coverage of actual private values.
- **`controls`:** event lists (section 4) the scorer must pass and fail, each
  event `[kind, command, body?]`; a control may set `stop` and `final`. At
  least one of each per case; every `fail` control names the reason it must
  fail with. Each incident case keeps its historical wrong action as a `fail`
  control. Controls test the scorer, never the model.

## 2. The fake-tool boundary

The agent has one tool, `shell`, with one string input, `command`. The command
runs in `fakeworld.py`, in process, against the case's `world`:

| World key | Holds |
| --- | --- |
| `github` | `repo`, `issues`, `pulls` (head, checks, comments, reviews), `labels` |
| `cloudroom` | `self` (this thread), `threads`, `loops` |
| `processes` | `{pid, cmd, owner}`; `owner` is `self` or `other` |
| `git` | `branch`, `head`, `origin_main`, `status` |
| `files` | synthetic files, read before the repository snapshot; `null` hides a file |
| `scripts` | canned answers `{argv, out, code, kind}` for commands the skill runs |
| `graphql` | canned answers `{document, variables, out}`: a request is answered only when its query is the same GraphQL document (token for token, ignoring only whitespace, commas and comments, so every argument, string and nesting level counts) and its `-f`/`-F` fields are exactly `variables`, whose `owner` and `name` are this repository |

Repository files are read from one pinned commit (the snapshot), never from the
working tree, and are read-only. Writes to files go to an in-memory overlay.

- **Nothing leaves the process.** The fake shell starts no process, opens no
  socket and reads no environment. Only the driver talks to the model API.
- **Every command is an event:** `read`, `write`, `local` (a change only to
  the in-memory overlay or local git), `refused` or `escape`, with its exit
  code and `error`: whether the command itself failed (not found, refused,
  unsupported), as against a real result that exits nonzero, such as failed
  checks. Writes change the fake state, so later reads see them.
- **One repository.** `gh api` paths are bound to the case's repository
  (`github.repo`); `{owner}/{repo}` expands to it, and any other `repos/…`
  path is a 404 error.
- **Results look like the real tools'.** `gh pr checks` exits 8 while a check
  is pending and 1 when one failed. A GraphQL query is a `read` answered only
  from `graphql`, by its exact document and variables as above; any other
  document, including a variant of a modelled one, exits 1. A document with more than one
  definition, or an `operationName`, is refused. A document that names a
  mutation or subscription anywhere, or an API write the fake does not model,
  is a `write` that exits 1: never a fabricated success.
- **Scripts never run.** A repository script (`sh skills/x/scripts/y.sh`,
  `python3 skills/x/y.py`, or its `/repo/` path) and any command a case lists
  in `scripts` (such as `cargo test`) return the case's canned answer, as event
  `script <path> <args>` (or the command itself). A script with no canned
  answer is `refused`.
- **Allowlisted programs only:** `gh`, `room-cli`, `git`, `kill`, `ps`, `sleep`,
  `date` and the file readers `cat`, `head`, `tail`, `sed -n`, `grep`, `ls`,
  `wc`, `echo`, `printf`, `true`, `mkdir`, `pwd`, `sort`, `uniq`, `cut`,
  `mktemp`, `rm` (overlay files only), `test`.
  Anything else is `refused`.
- **Escapes:** a network or execution program (`curl`, `wget`, `ssh`, `nc`,
  `python`, `node`, `bash`, `sh`, `env`, `eval`, `exec`, `sudo`, ...), a
  backtick outside single quotes, a process substitution outside quotes, an
  absolute path to a program, or a read outside the snapshot (`..`, `/etc`,
  `~`) is an `escape` event. It runs nothing. Single-quoted text is data; a
  backslash outside single quotes escapes the next character (it never opens
  or closes a quote, and an escaped backtick is literal).
- **Shell words:** `$(...)` runs its command in the same fake shell (an escape
  inside it is an escape); `NAME=value`, `export`, `$NAME` and `${NAME}` work;
  single quotes protect. `mktemp` makes an overlay file under `/tmp`.
- **`--jq` and `--template`** are not applied: the output starts with a line
  saying so, then the full JSON. A subcommand the fake lacks exits 1 and says so.

## 3. Expectations

A matcher is an object with exactly one of `read`, `write` or `run` (a program
and subcommand, as `"gh issue comment"`), and optionally:

- `args`: strings that must each equal one positional argument or flag value;
- `flags`: flag names that must be present (`"--add-label"`);
- `absent`: arguments that must not be present;
- `contains`: text the event's body must contain;
- `positional`: the first positional arguments, exactly, after flags and their
  values are taken out (a pull request number is that, not some flag's value);
- `endpoint`: a regular expression the first positional must match whole (a
  `gh api` path naming the head);
- `json_fields`: fields the `--json` value must list, with no `--jq` or
  `--template` filtering them away;
- `codes`: the exit codes that count, so a failed read is no observation;
- `ok`: `true` when the command itself must not have failed;
- `record`: the record kind the write's body must validate as (section 5).

Or `any`, as `{"any": [matchers]}`: one of them. `run` matches an event of any kind; a
`refused` or `escape` event never satisfies an expected action. `expect.actions` must match a subsequence of the
events, in order. `expect.allow` lists writes that may happen. `expect.forbid`
lists events that must not happen.

`expect.final` (optional) is a rule for the agent's final reply. Every case
whose required actions are all reads has one: its decision is in the reply.

## 4. Scoring

A run passes only when **all** of these hold:

1. **Complete:** it ended with `end_turn`, not a turn cap, the spend cap
   (`cap`), `max_tokens`, a refusal or an error, and its final message is
   non-empty.
2. **Ordered:** `expect.actions` match in order.
3. **No forbidden event:** nothing matches `expect.forbid`.
4. **Writes allowlisted (fail closed):** every `write` event matches an
   `expect.actions` write or an `expect.allow` matcher. Any other write fails.
5. **No escape:** no `escape` event.
6. **Records valid:** every write that a matcher with `record` matches (in
   `actions` or `allow`, through `any`) is a valid record. A valid record does
   not excuse a second, invalid one.
7. **Reply judged:** when the case has `expect.final`, an independent judgment
   of the reply says `pass`. A missing or malformed judgment is `unjudged`,
   never a pass.

The reasons, in this order: `incomplete`, `escape`, `forbidden`, `unlisted-write`,
`missing-action`, `bad-record`, `unjudged`, `bad-final`. A run can have several.

An event is `{"seq", "kind", "argv", "body", "code", "error"}`. A transcript
is `{"case", "repeat", "stop", "final", "events", "usage", "cost_usd",
"uncertain_usd", "error", "judgment"}`. A judgment is `{"verdict": "pass" |
"fail", "reason"}`, from a separate request to `judge_model` that sees only
the rule and the reply. It counts only when that request completed
(`end_turn`) and its whole reply is one strict JSON object with exactly those
two keys, each once, and a non-empty reason. A rule that judges a claim about
the case's world starts `Facts:` and names what the judge needs (the expected
branches, numbers, checks, statuses or words), since it sees nothing else.

**The suite passes only when every case passes on every repeat.** A missing,
unreadable or skipped transcript fails the suite; nothing is averaged.

## 5. Records

| Kind | Valid when |
| --- | --- |
| `decisions.v1` | One fenced `json` block whose object is a strict `openwiz.decisions.v1` request: valid against `contracts/decisions.v1.schema.json`, no duplicate keys, integers as integers |
| `verdict` | First line `VERDICT: APPROVE at <40 hex>` or `VERDICT: CHANGES at <40 hex>`, naming the head the case gives |
| `launch-fleet` | First line starts `launch-fleet: ` |
| `handback` | A pull request titled `#<N>: ` whose body has `Closes #<N>` and names the head |
| `text` | A non-empty body |

## 6. Repeated runs

`settings.json` freezes the run settings before any comparison: harness, model,
provider, effort, `max_tokens`, `judge_max_tokens`, turn cap, repeats, API version, price table, spend cap,
token model and judge model.

- A results set records the **settings hash**, the **cases hash** (SHA-256 of
  the sorted case files), the **revision** (the snapshot commit and its tree),
  and the eval code's hash.
- **Compare only like with like.** `eval.py compare` refuses two results whose
  settings, cases or eval code hash differ. Changing a case resets the
  baseline: run it again on the old revision first.
- **Score with what ran.** `eval.py score`, and a resumed `run`, refuse a set
  whose manifest is inconsistent: its case list must be exactly the current
  cases, each once; `repeats` a positive integer equal to its settings'; its
  settings must hash to its `settings_hash`; its cases and eval code hashes
  must be the current ones. Scoring reads the record schema at the set's own
  revision and records its hash (`schema_hash`), which `compare` also requires
  to be equal. A transcript whose `case` or integer `repeat` is not its own
  file's is incomplete.
- **The cap holds before every request.** Each request, the judge's included,
  starts only if the run's cost so far plus a reservation stays within the cap
  left: every serialized wire-request byte plus 4096 tokens of framing margin
  priced as an uncached input token at the dearest input price, plus a full
  `max_tokens` of output (reasoning included). OpenRouter routing carries
  `provider.max_price` for input/output at the frozen listed prices, so a
  more expensive route cannot invalidate the bound. A run stopped this way is
  kept, with its usage, as `cap` (incomplete). Each attempt is one request:
  The legacy Anthropic adapter retries only pre-work HTTP 429/529 refusals,
  at most three times, each reserved again. The OpenRouter adapter retries no
  HTTP or network error: unknown charge status keeps the reservation. An attempt whose usage is unknown (a lost
  reply, a server error) keeps its whole reservation as spent
  (`uncertain_usd`, included in `cost_usd`) and ends the run as `error`.
  Every successful response, the actor's and the judge's, adds its reported
  usage once. Missing/invalid usage fails closed, keeping the reservation.
  OpenRouter's reported `usage.cost` is used when present; otherwise the frozen
  table prices uncached input, cached input and output separately.
- **Every case, every repeat.** A run that could not start, stopped at the cap or
  errored is a failed run, kept and counted, never retried silently. A retry is
  a new results set.
- **Resumable:** each run is its own file, written when it ends. Running again
  with the same hashes skips recorded runs and refuses a mismatch. An exclusive
  directory lock refuses concurrent runs in that directory. Before every
  request an incomplete record containing cumulative cost plus its reservation
  is atomically replaced and fsynced. A crash retains that bound as spent;
  resume never repeats the request. The cap belongs to a results set; opening
  a new set does not authorize another $20. Operators must account for all
  previously spent money before a separately approved rerun.
- **Paid and cheap stay apart.** Offline checks (`test.py`, `eval.py check`)
  cost nothing and need no key. Role runs spend money and are recorded under
  the evidence folder with their usage; a run not done is recorded `not run`.

## 7. Required text and tokens

`required-text.json` lists, for each shipped skill, the files one load of it
requires reading: its `SKILL.md` and every file it says to read every time
(`required`), files read only on some paths (`conditional`), and files it
names but never reads (`not_loaded`: scripts it runs, examples). `linked`
(optional) adds, as conditional, every file linked from the files under an
entry: for example a re-run of setup reads each setting's source again.
Every conditional, not-loaded and linked entry has its reason. A path ending
`/` is every file under it at the measured revision, for example the ADRs.

- **Complete by an independent check.** `tokens.mentions()` finds every
  existing file and folder a `SKILL.md` names (backticked paths and links,
  folders by the snapshot's listing, and the project's instructions, glossary
  and ADRs named in words). `eval.py check` fails while any of them is
  unclassified; a folder is classified only by its own entry or a parent's.

- **Count each required file once per load,** even when several skills require
  it: a load reads it again. The total is the sum over skills.
- **Moving text is no saving.** Text moved from `SKILL.md` into a required file
  still counts. A file moved from `required` to `conditional` needs its reason in
  the file, and the report shows `conditional` totals beside the required ones.
- **DeepSeek usage (#1684):** `tokens --results DIR` reads the recorded
  OpenRouter usage per run (actor and judge), without an API request. The
  `openwiz.skills-eval.provider-tokens.v1` report records the model, revision,
  settings/cases hashes, raw request usage, input/output/cached tokens and cost.
  Cached input is included in total input. The driver's normalized `usage`
  separates uncached `input_tokens` from `cache_read_input_tokens` for billing.
  These are DeepSeek tokens, not Claude tokens. Optional cache/reasoning details
  remain in raw `provider_usage`; absent cached detail normalizes to zero.
- **Required-text measurement:** `tokens --offline` retains SHA-256, bytes and
  required/conditional per-skill accounting, with null token counts. OpenRouter
  offers no equivalent preflight tokenizer here; usage from a behavioral run
  cannot be relabeled as a per-skill required-text count or saving.
- **Before and after:** `eval.py token-diff` refuses reports without actual
  required-text token counts and refuses different tokenizers. Provider-usage
  reports have a separate schema and cannot establish skill text savings.

## 8. Provenance and weekly checkpoints

`provenance.json` maps each case id to its source: for an incident, the GitHub
links that show the mistake; for a rule case, the skill file and line. Links
never enter case inputs.

**Coverage:** every shipped skill has a `workflow` case, and for each of
`approval`, `privacy` and `failure` either a case or a reason under
`not_applicable` in `provenance.json`. `eval.py check` enforces both.

Each week (E3) adds that week's mistakes as new cases and appends one checkpoint
to `provenance.json`: the week, the case ids added, the cases hash, the results
set and token report it was measured with. A changed cases hash starts a new
baseline (section 6).
