---
name: install
description: Install OpenWiz for a user from its one install line, "Install OpenWiz from github.com/openwizdev/OpenWiz". Check the machine and CloudRoom, install the verified prebuilt release (no Rust or Node), open setup and connect what is missing, choose the engine, explain the product in a few lines, then hand the first fleet to the onboard skill. Use when a user asks an agent to install, set up, repair, update or remove OpenWiz, or to resume an interrupted install.
---

# Install OpenWiz

The user pasted one line into their agent:

> Install OpenWiz from github.com/openwizdev/OpenWiz

Take them from that line to setup, then to their first fleet, in this order: preflight, verified install, setup and connections, engine, a brief explanation, first fleet. Keep each step short: the goal is the user seeing their own agents working within minutes.

This skill only connects existing tools: the verified installer (`tools/install/install` in the OpenWiz repository, over that repository's `contracts/install.v1.md`), setup (its `contracts/setup.v1.md` and the [`setup`](../setup/SKILL.md) skill), the agent CLI ([`contracts/cli.v1.md`](../../contracts/cli.v1.md)) and the [`onboard`](../onboard/SKILL.md) skill. It adds no installer, engine, approval or planner of its own. The public guide is `docs/install.md` in the OpenWiz repository.

**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.

## Rules for the whole install

- **Install permission is not work approval.** Asking for an install, finishing setup or saying yes to a step approves no spec, no plan and no start. Only the `onboard` skill's spec confirmation and exact-plan approval start work, through the existing launch rules. Never write, fake or infer an approval.
- **Every effect is shown first, then waits for a yes.** Before connecting the App, saving project settings, configuring phone access or activating the engine, show the tool's proposed effects and operation id and wait for the user's explicit yes to exactly that proposal. Then confirm that same operation id. No yes, no effect.
- **Use the agent CLI's JSON, never its screen.** Every command here prints one JSON object or has a `--json` form; read it and its exit code. Never scrape a terminal screen, and run installed programs by absolute path.
- **No build tools.** The packaged install needs Python 3.9 or later and nothing else: no Rust, Cargo, Node or npm, and no source build. If a step seems to need one, stop and say so.
- **Credentials stay out of the conversation.** Never ask for a key or token in chat, and never put one in a prompt, command argument, URL, log, issue or repository file. App keys and access credentials go only into owner-only state on the selected engine host or CloudRoom's own secret store, through the tools' own protected setup.
- **Uncertain is never retried blindly.** A lost reply or an uncertain outcome is reconciled with the same operation id, which every tool reuses; never start the same effect a second time.
- **Free now; other charges are separate.** OpenWiz is free now. Paid plans come later. CloudRoom and model charges are separate and not included. If the user wants more Cloud Credits, that is CloudRoom's own plan, bought from CloudRoom at its pricing page (`https://cloudroom.dev/pricing`), not from OpenWiz. Referral verification is unavailable. No referral is applied. No owner-supplied referral has been verified, so never guess one or add a code or parameter to that link.

Keep `<root>` (the install root, default `$HOME/.local/lib/openwiz`), `<build>` and `<state>` (the `build` and `state_root` paths `install` prints; `<state>` defaults to `<root>/state`) as absolute paths. All are owner-only. In the shell, also keep `<build>` as `$build` (`build=<build>`): the installed runtime's Python tools below run from `"$build"/runtime/...`. Run them with `python3 -I -B`, so nothing is written into the verified build. Every setup, App, phone-access and engine command after the install runs with `OPENWIZ_STATE_DIR=<state>` in its environment, and the commands below also name it with `--state-dir <state>`, so every effect lands in this install's state and the setup page reads the same state.

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

It serves only the installed build's own setup page at `http://127.0.0.1:7370/setup`, after checking the served page is that build's, and reads setup from `<state>` (pass `--state-root <state>` if you installed with a custom state). It reads no account and starts no engine. Then check each connection independently, with the installed runtime:

```sh
python3 -I -B "$build"/runtime/setup/setup.py check --state-dir <state>
```

Read each component's state (`verified`, `missing`, `refused`, `unknown`) and its `next` step, in the page or in `GET /api/v1/setup`. Follow the `setup` skill for what is missing: it reuses the user's CloudRoom sign-in and harnesses, checks the agents' own GitHub login, connects OpenWiz's GitHub App on selected repositories only, as setup's "The App" section says (`python3 -I -B "$build"/runtime/github-app/setup.py`, preview first; the person clicks Create, then Install on selected repositories, and any key goes only into CloudRoom's own secret prompt, never the chat), and prepares the project (`python3 -I -B "$build"/runtime/setup/setup.py prepare --state-dir <state>` with its settings, preview first, then the same with `--yes --operation <id>`). Phone access is optional and separate: offer it, using `python3 -I -B "$build"/runtime/access/access.py` as its README says. Run `check` again after each change. Never mark a component ready yourself: only the check does.

Done when every prerequisite for the chosen engine reads `verified`, or the user has chosen to stop with the remaining `next` steps.

## 4. Engine

Preview where the engine runs, and show the user the effects and the cost line exactly as printed:

```sh
<build>/openwiz engine preview --location cloud|local --state-dir <state> --json
```

The engine is the plain mechanical tick, run on a schedule; it starts only approved, ready tickets, so an empty project starts nothing. Recommend from the cost line: a measured Cloud cost above about a tenth of the free monthly allowance means Local for a free user, and an unknown cost means the user chooses explicitly. Activate only on the user's yes to that preview, with its operation id (`<build>/openwiz engine activate --yes --operation <id> --root <root> --state-dir <state> --json`), and report the result as it is: held or unavailable is not running. `<build>/openwiz engine status --state-dir <state> --json` reads it again.

Done when the engine choice is recorded and its status reported truthfully.

## 5. Explain

Say in a few plain sentences what happens next, before asking about a project:

> You bring an **idea**. I **grill** you with a few quick questions to settle it, then write it up as a **spec** for you to confirm. The spec becomes small **tickets**, a plan you approve as a whole. Each ticket gets its own **builder**, an agent that writes the code on its own branch. A **reviewer** from a different model family reviews each pull request independently, and approved, green work **merges** by the project's rules. Nothing starts until you approve the plan.

Done when the user has seen it.

## 6. First fleet

Hand over to the `onboard` skill, from its step 2 (the explanation is done): fun, quick ideas, a disposable demo repository by default, a brief grill, the user's choice of harness, model, effort and where the agents run, then spec confirmation, exact-plan approval and the launch of only the approved frontier. Point the user to the cockpit and `openwiz` Home to watch the agents.

Done when `onboard` is done, or the user has stopped with what is left.

## Repeat, interrupted or failed

Run the same step again: every step reads before it writes. A repeated `install` reuses the verified build; a refused one leaves the last good build selected. Setup and engine operations keep their operation ids in the private state, so an interrupted preview is confirmed or replaced, never doubled, and an uncertain one is reconciled first. Settings, credentials and owner work are never replaced by a reinstall.

## Recovery

If setup does not open, run `install status --root <root>` (with `--state-root <state>` for a custom state) and `open` again: a failed bind is a failure, never proof another program's page is OpenWiz's. If a connection reads `refused` or `unknown`, follow its `next` step and check again. To recover from a bad update, `<root>/current` still points at the last good build until a new one fully verifies.

## Removal and revoking access

Removing OpenWiz from this computer does not revoke anything it was granted. To remove it, stop only this installation's own server and engine (`<build>/openwiz engine status --state-dir <state> --json` names it), then delete `<root>`; keep `<state>` unless the user asks to delete it too, since it holds their settings and records. Their repositories, branches and CloudRoom threads are their work and stay. To revoke access, the user uninstalls OpenWiz's GitHub App or removes repositories from it in GitHub's settings, deletes any phone-access tunnel and Access application or Tailscale rule they made, and removes any engine Loop in CloudRoom. Show these steps; never perform a removal or revocation without the user's yes.
