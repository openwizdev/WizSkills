---
"build-ticket": minor
"review-ticket": patch
---

Builders prove red before, green after with one command, `prove.py`, which runs the test twice on the base and twice on the head in throwaway worktrees and passes only when base fails at an assertion both times and head passes both times; reviewers rerun the same command at the pull request's head.
