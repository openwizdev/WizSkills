---
"build-ticket": patch
---

Builders take only the App's token and push from the identity page and keep the identity `ticket.py author` set, and repair a refused push's outgoing commits only when, read from origin's push URL as `ticket.py push` reads them, they are a merge-free run after one published commit; otherwise they stop and ask.
