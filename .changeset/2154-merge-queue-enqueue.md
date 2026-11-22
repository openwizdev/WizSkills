---
"launch-fleet": patch
---

On a merge-queue repository, `merge.py merge` enqueues through GitHub's merge queue pinned to the approved head, refuses while required checks are still running, and writes its `merge queued` receipt only after it reads the queue entry back.
