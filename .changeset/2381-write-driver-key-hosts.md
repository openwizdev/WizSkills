---
"write-driver": minor
---

write-driver writes drivers for key hosts: every host API call goes through the kit's key helper as a method and a path, the key stays in the user's keychain or environment and the driver never sees it, and a host that can't wake or stop a run gets a plain no.
