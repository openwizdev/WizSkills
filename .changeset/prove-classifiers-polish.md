---
"build-ticket": patch
---

`prove.py` refuses a test command it cannot start, and it treats a node subtest assertion, a pytest id that contains a space, and a unittest unexpected success as the test output says.
