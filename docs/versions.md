# WizSkills versions

WizSkills uses semantic versions, starting at 0.1.0, and stays on 0.x while
the skills settle. A release is the annotated Git tag `v<version>` on `main`,
whose message records the release's commit and tree, a section of
[CHANGELOG.md](../CHANGELOG.md) with its date and one line per change, and the
same version in `.claude-plugin/plugin.json`. A released tag never moves.

Each skill also has its own semantic version, the `version:` line of its
`SKILL.md` front matter (J205): patch for wording or a fix, minor for a new
step or ability, major for changed inputs, outputs or records. Every skill
starts at 0.2.0, the release that rewrote them all.

A release is a bundle of skill versions (J206). Each pull request that changes
a skill adds one note under [.changeset/](../.changeset/README.md), and CI fails
it without one. At release, `python3 -I check/changesets.py release` runs the
pinned [Changesets](https://github.com/changesets/changesets) over the pending
notes and prints each skill's bump and the CHANGELOG section; `--write` applies
them. The bundle's own bump is:

- **major** when something breaks for a user: a skill's major bump, or a note
  naming `"wizskills": major` (such as a renamed skill);
- **minor** when many change: a skill added or removed since the last release,
  more than three skills changed, or a skill's minor bump;
- **patch** otherwise: up to three skills, all fixes.

Changesets is a release tool only (`npm ci` installs it from
`package-lock.json`); no skill depends on it.
