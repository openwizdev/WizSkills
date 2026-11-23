---
"install": patch
---

Install step 4 reads each agent's row of the skills install: a partial install counts as done, each skipped skill of your own is named with its next step, an older copy left by a failed write is caught, a refused run says nothing was installed, and the skill count comes from the release, not a fixed number. Uninstall lists every heartbeat job and removes only the ones you name.
