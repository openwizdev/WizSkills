---
"build-ticket": patch
---

Builders commit only as their GitHub noreply address: `ticket.py author` refuses while anything overrides it, and `ticket.py push` sends only HEAD to origin and refuses any commit origin lacks whose author or committer is not a noreply address named as its login.
