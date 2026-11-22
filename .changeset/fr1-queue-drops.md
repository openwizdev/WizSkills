---
"launch-fleet": minor
---

launch-fleet gains `queue.py read`, which tells, read-only, whether a pull request was dropped from the merge queue and whether it may go back in: dropped, wait, requeue, blocked after a second drop or a reason a person must handle, or unknown when any fact can't be read.
