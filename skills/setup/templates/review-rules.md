# Review rules

The owner keeps this file; reviewers read it and never edit it. Keep it under 6 KB: when a section grows, merge lines into a wider class or drop the oldest. The `review-ticket` skill reads it when it is present, and a missing file changes nothing.

## Never flag

Classes of finding the owner has declined. A reviewer skips any finding in one of these classes. One line each: the class, how often it was declined and the date it was last declined.

- `<class of finding>`: declined `<count>`, `<YYYY-MM-DD>`

Example: style-only renames in tests: declined 4, 2026-11-20

## Path rules

One-line invariants learned from past bugs. A reviewer applies a rule only when a changed path matches its glob, and ignores the rest.

- `` `<glob>` ``: `<invariant>`

Example: `` `src/export/**` ``: an export never overwrites an existing file; it exits 3 instead.

## Severity examples

One finding of each grade for this project, so reviewers grade alike.

- Blocking: `<finding that stops the merge, and why>`
- Non-blocking: `<finding filed as polish, and why>`

Example, blocking: a second export in one day silently replaces the first, so a user loses data.
Example, non-blocking: the help text says "zip archive file" where the glossary says "export".
