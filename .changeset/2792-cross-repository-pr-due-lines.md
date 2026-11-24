---
"launch-fleet": patch
---

launch-fleet names a closing pull request that lives in another repository in full in its due lines (`merge owner/name#31 for #12 at <commit>`, and the same for re-test, merge main in, review, re-check, CI failed, findings and the other lines that act on it), and `merge.py` takes that name as its pull request: `merge.py merge <ticket's repository> owner/name#31 ...` reads, enqueues at the approved head, merges and records on that pull request, never on the ticket repository's own #31, and reads a bare `--ticket` as the ticket repository's issue. A pull request that reads back as another repository's stops before any write. Pull requests in the ticket's own repository keep their lines byte for byte.
