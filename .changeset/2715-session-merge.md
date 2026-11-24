---
"launch-fleet": minor
---

The session runner now merges an approved, green pull request itself and carries on, instead of stopping for you. Each merge goes through the fleet's own checks: the current reviewer's approval at the exact head, the overload guard, then `merge.py`, through the merge queue where there is one. While builders or reviewers still run, it keeps polling CI and the merge queue, so a pull request that turns green merges at once. It waits for a reviewer that is still finishing, and records `merge blocked` on the pull request when the approval can't be tied to the current reviewer. Where the project configures an overload supplier (`LAUNCH_FLEET_OVERLOAD_SUPPLY`), each merge batch also passes the fleet's overload guard on the repository's `LAUNCH_FLEET_OVERLOAD_STATE`, and the session stops before merging when that state isn't set; a project without a supplier, such as a new user's first fleet, merges without the overload guard.
