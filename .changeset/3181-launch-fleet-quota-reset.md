---
"launch-fleet": patch
---

Catch first-turn model quota errors on builder starts with `start not tried: quota` (and reset time) instead of `started`, retry at the reset, and wait 10 minutes when that record is posted after the reset has passed.
