<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/openwizdev/.github/main/profile/art/wiz.png">
  <img alt="The OpenWiz Wiz" src="https://raw.githubusercontent.com/openwizdev/.github/main/profile/art/wiz.png" width="56">
</picture>

# WizSkills

**The skills your agents follow to run an [OpenWiz](https://github.com/openwizdev/OpenWiz) factory: grill, spec, tickets, build, review, merge.** OpenWiz is the kernel; WizSkills is what the agents actually do on top of it.

**Status:** release 0.1.2. 0.2.0 is coming soon. Works with Claude Code, Codex, or any agent that can read a file.

## Quick start

On Claude Code, install the plugin pinned to this release, then start a new session:

```sh
claude plugin marketplace add https://github.com/openwizdev/WizSkills.git#v0.1.2
claude plugin install openwiz@wizskills --scope project
```

Codex and other agents: see [docs/install.md](docs/install.md), which also shows how to check a release before you run it.

## How it works

A skill is a folder, `skills/<name>/`, with a `SKILL.md` your agent reads and the scripts and tests beside it. On Claude Code each is named `openwiz:<name>`. The main path through a factory:

| Step | Skill | What the agent does |
| --- | --- | --- |
| You decide | [`grill`](skills/grill/SKILL.md) | Asks you a few questions and records your answers |
| Plan | [`to-spec`](skills/to-spec/SKILL.md), [`to-tickets`](skills/to-tickets/SKILL.md) | Turns your answers into a spec, then sized tickets |
| Build | [`launch-fleet`](skills/launch-fleet/SKILL.md), [`build-ticket`](skills/build-ticket/SKILL.md) | Starts builders; each builds one ticket into one pull request |
| Review | [`review-ticket`](skills/review-ticket/SKILL.md) | A reviewer from another model family checks it before merge |
| Watch | [`where-are-we`](skills/where-are-we/SKILL.md) | Tells you where things stand |

Every skill is listed in [skills/README.md](skills/README.md). Skills write their records to GitHub by OpenWiz's [records rules](https://github.com/openwizdev/OpenWiz/blob/main/kernel/records.v1.md). WizSkills supplies no credentials: your agent uses its own signed-in tools.

## Links

- [Install guide](docs/install.md) · [Versions and releases](docs/versions.md) · [Changelog](CHANGELOG.md)
- [OpenWiz](https://github.com/openwizdev/OpenWiz) · [openwiz.dev](https://openwiz.dev) · [all repos](https://github.com/openwizdev)
- To report a problem, ask your agent to file a GitHub issue.
- [Apache License 2.0](LICENSE). [NOTICE](NOTICE) collects the upstream notices; each adapted skill keeps its own `NOTICE.md`.
