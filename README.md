<img alt="The OpenWiz Wiz" src="https://raw.githubusercontent.com/openwizdev/.github/main/profile/art/wiz.png" width="56">

# WizSkills

Part of [OpenWiz](https://openwiz.dev), the open source agent factory.

The skills coding agents follow to run an [OpenWiz](https://github.com/openwizdev/OpenWiz) agent factory: grill, spec, tickets, build, review, merge. Each skill is a `SKILL.md` that Claude Code, Codex or any agent can read.

## Install (Claude Code, release v0.5.0)

```sh
claude plugin marketplace add https://github.com/openwizdev/WizSkills.git#v0.5.0
claude plugin install openwiz@wizskills --scope project
```

`--scope project` enables it for this project only. Then start a new session. Codex and other agents: [docs/install.md](docs/install.md).

## Main skills

- [`grill`](skills/grill/SKILL.md): maps every decision, posts one question at a time to the configured channel, and records your yes.
- [`to-spec`](skills/to-spec/SKILL.md) and [`to-tickets`](skills/to-tickets/SKILL.md): turn answers into a spec, then sized tickets.
- [`launch-fleet`](skills/launch-fleet/SKILL.md) and [`build-ticket`](skills/build-ticket/SKILL.md): one builder per ticket, one pull request each.
- [`review-ticket`](skills/review-ticket/SKILL.md): a reviewer from another model family checks before merge.
- [`where-are-we`](skills/where-are-we/SKILL.md): tells you where things stand.

All skills and how to check a change: [skills/README.md](skills/README.md).

[Releases](docs/versions.md) · [Changelog](CHANGELOG.md) · [openwiz.dev](https://openwiz.dev) · [Apache-2.0](LICENSE) · [NOTICE](NOTICE)
