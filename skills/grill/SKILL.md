---
name: grill
description: Map the decision tree and settle it one question at a time. Use when asked to grill, before an unsettled plan, to resume a grill, or when a builder grills a spec alone.
version: 0.2.2
---

# Grill

Settle the design before anyone plans or builds. Map every decision from
the repo first. The user makes the decisions. A grill gives no authority to
plan, start tickets, build or review until the user accepts the latest summary.

## Start or resume

1. Run `python3 -I "<this skill's folder>/../launch-fleet/scripts/context.py" planner`
   once per session (again only when a blob its header lists changes). Use what
   it prints. Exact replies still go in a private comment first. Read a
   `GLOSSARY.md` term only when you use it, and an ADR only in the area it
   touches. The card's decision-record forms replace the open-development
   contract for public decision records; read the full contract only for
   release, publishing, importer and ticket-mover work. Verify the private
   repository's visibility and the checkout's remote before any write. Stop
   if either is unverified. Keep the grill, its branch, PR, exact replies and
   requests there. Before the first save, read
   [recording and recovery](references/records.md).
2. From the private checkout, run `sh <skill-directory>/scripts/index.sh`. Read
   related grills and check open private PRs for unmerged files. Resume the
   matching grill from its last saved round, tree and pending decisions. Otherwise
   use the [file template](assets/grill.md) to create one private file, branch
   and PR. Keep the shared index untouched.
3. For a version grill, create or reuse its named development-tracker milestone
   on the day the grill starts. Use the project's tracker instructions.

Start is complete when the private file, index row, PR and any required
milestone exist.

The orchestrator also brings the next grill the same day the project's board
reports low stock. Use the [ready-stock and fed-ratio rules](../../contracts/plan-links.v1.md)
if counting from the tracker. The orchestrator can bring several grills for a
large gap. Builder limits and approval gates still apply.

## Map, then ask

Before any question, read the code, docs, tickets, glossary and ADRs the
feature touches. Write the decision tree in the private file: every decision,
what it depends on, and what it unblocks. Record as settled, with the source,
anything those files already decide. Ask only what they leave open.

The frontier is the open decisions whose prerequisites are settled. One
substantive question per round, the one that unblocks the most: a stable ID,
plain context, options, consequences, and one recommendation on its own
➡️ line so "yes" accepts it. A dependent of a question still open waits.
Trivial confirmations may share a round, at most three, when none changes a
dependency. Continue until no frontier decision remains. The install's first
fleet may set a shorter cap; name the remainder and leave it unsettled.

An ambiguous term gets one agreed name before reuse, including a clash with
`GLOSSARY.md`, saved under Glossary. A question only a prototype can answer
goes under Parked, with why, and stays undecided.

Save each round as [recording and recovery](references/records.md) describes,
show that saved round, and wait. A skip or an ambiguous "yeah" stays open.
"simplify" keeps the ID and context and is asked more plainly. Answer a
question back before the next round. On a conflict, ask which meaning stands.
A project term or hard-to-reverse decision follows the glossary and ADR steps
there. Recompute the frontier after the saved reply.

Read [coordination](references/coordination.md) before several grills in one
message, new IDs beside another grill, or parking and resuming. A parked grill
is the user stopping. The Parked list is prototype questions in an open grill.

## Fleet mode

With no person in the chat, and an orchestrator, ticket or spec as the
counterpart, invent no answer. Keep what the spec, ticket, glossary, ADRs and
code already decide. Record the rest unresolved, recommendation not settled,
status open: in the private file when that checkout verifies, otherwise as a
public-safe ticket comment. Do not confirm or start [to-spec](../to-spec/SKILL.md).

## Exit check

Ask the next question unless every branch has a source or a saved answer,
every term in play has one Glossary name, every prototype question is under
Parked and undecided, and the frontier is empty.

Then save a summary of at most ten numbered decisions, parked items included
as undecided, and publish its confirmation request as recording and recovery
describes. Show it and ask whether you are aligned. Save the exact reply
first. A correction needs a new summary and request. A new decision reopens
the rounds.

Confirm only on an explicit acceptance of the latest summary with nothing
open. The install's first fleet may accept a short summary that names an
unasked remainder; that yes covers only that short grill. Then confirm, push,
resolve the request, and merge by the project's rules or ask the user to
merge. Hand the merged record to [to-spec](../to-spec/SKILL.md), which copies
the Glossary, decision tree, Parked list and summary into the spec. Builders
use those names and leave parked items unbuilt. Spec confirmation and plan
approval stay separate, and builders and reviewers stay independent.

Credit: adapted from Matt Pocock's skills under the MIT License; the notice and sources are in [NOTICE.md](NOTICE.md).
