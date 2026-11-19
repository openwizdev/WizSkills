---
name: grill
description: Grill the user on a design in rounds of three plain questions, each with a recommendation, and save every question and exact reply to the private repository after every round. Use before a version, spec or skill is planned, when the user asks to grill, or to resume an open grill.
---

# Grill

Interview the user until a design is settled, at most three questions at a time, and write down every word as you go, so a fresh session (or `to-spec`, which plans from it) can carry on without the chat. You find the facts; the user makes every decision. The grill is done only when the user confirms its summary.

## Where things go

Read the development and private repositories from `docs/agents/issue-tracker.md` and their paths from `docs/agents/domain.md`. Verify the private remote and its private visibility before writing any grill. Run private Git operations and the index from that private checkout; explicitly target its repository on every grill PR/comment operation. Unknown visibility or missing private settings stops private writes; use existing settings before asking for a missing location. Public glossary/ADR work uses the development checkout. The version milestone stays on the development tracker.

| What | Where |
| --- | --- |
| The grill itself | In the private repository only: `docs/grills/<date>-<topic>.md`, one file per grill, for example `docs/grills/2026-10-30-fleets-0.0.5.md`. `<date>` is the day it starts; `<topic>` is a few lowercase words joined by hyphens |
| The index | In the private checkout, printed by [`scripts/index.sh`](scripts/index.sh), in this skill's own folder (wherever the skill is installed, a plugin's folder included), from each grill file's status line: every grill in the tree it runs on, whether it is open, parked or confirmed, and what it feeds (on the main branch, the merged grills; an open grill shows on its own branch and in its pull request). Nobody writes it by hand, so no grill's pull request touches a shared file; `docs/grills/README.md` says how to print it |
| New terms | The glossary: `GLOSSARY.md` at the root, unless `docs/agents/domain.md` names another |
| Hard-to-reverse decisions | ADRs (one short file per decision) in `docs/adr/`, unless `docs/agents/domain.md` names another place |
| The version, for a grill for a version | Its milestone, named after it, made when the grill starts (see "Start") |

Create each file the first time you have something to write in it. `to-spec` reads all three: the grill, the glossary and the ADRs.

**Grills are private.** A grill keeps the user's exact words, which can include personal context.

- Keep its file, branch, PR, replies and decision requests in the configured private repository (ClosedWiz for OpenWiz), and nowhere public.
- A public repository, issue or document carries only a decision in plain words, its decider and date, and a private-comment pointer as [open-development.v1](../../contracts/open-development.v1.md) specifies. Never copy exact replies or thread ids into public text.
- Read the configured private location first. If it is missing, ask before the first round; never create a grill in a public repository.

## When to start a grill

A grill starts when the user asks for one, and also when the factory runs low: the **fed-factory rule**, a standing rule the orchestrator follows without being asked.

- **The rule:** at any moment there are at least twice as many tickets ready to start as builders running. Count both exactly as the [plan links contract](../../contracts/plan-links.v1.md) defines them, its **ready stock** and **builders running** (its **fed ratio** is the one against the other): the numbers the project's board shows, with its low-stock flag. Use those definitions, never a count of your own.
- **Below it, the same day:** when the ready stock drops below twice the builders running, the orchestrator brings the user the next grill that same day: a forward one (the next version) or a sideways one (a side spec). When the gap is large, it brings several grills in parallel, as "Several grills at once" allows. It doesn't wait for the user to ask, and it keeps going on a day the user doesn't work, so the stock is ready when they're back.
- **Never a cap, never a start:** the rule never limits how many builders run, and it never starts work without the user's approval. A grill is a question for the user, not a plan: only a confirmed grill and an approved plan graph make tickets ready.
- **Where to look:** the board's page, which the orchestrator's standing notes name. With no board, count by the contract's definitions from the tracker.

## Start

1. **Read what is already settled:** the grill index (`sh <this skill's folder>/scripts/index.sh`, run from the private checkout's root, where `<this skill's folder>` is the folder this file is in), every grill on a related topic, the glossary and the ADRs. An open grill's file is on its own branch until it merges, so check the open grill pull requests too. If one is open or parked on this topic, resume it: read its file and carry on after its last round (a parked one: see "Several grills at once").
2. **Map the design tree:** every decision the topic needs, and the decisions that hang off each one. The **frontier** is every open decision whose prerequisites are settled: what you can ask now without guessing at answers you haven't heard.
3. **Open the grill:** in the private checkout, write its file from the template below (status **open**), on a branch of its own, with one private pull request for this grill alone. Never edit `docs/grills/README.md`: the index reads the file.
4. **For a version, open its milestone.** If the grill is for a version, make the version's milestone now, named after the version (for example `0.3.0`), so it exists from the grill's first round; if it already exists, use it. `docs/agents/issue-tracker.md` has the commands. A version gets its number and its milestone the day its grill starts, and never before. A grill for anything else (a skill, infra work) makes none.

Done when the file, its index row (what `scripts/index.sh` prints for it, on its branch) and its pull request exist, and, for a version, its milestone.

## Each round

1. **Check the grill log and ADRs first.** Re-read this grill, the other grills and the ADRs, and drop every question they already answer: a settled question is never re-asked. List what you dropped in the file's "Already settled" line, with where it was settled.
2. **Pick at most three questions from the frontier,** the ones that unblock the most (three per grill, when several run at once). A question that hangs on another question still open belongs to a later round. Re-asked questions count toward the three. Facts are your job: anything the code, the files or the tracker can tell you, look up yourself, and ask the user only for decisions.
3. **Word each question in the simplest ELI5 way, without leaving out context.** Open with what it decides, in one short sentence. Then what is true today, the options, and what each one changes, in short everyday sentences; a concrete example beats a definition. Use the glossary's words, and explain any other term in a few words. Then give your recommendation on its own `➡️` line, worded so that "yes" accepts it.
4. **Save, then ask.** Add the round to the file and push. Post its `grill_round` decision record as below. Then send the user the round's questions exactly as saved, so they can answer by id ("G2 yes").
5. **Wait for the reply.** Every decision is the user's, even one whose answer looks obvious.
6. **Save the reply exactly,** every line as they wrote it, typos and all, then the `Settled:` line (see "Reading a reply"), and push. Do this before anything else, so a session that ends here loses nothing. Then update the round record's saved answers as below.
7. **Record what the reply settled.** Keep the exact reply in the private grill and save/read back a private comment on its PR holding those words and what they answered, so public decisions can point to it. In a separate development PR, add each new term to the public glossary and each hard-to-reverse decision as a public ADR (below). Never carry the grill file or its exact replies into that public PR.
8. **Recompute the frontier** and start the next round.

Done when the reply, its `Settled:` line and any glossary or ADR change are pushed.

## Reading a reply

- **A contextual cockpit reply** starts with `openwiz decision answer v1` and follows [decisions.v1's contextual answer message](../../contracts/decisions.v1.md#response-risk-and-answers). Read its one compact JSON context line and the two LF bytes after it; the verbatim answer is every byte after that boundary through message EOF, without trimming, normalization, unescaping or scanning it for another header. Before interpreting it, read the exact saved request comment on the named repository/subject and independently check the saved source at its current head: repository, subject kind/number, comment id, request id/kind, fingerprint, grill file and round/question id (or the latest summary's confirmation identity) must all match an open, current, unanswered request. Keep every risk, ambiguity and confirmation gate. Unread, malformed, ambiguous, mismatching, stale or superseded context settles nothing: ask again; never strip it and treat it as an ordinary reply. Generated context alone confirms nothing.
- **Save only the matched answer segment as the user's reply**, verbatim, through the same private grill and private-comment workflow, before updating `answered` or `status`. Apply the ordinary Yes/recommendation, Simplify, question-back and latest-summary rules below to that segment, restricted to its matched question or summary: context never settles another question or grill, even if the segment names it. Preserve payload lines and blank lines, including header-like text, without splitting them across other grills. A sent/uncertain receipt still settles nothing. Ordinary replies without this framing keep all existing handling below, including split replies, ambiguity and saved-first confirmation.
- **Settle a question only on a reply that answers it:** "yes", "rec is good", "G2 yes", or the user's own decision. A reply about something else, or one "yeah" that could mean anything, settles nothing: never infer an answer from a vague reply; ask again. A question the reply skips stays open too.
- **"Simplify this"** (or "I don't get it", or any reply asking what a question means): re-ask that question more simply in the next round, with the same id and the same context.
- **A question back:** answer it before the next round, and add your answer to the file as a note.
- **A reply that clashes with the glossary, an ADR, an earlier answer or the code:** say so plainly, and ask which one stands.
- **A fuzzy or overloaded word:** propose one precise term, and settle it like any other question.

## Several grills at once

Several grills can run side by side, even sent to the user in one message. Each still follows every rule above; these add what running them together needs.

- **Each grill stays its own.** Its own file, branch and pull request, its own frontier and its own rounds: at most three questions a round, per grill.
- **Ids are unique across every open and parked grill.** When a grill opens, give it letters that no open or parked grill uses (the index lists the merged ones; the open grill pull requests hold the rest), so "D2 yes" names one question across all of them. A confirmed grill's letters can be used again.
- **One message can carry several grills' rounds,** grouped by grill: a line naming each grill (its topic and its file), then its round exactly as saved. Save and push every grill's round before the message goes.
- **Split a reply by grill.** Save each line in the file of the grill it names (by an id, the grill's letters or its topic), word for word and in order, with a note in each file naming the files that hold the rest of that reply. A line that names several grills goes in each of their files. A line that names none goes in the file of every grill in that message and settles nothing alone. Any question the reply doesn't name stays open: ask it again, by id, in that grill's next round.
- **Parking a grill.** When the user parks a grill (sets it aside for later), save the reply exactly, set its status to **parked**, leave its open questions as they are, push, and get its pull request merged: merge it as the project's merge rules allow, or ask the user to merge it, so the file is on the main branch and can't be lost with its branch. Its letters stay its own. To resume it, open a new branch and pull request, set the status back to **open**, and carry on after its last round.

## Finish

1. When the frontier is empty, **write a summary of at most 10 numbered lines,** one decision per line, in plain words.
2. **Save it, push, and show it to the user** exactly as saved. Post its `grill_confirmation` decision record as below. Ask them to confirm it.
3. **Save their reply exactly.** If it corrects a line, fix it, save the new summary below their reply, and show it again. If it opens a decision (something new, or something unclear), go back to rounds: ask it in the next round, with ids still counting, and when the frontier is empty again, write a new summary and show it.
4. **Done only when the user confirms the summary** (the latest one) and nothing is open. Set the file's status to **confirmed**, with the date, push, resolve its decision record, and merge the pull request as the project's merge rules allow (or ask the user to merge it).

Done when the confirmed grill is merged. From there, `to-spec` can plan from it.

## Decision records

These are added requests for the cockpit, alongside every existing saved question, reply and confirmation. Follow [decisions.v1](../../contracts/decisions.v1.md) and its [schema](../../contracts/decisions.v1.schema.json); they add no approval or live-run authority.

1. **Post after saving.** Each saved round posts one `grill_round`; each latest saved summary posts one `grill_confirmation`. Use the grill's pull request, including its current branch head, never an older default-branch file. A round has its actual positive round number and 1–3 questions in saved order: copy each `id`, `decides` (the question wording), `context` and `recommendation` exactly. Copy the summary as 1–10 lines without line breaks inside a line; do not truncate. Use the relative `docs/grills/<basename>.md` file and no fabricated spec number.
2. **Bind the proposal.** Allocate a repository-unique ASCII letter/digit/underscore/hyphen `id` starting with a letter or digit; never reuse it for another request. Set `schema: openwiz.decisions.v1`, `status: open`, and the round's `answered: []`. Explicitly classify `risk` as `ordinary`, `live`, `release`, `publish` or `unknown`; never default to ordinary from wording or missing data. Unknown disables answering; live/release/publish require the cockpit's second confirmation. Compute `fingerprint` as SHA-256 of canonical UTF-8 JSON after removing only `fingerprint`, `status` and `answered`: recursively sort object keys by ASCII name, retain array order and raw Unicode, use decimal integers and no whitespace or trailing newline, escape quotes/backslashes and C0 controls (the usual short escapes, otherwise lowercase `\u00xx`), and never escape `/`. A changed risk or wording needs a new request too.
3. **Post and read back.** Put exactly one request object, with exactly its schema keys, in one column-zero fence opened by three backticks plus `json` and closed by three backticks. Post a separate comment with `gh pr comment <grill-pr> --repo <private-owner/repo> --body-file record.md`, using the verified private repository and existing privacy rules. All PR/comment reads and lifecycle PATCHes explicitly target that same repository; a number alone must not select a public subject. Read the returned comment back by its GitHub comment id; verify its subject, unique request id, exact fields, fingerprint and current saved wording before treating it as posted. A failed or uncertain post/read is unresolved: inspect it before retrying, never blindly post another copy. The synthetic examples below are shapes, never live ids or source content.
4. **Save replies before updating.** Only the orchestrator updates this added JSON block, preserving surrounding human-readable prose and every existing reply/approval record. After the exact reply and `Settled:` line are saved and pushed, set `answered` to exactly the saved answered question ids in question order, without duplicates. Partial answers keep `open`; all questions answered makes it `resolved`. Resolve a summary only after the existing latest-summary confirmation rule accepts the reply and saves it. An accepted, sent or uncertain send, a vague reply, or closing the PR alone resolves nothing.
5. **Replace changed wording.** A rephrased/simplified question, corrected summary, withdrawn request, or next round replacing pending questions supersedes the old request; a replacement gets a new id and fingerprint. Re-asked questions keep their question ids and context. Never mutate proposal fields, kind, id or fingerprint to record progress: only `status` and `answered` change. Save the source change first, mark the old block `superseded`, post the replacement, and read both back. Parking alone leaves questions open; on resuming use the current grill PR and supersede any pending request on its old PR before replacing it. Ambiguous ids, conflicting records or failed reads remain unresolved, never last-write-wins. Updates use the exact comment id (GitHub's issue-comment PATCH), never an unrelated latest comment; read back every lifecycle edit.

**Saved risk locator.** When saving each round, summary or corrected summary, explicitly classify its risk and write exactly one `Risk: ordinary`, `Risk: live`, `Risk: release` or `Risk: publish` as the first physical line immediately below that section's heading, before any blank line. Copy that saved classification into the request's `risk`; never infer or default it. If the classification cannot be established, leave the locator absent and use request risk `unknown`; answering stays disabled. This line is saved in the grill file at its PR head, independently of the request comment.

**Independent currentness.** Preserve the existing human records. The request cannot attest its own currentness: neither its schema, its fingerprint nor reading back that same block establishes a match to independent source wording. U5 must report `current` unknown whenever the exact saved round/summary or independently recorded risk cannot be checked; an unknown check never authorizes an answer. Do not add a currentness field to the request or rewrite the human record to make the request validate itself.

Synthetic round output (all values are invented, including the file and ids):

```json
{
  "schema": "openwiz.decisions.v1", "kind": "grill_round",
  "id": "synthetic-grill-round-1", "status": "open",
  "fingerprint": "d0e5430830a0c844b48ad380e8b26aabed462b3379bde1e8f113e0fa08517956",
  "risk": "ordinary", "grill_file": "docs/grills/2099-01-01-synthetic.md",
  "round": 1,
  "questions": [{"id": "SY1", "decides": "Which synthetic view?", "context": "Synthetic café: \"yes\", path a\\b.\nKeep both lines.", "recommendation": "Use the compact view."}],
  "answered": []
}
```

Synthetic summary output, from the latest saved summary:

```json
{
  "schema": "openwiz.decisions.v1", "kind": "grill_confirmation",
  "id": "synthetic-grill-summary-1", "status": "open",
  "fingerprint": "1294267409e4ff89122faa640967a673b2b06336349e72dc220f720c79c634e3",
  "risk": "ordinary", "grill_file": "docs/grills/2099-01-01-synthetic.md",
  "summary": ["Use the compact synthetic view.", "Keep the synthetic replies exactly."]
}
```

## The grill file

Every grill file has exactly this shape, from its first save. `<User>` is the user's name. An id is the grill's letters (a letter or two for the topic, unique across every open and parked grill) and a number that keeps counting across rounds (G1, G2, G3, then G4 in round 2); a re-asked question keeps its id and says so.

```md
# Grill: <topic> (<YYYY-MM-DD>)

**Private.** Every question exactly as asked, with the recommendation; every reply exactly as <User> wrote it, typos included. Status: **open**. Feeds: <what it will feed>.

Already settled: <each settled decision this grill relies on, and where it was settled>.

## Round 1
Risk: <ordinary|live|release|publish>

**G1 - <the question, short>?** <its context, in plain words>
➡️ <the recommendation, worded so "yes" accepts it>

**G2 - <the question, short>?** <its context>
➡️ <the recommendation>

**G3 - <the question, short>?** <its context>
➡️ <the recommendation>

**<User>:**
> <their reply, exactly, every line>

Settled: G1, G3 (<a few words, if the reply changed the recommendation>). Open: G2.

## Round 2
Risk: <ordinary|live|release|publish>

**G2, re-asked - <the question, more simply>?** <its context>
➡️ <the recommendation>

...

## Summary (shown to <User> for confirmation)
Risk: <ordinary|live|release|publish>

1. <one decision per line, at most 10 lines>

**<User>:**
> <their reply, exactly>
```

- **Replies:** quote every message, in order, with `> ` before every line (a blank line inside a message is a lone `>`). Never tidy, shorten or fix a reply.
- **`Settled:` and `Open:`:** after each reply, every question of that round in one of the two (`none` when empty).
- **Your notes:** one line in parentheses under the reply, only when needed: the answer to a question back, why a question is re-asked, the ADR a decision went to, or, for a reply split across grills, the files that hold the rest of it.
- **A corrected summary:** saved under `## Summary, corrected (shown to <User> for confirmation)`, below the reply that changed it, or below the rounds that reply opened.
- **Confirmed:** the status becomes `Status: **confirmed** by <User>, <YYYY-MM-DD>.` and drops "open".
- **Parked:** the status becomes `Status: **parked** by <User>, <YYYY-MM-DD>.`, the day it was parked, and back to `Status: **open**.` when it resumes.
- **The status paragraph** (line 3, right after the title and its blank line) holds exactly one `Status:` and the `Feeds:` sentence: `scripts/index.sh` reads the index row from it, and refuses a file without them.
- **"Already settled":** leave it out when nothing is.

`docs/grills/README.md` holds no table, so no grill's pull request edits it:

```md
# Grills

**Private.** One file per grill, each saved exactly, question by question, after every round. The index is printed from the files by the `grill` skill's `scripts/index.sh`, run from the private repository's root.
```

`scripts/index.sh` prints one row per grill file, in file-name order: `| [<topic>](<YYYY-MM-DD>-<topic>.md) | **open** | <what it feeds> |`, where a confirmed row reads `**confirmed** (<YYYY-MM-DD>)` and a parked one `**parked** (<YYYY-MM-DD>)`.

## Glossary and ADRs

**A new term:** add it to the glossary the moment it is settled, in the glossary's own format:

```md
**<Term>**:
<one or two sentences: what it is, not how it works>
_Avoid_: <other words for the same thing>
```

Only words specific to this project; general programming words stay out.

**An ADR:** write one for every settled decision that would be hard to reverse, even an obvious one. Name it `<NNNN>-<slug>.md`, numbered one above the highest in `docs/adr/`, and keep it to a title and one paragraph:

```md
# <the decision, as a short title>

<one to three sentences: the context, the decision in your own plain words, and why>

Source: <User>, <YYYY-MM-DD>: <the decision, without quoted exact words> ([private record](<the full private-comment URL>)).
```

## Licence

Adapted from Matt Pocock's `grilling` and `domain-modeling` skills (`github.com/mattpocock/skills` @ `a496f55`), which carry this notice:

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
