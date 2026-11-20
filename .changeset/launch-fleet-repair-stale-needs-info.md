---
"launch-fleet": patch
---

A fleet wake's status step is one `status.py repair` call: it adds `needs-info` only while a note is still asking at the write, takes off a stale label only when it added it itself, and reports a failed check as a failed check.
