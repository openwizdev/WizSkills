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
- **CloudRoom is optional (from OpenWiz 0.1.1).** It is one place agents can run, beside this computer and boat.dev, never a requirement or a done condition: its install and sign-in run only when the user picks it. There is no setup page or local server: setup is the commands below.
- **Free now; other charges are separate.** OpenWiz is free now. Paid plans come later. CloudRoom and model charges are separate and not included. More Cloud Credits are CloudRoom's own plan, from `https://cloudroom.dev/pricing`. Referral verification is unavailable. No referral is applied. Never add a code or parameter to that link.

## Where your agents run

For a new install, start step 1 by reading the release you install, GitHub's Latest:

```sh
curl -sS --proto '=https' -o /dev/null -w '%{redirect_url}\n' https://github.com/openwizdev/OpenWiz/releases/latest
```

It prints `https://github.com/openwizdev/OpenWiz/releases/tag/<tag>`. Use that `<tag>` (such as `v0.1.1`) below, and `<version>` for it without the `v` (`0.1.1`). With no `/tag/` in it, GitHub has no Latest release yet: use the tag the user names, never a guess.

Use the chosen release's `<version>` for this check, on both a new install and a resume:

```sh
case '<version>' in
  0.1.0) printf '%s\n' cloudroom-only ;;
  *) printf '%s\n' choose-host ;;
esac
```

For `cloudroom-only`, offer only CloudRoom. Say:

> This computer and boat.dev need OpenWiz 0.1.1 or later, which isn't released yet. Today, OpenWiz 0.1.0 runs agents on CloudRoom only.

Offer to follow the [0.1.0 install instructions](https://github.com/openwizdev/WizSkills/blob/maint/0.2/skills/install/SKILL.md) (WizSkills v0.2.x), with its hand-started fleets at the end, or wait for 0.1.1. In those instructions, when 0.1.0 is the release you install, always take the pinned `v0.1.0` fetch in step 2, never its `download`. Stop this skill here.

For `choose-host` (OpenWiz 0.1.1 or later), ask in these exact words, with the three as equal choices and no recommendation:

> Where should your agents run? This computer (Claude Code or Codex you're signed in to), boat.dev, or CloudRoom.

Keep the answer for the whole install: it is the host the onboarding road's step 1 records. **This computer** and **boat.dev** skip every CloudRoom step: CloudRoom's install and sign-in, and its rows in step 3. **CloudRoom** runs them all, exactly as written. Carry that answer in step 4's restart message. In a resumed session, recover the choice as Resume says. Moving to CloudRoom later runs step 3's CloudRoom rows, then continues where the user was.

Keep `<root>` (default `$HOME/.local/lib/openwiz`), and the `build` and `state_root` paths `install` prints as `<build>` (also `build=<build>` in the shell) and `<state>`, all absolute and owner-only. Run runtime tools with `python3 -I -B` and `OPENWIZ_STATE_DIR=<state>`, and pass `--state-dir <state>`. After a restart, read them from the installed files, as Resume says.

## Resume

Two roads lead past step 4. **The same session (the default):** step 4 has you read the running agent's installed `install/SKILL.md` and carry on at step 5 in this chat, with the host, release, `<root>`, `<build>` and `<state>` it already holds; you don't start here. **A new session** (after step 4's fallback restart, or when the chat ended), whatever the user said ("continue", the continuation message, or the one line again), starts here: find the first unfinished step and resume there. Use only the installed files, never a temporary clone: a new session doesn't have it.

Read the release from the continuation message: `release <tag>` names the release step 1 chose (its `<tag>`, and `<version>` without the `v`); use that release, never GitHub's Latest again, everywhere below.

If `<root>/current` exists, read the installed build before choosing a host:

```sh
<root>/current/openwiz --build-identity
```

If the continuation message has no `release <tag>`, read Latest in **Where your agents run** to get the release you will install. Run the release check there with that release's `<version>`. On `cloudroom-only`, follow that path and stop. On `choose-host`, recover or ask for the host below.

Read the host from the continuation message: `local` means this computer, `boat` means boat.dev, and `cloud` means CloudRoom. Use that choice for the setup checks below and carry it to step 6.1. If the message has no host, reuse the answer from this chat or `host.agents` if it is already recorded in the owner-only first-fleet state. Ask the host question only if you have none of those.

No `<root>/current`, or `--build-identity` does not read the `<version>` of the release you install: resume at step 1. For a matching installed build, run the setup checks:

```sh
build=$(readlink <root>/current); state=${build%/service/builds/*}
OPENWIZ_STATE_DIR="$state" python3 -I -B "$build"/runtime/setup/setup.py check --state-dir "$state"
OPENWIZ_STATE_DIR="$state" python3 -I -B "$build"/runtime/setup/github_login.py status --state-dir "$state"
grep -m1 '^version:' ~/.claude/skills/install/SKILL.md "${CODEX_HOME:-$HOME/.codex}/skills/install/SKILL.md"
```

`<root>` is `$HOME/.local/lib/openwiz` unless the user chose another. Take the first that holds:

- `status` does not read the GitHub account, or the user chose CloudRoom and `check` does not read `cloudroom_login_verified`: resume at step 3. `identity_unreadable` means GitHub gave no clear answer: wait a minute and run `status` again; it clears.
- The running agent's `install/SKILL.md` is missing, or does not read `version: <version of this skill>`, this file's own `version:` line at the top: resume at step 4. When that agent's folder holds every skill the verified build ships (each folder in `"$build"/runtime/skills`), each with an `.openwiz-skill` whose second line is the `source` that `--build-identity` prints (an older copy names another), run only step 4's overwrite block, which needs no OpenWiz clone. When they are missing, copying them needs OpenWiz's installer again: step 1's `git clone` into a new temporary folder (it installs nothing), then all of step 4. Either way, step 4 ends by carrying on in this session; the restart is again only its fallback.
- Otherwise resume at step 5; for a first fleet already under way, at step 6 with `first_fleet.py next`. If it prints `Next: where.`, follow step 6.1 with the recovered choice.

## 1. Preflight

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
python3 -I "$openwiz"/tools/install/install skills --root <root> > <private file>; echo "exit: $?"
python3 -I -c 'import json, os, sys
r = json.load(open(sys.argv[1]))
for h in r.get("harnesses", []):
    print("%s: %s %s" % (h["state"], h["id"], h["path"]) + ("" if h["state"] == "installed" else " (next: %s)" % h.get("next")))
    gone = [s["skill"] for s in h.get("skipped", [])]
    for s in h.get("skipped", []):
        print("skipped: %s in %s (next: %s)" % (s["skill"], h["id"], s["next"]))
    for n in r.get("skills", []) if h["state"] in ("installed", "partial") else []:
        d = os.path.join(h["path"], n); m = os.path.join(d, ".openwiz-skill")
        if n in gone:
            continue
        if not os.path.isdir(d):
            print("missing: %s in %s" % (n, h["id"]))
        elif not os.path.isfile(m) or open(m, "rb").read(65) != ("openwiz.skill-copy.v1\n%s\n" % r.get("source")).encode():
            print("missing: %s in %s (not this release%ss copy)" % (n, h["id"], chr(39)))
for s in r.get("canonical_skipped", []):
    print("skipped: %s in %s (next: %s)" % (s["skill"], r.get("canonical"), s["next"]))
print("outcome: %s, %d skills" % (r.get("outcome"), len(r.get("skills", []))))' <private file>
```

`<private file>` is a new owner-only file outside any project; keep it: its rows name the folders the block below copies into. If the reader can't read it (the installer printed no JSON), show the user that file and the exit line, and stop. It copies every skill the release ships (the output's `skills` list, which the reader counts) into `<root>/skills` and into each agent folder present here: `~/.claude/skills` (Claude Code), `${CODEX_HOME:-$HOME/.codex}/skills` (Codex: `$CODEX_HOME/skills` when `CODEX_HOME` is set, otherwise `~/.codex/skills`), `~/.cursor/skills`, `~/.config/opencode/skills` and `~/.grok/skills`. The reader prints one line per agent row, its state first. Done for the agent you are running in when its row reads `installed` or `partial`, with no `skipped: install` line and no `missing:` line for it: the reader checked that agent's folder, the row's `path`, holds every skill in the release's list except the ones skipped there, each marked by the installer as this release's copy (its `.openwiz-skill` names the output's `source`), so the count never goes stale and an older copy never passes. For each `skipped:` line, tell the user the skill, the agent and its `next` step (their own skill of that name is kept: they move or rename it, then run this again); never delete or overwrite it. A `missing:` line means that skill did not arrive, or an older copy is still there: report it with the row's `next` step (a write failure says what to fix), then run `install skills` again; that agent is not done. An `absent` row means that agent's folder (`~/.claude`, or for Codex `$CODEX_HOME` when set, otherwise `~/.codex`) is missing on this computer: tell the user which folder, that their agent has no OpenWiz skills, and its `next` step; never create the folder yourself. A `refused` row names why that agent got nothing. `outcome: refused` (exit 5) means nothing was installed, not even `<root>/skills`: name each `absent` row's folder and stop here.

Then make every installed copy of this skill this one, the whole folder. The copy `install skills` just wrote comes from the release's package and can be older: `grep -m1 '^version:' "$build"/runtime/skills/install/SKILL.md` prints its real version from the verified build, an older copy's `SKILL.md` and scripts can still name a setup page and a server OpenWiz removed, and a new session loads it whatever the user says. Never downgrade it: when the verified build's copy, `"$build"/runtime/skills/install`, reads this skill's version or a newer one, the block below takes it and skips the clone. Otherwise take this skill's own folder: the one you read it from when it is on this computer (a WizSkills clone or plugin: set `src` to it and skip the clone), otherwise a fresh clone of this skill's own release tag, `v<version of this skill>`, never `main` (it installs nothing). Then overwrite only the agent folders the installer reported as taking OpenWiz's copy, and check every file by content. `<installed agent folders>` is the quoted `path` of each `harnesses` entry from `install skills` that reads `installed`, or `partial` with no `skipped` entry for `install`. Without this session's `install skills` output (a resumed session), run `install skills` again from a fresh clone of the chosen `<tag>` and use its rows; if you can't, copy nothing and tell the user. Never guess a folder. A folder is copied over only when no part of its path is a link (the installer refuses those too) and while its `install/.openwiz-skill` is the installer's own receipt, never a user's skill. `<version of this skill>` is the `version:` at the top of this file, such as `0.4.0`:

```sh
want='version: <version of this skill>'
bundled=$(grep -m1 '^version:' "$build"/runtime/skills/install/SKILL.md 2>/dev/null)
if [ -n "$bundled" ] && python3 -I -c 'import sys; v = lambda s: tuple(int(p) for p in s.split()[-1].split(".")); sys.exit(v(sys.argv[1]) < v(sys.argv[2]))' "$bundled" "$want" 2>/dev/null; then
  src="$build"/runtime/skills/install; want=$bundled
else
  wizskills=<private temporary folder>/WizSkills
  git clone --depth 1 --branch v<version of this skill> https://github.com/openwizdev/WizSkills "$wizskills"
  src="$wizskills"/skills/install
fi
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

If it prints `NOT THIS SKILL` (the clone failed, or that tag is not published yet), nothing was copied: stop here, say so, and try again shortly. A `not OpenWiz's, left alone` line is the user's own skill: never copy over it, and say so if it is the running agent's. A `STILL OLD` line means that folder's copy did not take (it may not be writable): report it and fix it before you carry on; never carry on with, or restart onto, an old copy. A later `install skills` run, such as a repair, writes the old copy again: repeat this block after it.

**Carry on in this session; no restart.** An agent lists new skills only when it starts, so don't wait for it to find them: read the running agent's installed copy of this skill in full, by path, and follow it from step 5. That exact file is the `path` of the running agent's `harnesses` entry plus `/install/SKILL.md`, the folder the block just printed `ok:` for:

- Claude Code: `~/.claude/skills/install/SKILL.md`
- Codex: `${CODEX_HOME:-$HOME/.codex}/skills/install/SKILL.md`

Read it with your file tool, or `cat` it, and check its `version:` line reads `version: <version of this skill>`, or the newer version the block kept. From then on `<this skill's folder>` is that file's folder (`~/.claude/skills/install`, or `${CODEX_HOME:-$HOME/.codex}/skills/install`) for `teach.md`, `ideas.md` and `scripts/`, never a temporary clone. Keep what this chat already holds (the host answer, the release `<tag>`, `<root>`, `<build>` and `<state>`) and ask nothing again.

Give the user their host's continuation message all the same, for a later session if this chat ends early:

- This computer: `continue the OpenWiz install with host local and release <tag>`
- boat.dev: `continue the OpenWiz install with host boat and release <tag>`
- CloudRoom: `continue the OpenWiz install with host cloud and release <tag>`

Keep the full message. "continue the OpenWiz install" names the skill, the host carries the user's answer into Resume, and `release <tag>` (step 1's, filled in) keeps the chosen release after GitHub's Latest moves.

**The restart is the fallback,** only when this agent cannot read that file and follow it in this session: its tools can't open a file outside the project, or it can follow only the skills it loaded at start. Then the user restarts the agent and pastes that message into the new session, which starts at Resume. Any installed copy whose `version:` line is older than this file's is older than this one; if you are told to install again, follow this skill (https://github.com/openwizdev/WizSkills/blob/v<version of this skill>/skills/install/SKILL.md) and resume at the first unfinished step, as Resume says.

Done when the reader printed `installed` or `partial` for the running agent with no `missing:` or `skipped: install` line for it and every `ok:` line printed with no `STILL OLD`, or the user knows which folder is missing; the user has the continuation message with their chosen host; and you have read that agent's installed `install/SKILL.md` and carry on at step 5 in this session, or, only as the fallback, the user is restarting their agent.

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
- **A new repository:** GitHub sign-in first, which the person does themselves: show them `python3 -I -B "$build"/runtime/setup/github_login.py sign-in --state-dir <state> --yes` to run in their own terminal (it opens GitHub's browser page), and wait until they say done. Then run the read-only check, `python3 -I -B "$build"/runtime/setup/github_login.py status --state-dir <state>`, and continue only when it reads their account. Then `first_fleet.py create-repo --repo <owner>/<name>` previews it, its one README commit, and the passing test and CI check (`check`) it adds; on the yes, add `--yes`. Exit 6: run it again. With CloudRoom, the user makes or picks its CloudRoom project.

Done when the idea and one repository are chosen and read back. There is no second repository.

### 3. Connect

For that repository, each tool previews and applies only on the yes (`--yes`, or `--yes --operation <id>` from its preview). Setup takes one yes for the defaults, one pick of the permission mode and one pull request the user merges once:

1. **Sign-in:** run the read-only `github_login.py status --repository <owner>/<name> --state-dir <state>`. Only its account and push-access read-back count. Signed out, or without push access, the person fixes it themselves, as in step 2 (`github_login.py sign-in --repository <owner>/<name> --state-dir <state> --yes` in their own terminal); then run `status` again.
2. **One block of defaults:** save `<root>/current/openwiz models --json --host cloud` privately with CloudRoom; with a driver host, `<root>/current/openwiz models --json --host <its name>` (on this machine it offers only the harnesses `where` found). Then run `first_fleet.py defaults --options <saved file>`. It prints the recommended setup as one block: the user's GitHub login as operator, a new service issue, the current builder and reviewer models, and the user's own login instead of the GitHub App for the first fleet, on every host (step 3). Under it, it lists the five numbered steps that one yes covers: the service issue, `setup.py prepare`, the acting identity, `openwiz init` (its missing labels and the brain's pull request) and `setting` (the files it adds to that pull request, including setup's four files for a new repository). For a repository `create-repo` made, those files name the passing test and the CI check, `check`, it added. An existing repository with no `docs/agents/fleet.md` has no test command or CI check OpenWiz can name, and OpenWiz's setup check needs one of each, so `defaults` refuses and names that gap with its one-line fix: the user's agent adds one passing test and a CI workflow with a job named check, then runs the `setup` skill, and the user merges that. Say it as printed; never add a test or workflow yourself. Show the block and its steps as printed and ask its one question. One yes accepts all of it: run it again with `--yes --confirm <the digest it printed>`; if anything changed since, it refuses and prints the new block to ask again. To change a line instead, add its flag (`--operator <login>`, `--service-issue <N>`, `--harness <h> --model <m> --effort <e>` or `--reviewer-harness <h> --reviewer-model <m> --reviewer-effort <e>` from the saved options, or `--app`), show the new block and take the yes to that. The permission mode is never in the block. With CloudRoom also ask, one question each, for the two CloudRoom ids below.

   Then apply it on that yes, the block's steps in order, each tool's preview then its `--yes --operation <id>`, without asking again while the preview shows only what its step said; anything else it shows is asked first. `first_fleet.py next --setup-state <state>` names the first step not applied yet, so a new session resumes there:
   - For a new service issue, run `first_fleet.py service-issue --yes`. It saves a pending record first, reuses your open issue titled "OpenWiz service records" in that repository when there is one, and otherwise opens one (an issue, not a pull request). Exit 6 means the reply was lost: run it again, and it reads the open issues back before it opens anything. It prints the issue's number, and `next` names that number for `prepare`.
   - `setup.py prepare --state-dir <state> --repository <owner>/<name> --operator <login> --service-issue <N> --harness <harness> --model <model> --effort <effort>`, from the block, with `<N>` the issue `service-issue` printed. For this computer add `--host local`, for boat.dev `--host boat`, and for another driver `--host <its name>`; the default is `cloud`. With any host but `cloud`, give no `--project` or `--answer-thread`: `prepare` refuses them ([setup v1](https://github.com/openwizdev/OpenWiz/blob/main/contracts/setup.v1.md), the host-aware report).
     - `--project`, only with CloudRoom: the CloudRoom project the fleet runs in, by id (`<root>/current/openwiz ls --json` groups threads by project).
     - `--answer-thread`, only with CloudRoom: the user's CloudRoom thread in that project that gets the fleet's answers, from the same `ls`; another project's thread reads `project_answer_refused`.
   - Then the acting identity (step 3 below) and the brain (step 4 below).
3. **The App, or an explicit skip:** the block's acting identity line shows the recommendation.
   - **On every host, for the first fleet:** recommend the personal GitHub login, the verified path: the installed `github_login.py skip-app` (preview, then `--yes --operation <id>`), so the login `status` read back acts. This holds with CloudRoom too.
   - **The App, offered instead:** when the user asks for it, add `--app` to the block: the App, set up with the installed `"$build"/runtime/github-app/setup.py` as the `setup` skill's "The App" says. Without CloudRoom, say in one line that the App needs CloudRoom today.

   Only the user's answer selects `github_login.py skip-app`; an App failure never becomes a skip. The block's yes is that answer when its acting identity line names the user's own login.
4. **The brain:** `<root>/current/openwiz init --repository <owner>/<name> --state-dir <state> --json`. Say in one line where it went, and do not ask for a merge yet: in the repository its pull request becomes the one setup pull request. For a public repository's private companion, run `first_fleet.py decisions --setup-state <state>`, then `--yes`.
5. **The permission mode and the setup pull request:** on this machine ask the permission mode once, as **Host setting** says. Then run `first_fleet.py setting --setup-state <state> --build "$build"` (the block's step 5): it refuses until the block's steps 1 to 4 are applied. While the brain's pull request is open in the repository it adds the Models table, the host setting and the mode rows (and, for a new repository, setup's four files) to that same pull request; for a companion brain it opens one settings pull request in the repository. Show its effect; when it shows only what the block's step 5 said, with the mode rows of the user's pick, run it with `--yes` on the block's yes, without asking again. Ask the user to merge that one pull request, once. A brain pull request that is already merged (in a companion, `openwiz init` may merge it itself) is done and never asked for; `setting` names one that still waits.
6. **Carry it:** after the merge, `setup.py check --state-dir <state>`, then `first_fleet.py continue --setup-state <state> --explained`. It refuses, naming each component that is missing, refused, unknown or stale, and withdraws what it carried before; follow that `next` step and run both again.

Done when `continue` prints the carried setup and the acting identity. Nothing else asks for a merge before the grill.

### 4. Grill

Say **The grill**'s first line, then run `grill` in one short round: at most three questions, each with a recommendation, steered to about three small tickets, each one a single builder finishes fast, with no blockers between them and no shared owned paths, so all three build in parallel. Anything bigger waits for the closing offer's keep building, after the first merge. When its summary is ready, show it and say **The grill**'s second line. Only the user's yes here confirms it; anything else is a change to make. Save the yes as `grill` says, then run `first_fleet.py grill --confirmed <its private comment URL>`.

Done when `grill` recorded the confirmation.

### 5. Agents

Harness, model and effort were answered in Connect's block, and its setup pull request carried the Models table. Run `first_fleet.py choose --options <saved file> --from-setup` with the options Connect saved (`<root>/current/openwiz models --json --host cloud` with CloudRoom, `<root>/current/openwiz models --json --host <its name>` with a driver host). It reads the default branch's Models table back, keeping the Reviewer in the other family, and asks for no merge. Without Connect's block (an older onboarding), ask the three and pass `--harness --model --effort`: `choose` writes the table into `docs/agents/fleet.md`; commit that file and merge it, then run the same `choose` again to read it back.

Done when the choice is recorded and the default branch's Models table names it.

### 6. Host setting

Connect runs this step before its merge, so the mode and the host setting ride in the one setup pull request; afterwards `setting` only reads them back. On this machine, ask the owner to pick the harness permission mode, once, on its own and never inside Connect's block. Run `first_fleet.py mode`: it lists the modes of every harness the fleet starts here, each with what it lets an agent do. With both Claude Code and Codex installed, builders use one and each review uses the other, so it lists both, and the owner picks one mode for each. Explain each one plainly, as printed, and recommend none: never pick, default or widen a mode for the owner, and touch no login. On their answer, run `first_fleet.py mode --mode <their pick>`, or with both harnesses `first_fleet.py mode --claude-mode <their pick> --codex-mode <their pick>`. From those picks it saves this machine's host-side approval for the repository and each harness, outside the repository, through the local driver's setup step; it never changes or widens an approval already saved. The host setting below adds the matching `fleet.md` rows. The local driver passes the mode to the harness unchanged and starts nothing unless the row and the approval match.

Then run `first_fleet.py setting` (after Connect's block, with `--setup-state <state> --build "$build"`). While the brain's pull request (init's `openwiz/brain` branch) is open in the repository, it writes the files below, and the Models table Connect's block chose, on that branch, so that one pull request carries them all and opens no other; it first checks that pull request is init's, onto the default branch, holding exactly init's brain files, and writes nothing to one holding anything else. Otherwise (a merged brain pull request, or a companion brain) it uses its own branch `openwiz/host-setting`. A repository `create-repo` made, with no `docs/agents/fleet.md`, also gets setup's four files, filled from the block, with its test command `python3 -m unittest discover -s tests` and its CI check `check`; any other repository without that file is refused, naming the gap, as Connect says. A write cut short is completed when it runs again on the same branch. For a driver host other than this machine (boat.dev, or another the user picked) it previews one pull request that adds only `docs/agents/host.md` with `Host: <its name>`, the line launch-fleet reads, and no mode row; on the yes, run it with `--yes` and ask the user to merge it, as below. For this machine it previews one pull request that adds `docs/agents/host.md` with `Host: local` (the host launch-fleet reads) and the mode rows to the `docs/agents/fleet.md` setup wrote (the modes the local driver reads), changing no other line: one row, `| Harness permission mode | `<their pick>` |`, or with both harnesses one row each, `| Harness permission mode (claude) | `<pick>` |` and `| Harness permission mode (codex) | `<pick>` |`. On the yes, run it with `--yes` and ask the user to merge it. It never adds a second row or replaces a mode the owner already saved: it names that row and asks. It never writes over a branch `openwiz/host-setting` that holds anything else, and it says the pull request is ready only once both files read back from it exactly; a failed or uncertain write is said, never retried blindly: run it again to read the branch first. For Cloudroom no file is needed: it says so and exits 0. It never overwrites a host the project already names. The launch waits until the pull request is merged, for every driver host.

Done when both settings match the answers, or their pull request is open.

### 7. Plan

The plan checks itself. Run `to-spec` with the confirmed grill and say it is the install's first fleet: it writes the spec and runs `to-tickets`, whose checks record the machine plan approval, then goes straight to the launch with no video (to-spec skips its video step for this fleet only; a later spec, from keep building or anywhere else, gets its video as usual). A reset or change of this spec or plan, before or after the launch, gets a new machine approval and still no video. Say **The spec and its video** with the spec link. Without Node on `PATH` nothing changes: you skip the video step all the same, and the fleet still starts. Ask nothing here: no spec or plan approval. For now the owner steers through the orchestrator: what they want changed goes to this chat, never a comment on the spec, which steers nothing until OpenWiz #1402. launch-fleet's one-time notice saying so is normal, not a hold. When a check refuses, re-cut the plan; never ask the user to approve it instead. Then run `first_fleet.py spec --spec <N> --repo <owner>/<name>`.

Done when the machine plan approval is on the spec and `spec` saved it.

### 8. Launch

Preview with `first_fleet.py launch --spec <N>`. It reads the spec's machine plan approval for this grill, the host the user chose (a driver host, this machine or boat.dev or another, only once its host setting is merged) and launch-fleet's own frontier, then prints the start's effects and one question that names the host and says it can cost money. Show the effects and ask that question as printed. This is the one yes before the fleet starts; never skip it, even though the cost was shown at **Where agents run**. On the yes, run it with `--yes --confirm <the digest it printed>`. It refuses if anything changed since the preview: preview again and ask again.

- **This machine:** the yes hands the fleet to launch-fleet's session runner (`session.py run`, [Hosts without CloudRoom](../launch-fleet/references/launch.md#hosts-without-cloudroom)) in this chat, with no timer and no heartbeat. Say **The fleet starting** as `launch` prints it, then let the session run: its tick lines show here, and `launch` waits until it stops. It prints where the session stopped and, unless the spec is done, the session's own stop lines as they are, its `carry on:` command among them: show them to the user unchanged. After them it prints onboarding's carry on, `first_fleet.py launch --spec <N> --carry-on`: that is the one you run here. It runs the same session command again with the fleet's saved driver folder and GitHub-only, and saves where it stops, so `progress` shows the latest stop; never run the session's own `carry on:` command by hand in onboarding. The session merges nothing: at an approved, green pull request it stops with exit 3 and its lines say how to merge it and carry on; the user merges it (or launch-fleet's Merging steps do), then run `launch --spec <N> --carry-on`. On any other **needs you**, handle that line with launch-fleet, then run `launch --spec <N> --carry-on`. A refused carry-on keeps the fleet's start: run it again once the other session or heartbeat tick ends. If the session was refused (another session or a heartbeat already runs the spec), the yes is withdrawn: preview again and ask again.
- **The heartbeat, the opt-in:** after a session that did not finish the spec, `launch` offers the heartbeat for keeping the fleet going after the chat closes. Ask only that, once. Only on the user's yes, run `first_fleet.py launch --spec <N> --heartbeat`, show its job preview and question, and on a second yes to that, run it with `--heartbeat --yes --confirm <its digest>`. Without their yes, install nothing.
- **CloudRoom:** it starts nothing itself: it saves the yes and names launch-fleet's own start path. Follow launch-fleet's Launch section ([references/launch.md](../launch-fleet/references/launch.md)): the project's two loops, the GitHub messages question (a gate, in its own words), then "Starting one": the spec's loop, its private loop-map entry, read back, and the `launch-fleet: fleet active, loop fleet-<S>` record, read back. Then run `first_fleet.py launch --spec <N>` again: it says **The fleet starting** when the activation record reads back.
- **Another driver host (boat.dev or another):** follow the local heartbeat handoff as `launch` printed it, including the heartbeat preview and approval. Then run `first_fleet.py launch --spec <N>` again: it confirms the active heartbeat.

Never start the fleet a second way.

Done when this machine's session has run and stopped, `launch` reads back the CloudRoom activation record, or it confirms the active heartbeat for another driver host.

### 9. Watch

Run `first_fleet.py progress --spec <N> --openwiz <root>/current/openwiz` when the user asks or a moment may have happened, and say each moment's line once: **A pull request opened**, then **Reviewed**. On this machine it first says where this chat's session last stopped (after a carry-on, where that one stopped), with the session's own stop lines and onboarding's `launch --spec <N> --carry-on`, and whether the heartbeat is installed. A count is never a merge. When a pull request merges, run `first_fleet.py first-merge --pr <number>`: it reads the merge back from GitHub and prints **Merged** and **The closing offer**; say both. On the answer: stay as the project's orchestrator (launch-fleet), start a new project (this road again, with a new state file), or keep building (the grill again, for the next idea).

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

1. **Heartbeat first.** A local fleet's heartbeat is a per-user scheduled job outside `<root>`, and it keeps waking after the build is gone. Other installs' jobs share its folder, so list every job (it only reads):

   ```sh
   for c in ~/.local/state/openwiz-heartbeat/*/config.json; do
     [ -f "$c" ] && python3 -I -c 'import json, sys; c = json.load(open(sys.argv[1])); print("job:", *c["argv"][-2:], "(adapters: %s)" % (c.get("environment", {}).get("OPENWIZ_ADAPTERS") or "none"))' "$c"
   done
   ```

   Each line reads `job: <owner>/<repo> <S> (adapters: <folder>)`, the folder being the build that job runs on. Never decide which jobs are this install's yourself: another install's state folder can sit inside this one's, so a folder inside `<state>` proves nothing. Show the user every `job:` line, ask which belong to this uninstall, and remove only the jobs the user names; every other job keeps running. Set `launch_fleet` to the installed launch-fleet skill's folder and, for each job the user named, run `python3 -I "$launch_fleet"/scripts/heartbeat.py remove "<owner>/<repo>" "<S>"`: it takes down the schedule, stops the saved orchestrator and removes its state. `heartbeat: not installed` means there was none.
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
