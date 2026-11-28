Closes #101

## Summary

A synthetic adder.

## Evidence

Before: `python3 -m unittest test_adder` on the base printed `FAILED (failures=2)`.

After: the same command printed `OK`. Criterion 1: `test_sum` passed.

- An empty input prints `usage` and exits 2: `test_empty` passed.

## Self-check

- undo and rerun: `python3 -m unittest test_adder` printed FAILED


## Merge danger

Door: two-way. Blast radius: small.
