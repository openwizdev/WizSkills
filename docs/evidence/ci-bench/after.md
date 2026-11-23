# AFTER bench: `check` with the shard matrix, the split suites and the selector

The AFTER half of spec openwizdev/OpenWiz#2134's bench (ticket WQ7, openwizdev/OpenWiz#2284). It runs `check/bench.py`, the tool [before.md](before.md) used, with the same phase definitions, on a fixed window taken after the shard matrix (#275), the split long suites (#282) and the per-PR shard selector (#292, merged 2026-11-23T01:13:45Z) were all on `main`.

## Window

- **Runs:** every successful, completed `pull_request` run of the `WizSkills check` workflow created 2026-11-23T01:14:00Z to 01:30:00Z, read at about 01:50 UTC: **5 runs**. All five ran on a tree with the matrix and the selector. One other `pull_request` run in it failed and stays out, as in BEFORE: 45094439044/1 (#303). The window ends at 01:30 because runs created later were still running when it was read.
- **Samples (`<run id>/<attempt>`):** 45093658868/1 (#288), 45094226180/1 (#310), 45094331892/1 (#308), 45094535655/1 (#311), 45094724954/1 (#285).
- **Command:** `python3 check/bench.py --runs 45093658868/1 45094226180/1 45094331892/1 45094535655/1 45094724954/1`. Its date window (`--from`/`--to`) takes whole days, so the AFTER window is pinned by its samples instead.
- Each run had 40 jobs on `ubuntu-24.04`: `list shards`, `gates`, one `shard <name>` job per shard (37) and the final `check` job. bench.py takes each phase's longest job and times `total` from the attempt's start to its last job's completion, so `total` is the run's wall time, push to green less the seconds GitHub takes to create the run.

## AFTER beside BEFORE

| Window | Runs | Median total (s) | Range (s) |
| --- | ---: | ---: | --- |
| BEFORE: pull_request runs 2026-11-20 to 2026-11-22, one `check` job ([before.md](before.md)) | 247 | 2474.0 | |
| AFTER: all five pull_request runs above | 5 | 484.0 | 450 to 499 |
| AFTER: the three one-skill PRs, #310 (launch-fleet), #311 (launch-fleet), #285 (install) | 3 | **461.0** | 450 to 490 |

- **A typical one-skill PR goes from push to green in 461 s (7 min 41 s), against 2474 s (41 min) before:** under the 10-minute target, about 5.4 times faster. The other two samples change three skills (#288: build-ticket, launch-fleet, setup) and only `check/` (#308); they took 484 s and 499 s.
- **Reference runs:** `main`'s full push run 45083287465/1 (at 226eac9, #282's merge) took 462 s by the bench (7m43s by the run's own created and updated times) on every shard (37 of 37), and #282's own PR run 45080591838/1 took 479 s (7m59s), both before the selector landed. The AFTER runs match them, which is what the next point predicts.
- **The selector picks every shard for a one-skill PR today.** All five AFTER samples ran all 37 shards. On `main` at cd58dc2, `check/select.py` widens any change under `skills/<name>/` to every shard, because the install, launch-fleet, setup, to-tickets, triage and write-driver suites read every skill's folder (it prints `select: every shard: <skill> read by install, launch-fleet, setup, to-tickets, triage, write-driver's suites`), and a change under `docs/` (this file, for one) selects every shard too; #308, which changes only `check/test_select.py`, also ran all 37. So the AFTER time comes from the parallel matrix and the split suites, not from skipping shards: no sample in this window ran fewer than 37.
- **The critical path** is now the `shard launch-fleet` job (its suites other than `test.sh`, 20 at cd58dc2; 409 to 481 s in the five samples) and `shard install` (`test_first_fleet.py` and `test_onboarding.py`, 315 to 442 s). The 14 `launch-fleet.<n>` parts of `test.sh` each took 208 to 264 s at most.
- Several suites are slower per run than in BEFORE (median `test_first_fleet.py` 235.7 s against 123.5 s, `test_onboarding.py` 162.7 s against 121.6 s, `check/test_suites.py` 138.0 s against 0.1 s). This bench does not say why; the claim here is the wall time only, and the gap is listed below.

## The AFTER table

Seconds per phase, as `check/bench.py` printed it for the five samples; the phase definitions are before.md's. The `suite launch-fleet.<n>` rows are the 14 parts of `sh skills/launch-fleet/scripts/test.sh` (WQ2's `TEST_SHARD=<n>/14`); BEFORE timed that suite whole, at 1803.7 s.

| Phase | Median (s) | Known | 45093658868/1 | 45094226180/1 | 45094331892/1 | 45094535655/1 | 45094724954/1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| queue wait | 3.0 | 5/5 | 3.0 | 3.0 | 7.0 | 2.0 | 2.0 |
| setup | 11.0 | 5/5 | 8.0 | 12.0 | 11.0 | 11.0 | 9.0 |
| changeset gate | 0.0 | 5/5 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| comment check | 4.0 | 5/5 | 4.0 | 4.0 | 4.0 | 4.0 | 4.0 |
| browser tools | 15.0 | 5/5 | 15.0 | 19.0 | 15.0 | 21.0 | 15.0 |
| rules | 0.1 | 5/5 | 0.1 | 0.1 | 0.1 | 0.1 | 0.1 |
| standalone | unknown | 0/5 | unknown | unknown | unknown | unknown | unknown |
| suite build-ticket: python3 -I skills/build-ticket/scripts/test_ticket.py | 40.6 | 5/5 | 40.3 | 40.2 | 41.4 | 43.2 | 40.6 |
| suite triage: python3 -I skills/triage/test/test_find_work.py | 9.2 | 5/5 | 9.5 | 9.2 | 9.2 | 7.9 | 8.4 |
| suite triage: python3 -I skills/triage/test/test_public_records.py | 7.7 | 5/5 | 7.8 | 7.7 | 7.7 | 6.5 | 6.9 |
| suite to-spec: python3 -I skills/to-spec/test/test_video.py | 1.3 | 5/5 | 1.3 | 1.2 | 1.2 | 1.3 | 1.3 |
| suite feedback: python3 -I skills/feedback/test/test_feedback.py | 29.9 | 5/5 | 29.9 | 23.9 | 30.4 | 30.1 | 29.8 |
| suite install: python3 -I skills/install/tests/test_first_fleet.py | 235.7 | 5/5 | 246.1 | 235.7 | 194.7 | 171.0 | 259.1 |
| suite install: python3 -I skills/install/tests/test_doctor.py | 5.5 | 5/5 | 7.0 | 6.6 | 5.3 | 4.5 | 5.5 |
| suite install: python3 -I skills/install/tests/test_onboarding.py | 162.7 | 5/5 | 182.0 | 177.7 | 145.4 | 129.1 | 162.7 |
| suite hill-climb: python3 -I -m unittest discover -s skills/hill-climb/tests | 5.4 | 5/5 | 5.0 | 5.4 | 5.8 | 5.2 | 6.1 |
| suite diagnose: node --test skills/diagnose/tests/hitl-loop.test.mjs | 0.1 | 5/5 | 0.2 | 0.1 | 0.1 | 0.1 | 0.1 |
| suite diagnose: python3 -I skills/diagnose/scripts/test_loop.py | 8.2 | 5/5 | 8.3 | 7.6 | 8.2 | 8.2 | 7.8 |
| suite launch-fleet.2: sh skills/launch-fleet/scripts/test.sh | 131.3 | 5/5 | 149.3 | 131.3 | 118.3 | 105.8 | 140.7 |
| suite grill: sh skills/grill/scripts/test.sh | 0.2 | 5/5 | 0.2 | 0.2 | 0.2 | 0.2 | 0.2 |
| suite grill: python3 skills/grill/scripts/test_records.py | 12.7 | 5/5 | 10.2 | 12.9 | 12.7 | 12.7 | 13.9 |
| suite research: python3 -I skills/research/test/test_workers.py | 1.8 | 5/5 | 1.4 | 1.7 | 1.8 | 1.8 | 1.8 |
| suite research: python3 -I skills/research/test/test_snapshot_commands.py | 0.1 | 5/5 | 0.0 | 0.1 | 0.1 | 0.1 | 0.1 |
| suite setup: python3 -I skills/setup/scripts/test_settings.py | 4.1 | 5/5 | 3.3 | 3.2 | 4.1 | 4.1 | 4.1 |
| suite image: python3 -I -m unittest discover -s skills/image/tests | 21.2 | 5/5 | 20.1 | 20.0 | 22.2 | 21.3 | 21.2 |
| suite image: python3 -I -m unittest discover -s skills/image/references | 0.0 | 5/5 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| suite huntr: sh skills/huntr/scripts/test.sh | 31.4 | 5/5 | 30.9 | 38.9 | 31.4 | 39.8 | 29.6 |
| suite launch-fleet: python3 -I skills/launch-fleet/test/ops-protocol/test_protocol.py | 0.2 | 5/5 | 0.2 | 0.2 | 0.2 | 0.2 | 0.1 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-effects.py | 0.2 | 5/5 | 0.2 | 0.2 | 0.2 | 0.1 | 0.1 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-grants.py | 0.2 | 5/5 | 0.2 | 0.2 | 0.2 | 0.2 | 0.2 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-inbox.py | 0.1 | 5/5 | 0.1 | 0.1 | 0.1 | 0.1 | 0.1 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-records.py | 72.1 | 5/5 | 72.1 | 72.8 | 74.6 | 66.3 | 58.8 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-status.py | 117.3 | 5/5 | 118.1 | 117.3 | 120.6 | 114.6 | 104.2 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-ops-starts.py | 4.6 | 5/5 | 4.6 | 4.6 | 4.9 | 4.4 | 4.0 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-on1.py | 0.3 | 5/5 | 0.3 | 0.3 | 0.3 | 0.3 | 0.2 |
| suite launch-fleet: sh skills/launch-fleet/scripts/test-loop.sh | 41.4 | 5/5 | 41.8 | 41.4 | 42.4 | 37.6 | 34.2 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-limit-replacement.py | 0.2 | 5/5 | 0.2 | 0.2 | 0.2 | 0.2 | 0.1 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-limit-recovery.py | 0.1 | 5/5 | 0.1 | 0.1 | 0.1 | 0.1 | 0.1 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-post.py | 3.7 | 5/5 | 3.7 | 3.7 | 3.8 | 3.6 | 3.1 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-merge.py | 88.3 | 5/5 | 88.3 | 95.6 | 92.1 | 85.1 | 74.7 |
| suite launch-fleet: env -u OPENWIZ_GITHUB_APP_KEY python3 -I skills/launch-fleet/scripts/test-queue.py | 7.2 | 5/5 | 7.3 | 7.2 | 7.6 | 7.0 | 6.0 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-brief.py | 3.3 | 5/5 | 3.3 | 3.3 | 3.5 | 3.2 | 2.8 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-heartbeat.py | 14.0 | 5/5 | 14.0 | 14.1 | 14.5 | 13.7 | 12.7 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-ledger.py | 4.4 | 5/5 | 4.4 | 4.5 | 4.6 | 4.4 | 3.7 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-host.py | 93.7 | 5/5 | 94.3 | 93.7 | 95.4 | 92.0 | 89.6 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-route.py | 2.6 | 5/5 | 2.6 | 2.8 | 3.4 | 2.6 | 2.2 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-budget.py | 2.5 | 5/5 | 2.6 | 2.5 | 2.8 | 2.5 | 2.2 |
| suite handoff: python3 -I skills/handoff/test/test_handoff.py | 1.8 | 5/5 | 1.6 | 1.8 | 1.8 | 1.4 | 1.8 |
| suite review-ticket: python3 -I skills/review-ticket/scripts/test_review.py | 20.6 | 5/5 | 17.4 | 16.3 | 23.4 | 20.6 | 22.8 |
| suite wayfind: python3 -I skills/wayfind/test/test_frontier.py | 2.7 | 5/5 | 3.3 | 2.6 | 3.3 | 2.7 | 2.7 |
| suite launch-fleet.1: sh skills/launch-fleet/scripts/test.sh | 115.9 | 5/5 | 158.4 | 115.9 | 101.1 | 106.0 | 147.7 |
| suite write-driver: python3 -I skills/write-driver/tests/test_write_driver.py | 21.6 | 5/5 | 30.8 | 31.6 | 21.2 | 21.6 | 20.8 |
| suite write-driver: python3 -I skills/write-driver/tests/test_eval.py | 38.5 | 5/5 | 42.3 | 42.7 | 38.5 | 38.3 | 38.1 |
| suite where-are-we: python3 -I skills/where-are-we/test/test_read_github.py | 3.1 | 5/5 | 2.7 | 3.1 | 3.1 | 3.1 | 3.1 |
| suite ask-wiz: python3 -I skills/ask-wiz/test/test_routes.py | 0.1 | 5/5 | 0.1 | 0.1 | 0.1 | 0.1 | 0.1 |
| suite to-tickets: python3 -I skills/to-tickets/scripts/test_check_approval.py | 66.8 | 5/5 | 76.8 | 61.5 | 66.8 | 78.3 | 61.5 |
| suite to-tickets: python3 -I skills/to-tickets/scripts/test_approve.py | 0.7 | 5/5 | 0.8 | 0.6 | 0.7 | 0.8 | 0.7 |
| suite to-tickets: sh skills/to-tickets/test/test-revision.sh | 12.2 | 5/5 | 13.9 | 11.2 | 12.2 | 13.8 | 11.3 |
| suite to-tickets: python3 -I skills/to-tickets/test/test_relies.py | 10.0 | 5/5 | 11.4 | 9.1 | 10.0 | 11.4 | 9.1 |
| suite to-tickets: python3 -I skills/to-tickets/test/test_picture.py | 0.2 | 5/5 | 0.2 | 0.2 | 0.2 | 0.2 | 0.2 |
| suite to-tickets: python3 -I skills/to-tickets/test/test_request.py | 0.2 | 5/5 | 0.3 | 0.2 | 0.2 | 0.3 | 0.2 |
| suite to-tickets: python3 -I skills/to-tickets/test/test_lead_time.py | 0.3 | 5/5 | 0.3 | 0.3 | 0.3 | 0.3 | 0.3 |
| suite to-tickets: python3 -I skills/to-tickets/test/test_links.py | 0.6 | 5/5 | 0.8 | 0.6 | 0.6 | 0.8 | 0.6 |
| suite launch-fleet.8: sh skills/launch-fleet/scripts/test.sh | 156.9 | 5/5 | 156.9 | 159.7 | 161.4 | 100.6 | 132.7 |
| suite launch-fleet.3: sh skills/launch-fleet/scripts/test.sh | 121.0 | 5/5 | 164.5 | 96.0 | 121.0 | 91.9 | 142.2 |
| suite launch-fleet.6: sh skills/launch-fleet/scripts/test.sh | 166.2 | 5/5 | 176.3 | 129.7 | 178.4 | 162.6 | 166.2 |
| suite check: python3 -I check/test_notice.py | 0.1 | 5/5 | 0.1 | 0.1 | 0.1 | 0.1 | 0.1 |
| suite check: python3 -I check/test_versions.py | 0.0 | 5/5 | 0.0 | 0.1 | 0.0 | 0.0 | 0.1 |
| suite check: python3 -I check/test_changesets.py | 5.5 | 5/5 | 5.5 | 5.8 | 5.3 | 6.1 | 5.4 |
| suite check: python3 -I check/test_suites.py | 138.0 | 5/5 | 133.0 | 152.2 | 140.0 | 123.2 | 138.0 |
| suite check: python3 -I check/test_bench.py | 0.7 | 5/5 | 0.6 | 0.7 | 0.7 | 0.5 | 0.7 |
| suite check: python3 -I check/test_select.py | 7.8 | 5/5 | 7.8 | 9.2 | 7.7 | 7.3 | 8.0 |
| suite launch-fleet.12: sh skills/launch-fleet/scripts/test.sh | 202.2 | 5/5 | 161.2 | 203.0 | 202.2 | 201.8 | 258.6 |
| suite launch-fleet.13: sh skills/launch-fleet/scripts/test.sh | 158.9 | 5/5 | 176.1 | 104.3 | 162.8 | 116.4 | 158.9 |
| suite launch-fleet.7: sh skills/launch-fleet/scripts/test.sh | 141.8 | 5/5 | 110.8 | 110.6 | 158.5 | 161.2 | 141.8 |
| suite launch-fleet.5: sh skills/launch-fleet/scripts/test.sh | 194.5 | 5/5 | 198.3 | 194.5 | 157.5 | 206.7 | 160.3 |
| suite launch-fleet.9: sh skills/launch-fleet/scripts/test.sh | 145.0 | 5/5 | 106.2 | 132.3 | 148.1 | 145.0 | 176.3 |
| suite launch-fleet.11: sh skills/launch-fleet/scripts/test.sh | 180.0 | 5/5 | 141.4 | 180.0 | 180.2 | 181.9 | 138.6 |
| suite launch-fleet.10: sh skills/launch-fleet/scripts/test.sh | 137.8 | 5/5 | 193.2 | 105.8 | 155.5 | 137.8 | 120.1 |
| suite launch-fleet.4: sh skills/launch-fleet/scripts/test.sh | 156.3 | 5/5 | 144.0 | 156.3 | 156.7 | 133.6 | 173.7 |
| suite launch-fleet.14: sh skills/launch-fleet/scripts/test.sh | 198.0 | 5/5 | 155.5 | 159.0 | 231.0 | 230.3 | 198.0 |
| total | 484.0 | 5/5 | 484.0 | 490.0 | 499.0 | 461.0 | 450.0 |

## Nothing stopped being tested: the suite list, one for one

`python3 check/run.py --list` at `main` (cd58dc2) against the pre-spec `SUITES` in `git show 3178eff5:check/run.py` (`main` at #256's merge, before any spec #2134 ticket): **all 54 pre-spec suites are listed, each with the same command, in its own skill's shard**. Only `sh skills/launch-fleet/scripts/test.sh` moved, into the 14 `launch-fleet.<n>` shards that each run it with `TEST_SHARD=<n>/14` (WQ2); every other suite runs once, in the shard named for its skill. The comparison reads `SUITES` with `ast.literal_eval` and each listed shard's `commands[].suite`, so it compares the commands themselves, not their count.

| Pre-spec suite (`SUITES` at 3178eff5) | Shard at `main` (cd58dc2) |
| --- | --- |
| build-ticket: `python3 -I skills/build-ticket/scripts/test_ticket.py` | build-ticket |
| triage: `python3 -I skills/triage/test/test_find_work.py` | triage |
| triage: `python3 -I skills/triage/test/test_public_records.py` | triage |
| feedback: `python3 -I skills/feedback/test/test_feedback.py` | feedback |
| install: `python3 -I skills/install/tests/test_first_fleet.py` | install |
| install: `python3 -I skills/install/tests/test_doctor.py` | install |
| install: `python3 -I skills/install/tests/test_onboarding.py` | install |
| huntr: `sh skills/huntr/scripts/test.sh` | huntr |
| grill: `sh skills/grill/scripts/test.sh` | grill |
| grill: `python3 skills/grill/scripts/test_records.py` | grill |
| diagnose: `node --test skills/diagnose/tests/hitl-loop.test.mjs` | diagnose |
| diagnose: `python3 -I skills/diagnose/scripts/test_loop.py` | diagnose |
| where-are-we: `python3 -I skills/where-are-we/test/test_read_github.py` | where-are-we |
| handoff: `python3 -I skills/handoff/test/test_handoff.py` | handoff |
| ask-wiz: `python3 -I skills/ask-wiz/test/test_routes.py` | ask-wiz |
| hill-climb: `python3 -I -m unittest discover -s skills/hill-climb/tests` | hill-climb |
| setup: `python3 -I skills/setup/scripts/test_settings.py` | setup |
| image: `python3 -I -m unittest discover -s skills/image/tests` | image |
| image: `python3 -I -m unittest discover -s skills/image/references` | image |
| to-spec: `python3 -I skills/to-spec/test/test_video.py` | to-spec |
| to-tickets: `python3 -I skills/to-tickets/scripts/test_check_approval.py` | to-tickets |
| to-tickets: `sh skills/to-tickets/test/test-revision.sh` | to-tickets |
| to-tickets: `python3 -I skills/to-tickets/test/test_relies.py` | to-tickets |
| to-tickets: `python3 -I skills/to-tickets/test/test_picture.py` | to-tickets |
| to-tickets: `python3 -I skills/to-tickets/test/test_request.py` | to-tickets |
| to-tickets: `python3 -I skills/to-tickets/test/test_lead_time.py` | to-tickets |
| review-ticket: `python3 -I skills/review-ticket/scripts/test_review.py` | review-ticket |
| wayfind: `python3 -I skills/wayfind/test/test_frontier.py` | wayfind |
| research: `python3 -I skills/research/test/test_workers.py` | research |
| research: `python3 -I skills/research/test/test_snapshot_commands.py` | research |
| write-driver: `python3 -I skills/write-driver/tests/test_write_driver.py` | write-driver |
| write-driver: `python3 -I skills/write-driver/tests/test_eval.py` | write-driver |
| launch-fleet: `sh skills/launch-fleet/scripts/test.sh` | launch-fleet.1 to launch-fleet.14 (14 parts, `TEST_SHARD=<n>/14`) |
| launch-fleet: `python3 -I skills/launch-fleet/test/ops-protocol/test_protocol.py` | launch-fleet |
| launch-fleet: `python3 -I skills/launch-fleet/scripts/test-effects.py` | launch-fleet |
| launch-fleet: `python3 -I skills/launch-fleet/scripts/test-grants.py` | launch-fleet |
| launch-fleet: `python3 -I skills/launch-fleet/scripts/test-inbox.py` | launch-fleet |
| launch-fleet: `python3 -I skills/launch-fleet/scripts/test-records.py` | launch-fleet |
| launch-fleet: `python3 -I skills/launch-fleet/scripts/test-status.py` | launch-fleet |
| launch-fleet: `python3 -I skills/launch-fleet/scripts/test-ops-starts.py` | launch-fleet |
| launch-fleet: `python3 -I skills/launch-fleet/scripts/test-on1.py` | launch-fleet |
| launch-fleet: `sh skills/launch-fleet/scripts/test-loop.sh` | launch-fleet |
| launch-fleet: `python3 -I skills/launch-fleet/scripts/test-limit-replacement.py` | launch-fleet |
| launch-fleet: `python3 -I skills/launch-fleet/scripts/test-limit-recovery.py` | launch-fleet |
| launch-fleet: `python3 -I skills/launch-fleet/scripts/test-post.py` | launch-fleet |
| launch-fleet: `python3 -I skills/launch-fleet/scripts/test-merge.py` | launch-fleet |
| launch-fleet: `python3 -I skills/launch-fleet/scripts/test-brief.py` | launch-fleet |
| launch-fleet: `python3 -I skills/launch-fleet/scripts/test-heartbeat.py` | launch-fleet |
| launch-fleet: `python3 -I skills/launch-fleet/scripts/test-host.py` | launch-fleet |
| launch-fleet: `python3 -I skills/launch-fleet/scripts/test-route.py` | launch-fleet |
| check: `python3 -I check/test_notice.py` | check |
| check: `python3 -I check/test_versions.py` | check |
| check: `python3 -I check/test_changesets.py` | check |
| check: `python3 -I check/test_suites.py` | check |

Listed at `main` and not in the pre-spec `SUITES`, all additions: None: `python3 -I check/standalone.py --tree .` (standalone); to-tickets: `python3 -I skills/to-tickets/scripts/test_approve.py` (to-tickets); to-tickets: `python3 -I skills/to-tickets/test/test_links.py` (to-tickets); launch-fleet: `env -u OPENWIZ_GITHUB_APP_KEY python3 -I skills/launch-fleet/scripts/test-queue.py` (launch-fleet); launch-fleet: `python3 -I skills/launch-fleet/scripts/test-ledger.py` (launch-fleet); launch-fleet: `python3 -I skills/launch-fleet/scripts/test-budget.py` (launch-fleet); check: `python3 -I check/test_bench.py` (check); check: `python3 -I check/test_select.py` (check). `check/standalone.py` is not new: before the spec, `check/run.py` ran it itself after the rules; now it is the `standalone` shard, and the `rules` shard runs the in-process rules with no suite command.

## Every shard ran on `main` and in the queue

A merge group or a push to `main` keeps every shard (`check/select.py --event merge_group|push`); the `list shards` job writes `skipped` as the listed shards minus the kept ones. For each run below, the run's `shard <name>` jobs were compared with `check/run.py --list` at the run's tree: no listed shard is missing and none extra, so its `skipped` was `[]`.

| Run | Event | Tree | Shard jobs / listed | Result | Wall time |
| --- | --- | --- | --- | --- | --- |
| 45092551129/1 | merge_group (#292, queue branch `gh-readonly-queue/main/pr-292-a1b9d1f…`) | d70595a | 37 / 37 | all success | 01:05:35Z to 01:13:35Z (8m00s) |
| 45093358703/1 | push to `main` (#292's merge) | d70595a | 37 / 37 | all success | 01:13:47Z to 01:22:00Z (8m13s) |
| 45083287465/1 | push to `main` (#282's merge) | 226eac9 | 37 / 37 | all success | 23:26:43Z to 23:34:26Z (7m43s) |

The merge group's `list shards` job (137425138552) printed one `shard <name>: browser …` line for each of the 37 shards, browser `yes` only for `image` and `to-spec`.

## The merge queue, live

**One real PR through the queue, end to end: #292** (WQ4, the shard selector), from GraphQL's timeline events:

1. `AddedToMergeQueueEvent` 2026-11-23T01:05:17Z.
2. Its merge group's `check` run 45092551129/1 started 01:05:35Z and passed at 01:13:35Z, every shard (above).
3. `MergedEvent` 01:13:45Z, commit d70595a, with `RemovedFromMergeQueueEvent` reason `merged` at the same second (actor `github-merge-queue`).
4. The push run on `main` at d70595a, 45093358703/1, passed every shard at 01:22:00Z.

Added to merged: 8 min 28 s.

**A queued PR whose merge with `main` fails, removed with a clear reason: not seen yet.** Every `RemovedFromMergeQueueEvent` on a WizSkills PR updated from 2026-11-22T12:00Z to the read at about 01:50Z on 2026-11-23 has reason `merged`. This is still to watch for; when one appears, its `reason` and the failing merge-group run belong here.

**The day of merges through the queue** (open: a day can't finish in one session). Among the 55 WizSkills PRs updated since 2026-11-22T12:00Z, the first `AddedToMergeQueueEvent` is #259's at 2026-11-22T23:39:53Z. Merges since then, read through GraphQL at about 01:50Z on 2026-11-23:

| PR | Added to the queue | Merged | Commit |
| --- | --- | --- | --- |
| #259 | 11-22 23:39:53Z | 23:48:10Z | 061b6c5 |
| #281 | 23:41:55Z | 23:49:59Z | ba89176 |
| #297 | 23:45:58Z | 23:54:21Z | c885d0d |
| #300 | 11-23 00:02:20Z | 00:10:51Z | 67177df |
| #269 | 00:02:40Z | 00:11:13Z | d3be311 |
| #294 | 00:48:41Z | 00:56:57Z | a5189c8 |
| #291 | 00:51:54Z | 01:00:10Z | 829421d |
| #295 | 00:54:53Z | 01:02:18Z | b059862 |
| #299 | 00:56:23Z | 01:04:53Z | ae1b242 |
| #293 | 00:56:30Z | 01:04:53Z | 2e0a734 |
| #298 | 01:02:01Z | 01:10:09Z | 39b960f |
| #301 | 01:04:45Z | 01:13:29Z | a1b9d1f |
| #292 | 01:05:17Z | 01:13:45Z | d70595a |
| #296 | 01:05:34Z | 01:14:53Z | cd58dc2 |
| #304 | 01:30:06Z | 01:37:30Z | 32a94a6 |

15 merges through the queue in about 2 hours, each 7.4 to 9.3 minutes from added to merged, with no merge window: PRs were added whenever they were ready and up to five sat in the queue at once (#291, #293, #294, #295 and #299 at 00:56:30Z), every removal `merged`. #308 was in the queue at the read (added 01:46:59Z). Two PRs merged in that span with no queue event: #286 (00:10:52Z) and #287 (the 0.4.1 release, 00:11:16Z); the timeline does not say how. **Open for the lead:** close the day at 2026-11-23T23:39:53Z with the full list, and say whether #286 and #287 merging outside the queue counts against "no merge window".

## Gaps

- **Thin window.** 5 AFTER samples (3 one-skill PRs) against 247 BEFORE; the selector had been on `main` 16 minutes when the window closed. A wider re-run is `check/bench.py --runs` with the later samples; the one-skill median here is the claim at this size only.
- **`standalone` is unknown in AFTER.** bench.py times it from a `rules:` line to a `standalone:` line in one job's log; the rules and standalone checks now run in separate shards, so no job has both. Its own shard job took 8 to 13 s in the five samples and the #292 merge group, and is never on the critical path. Fixing the phase is a change to `check/bench.py`, outside this ticket.
- **Slower suites, cause unmeasured** (see AFTER beside BEFORE).
- **No queue removal with a non-merged reason yet**, and **the day of queue merges is open** (both above).
