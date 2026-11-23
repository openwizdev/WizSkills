---
"install": patch
"launch-fleet": minor
---

`gitread.py` reads a file at the tip of a repository's default branch from a fetched git cache instead of the GitHub API, and post.py and ops-starts.py now read `docs/agents/fleet.md` through it, so those reads cost no REST allowance. The cache is owner-only (0700), git borrows the signed-in `gh` credential for the fetch, and a failed fetch is not retried until the max age has passed.
