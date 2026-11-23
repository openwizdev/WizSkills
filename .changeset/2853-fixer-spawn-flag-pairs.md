---
"setup": patch
---

Setup's `settings.py check` rejects a Fixer row whose spawn-flags cell has trailing tokens after the three `--provider` / `--model` / `--reasoning-level` pairs, naming the malformed cell.