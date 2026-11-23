# BEFORE: who spends the REST allowance (FR5, OpenWiz#2621)

The baseline for spec #2428's allowance plan. The AFTER bench reruns the same two commands once FR6 to FR12 land, against the target of 100 agents under 3,000 REST calls an hour.

Two kinds of number appear here, and they are never mixed:

- **Measured live:** the shared account's own `used`, read from `gh api rate_limit` (free) every 3 minutes for one hour. It counts every agent on the account, not one script.
- **Fixtures times cadence:** calls counted by `gh-meter.py` while each wake script ran its own test suite against its fake `gh`, divided by its fixture runs, times 6 wakes per spec-hour. A derived estimate, not an observation.

## Measured live: one hour on the shared account

`python3 -I bench.py live live-samples.jsonl` ([live-hour.txt](live-hour.txt)), samples from 2026-11-23 01:34:34Z to 02:34:41Z:

| Allowance | Samples kept | Used in the hour (lower bound) | Lowest remaining | Limit |
| --- | --- | --- | --- | --- |
| REST (`core`) | 19 of 21 | 2,303 | 2,860 | 5,000 |
| GraphQL | 19 of 21 | 556 | 4,456 | 5,000 |

The hour crosses one reset of each, so the units spent between the last sample before a reset and the reset itself are not seen: both totals are lower bounds. Two samples (01:37:35Z and 02:16:41Z) came back from another allowance window (their `reset` and `used` match neither neighbour) and are left out, as `live-hour.txt` lists. No sample was unreadable.

So, measured: the account spent at least **2,303 REST units in one hour**, 77% of the 3,000-an-hour target, at the fleet's size that hour.

## Fixtures times cadence: calls per run

`env -u OPENWIZ_GITHUB_APP_KEY TEST_JOBS=3 python3 -I bench.py fixtures OUT` ([fixtures-bench.txt](fixtures-bench.txt)), at this branch's commit 5ffd8c9 on 2026-11-23, whose wake scripts, suites and fixtures are main's at 32a94a6 (main has since changed `fleet.sh` and `merge.py`; the AFTER bench reruns both benches at its own head): every suite passed under the meter (`test.sh`: 918 cases, 0 failed), and none of the 25 stubbed agent, harness and host CLIs was called.

| Script | Role | Fixture runs | Calls | REST calls | GraphQL calls | REST units | REST units per run | REST units per spec-hour (x6 wakes) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fleet.sh spec | fleet | 261 | 16893 | 12582 | 4311 | 7837 | 30.0 | 180 |
| merge.py | orchestrator | 174 | 1206 | 942 | 264 | 942 | 5.4 | 32 |
| status.py repair | orchestrator | 45 | 511 | 423 | 88 | 423 | 9.4 | 56 |
| post.py | orchestrator | 21 | 38 | 38 | 0 | 38 | 1.8 | 11 |
| ops-starts.py | orchestrator | 60 | 56 | 56 | 0 | 56 | 0.9 | 6 |
| brief.py | orchestrator | 49 | 0 | 0 | 0 | 0 | 0.0 | 0 |

Per run is the mean over each suite's fixture cases, error paths included, so it is a fixture mean, not a typical live wake. The last column assumes each script runs once per wake and 6 wakes per spec-hour (one every 10 minutes), the cadence this bench takes from the fleet loops: derived, not measured. Summed, that is **285 REST units per spec-hour** (180 + 32 + 56 + 11 + 6 + 0), against the 2,303 measured for the whole account in the live hour.

## Per role (fixtures)

| Role | Calls | REST calls | GraphQL calls | REST units | Used delta |
| --- | --- | --- | --- | --- | --- |
| fleet | 16893 | 12582 | 4311 | 7837 | - |
| orchestrator | 1811 | 1459 | 352 | 1459 | - |

`Used delta` is empty because fixture runs set `GH_METER_RATE=0`: the fake `gh` has no allowance to read. Every Python script ran as `orchestrator` and `fleet.sh spec` as `fleet`; the live hour's builders, reviewers and heartbeats are inside the measured total above, unmetered by role.

## Top five endpoints by REST units (fixtures)

| # | Endpoint | REST units | Calls | By script (REST units) |
| --- | --- | --- | --- | --- |
| 1 | `GET repos/:owner/:repo/issues/:n/comments` | 2,775 | 4,093 | fleet.sh 2,514; merge.py 252; post.py 9 |
| 2 | `GET repos/:owner/:repo/issues/:n` | 1,832 | 2,981 | fleet.sh 1,832 |
| 3 | `GET repos/:owner/:repo/issues/:n/dependencies/blocked_by` | 1,825 | 2,773 | fleet.sh 1,825 |
| 4 | `GET repos/:owner/:repo/pulls/:n/files` | 400 | 400 | fleet.sh 400 |
| 5 | `GET repos/:owner/:repo/contents/docs/agents/fleet.md` | 392 | 468 | merge.py 197; fleet.sh 182; post.py 13 |

`fleet.sh spec` spends 6,753 of these 7,224 units. The first three are its per-issue reads, which spec #2428 moves to batched GraphQL (FR4, FR8); the fifth is a default-branch file read, which it moves to git (FR6). Units are fewer than calls where `fleet.sh` revalidates with an ETag and gets a free `304`. The `:owner/:repo` here is the fixtures' synthetic repository; the per-endpoint table below keeps the exact names.

## Per endpoint (fixtures)

| Method | Endpoint | Kind | Calls | REST units |
| --- | --- | --- | --- | --- |
| GET | repos/synthetic-owner/synthetic-repo/issues/:n/comments | rest | 4093 | 2775 |
| GET | repos/synthetic-owner/synthetic-repo/issues/:n | rest | 2981 | 1832 |
| GET | repos/synthetic-owner/synthetic-repo/issues/:n/dependencies/blocked_by | rest | 2773 | 1825 |
| GET | repos/synthetic-owner/synthetic-repo/pulls/:n/files | rest | 400 | 400 |
| GET | repos/synthetic-owner/synthetic-repo/contents/docs/agents/fleet.md | rest | 468 | 392 |
| GET | repos/synthetic-owner/synthetic-repo/issues/:n/timeline | rest | 812 | 286 |
| GET | repos/synthetic-owner/synthetic-repo/issues | rest | 258 | 185 |
| GET | repos/synthetic-owner/synthetic-repo/contents/docs/agents/triage-labels.md | rest | 258 | 182 |
| GET | repos/example/tracker/issues/:n/comments | rest | 137 | 137 |
| GET | repos/synthetic-owner/synthetic-repo/pulls/:n | rest | 335 | 118 |
| GET | repos/openwizdev/OpenWiz/issues/:n/comments | rest | 109 | 109 |
| GET | repos/example/tracker/issues/:n/events | rest | 97 | 97 |
| GET | repos/openwizdev/OpenWiz/contents/docs/agents/fleet.md | rest | 83 | 83 |
| POST | repos/synthetic-owner/synthetic-repo/issues/:n/comments | rest | 69 | 69 |
| GET | repos/example/tracker/issues/:n | rest | 67 | 67 |
| GET | repos/synthetic-owner/synthetic-tickets/issues/:n/comments | rest | 64 | 64 |
| GET | search/issues | rest | 63 | 63 |
| GET | repos/synthetic/ops/contents/docs/agents/fleet.md | rest | 56 | 56 |
| GET | repos/openwizdev/OpenWiz/issues/:n | rest | 52 | 52 |
| GET | repos/synthetic-owner/synthetic-repo/commits/:n/check-runs | rest | 132 | 49 |
| GET | repos/synthetic-owner/synthetic-repo/commits/:n/status | rest | 132 | 49 |
| GET | repos/example/tracker/contents/docs/agents/fleet.md | rest | 45 | 45 |
| GET | repos/synthetic-owner/synthetic-tickets/contents/docs/agents/fleet.md | rest | 44 | 44 |
| POST | repos/openwizdev/OpenWiz/issues/:n/comments | rest | 32 | 32 |
| GET | repos/synthetic-owner/synthetic-repo/issues/:n/sub_issues | rest | 71 | 31 |
| POST | repos/example/tracker/issues/:n/labels | rest | 27 | 27 |
| GET | repos/synthetic-owner/synthetic-repo/git/ref/heads/main | rest | 71 | 26 |
| GET | repos/synthetic-owner/synthetic-repo | rest | 71 | 25 |
| GET | user | rest | 66 | 25 |
| POST | repos/example/tracker/issues/:n/comments | rest | 22 | 22 |
| POST | repos/synthetic-owner/synthetic-tickets/issues/:n/comments | rest | 20 | 20 |
| PATCH | repos/example/tracker/issues/comments/:n | rest | 19 | 19 |
| GET | repos/synthetic-owner/synthetic-repo/issues/comments/:n | rest | 15 | 15 |
| GET | repos/synthetic-owner/synthetic-repo/git/matching-refs/heads/room/12- | rest | 10 | 10 |
| GET | repos/example/public/issues/:n/comments | rest | 14 | 7 |
| DELETE | repos/example/tracker/issues/:n/labels/needs-info | rest | 6 | 6 |
| GET | repos/openwizdev/WizSkills/issues/:n/comments | rest | 6 | 6 |
| GET | repos/example/public/issues/:n | rest | 11 | 5 |
| GET | repos/example/public/issues/:n/dependencies/blocked_by | rest | 10 | 5 |
| GET | repos/synthetic-owner/synthetic-tickets/issues/comments/:n | rest | 5 | 5 |
| GET | repos/example/public/issues/:n/timeline | rest | 4 | 4 |
| GET | repos/openwizdev/WizSkills/contents/docs/agents/fleet.md | rest | 4 | 4 |
| GET | installation/repositories | rest | 6 | 3 |
| DELETE | repos/example/tracker/issues/comments/:n | rest | 3 | 3 |
| PATCH | repos/synthetic-owner/synthetic-repo/issues/comments/:n | rest | 3 | 3 |
| GET | repos/example/public/pulls/:n | rest | 2 | 2 |
| POST | repos/openwizdev/WizSkills/issues/:n/comments | rest | 2 | 2 |
| GET | repos/example/public/contents/docs/agents/fleet.md | rest | 2 | 1 |
| GET | repos/example/public/contents/docs/agents/triage-labels.md | rest | 2 | 1 |
| GET | repos/example/public/issues | rest | 2 | 1 |
| GET | repos/example/public | rest | 1 | 1 |
| GET | repos/example/public/commits/:n/check-runs | rest | 1 | 1 |
| GET | repos/example/public/commits/:n/status | rest | 1 | 1 |
| GET | repos/example/public/git/ref/heads/main | rest | 1 | 1 |
| GET | repos/example/public/issues/:n/sub_issues | rest | 1 | 1 |
| GET | repos/example/public/pulls/:n/files | rest | 1 | 1 |
| DELETE | repos/openwizdev/OpenWiz/issues/comments/:n | rest | 1 | 1 |
| view | issue view | graphql | 3164 | 0 |
| POST | graphql | graphql | 1267 | 0 |
| view | repo view | graphql | 226 | 0 |
| merge | pr merge | graphql | 6 | 0 |
