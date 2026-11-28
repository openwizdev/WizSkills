---
name: dream-cycle
description: Run a dream-cycle wake or org-wide review into a private report and proven tickets. Use triage for one issue.
version: 0.1.0
---

# Dream cycle

**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.

## Guards

- Scouts and provers read only.
- Only the controller writes.
- Verify the private target before writing.
- Never delete, close, archive or edit existing work.
- Records kept by rule may only be fixed.

## 1. Scope

Read settings. Use [the controller steps](agents/controller.md).
Resume the next missing step in the dated private run.
Done when scope and privacy are verified.

## 2. Scout

Inventory each repo.
Fan out [scout.md](scout.md) with inventory slices.
Re-tell a scout without its findings file.
Done when each slice has a file or gap.

## 3. Prove

Run the link funnel in [prover.md](prover.md).
Merge and verify in waves within `link_budget`.
Done when verdicts and gaps are saved.

## 4. Report

Render and read back the private report.
Done when the report and ticket list are saved.

## 5. File

File `CONFIRMED` wins as `ready-for-agent` briefs.
Look up the exact title first.
Use a private-record link and neutral wording.
Done when issue receipts are saved.

## 6. Summarize

Send the owner the top ten deletes, fixes and links.
Done when delivery is recorded.
