# GitHub identity

**The App identity is off unless the operator turns it on:** the `App identity` row of `docs/agents/fleet.md`'s `## GitHub identity` table, on the default branch, must say `on`. With no row, any other value or an unreadable file, act as today's signed-in account: never run, try or probe `openwiz github token` or `agent-token.py`, and skip the rest of this page. The block below checks the row itself before any mint, with the setup skill's own reader (its settings script's `app-identity` command), which reads off for anything but one `on` row with no fence-like line before it (OpenWiz #2394).

Read this before your first push, pull request, comment, label or merge as the App.

With the App identity on, the agents act on GitHub as the project's OpenWiz App ([`openwiz.github-identity.v1`](../../../contracts/github-identity.v1.md); GI7, #2549), so they spend the App's installation budget, not the user's account. **Builders** push their branch and open its pull request, **reviewers** comment, and **managers** (the ticks, fleet threads and orchestrator) comment, label and merge, each as the App. Every commit stays **authored and committed as the user**, so the credit stays theirs. The App only carries the push. The user keeps their own account for their own actions (approvals, settings).

- **The token:** mint one into its own variable when you need it, in the shell that runs the commands, and never store it. Never mint into `GH_TOKEN`: your own account's credential stays as it is, set or not. Only the commands you run through `app` and `app_git` see the App token: `gh` reads it from `GH_TOKEN`, and git gets it only through a credential helper that reads the environment, never in a URL or an argument. Add `--read` for a use that only reads (the check: with the App identity on, `loop.sh` mints a `--read` token for it). Tokens last an hour; mint again for later work.

  <!-- GI7 identity -->
  ```sh
  app_token=
  if fleet_md=$(gh api -H 'Accept: application/vnd.github.raw+json' "repos/<owner>/<repo>/contents/docs/agents/fleet.md" 2> /dev/null) \
    && printf '%s\n' "$fleet_md" | python3 -I "<the setup skill's folder>/scripts/settings.py" app-identity > /dev/null 2>&1; then
    app_token=$(openwiz github token --repository "<owner>/<repo>" 2> /dev/null) || app_token=
    [ -n "$app_token" ] || echo "GitHub as today's account: no App token" >&2
  else
    echo "GitHub as today's account: App identity is not on in docs/agents/fleet.md" >&2
  fi
  if [ -n "$app_token" ]; then
    app() { GH_TOKEN=$app_token "$@"; }
    app_git() {
      GH_TOKEN=$app_token git -c credential.helper= \
        -c 'credential.helper=!f() { [ "$1" = get ] && printf "username=x-access-token\npassword=%s\n" "$GH_TOKEN"; }; f' "$@"
    }
  else
    app() { "$@"; }
    app_git() { git "$@"; }
  fi
  # For example: app_git push origin HEAD; app gh pr create ...; app gh pr comment ...
  ```
- **The author:** before your first commit, read the user from GitHub on today's account (plain `gh`, not through `app`): `gh api user --jq '"\(.login) \(.id)"'`. Then `git config user.name <login>` and `git config user.email <id>+<login>@users.noreply.github.com`. Never guess them.
- **The fallback:** with the App identity off, no `OPENWIZ_GITHUB_APP_KEY` secret, no `openwiz`, or a failed mint, the block above says on stderr that you act as today's account, and `app` and `app_git` run the commands with your own credential untouched. Go on: the fleet never stops for it. The commit author rule still holds.
- **Workflows stay on today's path.** The App has no Workflows permission, so push a branch whose diff changes `.github/workflows/` as today's account.
- **A refused merge stops for the user.** The App merges only under `fleet.md`'s standing merge rules. If a repository rule refuses the App's merge, record `launch-fleet: merge blocked <commit>: a repository rule refused the App's merge` and tell the user ([user.md](user.md)). Never retry it as another account and never bypass the rule.

Until the operator sets the `App identity` row to `on`, and the user installs the App and gives its key (#2548), nothing mints and everything runs as today's account, as the fallback says.
