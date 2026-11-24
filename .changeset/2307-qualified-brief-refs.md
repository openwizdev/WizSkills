---
"launch-fleet": major
---

Every brief names its ticket and pull request as OWNER/NAME#N and tells the agent to pass that repository with `--repo` on every `gh` call, so an agent in another repository's sandbox reads the right issue; `brief.py` now takes OWNER/NAME#N targets and refuses a bare number. The one exception is a `reviewer` brief asked for with `GH_REPO` set, as the fleet session does: its bare pull request number is written out in that repository.
