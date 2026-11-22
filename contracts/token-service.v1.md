# Token service v1 (`openwiz.token-service.v1`)

GA1 of spec #1837, its contract-first ticket (#1839). This contract covers how
an agent gets an `openwiz[bot]` installation token without the App's key ever
leaving the owner's machine: the request, the answer, every refusal, the
refresh rule, how an agent reaches the service, the fallback to the owner's
account and the never-exposed rules. GA2 (#1841) builds the service, GA3
(#1844) the agent helper and GA4 (#1846) the fleet's use of it. They build to
this contract.

**This contract grants nothing.** It authorizes no installation, credential,
token mint, live read or write, or permission change. A fixture or test that
passes here proves the contract is consistent, never that any of it is live.
[`github-identity.v1`](github-identity.v1.md) stays authoritative for the App,
its permission profile, its installations, authorship and roles. For agents'
tokens, this contract replaces that contract's Cloudroom-secret route for the
key: the key stays on the owner's machine and never enters a secret store
(spec #1837, superseding G2's choice, #1402).

## The pin

The JSON block below is the machine-readable pin.
`contracts/fixtures/token-service/test_fixtures.py` checks it against
`github-identity.v1`, the schema and the fixtures. The prose explains it.
Where they disagree, the contract is wrong and must be fixed.

```json
{
  "schema": "openwiz.token-service.v1",
  "authority": {"installation": false, "credential": false, "live": false},
  "key": {
    "lives": "owner's machine only",
    "path": "<state>/service/app/private-key.pem",
    "file_mode": "0600",
    "directory_mode": "0700",
    "read_by": "the token service only",
    "agents": "never ask for, read, copy or hold it",
    "leaves_the_machine": false
  },
  "app_permissions": {
    "metadata": "read",
    "contents": "write",
    "issues": "write",
    "pull_requests": "write",
    "checks": "read",
    "actions": "read"
  },
  "reach": {
    "listens": "no port",
    "request": "stdin",
    "answer": "stdout, one JSON line, read from a pipe",
    "timeout_s": 60,
    "token_crossing": {
      "never": ["command line", "terminal", "log", "record"],
      "only": "piped stdout of one room-cli mac run --stdin call",
      "into": "the caller's private place",
      "live_gate": "GA5 reads back no pairing log or mac run result record keeps it",
      "if_kept": "cloud route stays off; cloud threads fall back with the note"
    },
    "pairing_gate": {"variable": "OPENWIZ_TOKEN_SERVICE_READBACK", "on_only_when": "passed", "otherwise": "pairing-off"},
    "routes": {
      "pairing": ["room-cli", "mac", "run", "--stdin", "python3 -I '<service>' mint"],
      "local": ["python3", "-I", "<service>", "mint"]
    },
    "configuration": {
      "OPENWIZ_TOKEN_SERVICE": "the service's absolute path on the owner's machine",
      "OPENWIZ_TOKEN_SERVICE_ROUTE": ["pairing", "local"],
      "OPENWIZ_TOKEN_SERVICE_READBACK": "passed only after GA5's live read-back succeeded"
    }
  },
  "request": {"repeated_key": "usage", "repository_case": "insensitive"},
  "answer": {
    "max_lifetime_s": 3900,
    "scope": "exactly the requested repositories and permissions"
  },
  "refusals": {
    "usage": {"exit": 2, "message": "Token refused: the request is not one valid token-service request."},
    "one-owner": {"exit": 2, "message": "Token refused: the repositories must share one owner."},
    "not-installed": {"exit": 3, "message": "Token refused: a repository is not in the App's installation."},
    "permission": {"exit": 5, "message": "Token refused: a permission is outside the App's."},
    "github": {"exit": 5, "message": "Token refused: GitHub refused the exchange or granted a different scope."},
    "expiry": {"exit": 5, "message": "Token refused: the minted token failed the expiry guards."},
    "unavailable": {"exit": 1, "message": "Token refused: the service cannot read its App state or reach GitHub."}
  },
  "refresh": {"at_or_under_s": 300},
  "fallback": {
    "identity": "the owner's existing GitHub login",
    "note": "openwiz: no openwiz[bot] token (<reason>); using the owner's GitHub account",
    "notes_per_run": 1,
    "clears": ["GH_TOKEN", "private token file"],
    "reasons": ["unreachable", "bad-answer", "pairing-off", "usage", "one-owner", "not-installed",
                "permission", "github", "expiry", "unavailable"],
    "not_configured": "exactly as today: no note"
  },
  "handover": {
    "gh": "GH_TOKEN in the child's environment",
    "git": "a credential helper that reads the private token file",
    "private_file": {"mode": "0600", "directory_mode": "0700", "outside_git_trees": true}
  },
  "mint_log": {"mode": "0600", "holds": ["at", "requester", "repositories", "permissions", "outcome", "expires_at"],
               "permissions": "minted only, App profile names only"}
}
```

## Where the key lives

The App's private key lives **only on the owner's machine** (the owner's PC
now; the VPS later, J258), in the owner's OpenWiz state directory, at
`<state>/service/app/private-key.pem`, mode 0600 in 0700 directories, where
the merged minter (`tools/github-app/`) already keeps it. Only the token
service reads it. It never leaves that machine: not to a cloud sandbox, a
Cloudroom secret, a pairing call, a prompt, a log or the repository.

**Agents never ask for the key.** No agent, helper, brief or request asks for,
reads, copies or holds it, and nothing in a request names it. The service
never sends it, and no answer or refusal carries it or the App's JWT.

## Reaching the service

The service listens on **no port**, public or local. An agent reaches it the
way it already reaches the owner's machine:

- **A cloud thread** runs the service through the owner's existing machine
  pairing: `room-cli mac run --stdin 'python3 -I <service> mint'`.
- **A local thread**, already on the owner's machine, runs
  `python3 -I <service> mint` itself.

`<service>` is the service's absolute path on the owner's machine, from
`OPENWIZ_TOKEN_SERVICE`; `OPENWIZ_TOKEN_SERVICE_ROUTE` says `pairing` or
`local`. Neither is a secret. The path sits inside single quotes on the
pairing route, so a path holding a single quote or a line break is refused by
the helper as `unreachable`, never run. The request goes on standard input, never on
the command line. The answer comes back as **one JSON line on standard
output, read from a pipe**: the caller never lets it reach a terminal, a
transcript or a log. A call has 60 seconds.

**How a token crosses the pairing** (the planner's answer on #1839, option 1;
2026-11-20):

- A token never appears on any command line, in a terminal, or in any log or
  record.
- It crosses the owner's machine pairing only as the piped standard output of
  one `room-cli mac run --stdin` call, read straight into the caller's private
  place.
- GA5's live check reads back that no pairing log or `mac run` result record
  keeps it. If one does, the cloud route stays off and cloud threads fall back
  to the owner's account, with the standard-error note, until that's fixed.

**The pairing route is off by default.** The helper makes a pairing call only
when `OPENWIZ_TOKEN_SERVICE_READBACK` is exactly `passed`, which the owner
sets only after GA5's live read-back has succeeded. Unset, `inconclusive`,
`failed` or any other value means the route is off: the helper makes no call,
and the agent falls back with the one note, reason `pairing-off`. The local
route needs no read-back, since its call never crosses the pairing. No fixture
or test enables the live route: they use synthetic values only.

How the owner starts and stops the service is GA2's runbook. A stopped
service answers like an unreachable one.

## The request

One JSON object (`#/$defs/request` in the schema), each key once: a repeated
key, at any depth, is a `usage` refusal, never the last value silently kept.

```json
{"schema": "openwiz.token-service.v1", "kind": "request", "requester": "builder-1839",
 "repositories": ["owner/name"], "permissions": {"contents": "write", "metadata": "read"}}
```

- **`repositories`:** one or more `owner/name`, all of one owner (one
  installation mints one token). Each must be in the App's installation.
  Owners and names compare without regard to case, as GitHub's do; the answer
  echoes them as requested.
- **`permissions`:** at most the App's: each name in the App's profile above,
  each level no higher than the App's (`read` is below `write`). A read-only
  use asks for read levels only (github-identity.v1's read profile).
- **`requester`:** a short synthetic label for the mint log, such as a role and
  ticket number. Never a thread id or a person's name.

## The answer

One JSON object (`#/$defs/answer`), exit 0:

```json
{"schema": "openwiz.token-service.v1", "kind": "answer", "token": "<token>",
 "expires_at": 4600, "repositories": ["owner/name"], "permissions": {"contents": "write", "metadata": "read"}}
```

The token covers **exactly** the requested repositories and permissions,
nothing wider. `expires_at` is Unix seconds; the token has more than 300 and at
most 3900 seconds left when handed over (github-identity.v1's guards). The
service's standard error stays empty on success.

## Refusals

A refusal is one JSON object (`#/$defs/refusal`) on standard output with the
pin's fixed exit and sentence, and no provider body, URL, id, key or token.
The service checks in this order and answers the first that applies:

| Refusal | Exit | When |
| --- | --- | --- |
| `usage` | 2 | Not one valid request: bad JSON, a missing or unknown field, a bad repository or level |
| `one-owner` | 2 | The repositories have more than one owner |
| `not-installed` | 3 | A repository is not in the App's installation |
| `permission` | 5 | A permission is not in the App's profile, or above the App's level |
| `github` | 5 | GitHub refused the exchange, or granted other repositories or permissions |
| `expiry` | 5 | The minted token has 300 seconds or less left, or claims more than 3900 |
| `unavailable` | 1 | The service cannot read its App state or key, or cannot reach GitHub |

## Refresh

The helper refreshes a token **when 300 seconds or less are left** (under five
minutes, github-identity.v1's refresh boundary), before the next use, by
sending a fresh request. An expired token is never used. A failed refresh
falls back as below.

## Handing the token over

- **`gh`** gets it as `GH_TOKEN` in its own environment.
- **git** gets it through a credential helper that reads the **private token
  file**: mode 0600, in a 0700 directory outside every Git working tree,
  replaced at each refresh and deleted at a fallback. Never in a remote URL, a `-c` option or a header
  argument.

## The fallback

When `OPENWIZ_TOKEN_SERVICE` is set and the helper gets no usable token, the
agent works as the owner's existing GitHub login, exactly as today, and the
helper writes **exactly one line** to standard error per run:

```text
openwiz: no openwiz[bot] token (<reason>); using the owner's GitHub account
```

`<reason>` is `unreachable` (the call failed, timed out, or the service is
stopped), `bad-answer` (the answer is not one valid answer or refusal, or its
scope or expiry differ from the request and this contract), `pairing-off`
(the pairing route is configured but its read-back has not passed) or the
refusal's code.

**A fallback leaves no service credential behind**, a failed refresh
included. Before the agent goes on as the owner, the helper deletes the
private token file and hands no `GH_TOKEN` to any child. With no file, the git
credential helper answers nothing, so git uses the owner's credentials too:
`gh` and git never split between the App and the owner. With **no service configured**, it
does nothing and prints nothing: starts are exactly as today.

## Never exposed

- No key or token appears in any output, log, commit, comment, argument list,
  URL, environment other than the `GH_TOKEN` of the child that uses it, or file
  outside its private place: the key's file on the owner's machine, the
  service's answer pipe, and the agent's private token file.
- **The mint log** is owner-only (0600) on the owner's machine: one line per
  request with `at`, `requester`, `repositories`, `permissions`, `outcome`
  (`minted` or the refusal code) and, when minted, `expires_at`
  (`#/$defs/mint_log`). A `usage` refusal logs `requester` as `-` and no
  repositories or permissions: nothing from an unreadable request is trusted.
  Every other refusal logs its checked repositories but no permissions, so a
  rejected permission name never reaches the log. A minted line logs only the
  App profile's permission names, and the schema refuses any other. It has no token, key or JWT field, and the schema
  refuses one.
- Approvals, repository settings and pushes that change `.github/workflows/`
  stay on the owner's own login (github-identity.v1's roles).

## Fixtures and the test

`contracts/fixtures/token-service/` holds synthetic fixtures only. Owners,
tokens and times are placeholders; times are Unix seconds on a controlled
clock.

- `requests.json`: a good write and a good read request, and each refusal, with
  the answer or refusal, exit, standard error and mint-log line (GA2's seam).
- `refresh.json`: tokens with time to spare, at the boundary and expiring, and
  whether the helper refreshes (GA3's seam).
- `fallback.json`: a pairing whose read-back has not run, was inconclusive,
  failed or is unknown; an unreachable service, a stopped one, a bad answer,
  refusals, a failed refresh from a held token, good answers over the pairing
  and locally, and no service configured, with the identity `gh` and git each
  use, the private token file, the environment and standard error (GA3's and
  GA4's seam).
- `invalid.json`: messages the schema must refuse, including a mint log with a
  token in it and one with a permission name outside the App's profile.
- `red-run.txt`: the test's failing-first run.

Run `python3 -I contracts/fixtures/token-service/test_fixtures.py`. It is
offline, uses no credentials and checks the pin against github-identity.v1,
every fixture against the schema and the pin's rules, the refresh boundary,
the single fallback note, and that no credential-shaped value or long id
appears and a token appears only in its private places.
