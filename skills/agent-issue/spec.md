# Agent issue

The issue description carries one record. The linter is `scripts/lint.py`. People read the title. Agents read the fence.

## Fence

Exactly one fence at column 0, info string `agent-issue`. Inside it, one JSON object with `"schema": "agent-issue/1"`. Duplicate keys are invalid. At most three other non-empty lines are ignored, so a forge may add `Closes #14`. Those lines are not the record. The description is at most 65536 bytes. No secrets, credentials, or hidden characters.

## Fields

| Field | Rule |
| --- | --- |
| `id` | A number such as `14`, or a lowercase slug with no hyphen |
| `kind` | `bug`, `feature`, `chore`, `spec`, or `research` |
| `goal` | One sentence, 8 to 240 characters |
| `summary` | Optional. One line, at most 120 characters. The title uses it, or `goal` when it is absent |
| `acceptance` | One to twenty items. Each `id` is `A1`, `A2`, and so on. Each `check` is a different command |
| `owned_paths` | Paths the worker may change. A directory ends with `/` and covers files under it. A path without `/` is one file |
| `out_of_scope` | Zero or more one-line strings |
| `depends` | Ids that must land first |
| `blocks` | Ids that wait on this one. No overlap with `depends`, and neither names this `id` |
| `risk` | `low`, `medium`, or `high`, then an optional `: note` |
| `gates` | Zero or more of `release`, `secrets`, `auth`, `ci-permissions`, `migration`, `spending`, each once. A non-empty list stops for a human |
| `effort` | `tiny`, `small`, `medium`, or `large`. Split a `large` issue before `ready-for-agent` |
| `ready` | `ready-for-agent`, `needs-grill`, or `blocked`. Ready needs empty `depends`. Blocked needs `depends` |
| `context` | `http` or `https` urls with a dotted host and no userinfo, or repo-relative paths |

Lists hold at most 20 entries.

## Title

`#<id>: <summary or goal>` when `id` is a number. Otherwise `<id>: <summary or goal>`. At most 256 characters. If `goal` does not fit, add `summary`.

## Work

Start only when `ready` is `ready-for-agent`. `needs-grill` waits for a design decision. `blocked` waits on `depends`. One issue is one outcome. The worked example is [template.md](template.md). A body that must fail is [examples/missing-goal.md](examples/missing-goal.md).

Opening the pull request is [agent-pr](../agent-pr/SKILL.md). Forge differences are in [forges.md](forges.md).
