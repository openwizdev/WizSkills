---
"build-ticket": patch
---

Builders finish git push and its pre-push hook in the same turn, then confirm the remote tip equals the local head before the turn ends.
