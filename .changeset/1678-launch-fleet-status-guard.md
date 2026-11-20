---
"launch-fleet": patch
---

launch-fleet's status writer refuses a note holding a forward-slash drive path (`C:/…`), an scp-style `host:/…` path or a colon-form key such as `api_key:`, `access_token:` or `auth:`.
