---
"review-ticket": patch
---

Make the reviewer's read-only checkout a check: `review.py snapshot` records HEAD and the working tree before the diff is read, and `review.py verify` refuses to post when HEAD, a commit or any working-tree file changed, ignoring scratch worktrees under the system temp folder.
