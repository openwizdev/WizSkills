---
"huntr": patch
---

Every final path of a hunt now ends with `lease.mjs finish`, which publishes the final result and releases the lease even through a brief GitHub read failure; a dispatch that blocks every slice finishes at once; and pacing refuses a last-empty time without Z or an offset.
