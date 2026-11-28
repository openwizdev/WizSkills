---
"to-tickets": patch
---

Machine approval now catches intersecting glob patterns in owned paths, ignores HTML comments and fenced code blocks when reading ticket metadata (requiring `Size:` in visible `Parent`), and verifies cross-repository `Relies on:` paths against per-repository `--checkout` folders instead of the graph checkout.
