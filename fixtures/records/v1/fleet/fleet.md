# Fleet settings

Every fleet in this project starts from these settings. The fleet skills read this file instead of naming any project's agents, commands or rules. Each value names its source; when a source changes, run the `setup` skill again (or edit the line by hand) so the two agree.

## Models

One table for every agent the fleet starts, in the models contract's form (`openwiz.models.v1`). The Orchestrator starts each spec's fleet thread. The Builder builds each ticket on its own branch, and never reviews or merges. The Reviewer reviews each pull request's exact head, and never edits. The Small builder (tickets with an exact `polish`, `huntr` or `proposal` label) and the Fixer follow the Builder unless their row names a choice of its own. A pull request is reviewed by the other model family than its builder: the Reviewer, or the Builder when the Reviewer is the builder's family; otherwise the review waits, and is never swapped for another model. To change a row, edit it by hand or run `setup` again.

| Role | Harness | Model | Effort | `room-cli thread spawn` flags |
| --- | --- | --- | --- | --- |
| Orchestrator | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |
| Builder | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |
| Reviewer | Codex | Sol 6.2 | Medium | `--provider codex --model gpt-6.2-sol --reasoning-level medium` |
| Small builder | follows Builder | | | |
| Fixer | follows Builder | | | |

Source: synthetic-owner, 2099-01-01: the synthetic settings..

## Roster

Who may take which role, in the roster contract's form (`openwiz.roster.v1`). It starts with one entry: the person's own harness, which may take every role, on the driver setup chose. Every entry writes on GitHub as the person's own OpenWiz App, the person being the GitHub login that owns it. A fleet gives a role only to an entry that lists it, the first in table order. To add a host or a bot, add its row by hand and run `setup`'s check.

| Name | Kind | Driver | Roles | Writes as |
| --- | --- | --- | --- | --- |
| Claude Code | harness | local | orchestrator, builder, reviewer, helper | synthetic-owner's App |

## Labels

The triage labels and their names here are in `triage-labels.md`. A fleet adds one label of its own:

| Label | Means | Put on by | Taken off by |
| --- | --- | --- | --- |
| `held` | The ticket is held: it waits for the user's approval of a changed plan or contract, and never starts while it has this label. It has no ready label while held | `to-tickets`, before it changes an approved plan; `launch-fleet`, when a merge changes a contract the ticket relies on | `to-tickets`, as it puts the ready label back once the new approval is recorded; `launch-fleet`'s `release` line, if it is still on after that |

The skill that holds a ticket first creates the label, once, with the description "Held: waits for the user's approval".

Source: the fleet skills, `to-tickets` and `launch-fleet`, which put it on and take it off. It is the same in every project.

## Test commands

The full set, in this order. A builder runs all of it locally, and opens its pull request only when every command passes. Python 3.12.

| # | Folder | Command | CI check |
| --- | --- | --- | --- |
| 1 | root | `python3 -m unittest` | `test` |

Source: [README.md](README.md), and [ci.yml](.github/workflows/ci.yml).

## CI checks

| Check | Runs | Required on |
| --- | --- | --- |
| `test` | 1 | `main` |

A draft runs the same check.

Source: [ci.yml](.github/workflows/ci.yml), and the branch rules (`gh api 'repos/{owner}/{repo}/rulesets'`).

## Approval rules

What the fleet's agents must ask before doing: each rule asks its named approver first, and a plan or machine approval grants none. To change a rule or add one, edit its line by hand; each starts `Ask before` and names a person, never "the user".

| Rule | Approver |
| --- | --- |
| Ask before publishing a release, a tag or a package | synthetic-owner |
| Ask before spending money or credits beyond the recorded limits | synthetic-owner |
| Ask before adding, reading or changing a secret | synthetic-owner |
| Ask before deleting user data | synthetic-owner |
| Ask before a cut-over | synthetic-owner |
| Ask before installing the repository webhook | synthetic-owner |

Source: synthetic-owner, 2099-01-01: the synthetic settings..

## Standing merge rules

| Pull request | Review | Merged by, and when |
| --- | --- | --- |
| Any | The Reviewer | The owner, by hand |

Source: synthetic-owner, 2099-01-01: the synthetic settings..

## GitHub identity

| Setting | Value |
| --- | --- |
| Record authors | `openwiz[bot]`, `synthetic-owner` |
| App identity | off |

The App identity row stays `off` until the user turns it on with exactly `on` (OpenWiz #2835). Any other value, a second such row, or the table moved or wrapped in other markup reads as off, and `settings.py check` names it.

Source: the App's settings.
