---
"launch-fleet": major
---

launch-fleet tries a refused driver start or wake twice more, then marks the ticket's fleet note `stopped (driver start failed)` and leaves one comment with the driver's next step, cleared by the next success; host.py now needs the fleet's harness, model and skills in its environment.
