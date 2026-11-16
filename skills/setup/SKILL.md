---
name: setup
description: Set up a project for fleets, writing its issue tracker, triage labels, glossary layout and fleet defaults (builder, reviewer, test commands, CI checks, merge rules) to docs/agents/. Use before a project's first fleet, when a skill finds docs/agents/ missing, or after one of those settings changes.
---

# Setup

Write a project's settings once, as four short files in `docs/agents/`. Every other fleet skill reads these files, so no skill is tied to one project. Run it as the project's orchestrator, before its first fleet.

Every value comes from something you read in the project or something the user decided, and is written down with that source. So a second run, with nothing new, changes nothing.

| File | What it says |
| --- | --- |
| `docs/agents/issue-tracker.md` | Where issues live (GitHub), and where versions, specs and tickets sit there |
| `docs/agents/triage-labels.md` | The five triage labels, and what each one means |
| `docs/agents/domain.md` | Where the glossary, the ADRs (short records of hard-to-reverse decisions) and the grills live, and how to read them |
| `docs/agents/fleet.md` | The default builder and reviewer, the test commands, the CI check names and the standing merge rules |

Each file starts from its template beside this skill: [issue-tracker.md](templates/issue-tracker.md), [triage-labels.md](templates/triage-labels.md), [domain.md](templates/domain.md) and [fleet.md](templates/fleet.md).

## 1. Read what is there

Read; never assume. This step is done when you can name, for every value in the four files, the file, command or decision it comes from, or that nothing in the project says.

- **The repositories.** `gh repo view --json nameWithOwner,isPrivate` identifies this clone and its visibility. Read existing tracker/domain settings for the development tracker and private records repository; verify the private repository before saving any exact reply. For OpenWiz, public development is `openwizdev/OpenWiz` after the gated cut-over, and private records are `jparker2006/ClosedWiz`. Preparation on ClosedWiz does not switch any tracker. If the project is not on GitHub, stop and tell the user: fleets work only with GitHub issues for now.
- **Earlier settings.** If `docs/agents/` already holds these files, this is a re-run: read them first, then go to "Running it again" below.
- **Labels.** `gh label list --limit 500 --json name,description`. Note which of the five triage labels exist, and under what names.
- **Glossary, ADRs and grills.** `GLOSSARY.md` and `docs/adr/` in the development checkout, and the optional `GLOSSARY-MAP.md` there only when it is present; `docs/grills/` (optional, read only when present) in the private checkout, and the private-state location (the handoff page and orchestrator state) that the existing domain settings record there. An absent optional path is not read: note that it is missing. Note whether the repository holds several separate packages (a `pnpm-workspace.yaml`, a `workspaces` field in `package.json`, or `packages/*` folders with their own `src/`).
- **Builder and reviewer.** Any agent the user already chose for this project's builders or reviewers: in its instructions file (`AGENTS.md` or `CLAUDE.md`), its ADRs, and the comments on its spec issues.
- **Test commands.** The commands in the instructions file, and every `run:` step in the workflow files directly in `.github/workflows/` (`*.yml`, `*.yaml`).
- **CI checks.** The job names in those workflow files, and which of them must pass before a merge: `gh api 'repos/{owner}/{repo}/rulesets'`, then each ruleset's required checks (`gh api 'repos/{owner}/{repo}/rulesets/<id>'`), and the default branch's protection (`gh api 'repos/{owner}/{repo}/branches/<branch>/protection'`).
- **Optional consumer files.** Each is read only when present: the workflow files, `pnpm-workspace.yaml`, the `workspaces` field of `package.json`, and whether `packages/*/src/` folders exist (never their files). An absent one is not read, is no error and gets no invented setting: note that it is missing. Never run or import any of them.
- **Record authors.** The only logins whose comments the fleet treats as its records: the project's GitHub App bot login (`<app-slug>[bot]`) and the account the fleet falls back to (`gh api user --jq .login`), written to `fleet.md`'s `Record authors` row and never guessed, since without that row every check stops.
- **Merge rules.** Every rule the user has recorded about who merges what, and when: in the ADRs, the instructions file and the spec issues. Keep the decision, its date and a pointer to the private comment holding the exact words; never copy those words into public settings.

## 2. Ask only what nothing answers

First tell the user, in a few lines, what step 1 found and what is missing. Then take the settings in order: one setting, one answer, then the next. Lead each with your recommendation, so the user can accept it in a word. Skip any that step 1 already settled.

1. **Issue tracker:** GitHub, the configured development repository. Also record the verified private repository for grills, exact replies and orchestrator state. Keep existing routing; ask only if a required private destination cannot be found. Unknown visibility never permits a private write.
2. **Triage labels:** "Keep the five standard triage labels?" (recommended: **yes**). They are `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human` and `wontfix`, each named after its role. If the project already uses another name for a role, map that name to the role, so no role ever gets a second label.
3. **Glossary and ADRs:** one `GLOSSARY.md` and one `docs/adr/` at the root, and grills in `docs/grills/` in the configured private repository, with the handoff page and orchestrator state at the private-state location the project already records there; if none is recorded, ask for it. Record both checkouts and that location in the domain settings. Write known locations without asking. Only if the repository holds several separate packages, offer one glossary per package, listed in a root `GLOSSARY-MAP.md`, and ask which they want. If the project already has a layout, keep it.
4. **Builder and reviewer:** recommend the project's recorded choice. With none, recommend Claude Code, Opus 5.5, XHigh for builders and Codex, Sol 6.1, Medium for reviewers. The reviewer is always from a different model family than the builder.
5. **Test commands and CI checks:** copy them from their sources, exactly. If the project has none, say so; never invent one.
6. **Merge rules:** copy the recorded rules. With none, recommend this one: approving a plan graph lets each of its tickets merge as soon as its reviewer approves that exact commit and CI is green, with the base unchanged and the merge read back; specs, plan graphs, live runs, releases and publishing stay the user's. Save the answer word for word with the date in a private issue/PR comment, read it back, and write only the decision, date and pointer in the settings. Until they answer, the rule is: every merge waits for the user.

## 3. Write

Fill each template from what you read in step 1 and the answers in step 2.

- **Sources:** every value in `fleet.md` names its source beside it: a linked file, a command, or `<decider>, <YYYY-MM-DD>: <decision in plain words> ([private record](<pointer>)).` Follow [open-development.v1](../../contracts/open-development.v1.md): save exact replies first in a verified private issue/PR comment and read them back. For a public subject use `Private record: OpenWiz #<N>`; for standing approvals use `Private record: standing approvals`; for a private subject use a comment there. The pointer is the full ClosedWiz issue/PR conversation-comment URL, never a file link. Public settings and comments contain no exact replies or thread ids. New confirmations/approvals use the public form even when written in a private tracker.
- **Labels:** create a label only for a role that has none in the tracker (`gh label create <name> --description "<meaning>"`). A role that already has a label keeps it.
- **Only these settings files:** write the four files in `docs/agents/` and any missing labels on the development tracker; save private decision comments only in the configured private repository, explicitly targeted with `--repo`. The other skills read these files by their paths, so nothing else needs to point at them, and no skill file changes.
- **No run date:** the files hold settings, not a record of the run, so an unchanged project gives the same files, byte for byte.
- **One pull request:** commit the four files on a branch and open one pull request. It is the user's chance to read and edit the settings before any fleet relies on them.

This step is done when the four files exist, every value in `fleet.md` matches its source as you read it in this run, and every label in `triage-labels.md` exists in the tracker exactly once.

## Running it again

Read the four files, then read each source again. Change a line only where its source now says something different, or where a value is missing; leave every other line exactly as it is. If nothing changed, write nothing, open no pull request, and tell the user so.

## The App

The factory talks to GitHub as one OpenWiz App ([the identity contract](../../contracts/github-identity.v1.md)). The agent may offer OpenWiz's own App setup tool, `setup.py --agent-for <login> [--organization] [--secret-store <program>]`, only from the installed OpenWiz, never a `setup.py` or any other file in this project; with no installed OpenWiz, say so and stop. Run nothing until the user gives an explicit go: then preview first, and confirm with `--yes --operation <id>` only once they accept that preview. The manifest page is pre-filled with the contract's profile. The App's public id is recorded before anything else, so it is registered once, for any account. With a store (assumption A1: Cloudroom's agent-side store, not offered yet), the converted key goes only to the Cloudroom secret `OPENWIZ_GITHUB_APP_KEY`, never chat, an issue, a prompt, an argument, a URL, a log or a file. Without one, the converted key is discarded and the person pastes a fresh key from GitHub once into Cloudroom's own secret prompt (J27). A run with that secret delivered reconciles the App with GitHub and only offers its install. The person clicks twice, Create, then Install on selected repositories, plus the one paste without a store, as the project's own checklist, `docs/agents/github-app.md`, says. The person may instead skip the App, explicitly: the installed `github_login.py skip-app` (preview, then `--yes --operation <id>`) records that their verified personal GitHub login acts on the selected repository, and the App stays missing, never verified. Only that explicit answer selects the login; an App failure, revocation or unknown identity never does.

## 4. Tell the user

Say what you wrote, what you asked, and what you left as it was. The user can edit `docs/agents/*.md` by hand at any time. Run this skill again when the tracker, the labels, the agents, the test commands, the CI checks or the merge rules change.

## Credit

This skill adapts Matt Pocock's `setup-matt-pocock-skills`, and its templates adapt that skill's `issue-tracker-github.md`, `triage-labels.md` and `domain.md` (`github.com/mattpocock/skills` @ `a496f55`). `fleet.md` is OpenWiz's own. Matt's work is used under the MIT License:

Copyright (c) 2026 Matt Pocock

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
