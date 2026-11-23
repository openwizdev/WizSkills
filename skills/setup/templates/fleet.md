# Fleet settings

Every fleet in this project starts from these settings. The fleet skills read this file instead of naming any project's agents, commands or rules. Each value names its source; when a source changes, run the `setup` skill again (or edit the line by hand) so the two agree.

## Models

One table for every agent the fleet starts, in the models contract's form (`openwiz.models.v1`). The Orchestrator starts each spec's fleet thread. The Builder builds each ticket on its own branch, and never reviews or merges. The Reviewer reviews each pull request's exact head, and never edits. The Small builder (tickets with an exact `polish`, `huntr` or `proposal` label) and the Fixer follow the Builder unless their row names a choice of its own. A pull request is reviewed by the other model family than its builder: the Reviewer, or the Builder when the Reviewer is the builder's family; otherwise the review waits, and is never swapped for another model. To change a row, edit it by hand or run `setup` again.

| Role | Harness | Model | Effort | `room-cli thread spawn` flags |
| --- | --- | --- | --- | --- |
| Orchestrator | <harness, for example Claude Code> | <model, for example Opus 5.5> | <effort, for example Medium> | `--provider <id> --model <id> --reasoning-level <level>` |
| Builder | <harness, for example Claude Code> | <model, for example Opus 5.5> | <effort, for example Medium> | `--provider <id> --model <id> --reasoning-level <level>` |
| Reviewer | <harness from the other family, for example Codex> | <model, for example Sol 6.2> | <effort, for example Medium> | `--provider <id> --model <id> --reasoning-level <level>` |
| Small builder | follows Builder | | | |
| Fixer | follows Builder | | | |

Source: <a linked source file, or decider, date and plain decision with a Markdown private-record comment link>.

## Roster

Who may take which role, in the roster contract's form (`openwiz.roster.v1`). It starts with one entry: the person's own harness, which may take every role, on the driver setup chose. Every entry writes on GitHub as the person's own OpenWiz App, the person being the GitHub login that owns it. A fleet gives a role only to an entry that lists it, the first in table order. To add a host or a bot, add its row by hand and run `setup`'s check.

| Name | Kind | Driver | Roles | Writes as |
| --- | --- | --- | --- | --- |
| <the person's harness, for example Claude Code> | harness | <driver, for example local> | orchestrator, builder, reviewer, helper | <the person's GitHub login>'s App |

## Labels

The triage labels and their names here are in `triage-labels.md`. A fleet adds one label of its own:

| Label | Means | Put on by | Taken off by |
| --- | --- | --- | --- |
| `held` | The ticket is held: it waits for the user's approval of a changed plan or contract, and never starts while it has this label. It has no ready label while held | `to-tickets`, before it changes an approved plan; `launch-fleet`, when a merge changes a contract the ticket relies on | `to-tickets`, as it puts the ready label back once the new approval is recorded; `launch-fleet`'s `release` line, if it is still on after that |

The skill that holds a ticket first creates the label, once, with the description "Held: waits for the user's approval".

Source: the fleet skills, `to-tickets` and `launch-fleet`, which put it on and take it off. It is the same in every project.

## Test commands

The full set, in this order. A builder runs all of it locally, and opens its pull request only when every command passes. <Toolchain versions, as the instructions file gives them.>

<isolation rule, optional: project-specific restrictions on concurrent commands and shared build output, with their source; omit if none>

| # | Folder | Command | CI check |
| --- | --- | --- | --- |
| 1 | <root, or `<folder>`> | `<command, exactly as the source spells it>` | `<the check that runs it>` |

Source: <the instructions file's commands, linked>, and <the CI workflow, linked>.

## CI checks

| Check | Runs | Required on |
| --- | --- | --- |
| `<job name>` | <the test commands it runs, by number> | `<branch>` |

<What the user should know about these checks: how a draft or a docs-only change shows, for example.>

Source: <the CI workflow, linked>, and the branch rules (`gh api 'repos/{owner}/{repo}/rulesets'`).

## Approval rules

What the fleet's agents must ask before doing: each rule asks its named approver first, and a plan or machine approval grants none. To change a rule or add one, edit its line by hand; each starts `Ask before` and names a person, never "the user".

| Rule | Approver |
| --- | --- |
| Ask before publishing a release, a tag or a package | <the person's name or GitHub login> |
| Ask before spending money or credits beyond the recorded limits | <the person's name or GitHub login> |
| Ask before adding, reading or changing a secret | <the person's name or GitHub login> |
| Ask before deleting user data | <the person's name or GitHub login> |
| Ask before a cut-over | <the person's name or GitHub login> |
| Ask before installing the repository webhook | <the person's name or GitHub login> |

Source: <decider, date and plain decision with a Markdown private-record comment link>.

## Standing merge rules

| Pull request | Review | Merged by, and when |
| --- | --- | --- |
| <kind of pull request> | <who reviews it, or none> | <who merges it, and the exact conditions> |

<With no rule recorded: "None yet: every merge waits for the user.">

Source: <linked source files, or decider, date and plain decision with a Markdown private-record comment link>.

## GitHub identity

| Setting | Value |
| --- | --- |
| Record authors | `<app-slug>[bot]`, `<the login of the account the fleet falls back to>` |
| App identity | off |

`App identity` stays `off`: nothing reads this row yet (OpenWiz #2394), so no value lets agents or `loop.sh` mint the App's token (`openwiz github token`).

Source: <the App's settings, and `gh api user` on the account the fleet runs as>.
