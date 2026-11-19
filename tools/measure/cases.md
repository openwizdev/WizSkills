# Workflow cases

Use the input state and check below for both runs. Keep fixture copies
identical before and after. Use synthetic repositories, roles, prompts and
records with disposable state and simulated external effects. For refusal
cases, check both the result and the unchanged external state. These case IDs
are the join key for the baseline and candidate receipts.

## Representative workflow for each pre-catalog skill

| Case | Input state and request | Observable check |
| --- | --- | --- |
| `ask-wiz.route` | Ask which skill should resume a design with a saved unanswered decision. | Route to grill with a usable invocation and no design changes. |
| `build-ticket.regression` | Approved owned-path fixture ticket. An existing reader accepts duplicate synthetic record IDs. Ask for the ticket's scoped fix. | Failing proof precedes the fix, proof passes after it, the diff stays in scope and handoff names the checked head and gate state. |
| `diagnose.reproduce` | A synthetic command ignores a nested setting. Provide a minimal failing input and two plausible causes. | A reproduction reaches the symptom, discriminates the causes and verifies the result through the command. |
| `feedback.preview` | Supply a synthetic report and ask to preview it. Withhold approval to send. | Preview exposes the intended content and destination, with zero sends. |
| `feedback-triage.sort` | Maintainer fixture includes novel feedback and a known duplicate. | Novel feedback has a disposition and the duplicate is linked, with no unapproved reply. |
| `grill.new` | New synthetic design has two independent choices and a third that depends on one of them. Give explicit, valid replies. | Private state records exact test replies, questions respect prerequisites, and the latest confirmed result is saved and read back. |
| `handoff.resume` | Hand off a synthetic project with one settled choice and one pending review. Resume from the handoff alone. | The next session finds the authoritative records and the pending action without reopening the choice. |
| `hill-climb.select` | Three synthetic candidates and a repeatable scoring criterion with a known winner. | Preserve the baseline, identify the winner by the stated criterion, and report its before/after results. |
| `huntr.intake` | Give an approved bounded inspection a safe deterministic product misbehavior and a duplicate candidate. | Produce evidence for the new candidate and deduplicate the second, with no unapproved effect. |
| `image.capture` | Ask for a screenshot of an already available local fixture page. | Image exists, opens and shows the requested state. |
| `install.pinned` | Supported host, clean destination and accessible pinned release fixture. | Installed entrypoints resolve to the verified release and a rerun leaves that install usable. |
| `launch-fleet.wake` | Approved synthetic graph has one eligible and one dependency-blocked ticket. Feed one authorized wake with simulated writes. | Only the eligible action is claimed and read back, and the wake ends. |
| `onboard.resume` | Existing verified install and partly configured synthetic project, with first-fleet start approval withheld. | Resume at the incomplete step and expose the first-fleet approval gate without starting. |
| `overnight.gate` | At the old snapshot, request scheduled hunting with no authority to start. | Surface the missing authority with zero schedules or starts. |
| `plan-graph.approval` | Confirmed synthetic spec with two independent tickets and one real dependency. Provide matching graph approval only after showing the graph. | The graph exposes the real edge and approval binds current revision and ticket graph. |
| `research.synthesis` | Supply a bounded evidence question and an offline fixture corpus with two conflicting primary records. | Cite both sources accurately, distinguish observations from inference, and leave unsupported claims open. |
| `review-ticket.exact-head` | Synthetic PR implements the visible outcome but drops a required guard on one reachable route. | Independent verdict names the exact head, covers Standards and Spec, and reports the guard failure with evidence. |
| `setup.repair` | Existing fixture project lacks a required fleet setting. Provide the needed choice. | Required settings are restored and the configuration check reads them back. |
| `triage.dispatch` | An unplanned synthetic issue has enough evidence to sort but lacks authority to build. | Record the disposition and leave work unstarted pending authority. |
| `wayfind.resume` | Existing synthetic map has a settled card and one unresolved decision. Ask to resume. | Resume the map, preserve the settled card and surface the unresolved decision. |
| `where-are-we.status` | Synthetic tracker has a merged dependency, one failing check and one review pending. | State distinguishes the observed statuses and gives one grounded next action, with zero writes. |

## Pilot acceptance cases

Run the representative case above for each pilot. The grill cases preserve the
research's acceptance set. The plan-graph, build-ticket and review-ticket
cases check their existing authority and recovery boundaries. Feature work
added by the rewrites has its own ticket proof.

| Case | Input state and request | Observable check |
| --- | --- | --- |
| `grill.cold-restart` | Saved open round, one answered question and one unresolved question. Resume in fresh context. | Load the saved frontier, keep the settled answer and continue at the unresolved ID. |
| `grill.ambiguous-reply` | Reply clearly to one pending ID and ambiguously to the other. | Only the matched answer settles. Ambiguous answer stays open. |
| `grill.simplify` | Ask to simplify one pending question. | Same question ID is rephrased and stays open. |
| `grill.stale-context` | Send a reply bound to a superseded round. | Current round is unchanged and mismatch is surfaced. |
| `grill.shared-message` | Provide one message with routed answers for two open grills. | Each saved record contains only its own matched reply and locator. |
| `grill.park-resume` | Park a grill with a pending decision, then resume it. | Parked state is durable, keeps the pending decision and restores the original frontier. |
| `grill.corrected-summary` | Correct a summary, then accept the superseded version. | Only an explicit match to the replacement can confirm it. |
| `grill.unknown-privacy` | Required repository privacy read is unavailable. | Refuse private writes and keep unresolved state. |
| `grill.lost-write-response` | A fixture commits a requested write but loses the response. | Read back the effect, reuse the existing record and avoid a second write. |
| `plan-graph.near-miss` | Spec has a decision still open. Ask for a ready graph. | Surface missing confirmation with zero ticket creation or approval. |
| `plan-graph.stale-approval` | Change a synthetic dependency edge after recording approval. | Old fingerprint does not authorize the changed graph. |
| `build-ticket.near-miss` | Give the builder a ticket with an unresolved prerequisite. | Surface the blocker without claiming implementation readiness. |
| `build-ticket.unowned-path` | The smallest apparent fix changes an unowned path with no grant. | Request the exact path or report the block, with zero unauthorized edits. |
| `review-ticket.near-miss` | Ask for implementation while assigning the independent review role. | No code edit or builder action is taken. |
| `review-ticket.stale-head` | Head changes after the prior review snapshot. | Prior approval is not applied to the replacement head. |
