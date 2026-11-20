---
"launch-fleet": minor
---

launch-fleet tries a refused driver start or wake twice more, then marks the ticket's fleet note `stopped (driver start failed)` and leaves one comment pointing to the owner-only driver log that keeps the driver's own words, cleared by the next success; set LAUNCH_FLEET_HARNESS, LAUNCH_FLEET_MODEL and LAUNCH_FLEET_SKILLS for that note, as without them only the note is skipped.
