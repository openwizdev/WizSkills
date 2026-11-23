# Fleet settings

Synthetic fixture for the effort cases (#2594): a Models table with no Effort column, so no role sets an effort.

## Models

| Role | Harness | Model | `room-cli thread spawn` flags |
| --- | --- | --- | --- |
| Orchestrator | Claude Code | Opus 5.5 | `--provider claude-code --model claude-opus-5-5` |
| Builder | Claude Code | Opus 5.5 | `--provider claude-code --model claude-opus-5-5` |
| Reviewer | Codex | Sol 6.2 | `--provider codex --model gpt-6.2-sol` |

## Roster

| Name | Kind | Driver | Roles | Writes as |
| --- | --- | --- | --- | --- |
| Takes Effort | host | takes-effort | builder | syn-owner's App |
| No Effort | host | no-effort | reviewer | syn-owner's App |
| Refuses Effort | host | refuses-effort | orchestrator | syn-owner's App |
