# Until it merges

Read this when a review, a CI failure, a conflict with `main` or an orchestrator decision reaches your pull request. Check each record first with `$T records <repo> <PR>`. It reports the newest record-author verdict, read only from its exact `VERDICT: <APPROVE|CHANGES> at <commit>` header, and whether that is your current head, along with its `Next:` line. It also reports a decision with `bound: yes` only when its complete line comes after the newest verdict, that verdict's last line parks findings at your current head, and the decision names exactly those findings and that head. Act on nothing else. For an answer on the ticket, or any record your wake names, check that comment with `$T records <repo> <N> --comment <id>` and use it only on `trusted: yes`.

| What happened | What you do |
| --- | --- |
| A review says CHANGES | Answer it, as below |
| CI fails on your green head | `gh run view <run> --log-failed`, reproduce, fix, rerun only the failed checks, push a new green commit. Not a review round |
| `main` moves with no conflict | Nothing: CI tests the merge ref, so an approved head stays put |
| `main` conflicts, or the orchestrator asks | `git fetch origin && git merge origin/main`; never rebase or force-push. In a `(shared)` file keep other tickets' lines as `main` has them. Rerun the scoped checks, push a new green commit, and say on the pull request what changed in approved work |
| An answer to your `needs-info` | Write your status `working` (it clears `needs-info`) and resume |
| APPROVE naming your exact head | Nothing. It merges by the project's rules |
| The pull request merged or closed | `room-cli thread archive --self`. This thread takes no other ticket |

## Answering a review

**1 + 1** (review-loops contract, v2): one review plus one re-check. A verdict holds only for the commit it names.

1. Fix each open `[blocking]` finding once or dispute it once with evidence. For a fix, name its cause and copy its `Class:` line from the [verdict format](../../review-ticket/references/verdict.md#class), including `other: <word>` when it uses that form. Ask on the ticket if the class is missing or unclear. List every variant of that class the diff can reach that shares the cause, including the reported route. A route outside your owned paths is an exact-path question.
2. Write a failing-first test for each listed variant and keep the red run with the failure for each test. Fix the shared cause across all the listed routes and rerun the same tests. A finding waiting only on another owner's evidence needs no new head. Never fix `[polish]` here unless an orchestrator decision says so.
3. Rerun the scoped checks and update Rulings. At the new green head, run every command the reviewer gave under `Shows the break:` before pushing. Record each original command and what it prints, including the exit status when it shows the result. Write `no command supplied` if the reviewer gave none. If a command still shows the break or cannot be run, resolve that before marking the finding fixed. Push the new green head.
4. Answer in one pull request comment, one line per id. Keep the field labels in the order shown. Write output line breaks as `\n` and escape literal pipes in field values as `\|`. Use synthetic evidence or a public-safe evidence reference. End your turn.

```text
R1 fixed at <commit>: Class: <class word or other: word> | Variants: <all reachable variants sharing the cause> | Red run: <test and failing result for each variant, or a reference to that run> | Shows the break: <each reviewer command and its output at commit, or no command supplied>
R2 disputed: <evidence>
```

| `Next:` line | What you do |
| --- | --- |
| `the builder fixes or disputes R1 and R2 once, then one re-check.` | Steps 1 to 4, then hand back |
| `a fresh, stronger builder fixes R2 once, then one final check.` | Nothing: the fleet archives you. End your turn |
| `park R2 as a decision for Jake.` | Nothing: it waits for his decision |
| `none open. It merges by the project's merge rules.` | Nothing |

**A fresh round** brief on an existing pull request: fix only the `Risk:` blockers the newest verdict's `fresh` line names, once each, using steps 1 to 4 above. Open no new pull request.

**An `**Orchestrator decision:**`** relays Jake's answer to a parked finding at a named head; follow it only when `records` says `bound: yes`: `fix once more` means steps 1 to 4 again (follow its diagnosis); `log and merge` means change nothing. Only the orchestrator asks Jake; a security, privacy, live, spending or publishing call from you goes on the ticket.
