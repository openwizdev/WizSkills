---
name: to-spec
description: Turn a confirmed grill into a spec issue, run to-tickets on it, and make the spec's narrated steering video. Use when a grill is confirmed or the owner steers a spec through the orchestrator. No human step between grill and fleet.
version: 0.4.0
---

# To spec

The owner's one active step is answering and confirming the grill (J202). From
there the orchestrator writes the spec, has [to-tickets](../to-tickets/SKILL.md)
cut and approve the plan by its own checks, and makes one video the owner
watches, then steers through the orchestrator. Nothing is asked between them.
In OpenWiz,
[the roads page](https://github.com/openwizdev/OpenWiz/blob/main/docs/agents/roads.md)
describes when this road applies.

## 1. Read the confirmed grill

Run `python3 -I "<this skill's folder>/../launch-fleet/scripts/context.py" planner`
once per session (and again only when a blob its header lists changes). It prints
the public-writes card, the planner's fleet sections, the tracker's
where-things-live and repositories, the triage labels table, the private storage
rules, the roads page and the glossary's term index. Read a term's definition in
`GLOSSARY.md` only when you use it, and an ADR only when it touches the area.
The card's decision-record forms replace reading the open-development contract
for public decision records; read the full contract only for release, publishing,
importer and ticket-mover work. Read the grill privately, with its confirmation
comment, and the code. An unconfirmed grill, or a decision still open, goes back
to [grill](../grill/SKILL.md). Keep the confirmation's private-comment URL: it is
the plan approval's authority.

Keep exact replies, grill sources, thread IDs and private media in private
storage. Verify the private records repository and development tracker before
writing. Save public-safe summaries, issue text and visuals in public. An
unclear read or publication approval stops the related write.

## 2. Write the spec

Use the [spec template](spec.md). Name the outcome, proof and seams. Take the
headline from the grill's words, or `none` for infra. Use the grill's version
milestone, creating it if missing. Give the spec no ticket label. Create it,
read it back, and on a resume confirm any uncertain write before retrying. For
an already approved plan, use [the hold-first procedure](../to-tickets/changes.md)
before changing the spec.

Every spec carries its two checkpoint answers
([checkpoints.v1](../../contracts/checkpoints.v1.md)), filled from the grill and
confirmed with the spec, in this section:

```text
## Checkpoints

- One-way door: yes
- User-visible: no
```

Early only (`yes`, `no`) is the default. Write `User-visible: yes` when users
will see the change, `yes, a release` when the spec publishes a release, and
`One-way door: no` only when the grill settled that it can be undone. Reasons
go in other sections, never on these lines. to-tickets' approval check refuses
a spec created on or after its `CHECKPOINTS_SINCE` date without both answers;
an older spec without the section reads as early only.

## 3. Cut the plan

Run [to-tickets](../to-tickets/SKILL.md) on the spec now, with the grill
confirmation's URL. It ends with a machine plan approval on the spec, or a
refusal it fixes and re-checks. It never comes back to the owner.

## 4. Make the steering video

Skip this step for the install's first fleet, and only for it: when the install
skill's plan step runs you for that fleet, the spec gets no video and the launch
follows the machine plan approval straight away. A reset or change of that spec or
plan gets a new machine approval and still no video: for this fleet that
replaces step 5's new video. Every other spec gets its video.

One animatic: what changes for a user and in the codebase, in the grill's
words, in build order (step 1 is what starts first in the approved plan). No
bench and no ticket graph: the graph stays on the spec as the agents' document.
Write `storyboard.json` in a work folder outside any repo, as
[video.md](video.md) says, then:

- `node "<this skill's folder>/scripts/animatic.mjs" build storyboard.json -o spec.mp4`
  checks the storyboard first and renders nothing on a refusal: fix the lines
  it names. Read `build/sheet.png`; done when it reads right and the report ends
  `no warnings`.
- Put the MP4 where the owner can play it with the issue's visibility. Public
  sharing needs publication authority. Confirm playback there, then
  `node "<this skill's folder>/scripts/animatic.mjs" link "$url"` gives the line.
- Post it as a spec comment, never in the body (that would change the plan's
  fingerprint): the link, then `Steering by comment is off for now: tell your orchestrator what to change (stop, reset, or anything else).`

## 5. Steer

Steering by comment is off for now (until OpenWiz #1402), so the owner steers
through their orchestrator: stop holds the fleet, reset re-cuts the plan through
[the hold-first procedure](../to-tickets/changes.md) and makes a new video, and
anything else is a steer to act on. A changed spec or plan always gets a new
machine approval and a new video.

Planning grants only what the machine approval records, and no approval rule:
every rule in `fleet.md`'s Approval rules asks its named approver first; with no
such section, publishing, spending, secrets, deleting user data, cut-overs and
the repository webhook ask the user.
Builders and other-family reviewers stay independent; starting, reviewing and
merging stay with their roles.

Credit: adapted from Matt Pocock's skills, the video from his `animatic` skill, under the MIT License; the notice and sources are in [NOTICE.md](NOTICE.md).
