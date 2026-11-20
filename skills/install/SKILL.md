---
name: install
description: Install OpenWiz from its one line, "Install OpenWiz from github.com/openwizdev/OpenWiz", then optionally walk the resumable onboarding road to a first merged pull request. Checks the machine, installs the verified prebuilt release (no Rust or Node), checks setup's connections, asks where agents run, offers three ways to start, runs a short grill, and starts the fleet through launch-fleet once the plan passes its checks. Use to install, repair, update or remove OpenWiz, or to start or resume a first fleet. For a project's docs/agents/ settings alone, use setup.
version: 0.2.0
---

# Install OpenWiz

The user pasted one line into their agent:

> Install OpenWiz from github.com/openwizdev/OpenWiz

Take them from that line to setup, then down the onboarding road to their first merged pull request if they want one. Every step reads before it writes and reuses what an earlier one recorded, so a repeat or a fresh session resumes at the first unfinished step. Tools: OpenWiz's installer (`tools/install/install`, over its `contracts/install.v1.md`) and installed runtime (`contracts/setup.v1.md`), the agent CLI ([cli.v1](../../contracts/cli.v1.md)), and for the road `grill`, `to-spec`, `to-tickets` and `launch-fleet`, and this skill's [teach.md](teach.md) and [ideas.md](ideas.md). This skill adds no installer, engine, approval or planner, and never runs `openwiz engine` or `openwiz fleet tick`.

**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.

## Guards

- **Install permission is not work approval.** Installing or finishing setup approves nothing. The first fleet needs the user's answer to where agents run, their yes in this chat to the grill's summary, and, right before it starts, their yes to starting it on that host, which can cost money. The plan approves itself by to-tickets' checks (J203): no spec or plan approval is asked. Never write, fake or infer a yes, or ask for blanket consent.
- **Show every effect, then wait for a yes to exactly it.** Where agents run, the fleet's start, the App or its skip, project settings, the host setting, the brain, phone access and a new repository each preview first; confirm with that preview's own `--yes` or `--yes --operation <id>`. Creating a repository, any write, spend, secrets and publishing always ask; a teacher's line never stands in for that ask.
- **Never touch a login.** A missing sign-in gets its walk-through and a link; the user signs in themselves, in their own terminal or browser. Never run a sign-in for them (no `github_login.py sign-in --yes`, no `gh auth login`), and never read, pass or store a credential. Continue only on the installed setup's read-only check.
- **Credentials stay out of the conversation.** Never ask for a key or token in chat or put one in a prompt, argument, URL, log, issue or file. Keys go only through the tools' protected setup, into owner-only state on this computer or CloudRoom's secret store. Save the user's exact words only under [open-development](../../contracts/open-development.v1.md).
- **Uncertain is never retried blindly.** Run the same command again: it reads its record first and never repeats an effect.
- **Read JSON and exit codes, never a screen.** Run installed programs by absolute path. Python 3.9+ only: no Rust, Cargo, Node, npm or source build; if a step seems to need one, stop and say so.
- **Free now; other charges are separate.** OpenWiz is free now. Paid plans come later. CloudRoom and model charges are separate and not included. More Cloud Credits are CloudRoom's own plan, from `https://cloudroom.dev/pricing`. Referral verification is unavailable. No referral is applied. Never add a code or parameter to that link.

Keep `<root>` (default `$HOME/.local/lib/openwiz`), and the `build` and `state_root` paths `install` prints as `<build>` (also `build=<build>` in the shell) and `<state>`, all absolute and owner-only. Run runtime tools with `python3 -I -B` and `OPENWIZ_STATE_DIR=<state>`, and pass `--state-dir <state>`.

## 1. Preflight

```sh
openwiz=<private temporary folder>/openwiz
git clone --depth 1 https://github.com/openwizdev/OpenWiz "$openwiz"
python3 -I "$openwiz"/tools/install/install preflight
```

It reads Python, the target, disk space and whether `room-cli`, `gh` and `git` are on `PATH`; it runs none of them. Exit 5 names each missing item and its `next` step: tell the user plainly what they do themselves (Cloudroom: install the app and sign in; `gh`: install it and run `gh auth login` in their own terminal).

Done when preflight passes, or the user has each next step.

## 2. Verified install

```sh
python3 -I "$openwiz"/tools/install/install download --target <target> --dir <private download folder>
python3 -I "$openwiz"/tools/install/install install --assets <private download folder> --target <target> --root <root>
```

A refusal leaves the previous build selected: report it, never work around it. A checksum proves the files are the release's, not who published them.

Done when `install` printed `"activated": true` with the version, target, `build` and `state_root`.

## 3. Setup and connections

```sh
python3 -I "$openwiz"/tools/install/install open --root <root> --browser
python3 -I -B "$build"/runtime/setup/setup.py check --state-dir <state>
```

`open` serves only this build's setup page on `http://127.0.0.1:7370/setup` (add `--state-root <state>` for a custom state). Read each component's state (`verified`, `missing`, `refused`, `unknown`) and `next` step; only the check marks a component ready. Reuse the user's current CloudRoom sign-in and harnesses. GitHub, the App, the project and its brain wait for the repository the user picks on the onboarding road. Phone access is optional: `python3 -I -B "$build"/runtime/access/access.py`, as its README says. Run `check` after each change.

Done when CloudRoom reads `verified`, or the user chose to stop with the remaining `next` steps.

## 4. Teach

From here the agent is a teacher. At each moment named in **bold** below, say that moment's line from [teach.md](teach.md), filling each `<...>` from what just happened and keeping the rest of its words. Say **Up front**'s three lines once, then **Install done**.

Done when the user has heard both.

## 5. The onboarding road

Continue only if the user wants their first build; otherwise finish with the install and any outstanding setup steps. Pass one owner-only `--state <file>` outside the project to every `first_fleet.py` command (`python3 <this skill's folder>/scripts/first_fleet.py`), from the project's clone once there is one. To resume, run `first_fleet.py next --state <file> --setup-state <state>`: it reads only that file and the repository setup prepared, and prints the first unfinished step and its command. Exits: 0 done, 1 read failure, 2 usage, 5 refused, 6 uncertain, 7 busy, 10 state unavailable, 12 preview awaiting `--yes`.

### 1. Where agents run

Run `first_fleet.py where --agents local --build "$build"`. It checks this machine: a GitHub sign-in, Claude Code or Codex on `PATH`, and OpenWiz's local driver. For anything missing it prints **Where agents run**'s walk-through line with a link; say it as printed. The user signs in themselves; run it again when they say done. Exit 12 prints what this machine's agents cost. Then ask **Where agents run**'s question, suggesting this machine with the harness found, and add that cost and that Cloudroom uses Cloud Credits. Cloudroom is the cloud host today. On the answer, run `where --agents local|cloud --build "$build" --yes`: it records the verified build's `runtime/adapters` as this machine's drivers. With no local driver, offer Cloudroom or stopping.

Done when `where` recorded the answer.

### 2. Choose a start

Offer three ways to start: a small change in a repository they have, a fresh project from their idea, or something they've always wanted to build. Anyone without an idea gets two or three ideas from that choice's group in [ideas.md](ideas.md); their own idea always wins. Then its one repository:

- **A repository they have:** confirm it, and that the fleet opens branches and pull requests there, then run `first_fleet.py select --repo <owner>/<name>`.
- **A new repository:** GitHub sign-in first, which the person does themselves: show them `python3 -I -B "$build"/runtime/setup/github_login.py sign-in --state-dir <state> --yes` to run in their own terminal (it opens GitHub's browser page), and wait until they say done. Then run the read-only check, `python3 -I -B "$build"/runtime/setup/github_login.py status --state-dir <state>`, and continue only when it reads their account. Then `first_fleet.py create-repo --repo <owner>/<name>` previews it and its one README commit; on the yes, add `--yes`. Exit 6: run it again. The user makes or picks its Cloudroom project.

Done when the idea and one repository are chosen and read back. There is no second repository.

### 3. Connect

For that repository, each tool previews and applies only on the yes (`--yes`, or `--yes --operation <id>` from its preview):

1. **Sign-in:** run the read-only `github_login.py status --repository <owner>/<name> --state-dir <state>`. Only its account and push-access read-back count. Signed out, or without push access, the person fixes it themselves, as in step 2 (`github_login.py sign-in --repository <owner>/<name> --state-dir <state> --yes` in their own terminal); then run `status` again.
2. **Prepare:** `setup.py prepare --state-dir <state> --repository <owner>/<name> ...` with the Cloudroom project and the harness, model and effort the user picks from `openwiz models --json`, one question each, with a recommendation. On this machine, offer only the harnesses `where` found.
3. **The App, or an explicit skip:** recommend the App, set up as `setup`'s "The App" says. Only the user's answer selects `github_login.py skip-app`; an App failure never becomes a skip.
4. **The brain:** `<build>/openwiz init --repository <owner>/<name> --state-dir <state> --json`, then `--yes --operation <id>`. Say in one line where it went; the user merges its pull request. For a public repository's private companion, run `first_fleet.py decisions --setup-state <state>`, then `--yes`, and ask the user to restart the OpenWiz server.
5. **Carry it:** `setup.py check --state-dir <state>`, then `first_fleet.py continue --setup-state <state> --explained`. It refuses, naming each component that is missing, refused, unknown or stale, and withdraws what it carried before; follow that `next` step and run both again.

Done when `continue` prints the carried setup and the acting identity.

### 4. Grill

Say **The grill**'s first line, then run `grill` briefly: one or two rounds of at most three questions, each with a recommendation, steered to 4 to 7 small, mostly independent tickets, even for a small change. When its summary is ready, show it and say **The grill**'s second line. Only the user's yes here confirms it; anything else is a change to make. Save the yes as `grill` says, then run `first_fleet.py grill --confirmed <its private comment URL>`.

Done when `grill` recorded the confirmation.

### 5. Agents

Harness, model and effort were answered at Connect. Save `openwiz models --json` privately, then run `first_fleet.py choose --options <saved file> --from-setup` (without a carried setup, ask the three and pass `--harness --model --effort`). Then run `setup` so both builder tables name exactly these settings, sourced to the user's decision; setup keeps reviewers in the other family. Then run the same `choose` again: it reads the tables back.

Done when the choice is recorded and the builder tables match it.

### 6. Host setting

On this machine, first ask the owner to pick the harness permission mode, once. Run `first_fleet.py mode`: it lists that harness's modes, each with what it lets an agent do. Explain each one plainly, as printed, and recommend none: never pick, default or widen a mode for the owner, and touch no login. On their answer, run `first_fleet.py mode --mode <their pick>`. From that one pick it saves this machine's host-side approval for the repository and harness, outside the repository, through the local driver's setup step; it never changes or widens an approval already saved. The host setting below adds the matching `fleet.md` row. The local driver passes the mode to the harness unchanged and starts nothing unless the row and the approval match.

Then run `first_fleet.py setting`. For this machine it previews one pull request that adds `docs/agents/host.md` with `Host: local` (the host launch-fleet reads) and one row, `| Harness permission mode | `<their pick>` |`, to the `docs/agents/fleet.md` setup wrote (the mode the local driver reads), changing no other line. On the yes, run it with `--yes` and ask the user to merge it. It never adds a second row or replaces a mode the owner already saved: it names that row and asks. It never writes over a branch `openwiz/host-setting` that holds anything else, and it says the pull request is ready only once both files read back from it exactly; a failed or uncertain write is said, never retried blindly: run it again to read the branch first. For Cloudroom no file is needed: it says so and exits 0. It never overwrites a host the project already names.

Done when both settings match the answers, or their pull request is open.

### 7. Plan

The plan checks itself. Run `to-spec` with the confirmed grill. It writes the spec, runs `to-tickets`, whose checks record the machine plan approval, and makes the spec's video. Say **The spec and its video** with its video link. Ask nothing here: no spec or plan approval. For now the owner steers through the orchestrator: what they want changed goes to this chat, never a comment on the video, which steers nothing until OpenWiz #1402. launch-fleet's one-time notice saying so is normal, not a hold. When a check refuses, re-cut the plan; never ask the user to approve it instead. Then run `first_fleet.py spec --spec <N> --repo <owner>/<name>`.

Done when the machine plan approval is on the spec and `spec` saved it.

### 8. Launch

Preview with `first_fleet.py launch --spec <N>`. It reads the spec's machine plan approval for this grill, the host the user chose (this machine only once its host setting is merged) and launch-fleet's own frontier, then prints the start's effects and one question that names the host and says it can cost money. Show the effects and ask that question as printed. This is the one yes before the fleet starts; never skip it, even though the cost was shown at **Where agents run**. On the yes, run it with `--yes --confirm <the digest it printed>`. It refuses if anything changed since the preview: preview again and ask again. Say **The fleet starting** as it prints it. Exit 6 is uncertain: run it again to read the fleet record, never start by hand.

Done when the start is recorded, or recorded uncertain and reported so.

### 9. Watch

Run `first_fleet.py progress --spec <N> --openwiz <absolute path to openwiz>` when the user asks or a moment may have happened, and say each moment's line once: **A pull request opened**, then **Reviewed**. A count is never a merge. When a pull request merges, run `first_fleet.py first-merge --pr <number>`: it reads the merge back from GitHub and prints **Merged** and **The closing offer**; say both. On the answer: stay as the project's orchestrator (launch-fleet), start a new project (this road again, with a new state file), or keep building (the grill again, for the next idea).

Done when the user has heard the closing offer.

## Doctor

When setup or a fleet seems stuck, or the user asks whether setup is right, run the doctor from the project's clone:

```sh
python3 -I <this skill's folder>/scripts/doctor.py --repo <owner>/<name> --state-dir <state> --build <build> --openwiz "$openwiz" [--driver <the driver this machine runs>]
```

In order, it checks the labels, the App, that the acting login is a record author, the harness, the driver's `version` and the skills, through the checks that already exist. It only reads. Show each problem line as it is; its `Fix:` is the command that fixes it. A sign-in fix is the user's to run: show it, never run it. Exit 0 prints one all-clear line; 5 prints the problems.

Done when it prints all clear, or the user has each fix.

## Recovery and removal

If setup does not open, run `install status --root <root>` and `open` again; a failed bind never proves another page is OpenWiz's. To remove OpenWiz, stop only its own setup server and delete `<root>`; keep `<state>` unless the user asks. Removal revokes nothing: show the user how to uninstall the App or remove repositories from it, delete any phone-access tunnel or rule, and delete the fleet loops in CloudRoom. Never remove or revoke anything without their yes.
