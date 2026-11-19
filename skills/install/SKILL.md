---
name: install
description: Install OpenWiz for a user from its one install line, "Install OpenWiz from github.com/openwizdev/OpenWiz". Check the machine and CloudRoom, install the verified prebuilt release (no Rust or Node), open setup and check what is connected, and offer a first-fleet branch that connects GitHub, prepares the project and its private brain, and starts the fleet through launch-fleet. Use to install, set up, repair, update or remove OpenWiz, to try a first fleet, or to resume either journey.
version: 0.2.0
---

# Install OpenWiz

The user pasted one line into their agent:

> Install OpenWiz from github.com/openwizdev/OpenWiz

Take them from that line to setup, then to their first fleet, in this order: preflight, verified install, setup and connections, a brief explanation, first fleet. In this flow, every later step reuses what an earlier one recorded (the install, CloudRoom's sign-in, the repository, the identity, the brain, the agents), and resumes from the first unfinished step. Keep each step short: the goal is the user seeing their own agents working within minutes.

This skill only connects existing tools: the verified installer (`tools/install/install` in the OpenWiz repository, over that repository's `contracts/install.v1.md`), setup (its `contracts/setup.v1.md` and the [`setup`](../setup/SKILL.md) skill), the agent CLI ([`contracts/cli.v1.md`](../../contracts/cli.v1.md)), and, for the first fleet, [`grill`](../grill/SKILL.md), [`to-spec`](../to-spec/SKILL.md), [`to-tickets`](../to-tickets/SKILL.md) and [`launch-fleet`](../launch-fleet/SKILL.md). It adds no installer, engine, sign-in routine, approval or planner of its own, and never runs `openwiz engine` or `openwiz fleet tick`: the first fleet starts as launch-fleet starts every fleet, with a fleet thread and its loop. The public guide is `docs/install.md` in the OpenWiz repository.

**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.

## Rules for the whole install

- **Install permission is not work approval.** Asking for an install, finishing setup or saying yes to a step approves no spec, no plan and no start. The first fleet requires separate spec confirmation, exact-plan approval and explicit consent to start. Follow to-spec, to-tickets and launch-fleet. Never write, fake or infer an approval, or ask for blanket consent to future work.
- **Every effect is shown first, then waits for a yes.** Before signing in, connecting or skipping the App, saving project settings, creating the brain or configuring phone access, show the tool's proposed effects and operation id and wait for the user's explicit yes to exactly that proposal. Then confirm that same operation id. No yes, no effect.
- **Use the agent CLI's JSON, never its screen.** Every command here prints one JSON object or has a `--json` form; read it and its exit code. Never scrape a terminal screen, and run installed programs by absolute path.
- **No build tools.** The packaged install needs Python 3.9 or later and nothing else: no Rust, Cargo, Node or npm, and no source build. If a step seems to need one, stop and say so.
- **Credentials stay out of the conversation.** Never ask for a key or token in chat, and never put one in a prompt, command argument, URL, log, issue or repository file. App keys and access credentials go only into owner-only state on this computer or CloudRoom's own secret store, through the tools' own protected setup.
- **Uncertain is never retried blindly.** A lost reply or an uncertain outcome is reconciled with the same operation id, which every tool reuses; never start the same effect a second time.
- **Free now; other charges are separate.** OpenWiz is free now. Paid plans come later. CloudRoom and model charges are separate and not included. If the user wants more Cloud Credits, that is CloudRoom's own plan, bought from CloudRoom at its pricing page (`https://cloudroom.dev/pricing`), not from OpenWiz. Referral verification is unavailable. No referral is applied. No owner-supplied referral has been verified, so never guess one or add a code or parameter to that link.

Keep `<root>` (the install root, default `$HOME/.local/lib/openwiz`), `<build>` and `<state>` (the `build` and `state_root` paths `install` prints; `<state>` defaults to `<root>/state`) as absolute paths. All are owner-only. In the shell, also keep `<build>` as `$build` (`build=<build>`): the installed runtime's Python tools below run from `"$build"/runtime/...`. Run them with `python3 -I -B`, so nothing is written into the verified build. Every setup, sign-in, App, init and phone-access command after the install runs with `OPENWIZ_STATE_DIR=<state>` in its environment, and the commands below also name it with `--state-dir <state>`, so every effect lands in this install's state and the setup page reads the same state.

## 1. Preflight

Get the installer from the public repository into a private temporary folder, kept as `$openwiz`. Nothing in it is built or run except the installer itself:

```sh
openwiz=<private temporary folder>/openwiz
git clone --depth 1 https://github.com/openwizdev/OpenWiz "$openwiz"
python3 -I "$openwiz"/tools/install/install preflight
```

It reads only this machine: the Python version, the supported target (`aarch64-apple-darwin`, `x86_64-apple-darwin` or `x86_64-unknown-linux-gnu`), free disk space, and whether `room-cli`, `gh` and `git` are on `PATH`. It runs none of them, so CloudRoom's sign-in is checked later, in setup. Exit 0 means the machine can install; exit 5 means a check refused, with its `next` step. Tell the user each missing item and its next step, plainly: for CloudRoom, install the CloudRoom app and sign in; for `gh`, install it and `gh auth login`.

Done when preflight passes, or the user has the next step for each missing item.

## 2. Verified install

Download the latest published release for the target into a new private folder, then install it:

```sh
python3 -I "$openwiz"/tools/install/install download --target <target> --dir <private download folder>
python3 -I "$openwiz"/tools/install/install install --assets <private download folder> --target <target> --root <root>
```

`download` fetches only the release's checksum file, manifest and archive from `github.com/openwizdev/OpenWiz/releases`, within their declared sizes. If `<root>`'s parent folder is missing inside your home folder (a fresh `~/.local/lib`), `install` makes it, owner-only, never through a link. `install` checks the manifest against that checksum and every file against the manifest before anything is selected, records the packaged update channel, and switches `<root>/current` to the new build only when everything matched. A checksum proves the files are the release's files, not who published them. If it refuses, the previous install (if any) stays selected and usable; report the refusal, never work around it. Running it again with the same release reuses the verified build.

Done when `install` printed `"activated": true`, the version, source and target, and its `build` and `state_root` paths, which you keep as `<build>` and `<state>`.

## 3. Setup and connections

Open the installed setup page on loopback and leave it running:

```sh
python3 -I "$openwiz"/tools/install/install open --root <root> --browser
```

It serves only the installed build's own setup page at `http://127.0.0.1:7370/setup`, after checking the served page is that build's, and reads setup from `<state>` (pass `--state-root <state>` if you installed with a custom state). It reads no account and starts nothing. Then check each connection independently, with the installed runtime:

```sh
python3 -I -B "$build"/runtime/setup/setup.py check --state-dir <state>
```

Read each component's state (`verified`, `missing`, `refused`, `unknown`) and its `next` step, in the page or in `GET /api/v1/setup`. Here, reuse the user's existing CloudRoom installation and sign-in and its harnesses, as the `setup` skill says: an existing current one is never replaced or asked for again. GitHub sign-in, the user's own App or the explicit skip, the project and its private brain all belong to the one repository the user picks, so connect them only after the user chooses a repository in the first-fleet branch. Phone access is optional and separate: offer it, using `python3 -I -B "$build"/runtime/access/access.py` as its README says. Run `check` again after each change. Never mark a component ready yourself: only the check does. There is no engine to choose and no engine location to ask about.

Done when CloudRoom reads `verified`, or the user has chosen to stop with the remaining `next` steps.

## 4. Explain

Say in a few plain sentences what happens next, before asking about a project:

> You bring an **idea**. I **grill** you with a few quick questions to settle it, then write it up as a **spec** for you to confirm. The spec becomes small **tickets**, a plan you approve as a whole. Each ticket gets its own **builder**, an agent that writes the code on its own branch. A **reviewer** from a different model family reviews each pull request independently, and approved, green work **merges** by the project's rules. Nothing starts until you approve the plan.

Done when the user has seen it. Reuse any explanation already given.

## 5. First fleet

Continue when the user wants to try a first fleet. For an existing install, start here with its recorded build and setup paths, and give the explanation in step 4 if the user has yet to see it. If they only asked to install or repair, finish with the verified install and any outstanding setup steps.

Read the existing private journey state, installed setup and GitHub. Resume at the first unfinished step and reuse every recorded choice. Ask for anything the user has yet to choose. Before a new effect, show its names, counts, where it runs and any measured, estimated or unknown costs, and wait for the user's yes to that preview. Cloud Credits and model-provider charges are separate. Save the user's exact words only under the project's private-record rules (`contracts/open-development.v1.md`).

Build the spec and tickets from this user's grill. Aim for 4 to 7 small tickets in the first fleet so they can watch agents start on their own idea. Later fleets follow their own size and approval rules.

Run `scripts/first_fleet.py` from the project's checkout, using this installed skill's folder for the script path. Reuse the same owner-only `--state` file outside the checkout on every command, including a journey started before the merge into install. The helper prints plain lines. Exit codes are 0 done, 1 read failure, 2 usage, 5 refused, 6 uncertain, 7 busy, 10 state unavailable and 12 preview awaiting `--yes`. Reconcile an uncertain effect from its record before continuing.

### 1. Choose a project

Offer three or four **fun, quick ideas**, made up fresh for this user (a tiny game, a toy command-line tool, a one-page site about something they like), plus "your own idea". Ideas are one line each, never a plan.

Then ask where the work goes, recommending the first:

1. **A new disposable demo repository** (the default): one private GitHub repository, created with the user's own `gh` identity, with one initial commit on its default branch: a `README.md` holding only its title (`# <name>`), which init needs to propose the brain. Show its exact owner, name, visibility and that initial README commit, and that it is new and safe to delete later; create it only after the user's yes to exactly that:

   **Sign in before creating the demo.** First run the installed GitHub sign-in tool from Connect, without `--repository` because the demo does not exist yet: `python3 -I -B "$build"/runtime/setup/github_login.py sign-in --state-dir <state>`. It reuses a verified account; if signed out, show its sign-in effects and, on the user's yes, run it with `--yes` for GitHub's browser sign-in. Only after the account reads back, show the demo creation preview and ask for its separate yes. Connect later verifies access to the created repository. `create-repo --yes` also refuses before creation if it cannot verify the GitHub login, pointing back to this sign-in step.

   ```sh
   python3 <this skill's folder>/scripts/first_fleet.py create-repo --state <private state file> --repo <owner>/<name>        # shows the effect
   python3 <this skill's folder>/scripts/first_fleet.py create-repo --state <private state file> --repo <owner>/<name> --yes  # on the yes
   ```

   It refuses a name that already exists, saves the name before it creates, makes one `gh repo create <owner>/<name> --private`, with `--add-readme` for its initial commit (the repository and that commit in one create; it never pushes a commit of its own), and reads back the private repository, its default branch and that commit before it says created. If the outcome is uncertain (exit 6), including a default branch or commit that did not read back, run the same command again: it reads first and never creates twice. A repository of its own without that branch is never seeded afterwards. Then clone it and work there. The CloudRoom project stays the user's to make or pick in CloudRoom; `setup` then selects that existing project. This skill creates nothing in CloudRoom.
2. **One of the user's existing repositories:** confirm which one, and that a fleet will open branches and pull requests there.

Done when the user has picked an idea and a repository, and the repository is created and read back (or chosen). This one repository is carried through every later step; there is no second one.

### 2. Connect

Set up GitHub, the project and its private brain for that same repository, once, with the installed tools (`$build`, `<state>` and the rules are the install's). Each tool shows its effects first and applies only on the user's yes to exactly that preview. Sign-in confirms with `--yes` alone (it has no operation id); prepare, the skip and init confirm with `--yes --operation <id>` from their own preview. A repeat reuses the id and reads before it writes.

1. **GitHub sign-in:** `python3 -I -B "$build"/runtime/setup/github_login.py sign-in --repository <owner>/<name> --state-dir <state>`. A current login is reused. Signed out, it prints `login_needed` and its effects; on the user's yes, run the same command with `--yes`, and the user approves in GitHub's own browser page; no token is pasted. A browser opening is not a login: only the account and push-access read-back are.
2. **Prepare the project:** `python3 -I -B "$build"/runtime/setup/setup.py prepare --state-dir <state> --repository <owner>/<name> ...` with the CloudRoom project the user made or picked, and the harness, model and effort the user chooses here from `openwiz models --json` (each its own question, with a recommendation). These are recorded once and reused in Choose the agents. The App and the skip both need this saved selection.
3. **The user's own App, or an explicit skip:** ask which, recommending the App. The App is the installed App tool of the `setup` skill's "The App": Create, then Install on selected repositories only, and its key only into CloudRoom's protected secret prompt. A skip is `github_login.py skip-app` (preview, then `--yes --operation <id>`): the user's personal login then acts, and the App stays missing, never verified. An App failure never becomes a skip: only the user's own answer does.
4. **The private brain:** `<build>/openwiz init --repository <owner>/<name> --state-dir <state> --json`, then the same with `--yes --operation <id>`. It reads the repository's visibility from GitHub and places the brain itself (a demo repository's brain proposal branches from the default branch `create-repo` read back): in the private repository, or in a new private companion for public code. Say in one line where it went; there is no placement question. It opens a pull request with the brain's settings; the user merges it on GitHub. For a public repository's companion, Decisions reads the companion only when the private settings' `decision_repositories` pair (decisions.v1's repository roles, in `<state>/service/config.json`) names the code repository as public and the companion as private; `continue` refuses until it does. After that pull request is merged, connect it:

   ```sh
   python3 <this skill's folder>/scripts/first_fleet.py decisions --state <private state file> --setup-state <state>        # shows the effect
   python3 <this skill's folder>/scripts/first_fleet.py decisions --state <private state file> --setup-state <state> --yes  # on the yes
   ```

   It reads the companion pair from setup and, on the user's yes, sets only that one key: every other key of an existing settings file stays, a missing file is created with just that key, and a pair already set changes nothing. Ask the user to restart the OpenWiz server, then go on to Grill. A settings file holding only this pair suits the standalone server this install runs; a host that later runs the full OpenWiz service must complete its settings.
5. **Check, then carry it forward:** `python3 -I -B "$build"/runtime/setup/setup.py check --state-dir <state>`, then

   ```sh
   python3 <this skill's folder>/scripts/first_fleet.py continue --state <private state file> --setup-state <state> [--explained]
   ```

   (`--explained` when the user already saw the explanation in step 4). It carries the repository, CloudRoom project, acting identity, brain and prepared agents, and refuses, naming each one, while anything is missing, refused, unknown or out of date. A refused `continue` also withdraws what was carried before (the user's choices stay), so nothing starts on an old setup: the brain pull request not yet merged, a login without push access, an App chosen but not verified. Follow that component's `next` step and run the check and `continue` again.

Done when `continue` prints the carried setup and the acting identity.

### 3. Grill

Run the `grill` skill, briefly: one or two rounds of at most three questions, each with a recommendation the user can accept in a word. Steer the answers toward something 4 to 7 small, mostly independent tickets can build: the smallest version of the idea that still delights. Save every question and answer as `grill` says. Ask for its summary to be confirmed.

Done when the grill is confirmed.

### 4. Choose the agents

Read the offered options with `openwiz models --json` and save the output privately. The harness, model and effort were answered once in Connect and are reused, not asked again. Ask the one question left, with a recommendation, never filling it in:

- **Where the fleet's agents run:** Cloud (recommended for the first fleet: fast, and it uses Cloud Credits) or Local (on the user's own computer).

Record it:

```sh
python3 <this skill's folder>/scripts/first_fleet.py choose --state <private state file> --options <saved models output> \
  --from-setup --agents cloud|local
```

It refuses settings the options don't offer and a harness the review rules don't cover (Claude Code and Codex). Without a carried setup (a first-fleet journey resumed without setup), ask harness, model and effort as three questions and pass `--harness <provider> --model <model> --effort <effort>` instead. Then run the `setup` skill so **both** builder tables in `docs/agents/fleet.md`, `## Builder` and `## Builder for small tickets`, name exactly these settings, with the user's decision as their source, since any ticket of the fleet may later get a small-ticket label. Setup keeps the reviewers in the other model family. `launch` reads those tables and refuses otherwise.

**Local agents are not available yet:** launch-fleet starts the fleet thread and its builders in the Cloud. If the user chose Local, say so plainly, and offer Cloud or stopping here. `launch` refuses Local and starts nothing.

Done when the choices are recorded and the builder settings match them.

### 5. Plan

Run `to-spec` from the confirmed grill, show the spec and wait for **spec confirmation**. Then run `to-tickets`: propose 4 to 7 small tickets with disjoint owned paths and as few arrows as the work allows, so several can start at once; write them; then wait for the user's **exact-plan approval** of the graph as written, recorded with its revision and fingerprint. A reply that asks for a change is not an approval. Then record which spec this first-fleet journey planned:

```sh
python3 <this skill's folder>/scripts/first_fleet.py spec --state <private state file> --spec <spec number> --repo <owner>/<name>
```

It checks the checkout is that repository and saves it; every later command refuses to run in another repository.

Done when to-tickets’ approval record is on the spec and current.

### 6. Launch

The first fleet starts the way launch-fleet starts every fleet: one fleet thread for the spec, with its own loop. Preview first:

```sh
python3 <this skill's folder>/scripts/first_fleet.py launch --state <private state file> --spec <spec number>
```

It reads launch-fleet's frontier (`<launch-fleet skill's folder>/scripts/fleet.sh frontier`, which checks the approval is current) and keeps this spec's tickets, reads the builder and reviewer tables setup wrote, and refuses unless both builder tables are the recorded harness, model and effort and the reviewer is from the other model family. A missing or stale approval leaves the frontier empty, so nothing starts. It prints the effects: one fleet thread in the carried CloudRoom project, with those settings; its loop, which checks the spec every 10 minutes (`fleet.sh spec <S>`); the builders it then starts on the frontier, and their reviewer; Cloud Credits unknown until measured. It prints a `Confirmation:` digest of exactly those effects and saves it privately. Show the effects and ask for a yes. This yes approves these starts and their spending; it is not the plan approval, which is already saved.

On the user's yes, run the same command with `--yes --confirm <that digest>`. It reads everything again, setup included, and refuses unless the effects are exactly the ones the user saw and setup still verifies what was carried: if anything changed (another ticket became ready, a setting moved, a check expired or refused), run `continue` or preview again and ask again. It saves the launch in the state file first, then starts the fleet thread once, as launch-fleet's "Fleet threads", "Starting one" says (`room-cli thread spawn --parent-self` with launch-fleet's own brief). From its first wake the fleet thread makes its loop, records `launch-fleet: fleet active, loop fleet-<S>` on the spec and starts the builders, reviews and merges by launch-fleet's rules. `launch` never starts a second fleet thread: a repeat only reads the spec's fleet record, and a start that was cut short or is uncertain (exit 6) stays so until that record reads back; never retry it by hand. Only when `room-cli` could not be run at all, so nothing was dispatched, is the start refused (exit 5): fix the installation, then preview and ask again.

Done when the fleet thread's start is recorded, or recorded uncertain and reported as such.

### 7. Watch

Show the fleet working:

```sh
python3 <this skill's folder>/scripts/first_fleet.py progress --state <private state file> --spec <spec number> --openwiz <absolute path to openwiz>
```

It reads whether the spec has its fleet record, then `openwiz fleet <spec> --json`, and prints each ticket's state and the counts. Read it again when the user asks, and point them to the cockpit, `openwiz` Home and the First hour page for the same view. Say what is unknown as unknown. A count is progress, never a first merge: the first merge is the one GitHub reads back merged, an implementation change at its reviewed, CI-green head, never an init-only pull request. Tell the user what happens next: reviews, merges and the blocked tickets follow by launch-fleet's rules, on the fleet thread's loop. Then offer their own next idea.

Done when the user has seen their agents' progress.

## Repeat, interrupted or failed

Run the same step again: every step reads before it writes. A repeated `install` reuses the verified build; a refused one leaves the last good build selected. Setup, sign-in, App and init operations keep their operation ids in the private state, so an interrupted preview is confirmed or replaced, never doubled, and an uncertain one is reconciled first. Settings, credentials and owner work are never replaced by a reinstall.

## Recovery

If setup does not open, run `install status --root <root>` (with `--state-root <state>` for a custom state) and `open` again: a failed bind is a failure, never proof another program's page is OpenWiz's. If a connection reads `refused` or `unknown`, follow its `next` step and check again. To recover from a bad update, `<root>/current` still points at the last good build until a new one fully verifies.

## Removal and revoking access

Removing OpenWiz from this computer does not revoke anything it was granted. To remove it, stop only this installation's own setup server, then delete `<root>`; keep `<state>` unless the user asks to delete it too, since it holds their settings and records. Their repositories, branches and CloudRoom threads are their work and stay. To revoke access, the user uninstalls OpenWiz's GitHub App or removes repositories from it in GitHub's settings, deletes any phone-access tunnel and Access application or Tailscale rule they made, and deletes the fleet threads' loops in CloudRoom. Show these steps; never perform a removal or revocation without the user's yes.
