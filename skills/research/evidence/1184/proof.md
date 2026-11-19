# WS11 research proof

| Evidence | Before | After |
| --- | ---: | ---: |
| Entrypoint lines | 168 | 97 |
| Entrypoint words | 2,041 | 1,181 |
| `research.synthesis` static loaded-path tokens | 2,785 | 1,675 |
| Observed workflow outcome | Unknown | Unknown |
| Observed workflow token counts | Unknown | Unknown |

Before is the WS1 pin `89fc285ce551f341b8d308732bcd8d4467ace353`. After is `320dbb45fcd9432a9bf9e6611306f8a6c3f2094f`
([path manifest](after-paths.json), [static count](static-after.json)), same
tokenizer and encoding as WS1. No workflow trial ran for this ticket: the
[receipt](after-receipt.json) keeps outcome and every counter unknown.

The skill's one exact mechanic, the worker write check, already lives in
`scripts/check-workers.sh`; no new script or test. Both kept suites,
`test_workers.py` and `test_snapshot_commands.py`, pass unchanged.
