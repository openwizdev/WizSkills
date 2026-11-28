# Agent pull request

One issue, one branch, one pull request. The fence info string is `agent-pr` and `"schema"` is `agent-pr/1`. Prose, size, and secrets follow [the issue record](../agent-issue/spec.md).

## Fields

| Field | Rule |
| --- | --- |
| `closes` | The one issue `id` |
| `intent` | One sentence |
| `changes` | One `acceptance` and `change` for each acceptance id |
| `proof` | The same ids. `command` equals that item's `check`. `result` is `pass` before review. `red_first` is true or false. A `bug` needs one true |
| `risk` | `low`, `medium`, or `high`, then an optional `: note` |
| `rollback` | One line, the undo |
| `owned_paths` | Paths this pull request touches. Each one is covered by the issue |
| `gates` | The same set as the issue. Non-empty means stop for a human |

Pass the issue file before review. The issue must be `ready-for-agent`. `--mode draft` allows `result` `fail` while the red test is still the current result. The worked example is [template.md](template.md).

## Branch

`<agent>/<repo>-<N>-<lane>`

`agent` and `repo` are lowercase slugs. `repo` may contain hyphens. `N` is the issue `id` and has no hyphen. `lane` is a lowercase word, such as `build`. Example: `ada/widgets-14-build`.

## Title

`#<id>: <summary or goal>` when `id` is a number. Otherwise `<id>: <summary or goal>`.

## Review

The reviewer is a different model family from the builder, reads that exact head, and does not push. The comment is the whole record:

```text
Review #<n> at <sha7>

- <blocking|nit> <path>:<line>: <what is wrong> Fix: <what to do>

VERDICT: <APPROVE|CHANGES> at <sha7>
```

`<sha7>` is the first 7 lowercase hex characters of the head. The two shas match. `APPROVE` has no `blocking` finding. `CHANGES` has at least one. A `nit` does not block. Blank lines are ignored. No other lines. Examples: [examples/review-approve.md](examples/review-approve.md) and [examples/review-changes.md](examples/review-changes.md).

## Merge

Merge only when the latest verdict is `APPROVE` at the current head, required CI is green on that head, and the forge reports a clean merge. Use the repo's merge queue when it has one. Do not force-push and do not use an admin bypass. A new commit needs a new review. A non-empty `gates` list stops the merge. Forge names are in [forges.md](../agent-issue/forges.md).
