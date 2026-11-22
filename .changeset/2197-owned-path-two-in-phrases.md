---
"launch-fleet": patch
---

The start gate reads an owned-path bullet's repository from its last "in `owner/name`" phrase (or its one such phrase), so a bullet like "its tests in `check/run.py` in `owner/repo`" no longer clashes with every ticket. Only a bullet naming two repositories, neither of them last, withdraws the start, and the report names that bullet; a ticket with no owned-path bullet is reported as such.
