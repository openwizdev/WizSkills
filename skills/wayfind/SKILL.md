---
name: wayfind
description: Chart an effort too big for one grill (many specs, even many versions, far out) as a map of the decisions it needs, and settle them one at a time until its designs are ready for to-spec and to-tickets. Use when a grill shows the effort is bigger than one grill, when asked to wayfind, or to work through an open map.
---

# Wayfind

Some efforts are too big for one grill: many specs, even many versions, far out. They arrive wrapped in fog: the way from here to the **destination** isn't visible yet. Wayfind charts that way as a **map** on GitHub, then settles its **questions** one at a time, until nothing is left to decide and `to-spec` and `to-tickets` can turn it into versions, specs and tickets. The orchestrator runs it, when a grill shows the effort is bigger than one grill, and grills the small parts as it goes.

- **Plan, don't do.** Each question settles a decision, and the map is done when the way is clear, with nothing left to decide. The pull to just do the work means you have reached the edge of the map: hand over to `to-spec` (see "When the way is clear"). Work starts only from a plan graph the user approves, never from the map.
- **Every decision is the user's, in a grill.** Research and prototypes only feed the grills. Never answer the user's side of a question yourself. Follow the project's open-development contract: save exact answers in the configured private repository; public answers and map entries give the decision in your own words, the date and a pointer to its private record comment. Publish no exact user words, thread ids, private files or links into them. If the private record cannot be saved or verified, ask the orchestrator before recording the decision.
- **Refer by name.** Every map and question is an issue, so it has a title. In everything the user reads, call it by its title, with its link inside the name (`[<title>](<url>)`), never by a bare number like `#42`.

## The map

The map is one GitHub issue for the whole effort, labelled `wayfind:map`, and each of its questions is a sub-issue of it. The map is an **index**, not a store: a decision lives in one place, its question, and the map gives it one line and a link.

Its body is the whole map at low resolution, read once per session. Open questions are not listed in it: they are its open sub-issues.

```markdown
## Destination

<what reaching the end of this map looks like: where the effort is heading, in one or two lines>

## Notes

<the domain; the skills every session should read; the user's standing preferences for this effort>

## Decisions so far

<!-- one line per settled question: enough to judge relevance; open the link for the detail -->

- [<question's title>](<link>): <the answer in one line>

## Not yet specified

<!-- the fog: in scope, but not sharp enough to ask yet -->

## Out of scope

<!-- ruled beyond the destination; never comes back -->
```

## Questions

Each question is a sub-issue of the map, small enough to settle in one session. Its body is the question alone:

```markdown
## Question

<the decision it settles, or the fact or the work a decision waits on>
```

- **Its kind is its label,** one of the four below; the body never says it. `wayfind:` labels are the only labels a map and its questions carry: never a ready label or any other triage label, so no fleet builds them. They are decisions, not work.
- **Blocking is GitHub's own "blocked by" link,** so each issue page shows what can be taken without opening the map. A question is unblocked when every question blocking it is closed.
- **A claim is a comment,** since every agent posts from the same GitHub account: `wayfind: claimed`, posted before any work. Capture the URL printed by `gh issue comment` and keep both that URL and its numeric comment id in private resumable state. The comment id is the positive decimal suffix after `#issuecomment-` in that URL, not the opaque GraphQL `id` field. Use that same decimal value in releases; never identify the holder publicly by thread. A claim stands until `wayfind: released <claim comment id>` names that exact claim. The reader below retains each comment's URL and body, so a release can be matched to the numeric id in the claim URL. Read comments in creation order: the earliest unreleased claim holds the question. If another claim holds it, release only your own comment id and take the next question. If you stop before settling it, release your own claim; if you lose its id, ask the orchestrator rather than releasing another holder's claim.
- **The frontier** is the open, unblocked, unclaimed questions: the edge of the known.
- **The answer is recorded when it is settled,** never in the body. Anything made while settling it is linked from the question, never pasted in.

| Label | Who | Settled by |
| --- | --- | --- |
| `wayfind:grill` | The user, with you. The default | A small grill with the user, with the `grill` skill: at most three questions a round, their exact words saved in the private repository's grill record. Its confirmed summary supplies the public decision, date and private-record pointer |
| `wayfind:research` | A fresh agent alone | A Cloud child thread you start, briefed "Read `skills/research/SKILL.md` and follow it" with the question. It reads the sources, reports on a branch as that skill says, and decides nothing. Claim the question as you start it, and record its report as the answer when the agent finishes. For a fact a decision waits on, from outside this repository |
| `wayfind:prototype` | The user, with you | A quick, rough, throwaway thing to react to (an outline, a mock, a stub), linked from the question, then shown to the user in a grill (the `grill` skill): save the exact reaction privately and record the decision, date and private-record pointer as the public answer. For how something should look or behave |
| `wayfind:task` | You alone where you can; otherwise the user | Work that must happen before a decision can be made, such as signing up for a service to judge its API, or getting access. Do it yourself where you can; otherwise give the user a precise checklist. Its answer records what was done and the facts later questions need. The one kind that does rather than decides |

## Fog and scope

The map is deliberately incomplete: don't chart what you can't see yet. Past the open questions lies the **fog**: decisions you can tell are coming but can't pin down yet, because they hang on questions still open. Write it down, as loosely or as fully as you can see it, under **Not yet specified**. Settling a question clears the fog ahead of it: what you can now ask precisely graduates into new questions, until the way to the destination is clear.

- **Question or fog?** The test is whether you can state the question precisely now, not whether you can answer it now. A sharp question is a question, even while it is blocked. Anything vaguer stays fog: don't cut the fog into question-sized pieces, since one patch may become several questions, or none.
- **Not yet specified holds only fog:** never what is decided (Decisions so far), what is already a question, or what is out of scope.
- **Out of scope is beyond the destination.** The destination fixes the scope, so work beyond it is not fog: it goes under **Out of scope** and never graduates. It comes back only if the destination is redrawn, and then as a fresh effort. When a question turns out to sit beyond the destination, close it, with a comment saying why, and add one line under Out of scope: the gist, why it is out, and its link. It stays out of Decisions so far, which records only the way walked.

## Chart the map

When a grill shows the effort is bigger than one grill, or the user brings a loose idea to wayfind.

1. **Name the destination.** Grill it with the user (the `grill` skill): what this map is finding its way to. The destination fixes the scope, so it is settled first.
2. **Map the frontier.** Grill again, breadth-first: across the whole space rather than deep on any one thread, for the open decisions and the questions you can ask now. If this shows no fog (the way is already clear, and the effort fits one grill after all), you don't need a map: stop, and ask the user how they want to go on.
3. **Create the map** (label `wayfind:map`): Destination and Notes filled in, Decisions so far empty, the fog sketched under Not yet specified.
4. **Create the questions you can state now,** each a sub-issue of the map with its label, then add their "blocked by" links in a second pass, since issues need numbers before they can point at each other. Write cross-references in that pass too, with real numbers: a placeholder like `#<n>` links to an unrelated issue.
5. **Put the map on the roadmap:** one Later line in the project's roadmap, linking the map. It stays until the map's versions are numbered, and they replace it.
6. **Start the research.** For each `wayfind:research` question, claim it and start its fresh agent now, all of them in parallel.
7. **Stop.** Charting is one session's work: it settles nothing else by hand.

Done when the map and its questions are on GitHub with their labels and links, the roadmap has the map's line, and every research question has its agent.

## Work through the map

When the user or the orchestrator names a map (its link or number), and perhaps one of its questions. Without a question, you pick the next one.

1. **Load the map:** its body, the low-resolution view, not every question.
2. **Choose and claim.** Take the question named, or else the first frontier question in order. Claim it before any work, then read its comments back: if an earlier claim still stands, release yours and take the next.
3. **Settle it** as its label says (the table in "Questions"); read the label, since the body never says the kind. Open any related or closed question in full as you need it, and read the skills the map's Notes name.
4. **Record it:** post the public-safe answer as a comment on the question. For a user decision, give the decision, date and private-record pointer; link public research or synthetic prototypes directly, but use a private-record comment pointer for private material. Close the question and add its one line, linked, to Decisions so far.
5. **Redraw the map.** Add the questions the answer surfaced (create, then link); graduate any fog it made specific, deleting that patch from Not yet specified so it lives only as its new questions; rule out of scope any question it shows sits beyond the destination; and change, or close with a comment saying why, any question the decision makes wrong.

**One question per session,** except research, which runs in parallel. Other sessions may be changing the map at the same time: read its body again right before you edit it.

Done when the answer is on the question, the question is closed, and the map shows its line and the redrawn fog.

## When the way is clear

When no question is open and nothing is left under Not yet specified, the map is clear. Hand it to `to-spec`, never straight to building: its Decisions so far link every grill it rests on. `to-spec` writes the specs across as many versions as needed. Once confirmed, `to-tickets` puts their tickets in the plan graph with real arrows to the exact tickets they need, in any version.

## Commands

GitHub CLI 2.94 or later (`docs/agents/issue-tracker.md` has the rest). Write every body of more than one line to a file first.

```sh
# Once per repository: the five labels
gh label create wayfind:map --description "Wayfind: the map of one effort"
gh label create wayfind:grill --description "Wayfind question: a grill with the user"
gh label create wayfind:research --description "Wayfind question: a fact, found by a research agent"
gh label create wayfind:prototype --description "Wayfind question: a throwaway prototype to react to"
gh label create wayfind:task --description "Wayfind question: work a decision waits on"

# The map, a question under it, then its blockers in a second pass
gh issue create --title "<the effort>" --label wayfind:map --body-file map.md
gh issue create --title "<the question>" --label wayfind:grill --parent <map> --body-file question.md
gh issue edit <question> --add-blocked-by <blocker>    # once for each blocker

# The frontier: the map's open questions, then each one's label, open blockers and claim comments
gh issue view <map> --json subIssues --jq '.subIssues.nodes[] | select(.state == "OPEN") | .number'
gh issue view <question> --json labels,blockedBy,comments --jq '{labels: [.labels[].name], open_blockers: [.blockedBy.nodes[] | select(.state == "OPEN") | .number], claims: [.comments[] | select(.body | startswith("wayfind: ")) | {url, body}]}'

# Claim, release, and settle: the answer as its own comment, then the close
# Save the printed claim URL and its numeric #issuecomment- suffix before working.
# Replace <claim comment id> with that same decimal id when releasing your claim.
gh issue comment <question> --body "wayfind: claimed"
gh issue comment <question> --body "wayfind: released <claim comment id>"
gh issue comment <question> --body-file answer.md
gh issue close <question>

# The map's body: read it again right before each edit
gh issue view <map> --json body --jq '.body' > map.md
gh issue edit <map> --body-file map.md
```

## Licence

Adapted from Matt Pocock's `wayfinder` skill (`github.com/mattpocock/skills` @ `4ae2317`), which carries this notice:

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
