---
name: to-tickets
description: Split a spec into sized tickets and check the plan. Use when to-spec hands over a spec or when an existing ticket plan needs revision.
version: 0.4.0
---

# To tickets

The orchestrator takes a spec from [to-spec](../to-spec/SKILL.md) to a plan
approved by its own checks (J202): no owner question and no human approval in
between. In OpenWiz,
[the roads page](https://github.com/openwizdev/OpenWiz/blob/main/docs/agents/roads.md)
describes when this road applies.

## 1. Check the starting point

Run `python3 -I "<this skill's folder>/../launch-fleet/scripts/context.py" planner`
once per session (and again only when a blob its header lists changes). It prints
the public-writes card, the planner's fleet sections, the tracker's
where-things-live and repositories, the triage labels table, the private storage
rules, the roads page and the glossary's term index. Read a term's definition in
`GLOSSARY.md` only when you use it, and an ADR only when it touches the area.
The card's decision-record forms replace reading the open-development contract
for public decision records; read the full contract only for release, publishing,
importer and ticket-mover work. You need the spec and its grill confirmation's
private-comment URL; read that comment back privately. No confirmed grill: stop
and use [grill](../grill/SKILL.md). If the plan was already approved,
[hold before editing](changes.md). Existing contract holds keep their recorded
release conditions.

Keep exact owner replies and private sources private. Verify tracker and private
repository before writing. A failed read or unknown state stops the write or
handoff it would authorize.

## 2. Cut the tickets

Cut end-to-end builder tickets to an expected diff of about 200 changed lines
and 10 files or fewer, judged from first-pass review results on comparable work:
that range is `Size: S.` (this revises openwizdev/OpenWiz#2484's RR2, which set
about 400). An M is about 400. Size M is allowed only with a
`Why M: <reason it can't split>` line in Parent. A ticket of size L is split,
never cut. For a spec created on or after approve.py's `SIZES_SINCE`, step 4
refuses an L, and an M without that line. Cut flat (F6): the shortest critical
chain, then the widest graph; disjoint owned paths; only the arrows a ticket
truly needs. A ticket that needs only another's interface waits on a
contract-first ticket; ordering never justifies an arrow. Step 4 needs a spec
`Why deep:` line for a chain over 5, or over 3 and over 2/3 of the open tickets.
Compare cuts as picture data with
`python3 -I "<this skill's folder>/scripts/prefer.py" <cut A> <cut B>`: it keeps
the shorter chain, then the wider graph. Ask of each ticket: right size, merge
or split? See [the ticket and graph inputs](tickets.md).

## 3. Write and verify the tickets

Before you create or show the tickets, run the
[fidelity pass](../to-spec/fidelity.md) on the whole drafted set: drop or fix
each item, or keep it and tell the user why in one line.
Create each issue without a ready label, blockers first, in the spec's
milestone, with its native parent and blockers. Read back every issue: title,
body, parent, milestone, labels and blockers. Draw the read-back graph with
`python3 -I "<this skill's folder>/scripts/picture.py" < graph.json > picture.md`
and post it on the spec: the graph is the agents' document, never the owner's.

## 4. Approve by the checks

```sh
sh "<this skill's folder>/check-links.sh" --read <spec> > graph.json
sh "<this skill's folder>/revision.sh" <spec> > revision.txt
gh issue view <spec> --json body,createdAt > spec.json
python3 -I "<this skill's folder>/scripts/approve.py" --graph graph.json --revision revision.txt --spec spec.json \
  --grill <confirmation URL> --number <N> [--changed "<what changed>"] --root . > record.md
```

Exit 0 prints the record, whose `width: chain` is the critical chain: the
longest run of open work, open blockers outside the spec included
([decisions.v1](../../contracts/decisions.v1.md#machine-plan-approval)).
Exit 1 names each failed check and prints nothing: fix the tickets, then run all
three again. Exit 2 is an unreadable input: read again. `N` is 1, or the latest
approval's revision plus one with `--changed`.

Post `record.md` with `gh issue comment <spec> --body-file record.md` as a
record author, read it back and compare it byte for byte. On an uncertain write,
read the comments before retrying. Only then apply each row's ready label (the
project's label for that role) and read the labels back.

## 5. Hand off

[launch-fleet](../launch-fleet/SKILL.md) starts the fleet from the machine
approval. Hand back to to-spec for the steering video. Builders and
other-family reviewers stay independent, and the fleet owns exact-head checks
and merge. The plan's outcome is the spec's lead time, from the spec's creation
to its last ticket's merge, for the war room:
`python3 -I "<this skill's folder>/scripts/lead_time.py" <collector JSON> --spec <spec>`
reads the collector's `flow` fact and keeps unknown unknown. Every rule in
`fleet.md`'s Approval rules asks its named approver first; with no such section,
publishing, spending, secrets, deleting user data, cut-overs and the repository
webhook ask the user. Planning and a machine approval grant no rule, and the
owner's release go stays as it is. Older human-approved plans and approvals on their own follow [records.md](records.md); before
labelling one, `sh "<this skill's folder>/scripts/check-approval.sh" <spec>` must
validate its posted table. End the turn
while waiting.

Credit: adapted from Matt Pocock's skills under the MIT License; the notice and sources are in [NOTICE.md](NOTICE.md).
