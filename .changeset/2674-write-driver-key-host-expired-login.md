---
"write-driver": minor
---

write-driver's expired-login lesson now runs for key-host drivers: `lesson expired-login --key-host <host> --openwiz <checkout>` runs the driver's start against the kit's fake host answering 401, with no real key and no live host, and the driver passes only when it turns that 401 into the contract's sign-in step.
