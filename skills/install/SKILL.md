---
name: install
description: Install OpenWiz for a user from its one install line, "Install OpenWiz from github.com/openwizdev/OpenWiz". Check the machine and CloudRoom, install the verified prebuilt release (no Rust or Node), open setup and check what is connected, explain the product in a few lines, then hand over to the onboard skill, which connects GitHub, prepares the project and its private brain, and starts the first fleet through launch-fleet. Use when a user asks an agent to install, set up, repair, update or remove OpenWiz, or to resume an interrupted install.
---

# Install OpenWiz

The user pasted one line into their agent:

> Install OpenWiz from github.com/openwizdev/OpenWiz

Take them from that line to setup, then to their first fleet, in this order: preflight, verified install, setup and connections, a brief explanation, first fleet. It is one continuation: every later step reuses what an earlier one recorded (the install, CloudRoom's sign-in, the repository, the identity, the brain, the agents), and resumes from the first unfinished step. Keep each step short: the goal is the user seeing their own agents working within minutes.

This skill only connects existing tools: the verified installer (`tools/install/install` in the OpenWiz repository, over that repository's `contracts/install.v1.md`), setup (its `contracts/setup.v1.md` and the [`setup`](../setup/SKILL.md) skill), the agent CLI ([`contracts/cli.v1.md`](../../contracts/cli.v1.md)), the [`onboard`](../onboard/SKILL.md) skill and, through it, [`launch-fleet`](../launch-fleet/SKILL.md). It adds no installer, engine, sign-in routine, approval or planner of its own, and never runs `openwiz engine` or `openwiz fleet tick`: the first fleet starts as launch-fleet starts every fleet, with a fleet thread and its loop. The public guide is `docs/install.md` in the OpenWiz repository.

**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.

## Rules for the whole install

- **Install permission is not work approval.** Asking for an install, finishing setup or saying yes to a step approves no spec, no plan and no start. Only the `onboard` skill's spec confirmation and exact-plan approval start work, through the existing launch rules. Never write, fake or infer an approval.
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

Read each component's state (`verified`, `missing`, `refused`, `unknown`) and its `next` step, in the page or in `GET /api/v1/setup`. Here, reuse the user's existing CloudRoom installation and sign-in and its harnesses, as the `setup` skill says: an existing current one is never replaced or asked for again. GitHub sign-in, the user's own App or the explicit skip, the project and its private brain all belong to the one repository the user picks, so the `onboard` skill does them, with these same installed tools (its "Connect" step), right after that choice. Phone access is optional and separate: offer it, using `python3 -I -B "$build"/runtime/access/access.py` as its README says. Run `check` again after each change. Never mark a component ready yourself: only the check does. There is no engine to choose and no engine location to ask about.

Done when CloudRoom reads `verified`, or the user has chosen to stop with the remaining `next` steps.

## 4. Explain

Say in a few plain sentences what happens next, before asking about a project:

> You bring an **idea**. I **grill** you with a few quick questions to settle it, then write it up as a **spec** for you to confirm. The spec becomes small **tickets**, a plan you approve as a whole. Each ticket gets its own **builder**, an agent that writes the code on its own branch. A **reviewer** from a different model family reviews each pull request independently, and approved, green work **merges** by the project's rules. Nothing starts until you approve the plan.

Done when the user has seen it.

## 5. First fleet

Hand over to the `onboard` skill, from its step 2 (the explanation is done; pass `--explained` to its `continue`): fun, quick ideas and a disposable demo repository by default; then, for that one repository, GitHub sign-in, the user's own App or an explicit skip, the prepared project and its private brain (`openwiz init`), carried forward once; a brief grill; where the agents run, beside the harness, model and effort already recorded; then spec confirmation, exact-plan approval, the start's own yes, and the first fleet through launch-fleet: one fleet thread and its loop, which start only the approved frontier. Point the user to the cockpit, `openwiz` Home and the First hour page to watch the agents.

Done when `onboard` is done, or the user has stopped with what is left.

## Repeat, interrupted or failed

Run the same step again: every step reads before it writes. A repeated `install` reuses the verified build; a refused one leaves the last good build selected. Setup, sign-in, App and init operations keep their operation ids in the private state, so an interrupted preview is confirmed or replaced, never doubled, and an uncertain one is reconciled first. Settings, credentials and owner work are never replaced by a reinstall.

## Recovery

If setup does not open, run `install status --root <root>` (with `--state-root <state>` for a custom state) and `open` again: a failed bind is a failure, never proof another program's page is OpenWiz's. If a connection reads `refused` or `unknown`, follow its `next` step and check again. To recover from a bad update, `<root>/current` still points at the last good build until a new one fully verifies.

## Removal and revoking access

Removing OpenWiz from this computer does not revoke anything it was granted. To remove it, stop only this installation's own setup server, then delete `<root>`; keep `<state>` unless the user asks to delete it too, since it holds their settings and records. Their repositories, branches and CloudRoom threads are their work and stay. To revoke access, the user uninstalls OpenWiz's GitHub App or removes repositories from it in GitHub's settings, deletes any phone-access tunnel and Access application or Tailscale rule they made, and deletes the fleet threads' loops in CloudRoom. Show these steps; never perform a removal or revocation without the user's yes.
