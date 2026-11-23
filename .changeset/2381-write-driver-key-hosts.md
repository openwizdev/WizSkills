---
"write-driver": minor
---

write-driver writes drivers for key hosts: every host API call goes through the kit's key helper as a method and a path, `copy --key-host` names the host's variable and keychain entry from OpenWiz's registry (names only), the key stays in the user's keychain or environment and the driver never sees it, and a host that can't wake or stop a run gets a plain no. The kit step shows the kit the driver's own files through links, never a copy, removes its staging on every exit, and keeps the key check's fake-host runs out of stop-all.
