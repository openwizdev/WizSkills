---
"launch-fleet": patch
---

`ghcache.py` never trusts a saved page list on a `304`: without a fresh `Link` it reads on until a short page, so a failed cache write can't hide a page, and it no longer writes into an existing cache entry. It also refuses a symlinked cache folder that another user could redirect, and lets two pollers create a fresh cache together.
