---
"launch-fleet": major
---

`merge.py merge` notices a pull request the merge queue dropped, even right after its first enqueue: it records `launch-fleet: merge dropped` with GitHub's reason once, waits while the cause stands or the queue facts can't be read, claims its one automatic re-queue at the same head with a `launch-fleet: merge re-queue claimed` record, never tried twice, after every required check ran green after the removal and the late look still lets it merge, and records `merge blocked` on a second drop, a merge conflict or a person's removal, where it used to record `merge blocked` on any removal.
