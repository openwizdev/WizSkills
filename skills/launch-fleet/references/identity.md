# GitHub identity

**The App identity is off for everyone:** nothing turns it on yet (OpenWiz #2394; its opt-in reader is a later ticket), so act as today's signed-in account: never run, try or probe `openwiz github token` or `agent-token.py`, and skip the rest of this page. The block below never mints: it only defines `app` and `app_git` to run your commands as today's account.

Read this before your first push, pull request, comment, label or merge as the App.

Once the App identity can be on, the agents act on GitHub as the project's OpenWiz App ([`openwiz.github-identity.v1`](../../../contracts/github-identity.v1.md); GI7, #2549), so they spend the App's installation budget, not the user's account. **Builders** push their branch and open its pull request, **reviewers** comment, and **managers** (the ticks, fleet threads and orchestrator) comment, label and merge, each as the App. Every commit stays **authored and committed as the user**, so the credit stays theirs. The App only carries the push. The user keeps their own account for their own actions (approvals, settings).

- **The token** (only once the App identity can be on): mint one into its own variable when you need it, in the shell that runs the commands, and never store it. Never mint into `GH_TOKEN`: your own account's credential stays as it is, set or not. Only the commands you run through `app` and `app_git` see the App token: `gh` reads it from `GH_TOKEN`, and git gets it only through a credential helper that reads the environment, never in a URL or an argument. Add `--read` for a use that only reads (the check: with the App identity on, `loop.sh` mints a `--read` token for it). Tokens last an hour; mint again for later work.

  <!-- GI7 identity -->
  ```sh
  restore_today_account() {
    [ -n "${OPENWIZ_AGENT_TOKEN_RUN+x}${OPENWIZ_AGENT_TOKEN_GIT_AT+x}${OPENWIZ_AGENT_TOKEN_PATH_WAS+x}${OPENWIZ_AGENT_TOKEN_EXEC_WAS+x}${OPENWIZ_AGENT_TOKEN_SSH_WAS+x}${OPENWIZ_AGENT_TOKEN_PROTOCOLS_WAS+x}${OPENWIZ_AGENT_TOKEN_GH_CONFIG_WAS+x}" ] || return 0
    for restore_pair in PATH:PATH GIT_EXEC_PATH:EXEC GIT_SSH_COMMAND:SSH GIT_ALLOW_PROTOCOL:PROTOCOLS GH_CONFIG_DIR:GH_CONFIG; do
      restore_name=${restore_pair%%:*}
      restore_mark=OPENWIZ_AGENT_TOKEN_${restore_pair#*:}_WAS
      eval "restore_value=\${$restore_mark-}"
      unset "$restore_mark"
      case $restore_value in
        1*) eval "$restore_name=\${restore_value#1}"; export "$restore_name" ;;
        *) unset "$restore_name" ;;
      esac
    done
    restore_at=${OPENWIZ_AGENT_TOKEN_GIT_AT-}
    restore_count=${GIT_CONFIG_COUNT-}
    case $restore_at in '' | *[!0-9]* | 0?* | ??????????*) restore_at= ;; esac
    case $restore_count in '' | *[!0-9]* | 0?* | ??????????*) restore_count= ;; esac
    if [ -n "$restore_at" ] && [ -n "$restore_count" ] && [ "$restore_at" -le "$restore_count" ]; then
      while [ "$restore_count" -gt "$restore_at" ]; do
        restore_count=$((restore_count - 1))
        unset "GIT_CONFIG_KEY_$restore_count" "GIT_CONFIG_VALUE_$restore_count"
      done
      GIT_CONFIG_COUNT=$restore_at
      export GIT_CONFIG_COUNT
    else
      restore_end=${restore_count:-0}
      [ -z "$restore_at" ] || [ $((restore_at + 2)) -le "$restore_end" ] || restore_end=$((restore_at + 2))
      restore_index=0
      while [ "$restore_index" -lt "$restore_end" ] || eval "[ -n \"\${GIT_CONFIG_KEY_$restore_index+x}\${GIT_CONFIG_VALUE_$restore_index+x}\" ]"; do
        unset "GIT_CONFIG_KEY_$restore_index" "GIT_CONFIG_VALUE_$restore_index"
        restore_index=$((restore_index + 1))
      done
      unset GIT_CONFIG_COUNT
    fi
    unset GH_TOKEN OPENWIZ_AGENT_TOKEN_RUN OPENWIZ_AGENT_TOKEN_GIT_AT restore_pair restore_name restore_mark restore_value restore_at restore_count restore_end restore_index
  }
  restore_today_account
  app_token=
  echo "GitHub as today's account: the App identity is off" >&2
  app() { "$@"; }
  app_git() { git "$@"; }
  # For example: app_git push origin HEAD; app gh pr create ...; app gh pr comment ...
  ```
- **Today's account, restored:** `restore_today_account` is the one step that returns a shell to today's account; `loop.sh` defines the same function, byte for byte, and runs it whenever the App identity is off or no token step is its own, before any other command. It acts only when an inherited token step's marks are present (`OPENWIZ_AGENT_TOKEN_RUN`, `OPENWIZ_AGENT_TOKEN_GIT_AT` or any `OPENWIZ_AGENT_TOKEN_*_WAS`), and then: it restores `PATH`, `GIT_EXEC_PATH`, `GIT_SSH_COMMAND`, `GIT_ALLOW_PROTOCOL` and `GH_CONFIG_DIR` from each `OPENWIZ_AGENT_TOKEN_*_WAS` (`1<value>` sets the value; anything else, `0` included, unsets the variable), drops every `GIT_CONFIG_KEY_<i>`/`GIT_CONFIG_VALUE_<i>` entry from `OPENWIZ_AGENT_TOKEN_GIT_AT` onward (when that mark or `GIT_CONFIG_COUNT` is not a plain number of at most nine digits, or the mark is above the count, it unsets `GIT_CONFIG_COUNT` and every indexed entry from 0 up to the larger of a readable count and a readable mark plus 2, then each further index while an entry with that index is set), and unsets `GH_TOKEN` and every mark. So no `gh` or `git` shim, credential helper or installation token stays reachable. Without marks it changes nothing, so your own `GH_TOKEN` stays. It never reads `OPENWIZ_GITHUB_APP_KEY`; `loop.sh` records only whether the key is set (`${OPENWIZ_GITHUB_APP_KEY+set}`) and unsets it as its first command, so no command it runs, bundle generation included, inherits the key. Call it as is from any caller that falls back to today's account.
- **The author:** before your first commit, read the user from GitHub on today's account (plain `gh`, not through `app`): `gh api user --jq '"\(.login) \(.id)"'`. Then `git config user.name <login>` and `git config user.email <id>+<login>@users.noreply.github.com`. Never guess them.
- **The fallback:** with the App identity off, no `OPENWIZ_GITHUB_APP_KEY` secret, no `openwiz`, or a failed mint, the block above says on stderr that you act as today's account, and `app` and `app_git` run the commands with your own credential untouched. Go on: the fleet never stops for it. The commit author rule still holds.
- **Workflows stay on today's path.** The App has no Workflows permission, so push a branch whose diff changes `.github/workflows/` as today's account.
- **A refused merge stops for the user.** The App merges only under `fleet.md`'s standing merge rules. If a repository rule refuses the App's merge, record `launch-fleet: merge blocked <commit>: a repository rule refused the App's merge` and tell the user ([user.md](user.md)). Never retry it as another account and never bypass the rule.

Until a later ticket adds the App identity's opt-in reader, and the user installs the App and gives its key (#2548), nothing mints and everything runs as today's account, as the fallback says.
