Synthetic hand-backs for `test_complete.py`. `ticket.md` is the one ticket body (three criteria,
ticket #101 by each description's `Closes` line); each case is a `description.md` and the
`paths.txt` of its changed paths.

| Case | What it plants | Expected |
| --- | --- | --- |
| `complete` | nothing | exit 0, `complete: ok` |
| `no-changelog-mention` | no `changes/101.md`, a `no-changelog` mention | exit 0, `complete: ok` |
| `fenced-heading` | a `## ` line inside the Before run's code fence | exit 0, `complete: ok` |
| `criterion-gap` | no line names criterion 3 | exit 1, `criterion without evidence` for it |
| `no-red` | `Before: n/a` | exit 1, `no red-first evidence` |
| `no-changelog` | only look-alike paths | exit 1, `no changelog line` |
| `wrong-ticket-note` | `changes/1010.md`, another ticket's note | exit 1, `no changelog line` |
| `every-gap` | criteria named only in the Summary, no Before run, no note | exit 1, all five lines |
