---
"write-driver": minor
---

write-driver's expired-login lesson now runs for key-host drivers: `lesson expired-login --key-host <host> --openwiz <checkout>` runs the driver's start against a fake host answering 401, with no real key, no live host and no network, and the driver passes only when it turns that 401 into the contract's sign-in step and does not name that step when the host answers 500.
