# Fleet settings

Synthetic fixture for the selected-row cases (#2594's R3, #2793): Orchestrator and Builder share one Claude model at
different efforts, and Small builder and Reviewer share one Codex model at different efforts, so only the Models row
each start was really picked from says its effort.

## Models

| Role | Harness | Model | Effort | `room-cli thread spawn` flags |
| --- | --- | --- | --- | --- |
| Orchestrator | Claude Code | Opus 5.5 | High | `--provider claude-code --model claude-opus-5-5 --reasoning-level high` |
| Builder | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |
| Reviewer | Codex | Sol 6.2 | Medium | `--provider codex --model gpt-6.2-sol --reasoning-level medium` |
| Small builder | Codex | Sol 6.2 | Low | `--provider codex --model gpt-6.2-sol --reasoning-level low` |
| Fixer | follows Builder | | | |

## Roster

| Name | Kind | Driver | Roles | Writes as |
| --- | --- | --- | --- | --- |
| Takes Effort | host | takes-effort | orchestrator, builder, reviewer | syn-owner's App |
