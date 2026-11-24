---
"launch-fleet": minor
---

The session runner now merges an approved, green pull request itself and carries on, instead of stopping for you. Each merge goes through the fleet's own checks: the current reviewer's approval at the exact head, the overload guard, then `merge.py`, through the merge queue where there is one. While builders or reviewers still run, it keeps polling CI and the merge queue, so a pull request that turns green merges at once. It waits for a reviewer that is still finishing, and records `merge blocked` on the pull request when the approval can't be tied to the current reviewer. It merges only with `LAUNCH_FLEET_OVERLOAD_STATE` set to the overload state path the rest of the fleet uses for that repository; without it the session stops before merging.
