---
"launch-fleet": minor
---

A red main pauses the pull requests that fail only what main fails, opens one `Main is red` fix ticket, and resumes them once main is green, instead of sending every builder back to fix a failure it did not cause.
