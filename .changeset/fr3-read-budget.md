---
"launch-fleet": minor
---

launch-fleet's new `budget.py admit N` admits or refuses the next batch of REST or GraphQL reads from GitHub's rate-limit headers or the free `rate_limit` read, keeping the larger of a quarter of the allowance and 1,500 (or `--floor`) for builders and reviewers, names the allowance it read, and refuses when the allowance is unknown.
