---
"launch-fleet": minor
---

`gitread.py` reads a file at the tip of a repository's default branch from a fetched git cache instead of the GitHub API, and post.py and ops-starts.py now read `docs/agents/fleet.md` through it, so those reads cost no REST allowance.
