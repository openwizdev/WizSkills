# Fleet settings

Synthetic fixture for the roster contract (`openwiz.roster.v1`): the starting Roster setup writes: one row, the person's own harness, every role.

## Models

| Role | Harness | Model | Effort | `room-cli thread spawn` flags |
| --- | --- | --- | --- | --- |
| Orchestrator | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |
| Builder | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |
| Reviewer | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |
| Small builder | follows Builder | | | |
| Fixer | follows Builder | | | |

## Roster

| Name | Kind | Driver | Roles | Writes as |
| --- | --- | --- | --- | --- |
| Claude Code | harness | local | orchestrator, builder, reviewer, helper | syn-owner's App |
