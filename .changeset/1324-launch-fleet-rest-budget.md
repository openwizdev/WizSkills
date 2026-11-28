---
"launch-fleet": minor
---

A fleet's `spec` check stays inside 30 REST calls a wake by default (`LAUNCH_FLEET_REST_PER_WAKE`): it reads by GraphQL when the unchanged probe would not fit, and `route.py cron` gives each spec's loop a minute of its own.
