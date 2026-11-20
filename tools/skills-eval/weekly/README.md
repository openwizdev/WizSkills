# Weekly collection and checkpoint core (#2236)

This is the fake-tool core consumed by #1363. Run its free, synthetic proofs:

```sh
python3 -I tools/skills-eval/weekly/test_weekly.py
```

Importing `run.py`, executing it, or calling `tick` without explicit fake tools
has no effect. No API client, model request, subprocess, scheduler, loop,
builder, ticket, merge or action executor is implemented here. Python standard
library only. No key is needed.

## Collection core

`collect.collect(week, read_page, synthesize, skills, ...)` reads all pages of
`issue_comments`, `review_comments` and `reviews`. They represent GitHub issue
and PR conversation comments (including launch-fleet and review verdict
records), inline review comments, and PR reviews respectively. Ordinary progress
comments may return no candidate. `week` is its UTC Monday, `YYYY-MM-DD`; the
interval includes Monday 00:00 and excludes the following Monday 00:00, using
source `updated_at` so newly edited evidence is considered too.

The injected `read_page(source, week, page)` boundary returns exactly:

```json
{"items": [{"id": 9001, "updated_at": "2030-01-08T12:00:00Z", "body": "synthetic mistake", "url": "https://github.com/example/work/issues/4901#issuecomment-9001"}], "next_page": null}
```

Pages start at 1; `next_page` is the next integer or explicit `null`. A failed
read, absent continuation, malformed record, conflicting repeated identity,
empty intermediate page or repeated page refuses the complete collection.
There is no partial-success result or per-source advancement. All three sources
must finish, including explicit empty responses. A later real adapter belongs
to #1363: it must normalize and check actual tool exit/error/JSON/continuation
information, and enumerate **every** relevant PR and its review pages for the
`reviews` family. An array with unknown completeness is never a complete page.
These tests prove the injected boundary, not real GitHub enumeration.

Each source record's anchor ID must equal its `id`. Conversation comments use
`issues/...#issuecomment-ID` or `pull/...#issuecomment-ID`; inline review comments
use `pull/...#discussion_rID`; reviews use `pull/...#pullrequestreview-ID`.
Repeated identities are compared across every returned record before date
filtering, so conflicting copies on opposite sides of the week refuse the
collection. Only in-week records enter synthesis and source checkpoints.

`synthesize(item)` is an injected pure function returning `None`, or exactly
`{incident: <stable synthetic key>, case: <E1 case>}`. It must assign the same
incident and case IDs to repeated evidence for one mistake, across source
families and weeks. A changed meaning needs a new case/baseline. This core does
not infer incidents from keywords or run a model. That synthesis integration and
its source selection belong to #1363. Bodies are transient and never persisted.
E1's case/privacy validator and pass/fail control scorer reject invalid drafts;
semantic de-identification still needs independent review. Links stay in the
separate provenance map, never in case inputs. Source checkpoints retain only
week, source IDs and content hashes. Repeated source IDs are processed once;
repeated incidents accumulate unique links without duplicating their cases.

## Checkpoint and fake-eval core

`run.tick(directory, week, cases_dir=..., provenance=..., skills=..., read_page=...,
synthesize=..., evidence=...)` writes only the explicitly selected local state
directory. `cases_dir` is an immutable synthetic case snapshot, not the live
suite to edit. A nonempty snapshot requires its complete E1 `provenance` object;
its rule/incident source entries and coverage explanations are retained with
the new links. A missing source index refuses preparation. The core preserves
its exact UTF-8 file bytes and uses E1's sorted filename/NUL/byte hashing.
Snapshots are decoded from bytes without newline translation, preserving CRLF
as well as LF in the saved case-file strings and their hashes.
New cases use a deterministic JSON encoding.
It does not alter `tools/skills-eval/cases/` or the canonical provenance file.

The first call atomically saves a `prepared` transaction with the complete
collection and candidate files. A second call can inject matching fake baseline
and result scores and evidence references. Crash/resume reuses that preparation
without another read or synthesis. One exclusive directory lock covers the
state re-read, preparation and completion. Each replacement fsyncs its file and
parent directory. Candidate files, incident identities, provenance, source
checkpoints and the successful week commit in one replacement, so there is no
window with a successful checkpoint but missing cases. The latest injected
evidence is retained with the success receipt; saved completion/state records
are validated again on resume. The `case_files` map can be materialized by
#1363; this core performs no publication.

The fake evidence envelope has `mode: "fake"`, frozen `settings` (including
its repetition count), E1 `baseline` and `result` score objects, `results_set`
and `token_report` references. Settings must hash to each score's recorded
settings hash. All cases and frozen repeats must be present exactly once;
completed passing rows must have no failure
reasons, all comparison hashes must match, and the result must pass. Paid or live
outcomes are refused. An interrupted, failed or incompatible outcome leaves the
successful week/source checkpoints unchanged and reports a gap. The prepared
transaction remains available for resumption; finish it before a later week.
Changing case bytes or the supplied provenance during a prepared week is refused.

The first snapshot seeds the existing suite. Later supplied snapshot additions
are counted alongside collected new cases. Previously accumulated links are
retained when a snapshot supplies an older provenance entry. A completed week
appends E1's checkpoint to its local provenance object:

```json
{"week": "2030-01-07", "case_ids": ["i9001-weekly-mistake"], "cases_hash": "<E1 SHA-256>", "results_set": "synthetic-results/week", "token_report": "synthetic-tokens/week.json"}
```

A complete collection with no added cases and an unchanged cases hash reports
`unchanged` and carries forward the last compatible evidence references. A
changed hash always needs a fresh matching baseline; E1 comparison refuses the
old one. A completed week's repeat returns its saved result and appends nothing.
Unread sources return a gap and preserve the previous successful state. Gaps
never include raw exception text or source bodies.

Every result is labeled `fixture test`, with `saving: null`. Injected outcomes
and references are synthetic evidence, never a measured token/credit saving or
proof of live reliability. Real first-pass continuation, experiment-stage
binding, fixed paid eval execution, eval/fix/cut routing, runbook, registration
and the first real weekly result remain #1363's work, with all their native
prerequisites and separate approvals intact. This core invents no experiment
stage field and registers no second loop.

## Weekly runbook (#1363)

The sections above describe #2236's core (`collect.py` and `tick`). The
integration below `run.py`'s marked line adds a CLI and one program, `gh api`,
run only by the `sources` and `tick` commands; importing `run.py` or running
`dry-run` still reads nothing remote and starts nothing.

**Measured evidence (J29, revision 17 of spec #1358).** The core's
`score_valid`, `evidence_valid`, `reply` and completion-receipt check also
accept `mode: "measured"`: the same envelope, hashes, repeats and all-pass
rule, with real finite, non-negative `cost_usd` per score and row. Fake mode
stays zero-cost only. A week completed on measured evidence, and an
unchanged week carrying it forward, are labelled `evidence_class: "measured
run"` rather than `"fixture test"`. The core notes above describe fake mode,
and no other core rule changed.

The one weekly process for spec #1358: `run.weekly(...)` wraps the core's
`tick` above, and `run.py` is its CLI. It never starts a builder, reviewer,
replay or live arm, never merges, and never pays: every effect goes through an
injected `route` (the CLI queues each action in the durable ledger) and builder
work through an injected `start_gate`. Fixture proofs, with no key, network or process:

```sh
OPENWIZ_PRIVACY_LITERALS=<synthetic list> python3 -I tools/skills-eval/weekly/test_weekly.py
python3 -I tools/skills-eval/weekly/run.py dry-run --out DIR       # synthetic week; report.md + report.json
python3 -I tools/skills-eval/weekly/run.py loop-definition --prompt-file FILE   # prints the one create command
```

### What a tick does

1. **Collect** last week (the UTC Monday before this tick's Monday).
   `run.py sources --repo OWNER/NAME --week W` prints that week's issue/PR
   comments, inline review comments and reviews to the terminal only, read
   through `gh api --paginate --slurp`; a failed or malformed read refuses the
   whole week. The agent writes a drafts file mapping **every** printed URL to
   `null` or `{incident, case}`: a synthetic E1 case, no quotes or links.
2. **Tick:** `run.py tick --repo R --week W --state DIR --drafts FILE
   --report DIR`, adding `--experiments`, `--baseline`,
   `--evidence`, `--cuts` and `--tokens` files when their owners have them. An
   undecided URL, a bad draft or any read gap leaves the last successful
   checkpoint as it was and reports the gap. The report is rendered, and its
   privacy check passed, before `report.json` or `report.md` is written; a
   refusal leaves both earlier files as they were.
3. **Baseline first.** New cases are a new baseline. `--baseline` is
   `{settings, score}` for fixture scores or `{mode: "measured", settings,
   score}` for an E1 score with its real recorded costs; it is labelled
   `measured run`. `--evidence` with `mode: "measured"` completes the week
   the same way. A baseline with failing
   cases routes one `fix` per caught skill; cuts wait until a passing result
   exists at the same cases hash. A failed cut is rejected and recorded; a
   passing one routes one `cut` ticket. Every cut must be comparable with the
   carried result under `E1.compare` (cases, settings, eval code and record
   schema hashes), or the tick refuses before recording any cut. An unchanged week re-tries cuts on the
   carried-forward result and routes no old fix again.
4. **Stages.** `--experiments` holds owners' import summaries
   (`tag, experiment_hash, stages, sources`, EB5's stage shape). Known stages
   are retained when a summary is absent. A changed experiment hash or a
   changed completed stage refuses the tick: a new candidate or case set is a
   new tag. Replay is proposed only when research and CF4 passed, live only
   when replay passed too; everything else is listed as blocked. Not-run
   stages, missing tokens and missing evals print `unobserved`, never zero.
5. **Route once.** Each action has a stable key and is recorded `unresolved`
   durably before routing. The CLI then marks it `queued`: it stays in
   `weekly.json`, so it survives a fresh sandbox. `run.py pending --state DIR`
   lists queued and unresolved actions. For each one, run `run.py handoff
   --state DIR --repo R --issue 1358 --key KEY` and nothing else:
   - It reads every comment on the issue first. A comment with the line
     `weekly-handoff: KEY SHA256` (the sha256 of the action's canonical
     payload) **and** the line `payload: <that payload>`, anywhere in it, is
     the earlier handoff, and it is recorded without posting.
   - A bare, stale or copied marker, with another hash or no payload, is not
     the earlier handoff: new pending work is posted, never dropped.
   - If the read fails, nothing is posted and the handoff is reported
     uncertain.
   - Otherwise it marks the action `unresolved`, posts one comment carrying
     the marker and payload lines, and records the new comment id as `routed`.

   A lost reply leaves the action `unresolved` until the next `handoff` finds
   the posted marker. Never post a handoff by hand, and no tick re-sends one.
   The orchestrator turns routed actions into ordinary tickets, builders,
   exact-head reviews, CI and verified merges under the standing rules.
6. **Report.** Post `report.md` as the short weekly result on spec #1358:
   cases added, pass/fail, actions, stages, blocked steps, tokens per skill and
   total, revisions and gaps. Rendering refuses links and thread/project ids.
   If nothing is new, post the unchanged result and archive the tick.

**State.** Each cron run is a fresh sandbox, so the state directory is
`private/evidence/skills-eval/e3/state/` on `main`. The tick's `state.json` and
`weekly.json` (never the lock files) land through the week's ordinary
infra PR, with the week's new case files materialized under that routed
ticket. If last week's PR has not merged, the tick reports that gap and
advances nothing.

### Credit-aware start rule

Jake's rule for CF4: builder work waits behind CI priority periods (spec
#1358's confirmation: built after that night's CI work), and the fleet's CS5
overload admission (`fleet.sh overload`, `docs/agents/fleet.md`) applies as
well. `--starts` defaults to `deferred`; pass `allowed` only when the
orchestrator's current records say builder starts are open. Deferred fix and
cut actions stay pending in the ledger, never done. Every later tick, in the
same week or a later one, reconsiders them under their original keys without
needing the baseline or cut inputs again, and the next allowed tick routes each
one once. Outstanding actions from earlier weeks stay in each week's report. A stage-ready proposal informs the orchestrator; it starts
nothing.

### Stop, resume, review

- **Stop:** the orchestrator runs `room-cli loop pause <id>`; `delete` ends
  it. The id stays in private orchestration state, never in this repository.
- **Resume:** `room-cli loop resume <id>`. A missed week is ticked by hand
  with the same commands; the checkpoints make a repeat a no-op.
- **Review:** every weekly result is a GitHub comment, and every routed change
  is an ordinary ticket with exact-head independent review and CI. The loop
  itself is registered once by the orchestrator after #1363's verified merge,
  with its schedule read back from `room-cli loop list`. That proves the
  schedule, not that future runs succeed.

### Gaps (honest, current)

- **No real weekly result yet.** #1362's real baseline, eval-backed cuts and
  token reports are this loop's end gate. The paid eval route (assumption A1,
  Hermes `deepseek:deepseek-v4.1-flash`), spend and the private literals
  input are #1362's gate. The measured path is proven only on synthetic
  nonzero-cost E1 outputs; no measured result exists yet.
- **Tokens:** required-text token counts are not measured (E1's offline
  report has bytes, not tokens), so they print `unobserved`.
- **Reviews read:** PRs are enumerated by `updated_at`; a review submitted in
  the week always updates its PR, but this rests on GitHub's behaviour, not a
  proof here. The reader is proven on a fake `gh` only.
- **Handoff marker:** reconciliation needs the exact key, payload hash and
  payload. It does not check the author: all agents post as one account
  until the OpenWiz App lands, so a deliberate full copy of a genuine handoff
  would still count. The `gh` issue adapter is proven on a fake runner only.
- **Loop agent auth:** the definition passes `--secrets none`, assuming the
  Cloud sandbox's own `gh` login; registration read-back must confirm it.
