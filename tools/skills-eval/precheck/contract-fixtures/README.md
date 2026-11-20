# Synthetic precheck examples

All values, revisions, dates and technical findings here are invented. These
files contain no provenance links or runtime identities. They prove shape and
refusal behavior, never actual helper quality or live/paid evidence.

- `complete.json`: ordinary untagged request and clean complete result.
- `failed.json`: the same request with an explicit tool failure; conforms but
  blocks hand-back even though its findings list is empty.
- `findings.json`: a complete result with one typed helper finding; conforms but
  blocks until a fix and fresh clean check.
- `controls.json`: refusing and conforming examples expressed as one replacement
  of `complete.json` at `path` (object keys or array indexes). `expect` is either
  the exact outcome or `invalid:<reason>` for a malformed record. Expectations
  are literal, independently chosen from the contract.

Run `python3 -I tools/skills-eval/precheck/test_contract.py`. Its table runner
requires the exact outcome or refusal reason for every control; an always-ready
checker fails. Its CLI tests provide a separate current request and current time,
assert the process status, and check that the input directory gains no files.
The checker prints conformance only and never invokes a helper.

For a tagged example the tests join, by reference, EB5's synthetic
`tools/collector/fixtures/bottlenecks-contract/accepted.json` and its bound
`fixtures/journey/journeys.json`. They use tag `synthetic-skills-1`, candidate
revision `bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb` (commit and tree), its three
skill hashes of 64 `b`s, and exact CF4 keys `old-cf4-1` / `candidate-cf4-1`.
Both results pass 60 of 60 planned runs before helper completion. The frozen
experiment hash is taken as a literal from that independently supplied fixture;
no competing experiment or manifest format is created here.

The suite also tests changed base/head/diff, skill commit/tree/bytes, checklist,
week, unknown kinds, independently counted helper findings, stale hashes,
expired/future timestamps, missing or failed results, no-push failures and
missing/failed/late/incompatible CF4 references. All dates are controlled;
no wall-clock race, live call, API key or paid model run is involved.
