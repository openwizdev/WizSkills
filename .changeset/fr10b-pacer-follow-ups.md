---
"launch-fleet": patch
---

`post.py` refuses a pacer state or saved-aside wait file holding an invalid UTF-8 byte with its usual path-free `refused:` line instead of a traceback. A writer now admits its slot in one step under a publish lock: it re-reads saved-aside waits, rechecks its 30-second window and records the slot. A wait saved aside before that step stops the write, and a settlement that cannot get the state lock saves its wait only before or after that step, never during it. A writer that stalls past its window during the re-read is refused.
