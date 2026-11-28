# Synthetic project fleet settings

## Models

| Role | Harness | Model | Effort | `room-cli thread spawn` flags |
| --- | --- | --- | --- | --- |
| Orchestrator | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |
| Builder | Claude Code | Sonnet 5.5 | Medium | `--provider claude-code --model claude-sonnet-5-5 --reasoning-level medium` |
| Reviewer | Codex | Sol 6.2 | Medium | `--provider codex --model gpt-6.2-sol --reasoning-level medium` |
| Small builder | Claude Code | Sonnet 5.5 | Low | `--provider claude-code --model claude-sonnet-5-5 --reasoning-level low` |

## Escalation

A heading with no table.
