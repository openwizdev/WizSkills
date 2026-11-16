---
name: onboard
description: Onboard a new OpenWiz user from install to a first fleet. Explain the factory in a few lines, offer fun quick ideas with a disposable demo repository by default or their own repository, connect GitHub (the user's own App or an explicit skip), prepare the project and its private brain once, grill a fresh idea briefly toward 4 to 7 small tickets, reuse the recorded harness, model and effort and ask Cloud or Local, then follow plan-graph's spec confirmation and exact-plan approval and start the first fleet through launch-fleet. Use after install, when a user asks to try OpenWiz, or to resume an interrupted first fleet.
---

# Onboard

Take a new user from a fresh install to their **first fleet**: a fresh idea of theirs, grilled briefly, planned as 4 to 7 small tickets, approved by them, and built by agents they can watch. The wow is seeing several agents start on the user's own idea within minutes, so keep every step short.

This skill only connects the existing skills and installed tools. It reuses [`grill`](../grill/SKILL.md), [`setup`](../setup/SKILL.md), [`plan-graph`](../plan-graph/SKILL.md) and [`launch-fleet`](../launch-fleet/SKILL.md), the installed setup, GitHub sign-in, App and `openwiz init` tools that the [`install`](../install/SKILL.md) skill names, and the agent CLI as [`contracts/cli.v1.md`](../../contracts/cli.v1.md) defines it. It adds no approval, no planner, no sign-in routine and no engine of its own, and it never runs `openwiz engine` or `openwiz fleet tick`.

**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.

## Rules for the whole journey

- **Install permission is not work approval.** Installing OpenWiz, finishing setup or saying yes to this skill approves no spec, no plan and no start. Only plan-graph's separate spec confirmation and its exact-plan approval let tickets start, and only through the existing launch rules. Never write, fake or infer an approval, and never ask for a blanket yes to future work.
- **Every effect is shown first, then waits for a yes.** Before creating a repository, signing in, creating or skipping an App, saving project settings, creating the brain or starting agents that spend Cloud Credits, list exactly what will happen (names, counts, where it runs, what it may cost, labelled measured, estimated or unknown) and wait for the user's explicit yes to that list. No yes, no effect. Model-provider charges are separate from Cloud Credits.
- **No prewritten plan.** There is no demo plan, ticket list or template project in this skill. Every spec and ticket comes from this user's grill, in this conversation.
- **The size is for the first fleet only.** Aim for 4 to 7 small tickets so the first fleet is quick and cheap. It is no limit on any later fleet, and it never shrinks a later plan.
- **Use the agent CLI's JSON, never its screen.** Run `openwiz` commands with `--json` where the catalogue (`openwiz help --agent`) says they have it, and read exit codes as the contract defines them. Use the installed program by its absolute path.
- **Keep private things private.** The user's exact words go only where the project's private-record rules say (`contracts/open-development.v1.md`). No credentials in prompts, files, arguments or logs.
- **Interrupted is resumable.** Read the private state file, the installed setup state and GitHub first; continue from the first unfinished step. Never redo an effect already recorded: every installed tool reuses its operation id, and an uncertain one is reconciled, never repeated.
- **Every recorded choice is reused, never invented.** A choice already saved (the repository, the identity, the harness, model and effort) is carried forward and not asked again. A choice nothing recorded is asked, with a recommendation, never filled in. Spec confirmation, exact-plan approval and spending consent stay three separate answers.

The helper beside this skill, `scripts/onboard.py`, does the mechanical checks. Run it with Python 3 (standard library only) from the project's checkout, keep `--state` in owner-only private state outside the checkout, and pass the installed `openwiz` by absolute path where a command takes it. It prints plain lines; its exit codes are 0 done, 1 read failure, 2 usage, 5 refused (nothing started), 6 uncertain (never retried), 7 busy, 10 state unavailable, 12 preview awaiting `--yes`.

## 1. Explain

Say in a few plain sentences what OpenWiz does, before asking anything:

> You bring an **idea**. I **grill** you with a few quick questions to settle it, then write it up as a **spec** for you to confirm. The spec becomes small **tickets**, a plan you approve as a whole. Each ticket gets its own **builder**, an agent that writes the code on its own branch. A **reviewer** from a different model family reviews each pull request independently, and approved, green work **merges** by the project's rules. Nothing starts until you approve the plan.

Done when the user has seen it. Answer their questions briefly; don't lecture. When the `install` skill already gave it, it is done: don't repeat it.

## 2. Choose a project

Offer three or four **fun, quick ideas**, made up fresh for this user (a tiny game, a toy command-line tool, a one-page site about something they like), plus "your own idea". Ideas are one line each, never a plan.

Then ask where the work goes, recommending the first:

1. **A new disposable demo repository** (the default): one private GitHub repository, created with the user's own `gh` identity. Show its exact owner, name and visibility, and that it is new and safe to delete later; create it only after the user's yes to exactly that:

   ```sh
   python3 <this skill's folder>/scripts/onboard.py create-repo --state <private state file> --repo <owner>/<name>        # shows the effect
   python3 <this skill's folder>/scripts/onboard.py create-repo --state <private state file> --repo <owner>/<name> --yes  # on the yes
   ```

   It refuses a name that already exists, saves the name before it creates, makes one `gh repo create <owner>/<name> --private` and reads it back. If the outcome is uncertain (exit 6), run the same command again: it reads first and never creates twice. Then clone it and work there. The CloudRoom project stays the user's to make or pick in CloudRoom; `setup` then selects that existing project. This skill creates nothing in CloudRoom.
2. **One of the user's existing repositories:** confirm which one, and that a fleet will open branches and pull requests there.

Done when the user has picked an idea and a repository, and the repository is created and read back (or chosen). This one repository is carried through every later step; there is no second one.

## 3. Connect

Set up GitHub, the project and its private brain for that same repository, once, with the installed tools (`$build`, `<state>` and the rules are the `install` skill's). Each tool shows its effects first and applies only on the user's yes to exactly that preview. Sign-in confirms with `--yes` alone (it has no operation id); prepare, the skip and init confirm with `--yes --operation <id>` from their own preview. A repeat reuses the id and reads before it writes.

1. **GitHub sign-in:** `python3 -I -B "$build"/runtime/setup/github_login.py sign-in --repository <owner>/<name> --state-dir <state>`. A current login is reused. Signed out, it prints `login_needed` and its effects; on the user's yes, run the same command with `--yes`, and the user approves in GitHub's own browser page; no token is pasted. A browser opening is not a login: only the account and push-access read-back are.
2. **Prepare the project:** `python3 -I -B "$build"/runtime/setup/setup.py prepare --state-dir <state> --repository <owner>/<name> ...` with the CloudRoom project the user made or picked, and the harness, model and effort the user chooses here from `openwiz models --json` (each its own question, with a recommendation). These are recorded once and reused in step 5. The App and the skip both need this saved selection.
3. **The user's own App, or an explicit skip:** ask which, recommending the App. The App is the installed App tool of the `setup` skill's "The App": Create, then Install on selected repositories only, and its key only into CloudRoom's protected secret prompt. A skip is `github_login.py skip-app` (preview, then `--yes --operation <id>`): the user's personal login then acts, and the App stays missing, never verified. An App failure never becomes a skip: only the user's own answer does.
4. **The private brain:** `<build>/openwiz init --repository <owner>/<name> --state-dir <state> --json`, then the same with `--yes --operation <id>`. It reads the repository's visibility from GitHub and places the brain itself: in the private repository, or in a new private companion for public code. Say in one line where it went; there is no placement question. It opens a pull request with the brain's settings; the user merges it on GitHub. For a public repository's companion, Decisions reads the companion only when the private settings' `decision_repositories` pair (decisions.v1's repository roles, in `<state>/service/config.json`) names the code repository as public and the companion as private; `continue` refuses until it does. After that pull request is merged, connect it:

   ```sh
   python3 <this skill's folder>/scripts/onboard.py decisions --state <private state file> --setup-state <state>        # shows the effect
   python3 <this skill's folder>/scripts/onboard.py decisions --state <private state file> --setup-state <state> --yes  # on the yes
   ```

   It reads the companion pair from setup and, on the user's yes, sets only that one key: every other key of an existing settings file stays, a missing file is created with just that key, and a pair already set changes nothing. Ask the user to restart the OpenWiz server, then go on to step 5. A settings file holding only this pair suits the standalone server this install runs; a host that later runs the full OpenWiz service must complete its settings.
5. **Check, then carry it forward:** `python3 -I -B "$build"/runtime/setup/setup.py check --state-dir <state>`, then

   ```sh
   python3 <this skill's folder>/scripts/onboard.py continue --state <private state file> --setup-state <state> [--explained]
   ```

   (`--explained` when step 1, or the `install` skill, already gave the explanation). It carries the repository, CloudRoom project, acting identity, brain and prepared agents, and refuses, naming each one, while anything is missing, refused, unknown or out of date. A refused `continue` also withdraws what was carried before (the user's choices stay), so nothing starts on an old setup: the brain pull request not yet merged, a login without push access, an App chosen but not verified. Follow that component's `next` step and run the check and `continue` again.

Done when `continue` prints the carried setup and the acting identity.

## 4. Grill

Run the `grill` skill, briefly: one or two rounds of at most three questions, each with a recommendation the user can accept in a word. Steer the answers toward something 4 to 7 small, mostly independent tickets can build: the smallest version of the idea that still delights. Save every question and answer as `grill` says. Ask for its summary to be confirmed.

Done when the grill is confirmed.

## 5. Choose the agents

Read the offered options with `openwiz models --json` and save the output privately. The harness, model and effort were answered once in step 3 and are reused, not asked again. Ask the one question left, with a recommendation, never filling it in:

- **Where the fleet's agents run:** Cloud (recommended for the first fleet: fast, and it uses Cloud Credits) or Local (on the user's own computer).

Record it:

```sh
python3 <this skill's folder>/scripts/onboard.py choose --state <private state file> --options <saved models output> \
  --from-setup --agents cloud|local
```

It refuses settings the options don't offer and a harness the review rules don't cover (Claude Code and Codex). Without a carried setup (an onboarding resumed outside install), ask harness, model and effort as three questions and pass `--harness <provider> --model <model> --effort <effort>` instead. Then run the `setup` skill so **both** builder tables in `docs/agents/fleet.md`, `## Builder` and `## Builder for small tickets`, name exactly these settings, with the user's decision as their source, since any ticket of the fleet may later get a small-ticket label. Setup keeps the reviewers in the other model family. `launch` reads those tables and refuses otherwise.

**Local agents are not available yet:** launch-fleet starts the fleet thread and its builders in the Cloud. If the user chose Local, say so plainly, and offer Cloud or stopping here. `launch` refuses Local and starts nothing.

Done when the choices are recorded and the builder settings match them.

## 6. Plan

Run `plan-graph` from the confirmed grill, unchanged: write the spec, show it, and wait for the user's **spec confirmation**; propose 4 to 7 small tickets with disjoint owned paths and as few arrows as the work allows, so several can start at once; write them; then wait for the user's **exact-plan approval** of the graph as written, recorded with its revision and fingerprint. A reply that asks for a change is not an approval. Then record which spec this onboarding planned:

```sh
python3 <this skill's folder>/scripts/onboard.py spec --state <private state file> --spec <spec number> --repo <owner>/<name>
```

It checks the checkout is that repository and saves it; every later command refuses to run in another repository.

Done when plan-graph's approval record is on the spec and current.

## 7. Launch

The first fleet starts the way launch-fleet starts every fleet: one fleet thread for the spec, with its own loop. Preview first:

```sh
python3 <this skill's folder>/scripts/onboard.py launch --state <private state file> --spec <spec number>
```

It reads launch-fleet's frontier (`<launch-fleet skill's folder>/scripts/fleet.sh frontier`, which checks the approval is current) and keeps this spec's tickets, reads the builder and reviewer tables setup wrote, and refuses unless both builder tables are the recorded harness, model and effort and the reviewer is from the other model family. A missing or stale approval leaves the frontier empty, so nothing starts. It prints the effects: one fleet thread in the carried CloudRoom project, with those settings; its loop, which checks the spec every 10 minutes (`fleet.sh spec <S>`); the builders it then starts on the frontier, and their reviewer; Cloud Credits unknown until measured. It prints a `Confirmation:` digest of exactly those effects and saves it privately. Show the effects and ask for a yes. This yes approves these starts and their spending; it is not the plan approval, which is already saved.

On the user's yes, run the same command with `--yes --confirm <that digest>`. It reads everything again, setup included, and refuses unless the effects are exactly the ones the user saw and setup still verifies what was carried: if anything changed (another ticket became ready, a setting moved, a check expired or refused), run `continue` or preview again and ask again. It saves the launch in the state file first, then starts the fleet thread once, as launch-fleet's "Fleet threads", "Starting one" says (`room-cli thread spawn --parent-self` with launch-fleet's own brief). From its first wake the fleet thread makes its loop, records `launch-fleet: fleet active, loop fleet-<S>` on the spec and starts the builders, reviews and merges by launch-fleet's rules. `launch` never starts a second fleet thread: a repeat only reads the spec's fleet record, and a start that was cut short or is uncertain (exit 6) stays so until that record reads back; never retry it by hand. Only when `room-cli` could not be run at all, so nothing was dispatched, is the start refused (exit 5): fix the installation, then preview and ask again.

Done when the fleet thread's start is recorded, or recorded uncertain and reported as such.

## 8. Watch

Show the fleet working:

```sh
python3 <this skill's folder>/scripts/onboard.py progress --state <private state file> --spec <spec number> --openwiz <absolute path to openwiz>
```

It reads whether the spec has its fleet record, then `openwiz fleet <spec> --json`, and prints each ticket's state and the counts. Read it again when the user asks, and point them to the cockpit, `openwiz` Home and the First hour page for the same view. Say what is unknown as unknown. A count is progress, never a first merge: the first merge is the one GitHub reads back merged, an implementation change at its reviewed, CI-green head, never an init-only pull request. Tell the user what happens next: reviews, merges and the blocked tickets follow by launch-fleet's rules, on the fleet thread's loop. Then offer their own next idea.

Done when the user has seen their agents' progress.
