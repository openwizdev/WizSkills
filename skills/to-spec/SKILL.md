---
name: to-spec
description: Turn a confirmed grill into a spec issue. Use when a grill is confirmed or the owner steers an existing spec.
version: 0.4.0
---

# To spec

The owner's one active step is confirming the grill (J202). From there the
orchestrator writes the spec, has [to-tickets](../to-tickets/SKILL.md) cut and
approve the plan by its own checks, and makes one steering video; nothing is
asked between them.

## 1. Read the confirmed grill

Run `python3 -I "<this skill's folder>/../launch-fleet/scripts/context.py" planner`
once per session (rerun only when a listed blob changes). Read the grill and
confirmation comment privately, plus the code; an unconfirmed grill or open
decision returns to [grill](../grill/SKILL.md). Keep the confirmation URL as
the plan approval's authority. An unclear read or publication approval stops
the related write.

## 2. Write the spec

Use [spec.md](spec.md): name outcome, proof and seams; headline from the grill
or `none` for infra; use the grill's version milestone (create if missing); no
ticket label. Run [fidelity.md](fidelity.md) before creating or showing it
(drop, fix, or explain kept items in one line). Create, read back, and on
resume confirm uncertain writes before retrying. For an already approved plan,
use [changes.md](../to-tickets/changes.md) first.

Every spec carries its two checkpoint answers
([checkpoints.v1](../../contracts/checkpoints.v1.md)), filled from the grill and
confirmed with the spec:

```text
## Checkpoints

- One-way door: yes
- User-visible: no
```

Default is `yes` / `no` (early only). Use `User-visible: yes` (or
`yes, a release`) and `One-way door: no` only when settled; `approve.py`
refuses missing or malformed lines.

## 3. Cut the plan

Run [to-tickets](../to-tickets/SKILL.md) with the grill confirmation URL. It
ends with a machine plan approval or fixes and re-checks refusals without
returning to the owner.

## 4. Make the steering video

Skip this step for the install's first fleet, and only for it: when the install
skill's plan step runs you for that fleet, the spec gets no video and the launch
follows the machine plan approval straight away. A reset or change of that spec or
plan gets a new machine approval and still no video: for this fleet that
replaces step 5's new video. Every other spec gets its video.

One animatic in build order (step 1 starts first), in the grill's words, showing
user and code changes. Write `storyboard.json` outside any repo
([video.md](video.md)), then:

- `node "<this skill's folder>/scripts/animatic.mjs" build storyboard.json -o spec.mp4`;
  read `build/sheet.png` until it reads right and ends `no warnings`.
- Host the MP4 with the issue's visibility (public sharing needs publication
  authority), confirm playback, then get the link line via
  `node "<this skill's folder>/scripts/animatic.mjs" link "$url"`.
- Post as a spec comment, never in the body: the link, then `Steering by comment is off for now: tell your orchestrator what to change (stop, reset, or anything else).`

## 5. Steer

Steering by comment is off for now (until OpenWiz #1402), so the owner steers
through their orchestrator: stop holds the fleet, reset re-cuts via
[changes.md](../to-tickets/changes.md) and makes a new video, anything else is
a steer to act on. A changed spec or plan always gets a new machine approval
and new video.

Planning grants only what the machine approval records, never `fleet.md`'s
Approval rules (each asks its named approver first; default: publishing,
spending, secrets, deleting user data, cut-overs, webhook ask the user).
Builders and other-family reviewers stay independent; starting, reviewing and
merging stay with their roles.

Credit: adapted from Matt Pocock's skills, the video from his `animatic` skill, under the MIT License; the notice and sources are in [NOTICE.md](NOTICE.md).
