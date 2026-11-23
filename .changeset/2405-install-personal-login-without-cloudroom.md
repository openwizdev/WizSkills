---
"install": patch
---

Without CloudRoom, Connect now recommends your verified personal GitHub login (`github_login.py skip-app`) instead of the GitHub App, whose setup needs CloudRoom today; the App is still there if you ask for it, and with CloudRoom the App stays the recommendation. Step 4 now refreshes the install skill from this release's own tag (or the verified build's copy when it already matches), never from `main`, so the restart keeps this fix.
