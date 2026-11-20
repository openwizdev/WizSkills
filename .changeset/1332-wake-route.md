---
"launch-fleet": minor
---

launch-fleet wakes the right fleet for GitHub messages from any repository whose pull requests close the project's tickets, and resolves a fleet's loop handle with a tested lookup that leaves a spec with no loop id to its own loop. Its webhook setup, rotation, list and delete run `gh` through `route.py gh` with a clean environment, so no trace setting in the caller's shell can print the webhook address.
