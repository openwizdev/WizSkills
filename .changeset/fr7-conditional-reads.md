---
"launch-fleet": minor
---

A new `ghcache.py` gives Python pollers conditional REST reads with saved ETags, so an unchanged answer is a free `304`; a damaged cache, a `304` with nothing saved or a refusal is an error, never an empty answer.
