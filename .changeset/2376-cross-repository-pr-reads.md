---
"launch-fleet": patch
---

launch-fleet reads a closing pull request that lives in another repository from that repository: its comments (every page), its check pages past the first 20, its unchanged-check probes, and, for the re-test guard, its files and that repository's own merges into its base branch. It no longer reports a false look or misses a record when this repository has no item with that number or has a different one, and such a pull request with more than 20 checks no longer stops every claim. A comment history that can't be read in full now says which request failed and why.
