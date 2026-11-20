# Builder precheck contract, version 1

EB3-C (#2232), spec #1383. This defines the interface for EB3's pre-hand-back
self-check. It launches nothing and changes no builder instructions, checklist,
fleet/helper settings, reviewer family, spending policy, CF4 scoring or cases.
#1386 owns invocation, fixes/re-checks, cleanup and the actual hand-back gate;
#2233 produces candidate checks; #2235 consumes result facts offline.

The existing checklist and the week's known finding kinds are checked against
one pinned diff. A missing, failed or stale result blocks hand-back. Findings
must be fixed and a fresh clean result retained before independent review.
A conforming record is not necessarily usable: failure and missing observations
are valid records with blocked outcomes. Shape conformance proves no improvement
in real approval rate, merge time, reliability or cost.

## Conformance seam

`test_contract.py` is a stdlib-only conformance checker and its owning tests,
not a helper runner, scorer, production admission hook or independent reviewer.
It reads explicit local inputs only, opens nothing for writing and uses no
network, subprocess program or environment override in its check path.

```sh
python3 -I tools/skills-eval/precheck/test_contract.py
python3 -I tools/skills-eval/precheck/test_contract.py --check RECORD.json \
  --current CURRENT_REQUEST.json --at 2030-01-03T14:00:00Z \
  --experiment EB5_BUNDLE.json --journey JOURNEY_V1.json
```

`assess(record, current, bundle=None, journey=None, *, at)` returns the outcome
below; invalid shapes/joins raise `ValueError`. `validate_check(check)` validates
the candidate form for EB4, without approving or promoting it. The CLI exits 0
only for `ready`, 1 for any blocked/invalid/unreadable input and 2 for bad
arguments. `--experiment` and `--journey` go together and may be omitted for
ordinary untagged changes. `--at` is an independently supplied current UTC time,
never a helper-supplied time or a default fixture date.

All keys below are required exactly once; no extra keys. Objects and arrays keep
their types; booleans are not integers. Repeated JSON keys, nonfinite numbers,
wrong versions and operational identities refuse. JSON hashing uses EB5's
canonical SHA-256 (`experiment_contract.digest`): sorted keys, compact separators,
ASCII escaping, no nonfinite numbers, UTF-8. Hashes are 64 lowercase hex;
commits/trees are 40 lowercase hex; timestamps are UTC seconds ending `Z`.
All examples are synthetic; provenance links remain separate from inputs/results.

## Request and independently read current facts

A record has exactly `{request, result}`. The result may be null when missing.
`request` and the separately supplied `current` request each have:

| Key | Meaning |
| --- | --- |
| `schema` | `openwiz.precheck.request.v1` |
| `change` | `ordinary`, `skill`, `model` or `brief`; the last three require an experiment reference |
| `binding` | `{repo, ticket, pr, base, head, diff_hash}` |
| `skills` | `{revision: {commit, tree}, build_hash, review_hash, brief_hash}` |
| `inputs` | `{checklist, week}` below |
| `experiment` | null for an ordinary untagged change; otherwise the EB5 reference below |

`repo` is `OWNER/REPO`; ticket and PR are positive integers, never titles or
runtime identities. Base/head pin the actual compared commits. `diff_hash` is
SHA-256 of the exact bytes from
`git diff --binary --full-index --no-ext-diff <base> <head> --`.
The future caller must use these explicit revisions, verify a clean working tree
and recompute the diff; a moving branch or uncommitted change cannot pass.

`skills.revision` pins the installed build/review/brief snapshot, separately from
the code head under inspection. The three hashes pin those files' raw bytes;
`review_hash` includes the review skill's Standards/Spec/Sweep requirements.
The checklist is `{path: "skills/build-ticket/checklist.md", revision, hash}`:
its immutable commit and raw-file SHA-256, not a quotation or remembered list.

A week has exactly `{start, end, history, known_kinds, checks}`. Its interval is
seven days, half-open `[start,end)`, with the weekly producer supplying the
existing reporting boundary as UTC (PST midnight is 08:00Z). Both current time
and result completion must fall in the interval; completion cannot be in the
future. `history` is `available` or `unknown`. Unknown history retains empty
kinds/checks, never an invented zero-finding week; the existing checklist still
applies. Available history with empty kinds/checks means no known findings in
that supplied week, not proof of complete historical coverage.

`known_kinds` is the week's selected top kinds, each once as `{kind, count}`
with positive integer count. Use the existing journey finding vocabulary:
`missing-proof`, `stale-docs`, `spec-mismatch`, `fail-open`, `unknown`.
Unrecognized historical evidence stays `unknown`; do not invent a new kind.
The upstream weekly producer owns selection/deduplication/counting; this shape
checker neither re-collects GitHub nor establishes its completeness.

`checks` contains candidate self-checks in the common EB4 form:
`{id, kind, check, instruction}`. IDs are unique lowercase letters/digits/hyphens,
starting with a letter/digit. `check` is `Standards`, `Spec` or `Sweep`;
`instruction` is nonempty text. Each kind must occur in `known_kinds` and be
recognized, excluding `unknown`. `validate_check` can check a proposed row in
isolation; `assess` also checks its membership in the supplied week. These rows
are candidates only: detecting a recurrence never approves a rule/contract edit.
No threshold or promotion engine is implemented here.

The future caller reads the current diff, head, installed skill bytes, checklist
and weekly inputs independently, then compares the entire request, including
its experiment reference. A helper echoing its old request is not a current
read. Every input change invalidates the result, including a fix, a new head or
base, an unchanged-head diff change, changed checklist/skill/brief bytes, a new
week, changed known kinds/checks or changed experiment/CF4 refs. Re-check after
fixes; retain old observations rather than relabeling them as fresh.

## Result and failure states

A nonnull result has exactly:

| Key | Value |
| --- | --- |
| `schema` | `openwiz.precheck.result.v1` |
| `request_hash` | canonical SHA-256 of the entire request |
| `status` | `complete` or `failed` |
| `finished_at` | completion/failure timestamp |
| `findings` | array below; partial findings survive failure |
| `error` | null for complete; `read-failed`, `tool-failed`, `incomplete` or `unavailable` for failed |
| `no_push` | `clean`, `hit` or `unavailable` |
| `independent` | exactly false |
| `review_round` | exactly false |

A finding is exactly `{id, kind, kind_evidence, severity, check, path, line,
summary}`. IDs are local `F1`, `F2`, ... and unique within this report, never the
independent reviewer's `R` ids. Kinds use the journey vocabulary above.
`kind_evidence` is `marker`, `no marker` or `unrecognised marker`; the last two
require `unknown`. Classify only from an explicit typed marker, never infer a
kind from summary prose. Severity is `high`, `medium` or `low`; check is
`Standards`, `Spec` or `Sweep`. Path is a repository-relative nonempty path with
letter/digit/underscore/dot/hyphen components, excluding `.` and `..`; line is a
positive integer. Summary is a nonempty sanitized technical fact, never a source
comment, transcript or exact private answer. Unknown findings remain findings.

The lead assembles the envelope only after reading the helper report, archiving
it and running the existing durable-snapshot no-push check. `no_push: clean` is
the lead's assertion about that check, not a helper's permission or self-report.
Its actual snapshot/window and runtime identities stay in private resumable
state. Missing/unreadable proof is `unavailable`; a hit stops work under the
existing helper rules. A helper may only read/search/check the pinned material
and report to its lead. It cannot edit, commit, push, comment, label, open a
PR/issue, merge, launch an agent or change settings/authority. This contract does
not introduce another model profile or authorize helper invocation.

Outcomes (malformed data always refuses first):

| Outcome | Condition |
| --- | --- |
| `blocked-stale` | request differs from current, request hash differs, expired week, or completion outside the week/in the future |
| `blocked-missing` | matching current request, result null |
| `blocked-failed` | current result reports failure, even with no findings |
| `blocked-no-push` | lead has no clean no-push result |
| `blocked-findings` | any finding remains; fix/re-check before hand-back |
| `blocked-evidence` | tagged request lacks explicit EB5 bundle/journey inputs |
| `blocked-cf4` | missing refs, missing/failed result key, or referenced CF4 completion after the helper result |
| `ready` | current complete clean result, no findings, and all applicable reference checks pass |

Precedence is the table order. Stale observations are retained but unusable;
missing results never become successful empty reports. `ready` means only this
interface's conformance conditions hold. It does not approve hand-back, a PR,
merge or experiment launch. Byte/source verification is still the consumer's
job; a fabricated matching hash or assertion proves nothing by itself.

## Shared experiment and CF4 references

Use [EB5's experiment contract](../../collector/experiment-contract.md)
unchanged. There is no second experiment schema, stage store, assignment record
or evaluator. The precheck's `experiment` is a reference only:
`{tag, experiment_hash, arm, cf4_refs}`. Tag + bound repository + canonical
experiment hash identify EB5's frozen experiment. Arm is `old` or `candidate`.
`cf4_refs` is null when unavailable, otherwise EB5's `{old: key, candidate: key}`
references to exact result records in `cf4_runs`. It does not contain copied
manifests or independent result counters.

The explicit bundle and journey must pass `experiment_contract.validate`.
Request identity must match that bundle; ticket/PR must join its bound journey.
The selected arm's revision, build/review/brief hashes must equal request skills;
nonordinary `change` must equal its `change_kind`. The journey's historical PR
tag is not a current binding and is not used as a substitute for this explicit
reference. No historical PR metadata is rewritten here.

EB5 owns both CF4 input references, including manifest/settings/cases/code/schema
hashes, commit/tree, repetitions and case count; its compatibility rules require
like-for-like inputs and fresh baseline after suite/settings/scorer/schema
changes. The exact referenced result key in **both** arms must pass every case
on every repeat and complete no later than the helper result. A later retry's
pass cannot replace a failed selected key. Unrun/missing/failed/skipped results
block; offline conformance is never a paid baseline. Actual pinned manifest and
score bytes, coverage and permission still need verification through CF4's
existing seam. Shared gate edits that change compared skills need new compatible
manifests; old evidence cannot pass by acquiring a new label.

## Independent review and retained authority

Helper findings and results are structured records, never `review-ticket`
report bodies starting with `VERDICT:` followed by `Full review by` / `Re-check`.
They are not independent findings, verdicts or review rounds and cannot be fed
into those arrays as independent observations. Mentioning a report token in a
technical summary grants no verdict or round status. Consumers keep
them separate under the [journey contract](../../collector/journey-contract.md),
including its outcome sidecar's helper/round separation. No independent round
count or approval field is supplied by this result.

Exact-head independent review in the required other family, required CI and
verified merge remain mandatory. Live work, paid CF4/API-key/spending gates,
activation/weekly-loop registration, releases, publication and public cut-over
retain their separate approvals. A ready label, conforming reference or helper
result grants none of that authority. Existing spending/model/settings rules
are unchanged; later integration uses the then-approved profiles.

[Conformance examples](contract-fixtures/README.md) prove this interface only.
