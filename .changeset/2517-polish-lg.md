---
"launch-fleet": patch
---

The ledger's read-only test treats a GraphQL call with an `--input` body, a call with no endpoint and one with two query fields as unknown, and reads `-X=GET` and `-f=query=...` as the reads they are.
