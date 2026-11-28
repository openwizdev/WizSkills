# Escalation contract, version 1 (`openwiz.escalation.v1`)

CP4 (#3787) of OpenWiz spec #3719. This contract gives launch-fleet one
optional builder escalation per ticket. CP5 (#3790) implements it and runs
the [synthetic cases](fixtures/escalation/cases.json).
[Models v1](models.v1.md) still owns normal role selection, model IDs and
reviewer selection.

## The fleet row

Read `docs/agents/fleet.md` from the default branch at each builder start.
Zero `## Escalation` headings means normal routing. One heading means read
the first table in that section, bounded by the next level-two or
higher heading. Prose may precede the table. For example:

```md
## Escalation

| Harness | Model | Effort | `room-cli thread spawn` flags |
| --- | --- | --- | --- |
| Codex | Sol 6.2 | Xhigh | `--provider codex --model gpt-6.2-sol --reasoning-level xhigh` |
```

The header, separator and one data row are required, with the Models table's
four choice columns in their original order. Trim cells as in Models v1.
Use its non-empty display names, single code span, exact flag order and ID
grammar. The flags supply the provider, model and effort IDs used for the
start. There is no Role column or following row. A duplicate heading, missing
table or invalid first table refuses the start. Report the bad Escalation
configuration and start nothing. Readers never search subsequent tables for
a usable row.

## Failed attempts

A failed attempt is a builder run on this ticket that ended stopped, failed
or replaced without its linked pull request reaching green required checks
during that run. Use the ticket's [status notes](agent-status.v1.md) and
trusted launch-fleet records to establish the run and its end. Use the linked
pull request's required-check evidence for the head associated with that run
and time. A later head or a later red result cannot erase a proven green.
A run that conclusively ended without opening a pull request also counts.

- Count a run once, using its builder status-note comment ID as its public
  reference. Edits keep the same ID. Associate the note with the confirmed
  start using the ticket's records. A confirmed replacement can have its own
  note and count separately on the same branch or pull request.
- A refused, untried or withdrawn start is no run. A live or merely lapsed
  note does not prove an end. A `done` note alone reports a hand-off and says
  nothing about terminal failure or green required checks. Reviewer and
  fleet notes do not count as builder runs.
- Count only runs whose end and absence of green checks are established. A
  missing link with inconclusive records, unavailable checks or conflicting
  attribution is unknown. A known pending or failed check at one point is
  insufficient to infer the run's entire check history.

The threshold is two distinct failed attempts. When more than two are
established, use the first two in end order, breaking a tie by ascending note
ID, as the evidence for crossing the threshold.

## Choosing a builder

| Condition | Choice before quota fallback |
| --- | --- |
| Escalation section absent | The normal Models v1 choice, without needing escalation history |
| Escalation section malformed | Refuse, even with no failed attempts |
| Valid row, fewer than two failed attempts | The normal Models v1 choice |
| Valid row, at least two failed attempts and no escalated start yet | The Escalation row |
| Valid row and a confirmed escalated start on this ticket | The normal Models v1 choice on every later start |

The rule covers Builder and Small builder starts. Keep the existing role
and apply the existing [quota fallback](https://github.com/openwizdev/OpenWiz/issues/3500)
after the choice. A fallback that launches still belongs to that escalated
start. If quota fallback says to wait before launch, it creates no failed
attempt and does not use the escalation. The chosen row affects only this
start. It changes no Models setting or running job.

## Recording the escalation

Within launch-fleet's existing start claim, write the escalation on the
ticket before launching the builder. The comment body has these two lines:

```text
launch-fleet: escalated #<ticket> after 2 failed attempts: <harness> <model> <effort>
Attempts: <note-id>, <note-id>
```

The first line uses the IDs from the Escalation row before quota fallback.
The second line gives the two public builder status-note comment IDs in
threshold order. The checked start and builder status note record the actual
launch, including any quota fallback. Keep private run and host identifiers
out of the public comment.

Treat the comment as a reservation until its start is confirmed. Reconcile
an existing reservation before starting anything. While its outcome is
uncertain, wait. If the records prove no run started, the same reservation
may be reused. Re-read the current row before retrying and update the
reservation in place if its planned choice changed. A confirmed start uses
the escalation for the ticket, even when its builder later fails. Neither
edits to the Escalation row nor subsequent failures make it available again.

## Review

Apply [the Models v1 cross-family rule](models.v1.md#the-cross-family-rule)
to the branch-matching checked start and the actual builder's verified
harness, including any quota fallback. Use the configured Reviewer when
its known family differs, otherwise the configured Builder when its known
family differs, otherwise wait. An unknown builder family waits.

## Fixture inputs and outcomes

Each case in [`cases.json`](fixtures/escalation/cases.json) names a synthetic
fleet file and ticket. Its `history` is a chronological projection of the
ticket's established evidence, one entry per confirmed builder run:

| Field | Meaning |
| --- | --- |
| `note`, `start` | Public builder status-note and start comment IDs |
| `branch`, `pr` | The checked branch and attributed pull request number, or null for no attributed pull request |
| `end` | `stopped`, `failed`, `replaced` or null for no proven end |
| `checks` | `green` for a proven green during the run, `not_green` for a proven absence of green up to its end, `no_pr` for a proven absence of a pull request, or `unknown` |

`unstarted` holds raw comments for claims that did not start. An optional
`prior_escalation` holds the record body, its associated checked start
comment ID or null, and the reconciliation state (`started`,
`not_started` or `unconfirmed`). The requested role defaults to `builder`.
An optional `quota` supplies the downstream fallback result
(`fallback` with a choice, or `wait`). These are test inputs, not new
GitHub record formats.

`expected.choice` is `models`, `escalation`, `refused` or `wait`.
An expected refusal or wait before model selection gives a reason.
For a selected route, `requested` gives its provider, model and effort
before quota fallback and `effective` gives the final choice or null
if quota blocks the start. `failed`, when present, gives the note IDs
counted as failures. `record` gives the new reservation body or null, and
`review` gives the cross-family role and provider for an effective start,
only the role `waits` when review waits, or null when there is no start.

Models v1 has no new fields or roles. The fixtures pin decisions for CP5
and do not start, replace or review any live run.
