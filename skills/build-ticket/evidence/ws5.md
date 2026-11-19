# WS5 build-ticket proof

## SK-B and SK-C

Same `build-ticket.regression` case and stop as WS1: an ordinary approved
ticket through scoped hand-back, with simulated effects and no grant or
review response. The skill runs `ticket.py` without reading its source. The
review loop and the ops-dispatch rules load only on their own branches. The
App identity section of launch-fleet loads only when an App token mints, so
both branches are counted.

| Evidence | Before | After |
| --- | ---: | ---: |
| Entrypoint lines (WS1 pin / pre-rewrite `main`) | 377 / 354 | 89 |
| Entrypoint words (WS1 pin / pre-rewrite `main`) | 6,777 / 5,848 | 1,415 |
| Entrypoint static tokens (WS1 pin) | 9,389 | 2,095 |
| Static loaded-path tokens, no App token | 53,161 | 14,798 (−72.2%) |
| Static loaded-path tokens, App token mints | 53,161 | 40,032 (−24.7%) |
| Observed workflow outcome | Pass | Unknown |
| Observed workflow token counts and wall time | Unknown | Unknown |

Conditional references carry static token counts of 718 for
`references/review.md` and 566 for `references/ops.md`. These references are
outside the regression branch. The entrypoint includes the full license notice
that the WizSkills checker requires.

The before values come from the
[WS1 static baseline](../../../tools/measure/evidence/static-baseline.json)
and [LV1 receipts](../../../tools/measure/evidence/lv1.json) at
`89fc285ce551f341b8d308732bcd8d4467ace353`. The
[after path manifest](ws5-after-paths.json) pins the candidate text, and the
[static count](ws5-static-after.json) uses the same tokenizer and encoding.
To regenerate it, run
`node tools/measure/static-count.cjs skills/build-ticket/evidence/ws5-after-paths.json <tokenizer>`
from the WizSkills root, using `js-tiktoken@1.0.21`.

The [after receipt](ws5-after-receipt.json) is `measure.py`'s output for the
matched observation. It uses the baseline profile and the pinned candidate.
Its outcome and all counters are `null` until the fleet runs the independent
after trial. The `build-ticket.near-miss` and `build-ticket.unowned-path`
trials are also unrun. They have the fixture-level proofs listed below.

## SK-D: mechanics in tested scripts

`scripts/ticket.py` now does the mechanics that the text used to spell out:

- reading the ticket's owned paths and readiness
- checking every changed path, including both sides of a rename and untracked files
- reading the record-author row and the newest trusted verdict against the current head
- setting the noreply author
- keeping and posting the first-successful-push receipt with read-back

Run `python3 -I skills/build-ticket/scripts/test_ticket.py -v`, which
`check/run.py` also runs. All 17 tests first failed against a stub that
exits 2 for every command. Each failure reached its own assertion, as shown in
[ws5-red.txt](ws5-red.txt).

Each guard below was broken in a temporary copy of the implementation. The
named test then failed, and restoring the copy made it pass.

| Planted break | Caught by |
| --- | --- |
| Folder prefix matched without its `/` boundary | `test_scope_flags_every_unowned_side` |
| Only the new side of a rename checked | `test_scope_flags_every_unowned_side` |
| Untracked files skipped | `test_scope_flags_every_unowned_side` |
| Any commenter's `VERDICT:` trusted | `test_records_trusts_only_record_authors` |
| An empty authors row trusts everyone | `test_records_without_a_valid_authors_row_trusts_nobody` |
| Verdict head not compared with the current head | `test_records_marks_a_verdict_on_an_older_head` |
| Open blocker ignored | `test_read_refuses_an_open_blocker` |
| `needs-info` ignored | `test_read_refuses_a_ticket_not_released_to_agents` |
| Repository qualifier read as an owned path | `test_read_lists_owned_paths_and_readiness` |
| Receipt replaced on a later push | `test_push_receipt_records_only_the_first_success` |
| Receipt saved after a failed push | `test_push_receipt_records_only_the_first_success` |
| Receipt allowed inside the checkout | `test_push_refuses_a_receipt_inside_the_checkout` |
| Post without reading back first | `test_post_receipt_survives_a_lost_response_and_never_posts_twice` |
| Lost POST response treated as not posted | `test_post_receipt_survives_a_lost_response_and_never_posts_twice` |
| Author email not the noreply form | `test_author_sets_the_users_noreply_identity` |

## SK-E: guards

- **Privacy.** The skill still names the open-development contract and keeps
  its no-private-details rule visible. The receipt is refused inside the
  checkout.
- **Approval.** The skill states the rules for owned paths, supporting
  edits, standing rules, shared files, ticket bodies and asking first. The
  `scope` command enforces them, and ops-dispatch envelopes and grants are in
  `references/ops.md`.
- **Records.** The skill states the record-author rule, and the `records`
  command enforces it. Without a valid authors row, it trusts nobody.
- **Builder and reviewer.** The builder never reviews, merges or delegates,
  uses no helper agents, never waits awake, follows the 1 + 1 loop with its
  `Next:` states and archives itself after a merge or close (CW16).

No build-ticket suite existed before this change, and no test was deleted.
The skill rules, the standalone check and every other suite run unchanged.
