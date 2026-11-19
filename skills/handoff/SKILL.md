---
name: handoff
description: Keep the orchestrator's one-page handoff file in the private repository current, so a new orchestrator can take over without the old chat. Use after the user approves a plan graph, before an orchestrator retires, and first thing when taking over as orchestrator. Orchestrator only.
version: 0.2.0
---

# Handoff

An orchestrator is one long chat. When it grows too long, or a new orchestrator takes over, everything it knew has to survive. It survives in the project's **handoff file**: one short page in the configured private repository. Matt's version writes to a temporary folder, which a cloud sandbox throws away; in the private repository, every authorized new orchestrator can read it.

**Only the orchestrator hands off.** A builder's state is its branch, pull request and ticket, and it stays with its ticket to the end. A reviewer's state is its report on the pull request. The five-minute loop starts a fresh thread each time it runs and reads everything from GitHub. If any of them stops, its replacement reads those and carries on.

## When

| When | Do |
| --- | --- |
| You are taking over as orchestrator | **Take over**: read the page before anything else |
| The user has just approved a plan graph | **Update the page** |
| You are about to retire: your chat is too long, or another orchestrator takes over | **Update the page** as your last act, then tell the user it is ready for the next orchestrator |

## Find the page

Read `docs/agents/issue-tracker.md` for the private repository and `docs/agents/domain.md` for its checkout and state paths, then the handoff path the project's instructions name. Resolve the private handoff file and orchestrator state through the consumer project's settings. Verify the remote and private visibility before writing. If no handoff exists, create it at that private path from the template below. Missing private settings or unknown visibility stops the write; never fall back to a public `docs/agents/handoff.md`. A public instruction may name the private location, but must not copy its content.

## Take over

1. Read the handoff file first, then the issues and files it points to.
2. Check it. The page is a **snapshot**, and the work has moved since it was written. Check each fleet against its spec issue, each agent and loop against CloudRoom, and each decision against where it was asked. Act on what is true now.

Done when you know, for every line on the page, whether it still holds.

## Update the page

1. **Read the facts fresh** from GitHub and CloudRoom: each open spec with an approved plan graph, and its tickets; the open pull requests; every agent and loop still running for the project; the standing approvals on record.
2. **Rewrite the page whole** from the template. Replace it rather than adding to it; git keeps the history. Under a heading with nothing in it, write "None."
3. **Give every line its source:** the issue, pull request, commit or file it comes from, or a decision with its date and private-comment pointer. Exact decision words may be kept on this private page only. Point to specs, plans, decisions and reports by link or path, and keep their content where it already lives. Mark anything you could not check **unverified**: the next orchestrator trusts this page, so a guess written as a fact sends it the wrong way. A branch or pull request shows the work, not that its agent is still running: unless CloudRoom shows the thread, its state is unverified.
4. **Keep it safe to commit:** no keys, tokens, passwords, email addresses or personal details, and nothing quoted from a chat but the user's decisions, confined to this private page. No handoff, state, exact replies or thread ids go into a public file, PR description or comment; public decision sources use the decision, date and private-comment pointer. Name each agent by its work (role, ticket, branch, pull request), which is how a fleet finds its agents anyway.
5. **Land it on the private repository's default branch** (usually `main`), with Git/PR operations in its verified private checkout and comments explicitly targeting that repository, by the project's standing merge rules (`docs/agents/fleet.md`), and read it back from there. A page left on a branch hands nothing off.

Done when the private default branch holds the new page, every line on it has a source or says unverified, and it is still one short page: one row per fleet, with each full list one link away, however many agents are at work.

## The page

One snapshot line, then these five sections in this order, and nothing else:

```markdown
# Orchestrator handoff

**Snapshot: <UTC date and time>, <why: "plan graph approved on #N" or "before retiring">.** <Where the rules and the project's status live.> A new orchestrator reads this first and checks each line before acting on it.

## Open fleets

One row per spec whose plan graph the user approved and that is still open, and one per piece of open work outside any fleet, marked so. Write counts; the spec issue lists the tickets. Name a ticket only when it needs a look.

| Fleet | Version | Graph approved | Merged | Can start or building | Waiting on blockers | Needs a look |
| --- | --- | --- | --- | --- | --- | --- |

## Running agents

One row per fleet, and one for agents outside any fleet: how many builders and reviewers are at work (counted in CloudRoom, or marked unverified), where the full list is (the spec issue: each ticket's branch and pull request lead to its agent), and any agent that needs a look, by ticket. Anything else left running for the project (a server, a tunnel) goes below the table, with how to check it and restart it.

| Fleet | Builders | Reviewers | Full list | Needs a look |
| --- | --- | --- | --- | --- |

## Decisions waiting on <the user>

Each question the user has not answered and each step only the user can take: what it is, where it was asked, and your recommendation.

## Loops

Each loop running for the project: what it checks, how often, and when to stop it.

## Standing approvals

Each permission the user gave that still holds: the decision, date, private-comment pointer and what it does not cover. Exact words may be retained here because this page is private. Any public use of the standing approval uses the public approval-on-its-own form and points to that private comment.
```

## Credit

Adapted from Matt Pocock's `handoff` skill (`github.com/mattpocock/skills` @ `a496f55`), under the MIT License:

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
