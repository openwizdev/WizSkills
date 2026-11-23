---
"launch-fleet": patch
---

`post.py` refuses a pacer state or saved-aside wait file holding an invalid UTF-8 byte with its usual path-free `refused:` line instead of a traceback, and a writer re-reads saved-aside waits just before taking its slot, so a wait another writer saves during that decision stops the write.
