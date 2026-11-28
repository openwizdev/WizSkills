Closes #101

## Summary

A synthetic adder.

## Evidence

Before: `python3 -m unittest test_adder` on the base printed `FAILED (failures=2)`.

After: the same command printed `OK`. Criterion 1: `test_sum` passed.

- An empty input prints `usage` and exits 2: `test_empty` passed.

## Self-check

- criterion 3: `python3 -m unittest discover` printed OK (9 tests)

## Rulings

none: tests only, so the `no-changelog` label stands in for a line.

## Merge danger

Door: two-way. Blast radius: small.
