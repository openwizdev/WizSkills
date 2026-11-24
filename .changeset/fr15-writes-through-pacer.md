---
"launch-fleet": patch
"review-ticket": patch
---

Status notes, the needs-info label, review-ticket's follow-up issues and merge.py's landed comment and duplicate deletes now go through post.py's write pacer, so a recorded GitHub cooldown stops them before they write; merge.py's help and retry message say a re-queue's claim was recorded and its enqueue attempted, and describe the claim's own read-back.
