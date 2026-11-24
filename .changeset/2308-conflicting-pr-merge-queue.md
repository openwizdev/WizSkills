---
"launch-fleet": patch
---

When a merge-queue repository refuses an enqueue or re-queue and the pull request reads back open at the approved head with `CONFLICTING` mergeability, `merge.py merge` now records `launch-fleet: merge blocked <head>: not mergeable: CONFLICTING` and exits with `blocked: not mergeable: CONFLICTING` instead of stalling at `not queued`, so the fleet routes it back to its builder to merge main in.
