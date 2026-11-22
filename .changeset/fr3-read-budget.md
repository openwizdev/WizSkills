---
"launch-fleet": minor
---

launch-fleet's new `budget.py admit N` admits or refuses the next batch of REST reads from GitHub's rate-limit headers or the free `rate_limit` read, keeping a quarter of the allowance for builders and reviewers, and refuses when the allowance is unknown.
