---
name: install
description: Install OpenWiz from its one line, "Install OpenWiz from github.com/openwizdev/OpenWiz", then optionally run a resumable first fleet. Asks first where the user's agents run (this computer, boat.dev or CloudRoom; CloudRoom is optional), checks the machine, installs the verified prebuilt release (no Rust or Node), checks setup's connections (CloudRoom's only when chosen), and either connects one repository and starts its CloudRoom fleet through launch-fleet, or, without CloudRoom, says what works today and how to start a builder by hand. Use to install, repair, update or remove OpenWiz, or to start or resume a first fleet. For a project's docs/agents/ settings alone, use setup.
version: 0.2.2
---

# Install OpenWiz

The user pasted one line into their agent:

> Install OpenWiz from github.com/openwizdev/OpenWiz

Take them from that line to setup, then to their first fleet if they want one. Every step reads before it writes and reuses what an earlier one recorded, so a repeat or a fresh session resumes at the first unfinished step. Tools: OpenWiz's installer (`tools/install/install`, over its `contracts/install.v1.md`) and installed runtime (`contracts/setup.v1.md`), the agent CLI ([cli.v1](https://github.com/openwizdev/WizSkills/blob/350887bbc00ca8e11ee6f084e4936b4fabf852fa/contracts/cli.v1.md)), and for the first fleet `grill`, `to-spec`, `to-tickets` and `launch-fleet`. This skill adds no installer, engine, approval or planner, and never runs a fleet tick itself.

**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.

## Guards

- **Install permission is not work approval.** Installing or finishing setup approves no spec, plan or start. The first fleet needs the user's spec confirmation, exact-plan approval and a separate yes to start. Never write, fake or infer an approval, or ask for blanket consent.
- **Show every effect, then wait for a yes to exactly it.** CloudRoom's install, the App or its skip, project settings, the brain, phone access, the demo repository and the launch each preview first; confirm with that preview's own `--yes` or `--yes --operation <id>`, where `<id>` is the preview's `operation_id` (for `cloudroom.py install`, the `operation_id` inside its `operation`). CloudRoom's sign-in has no preview: ask in chat first, then run it.
- **Credentials stay out of the conversation.** Never ask for a key or token in chat or put one in a prompt, argument, URL, log, issue or file. Keys go only through the tools' protected setup, into owner-only state on this computer or CloudRoom's secret store. Save the user's exact words only under [open-development](https://github.com/openwizdev/WizSkills/blob/350887bbc00ca8e11ee6f084e4936b4fabf852fa/contracts/open-development.v1.md).
- **Uncertain is never retried blindly.** Run the same command again: it reads its record first and never repeats an effect.
- **Read JSON and exit codes, never a screen.** Run installed programs by absolute path: there is no `openwiz` on `PATH`; it is `<root>/current/openwiz`. Python 3.9+ only: no Rust, Cargo, Node, npm or source build; if a step seems to need one, stop and say so.
- **CloudRoom is optional.** OpenWiz 0.1.0 installs, signs in to GitHub and plans without CloudRoom, and a builder can be started by hand on this computer or on boat.dev. Only its automatic fleet (step 6: the fleet's own thread and loops) runs in CloudRoom; the automatic fleet without CloudRoom arrives in 0.1.1. Never present CloudRoom as required. There is no setup page or local server in 0.1.0: setup is the commands below.
- **Free now; other charges are separate.** OpenWiz is free now. Paid plans come later. CloudRoom and model charges are separate and not included. More Cloud Credits are CloudRoom's own plan, from `https://cloudroom.dev/pricing`. Referral verification is unavailable. No referral is applied. Never add a code or parameter to that link.

## Where your agents run

Ask this first, before step 1, in these exact words, with the three as equal choices and no recommendation:

> Where should your agents run? This computer (Claude Code or Codex you're signed in to), boat.dev, or CloudRoom.

Keep the answer for the whole install. **This computer** and **boat.dev** skip every CloudRoom step: CloudRoom's install and sign-in, and its rows in step 3. **CloudRoom** runs them all, exactly as written. In a new session that has not heard the answer (after step 4's restart, too), ask it again before anything else. The user can change their mind at any time: moving to CloudRoom runs step 3's CloudRoom rows, then continues where they were.

Keep `<root>` (default `$HOME/.local/lib/openwiz`), and the `build` and `state_root` paths `install` prints as `<build>` (also `build=<build>` in the shell) and `<state>`, all absolute and owner-only. Run runtime tools with `python3 -I -B` and `OPENWIZ_STATE_DIR=<state>`, and pass `--state-dir <state>`. After a restart, read them from the installed files, as Resume says.

## Resume

A new session, whatever the user said ("continue", or the one line again), starts here: find the first unfinished step and resume there. Use only the installed files, never a temporary clone: a restart loses it.

```sh
<root>/current/openwiz --build-identity
build=$(readlink <root>/current); state=${build%/service/builds/*}
OPENWIZ_STATE_DIR="$state" python3 -I -B "$build"/runtime/setup/setup.py check --state-dir "$state"
OPENWIZ_STATE_DIR="$state" python3 -I -B "$build"/runtime/setup/github_login.py status --state-dir "$state"
grep -m1 '^version:' ~/.claude/skills/install/SKILL.md "${CODEX_HOME:-$HOME/.codex}/skills/install/SKILL.md"
```

`<root>` is `$HOME/.local/lib/openwiz` unless the user chose another. Take the first that holds:

- No `<root>/current`, or `--build-identity` does not read 0.1.0: resume at step 1.
- `status` does not read the GitHub account, or the user chose CloudRoom and `check` does not read `cloudroom_login_verified`: resume at step 3. `identity_unreadable` means GitHub gave no clear answer: wait a minute and run `status` again; it clears.
- The running agent's `install/SKILL.md` is missing, or does not read `version: 0.2.2`: resume at step 4. When that agent's folder holds OpenWiz's 18 skills, run only step 4's overwrite block, which needs no OpenWiz clone. When they are missing, copying them needs OpenWiz's installer again: step 1's `git clone` into a new temporary folder (it installs nothing), then all of step 4.
- Otherwise resume at step 5; with CloudRoom, for a first fleet already under way, at step 6 with `first_fleet.py next`.

## 1. Preflight

```sh
openwiz=<private temporary folder>/openwiz
git clone --depth 1 --branch v0.1.0 https://github.com/openwizdev/OpenWiz "$openwiz"
python3 -I "$openwiz"/tools/install/install preflight
```

`git clone` may warn that `refs/tags/v0.1.0` is not a commit (it is an annotated tag) and print detached-HEAD advice: both are harmless. Preflight reads Python, the target, disk space and whether `room-cli`, `gh` and `git` are on `PATH`; it runs none of them. It prints `target` for the next step. For 0.1.0, supported means a Mac with Apple silicon (`aarch64-apple-darwin`) or Linux on x86_64 (`x86_64-unknown-linux-gnu`). An Intel Mac (`x86_64-apple-darwin`) has a 0.1.0 build, but CloudRoom offers no Intel Mac build today: if the user chose CloudRoom, say so plainly, offer this computer or boat.dev instead, and stop before installing if they keep CloudRoom. Exit 5 names each missing item and its `next` step: tell the user plainly (`gh`: install it and `gh auth login`). `room-cli` reading `missing` never stops preflight; it matters only if the user chose CloudRoom, and step 3 installs CloudRoom then. Linux on ARM is refused. On Linux the build needs glibc 2.34 or later (`ldd --version`). Read its `checks` even on exit 0: `gh` reading `missing` does not stop preflight, but setup needs it. Then the user installs GitHub CLI first, from https://cli.github.com, and `gh --version` shows it is there; then continue.

Done when preflight passes, or the user has each next step.

## 2. Verified install

```sh
python3 -I "$openwiz"/tools/install/install download --target <target> --dir <private download folder>
python3 -I "$openwiz"/tools/install/install install --assets <private download folder> --target <target> --root <root>
```

**While 0.1.0 is not yet GitHub's Latest release,** `download` refuses ("the step could not be completed safely") because `releases/latest/download/...` answers 404. Check that with `curl -sI https://github.com/openwizdev/OpenWiz/releases/latest/download/openwiz-<target>.sha256`. On a 404, and only then, fetch the same three files from the pinned tag into a new owner-only folder, then run the same `install` above:

```sh
umask 077; mkdir <private download folder>
for f in openwiz-<target>.sha256 openwiz-<target>.manifest.json openwiz-0.1.0-<target>.tar.gz; do
  curl -fsSL --proto '=https' -o <private download folder>/"$f" https://github.com/openwizdev/OpenWiz/releases/download/v0.1.0/"$f"
done
```

`install` checks the manifest against its checksum and every file against the manifest, as `download` would. Any other refusal leaves the previous build selected: report it, never work around it. A checksum proves the files are the release's, not who published them.

Then prove the build:

```sh
<root>/current/openwiz --build-identity
```

It prints `"version":"0.1.0"` and the release's `source` commit. On Linux, a `weak version 'GLIBC_2.39' not found` line on stderr is harmless. OpenWiz's skills go into the user's agents at step 4, after setup.

Done when `install` printed `"activated": true` with the version, target, `build` and `state_root`, and `--build-identity` read 0.1.0.

## 3. Setup and connections

```sh
python3 -I -B "$build"/runtime/setup/setup.py check --state-dir <state>
```

It reads each connection and records only its own results in `<state>`. It prints one bare code per component and no next step, so read each code below. Run `check` again after each change.

**CloudRoom** (`cloudroom`), only if the user chose CloudRoom. Otherwise skip this table and ignore every `cloudroom_*` code `check` prints: it never blocks this install. With CloudRoom, use `python3 -I -B "$build"/runtime/cloudroom/cloudroom.py status | install | sign-in --state-dir <state>`:

| Code | Next |
| --- | --- |
| `cloudroom_login_verified` | Done: signed in now. |
| `cloudroom_not_installed` | `cloudroom.py install --state-dir <state>` previews CloudRoom's checksum-checked installer; on the yes, `cloudroom.py install --yes --operation <id> --state-dir <state>`. Then sign in. |
| `cloudroom_installed`, `cloudroom_reused`, `cloudroom_login_missing`, `cloudroom_login_unknown` | `cloudroom.py sign-in --state-dir <state>` opens CloudRoom's own sign-in once (or the app, the first time); the user signs in there, never in chat. Then `status`. On Linux, sign-in needs a desktop session and FUSE (the AppImage needs `fusermount`, from `fuse3` or `libfuse2`): a headless VPS cannot sign in. If nothing opens within a minute, the user opens `~/Applications/Cloudroom.AppImage` themselves. |
| `cloudroom_unsupported` | CloudRoom offers no build for this computer (an Intel Mac, or Linux on ARM): say so plainly, and offer this computer or boat.dev instead. |
| `cloudroom_source_unchecked` | `cloudroom.py install` could not read or check CloudRoom's published installer and its checksum (a network failure, or CloudRoom changed its download guide or release): nothing was proposed or downloaded. Run `install` again shortly. If it stays, `cloudroom.py install --yes --state-dir <state>` opens CloudRoom's download page once instead; the user installs CloudRoom from there, opens it once and signs in. Then `status`. |
| `cloudroom_installing` | An install is running: `status` again shortly. |
| `cloudroom_install_uncertain` | A plain `install` only shows the pending operation again. Read its `operation_id` from `cloudroom.py install --state-dir <state>` (inside `operation`), then reconcile that same operation: `cloudroom.py install --yes --operation <operation_id> --state-dir <state>`. Never preview a new install over it. |
| `cloudroom_install_failed` | Preview `install` again and ask again. |
| `cloudroom_install_declined` | The user said no: stop, or preview again only if they ask. |
| `cloudroom_checksum_mismatch` | Nothing was installed: report it and stop. |
| `cloudroom_destination_blocked` | Another file is at `~/Applications/Cloudroom.AppImage`: the user moves it, never you. |
| `cloudroom_unreadable` | `check` again; if it stays, `status`. |

**GitHub:** `python3 -I -B "$build"/runtime/setup/github_login.py sign-in --state-dir <state>` reuses a verified login. Signed out, it previews (`login_needed`): GitHub's own browser page and a one-time code, with no token pasted. On the yes, run it with `--yes`. `identity_unreadable` (from `status`, `sign-in` or `check`) means GitHub gave no clear answer: wait a minute and run it again; it clears. If it stays, `gh auth status` shows whether the user is signed in. `login_gh_missing` means GitHub CLI is not installed: the user installs it from https://cli.github.com, then `gh --version` shows it is there; run the sign-in preview again.

**The rest** (`harness_unselected`, `identity_unselected`, `project_unprepared`, `app_missing`) is expected now: each waits for the repository the user picks under First fleet, and Connect sets it. Phone access is optional: `python3 -I -B "$build"/runtime/access/access.py configure --plan <private file> --state-dir <state>` previews it; `access.py --help` gives the plan's shape.

Done when GitHub's sign-in is verified and, only if the user chose CloudRoom, CloudRoom reads `cloudroom_login_verified`; or the user chose to stop with the remaining next steps.


## 4. Skills into your agents, then a restart

Only now, with setup checked and the logins done (GitHub's, and CloudRoom's if chosen), copy OpenWiz's skills into the user's agents:

```sh
python3 -I "$openwiz"/tools/install/install skills --root <root>
```

It copies the 18 skills into `<root>/skills` and into each agent folder present here: `~/.claude/skills` (Claude Code), `${CODEX_HOME:-$HOME/.codex}/skills` (Codex: `$CODEX_HOME/skills` when `CODEX_HOME` is set, otherwise `~/.codex/skills`), `~/.cursor/skills`, `~/.config/opencode/skills` and `~/.grok/skills`. It prints `"outcome": "installed"` even when it copied nothing, so check two things: its `harnesses` entry for the agent you are running in reads `installed`, and that agent's folder, the entry's `path` (`ls ~/.claude/skills`, or for Codex `ls "${CODEX_HOME:-$HOME/.codex}/skills"`), now holds all 18 by name: `ask-wiz`, `build-ticket`, `diagnose`, `grill`, `handoff`, `hill-climb`, `huntr`, `image`, `install`, `launch-fleet`, `research`, `review-ticket`, `setup`, `to-spec`, `to-tickets`, `triage`, `wayfind` and `where-are-we`. If the entry reads `absent`, that agent's folder (`~/.claude`, or for Codex `$CODEX_HOME` when set, otherwise `~/.codex`) is missing on this computer: tell the user which folder, that their agent has no OpenWiz skills, and its `next` step; never create the folder yourself.

**A skill of the user's own with one of these names refuses the whole step** (`"outcome": "refused"`, exit 5, nothing copied): an entry reads `refused` with `next` "`<folder>` is not an OpenWiz copy; nothing was changed". It names only the first such folder per agent, so find them all (this skill's folder is the one you read it from; with none on this computer, run the overwrite block's fetch and verify lines below first and use `"$wizskills"/skills/install`):

```sh
python3 -I <this skill's folder>/scripts/skill_clash.py list --build "$build" --root <root>
```

It only reads, and checks the agent folders exactly as the installer does, as if the moves were done. When `blocked` is empty, show the user every `clashes` folder (`path`, and its `rename_to`), then ask exactly its `question`, word for word, and nothing else, for example: "You already have your own skills named handoff and research. Rename yours to handoff-mine and research-mine (and their name lines) so OpenWiz can install? They keep working under the new names. (yes/no)". When a `<name>-mine` is already taken, it picks `<name>-mine-2` and the question says so.

- **Yes:** do the moves yourself, with the `operation` that `list` printed:

  ```sh
  python3 -I <this skill's folder>/scripts/skill_clash.py rename --build "$build" --root <root> --yes --operation <operation>
  ```

  It moves each folder to its `rename_to` and sets its SKILL.md `name:` line to match, then checks each one (the new folder has the new name line, the old path is gone): exit 0 and every entry `moved`. Then run `install skills` again and carry on with the checks above. Exit 5 means the folders changed since `list`, or the installer would now refuse: nothing moved; run `list` again. Exit 6 names a move that did not check out: report it and stop.
- **No:** say plainly that OpenWiz's skills were not installed in any of your agents, and stop. Move nothing.

Never move, rename or delete a user's skill without that yes, and never touch a folder OpenWiz put there (it holds `.openwiz-skill`): `skill_clash.py` leaves those alone. When `blocked` has entries, there is no `question` and nothing may move: something the installer would still refuse after the renames (a linked folder such as `~/.config`, a skill whose `SKILL.md` is a link, a stray folder). Show each `path` and its `why`, say OpenWiz's skills were not installed, and stop.

Then make every installed copy of this skill this one, the whole folder. The copy `install skills` just wrote comes from the 0.1.0 package: it is older (`version: 0.2.0`), its `SKILL.md` and scripts still name a setup page and a server 0.1.0 removed, and a new session loads it whatever the user says. Fetch the pinned WizSkills commit into a temporary folder (it installs nothing), verify `HEAD` and the `skills/install` tree OID before copying anything, then overwrite each agent folder that holds OpenWiz's copy (marked by `.openwiz-skill`), and check every file by content:

```sh
wizskills=<private temporary folder>/WizSkills
expected_commit=350887bbc00ca8e11ee6f084e4936b4fabf852fa
expected_tree=66899e4ffd5c7ca78d53115cbdbcdc69671a655f
git init -q "$wizskills"
git -C "$wizskills" fetch -q --depth 1 https://github.com/openwizdev/WizSkills "$expected_commit"
git -C "$wizskills" checkout -q --detach FETCH_HEAD
head_commit=$(git -C "$wizskills" rev-parse HEAD)
install_tree=$(git -C "$wizskills" rev-parse HEAD:skills/install)
if [ "$head_commit" != "$expected_commit" ] || [ "$install_tree" != "$expected_tree" ]; then
  echo "SOURCE MISMATCH: expected $expected_commit ($expected_tree), got $head_commit ($install_tree)"
else
  src="$wizskills"/skills/install
  fixed() { grep -q '^version: 0.2.2$' "$1/SKILL.md" && ! grep -q -e 'install ope[n] ' -e 'from the setup pag[e]' -e 'Restart the OpenWiz serve[r]' "$1/SKILL.md" "$1"/scripts/*.py; }
  if fixed "$src"; then echo "source ok"; else echo "NOT THIS SKILL: $src"; fi
  fixed "$src" && for d in "$HOME/.claude/skills" "$HOME/.codex/skills" ${CODEX_HOME:+"$CODEX_HOME/skills"} "$HOME/.cursor/skills" "$HOME/.config/opencode/skills" "$HOME/.grok/skills"; do
    [ -f "$d/install/.openwiz-skill" ] || continue
    cp -R "$src"/. "$d/install/"
    same=yes; for f in $(cd "$src" && find . -type f); do cmp -s "$src/$f" "$d/install/$f" || same=no; done
    if [ "$same" = yes ] && fixed "$d/install"; then echo "ok: $d/install"; else echo "STILL OLD: $d/install"; fi
  done
fi
```

If it prints `SOURCE MISMATCH` or `NOT THIS SKILL` (the fetch failed, or `HEAD` or `HEAD:skills/install` did not match the expected hashes), nothing was copied: stop before the restart and tell the user. A `STILL OLD` line means that folder's copy did not take (it may not be writable): report it and fix it before the restart; never restart onto an old copy. A later `install skills` run, such as a repair, writes the old copy again: repeat this block after it.

An agent finds new skills only when it starts, so the user restarts it now: a new session of their agent, then exactly "continue the OpenWiz install". Ask them to type those words: a bare "continue" can load no skill at all. The new session loads this skill from the folder above and starts at Resume. Any installed copy that does not read `version: 0.2.2` is older than this one; if you are told to install again, follow this skill (https://github.com/openwizdev/WizSkills/blob/350887bbc00ca8e11ee6f084e4936b4fabf852fa/skills/install/SKILL.md) and resume at the first unfinished step, as Resume says.

Done when the running agent's folder holds the 18 skills by name and every `ok:` line printed with no `STILL OLD`, or the user knows which folder is missing, and the user knows to restart; or the user said no to the renames and knows OpenWiz's skills were not installed.

## 5. Explain

Say this before asking about a project, once:

> You bring an **idea**. I **grill** you with a few quick questions to settle it, then write it up as a **spec** for you to confirm. The spec becomes small **tickets**, a plan you approve as a whole. Each ticket gets its own **builder**, an agent that writes the code on its own branch. A **reviewer** from a different model family reviews each pull request independently, and approved, green work **merges** by the project's rules. Nothing starts until you approve the plan.

Done when the user has seen it.

## Without CloudRoom

If the user chose this computer or boat.dev, say this, then help with what they pick:

> Installed. Without CloudRoom today you can plan (grill, spec, tickets) and start a builder on this computer or on boat.dev by hand. The automatic fleet without CloudRoom arrives in 0.1.1. Want CloudRoom now instead? It's optional.

On a yes to CloudRoom, run step 3's CloudRoom rows, then step 6. Otherwise:

- **Plan:** before writing anything for the plan, run `jq --version` and `gh --version`. If jq is missing or fails, have the user install jq with their package manager. If GitHub CLI is missing, fails, or reports a version below 2.94, have them install or upgrade GitHub CLI from https://cli.github.com. Recheck both before continuing (GitHub CLI must be 2.94 or newer).
  In the project's clone, run `setup` (it writes `docs/agents/`, including the `Record authors` row; the App is optional, and skipping it is the user's answer), then run `grill` through the user's confirmation. Use steps 1–2 of `to-spec` to write and read back the spec. Run steps 1–4 of `to-tickets` to create the tickets, post and verify the machine plan approval, then apply and read the ready labels back. Skip the `launch-fleet` handoff and the steering video on this path. Give the user the spec and plan links and return to the hand-start steps below.
- **Start one ticket's builder by hand.** Use the GitHub CLI version checked above. In the project's clone, run `git fetch origin`. If it succeeds, use the same reader as the builder:
  `python3 -I "$build"/runtime/skills/build-ticket/scripts/ticket.py read <owner>/<name> <N>`
  For a new start, proceed only on exit 1 with `ready: no: no launch-fleet start record from a record author`. This means the ticket is open, has `ready-for-agent` and owned paths, has no `needs-info`, and every blocker is closed as completed. For any other refusal or unreadable result, give the reason and stop. If it already reads `ready: yes`, check the existing start and use its run if one exists instead of posting another start or launching again.

  Before asking to post, verify that `gh api user --jq .login` is the user's signed-in account and appears in the `Record authors` row under GitHub identity in `git show origin/main:docs/agents/fleet.md`, the same ref the builder reads. If setup's row is missing or the login is absent, stop and have the user correct and merge the project's settings first.

  Prepare the chosen host below, show the exact repository, ticket, harness, model, and any charges, and ask for the user's separate yes to that start. After the yes, fetch again and repeat the pre-start read and identity checks. Post from the verified account: `gh issue comment <N> --repo <owner>/<name> --body "launch-fleet: started by hand"`. Verify the exact comment and author on GitHub. If the post was uncertain, read first and retry only if the comment is absent. Then run the same ticket read again. Only exit 0 with `ready: yes` allows starting either driver; on any other result, report the reason and stop.

  - **This computer** (the installed local driver; the user's own signed-in `claude` or `codex` and `gh`). A builder needs a permission mode, or its harness refuses every tool: the user chooses it (a `claude --permission-mode` value, or a `codex --sandbox` value) and you never pick or widen it. Save it twice, each on its own yes. First, as one row in `docs/agents/fleet.md` on the default branch: `` | Harness permission mode | `<mode>` | ``. Second, on this computer, use `umask 077; mkdir -p ~/.local/state/openwiz-local`. Read the existing owner-only JSON object in `~/.local/state/openwiz-local/approvals.json` first. Start with an empty object only if the file is absent. Stop for a symlink, a file not owned by the user or not owner-only, or invalid JSON (including duplicate keys or a repository value that is not an object).

    Preview the selected repository, harness and old and new modes (say “no entry” when absent). Wait for the user's yes to this local change. If the file changed since the preview, read it again and ask on the new preview. In the object you read, set only `approvals[repository][harness] = mode`, creating that repository's object only if absent. Preserve every other repository and harness entry. Write the complete updated object to a temporary file in the same directory, `chmod 600` it, then atomically rename it over `approvals.json`. Before proceeding, read the saved JSON back and verify it is owner-only, the selected entry matches the approved mode, and every other entry equals the original.

    After the shared start gate above passes, run this with `build` as Resume sets it:

    `echo '{"repository":"<owner>/<name>","ticket":<N>,"skill":"build-ticket","harness":"<claude or codex>","model":"<model>"}' | "$build"/runtime/adapters/local/driver start`
    It works in its own clone under `~/.local/state/openwiz-local/work/`, and answers `{"run": "run-..."}` after watching the first turn for about 30 seconds; keep the run id. A refusal is `{"error", "next"}`: do its `next`. To wake the builder after review comments: `echo '{"run":"<run>"}' | "$build"/runtime/adapters/local/driver wake`; to stop it, the same with `stop`.
  - **boat.dev** (bills per second while a sandbox runs, on the user's plan: say so first). The user installs the `boat` CLI, signs in to it themselves, and in boat's dashboard connects GitHub and their harness's key or subscription; you touch none of it. The installed package's boat driver refuses (0.1.0 ships no `wizskills.lock` beside it), so run it from a fresh 0.1.0 checkout, which installs nothing:
    `ow=<new private temporary folder>/openwiz; git clone --depth 1 --branch v0.1.0 https://github.com/openwizdev/OpenWiz "$ow"`
    `echo '{"repository":"<owner>/<name>","ticket":<N>,"skill":"build-ticket","harness":"<claude or codex>","model":"<model>"}' | "$ow"/adapters/boat/driver start`
    Keep the run id it answers. Wake and stop as above, with `"$ow"/adapters/boat/driver` (run state is in `~/.local/state/openwiz-boat`, so any fresh checkout works). A sandbox boat stopped (an hour with no running turn) is never woken: start again.
- **Review and merge** stay with the user on 0.1.0 without CloudRoom: no reviewer starts on its own (step 5's other-family reviewer comes with the automatic fleet in 0.1.1). They review the pull request, comment, then wake the builder.

Done when the user has seen the text above and has what they chose: planning, a hand start, or CloudRoom.

## 6. First fleet

Continue only if the user chose CloudRoom and wants a first fleet; otherwise finish with the install and any outstanding setup steps, or with "Without CloudRoom" above. On 0.1.0 this automatic fleet runs in CloudRoom, even with builders on boat.dev: the fleet's own thread and loops are CloudRoom's. The automatic fleet without CloudRoom arrives in 0.1.1. Pass one owner-only `--state <file>` outside the project to every `first_fleet.py` command (`python3 <this skill's folder>/scripts/first_fleet.py`), from the project's clone. To resume, run `first_fleet.py next --state <file> --setup-state <state>`: it reads only that file and the repository setup prepared, and prints the first unfinished step and its command. Exits: 0 done, 1 read failure, 2 usage, 5 refused, 6 uncertain, 7 busy, 10 state unavailable, 12 preview awaiting `--yes`.

### 1. Choose a project

Offer three or four fun, one-line ideas made up for this user, plus "your own idea". Then ask where it goes:

1. **A new private demo repository** (recommended). Step 3's GitHub sign-in comes first. Then `first_fleet.py create-repo --repo <owner>/<name>` previews the repository and its one README commit; on the yes, add `--yes`. Exit 6: run it again. The user makes or picks its CloudRoom project.
2. **An existing repository:** confirm it, and that the fleet opens branches and pull requests there, then run `first_fleet.py select --repo <owner>/<name>`.

Done when the idea and one repository are chosen and read back. There is no second repository.

### 2. Connect

For that repository, each tool previews and applies only on the yes (`--yes`, or `--yes --operation <id>` from its preview):

1. **Sign-in:** `github_login.py sign-in --repository <owner>/<name> --state-dir <state>`. Only the account and push-access read-back count.
2. **Prepare:** `setup.py prepare --state-dir <state> --repository <owner>/<name> --project <project id> --operator <login> --service-issue <N> --answer-thread <thread id> --harness <harness> --model <model> --effort <effort>`, every flag required, one question each, with a recommendation:
   - `--project`: the CloudRoom project the fleet runs in, by id (`<root>/current/openwiz ls --json` groups threads by project).
   - `--operator`: the name a loop's on or off switch records as who did it; recommend the user's GitHub login.
   - `--service-issue`: an open issue in that repository for OpenWiz's service records (not a pull request). With none, offer to open one, titled "OpenWiz service records", on the yes.
   - `--answer-thread`: the user's CloudRoom thread in that project that gets the fleet's answers, from the same `ls`; another project's thread reads `project_answer_refused`.
   - `--harness`, `--model`, `--effort`: what the user picks from `<root>/current/openwiz models --json`.

   Without `--yes` it prints the effects and an operation id; on the yes, run it again with `--yes --operation <id>`.
3. **The App, or an explicit skip:** recommend the App, set up with the installed `"$build"/runtime/github-app/setup.py` as the `setup` skill's "The App" says. Only the user's answer selects `github_login.py skip-app`; an App failure never becomes a skip.
4. **The brain:** `<root>/current/openwiz init --repository <owner>/<name> --state-dir <state> --json`, then `--yes --operation <id>`. Say in one line where it went; the user merges its pull request. For a public repository's private companion, run `first_fleet.py decisions --setup-state <state>`, then `--yes`.
5. **Carry it:** `setup.py check --state-dir <state>`, then `first_fleet.py continue --setup-state <state> --explained`. It refuses, naming each component that is missing, refused, unknown or stale, and withdraws what it carried before; follow that `next` step and run both again.

Done when `continue` prints the carried setup and the acting identity.

### 3. Grill

Run `grill` briefly: one or two rounds of at most three questions, each with a recommendation, steered to 4 to 7 small, mostly independent tickets. Save it as `grill` says.

Done when the user confirms the grill's summary.

### 4. Choose the agents

Harness, model and effort were answered at Connect. Ask only where the agents run: Cloud (recommended; it uses Cloud Credits) or Local. Save `<root>/current/openwiz models --json` privately, then run `first_fleet.py choose --options <saved file> --from-setup --agents cloud|local` (without a carried setup, ask the three and pass `--harness --model --effort`). Then run `setup` so both builder tables name exactly these settings, sourced to the user's decision; setup keeps reviewers in the other family. Then run the same `choose` again: it reads the tables back. Local is not available yet: say so, and offer Cloud or stopping.

Done when the choice is recorded and the builder tables match it.

### 5. Plan

Run `to-spec` and wait for the user's spec confirmation. Run `to-tickets` for 4 to 7 small tickets with disjoint owned paths and few arrows, then wait for the user's exact-plan approval; a change request is not an approval. Then run `first_fleet.py spec --spec <N> --repo <owner>/<name>`.

Done when the approval record on the spec is current and `spec` saved it.

### 6. Launch

Preview with `first_fleet.py launch --spec <N>`. Show its effects (one fleet thread and its loop, the frontier's builders and their other-family reviewer, Cloud Credits unknown until measured) and ask for a yes to exactly those. On the yes, run it with `--yes --confirm <the digest it printed>`. It refuses if anything changed since the preview: run `continue` or preview again and ask again. Exit 6 is uncertain: run it again to read the fleet record, never start by hand.

Done when the start is recorded, or recorded uncertain and reported so.

### 7. Watch

Run `first_fleet.py progress --spec <N> --openwiz <root>/current/openwiz` when the user asks, and point them to openwiz.dev/app. Unknown stays unknown, and a count is never a first merge. Reviews and merges follow on the fleet thread's loop. Then offer their next idea.

Done when the user has seen their agents' progress.

## Doctor

When setup or a fleet seems stuck, or the user asks whether setup is right, run the doctor from the project's clone:

```sh
python3 -I <this skill's folder>/scripts/doctor.py --repo <owner>/<name> --state-dir <state> --build <build> --openwiz "$build"/runtime [--driver <the driver this machine runs>]
```

In order, it checks the labels, the App, that the acting login is a record author, the harness, the driver's `version` and the skills, through the checks that already exist. It only reads. Show each problem line as it is; its `Fix:` is the command that fixes it. A sign-in fix is the user's to run: show it, never run it. Exit 0 prints one all-clear line; 5 prints the problems.

Done when it prints all clear, or the user has each fix.

## Recovery and removal

If something seems wrong, verify the build with a fresh clone (it installs nothing): `openwiz=<new temporary folder>/openwiz`, step 1's `git clone`, then `python3 -I "$openwiz"/tools/install/install status --root <root>`. It verifies the selected build and changes nothing. A changed file reads `installed asset mismatch`, and `install` refuses the same way. To repair it and keep the settings, delete only the `<root>/current` link and the one build folder it points to (`<build>`, inside `<state>/service/builds/`), nothing else in `<state>/service/`, then run step 2's `install install` again.

To remove OpenWiz, on the user's yes: there is no remove command and no server to stop. Never remove `<root>` or `<state>` as a whole: the installer accepts folders that already hold other files, so either may hold the user's own.

1. `ls -A <root>`. A fresh install puts exactly `current`, `channel.json`, `install.lock`, `skills/` and, without a separate `--state-root`, `state/` (the `<state>`) there. Delete only `current`, `channel.json`, `install.lock` and `skills/`, and keep any of those names that was there before the install.
2. `ls -A <state>`. OpenWiz's builds are the folders in `<state>/service/builds/`, each named by a 40-character source commit and holding an `install-manifest.json` whose `"source"` is that same name. Delete those folders. `<state>/service/` is never deleted as a whole.
3. Only if the user wants their settings gone too: delete exactly these, when present: `<state>/setup/`, `<state>/cloudroom/`, and in `<state>/service/`: `config.json`, `app/` (the App's saved settings and key), `state.json`, `loops/` and `clone/`. Then `rmdir <state>/service/builds <state>/service <state>`, and last `rmdir <root>`. `rmdir` removes only an empty folder: leave any folder it refuses.
4. The skill copies stay: you never delete a skill folder yourself, and leftover copies are harmless. If the user wants them gone, list the folders with OpenWiz's 18 skill names (`ask-wiz`, `build-ticket`, `diagnose`, `grill`, `handoff`, `hill-climb`, `huntr`, `image`, `install`, `launch-fleet`, `research`, `review-ticket`, `setup`, `to-spec`, `to-tickets`, `triage`, `wayfind` and `where-are-we`) in each agent folder, show the list, and tell the user to look and remove only the ones they recognise as OpenWiz's, themselves, or keep them. A folder with one of these names may be the user's own skill.

   ```sh
   for d in "$HOME/.claude/skills" "${CODEX_HOME:-$HOME/.codex}/skills" "$HOME/.cursor/skills" "$HOME/.config/opencode/skills" "$HOME/.grok/skills"; do
     for s in ask-wiz build-ticket diagnose grill handoff hill-climb huntr image install launch-fleet research review-ticket setup to-spec to-tickets triage wayfind where-are-we; do
       [ -e "$d/$s" ] && echo "$d/$s"
     done
   done
   ```

Removal revokes nothing: show the user how to uninstall the App or remove repositories from it, delete any phone-access tunnel or rule, and delete the fleet loops in CloudRoom. Never remove or revoke anything without their yes.
