---
"launch-fleet": patch
---

Fleet checks tell open pull requests apart by their node id as well as their number, so two repositories' pull requests sharing a number no longer fail a spec's reads, and neither takes the other's checks.
