# GitHub identity

**The App identity is off for everyone:** nothing turns it on yet (OpenWiz #2394; its opt-in reader is a later ticket), so act as today's signed-in account: never run, try or probe `openwiz github token` or `agent-token.py`, and skip the rest of this page. The block below never mints: it only defines `app` and `app_git` to run your commands as today's account.

Read this before your first push, pull request, comment, label or merge as the App.

Once the App identity can be on, the agents act on GitHub as the project's OpenWiz App ([`openwiz.github-identity.v1`](../../../contracts/github-identity.v1.md); GI7, #2549), so they spend the App's installation budget, not the user's account. **Builders** push their branch and open its pull request, **reviewers** comment, and **managers** (the ticks, fleet threads and orchestrator) comment, label and merge, each as the App. Every commit stays **authored and committed as the user**, so the credit stays theirs. The App only carries the push. The user keeps their own account for their own actions (approvals, settings).

- **The token** (only once the App identity can be on): mint one into its own variable when you need it, in the shell that runs the commands, and never store it. Never mint into `GH_TOKEN`: your own account's credential stays as it is, set or not. Only the commands you run through `app` and `app_git` see the App token: `gh` reads it from `GH_TOKEN`, and git gets it only through a credential helper that reads the environment, never in a URL or an argument. Add `--read` for a use that only reads (the check: with the App identity on, `loop.sh` mints a `--read` token for it). Tokens last an hour; mint again for later work.

  <!-- GI7 identity -->
  ```sh
  app_token=
  echo "GitHub as today's account: the App identity is off" >&2
  app() { "$@"; }
  app_git() { git "$@"; }
  # For example: app_git push origin HEAD; app gh pr create ...; app gh pr comment ...
  ```
- **The author:** before your first commit, read the user from GitHub on today's account (plain `gh`, not through `app`): `gh api user --jq '"\(.login) \(.id)"'`. Then `git config user.name <login>` and `git config user.email <id>+<login>@users.noreply.github.com`. Never guess them.
- **The fallback:** with the App identity off, no `OPENWIZ_GITHUB_APP_KEY` secret, no `openwiz`, or a failed mint, the block above says on stderr that you act as today's account, and `app` and `app_git` run the commands with your own credential untouched. Go on: the fleet never stops for it. The commit author rule still holds.
- **Workflows stay on today's path.** The App has no Workflows permission, so push a branch whose diff changes `.github/workflows/` as today's account.
- **A refused merge stops for the user.** The App merges only under `fleet.md`'s standing merge rules. If a repository rule refuses the App's merge, record `launch-fleet: merge blocked <commit>: a repository rule refused the App's merge` and tell the user ([user.md](user.md)). Never retry it as another account and never bypass the rule.

Until a later ticket adds the App identity's opt-in reader, and the user installs the App and gives its key (#2548), nothing mints and everything runs as today's account, as the fallback says.
