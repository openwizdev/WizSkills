---
"launch-fleet": major
---

`merge.py merge` returns every `pending: ...` before it writes anything: a removal of the head whose enqueue does not read yet stays pending even when a queue receipt, drop record or claim already exists, a refused re-queue whose read-back is pending prints `pending: ...` instead of `not re-queued`, and duplicate records are deleted only on a wake that ends neither `pending: ...` nor `unknown: ...`.
