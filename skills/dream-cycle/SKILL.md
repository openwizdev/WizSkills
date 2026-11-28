---
name: dream-cycle
description: Run a read-only org-wide dream cycle into a private report and confirmed tickets. Use on a dream-cycle loop or org-wide review; not for single-issue triage or hunts.
version: 0.1.0
---

# Dream cycle

Skeleton entrypoint for `dream-cycle` (DC1 `#3089`). DC4 (`#3092`) fills the full controller procedure and the `scout.md` and `prover.md` role briefs.

**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.

## Guards

- **Scouts read only.** No scout deletes, closes, archives, or edits anything.
- **Only the controller writes** the dated private report and confirmed tickets.
- **Unproven findings are never ticketed.** Only `CONFIRMED` findings with a `ticket` title are filed.
- **Records kept by rule are never delete candidates.**

## Contract and commands

Read [dream-cycle.v1](../../contracts/dream-cycle.v1.md) and its schema [dream-cycle.v1.schema.json](../../contracts/dream-cycle.v1.schema.json), plus the project's `docs/agents/dream-cycle.md`.

- Inventory (DC2 `#3090`): `python3 -I scripts/inventory.py <repo> --days 14`
- Merge (DC3 `#3091`): `python3 -I scripts/dream.py merge <findings_dir> --out <merged.json> --batches-dir <dir>`
- Report (DC3 `#3091`): `python3 -I scripts/dream.py report <merged.json> <verdicts_dir> --date <YYYY-MM-DD> --out <report.md> --tickets-out <tickets.json>`
