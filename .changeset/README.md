# Changesets

A pull request that changes a skill adds one changeset here: a Markdown file
(such as `build-ticket-fix-typo.md`) that names each skill it changes, with
that skill's bump, then one summary line for the release notes. Changesets
ignores a name starting with `.`, `README.md` in any case, `AGENTS.md`,
`CLAUDE.md` and `GEMINI.md`, so the gate refuses those as changesets.

```markdown
---
"build-ticket": patch
"review-ticket": minor
---

Builders read the decision record before the verdict.
```

- **patch:** wording or a fix. **minor:** a new step or ability. **major:**
  changed inputs, outputs or records (J205).
- Name every skill whose folder the pull request changes, even a test or script
  only. Only a skill's `version:` line changing (a release) needs no note.
- Name `"wizskills": <bump>` too, for the bundle, when the pull request adds,
  removes or renames a skill (`major` for a rename) or changes something for
  users outside any one skill. A removed skill needs it.
- Write the summary for users, one line. Don't edit `version:` yourself; the
  release does.

`python3 -I check/changesets.py check --base origin/main` runs the same gate as
CI. [docs/versions.md](../docs/versions.md) says how a release bundles the notes.
