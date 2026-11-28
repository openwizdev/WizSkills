# Review a contribution

## Synthetic finding

In this dry review, `synthetic-river` opens `synthetic-fern/pantry#17` with no
linked issue. The description promises a working example of short Git status
output.

- **R1 [blocking]** `docs/status.md:1` (Spec) The example runs `git status --shrot`,
  which exits 129 with `error: unknown option \`shrot'`. Please change
  `--shrot` to `--short`.
  Class: docs
  User path: A reader copying the example gets an option error instead of the
  working-tree status.
  Shows the break: `git status --shrot` printed an unknown-option error and exited 129.
  Next command: `git status --short` shows the expected output in your checkout.
