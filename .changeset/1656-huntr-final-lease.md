---
"huntr": patch
---

A hunt's last wake, a pause after claiming and a dispatch that blocks every slice now publish the final result and release the lease; a wake that cannot read the lease retries instead of recording; and pacing refuses a last-empty time without Z or an offset.
