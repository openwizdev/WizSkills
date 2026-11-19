---
name: to-spec
description: Turn a confirmed grill into a spec issue and a short narrated video for the owner's confirmation. Use when the design is settled and the user asks for a spec. A confirmed spec goes to to-tickets.
version: 0.2.0
---

# To spec

The orchestrator takes a confirmed design to a confirmed spec. In OpenWiz,
[the roads page](https://github.com/openwizdev/OpenWiz/blob/main/docs/agents/roads.md)
describes when this road applies.

## 1. Read the settled design

Read the consumer project's tracker, domain and fleet settings in `docs/agents/`.
Read the confirmed grill privately, the glossary, relevant ADRs and the code.
If a decision is still open, return to [grill](../grill/SKILL.md) before writing.
Use the earliest user-facing seams that can prove the design.

Keep exact replies, grill sources, thread IDs and private media in private
storage. Verify the private records repository and development tracker before
writing. Save public-safe summaries, issue text and visuals in public. An
unclear read or publication approval stops the related write.

## 2. Write and show the spec

Use the [spec template](spec.md). Name the outcome, proof and seams the owner
will confirm. Set the headline to `none` for infra. Use the grill's version
milestone, creating it if applicable and missing. Give the spec no ticket label.

Build a short animatic with a simple slide and brief narration per beat.
Cover the problem, the proposed experience and how the proof will work. Use
existing local audio or authorized narration, and keep exact private replies
out of both slides and speech. See [the scene input](video.md).

- `python3 -I "<this skill's folder>/scripts/video.py" render scenes.json spec.mp4` assembles
  local slides and narration. Check the picture and sound before sharing.
- Put the MP4 in an approved location the owner can play with the issue's
  visibility. Public sharing needs publication authority. Confirm playback
  there. `python3 -I "<this skill's folder>/scripts/video.py" link "$url"` gives one Markdown
  line for the issue. Fix a refusal before filing it.

Create the spec issue with the video link in its body and read it back. On a
resume, confirm any uncertain issue or media write before retrying. For an
already approved graph, use [the hold-first procedure](../to-tickets/changes.md)
before updating the spec.

## 3. Record the owner's confirmation

Show the issue and up to ten summary lines including the exact headline. Ask
the owner to confirm. Use [the decision procedure](../to-tickets/records.md)
to post a `spec_confirmation` request. A correction supersedes that request
before you show a replacement.

Wait for a clear confirmation. Save and read back the exact answer in the
verified private comment. Publish the paraphrased `Spec confirmed by` comment
with its date and pointer, read it back, then resolve the request. Leave the
request open when a reply or write is uncertain.

Done when the current issue links the playable video and has verified owner
confirmation. Hand that issue to [to-tickets](../to-tickets/SKILL.md).
Planning grants only the authority recorded at each gate. Keep builders and
other-family reviewers independent and leave starting, reviewing and merging
to their assigned roles.

Credit: adapted from Matt Pocock's skills under the MIT License; the notice and sources are in [NOTICE.md](NOTICE.md).
