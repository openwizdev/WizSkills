---
"launch-fleet": patch
---

A fleet wake's status step is one `status.py repair` call. It adds `needs-info` only while a note still asks, records the repair in its own fleet note until the label is settled (so a later wake finishes a repair an earlier one left part way), takes off only the application it made, puts back and reports a person's application it took, and reports a failed check as a failed check.
