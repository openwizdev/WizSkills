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

Run `python3 check/run.py` at the repository root. The hosted workflow installs the pinned test-only browser tools first and runs the suite with `TEST_JOBS=2`. Source: [WizSkills CI](../../.github/workflows/ci.yml).

## CI checks

| Check | Runs | Required by fleet on |
| --- | --- | --- |
| `check` | Skill rules, standalone check and every skill suite | Pull requests to `main` at the exact proposed head |

## Standing merge rules

The fleet verifies the selected other-family reviewer's APPROVE and a passing `check` at the same PR head. It admits the merge with `PUT /repos/openwizdev/WizSkills/pulls/<number>/merge` and `sha` set to that head, then reads the result back. Jake's release and publication decisions are separate. Source: [WizSkills setup ruling](https://github.com/jparker2006/ClosedWiz/issues/3065#issuecomment-6998365073).

## GitHub identity

| Setting | Value |
| --- | --- |
| Record authors | `openwiz[bot]`, `jparker2006` |

Source: [OpenWiz GitHub identity settings](https://github.com/openwizdev/OpenWiz/blob/main/docs/agents/fleet.md#github-identity) and the verified fallback account.
