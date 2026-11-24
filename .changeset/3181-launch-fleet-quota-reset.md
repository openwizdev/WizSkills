---
"launch-fleet": patch
---

Catch first-turn model quota errors on builder starts with `start not tried: quota` (and reset time) instead of `started`, and retry at the reset.
