# Fleet settings

Synthetic fixture for the roster contract (`openwiz.roster.v1`): a namespaced model id driver v1 can't carry, and a Builder's configured High effort, which its note names.

## Models

| Role | Harness | Model | Effort | `room-cli thread spawn` flags |
| --- | --- | --- | --- | --- |
| Orchestrator | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |
| Builder | Claude Code | Opus 5.5 | High | `--provider claude-code --model claude-opus-5-5 --reasoning-level high` |
| Reviewer | Codex | vendor/demo | Medium | `--provider codex --model vendor/demo --reasoning-level medium` |
| Small builder | follows Builder | | | |
| Fixer | follows Builder | | | |

## Roster

| Name | Kind | Driver | Roles | Writes as |
| --- | --- | --- | --- | --- |
| Claude Code | harness | local | builder | syn-owner's App |
| Codex | harness | local | reviewer | syn-owner's App |
