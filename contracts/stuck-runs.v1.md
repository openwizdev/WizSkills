# OpenWiz stuck runs contract, version 1 (`openwiz.stuck-runs.v1`)

This contract defines the stuck check for every driver. [GE5](https://github.com/openwizdev/OpenWiz/issues/3742) supplies the contract and [synthetic timelines](fixtures/stuck-runs/timelines.json). [GE6](https://github.com/openwizdev/OpenWiz/issues/3745) and [GE7](https://github.com/openwizdev/OpenWiz/issues/3747) implement and test it with fake GitHub, a fake clock and a fake driver.

## Progress

An active run has a start time, a ticket, an author login and a branch. Its records also identify its [status note](agent-status.v1.md) and pull request once they exist. The run is active while it is the recorded run for the work and has not ended. The age of its status note alone does not determine whether the run is active.

Only three events move the progress time:

- An edit to the run's own status note, at the edit time GitHub records.
- A push to the run's own branch, at the push time.
- A comment on the run's ticket or pull request, at its creation time, from the run's author. Compare GitHub logins case-insensitively.

Measure from the start until the first progress event, then from the most recent progress. Ignore host logs, changes to other branches or notes, comments on other work, and comments from other authors. Fleet nudge, restart and look records do not count as progress, including when the fleet and run use the same login.

## Stuck

A run is stuck when it is active, is outside a usage-limit wait, and at least `stuck_minutes` have passed since its last progress or start. A driver's `wake` refusal naming a future usage-limit reset suspends every stuck action until that time. The refusal and reset do not move the progress time.

A stuck spell ends when progress resumes or the run ends. Progress at or after a nudge ends that nudge's spell. When the relevant run, progress or action records cannot be read, the checker does not guess that an action is due.

## Nudge

Below the daily cap, a stuck spell without a nudge gets one driver `wake`. Record the issued nudge on the ticket exactly as follows, with `<m>` the whole minutes since the last progress or start:

```text
launch-fleet: nudged #<ticket> after <m> minutes without progress
```

The first valid nudge record for the run in the spell supplies the nudge time. A quiet spell with a nudge never gets a second wake. A limit refusal still suspends actions until its reset.

## Restart

At least `restart_minutes` after the spell's nudge, if the run is still stuck and below the cap, stop it through its driver. After the stop succeeds, start one fresh run on the same ticket with the same recorded skill, harness and model. The fresh run resumes from the branch, pull request and status notes. Record the restart only when the fresh start succeeds:

```text
launch-fleet: restarted #<ticket> from its records
```

The checker only identifies due actions. The fleet verifies the run and records before acting. An uncertain stop must not start a replacement.

## Daily cap

Count a ticket's recorded restarts across its runs, using valid restart records posted on the current UTC day. At most two may occur per ticket per UTC day. When another spell is stuck at the cap, record one look on the ticket for that day and take no driver action:

```text
launch-fleet: look #<ticket>: stuck after 2 restarts
```

Later checks that day emit no further look for the same ticket. At midnight UTC the count starts over. The normal progress, nudge and limit rules still apply. Use GitHub's comment creation time for fleet action records, and accept them only from the project's record authors.

## Settings

A project can set either value in its `docs/agents/fleet.md` under `## Stuck runs`. Each row is optional. Use the default only when its row is absent.

| Setting | Value |
| --- | ---: |
| `stuck_minutes` | 30 |
| `restart_minutes` | 20 |

Each value is an integer from 10 through 240 inclusive. A malformed value, repeated setting or value outside the range refuses the settings and yields no due action.

## Timeline fixtures

[`timelines.json`](fixtures/stuck-runs/timelines.json) names the contract and one synthetic run. Each case is independent and uses the shared `run` as its starting state. A case supplies `now`, chronological `records` and the `expected` action, one of `none`, `nudge`, `restart` or `look`. It can override `active` and supply a partial `settings` map. `refusal: invalid-settings` also expects a settings refusal. All times are UTC timestamps.

- `status_edit` carries the note number, `push` carries the branch, and `comment` carries the login, target kind (`ticket` or `pull_request`) and number.
- `limit_wait` represents the active run's driver refusal and carries `reset_at`. `host_log` is unrelated activity.
- `nudged`, `restarted` and `look` carry the exact public record text. Each is a trusted record on the synthetic ticket. `nudged` belongs to the run in the case. The restart and look history can include earlier runs of that ticket.

GE6 checks the `none` and `nudge` cases. GE7 extends the checks to the full timeline set. The fixtures use only invented repositories, logins and run identifiers.
