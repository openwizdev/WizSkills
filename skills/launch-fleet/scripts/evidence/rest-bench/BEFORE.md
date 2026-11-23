# BEFORE: who spends the REST allowance (FR5, OpenWiz#2621)

The baseline for spec #2428's allowance plan. The AFTER bench reruns the same two commands once FR6 to FR12 land, against the target of 100 agents under 3,000 REST calls an hour.

Two kinds of number appear here, and they are never mixed:

- **Measured live:** the shared account's own `used`, read from `gh api rate_limit` (free) every 3 minutes for one hour. It counts every agent on the account, not one script.
- **Fixtures times cadence:** calls counted by `gh-meter.py` while each wake script ran its own test suite against its fake `gh`, divided by its fixture runs, times the fixed comparison scenario of 6 wakes an hour. A derived estimate, not an observation.

## Measured live: one hour on the shared account

`python3 -I bench.py live live-samples.jsonl` ([live-hour.txt](live-hour.txt)), samples from 2026-11-23 01:34:34Z to 02:34:41Z:

| Allowance | Samples kept | Used in the hour (lower bound) | Lowest remaining | Limit |
| --- | --- | --- | --- | --- |
| REST (`core`) | 19 of 21 | 2,303 | 2,860 | 5,000 |
| GraphQL | 19 of 21 | 556 | 4,456 | 5,000 |

The hour crosses one reset of each, so the units spent between the last sample before a reset and the reset itself are not seen: both totals are lower bounds. Two samples (01:37:35Z and 02:16:41Z) came back from another allowance window (their `reset` and `used` match neither neighbour) and are left out, as `live-hour.txt` lists. No sample was unreadable.

So, measured: the account spent at least **2,303 REST units in one hour**, 77% of the 3,000-an-hour target, at the fleet's size that hour.

## Fixtures times cadence: calls per run

`env -u OPENWIZ_GITHUB_APP_KEY TEST_JOBS=3 python3 -I bench.py fixtures OUT` ([fixtures-bench.txt](fixtures-bench.txt)) runs the wake scripts, suites and fixtures of this branch's commit 5ffd8c9, which equal main's at 32a94a6. Main has since changed `fleet.sh` and `merge.py`, and the AFTER bench reruns both benches at its own head. This run used the meter after review R2 and R3: route templates and verified header blocks. Every suite passed under the meter (`test.sh`: 918 cases, 0 failed), and none of the 25 stubbed agent, harness and host CLIs was called. Its call and unit counts equal the first run's; only the endpoint names and the uncertain count are new.

**Fixed comparison scenario:** each script runs once per wake, at 6 wakes an hour (one every 10 minutes). This bench fixes that scenario so BEFORE and AFTER compare like for like. It is derived, not measured, and is not a claim about any live fleet's cadence.

| Script | Role | Fixture runs | Calls | Calls per run | REST calls | GraphQL calls | REST units | Uncertain calls | REST units per run | REST units per spec-hour (scenario) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fleet.sh spec | fleet | 261 | 16893 | 64.7 | 12582 | 4311 | 7837 | 1 | 30.03 | 180.2 |
| merge.py | orchestrator | 174 | 1206 | 6.9 | 942 | 264 | 942 | 431 | 5.41 | 32.5 |
| status.py repair | orchestrator | 45 | 511 | 11.4 | 423 | 88 | 423 | 0 | 9.40 | 56.4 |
| post.py | orchestrator | 21 | 38 | 1.8 | 38 | 0 | 38 | 9 | 1.81 | 10.9 |
| ops-starts.py | orchestrator | 60 | 56 | 0.9 | 56 | 0 | 56 | 0 | 0.93 | 5.6 |
| brief.py | orchestrator | 49 | 0 | 0.0 | 0 | 0 | 0 | 0 | 0.00 | 0.0 |

Calls per run and REST units per run are means over each suite's fixture cases, error paths included: fixture means, not typical live wakes. Uncertain calls are counted as one REST unit each, a lower bound: all 441 are issue comment reads (merge.py 431, post.py 9, fleet.sh 1) whose page count or status the meter can't establish, such as a `--paginate` read without `--include`. Summed unrounded and rounded once, the scenario is **285.5 REST units per spec-hour**, against the 2,303 measured for the whole account in the live hour.

## Per role (fixtures)

| Role | Calls | REST calls | GraphQL calls | REST units | Uncertain |
| --- | --- | --- | --- | --- | --- |
| fleet | 16893 | 12582 | 4311 | 7837 | 1 |
| orchestrator | 1811 | 1459 | 352 | 1459 | 440 |

There is no used delta here: fixture runs set `GH_METER_RATE=0`, because the fake `gh` has no allowance to read. A used delta, where the meter has one, is a shared-account observation (every agent's calls land between the two reads), and the report leaves out any delta whose reads span an allowance reset. Every Python script ran as `orchestrator` and `fleet.sh spec` as `fleet`. The live hour's builders, reviewers and heartbeats are inside the measured total above, unmetered by role.

## Top five endpoints by REST units (fixtures)

| # | Endpoint | REST units | Calls | By script (REST units) |
| --- | --- | --- | --- | --- |
| 1 | `GET repos/:owner/:repo/issues/:n/comments` | 3,098 | 4,423 | fleet.sh 2,521; merge.py 431; status.py 137; post.py 9 |
| 2 | `GET repos/:owner/:repo/issues/:n` | 1,956 | 3,111 | fleet.sh 1,837; status.py 67; merge.py 52 |
| 3 | `GET repos/:owner/:repo/issues/:n/dependencies/blocked_by` | 1,830 | 2,783 | fleet.sh 1,830 |
| 4 | `GET repos/:owner/:repo/contents/:path` | 808 | 962 | fleet.sh 366; merge.py 328; ops-starts.py 56; status.py 45; post.py 13 |
| 5 | `GET repos/:owner/:repo/pulls/:n/files` | 401 | 401 | fleet.sh 401 |

`fleet.sh spec` spends 6,955 of these 8,093 units. The first three are its per-issue reads, which spec #2428 moves to batched GraphQL (FR4, FR8). The fourth is default-branch file reads (`docs/agents/fleet.md` and `triage-labels.md` in these fixtures), which it moves to git (FR6). The meter logs every file path as `:path`, so per-file numbers are not in the log. Units are fewer than calls where a script revalidates with an ETag and gets a free `304`.

## Per endpoint (fixtures)

| Method | Endpoint | Kind | Calls | REST units |
| --- | --- | --- | --- | --- |
| GET | repos/:owner/:repo/issues/:n/comments | rest | 4423 | 3098 |
| GET | repos/:owner/:repo/issues/:n | rest | 3111 | 1956 |
| GET | repos/:owner/:repo/issues/:n/dependencies/blocked_by | rest | 2783 | 1830 |
| GET | repos/:owner/:repo/contents/:path | rest | 962 | 808 |
| GET | repos/:owner/:repo/pulls/:n/files | rest | 401 | 401 |
| GET | repos/:owner/:repo/issues/:n/timeline | rest | 816 | 290 |
| GET | repos/:owner/:repo/issues | rest | 260 | 186 |
| POST | repos/:owner/:repo/issues/:n/comments | rest | 145 | 145 |
| GET | repos/:owner/:repo/pulls/:n | rest | 337 | 120 |
| GET | repos/:owner/:repo/issues/:n/events | rest | 97 | 97 |
| GET | search/issues | rest | 63 | 63 |
| GET | repos/:owner/:repo/commits/:sha/check-runs | rest | 133 | 50 |
| GET | repos/:owner/:repo/commits/:sha/status | rest | 133 | 50 |
| GET | repos/:owner/:repo/issues/:n/sub_issues | rest | 72 | 32 |
| GET | repos/:owner/:repo/git/ref/:ref | rest | 72 | 27 |
| POST | repos/:owner/:repo/issues/:n/labels | rest | 27 | 27 |
| GET | repos/:owner/:repo | rest | 72 | 26 |
| GET | user | rest | 66 | 25 |
| PATCH | repos/:owner/:repo/issues/comments/:n | rest | 22 | 22 |
| GET | repos/:owner/:repo/issues/comments/:n | rest | 20 | 20 |
| GET | repos/:owner/:repo/git/matching-refs/:ref | rest | 10 | 10 |
| DELETE | repos/:owner/:repo/issues/:n/labels/:name | rest | 6 | 6 |
| DELETE | repos/:owner/:repo/issues/comments/:n | rest | 4 | 4 |
| GET | installation/repositories | rest | 6 | 3 |
| view | issue view | graphql | 3164 | 0 |
| POST | graphql | graphql | 1267 | 0 |
| view | repo view | graphql | 226 | 0 |
| merge | pr merge | graphql | 6 | 0 |
