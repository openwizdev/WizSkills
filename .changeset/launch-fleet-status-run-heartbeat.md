---
"launch-fleet": minor
---

`status.py run --note <id> -- <command>` keeps an agent's claim live while long work runs, and stops the work when the claim is lost; a heartbeat never reopens a done or stopped note.
