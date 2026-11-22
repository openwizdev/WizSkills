---
"review-ticket": patch
---

A re-check after a large `main` merge now checks the pull request's own changes from the local checkout instead of failing at GitHub's 300-file compare limit, and says which commit it could not read when it refuses.
