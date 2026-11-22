---
name: install
description: Install OpenWiz from its one line, "Install OpenWiz from github.com/openwizdev/OpenWiz", then optionally walk the resumable onboarding road to a first merged pull request. Checks the machine, installs the verified prebuilt release (no Rust or Node), checks setup's connections, asks where agents run, offers three ways to start, runs a short grill, and starts the fleet through launch-fleet once the plan passes its checks. Use to install, repair, update or remove OpenWiz, or to start or resume a first fleet. For a project's docs/agents/ settings alone, use setup.
version: 0.4.0
---

# Install OpenWiz

The user pasted one line into their agent:

> Install OpenWiz from github.com/openwizdev/OpenWiz

Take them from that line to setup, then down the onboarding road to their first merged pull request if they want one. Every step reads before it writes and reuses what an earlier one recorded, so a repeat or a fresh session resumes at the first unfinished step. Tools: OpenWiz's installer (`tools/install/install`, over its `contracts/install.v1.md`) and installed runtime (`contracts/setup.v1.md`), the agent CLI ([cli.v1](https://github.com/openwizdev/WizSkills/blob/main/contracts/cli.v1.md)), and for the road `grill`, `to-spec`, `to-tickets` and `launch-fleet`, and this skill's [teach.md](teach.md) and [ideas.md](ideas.md). This skill adds no installer, engine, approval or planner, and never runs a fleet tick itself.

**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.

## Guards

- **Install permission is not work approval.** Installing or finishing setup approves nothing. The first fleet needs the user's answer to where agents run, their yes in this chat to the grill's summary, and, right before it starts, their yes to starting it on that host, which can cost money. The plan approves itself by to-tickets' checks (J203): no spec or plan approval is asked. Never write, fake or infer a yes, or ask for blanket consent.
- **Show every effect, then wait for a yes to exactly it.** Where agents run, the fleet's start, the App or its skip, project settings, the host setting, the brain, phone access and a new repository each preview first; confirm with that preview's own `--yes` or `--yes --operation <id>`, where `<id>` is the preview's `operation_id` (for `cloudroom.py install`, the `operation_id` inside its `operation`). Creating a repository, any write, spend, secrets and publishing always ask; a teacher's line never stands in for that ask.
- **Never touch a login.** A missing sign-in gets its walk-through and a link; the user signs in themselves, in their own terminal or browser. Never run a sign-in for them (no `github_login.py sign-in --yes`, no `gh auth login`), and never read, pass or store a credential. Continue only on the installed setup's read-only check.
- **Credentials stay out of the conversation.** Never ask for a key or token in chat or put one in a prompt, argument, URL, log, issue or file. Keys go only through the tools' protected setup, into owner-only state on this computer or CloudRoom's secret store. Save the user's exact words only under [open-development](https://github.com/openwizdev/WizSkills/blob/main/contracts/open-development.v1.md).
- **Uncertain is never retried blindly.** Run the same command again: it reads its record first and never repeats an effect.
- **Read JSON and exit codes, never a screen.** Run installed programs by absolute path: there is no `openwiz` on `PATH`; it is `<root>/current/openwiz`. Python 3.9+ only: no Rust, Cargo, Node, npm or source build; if a step seems to need one, stop and say so.
- **CloudRoom is optional.** It is one place agents can run, beside this computer and boat.dev, never a requirement or a done condition: its install and sign-in run only when the user picks it. There is no setup page or local server: setup is the commands below.
- **Free now; other charges are separate.** OpenWiz is free now. Paid plans come later. CloudRoom and model charges are separate and not included. More Cloud Credits are CloudRoom's own plan, from `https://cloudroom.dev/pricing`. Referral verification is unavailable. No referral is applied. Never add a code or parameter to that link.

## Where your agents run

Ask this first, before step 1, in these exact words, with the three as equal choices and no recommendation:

> Where should your agents run? This computer (Claude Code or Codex you're signed in to), boat.dev, or CloudRoom.

Keep the answer for the whole install: it is the host the onboarding road's step 1 records. **This computer** and **boat.dev** skip every CloudRoom step: CloudRoom's install and sign-in, and its rows in step 3. **CloudRoom** runs them all, exactly as written. Carry that answer in step 4's restart message. In a resumed session, recover the choice as Resume says. Moving to CloudRoom later runs step 3's CloudRoom rows, then continues where the user was.

Keep `<root>` (default `$HOME/.local/lib/openwiz`), and the `build` and `state_root` paths `install` prints as `<build>` (also `build=<build>` in the shell) and `<state>`, all absolute and owner-only. Run runtime tools with `python3 -I -B` and `OPENWIZ_STATE_DIR=<state>`, and pass `--state-dir <state>`. After a restart, read them from the installed files, as Resume says.

## Resume

Two roads lead past step 4. **The same session (the default):** step 4 has you read the running agent's installed `install/SKILL.md` and carry on at step 5 in this chat, with the host, release, `<root>`, `<build>` and `<state>` it already holds; you don't start here. **A new session** (after step 4's fallback restart, or when the chat ended), whatever the user said ("continue", the continuation message, or the one line again), starts here: find the first unfinished step and resume there. Use only the installed files, never a temporary clone: a new session doesn't have it.

Read the host from the continuation message: `local` means this computer, `boat` means boat.dev, and `cloud` means CloudRoom. Read the release from it too: `release <tag>` names the release step 1 chose (its `<tag>`, and `<version>` without the `v`); use that release, never GitHub's Latest again, everywhere below. Use that choice for the setup checks below and carry it to step 6.1. If the message has no host, reuse the answer from this chat or `host.agents` if it is already recorded in the owner-only first-fleet state. Ask the host question only if you have none of those.

```sh
<root>/current/openwiz --build-identity
build=$(readlink <root>/current); state=${build%/service/builds/*}
OPENWIZ_STATE_DIR="$state" python3 -I -B "$build"/runtime/setup/setup.py check --state-dir "$state"
OPENWIZ_STATE_DIR="$state" python3 -I -B "$build"/runtime/setup/github_login.py status --state-dir "$state"
grep -m1 '^version:' ~/.claude/skills/install/SKILL.md "${CODEX_HOME:-$HOME/.codex}/skills/install/SKILL.md"
```

`<root>` is `$HOME/.local/lib/openwiz` unless the user chose another. Take the first that holds:

- No `<root>/current`, or `--build-identity` does not read the `<version>` of the release you install (step 1 reads it): resume at step 1.
- `status` does not read the GitHub account, or the user chose CloudRoom and `check` does not read `cloudroom_login_verified`: resume at step 3. `identity_unreadable` means GitHub gave no clear answer: wait a minute and run `status` again; it clears.
- The running agent's `install/SKILL.md` is missing, or does not read `version: <version of this skill>`, this file's own `version:` line at the top: resume at step 4. When that agent's folder holds OpenWiz's 18 skills, run only step 4's overwrite block, which needs no OpenWiz clone. When they are missing, copying them needs OpenWiz's installer again: step 1's `git clone` into a new temporary folder (it installs nothing), then all of step 4. Either way, step 4 ends by carrying on in this session; the restart is again only its fallback.
- Otherwise resume at step 5; for a first fleet already under way, at step 6 with `first_fleet.py next`. If it prints `Next: where.`, follow step 6.1 with the recovered choice.

## 1. Preflight

First read the release you install, GitHub's Latest:

```sh
curl -sS --proto '=https' -o /dev/null -w '%{redirect_url}\n' https://github.com/openwizdev/OpenWiz/releases/latest
```

It prints `https://github.com/openwizdev/OpenWiz/releases/tag/<tag>`. Use that `<tag>` (such as `v0.1.1`) below, and `<version>` for it without the `v` (`0.1.1`). To install 0.1.0, stop this skill and follow the [0.1.0 install instructions](https://github.com/openwizdev/WizSkills/blob/maint/0.2/skills/install/SKILL.md) (WizSkills v0.2.x) instead, with its hand-started fleets at the end. 0.1.0 is no longer Latest, so in its step 2 always take its pinned `v0.1.0` fetch, never its `download`. With no `/tag/` in it, GitHub has no Latest release yet: use the tag the user names, never a guess.

```sh
openwiz=<private temporary folder>/openwiz
git clone --depth 1 --branch <tag> https://github.com/openwizdev/OpenWiz "$openwiz"
python3 -I "$openwiz"/tools/install/install preflight
```

`git clone` may warn that `refs/tags/<tag>` is not a commit (it is an annotated tag) and print detached-HEAD advice: both are harmless. Preflight reads Python, the target, disk space and whether `room-cli`, `gh` and `git` are on `PATH`; it runs none of them. It prints `target` for the next step. Today supported means a Mac with Apple silicon (`aarch64-apple-darwin`) or Linux on x86_64 (`x86_64-unknown-linux-gnu`). An Intel Mac (`x86_64-apple-darwin`) has a build, but CloudRoom offers no Intel Mac build today: if the user chose CloudRoom, say so plainly, offer this computer or boat.dev instead, and stop before installing if they keep CloudRoom. Exit 5 names each missing item and its `next` step: tell the user plainly what they do themselves (`gh`: install it and run `gh auth login` in their own terminal). `room-cli` reading `missing` never stops preflight; it matters only if the user chose CloudRoom, and step 3 installs CloudRoom then. Linux on ARM is refused. On Linux the build needs glibc 2.34 or later (`ldd --version`). Read its `checks` even on exit 0: `gh` reading `missing` does not stop preflight, but setup needs it. Then the user installs GitHub CLI first, from https://cli.github.com, and `gh --version` shows it is there; then continue.

Done when preflight passes, or the user has each next step.

## 2. Verified install

Download exactly the release step 1 chose, even if GitHub's Latest has moved since:

```sh
python3 -I "$openwiz"/tools/install/install download --target <target> --dir <private download folder> --version <tag>
```

If that installer answers `usage` for `--version` (an older one), and only then, fetch the same three files from the pinned tag into a new owner-only folder:

```sh
umask 077; mkdir <private download folder>
for f in openwiz-<target>.sha256 openwiz-<target>.manifest.json openwiz-<version>-<target>.tar.gz; do
  curl -fsSL --proto '=https' -o <private download folder>/"$f" https://github.com/openwizdev/OpenWiz/releases/download/<tag>/"$f"
done
```

Before activating anything, check the downloaded release is the chosen one:

```sh
grep -o '"version": *"[^"]*"' <private download folder>/openwiz-<target>.manifest.json
```

It must print `"version"` with `<version>`. Anything else: stop, install nothing, and say so. Then activate it:

```sh
python3 -I "$openwiz"/tools/install/install install --assets <private download folder> --target <target> --root <root>
```

`install` checks the manifest against its checksum and every file against the manifest, as `download` would. Any other refusal leaves the previous build selected: report it, never work around it. A checksum proves the files are the release's, not who published them.

Then prove the build:

```sh
<root>/current/openwiz --build-identity
```

It prints `"version":"<version>"` and the release's `source` commit. On Linux, a `weak version 'GLIBC_2.39' not found` line on stderr is harmless. OpenWiz's skills go into the user's agents at step 4, after setup.

Done when `install` printed `"activated": true` with the version, target, `build` and `state_root`, and `--build-identity` read `<version>`.

## 3. Setup and connections

```sh
python3 -I -B "$build"/runtime/setup/setup.py check --state-dir <state>
```

It reads each connection and records only its own results in `<state>`. It prints one bare code per component and no next step, so read each code below. Run `check` again after each change.

**CloudRoom** (`cloudroom`), only if the user chose CloudRoom. Otherwise skip this table and ignore every `cloudroom_*` code `check` prints (the host-aware report reads `cloudroom_not_needed`): it never blocks this install. With CloudRoom, use `python3 -I -B "$build"/runtime/cloudroom/cloudroom.py status | install | sign-in --state-dir <state>`:

| Code | Next |
| --- | --- |
| `cloudroom_login_verified` | Done: signed in now. |
| `cloudroom_not_installed` | `cloudroom.py install --state-dir <state>` previews CloudRoom's checksum-checked installer; on the yes, `cloudroom.py install --yes --operation <id> --state-dir <state>`. Then sign in. |
| `cloudroom_installed`, `cloudroom_reused`, `cloudroom_login_missing`, `cloudroom_login_unknown` | The person signs in themselves: show them `cloudroom.py sign-in --state-dir <state>` to run in their own terminal (it opens CloudRoom's own sign-in once, or the app the first time), and wait until they say done. Then `status`. On Linux, sign-in needs a desktop session and FUSE (the AppImage needs `fusermount`, from `fuse3` or `libfuse2`): a headless VPS cannot sign in. If nothing opens within a minute, the user opens `~/Applications/Cloudroom.AppImage` themselves. |
| `cloudroom_unsupported` | CloudRoom offers no build for this computer (an Intel Mac, or Linux on ARM): say so plainly, and offer this computer or boat.dev instead. |
| `cloudroom_source_unchecked` | `cloudroom.py install` could not read or check CloudRoom's published installer and its checksum (a network failure, or CloudRoom changed its download guide or release): nothing was proposed or downloaded. Run `install` again shortly. If it stays, `cloudroom.py install --yes --state-dir <state>` opens CloudRoom's download page once instead; the user installs CloudRoom from there, opens it once and signs in. Then `status`. |
| `cloudroom_installing` | An install is running: `status` again shortly. |
| `cloudroom_install_uncertain` | A plain `install` only shows the pending operation again. Read its `operation_id` from `cloudroom.py install --state-dir <state>` (inside `operation`), then reconcile that same operation: `cloudroom.py install --yes --operation <operation_id> --state-dir <state>`. Never preview a new install over it. |
| `cloudroom_install_failed` | Preview `install` again and ask again. |
| `cloudroom_install_declined` | The user said no: stop, or preview again only if they ask. |
| `cloudroom_checksum_mismatch` | Nothing was installed: report it and stop. |
| `cloudroom_destination_blocked` | Another file is at `~/Applications/Cloudroom.AppImage`: the user moves it, never you. |
| `cloudroom_unreadable` | `check` again; if it stays, `status`. |

**GitHub:** the read-only `python3 -I -B "$build"/runtime/setup/github_login.py status --state-dir <state>` reads the account. Signed out, `github_login.py sign-in --state-dir <state>` without `--yes` only previews (`login_needed`): GitHub's own browser page and a one-time code, with no token pasted. The person signs in themselves: they run it with `--yes` in their own terminal; then run `status` again. `identity_unreadable` (from `status`, `sign-in` or `check`) means GitHub gave no clear answer: wait a minute and run it again; it clears. If it stays, `gh auth status` shows whether the user is signed in. `login_gh_missing` means GitHub CLI is not installed: the user installs it from https://cli.github.com, then `gh --version` shows it is there; run the sign-in preview again.

**The rest** (`harness_unselected`, `identity_unselected`, `project_unprepared`, `app_missing`) is expected now: each waits for the repository the user picks on the onboarding road, and Connect sets it. Phone access is optional: `python3 -I -B "$build"/runtime/access/access.py configure --plan <private file> --state-dir <state>` previews it; `access.py --help` gives the plan's shape.

Done when GitHub's `status` reads the account and, only if the user chose CloudRoom, CloudRoom reads `cloudroom_login_verified`; or the user chose to stop with the remaining next steps.


## 4. Skills into your agents, then carry on

Only now, with setup checked and the logins done, copy OpenWiz's skills into the user's agents:

```sh
python3 -I "$openwiz"/tools/install/install skills --root <root>
```

It copies the 18 skills into `<root>/skills` and into each agent folder present here: `~/.claude/skills` (Claude Code), `${CODEX_HOME:-$HOME/.codex}/skills` (Codex: `$CODEX_HOME/skills` when `CODEX_HOME` is set, otherwise `~/.codex/skills`), `~/.cursor/skills`, `~/.config/opencode/skills` and `~/.grok/skills`. It prints `"outcome": "installed"` even when it copied nothing, so check two things: its `harnesses` entry for the agent you are running in reads `installed`, and that agent's folder, the entry's `path` (`ls ~/.claude/skills`, or for Codex `ls "${CODEX_HOME:-$HOME/.codex}/skills"`), now holds all 18 by name: `ask-wiz`, `build-ticket`, `diagnose`, `grill`, `handoff`, `hill-climb`, `huntr`, `image`, `install`, `launch-fleet`, `research`, `review-ticket`, `setup`, `to-spec`, `to-tickets`, `triage`, `wayfind` and `where-are-we`. If the entry reads `absent`, that agent's folder (`~/.claude`, or for Codex `$CODEX_HOME` when set, otherwise `~/.codex`) is missing on this computer: tell the user which folder, that their agent has no OpenWiz skills, and its `next` step; never create the folder yourself. A skill of the user's own with the same name refuses the whole step: report it.

Then make every installed copy of this skill this one, the whole folder. The copy `install skills` just wrote comes from the release's package and can be older: `grep -m1 '^version:' "$build"/runtime/skills/install/SKILL.md` prints its real version from the verified build, an older copy's `SKILL.md` and scripts can still name a setup page and a server OpenWiz removed, and a new session loads it whatever the user says. Take this skill's own folder: the one you read it from when it is on this computer (a WizSkills clone or plugin: set `src` to it and skip the clone), otherwise a fresh clone of WizSkills (it installs nothing). Then overwrite only the agent folders the installer reported as taking OpenWiz's copy, and check every file by content. `<installed agent folders>` is the quoted `path` of each `harnesses` entry from `install skills` that reads `installed`, or `partial` with no `skipped` entry for `install`. Without this session's `install skills` output (a resumed session), run `install skills` again from a fresh clone of the chosen `<tag>` and use its rows; if you can't, copy nothing and tell the user. Never guess a folder. A folder is copied over only when no part of its path is a link (the installer refuses those too) and while its `install/.openwiz-skill` is the installer's own receipt, never a user's skill. `<version of this skill>` is the `version:` at the top of this file, such as `0.4.0`:

```sh
wizskills=<private temporary folder>/WizSkills
git clone --depth 1 --branch main https://github.com/openwizdev/WizSkills "$wizskills"
src="$wizskills"/skills/install
want='version: <version of this skill>'
fixed() { grep -qxF "$want" "$1/SKILL.md" && ! grep -q -e 'install ope[n] ' -e 'from the setup pag[e]' -e 'Restart the OpenWiz serve[r]' "$1/SKILL.md" "$1"/scripts/*.py; }
if fixed "$src"; then echo "source ok"; else echo "NOT THIS SKILL: $src"; fi
ours() { [ "$(cd "$1" 2>/dev/null && pwd -P)" = "$1" ] && [ -d "$1/install" ] && [ ! -L "$1/install" ] && [ -f "$1/install/.openwiz-skill" ] && [ ! -L "$1/install/.openwiz-skill" ] && python3 -I -c 'import re, sys; sys.exit(not re.fullmatch(rb"openwiz\.skill-copy\.v1\n[0-9a-f]{40}\n", open(sys.argv[1], "rb").read(65)))' "$1/install/.openwiz-skill"; }
fixed "$src" && for d in <installed agent folders>; do
  [ -e "$d/install" ] || continue
  ours "$d" || { echo "not OpenWiz's, left alone: $d/install"; continue; }
  cp -R "$src"/. "$d/install/"
  same=yes; for f in $(cd "$src" && find . -type f); do cmp -s "$src/$f" "$d/install/$f" || same=no; done
  if [ "$same" = yes ] && fixed "$d/install"; then echo "ok: $d/install"; else echo "STILL OLD: $d/install"; fi
done
```

If it prints `NOT THIS SKILL` (the clone failed, or the branch still serves an older copy), nothing was copied: stop here, say so, and try again shortly. A `not OpenWiz's, left alone` line is the user's own skill: never copy over it, and say so if it is the running agent's. A `STILL OLD` line means that folder's copy did not take (it may not be writable): report it and fix it before you carry on; never carry on with, or restart onto, an old copy. A later `install skills` run, such as a repair, writes the old copy again: repeat this block after it.

**Carry on in this session; no restart.** An agent lists new skills only when it starts, so don't wait for it to find them: read the running agent's installed copy of this skill in full, by path, and follow it from step 5. That exact file is the `path` of the running agent's `harnesses` entry plus `/install/SKILL.md`, the folder the block just printed `ok:` for:

- Claude Code: `~/.claude/skills/install/SKILL.md`
- Codex: `${CODEX_HOME:-$HOME/.codex}/skills/install/SKILL.md`

Read it with your file tool, or `cat` it, and check its `version:` line reads `version: <version of this skill>`. From then on `<this skill's folder>` is that file's folder (`~/.claude/skills/install`, or `${CODEX_HOME:-$HOME/.codex}/skills/install`) for `teach.md`, `ideas.md` and `scripts/`, never a temporary clone. Keep what this chat already holds (the host answer, the release `<tag>`, `<root>`, `<build>` and `<state>`) and ask nothing again.

Give the user their host's continuation message all the same, for a later session if this chat ends early:

- This computer: `continue the OpenWiz install with host local and release <tag>`
- boat.dev: `continue the OpenWiz install with host boat and release <tag>`
- CloudRoom: `continue the OpenWiz install with host cloud and release <tag>`

Keep the full message. "continue the OpenWiz install" names the skill, the host carries the user's answer into Resume, and `release <tag>` (step 1's, filled in) keeps the chosen release after GitHub's Latest moves.

**The restart is the fallback,** only when this agent cannot read that file and follow it in this session: its tools can't open a file outside the project, or it can follow only the skills it loaded at start. Then the user restarts the agent and pastes that message into the new session, which starts at Resume. Any installed copy whose `version:` line is older than this file's is older than this one; if you are told to install again, follow this skill (https://github.com/openwizdev/WizSkills/blob/main/skills/install/SKILL.md) and resume at the first unfinished step, as Resume says.

Done when the running agent's folder holds the 18 skills by name and every `ok:` line printed with no `STILL OLD`, or the user knows which folder is missing; the user has the continuation message with their chosen host; and you have read that agent's installed `install/SKILL.md` and carry on at step 5 in this session, or, only as the fallback, the user is restarting their agent.

## 5. Teach

From here the agent is a teacher. At each moment named in **bold** below, say that moment's line from [teach.md](teach.md), filling each `<...>` from what just happened and keeping the rest of its words. Say **Up front**'s three lines once, then **Install done**.

Done when the user has heard both.

## 6. The onboarding road

Continue only if the user wants their first build; otherwise finish with the install and any outstanding setup steps. Pass one owner-only `--state <file>` outside the project to every `first_fleet.py` command (`python3 <this skill's folder>/scripts/first_fleet.py`), from the project's clone once there is one. To resume, run `first_fleet.py next --state <file> --setup-state <state>`: it reads only that file and the repository setup prepared, and prints the first unfinished step and its command. Exits: 0 done, 1 read failure, 2 usage, 5 refused, 6 uncertain, 7 busy, 10 state unavailable, 12 preview awaiting `--yes`.

### 1. Where agents run

Run `first_fleet.py where --build "$build"`. It lists every host this OpenWiz can run agents on: Cloudroom (`cloud`), and each driver the verified build's `runtime/adapters` carries that answers `version`, such as this machine (`local`) and boat.dev (`boat`). A driver whose `version` fails is not offered: say its `Not offered:` line as printed. Take the answer to the host question from this chat, or use the host from Resume in a new session. When that host is listed, run `where --agents <its name> --build "$build"` without asking again. When it is not, say its `Not offered:` line and ask the host question again, offering only the listed hosts, as equal choices. It checks what that host needs: a GitHub sign-in everywhere; on this machine Claude Code or Codex on `PATH`; for Cloudroom `room-cli`; for boat.dev the `boat` CLI. For anything missing it prints **Where agents run**'s walk-through line with a link; say it as printed. The user signs in themselves; run it again when they say done.

With `--agents`, exit 12 previews where the agents run and what they cost. Explain those effects and costs, including Cloud Credits for CloudRoom. For a driver host other than this machine it also prints where the login lives (boat.dev: `Login: held by boat.dev`, with its dashboard steps; any other: the driver's Login line) and one question asking whether the user has signed in there; ask it as printed. The user signs in themselves. On the user’s yes to the previewed effects and cost, run it again with `--yes`: it records the pick, and for a driver host the build's `runtime/adapters`. A driver host's `Host: <name>` line, the one launch-fleet reads, is written at **Host setting**; Cloudroom needs none. With nothing usable listed, offer Cloudroom or stopping.

Done when `where` recorded the answer.

### 2. Choose a start

Offer three ways to start: a small change in a repository they have, a fresh project from their idea, or something they've always wanted to build. Anyone without an idea gets two or three ideas from that choice's group in [ideas.md](ideas.md); their own idea always wins. Then its one repository:

- **A repository they have:** confirm it, and that the fleet opens branches and pull requests there, then run `first_fleet.py select --repo <owner>/<name>`.
- **A new repository:** GitHub sign-in first, which the person does themselves: show them `python3 -I -B "$build"/runtime/setup/github_login.py sign-in --state-dir <state> --yes` to run in their own terminal (it opens GitHub's browser page), and wait until they say done. Then run the read-only check, `python3 -I -B "$build"/runtime/setup/github_login.py status --state-dir <state>`, and continue only when it reads their account. Then `first_fleet.py create-repo --repo <owner>/<name>` previews it and its one README commit; on the yes, add `--yes`. Exit 6: run it again. With CloudRoom, the user makes or picks its CloudRoom project.

Done when the idea and one repository are chosen and read back. There is no second repository.

### 3. Connect

For that repository, each tool previews and applies only on the yes (`--yes`, or `--yes --operation <id>` from its preview):

1. **Sign-in:** run the read-only `github_login.py status --repository <owner>/<name> --state-dir <state>`. Only its account and push-access read-back count. Signed out, or without push access, the person fixes it themselves, as in step 2 (`github_login.py sign-in --repository <owner>/<name> --state-dir <state> --yes` in their own terminal); then run `status` again.
2. **Prepare:** `setup.py prepare --state-dir <state> --repository <owner>/<name> --project <project id> --operator <login> --service-issue <N> --answer-thread <thread id> --harness <harness> --model <model> --effort <effort>`, one question each, with a recommendation. For this computer add `--host local`, for boat.dev `--host boat`, and for another driver `--host <its name>`; the default is `cloud`. With any host but `cloud`, give no `--project` or `--answer-thread`: `prepare` refuses them ([setup v1](https://github.com/openwizdev/OpenWiz/blob/main/contracts/setup.v1.md), the host-aware report). With CloudRoom, every flag above is needed:
   - `--project`, only with CloudRoom: the CloudRoom project the fleet runs in, by id (`<root>/current/openwiz ls --json` groups threads by project).
   - `--operator`: the name a loop's on or off switch records as who did it; recommend the user's GitHub login.
   - `--service-issue`: an open issue in that repository for OpenWiz's service records (not a pull request). With none, offer to open one, titled "OpenWiz service records", on the yes.
   - `--answer-thread`, only with CloudRoom: the user's CloudRoom thread in that project that gets the fleet's answers, from the same `ls`; another project's thread reads `project_answer_refused`.
   - `--harness`, `--model`, `--effort`: what the user picks from `<root>/current/openwiz models --json --host cloud` with CloudRoom. With a driver host, use `<root>/current/openwiz models --json --host <its name>` and offer its local options; on this machine, only the harnesses `where` found.

   Without `--yes` it prints the effects and an operation id; on the yes, run it again with `--yes --operation <id>`.
3. **The App, or an explicit skip:** recommend the App, set up with the installed `"$build"/runtime/github-app/setup.py` as the `setup` skill's "The App" says. Only the user's answer selects `github_login.py skip-app`; an App failure never becomes a skip.
4. **The brain:** `<root>/current/openwiz init --repository <owner>/<name> --state-dir <state> --json`, then `--yes --operation <id>`. Say in one line where it went; the user merges its pull request. For a public repository's private companion, run `first_fleet.py decisions --setup-state <state>`, then `--yes`.
5. **Carry it:** `setup.py check --state-dir <state>`, then `first_fleet.py continue --setup-state <state> --explained`. It refuses, naming each component that is missing, refused, unknown or stale, and withdraws what it carried before; follow that `next` step and run both again.

Done when `continue` prints the carried setup and the acting identity.

### 4. Grill

Say **The grill**'s first line, then run `grill` in one short round: at most three questions, each with a recommendation, steered to about three small tickets, each one a single builder finishes fast, with no blockers between them and no shared owned paths, so all three build in parallel. Anything bigger waits for the closing offer's keep building, after the first merge. When its summary is ready, show it and say **The grill**'s second line. Only the user's yes here confirms it; anything else is a change to make. Save the yes as `grill` says, then run `first_fleet.py grill --confirmed <its private comment URL>`.

Done when `grill` recorded the confirmation.

### 5. Agents

Harness, model and effort were answered at Connect. Save `<root>/current/openwiz models --json --host cloud` privately with CloudRoom. With a driver host, save `<root>/current/openwiz models --json --host <its name>` and use its local options. Then run `first_fleet.py choose --options <saved file> --from-setup` (without a carried setup, ask the three and pass `--harness --model --effort`). `choose` writes the choice into `docs/agents/fleet.md`'s Models table, keeping the Reviewer in the other family. Commit that file and merge it, then run the same `choose` again: it reads the table back.

Done when the choice is recorded and the default branch's Models table names it.

### 6. Host setting

On this machine, first ask the owner to pick the harness permission mode, once. Run `first_fleet.py mode`: it lists the modes of every harness the fleet starts here, each with what it lets an agent do. With both Claude Code and Codex installed, builders use one and each review uses the other, so it lists both, and the owner picks one mode for each. Explain each one plainly, as printed, and recommend none: never pick, default or widen a mode for the owner, and touch no login. On their answer, run `first_fleet.py mode --mode <their pick>`, or with both harnesses `first_fleet.py mode --claude-mode <their pick> --codex-mode <their pick>`. From those picks it saves this machine's host-side approval for the repository and each harness, outside the repository, through the local driver's setup step; it never changes or widens an approval already saved. The host setting below adds the matching `fleet.md` rows. The local driver passes the mode to the harness unchanged and starts nothing unless the row and the approval match.

Then run `first_fleet.py setting`. For a driver host other than this machine (boat.dev, or another the user picked) it previews one pull request that adds only `docs/agents/host.md` with `Host: <its name>`, the line launch-fleet reads, and no mode row; on the yes, run it with `--yes` and ask the user to merge it, as below. For this machine it previews one pull request that adds `docs/agents/host.md` with `Host: local` (the host launch-fleet reads) and the mode rows to the `docs/agents/fleet.md` setup wrote (the modes the local driver reads), changing no other line: one row, `| Harness permission mode | `<their pick>` |`, or with both harnesses one row each, `| Harness permission mode (claude) | `<pick>` |` and `| Harness permission mode (codex) | `<pick>` |`. On the yes, run it with `--yes` and ask the user to merge it. It never adds a second row or replaces a mode the owner already saved: it names that row and asks. It never writes over a branch `openwiz/host-setting` that holds anything else, and it says the pull request is ready only once both files read back from it exactly; a failed or uncertain write is said, never retried blindly: run it again to read the branch first. For Cloudroom no file is needed: it says so and exits 0. It never overwrites a host the project already names. The launch waits until the pull request is merged, for every driver host.

Done when both settings match the answers, or their pull request is open.

### 7. Plan

The plan checks itself. Run `to-spec` with the confirmed grill and say it is the install's first fleet: it writes the spec and runs `to-tickets`, whose checks record the machine plan approval, then goes straight to the launch with no video (to-spec skips its video step for this fleet only; a later spec, from keep building or anywhere else, gets its video as usual). A reset or change of this spec or plan, before or after the launch, gets a new machine approval and still no video. Say **The spec and its video** with the spec link. Without Node on `PATH` nothing changes: you skip the video step all the same, and the fleet still starts. Ask nothing here: no spec or plan approval. For now the owner steers through the orchestrator: what they want changed goes to this chat, never a comment on the spec, which steers nothing until OpenWiz #1402. launch-fleet's one-time notice saying so is normal, not a hold. When a check refuses, re-cut the plan; never ask the user to approve it instead. Then run `first_fleet.py spec --spec <N> --repo <owner>/<name>`.

Done when the machine plan approval is on the spec and `spec` saved it.

### 8. Launch

Preview with `first_fleet.py launch --spec <N>`. It reads the spec's machine plan approval for this grill, the host the user chose (a driver host, this machine or boat.dev or another, only once its host setting is merged) and launch-fleet's own frontier, then prints the start's effects and one question that names the host and says it can cost money. Show the effects and ask that question as printed. This is the one yes before the fleet starts; never skip it, even though the cost was shown at **Where agents run**. On the yes, run it with `--yes --confirm <the digest it printed>`. It refuses if anything changed since the preview: preview again and ask again. It starts nothing itself: it saves the yes and names launch-fleet's own start path. With CloudRoom, follow launch-fleet's Launch section ([references/launch.md](../launch-fleet/references/launch.md)): the project's two loops, the GitHub messages question (a gate, in its own words), then "Starting one": the spec's loop, its private loop-map entry, read back, and the `launch-fleet: fleet active, loop fleet-<S>` record, read back. With a driver host, follow the local heartbeat handoff as `launch` printed it, including the heartbeat preview and approval. Then run `first_fleet.py launch --spec <N>` again. For CloudRoom it says **The fleet starting** when the activation record reads back. For a driver host it confirms the active heartbeat. Never start the fleet a second way.

Done when `launch` reads back the CloudRoom activation record or the active heartbeat for the chosen driver host.

### 9. Watch

Run `first_fleet.py progress --spec <N> --openwiz <root>/current/openwiz` when the user asks or a moment may have happened, and say each moment's line once: **A pull request opened**, then **Reviewed**. A count is never a merge. When a pull request merges, run `first_fleet.py first-merge --pr <number>`: it reads the merge back from GitHub and prints **Merged** and **The closing offer**; say both. On the answer: stay as the project's orchestrator (launch-fleet), start a new project (this road again, with a new state file), or keep building (the grill again, for the next idea).

Done when the user has heard the closing offer.

## Doctor

When setup or a fleet seems stuck, or the user asks whether setup is right, run the doctor from the project's clone:

```sh
python3 -I <this skill's folder>/scripts/doctor.py --repo <owner>/<name> --state-dir <state> --build <build> --openwiz "$build"/runtime [--driver <the driver this machine runs>]
```

In order, it checks the labels, the App, that the acting login is a record author, the harness, the driver's `version` and the skills, through the checks that already exist. It only reads. Show each problem line as it is; its `Fix:` is the command that fixes it. A sign-in fix is the user's to run: show it, never run it. Exit 0 prints one all-clear line; 5 prints the problems.

Done when it prints all clear, or the user has each fix.

## Recovery and removal

If something seems wrong, verify the build with a fresh clone (it installs nothing): `openwiz=<new temporary folder>/openwiz`, step 1's `git clone`, then `python3 -I "$openwiz"/tools/install/install status --root <root>`. It verifies the selected build and changes nothing. A changed file reads `installed asset mismatch`, and `install` refuses the same way. To repair it and keep the settings, delete only the `<root>/current` link and the one build folder it points to (`<build>`, inside `<state>/service/builds/`), nothing else in `<state>/service/`, then run step 2's `install install` again.

To remove OpenWiz, on the user's yes, in this order. Never remove `<root>` or `<state>` as a whole: the installer accepts folders that already hold other files, so either may hold the user's own.

1. **Heartbeat first.** A local fleet's heartbeat is a per-user scheduled job outside `<root>`, and it keeps waking after the build is gone. Other installs' jobs share its folder, so list them by owner (it only reads):

   ```sh
   for c in ~/.local/state/openwiz-heartbeat/*/config.json; do
     [ -f "$c" ] && python3 -I -c 'import json, os, sys; c = json.load(open(sys.argv[1])); a = c.get("environment", {}).get("OPENWIZ_ADAPTERS", ""); s = os.path.realpath(sys.argv[2]); print("this install:" if a and os.path.realpath(a).startswith(s + os.sep) else "ask first:", *c["argv"][-2:], "(adapters: %s)" % (a or "none"))' "$c" "<state>"
   done
   ```

   A `this install:` job runs on this install's build (its `OPENWIZ_ADAPTERS` is inside `<state>`); an `ask first:` job may be another install's. Remove only the `this install:` jobs; show every `ask first:` line and touch an `ask first:` job only after the user names it as part of this uninstall. Set `launch_fleet` to the installed launch-fleet skill's folder and, for each job you remove, run `python3 -I "$launch_fleet"/scripts/heartbeat.py remove "<owner>/<repo>" "<S>"`: it takes down the schedule, stops the saved orchestrator and removes its state. `heartbeat: not installed` means there was none.
2. **Then the installer's remove,** from step 1's clone of the chosen release (`git clone --depth 1 --branch <tag>` into a new temporary folder; it installs nothing). Preview with `python3 -I "$openwiz"/tools/install/install remove --root <root>`, adding `--state-root <state>` when the install chose a separate one. Show the user its `delete` list: it deletes exactly those and keeps everything else, and refuses while an install or update runs. On their yes, run the same command with `--yes`.
3. **The agents' copies:** `remove` never deletes them. Its `skills` rows give each agent folder's `path` and the OpenWiz skill `names` in it. Show those names only; the user deletes those folders themselves, or keeps them.

Only for 0.1.0's installer, which has no `remove` (its `remove` answers `usage`), remove it by hand instead of steps 2 and 3:

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

Removal revokes nothing: show the user how to uninstall the App or remove repositories from it, delete any phone-access tunnel or rule, and, with CloudRoom, delete the fleet loops there. Never remove or revoke anything without their yes.
