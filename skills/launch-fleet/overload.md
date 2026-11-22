# Overload admission (CS5): the observer's input, unknown states and pause

`fleet.sh overload <action>` runs the observer carried byte for byte in
[`scripts/carried/alarm.py`](scripts/carried/alarm.py). It reads one bounded
snapshot of the orchestrator's existing queue and rate-limit reads, makes no
network call, starts no controller, cancels nothing and sends no message.
Supply `GH_REPO`, `LAUNCH_FLEET_OVERLOAD_INPUT` (the observation below) and
`LAUNCH_FLEET_OVERLOAD_STATE` (the durable pause state below), then:

```sh
sh skills/launch-fleet/scripts/fleet.sh overload automatic-refresh
sh skills/launch-fleet/scripts/fleet.sh overload nonessential-poll
```

In an OpenWiz checkout, set `LAUNCH_FLEET_OVERLOAD_SUPPLY` to the absolute
path of that checkout's own overload supplier, the supply script in its CI
overload tool (MT6, #825), to have `fleet.sh overload`
read the war room collector's queue fact now, before `merge-batch`,
`automatic-refresh` and `nonessential-poll`, into a private file of that call's
own that only its guard reads (`LAUNCH_FLEET_OVERLOAD_INPUT` is then unused, so
concurrent calls never swap observations). A supplier that fails or can't start
leaves the guard no input, so it refuses new work as unknown. `completion` and
`reconciliation` read nothing more. That supplier is the checkout's own, never
part of this skill; its use and failure handling are in that checkout's CI
overload guide.

The actions are `merge-batch`, `automatic-refresh`, `nonessential-poll`,
`completion` and `reconciliation`. The output is one JSON decision. Exit 0
admits that action, 1 refuses it, and 2 means invalid invocation. Errors never
print input bodies, API responses or credential material. `allowed` supplies no
review, merge, messaging or live authority. Every existing hold, required check
and admission rule still applies.

## Inputs and source completeness

[`scripts/carried/healthy.json`](scripts/carried/healthy.json) is the synthetic input example. An observation contains
exactly `repository`, `observed_at` (Unix seconds), `complete`, `queue` and
`budgets`. Objects reject duplicate/extra keys and wrong types. Reads are bounded
to 2 MiB and 10,000 jobs; exceeding either bound is unknown, never empty.

The caller normalizes its existing complete queue reads: `queue.complete` must
cover every current required job across all pages, runs and current attempts,
not just the first page, newest run or one runner pool. `jobs` has unique,
nonempty synthetic-style opaque ids, `required` booleans, `status` (`queued`,
`in_progress`, `completed`), `queued_at` and nullable `started_at`. Requiredness
comes from the existing required-check/selection inputs; a missing receipt is
not evidence that a job is optional. A queued job has no start timestamp.
Running duration never counts as queue waiting.

`budgets` contains both `rest` and `graphql`: each has `remaining`, `limit`,
`reset_at` and `retry_after` (an absolute backoff deadline, zero if none). These
are the actual shared budget pools for the reads, never per-agent allowances.
Keep primary reset and secondary Retry-After/backoff evidence from the existing
reader. A crossed reset requires a fresh observation; it does not refill quota
by arithmetic. Unknown backoff cannot be represented as zero.

`observed_at` covers all component reads; the caller must mark incomplete if a
page, required-job classification, budget or backoff could not be established.
Inputs must be current and repository-bound. The maximum age is 60 seconds
(the observer's default; `fleet.sh overload` passes no other bound). This
is an input-validity check, not a new resume threshold. A caller assertion of
completeness is not authenticated live evidence.

## Decision and durable pause

| Observation | Decision |
| --- | --- |
| Oldest required queued job waits at least 300 seconds | alarm and pause |
| Either pool has remaining/limit strictly below 10% | alarm and pause |
| Oldest required queued job waits at least 900 seconds, or either pool is exhausted | escalation due and pause |
| Either pool has an active secondary backoff | alarm and pause |
| Missing, stale, partial, invalid or unreadable input/state | unknown and pause |

A known alarm/escalation survives an independent incomplete component; unknown
data never establishes healthy clearance. Waits use the oldest required queued
job across the complete input. Exact 10% alone is healthy; exact 300/900 seconds
triggers the corresponding threshold.

The state records the repository, pause start, cause, observation time and
evidence digest. Before taking the nonblocking state lock, each nonhealthy
observation atomically publishes an owner-only, fsynced record in
`<state>.pending/`. This journal retains triggers even when the lock is busy.
Every admission incorporates the journal under the state lock, preserving the
first trigger and upgrading only to a more severe trigger. It removes only
incorporated records after the pause's atomic, fsynced replacement; a crash
leaves either the journal or the durable pause. A later healthy snapshot cannot
erase either. Keep the journal alongside the state across restarts.

Journal input is bounded to 10,000 records and 2 MiB in total. Excess,
corrupt or unreadable records retain the journal and refuse new work, as does
corrupt state. Failed persistence or a busy lock also refuses. Nonregular
inputs are unknown; the guard never waits on a pipe or another invocation's
lock. Essential actions remain available on all these refusal paths.
Use one stable private state path per repository across orchestrator/fleet
invocations. The state must survive process and host restarts; never store the
only copy in a temporary directory. Provision its parent privately.

`merge-batch`, `automatic-refresh` and `nonessential-poll` are refused while
paused. `completion` and `reconciliation` remain allowed, including when data or
persistence is unknown, so admitted jobs and agents can finish. Those allowances
do not create fresh batch/refresh/poll authority. Keep their reads necessary and
bounded and honour the underlying reader's reset/backoff; no busy waiting.

There is **no resume/reset command and no automatic resumption**. Bring the
resumption disposition to Jake before enabling any resume path. Do not delete
or substitute the state to clear a pause.

`escalation: due_not_sent` means only that escalation is due. The orchestrator
uses its existing escalation channel only under its separate messaging authority.
Transport acceptance, recipient acknowledgement and work completion are separate
evidence. No delivery or acknowledgement is inferred here, and private response
payloads stay private. Offline tests never send a page.

## REST read budget (FR3, #2433)

[`scripts/budget.py`](scripts/budget.py) admits or refuses the next batch of
reads, so a wake backs off before the account's shared REST or GraphQL
allowance runs out. It is a gate a reader calls before each batch, not an
observer: it decides for that one batch and keeps no state.

```sh
python3 -I skills/launch-fleet/scripts/budget.py admit 12 headers-1.txt headers-2.txt
python3 -I skills/launch-fleet/scripts/budget.py admit 3 --resource graphql --floor 2000
```

Each file holds one earlier response as `gh api -i` writes it: the status line
first, then the headers up to the first blank line. Only that header block is
read; the body after it never counts. A file that doesn't start with its status
line, or whose headers don't end, is unknown. For a paginated read, save each
page's response in its own file (`gh api -i --paginate` puts every page in one
stream, and only the first page's headers would count). It reads the
`x-ratelimit-limit`, `-remaining`, `-reset` and `-resource` headers of every
file and takes the newest: the latest reset window (resets within ten
minutes of the latest are one window), and in it the lowest remaining,
whatever the files' order. The files must all count one allowance, `core`
(REST) or `graphql`, and `--resource` must match it when given. With no file,
or when that answer is past its reset, it reads `gh api rate_limit`, which
costs no allowance, for `--resource` (`core` by default). It admits the batch
when `remaining - N` stays at or above the reserve kept for builders and
reviewers: the larger of a quarter of the limit and 1,500 (1,500 for a limit
of 5,000). `--floor N` puts N in place of the 1,500.

It prints one JSON line,
`{"allowed": bool, "remaining": n, "limit": n, "reset": unix, "resource": "core"|"graphql", "reason": "..."}`.
Exit 0 admits, 1 backs off (the reason names the reset time) and 2 is unknown,
which also refuses: a missing, malformed or contradictory header, an answer
from another pool (such as `search`), answers from both pools, one unreadable
answer among several, or an unreadable `rate_limit`. It never prints a token
or a response body. Bad arguments are exit 2 with nothing on stdout.
`$LAUNCH_FLEET_NOW` (seconds since 1970) stands in for the clock in tests.

Beside the overload admission: the observer above pauses whole actions on a
complete snapshot of both pools at under 10%; the read budget refuses one
batch while its reserve is still left, so a wake's own reads stop well before
the observer's alarm. Neither clears or replaces the other.
