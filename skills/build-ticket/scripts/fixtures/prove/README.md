Synthetic repositories for `test_prove.py`. Each case is two trees: `base/` is committed first,
then `head/` replaces it as the next commit. `test_calc.py` exists only at head; `prove.py`
copies it into the base worktree.

| Case | Base | Head | Expected |
| --- | --- | --- | --- |
| `red-green` | wrong sum | right sum | exit 0 |
| `base-error` | no `calc` module | right sum | exit 1, base `error` |
| `base-passes` | right sum | right sum | exit 1, base `passed` |
| `flaky-head` | wrong sum | right on the first call only | exit 1, head `passed`, `failed` |
| `timeout` | wrong sum | never returns | exit 1, head `error` |
