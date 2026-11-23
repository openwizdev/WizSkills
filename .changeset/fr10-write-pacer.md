---
"launch-fleet": minor
---

`post.py` paces fleet writes below GitHub's secondary limits: each new comment takes a slot from its account's bucket (60 a minute, 400 an hour) in `${XDG_STATE_HOME:-~/.local/state}/launch-fleet/writes.json` under a file lock, with at most 20 writes in flight on the machine (edits count only toward that cap). With no slot within 30 seconds it refuses with `refused: write paced, retry after <time>` and writes nothing. A secondary-limit `403` or `429` records GitHub's wait so every writer on the machine waits it out, and is never retried blind.
