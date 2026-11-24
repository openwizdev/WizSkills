---
"launch-fleet": major
---

`merge.py merge` writes nothing before a `pending: ...`, except the call it is reading back: a removal of the head whose enqueue does not read yet stays pending even when a queue receipt, drop record or claim already exists, and a re-queue's read-back that is pending comes after two writes, its claim and then its enqueue, says so, and writes nothing more. It records a drop after a re-queue only once the removal reads after an enqueue by a record author made after the claim, a refused re-queue whose read-back is pending or whose queue facts can't be read prints `pending: ...` instead of `not re-queued`, and duplicate records are deleted only on a wake that ends neither `pending: ...` nor `unknown: ...`.
