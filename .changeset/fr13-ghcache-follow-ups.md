---
"launch-fleet": patch
---

`ghcache.py` no longer reuses an old page list after a failed cache write, refuses a symlinked cache folder that another user could redirect, and lets two pollers create a fresh cache together.
