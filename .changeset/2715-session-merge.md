---
"launch-fleet": minor
---

The session runner now merges an approved, green pull request itself and carries on, instead of stopping for you. Each merge goes through the fleet's own checks: the current reviewer's approval at the exact head, the overload guard, then `merge.py`, through the merge queue where there is one. While builders or reviewers still run, it keeps polling CI, so a pull request that turns green merges at once.
