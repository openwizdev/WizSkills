---
"to-tickets": patch
---

to-tickets' approval helper reads a cross-repository Relies on file as present only when the GraphQL answer has no `errors` key at all; an `errors` key of any value, even `null`, `false` or an empty list, is an unreadable input (exit 2, no approval).
