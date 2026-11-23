---
"launch-fleet": minor
---

`merge.py merge` notices a pull request the merge queue dropped: it records `launch-fleet: merge dropped` with GitHub's reason, waits while the cause stands, queues it again once at the same head after every required check ran green after the removal, and records `merge blocked` on a second drop, a merge conflict or a person's removal.
