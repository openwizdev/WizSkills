# WizSkills

WizSkills is the public home of OpenWiz's skills: the instructions, scripts and
tests that let a coding agent plan, build, review and run work as part of a
fleet. Each skill is a folder under `skills/<name>/`, read from its `SKILL.md`,
with its scripts, references and tests beside it. The skills install together
as one Claude Code plugin, `openwiz`, so each is named `openwiz:<name>`.

This README describes release 0.1.2. Every install below names that one
release; none follows a branch.
To report a problem with OpenWiz, ask your agent to file a GitHub issue.

## Versions

WizSkills uses semantic versions, starting at 0.1.0, and stays on 0.x while
the skills settle. A release is the annotated Git tag `v<version>` on `main`,
whose message records the release's commit and tree, a section of
[CHANGELOG.md](CHANGELOG.md) with its date and one line per change, and the
same version in `.claude-plugin/plugin.json`. A released tag never moves.

## What you need

Git, and a POSIX shell for `install.sh`. Some skills also run `gh`, `room-cli`,
Python 3 or Node, and read the project's own settings (such as its
`docs/agents/` files); each skill says what it needs. WizSkills supplies no
credentials and no project settings.

## Install on Claude Code

`claude plugin marketplace add openwizdev/WizSkills` registers the marketplace
from `main`, for browsing only. For an install, add the marketplace pinned to
this release instead, then install the plugin from it:

```sh
claude plugin marketplace add https://github.com/openwizdev/WizSkills.git#v0.1.2
claude plugin install openwiz@wizskills --scope project
```

Installing does not pin a marketplace that is already registered at another
ref: remove that registration first. Check that `claude plugin marketplace list`
shows the `wizskills` marketplace at `v0.1.2` and that
`claude plugin list` shows `openwiz@wizskills` at version 0.1.2.
Then start a new Claude Code session so the `openwiz:` skills load: a plugin
installed during a session is not available in that session.

## Get the installer

The Codex and other-agent installs run `install.sh` from a checkout of this
release. Check out the tag, and check the checkout before running anything in
it:

```sh
git clone --quiet --depth 1 --branch v0.1.2 https://github.com/openwizdev/WizSkills.git wizskills-installer
git -C wizskills-installer cat-file tag v0.1.2
git -C wizskills-installer rev-parse HEAD 'HEAD^{tree}'
git -C wizskills-installer status --porcelain --ignored
```

The tag's message is its release record, a JSON object naming `schema`,
`version`, `commit` and `tree`. The second command shows it; the third must
print exactly that commit and tree, and the last must print nothing.

## Install with install.sh

```sh
sh wizskills-installer/install.sh --version 0.1.2 --dest "$HOME/wizskills"
```

`install.sh --version <version> --dest <dir>` fetches only the tag
`v<version>`, checks its release record, its whole tree (every name, byte and
executable mode), `plugin.json` and the changelog, and only then puts a
checkout of that release at `<dir>`. The destination's parent must already
exist, and no part of its path may be a symbolic link. If `<dir>` already holds
exactly this clean release, it does nothing; a different, changed or unknown
`<dir>` is refused and left as it was. It writes nothing on failure.
Exit codes: 0 installed or already installed, 1 refused, 2 invalid arguments,
3 fetch or local failure.

## Install on Codex

Install with `install.sh` as above, then, from your project's root, link each
installed skill folder into the project's `.agents/skills/`. Each link points
at a whole skill folder, so its resources stay with it. An existing different
entry is refused, never replaced:

```sh
mkdir -p .agents/skills
(
  for skill in "$HOME/wizskills/skills/"*/; do
    skill=${skill%/}
    link=.agents/skills/${skill##*/}
    if [ -e "$link" ] || [ -L "$link" ]; then
      [ "$(readlink "$link")" = "$skill" ] || { echo "refused: $link exists" >&2; exit 1; }
    else
      ln -s "$skill" "$link"
    fi
  done
)
```

Check that `"$HOME/wizskills/.claude-plugin/plugin.json"` shows version
0.1.2. Then start a new Codex session so the linked OpenWiz skills load,
and ask Codex to read the exact skill, for example
`.agents/skills/build-ticket/SKILL.md`.

## Any other agent

Install with `install.sh` as above, then tell the agent to read
`$HOME/wizskills/skills/<name>/SKILL.md`. Keep the whole installed folder: a
skill reads its scripts and references from beside its `SKILL.md`. Check that
the requested skill resolves:

```sh
test -f "$HOME/wizskills/skills/build-ticket/SKILL.md" && echo ok
```

## Licence

[LICENSE](LICENSE) collects the upstream licence notices the skills carry.
Each adapted skill also keeps its notice in its own `SKILL.md`.
