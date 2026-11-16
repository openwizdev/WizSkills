---
name: onboard
description: Onboard a new OpenWiz user from setup to a first fleet. Explain the factory in a few lines, offer fun quick ideas with a disposable demo repository by default or their own repository, grill a fresh idea briefly toward 4 to 7 small tickets, ask harness, model, effort and Cloud or Local, then follow plan-graph's spec confirmation and exact-plan approval and launch only the approved frontier. Use after install and setup, when a user asks to try OpenWiz, or to resume an interrupted first fleet.
---

# Onboard

Take a new user from a ready setup to their **first fleet**: a fresh idea of theirs, grilled briefly, planned as 4 to 7 small tickets, approved by them, and built by agents they can watch. The wow is seeing several agents start on the user's own idea within minutes, so keep every step short.

This skill only connects the existing skills. It reuses [`grill`](../grill/SKILL.md), [`setup`](../setup/SKILL.md), [`plan-graph`](../plan-graph/SKILL.md) and [`launch-fleet`](../launch-fleet/SKILL.md), and the agent CLI as [`contracts/cli.v1.md`](../../contracts/cli.v1.md) defines it. It adds no approval, no planner and no engine of its own.

**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.

## Rules for the whole journey

- **Install permission is not work approval.** Installing OpenWiz, finishing setup or saying yes to this skill approves no spec, no plan and no start. Only plan-graph's separate spec confirmation and its exact-plan approval let tickets start, and only through the existing launch rules. Never write, fake or infer an approval, and never ask for a blanket yes to future work.
- **Every effect is shown first, then waits for a yes.** Before creating a repository or a CloudRoom project, changing account settings, activating the engine or starting agents that spend Cloud Credits, list exactly what will happen (names, counts, where it runs, what it may cost, labelled measured, estimated or unknown) and wait for the user's explicit yes to that list. No yes, no effect. Model-provider charges are separate from Cloud Credits.
- **No prewritten plan.** There is no demo plan, ticket list or template project in this skill. Every spec and ticket comes from this user's grill, in this conversation.
- **The size is for the first fleet only.** Aim for 4 to 7 small tickets so the first fleet is quick and cheap. It is no limit on any later fleet, and it never shrinks a later plan.
- **Use the agent CLI's JSON, never its screen.** Run `openwiz` commands with `--json` where the catalogue (`openwiz help --agent`) says they have it, and read exit codes as the contract defines them. Use the installed program by its absolute path.
- **Keep private things private.** The user's exact words go only where the project's private-record rules say (`contracts/open-development.v1.md`). No credentials in prompts, files, arguments or logs.
- **Interrupted is resumable.** Read the private state file and GitHub first; continue from the first unfinished step. Never redo an effect already recorded.

The helper beside this skill, `scripts/onboard.py`, does the mechanical checks. Run it with Python 3 (standard library only) from the project's checkout, keep `--state` in owner-only private state outside the checkout, and pass the installed `openwiz` by absolute path. It prints plain lines; its exit codes are 0 done, 1 read failure, 2 usage, 5 refused (nothing started), 6 uncertain (never retried), 7 busy, 10 state unavailable, 12 preview awaiting `--yes`.

## 1. Explain

Say in a few plain sentences what OpenWiz does, before asking anything:

> You bring an **idea**. I **grill** you with a few quick questions to settle it, then write it up as a **spec** for you to confirm. The spec becomes small **tickets**, a plan you approve as a whole. Each ticket gets its own **builder**, an agent that writes the code on its own branch. A **reviewer** from a different model family reviews each pull request independently, and approved, green work **merges** by the project's rules. Nothing starts until you approve the plan.

Done when the user has seen it. Answer their questions briefly; don't lecture.

## 2. Choose a project

Offer three or four **fun, quick ideas**, made up fresh for this user (a tiny game, a toy command-line tool, a one-page site about something they like), plus "your own idea". Ideas are one line each, never a plan.

Then ask where the work goes, recommending the first:

1. **A new disposable demo repository** (the default): one private GitHub repository, created with the user's own `gh` identity. Show its exact owner, name and visibility, and that it is new and safe to delete later; create it only after the user's yes to exactly that:

   ```sh
   python3 <this skill's folder>/scripts/onboard.py create-repo --state <private state file> --repo <owner>/<name>        # shows the effect
   python3 <this skill's folder>/scripts/onboard.py create-repo --state <private state file> --repo <owner>/<name> --yes  # on the yes
   ```

   It refuses a name that already exists, saves the name before it creates, makes one `gh repo create <owner>/<name> --private` and reads it back. If the outcome is uncertain (exit 6), run the same command again: it reads first and never creates twice. Then clone it and work there. The CloudRoom project stays the user's to make or pick in CloudRoom; `setup` then selects that existing project. This skill creates nothing in CloudRoom.
2. **One of the user's existing repositories:** confirm which one, and that a fleet will open branches and pull requests there. Setup must already show it ready.

Done when the user has picked an idea and a repository, the repository is created and read back (or chosen), and setup shows the project selected.

## 3. Grill

Run the `grill` skill, briefly: one or two rounds of at most three questions, each with a recommendation the user can accept in a word. Steer the answers toward something 4 to 7 small, mostly independent tickets can build: the smallest version of the idea that still delights. Save every question and answer as `grill` says. Ask for its summary to be confirmed.

Done when the grill is confirmed.

## 4. Choose the agents

Read the offered options with `openwiz models --json` and save the output privately. Ask four separate questions; offer a recommendation for each, but never fill one in for the user:

- **Harness** (for example Claude Code or Codex) and **model**, from the offered options only;
- **Effort**, from that model's offered efforts;
- **Where the fleet's agents run:** Cloud (recommended for the first fleet: fast, and it uses Cloud Credits) or Local (on the user's own computer). This is separate from where the engine runs: never copy the engine's location into it.

Record the answers:

```sh
python3 <this skill's folder>/scripts/onboard.py choose --state <private state file> --options <saved models output> \
  --harness <provider> --model <model> --effort <effort> --agents cloud|local
```

It refuses anything the options don't offer, any missing answer, and a harness the engine's review rules don't cover (Claude Code and Codex). Then run `setup` again so **both** builder tables in `docs/agents/fleet.md`, `## Builder` and `## Builder for small tickets`, name exactly these settings, with the user's decision as their source, since any ticket of the fleet may later get a small-ticket label. Setup keeps the reviewers in the other model family. `launch` checks all of this in the engine's rules and refuses otherwise.

**Local agents are not available yet:** the engine's start path places builders in the Cloud only. If the user chose Local, say so plainly, and offer Cloud or stopping here. `launch` refuses Local and starts nothing.

Done when the choices are recorded and the builder settings match them.

## 5. Plan

Run `plan-graph` from the confirmed grill, unchanged: write the spec, show it, and wait for the user's **spec confirmation**; propose 4 to 7 small tickets with disjoint owned paths and as few arrows as the work allows, so several can start at once; write them; then wait for the user's **exact-plan approval** of the graph as written, recorded with its revision and fingerprint. A reply that asks for a change is not an approval. Then record which spec this onboarding planned:

```sh
python3 <this skill's folder>/scripts/onboard.py spec --state <private state file> --spec <spec number> --repo <owner>/<name>
```

It checks the checkout is that repository and saves it; every later command refuses to run in another repository.

Done when plan-graph's approval record is on the spec and current.

## 6. Launch

Preview first:

```sh
python3 <this skill's folder>/scripts/onboard.py launch --state <private state file> --spec <spec number> --openwiz <absolute path to openwiz>
```

It reads launch-fleet's frontier (`<launch-fleet skill's folder>/scripts/fleet.sh frontier`, which checks the approval is current) and the engine's reviewed plan (`openwiz fleet tick --dry-run --json`), and refuses unless both name exactly the same tickets, every planned action is a builder start for this spec, and every start uses the recorded harness, model and effort. A missing or stale approval leaves the frontier empty, so nothing starts. It prints the effects and a `Confirmation:` digest of exactly those effects, and saves that preview privately. Show the effects to the user (how many agents, which tickets, where, Cloud Credits unknown until measured) and ask for a yes.

On the user's yes, run the same command with `--yes --confirm <that digest>`. It reads a fresh dry run and refuses unless its effects are exactly the ones the user saw: if anything changed (another ticket became ready, a setting moved), preview again and ask again. It saves the launch in the state file first, then runs the reviewed plan once (`openwiz fleet tick --expect-plan <plan> --json`). It never runs a second launch for the spec: a repeat or a reload only reads progress, and an uncertain outcome (exit 6) stays uncertain for the engine's own recovery to reconcile; never retry it by hand. Tickets that are blocked start later through the engine, by the existing launch rules.

Done when the launch is recorded done, or recorded uncertain and reported as such.

## 7. Watch

Show the fleet working:

```sh
python3 <this skill's folder>/scripts/onboard.py progress --state <private state file> --spec <spec number> --openwiz <absolute path to openwiz>
```

It reads `openwiz fleet <spec> --json` and prints each ticket's state and the counts. Read it again when the user asks, and point them to the cockpit and `openwiz` Home for the same view. Say what is unknown as unknown. Tell the user what happens next: reviews, merges and the blocked tickets follow by the project's rules, and the engine's status (`openwiz engine status --json`) says whether it is running. Then offer their own next idea.

Done when the user has seen their agents' progress.
