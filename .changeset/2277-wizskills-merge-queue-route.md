---
"launch-fleet": patch
---

On a repository with the merge queue on, an approved pull request is no longer re-tested or sent back to merge `main` in just because `main` moved, and WizSkills' fleet settings route its merges through the queue, pinned to the approved head.
