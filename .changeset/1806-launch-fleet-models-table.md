---
"launch-fleet": minor
---

launch-fleet starts every agent from the one Models table in `docs/agents/fleet.md`, read from GitHub's default branch at each start: builders, small builders, reviewers by the cross-family rule, fixers by the fixer rule, and a spec's fleet thread on the Orchestrator row, which each wake keeps its loop on. Projects with only the older five tables keep working, read whole. `ops-starts.py flags --repo <owner>/<repo>` prints each start's spawn flags.
