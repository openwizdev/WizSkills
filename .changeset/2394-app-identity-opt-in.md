---
"launch-fleet": minor
"setup": minor
"build-ticket": patch
---

The App identity is off for everyone: agents and the fleet loop never mint the App's token or run the agent helper, and act as today's account. Setup's `fleet.md` template gains an `App identity | off` row, which `settings.py check` holds to exactly `on` or `off`; nothing reads it yet.
