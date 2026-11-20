# Paired replay contract, version 1

EB5 (#2176) pins the `replay` member of
[openwiz.bottlenecks.v1](../collector/experiment-contract.md). EB7 (#2178)
owns its producer, isolation, execution, scoring and actual report. CF4's
[existing contract](contract.md) remains unchanged; no new evaluator is built
here. `experiment_contract.execute('run_replay', ...)` always refuses.

A replay record has exactly `frozen_at`, `started_at`, `completed_at`, `cf4_refs`, `selection_rules`, `exclusions`,
`rubric`, `rubric_hash`, `cohort`, `selection`, `avoided_rounds`. Start/completion timestamps are nullable before those events; an attempted run
requires a start after freeze, passed research and the bound passing CF4 results. Selecting an
arm requires a completion timestamp. That completion predates live protocol
registration, approval and assignment. Freeze selection
rules and exclusions (`{pr, reason}`) before either arm. Production targets about
20 historical merged PRs, both known-problem and clean-control cases; the one-row
fixture is only a small interface example. Never silently replace exclusions or
score only flattering rows. Empty cohorts and repeated/excluded PRs refuse.

Each cohort row has `pr`, `first_review_at`, `base`, `head`, `context_hash`,
`context`, `history`, `known`, `arms`. Base/head are the original first-review
commits, not today's. `history` records `merge_commit`, `merged_at`, `source`,
`independent_rounds` (integer or null), and `defects: {status, count,
observed_until}`. Historical defects are unknown/unmatured/mature under the
experiment's frozen follow-up; unknown has null count/time. Coverage and
attribution require source review, never inferred zeroes. A completed replay
cannot prove historical avoided rounds or actual first-push-to-merge improvement.

`context` has `isolation: verified|unavailable`, `materials`, `sealed_key_hash`.
Each material has `kind` (original-diff/original-file/original-instructions), `at`
(no later than first review), `hash`. Its context manifest hashes all available
material and permissions; both arms use exactly the same bundle. The sealed key
hash pins answers kept apart by the scorer; it is **not a reviewer material**.
A material hash equal to the sealed-key hash is refused even with an allowed
kind. Detecting transformed leaks and establishing real permissions remain EB7 work.
The full experiment/replay/scoring record is likewise not reviewer input.

EB7 must resolve material hashes to a scoped, read-only bundle and tools with no
access to the current checkout, later fixes/verdicts, output of the other arm or
answer key. A shared sandbox alone establishes no isolation. Missing original
head/base, uncertain available-at-time context or unavailable scoped tooling
means not run. The shape validator checks attestations and manifest boundaries,
not real filesystem permissions or source availability; those need independent
isolation proofs before dispatch.

Each arm has `status` (complete/not_run/error/uncertain), `run_key`, `context_key`,
`settings_hash`, `skill_hash`, `context_hash`, `report_hash`, `reported_at`,
`finished_at`, `adjudications`. Keys are local logical
record ids, never CloudRoom identities. Fresh context and run keys are unique
across the cohort and arms. Settings and review-skill hashes bind the frozen
experiment; context hashes bind the shared snapshot. Complete arms bind the immutable review output and its completion time,
separately from later scoring. Non-complete arms have null report hash/time and
no adjudications, and remain visible. Every complete/error/uncertain attempt
records `finished_at`; not_run uses null while pending, or a timestamp for an
explicit final decision to skip. A completed report is received no later than
its attempt finishes. Terminal attempt timestamps cannot change on resume. Unavailable isolation permits only not_run.
An uncertain attempt is retained and never dispatched again as though absent.

The fixed rubric is:

```json
{"matching":"same-root-cause-and-location","deduplication":"root-cause-per-pr","severity":["high","medium","low"],"unmatched":"unadjudicated-until-blind-review","adjudication":"arm-blind","missing_pair":"retain-inconclusive"}
```

The rubric hash pins that exact object. `known` contains unique `{id, severity}`
answer-key entries, available only on the post-review scoring surface. After both
reviews, arm-blinded adjudication maps reports to canonical root cause/location
ids; multiple mentions of one issue produce one score. Matching and severity
rules are identical for both arms. EB7 retains separate adjudication provenance
and raw output outside reviewer contexts; no source transcripts are fixture data.

Each adjudication checkpoint is `{at, source, findings}`: an arm-blind scored
snapshot after **both** paired attempts are terminal, with nondecreasing
timestamps. Its time is no earlier than either finished_at, including an error,
uncertain or explicit not-run disposition. A pending arm keeps the key sealed;
missing counterpart output is not permission to score early. Checkpoints append
only; never overwrite a prior decision. The latest snapshot supplies the paired
score, while the immutable report hash keeps the underlying output fixed. A
complete review with no adjudication is unresolved, never a clean-control pass.
A later snapshot may resolve matches, misses, false positives or disputes;
that changes scoring evidence without rerunning the reviewer.

Each snapshot's paired findings are unique `{id, severity, outcome}` entries:

- `catch`/`miss` must name a known real problem with matching severity. Every
  known problem appears once in each complete arm, including misses.
- `false_positive` is a distinct report adjudicated not to be a real problem,
  never a known problem and never inferred just because matching failed.
- `unmatched` and `unadjudicated` retain unresolved reports; they do not become
  false positives, catches or clean controls. Unadjudicated known problems stay
  visible with their key. Empty known sets represent clean controls.

Catch/miss/false-positive counts and severity denominators are the counts of
these canonical rows, with complete-pair and unresolved coverage reported apart.
The literal fixture has two real problems: old catches 1, misses 1 and raises
1 false positive; candidate catches 2, misses 0, raises 0 false positives. Partial
fixture retains old's complete score and candidate's error; it cannot select a
candidate. `selection` is old/candidate/none/pending, and only fully complete,
adjudicated pairs can select old/candidate. No-result/partial pairs are never
silently dropped, retried or averaged as complete pairs. Aggregate paired effects
and their uncertainty are EB7's work, not a second scorer in this contract ticket.

`avoided_rounds: {value, evidence_class: estimate}` is nullable and explicitly an
estimate. Observed historical rounds remain separate. Usage uses the shared
per-arm/total rows, with Codex tokens distinct from Cloud credits and sandbox
hours; shared/unattributed costs are gaps, never equally allocated or zero.

`validate_transition` freezes cohort, original revisions, context, history,
answer-key entries, rubric and planned run bindings. A not_run attempt can gain
its single result; complete/error/uncertain review output cannot be rewritten or
silently repeated. Completed reviews can gain append-only adjudications until
the replay report is finalized. Final completion freezes the whole report. Fresh retries require separate authorized records. This
format grants neither bounded dispatch nor a live go-ahead; the EB7 owner hands
the completed reviewed manifest to the orchestrator under the existing gates.
