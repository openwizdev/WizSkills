---
"launch-fleet": patch
---

Let the builder's starting thread record first-turn quota failures, including failures reported after the starting wake ends. Confirm the failed builder is archived before recording `start not tried: quota`, then retry at the reset or use the 10-minute wait when the reset is unknown or has already passed.
