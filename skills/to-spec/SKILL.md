---
name: to-spec
description: Turn a confirmed grill into a spec issue. Use when a grill is confirmed or the owner steers an existing spec.
version: 0.4.0
---

# To spec

The owner confirms the grill (J202), then steers. The orchestrator writes the
spec, runs [to-tickets](../to-tickets/SKILL.md) for machine approval and makes
the steering video.

## 1. Read the confirmed grill

Run `python3 -I "<this skill's folder>/../launch-fleet/scripts/context.py" planner`
once per session and after a listed blob changes. Read the grill and its
confirmation privately, plus the glossary, decision tree, parked list and code.
Carry the glossary, decision tree and parked list into the spec in public-safe form.
Return open decisions or an unconfirmed grill to [grill](../grill/SKILL.md).
Keep the confirmation URL for plan approval. Stop the affected write on an
unclear read or missing publication approval.

## 2. Write the spec

`gh repo view --json nameWithOwner` must match the configured tracker before a write.
Use [spec.md](spec.md) for outcome, proof and seams. Take the grill headline
(`none` for infra) and version milestone (create if needed). Omit ticket labels.
Run [fidelity.md](fidelity.md) before creating or showing the spec (drop, fix,
or explain in one line). Create and read back. On resume, verify uncertain
writes before retrying. [Hold an approved plan first](../to-tickets/changes.md).

Confirm both [checkpoint answers](../../contracts/checkpoints.v1.md) from the
grill with the spec:

```text
## Checkpoints

- One-way door: yes
- User-visible: no
```

Default is `yes` / `no` (early only). Use `User-visible: yes` (or
`yes, a release`) and `One-way door: no` only when settled; `approve.py`
refuses missing or malformed lines.

## 3. Cut the plan

Run [to-tickets](../to-tickets/SKILL.md) with the confirmation URL for machine
approval. Fix and re-check refusals without returning to the owner.

## 4. Make the steering video

Skip this step for the install's first fleet, and only for it: when the install
skill's plan step runs you for that fleet, the spec gets no video and the launch
follows the machine plan approval straight away. A reset or change of that spec or
plan gets a new machine approval and still no video: for this fleet that
replaces step 5's new video. Every other spec gets its video.

Show user and code changes in one animatic, in the grill's words, in build order
(step 1 first). Write `storyboard.json` outside any repo ([video.md](video.md)).

- `node "<this skill's folder>/scripts/animatic.mjs" build storyboard.json -o spec.mp4`;
  read `build/sheet.png` until it reads right and ends `no warnings`.
- Host the MP4 with the issue's visibility (public sharing needs publication
  authority), confirm playback, then get the link line via
  `node "<this skill's folder>/scripts/animatic.mjs" link "$url"`.
- Post as a spec comment, never in the body: the link, then `Steering by comment is off for now: tell your orchestrator what to change (stop, reset, or anything else).`

## 5. Steer

Until OpenWiz #1402 the owner steers through their orchestrator. Stop holds the fleet.
Reset re-cuts via [changes.md](../to-tickets/changes.md) and makes a new video.
Act on other steers. A changed spec or plan gets fresh machine approval and video.

Planning grants only what the machine approval records, never `fleet.md`'s
Approval rules (each asks its named approver first; default: publishing,
spending, secrets, deleting user data, cut-overs, webhook ask the user).
Builders and other-family reviewers stay independent; starting, reviewing and
merging stay with their roles.

Credit: adapted from Matt Pocock's skills, the video from his `animatic` skill, under the MIT License; the notice and sources are in [NOTICE.md](NOTICE.md).
