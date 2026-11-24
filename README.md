<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/openwizdev/.github/main/profile/art/wiz.png">
  <img alt="The OpenWiz Wiz" src="https://raw.githubusercontent.com/openwizdev/.github/main/profile/art/wiz.png" width="56">
</picture>

# WizSkills

**The skills coding agents follow to run an [OpenWiz](https://github.com/openwizdev/OpenWiz) agent factory: grill, spec, tickets, build, review, merge.**

Latest release: [v0.4.2](https://github.com/openwizdev/WizSkills/releases/tag/v0.4.2), 20 skills. On Claude Code, run this in your project, then start a new session:

```sh
claude plugin marketplace add https://github.com/openwizdev/WizSkills.git#v0.4.2 && claude plugin install openwiz@wizskills --scope project
```

Codex or any agent that can read a file: [docs/install.md](docs/install.md).

| Step | Skill | What the agent does |
| --- | --- | --- |
| You decide | [`grill`](skills/grill/SKILL.md) | Asks you a few questions and records your answers |
| Plan | [`to-spec`](skills/to-spec/SKILL.md), [`to-tickets`](skills/to-tickets/SKILL.md) | Turns your answers into a spec, then sized tickets |
| Build | [`launch-fleet`](skills/launch-fleet/SKILL.md), [`build-ticket`](skills/build-ticket/SKILL.md) | Starts builders; each builds one ticket into one pull request |
| Review | [`review-ticket`](skills/review-ticket/SKILL.md) | A reviewer from another model family checks it before merge |
| Watch | [`where-are-we`](skills/where-are-we/SKILL.md) | Tells you where things stand |

Each skill is a folder, `skills/<name>/`, with a `SKILL.md` the agent reads plus its scripts and tests; on Claude Code it is `openwiz:<name>`. All skills: [skills/README.md](skills/README.md). Skills write their records to GitHub by OpenWiz's [records rules](https://github.com/openwizdev/OpenWiz/blob/main/kernel/records.v1.md) and use your agent's own signed-in tools; WizSkills supplies no credentials.

## Links

- [Install guide](docs/install.md) (also: checking a release, running the tests) · [Versions](docs/versions.md) · [Changelog](CHANGELOG.md)
- [OpenWiz](https://github.com/openwizdev/OpenWiz) · [openwiz.dev](https://openwiz.dev) · [all repos](https://github.com/openwizdev)
- Report a problem: ask your agent to file a GitHub issue.
- [Apache License 2.0](LICENSE). [NOTICE](NOTICE) collects upstream notices; each adapted skill keeps its own `NOTICE.md`.
