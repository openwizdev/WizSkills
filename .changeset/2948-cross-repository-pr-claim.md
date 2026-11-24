---
"launch-fleet": patch
---

`fleet.sh claim` accepts `owner/name#N` for a pull request in another repository, reads the pull request and claim comment in that repository, prints `go owner/name#N` or `withdraw owner/name#N: <why>`, and refuses any repository that is not a closing pull request's repository before reading it. Bare-number claims behave as before.
