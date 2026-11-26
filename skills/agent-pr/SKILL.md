---
name: agent-pr
description: Open the one pull request for one agent issue, with proof and a strict review. Use when building or reviewing that issue; not for filing the issue.
version: 0.1.0
---

# Agent PR

Open one pull request that makes one ready issue true. One issue, one branch, one pull request. You build it or you review it, never both. The reviewer is a different model family, reads that exact head, and does not push.

## Guards

- The issue lints and `ready` is `ready-for-agent`. If it does not, stop and use [agent-issue](../agent-issue/SKILL.md).
- Touch only paths the issue's `owned_paths` cover.
- Do not merge while `gates` is non-empty. Stop for a human.
- Never force-push. A new head needs a new review.
- No secrets or private data in the record, the review, or the commits.

## 1. Branch and title

Branch `<agent>/<repo>-<N>-<lane>`, for example `ada/widgets-14-build`. `N` is the issue `id`. The title is `#<N>: <summary or goal>` when `N` is a number, otherwise `<id>: <summary or goal>`.

```sh
python3 -I <installed-agent-issue>/scripts/lint.py branch --name <branch> --repo <repo> --issue-id <id>
python3 -I <installed-agent-issue>/scripts/lint.py title --title "<title>" --issue-id <id> --expect "<summary or goal>"
```

Done when both commands exit 0.

## 2. Body

Read [spec.md](spec.md) and copy [template.md](template.md). `changes` and `proof` cover every acceptance id once. The proof command is that item's check. For a bug, one proof has `red_first` true because the test failed before the fix. Before review, every `result` is `pass`. Use `--mode draft` only while a proof still fails.

```sh
python3 -I <installed-agent-issue>/scripts/lint.py pr --body-file body.md --issue-file issue.md
```

Done when this exits 0. One open pull request closes this issue. If one already exists, update it.

## 3. Review

Post one comment on that head. Do not edit the branch. The comment is the whole record: a header, one finding per line, and a verdict. Lint it.

```sh
python3 -I <installed-agent-issue>/scripts/lint.py review --body-file review.md
```

`APPROVE` needs zero `blocking` findings. `CHANGES` needs one or more. Both shas are the head's first 7 lowercase hex characters. An example is [examples/review-approve.md](examples/review-approve.md).

Done when the comment lints and its sha is the head you read.

## 4. Merge

Merge only when all of these are true: the latest linted verdict is `APPROVE` and its sha is a prefix of the current head; required CI is green on that head; the forge reports a clean merge; you use the repo's merge queue when it has one, otherwise its normal merge. Do not use an admin bypass. If `gates` is non-empty, stop and name the gate.

Done when the pull request is merged and the issue is closed, or you have stopped at a human gate.

Read [forges.md](../agent-issue/forges.md) when you have not used this forge before.

**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.
