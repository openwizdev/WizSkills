# Fleet settings

Synthetic fixture for the roster contract (`openwiz.roster.v1`): refused (heading-form): an underlined Roster heading.

## Models

| Role | Harness | Model | Effort | `room-cli thread spawn` flags |
| --- | --- | --- | --- | --- |
| Orchestrator | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |
| Builder | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |
| Reviewer | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |
| Small builder | follows Builder | | | |
| Fixer | follows Builder | | | |

Roster
------

| Name | Kind | Driver | Roles | Writes as |
| --- | --- | --- | --- | --- |
| Demo Bot | bot | demo-bot | helper,orchestrator | syn-owner's App |
| Claude Code | harness | local | builder | syn-owner's App |
