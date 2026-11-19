---
name: to-tickets
description: Turn a confirmed spec into sized tickets and a plan graph for the owner's exact approval. Use to propose tickets, draw the graph or re-approve a changed plan. Send unconfirmed specs to to-spec.
version: 0.2.0
---

# To tickets

The orchestrator takes a confirmed spec to an approved, read-back graph. In
OpenWiz, [the roads page](https://github.com/openwizdev/OpenWiz/blob/main/docs/agents/roads.md)
describes when this road applies.

## 1. Check the starting point

Read the project's tracker, domain, label and fleet settings in `docs/agents/`.
Verify the current spec confirmation and its private pointer. If the spec
needs a decision, stop and use [to-spec](../to-spec/SKILL.md). If the plan was
already approved, [hold before editing](changes.md). Existing contract holds
keep their recorded release conditions.

Keep exact owner replies and private sources private. Verify tracker and private
repository before writing. A failed read, ambiguous reply or unknown approval
stops the write or handoff it would authorize.

## 2. Draw the proposal

Cut end-to-end tickets as large as one builder can finish near-certainly in one
fresh context. Use first-pass review results from comparable work to size
S, M or L. Keep the graph wide and short by giving builders disjoint owned paths
and using only necessary arrows. Record genuine file links and why each cannot
be split. Use a contract-first ticket for a shared interface, or say why none
is needed. See [the ticket and graph inputs](tickets.md).

Run `python3 -I "<this skill's folder>/scripts/picture.py" < graph.json > picture.md`. Use the
same picture inline in chat and in the spec's proposed-graph comment. Mark size
on each card, green for merged, blue for building and grey for waiting. Jake's
tickets and the release go use purple. The script groups shared prerequisites
and bolds the critical path. Fix inconsistent inputs if it refuses.

Show the graph, the ticket table and the file links. Ask the owner whether the
tickets are the right size, whether the arrows are right, and what to merge or
split. Iterate until the owner accepts the proposal.

## 3. Write and verify the tickets

Create each issue without a ready label, blockers first, in the confirmed
spec's milestone. Set the native parent and blockers. Read back every issue
and compare the complete graph with the accepted proposal. Use the existing
`check-relies.sh` for each body and `check-links.sh <spec>` for the full graph
as described in [tickets.md](tickets.md). Refusal stops approval.

Draw the read-back graph with issue numbers. Post it and the link report on the
spec, show that picture inline, and ask for approval of this exact graph using
the same questions where still open. Use [the decision procedure](records.md)
to post the `plan_approval` request. Explain that approval allows the fleet
to start eligible tickets after their blockers merge and to merge through
independent review. A changed spec goes back to confirmation.

## 4. Record the answer and hand off

A clear approval applies to this revision. On a requested change, update the
proposal and request approval again. Re-read the inputs, run both link checks,
and use `sh "<this skill's folder>/revision.sh" <spec>` for the current revision. Keep the
complete table, revision text and fingerprint.

Save and read back the exact approval in private first. Post its paraphrase,
date and private comment pointer with the revision. Read it back, compare the
current fingerprint and run `sh "<this skill's folder>/scripts/check-approval.sh" <spec>`.
Only then apply the approved ready labels, read them back and resolve the
request. Verify no held or extra ready ticket remains. A stale or
unverifiable record starts nothing.

Hand the verified plan to [launch-fleet](../launch-fleet/SKILL.md). Builders and
other-family reviewers stay independent, and the fleet owns exact-head checks
and merge. Jake's release go stays separate. End the turn while waiting.

## Licence

Adapted from Matt Pocock's `to-tickets` skill (github.com/mattpocock/skills).
Copyright (c) 2026 Matt Pocock

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
