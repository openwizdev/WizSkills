---
"launch-fleet": patch
---

The local heartbeat's `status` now names an unresolved start's folder and tells you to run `remove` once the spec is done, a closed spec's tick logs `done` instead of `idle`, and `remove` retires a saved run the driver no longer knows instead of refusing; the webhook setup no longer subscribes to check suites.
