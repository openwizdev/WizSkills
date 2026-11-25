---
name: to-tickets
description: Split a spec into sized tickets and check the plan. Use when to-spec hands over a spec or when an existing ticket plan needs revision.
version: 0.4.0
---

# To tickets

The orchestrator takes a spec from [to-spec](../to-spec/SKILL.md) to a plan
approved by its own checks (J202): no owner question or human approval between.

## 1. Check the starting point

Run `python3 -I "<this skill's folder>/../launch-fleet/scripts/context.py" planner`
once per session (rerun only when a listed blob changes). Read the grill
confirmation comment back privately; no confirmed grill stops and returns to
[grill](../grill/SKILL.md). If already approved, [hold before editing](changes.md);
existing contract holds keep their release conditions. A failed read or unknown
state stops the write or handoff it would authorize.

## 2. Cut the tickets

Cut end-to-end builder tickets to `Size: S.` (~200 changed lines, `<=10` files);
`approve.py` refuses `L` and any `M` (~400 lines) without `Why M:` in Parent.
Cut for shortest critical chain then widest graph (F6) with disjoint owned
paths; compare two cuts with
`python3 -I "<this skill's folder>/scripts/prefer.py" <cut A> <cut B>`. Use a
contract-first ticket for a shared interface, or say why none is needed. See
[tickets.md](tickets.md).

## 3. Write and verify the tickets

Run [fidelity.md](../to-spec/fidelity.md) on the drafted set before creating or
showing tickets (drop, fix, or explain kept items in one line). Create each
issue without a ready label, blockers first, in the spec's milestone, with
native parent and blockers, then read back every issue. Draw and post the graph
on the spec (agents' document, never the owner's) with
`python3 -I "<this skill's folder>/scripts/picture.py" < graph.json > picture.md`.

## 4. Approve by the checks

```sh
sh "<this skill's folder>/check-links.sh" --read <spec> > graph.json
sh "<this skill's folder>/revision.sh" <spec> > revision.txt
gh issue view <spec> --json body,createdAt > spec.json
python3 -I "<this skill's folder>/scripts/approve.py" --graph graph.json --revision revision.txt --spec spec.json \
  --grill <confirmation URL> --number <N> [--changed "<what changed>"] --root . > record.md
```

Exit 0 prints `record.md` (exit 1: fix and rerun; exit 2: re-read);
`approve.py` checks the plan and requires `--changed` when `N > 1`
([decisions.v1](../../contracts/decisions.v1.md#machine-plan-approval)).

Post `record.md` with `gh issue comment <spec> --body-file record.md` as a
record author, read it back byte for byte (on uncertain writes, read comments
before retrying), then apply each row's ready label and read labels back.

## 5. Hand off

[launch-fleet](../launch-fleet/SKILL.md) starts the fleet from the machine
approval; hand back to to-spec for the steering video. Builders and other-family
reviewers stay independent; the fleet owns exact-head checks and merge. Measure
spec lead time with
`python3 -I "<this skill's folder>/scripts/lead_time.py" <collector JSON> --spec <spec>`.
Planning and machine approval grant no `fleet.md` Approval rule (each asks its
named approver first; default: publishing, spending, secrets, deleting user
data, cut-overs, webhook ask the user); the owner's release go stays. Older
human-approved plans and standalone approvals follow [records.md](records.md)
and must pass `sh "<this skill's folder>/scripts/check-approval.sh" <spec>`
before labelling. End the turn while waiting.

Credit: adapted from Matt Pocock's skills under the MIT License; the notice and sources are in [NOTICE.md](NOTICE.md).
