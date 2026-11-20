---
"launch-fleet": minor
---

launch-fleet starts every agent from the one Models table in `docs/agents/fleet.md`, read at each start: builders, small builders, reviewers by the cross-family rule, fixers by the fixer rule, and a spec's fleet thread on the Orchestrator row. Projects with only the older five tables keep working, and `ops-starts.py flags` prints each start's spawn flags.
