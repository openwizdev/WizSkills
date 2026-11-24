# Fleet settings

Synthetic fixture for the roster contract (`openwiz.roster.v1`): a harness, a host and a bot entry, in the order the fleet prefers them.

## Models

| Role | Harness | Model | Effort | `room-cli thread spawn` flags |
| --- | --- | --- | --- | --- |
| Orchestrator | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |
| Builder | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |
| Reviewer | Codex | Sol 6.2 | Medium | `--provider codex --model gpt-6.2-sol --reasoning-level medium` |
| Small builder | follows Builder | | | |
| Fixer | follows Builder | | | |

## Roster

Who may take which role. Every entry writes as the same person's App.

| Name | Kind | Driver | Roles | Writes as |
| --- | --- | --- | --- | --- |
| Demo Bot | bot | demo-bot | orchestrator | syn-owner's App |
| Claude Code | harness | cloudroom | builder, reviewer | syn-owner's App |
| Codex | harness | cloudroom | reviewer | syn-owner's App |
| Own computer | host | local | builder, helper | syn-owner's App |

## Loop

Not the Roster: readers skip it.
