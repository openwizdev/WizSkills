# BEFORE bench: where `check` spends its time

The BEFORE half of spec openwizdev/OpenWiz#2134's bench (ticket WQ0, openwizdev/OpenWiz#2269). The AFTER bench (WQ7) runs `check/bench.py` with the same phase definitions on its own window.

## Window

- **Runs:** every successful, completed `pull_request` run of the `WizSkills check` workflow (`.github/workflows/ci.yml`) created 2026-11-20 to 2026-11-22 (UTC), read on 2026-11-22 at about 10:30 UTC: **247 runs**, from 44643925573 (2026-11-20T00:12:11Z) to 45008786724 (2026-11-22T09:41:45Z). The run ids are listed below.
- **Command:** `python3 check/bench.py --from 2026-11-20 --to 2026-11-22`. Runs created later on 2026-11-22 widen that query, so to repeat this exact window, pass the ids below with `--runs`.
- Every run had one job, `check`, on `ubuntu-24.04`.

## Phases

Seconds per phase. **Median** is over the runs that know the phase; **Known** counts them. A phase a run never ran or finished is unknown and stays out of the median, never counted as zero.

- **queue wait:** the job's created to started time.
- **setup:** the "Set up job", checkout and "Install the pinned Changesets" steps.
- **changeset gate**, **comment check**, **browser tools:** their workflow steps (GitHub reports steps to the whole second).
- **rules**, **standalone:** from the `check/run.py` step's start to its `rules:` line, then to its `standalone:` line.
- **suite …:** each suite command's `running` line to its `pass` or `fail` line.
- **total:** the run's created time to its job's completed time.

Lower Known counts are steps or suites added to (or restored on) `main` during the window. A pull request whose branch predates one never runs it, so those runs do not know it: the comment check step ran in 56 runs, `test-heartbeat.py` in 8.

## BEFORE table

| Phase | Median (s) | Known |
| --- | ---: | ---: |
| queue wait | 2.0 | 247/247 |
| setup | 4.0 | 247/247 |
| changeset gate | 0.0 | 247/247 |
| comment check | 3.0 | 56/247 |
| browser tools | 24.0 | 247/247 |
| rules | 0.1 | 247/247 |
| standalone | 1.1 | 247/247 |
| suite check: python3 -I check/test_versions.py | 0.1 | 247/247 |
| suite check: python3 -I check/test_changesets.py | 5.1 | 247/247 |
| suite build-ticket: python3 -I skills/build-ticket/scripts/test_ticket.py | 36.7 | 247/247 |
| suite triage: python3 -I skills/triage/test/test_find_work.py | 1.6 | 247/247 |
| suite triage: python3 -I skills/triage/test/test_public_records.py | 0.1 | 247/247 |
| suite install: python3 -I skills/install/tests/test_first_fleet.py | 123.5 | 247/247 |
| suite install: python3 -I skills/install/tests/test_doctor.py | 4.4 | 247/247 |
| suite huntr: sh skills/huntr/scripts/test.sh | 37.1 | 247/247 |
| suite grill: sh skills/grill/scripts/test.sh | 0.2 | 247/247 |
| suite grill: python3 skills/grill/scripts/test_records.py | 11.0 | 247/247 |
| suite diagnose: node --test skills/diagnose/tests/hitl-loop.test.mjs | 0.1 | 247/247 |
| suite diagnose: python3 -I skills/diagnose/scripts/test_loop.py | 7.9 | 247/247 |
| suite where-are-we: python3 -I skills/where-are-we/test/test_read_github.py | 2.7 | 247/247 |
| suite handoff: python3 -I skills/handoff/test/test_handoff.py | 1.6 | 247/247 |
| suite ask-wiz: python3 -I skills/ask-wiz/test/test_routes.py | 0.0 | 247/247 |
| suite hill-climb: python3 -I -m unittest discover -s skills/hill-climb/tests | 5.4 | 247/247 |
| suite setup: python3 -I skills/setup/scripts/test_settings.py | 1.1 | 247/247 |
| suite image: python3 -I -m unittest discover -s skills/image/tests | 19.2 | 247/247 |
| suite image: python3 -I -m unittest discover -s skills/image/references | 0.0 | 247/247 |
| suite to-spec: python3 -I skills/to-spec/test/test_video.py | 1.2 | 247/247 |
| suite to-tickets: python3 -I skills/to-tickets/scripts/test_check_approval.py | 49.1 | 247/247 |
| suite to-tickets: sh skills/to-tickets/test/test-revision.sh | 13.2 | 247/247 |
| suite to-tickets: python3 -I skills/to-tickets/test/test_relies.py | 9.4 | 247/247 |
| suite to-tickets: python3 -I skills/to-tickets/test/test_picture.py | 0.2 | 247/247 |
| suite to-tickets: python3 -I skills/to-tickets/test/test_request.py | 0.3 | 247/247 |
| suite review-ticket: python3 -I skills/review-ticket/scripts/test_review.py | 12.4 | 247/247 |
| suite wayfind: python3 -I skills/wayfind/test/test_frontier.py | 2.6 | 247/247 |
| suite research: python3 -I skills/research/test/test_workers.py | 1.7 | 247/247 |
| suite research: python3 -I skills/research/test/test_snapshot_commands.py | 0.1 | 247/247 |
| suite launch-fleet: sh skills/launch-fleet/scripts/test.sh | 1803.7 | 247/247 |
| suite launch-fleet: python3 -I skills/launch-fleet/test/ops-protocol/test_protocol.py | 0.2 | 247/247 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-effects.py | 0.1 | 247/247 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-grants.py | 0.2 | 247/247 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-inbox.py | 0.1 | 247/247 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-records.py | 44.4 | 247/247 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-status.py | 75.6 | 247/247 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-ops-starts.py | 0.5 | 247/247 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-on1.py | 0.3 | 247/247 |
| suite launch-fleet: sh skills/launch-fleet/scripts/test-loop.sh | 19.2 | 247/247 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-limit-replacement.py | 0.2 | 247/247 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-limit-recovery.py | 0.1 | 247/247 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-post.py | 2.7 | 247/247 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-merge.py | 17.1 | 247/247 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-brief.py | 0.4 | 247/247 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-route.py | 2.6 | 183/247 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-host.py | 80.2 | 220/247 |
| suite to-tickets: python3 -I skills/to-tickets/test/test_lead_time.py | 0.3 | 178/247 |
| suite install: python3 -I skills/install/tests/test_onboarding.py | 121.6 | 111/247 |
| suite feedback: python3 -I skills/feedback/test/test_feedback.py | 28.5 | 71/247 |
| suite write-driver: python3 -I skills/write-driver/tests/test_write_driver.py | 28.6 | 73/247 |
| suite check: python3 -I check/test_notice.py | 0.1 | 41/247 |
| suite check: python3 -I check/test_suites.py | 0.1 | 41/247 |
| suite write-driver: python3 -I skills/write-driver/tests/test_eval.py | 41.8 | 48/247 |
| suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-heartbeat.py | 11.7 | 8/247 |
| total | 2474.0 | 247/247 |

## What it shows

- The median run takes 2474 s (about 41 minutes) from created to done; queue wait is 2 s and everything before the first suite (queue wait to standalone) is about 35 s.
- `skills/launch-fleet/scripts/test.sh` alone takes 1804 s (about 30 minutes), about 73% of the median total. It is the floor for any one-job layout.
- The next longest suites: `install` `test_first_fleet.py` (124 s), `test_onboarding.py` (122 s), launch-fleet `test-host.py` (80 s) and `test-status.py` (76 s), to-tickets `test_check_approval.py` (49 s), launch-fleet `test-records.py` (44 s), write-driver `test_eval.py` (42 s), huntr `test.sh` (37 s) and build-ticket `test_ticket.py` (37 s).

<details><summary>The 247 run ids</summary>

44643925573 44644662231 44644985726 44645024663 44647072061 44648157001 44650381422 44650578777 44650629857 44651060369 44651197083 44651401019 44651530489 44651847208 44653132961 44654585702 44655137149 44655245696 44655449861 44655724943 44655945824 44656026490 44656397199 44657683065 44658100249 44659052785 44659232510 44661125948 44661250903 44661756078 44662359236 44662380640 44662481577 44662881775 44662922573 44663093811 44663867741 44663874465 44663890681 44663937793 44663946396 44664998054 44665629811 44667380427 44670422029 44670429714 44670432567 44670460528 44670668494 44670847339 44671272095 44672390882 44672681806 44673424831 44674804353 44676168185 44676260476 44676447227 44676651384 44677272842 44679406882 44679501790 44679980596 44680052882 44680655235 44681102370 44681910456 44682324099 44683686912 44684050187 44684160632 44686000049 44686068061 44686890959 44692989069 44694143422 44694164807 44694191049 44694793237 44695518963 44696274051 44696352644 44701727719 44702920906 44705205909 44706151753 44706155197 44710918863 44711019989 44713323878 44714042026 44718889949 44721850332 44721894078 44726396149 44731725604 44731743464 44731959152 44733303244 44733484264 44736107961 44736297956 44737590252 44738324897 44739195692 44740557771 44740760743 44741260513 44742092344 44744001180 44744202010 44745933780 44747785335 44748639921 44750632431 44752564111 44752587540 44752892036 44755889936 44760152539 44761180607 44762717591 44765042776 44767209950 44767695340 44767732907 44768202275 44768388233 44768757542 44768892980 44769055466 44776644594 44776673231 44777818602 44778413983 44779107142 44783708276 44785529190 44786229075 44789608557 44790833931 44792917636 44795254859 44795418302 44800789338 44800959166 44803197360 44803671332 44811606655 44812135661 44812426135 44814866103 44815130255 44815287631 44815318750 44815788236 44823071091 44824096323 44824409928 44828166847 44833658753 44833864209 44835346433 44839548594 44839562710 44839682557 44840377110 44845207580 44846043020 44846082630 44851248160 44851396270 44851706763 44851995781 44852136007 44853394520 44854760463 44855316541 44857059895 44857862087 44857915554 44858878712 44860062360 44861960520 44862030208 44862038377 44863897707 44864840695 44866265531 44866922190 44868111302 44872780222 44873194528 44876346700 44878378105 44883209221 44883293508 44884467000 44884997940 44885793556 44889299977 44891549375 44891749013 44893206945 44896915346 44897133708 44901221227 44901265717 44905749652 44906172973 44910133651 44924512251 44931169815 44934792891 44936855036 44937025985 44946235438 44947319284 44956408780 44957028627 44957230904 44971139972 44971573720 44972015277 44972258482 44973098515 44991669639 44991908140 44991991429 44992169210 44992405352 44994492517 44996697826 44997334503 44999318666 45001705570 45001877746 45001898704 45002499038 45002977492 45004396897 45005495668 45006009697 45007318955 45007321482 45007415699 45008786724

</details>
