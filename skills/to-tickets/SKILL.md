---
name: to-tickets
description: Split a spec into sized tickets and check the plan. Use when to-spec hands over a spec or when an existing ticket plan needs revision.
version: 0.4.0
---

# To tickets

Take a [to-spec](../to-spec/SKILL.md) spec through machine plan approval (J202)
with no owner question or human approval.

## 1. Check the starting point

Run `python3 -I "<this skill's folder>/../launch-fleet/scripts/context.py" planner`
once per session and after a listed blob changes. Before writing, verify the
configured tracker with `gh repo view --json nameWithOwner`. Stop on a mismatch.
Verify the grill confirmation privately or return to [grill](../grill/SKILL.md).
[Hold an approved plan before editing](changes.md). Keep existing contract holds'
release conditions. A failed read or unknown state stops its write or handoff.

## 2. Cut the tickets

Cut end-to-end `Size: S.` tickets (~200 changed lines, ≤10 files). For new specs,
`approve.py` refuses `L` and requires `Why M:` in Parent for `M` (~400 lines).
Cut flat (F6): shortest critical chain, then widest graph, disjoint owned paths,
and only needed arrows. Use contract-first blockers for interface-only reliance.
Explain shared interfaces without one. Ordering alone earns no arrow. Step 4
requires `Why deep:` in the spec for a chain over 5,
or over 3 and over 2/3 of the open tickets.
Compare picture data with
`python3 -I "<this skill's folder>/scripts/prefer.py" <cut A> <cut B>`.
Check size and what to merge or split. See [tickets.md](tickets.md).

## 3. Write and verify the tickets

Run [fidelity.md](../to-spec/fidelity.md) before creating or
showing tickets (drop, fix, or explain in one line). Create each issue without
a ready label, blockers first, with the spec milestone, native parent and
blockers. Read each back. Post the agents' graph on the spec using
`python3 -I "<this skill's folder>/scripts/picture.py" < graph.json > picture.md`.

## 4. Approve by the checks

```sh
sh "<this skill's folder>/check-links.sh" --read <spec> > graph.json
sh "<this skill's folder>/revision.sh" <spec> > revision.txt
gh issue view <spec> --json body,createdAt > spec.json
python3 -I "<this skill's folder>/scripts/approve.py" --graph graph.json --revision revision.txt --spec spec.json \
  --grill <confirmation URL> --number <N> [--changed "<what changed>"] --root . > record.md
```

`N` is 1 for the first approval, otherwise the latest revision plus one.
`approve.py` requires `--changed` for successors. Exit 0 writes `record.md`.
Fix and rerun on 1 and re-read on 2
([decisions.v1](../../contracts/decisions.v1.md#machine-plan-approval)).

As a record author, post `gh issue comment <spec> --body-file record.md` and
verify the bytes. Read comments before retrying an uncertain write. Then apply
and read back each row's ready label.

## 5. Hand off

[launch-fleet](../launch-fleet/SKILL.md) starts from machine approval. Hand back
to to-spec for the steering video. Builders and other-family reviewers stay
independent. The fleet owns exact-head checks and merge. Measure spec lead time with
`python3 -I "<this skill's folder>/scripts/lead_time.py" <collector JSON> --spec <spec>`.
Planning and machine approval grant no `fleet.md` Approval rule (each asks its
named approver first; default: publishing, spending, secrets, deleting user
data, cut-overs, webhook ask the user); the owner's release go stays. Older
human-approved plans and standalone approvals follow [records.md](records.md)
and must pass `sh "<this skill's folder>/scripts/check-approval.sh" <spec>`
before labelling. End the turn while waiting.

Credit: adapted from Matt Pocock's skills under the MIT License; the notice and sources are in [NOTICE.md](NOTICE.md).
