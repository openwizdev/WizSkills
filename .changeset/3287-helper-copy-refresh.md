---
"launch-fleet": patch
---

launch-fleet's copies of the GitHub App helpers and the token-service contract match OpenWiz main again: each token request carries a one-time RSA 3072-bit public key (`answer_key`) and the service returns the token only sealed (`sealed_token`), which only the asking helper opens into its private folder.
