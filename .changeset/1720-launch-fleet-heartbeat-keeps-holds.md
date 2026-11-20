---
"launch-fleet": patch
---

A `status.py run` heartbeat never removes a `needs-info` hold it didn't add. It takes off only the label its own run applied, under a GitHub App's own login, so a hold a person set, or one the wake's repair put back, stays.
