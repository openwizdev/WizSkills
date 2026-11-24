# Fleet settings

Synthetic fixture for the effort cases (#2594): each role's first entry is one of the three effort drivers.

## Models

| Role | Harness | Model | Effort | `room-cli thread spawn` flags |
| --- | --- | --- | --- | --- |
| Orchestrator | Claude Code | Opus 5.5 | High | `--provider claude-code --model claude-opus-5-5 --reasoning-level high` |
| Builder | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |
| Reviewer | Codex | Sol 6.2 | Medium | `--provider codex --model gpt-6.2-sol --reasoning-level medium` |
| Small builder | follows Builder | | | |
| Fixer | follows Builder | | | |

## Roster

| Name | Kind | Driver | Roles | Writes as |
| --- | --- | --- | --- | --- |
| Takes Effort | host | takes-effort | builder | syn-owner's App |
| No Effort | host | no-effort | reviewer | syn-owner's App |
| Refuses Effort | host | refuses-effort | orchestrator | syn-owner's App |
