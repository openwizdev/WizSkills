# Fleet settings

WizSkills changes use the ticket and approved plan in [OpenWiz](https://github.com/openwizdev/OpenWiz/issues). The builder and reviewer work as individual agents.

## Builder

| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Claude Code | `--provider claude-code` |
| Model | Opus 5.5 | `--model claude-opus-5-5` |
| Effort | High | `--reasoning-level high` |

## Builder for small tickets

| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Codex | `--provider codex` |
| Model | Sol 6.1 | `--model gpt-6.1-sol` |
| Effort | High | `--reasoning-level high` |

## Reviewer for Claude-built

| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Codex | `--provider codex` |
| Model | Sol 6.1 | `--model gpt-6.1-sol` |
| Effort | High | `--reasoning-level high` |

## Reviewer for GPT-built

| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Claude Code | `--provider claude-code` |
| Model | Opus 5.5 | `--model claude-opus-5-5` |
| Effort | High | `--reasoning-level high` |

New assignments follow the current orchestrator ruling. Existing agents keep their assignments. The reviewer is always from the other family. Source for the default tables: [OpenWiz fleet settings](https://github.com/openwizdev/OpenWiz/blob/main/docs/agents/fleet.md).

## Test commands

Run `python3 check/run.py` at the repository root, or `python3 check/run.py --shard <name>[,<name>...]` for the shards `python3 check/run.py --list` names ([check shards contract](../../contracts/check-shards.v1.md)). The hosted workflow runs one job per listed shard with `TEST_JOBS=2`, installing the pinned test-only browser tools only in the shards whose skill names `playwright-core`, and the changeset and comment gates in their own job. Source: [WizSkills CI](../../.github/workflows/ci.yml).

Evidence (red and green runs, logs, screenshots, review captures) goes in the pull request's description or comments, never in the tree.

## CI checks

| Check | Runs | Required by fleet on |
| --- | --- | --- |
| `check` | Passes only when every job passed: one job per shard from `run.py --list` (skill rules, standalone check and every skill suite) and the gates job; on pull requests, merge groups and pushes to `main` | Pull requests to `main` at the exact proposed head |

## Standing merge rules

The fleet verifies the selected other-family reviewer's APPROVE and a passing `check` at the same PR head. It admits the merge with `PUT /repos/openwizdev/WizSkills/pulls/<number>/merge` and `sha` set to that head, then reads the result back. Jake's release and publication decisions are separate. Source: [WizSkills setup ruling](https://github.com/jparker2006/ClosedWiz/issues/3065#issuecomment-6998365073).

## GitHub identity

| Setting | Value |
| --- | --- |
| Record authors | `openwiz[bot]`, `jparker2006` |

Source: [OpenWiz GitHub identity settings](https://github.com/openwizdev/OpenWiz/blob/main/docs/agents/fleet.md#github-identity) and the verified fallback account.
