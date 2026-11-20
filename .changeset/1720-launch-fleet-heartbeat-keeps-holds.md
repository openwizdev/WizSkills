---
"launch-fleet": patch
---

A `status.py run` heartbeat never removes `needs-info`. It still adds the label for an asking note, and the agent's own status write leaving asking clears it, so a hold a person set, or one the wake's repair put back, stays.
