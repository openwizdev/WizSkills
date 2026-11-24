# Fleet settings

Synthetic fixture for the roster contract (`openwiz.roster.v1`): Model names of 45 and 46 characters, at the status note's 60-character limit.

## Models

| Role | Harness | Model | Effort | `room-cli thread spawn` flags |
| --- | --- | --- | --- | --- |
| Orchestrator | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |
| Builder | Claude Code | Synthetic Long Display Name For Edge Case 45x | Medium | `--provider claude-code --model syn-model-45 --reasoning-level medium` |
| Reviewer | Codex | Synthetic Long Display Name For Edge Case 46xy | Medium | `--provider codex --model syn-model-46 --reasoning-level medium` |
| Small builder | follows Builder | | | |
| Fixer | follows Builder | | | |

## Roster

| Name | Kind | Driver | Roles | Writes as |
| --- | --- | --- | --- | --- |
| Claude Code | harness | local | builder | syn-owner's App |
| Codex | harness | local | reviewer | syn-owner's App |
