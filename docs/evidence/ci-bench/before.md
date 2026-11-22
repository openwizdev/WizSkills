# BEFORE bench: where `check` spends its time

The BEFORE half of spec openwizdev/OpenWiz#2134's bench (ticket WQ0, openwizdev/OpenWiz#2269). The AFTER bench (WQ7) runs `check/bench.py` with the same phase definitions on its own window.

## Window

- **Runs:** every successful, completed `pull_request` run of the `WizSkills check` workflow (`.github/workflows/ci.yml`) created 2026-11-20 to 2026-11-22 (UTC), read on 2026-11-22 at about 10:30 UTC: **247 runs**, from 44643925573 (2026-11-20T00:12:11Z) to 45008786724 (2026-11-22T09:41:45Z). Each run is one sample: the attempt GitHub listed for it, written `<run id>/<attempt>`. One run was rerun, 44824409928; its sample is attempt 2. The pinned samples are listed below.
- **Command:** `python3 check/bench.py --from 2026-11-20 --to 2026-11-22`. Runs created later on 2026-11-22 widen that query, and a later rerun changes a run's latest attempt, so to repeat this exact window, pass the pinned samples below to `--runs`, which reads exactly those attempts.
- Every run had one job, `check`, on `ubuntu-24.04`.

## Phases

Seconds per phase. **Median** is over the runs that know the phase; **Known** counts them. A phase a run never ran or finished is unknown and stays out of the median, never counted as zero.

- **queue wait:** the job's created to started time.
- **setup:** the "Set up job", checkout and "Install the pinned Changesets" steps.
- **changeset gate**, **comment check**, **browser tools:** their workflow steps (GitHub reports steps to the whole second).
- **rules**, **standalone:** from the `check/run.py` step's start to its `rules:` line, then to its `standalone:` line.
- **suite …:** each suite command's `running` line to its `pass` or `fail` line, with or without the ` in N.Ns` that `check/run.py` may add; the time comes from the log's timestamps either way, so the AFTER bench reads its window the same way.
- **total:** the attempt's start to its job's completed time, so a rerun never counts the wait before it.

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

<details><summary>The 247 pinned samples (`<run id>/<attempt>`)</summary>

44643925573/1 44644662231/1 44644985726/1 44645024663/1 44647072061/1 44648157001/1 44650381422/1 44650578777/1 44650629857/1 44651060369/1 44651197083/1 44651401019/1 44651530489/1 44651847208/1 44653132961/1 44654585702/1 44655137149/1 44655245696/1 44655449861/1 44655724943/1 44655945824/1 44656026490/1 44656397199/1 44657683065/1 44658100249/1 44659052785/1 44659232510/1 44661125948/1 44661250903/1 44661756078/1 44662359236/1 44662380640/1 44662481577/1 44662881775/1 44662922573/1 44663093811/1 44663867741/1 44663874465/1 44663890681/1 44663937793/1 44663946396/1 44664998054/1 44665629811/1 44667380427/1 44670422029/1 44670429714/1 44670432567/1 44670460528/1 44670668494/1 44670847339/1 44671272095/1 44672390882/1 44672681806/1 44673424831/1 44674804353/1 44676168185/1 44676260476/1 44676447227/1 44676651384/1 44677272842/1 44679406882/1 44679501790/1 44679980596/1 44680052882/1 44680655235/1 44681102370/1 44681910456/1 44682324099/1 44683686912/1 44684050187/1 44684160632/1 44686000049/1 44686068061/1 44686890959/1 44692989069/1 44694143422/1 44694164807/1 44694191049/1 44694793237/1 44695518963/1 44696274051/1 44696352644/1 44701727719/1 44702920906/1 44705205909/1 44706151753/1 44706155197/1 44710918863/1 44711019989/1 44713323878/1 44714042026/1 44718889949/1 44721850332/1 44721894078/1 44726396149/1 44731725604/1 44731743464/1 44731959152/1 44733303244/1 44733484264/1 44736107961/1 44736297956/1 44737590252/1 44738324897/1 44739195692/1 44740557771/1 44740760743/1 44741260513/1 44742092344/1 44744001180/1 44744202010/1 44745933780/1 44747785335/1 44748639921/1 44750632431/1 44752564111/1 44752587540/1 44752892036/1 44755889936/1 44760152539/1 44761180607/1 44762717591/1 44765042776/1 44767209950/1 44767695340/1 44767732907/1 44768202275/1 44768388233/1 44768757542/1 44768892980/1 44769055466/1 44776644594/1 44776673231/1 44777818602/1 44778413983/1 44779107142/1 44783708276/1 44785529190/1 44786229075/1 44789608557/1 44790833931/1 44792917636/1 44795254859/1 44795418302/1 44800789338/1 44800959166/1 44803197360/1 44803671332/1 44811606655/1 44812135661/1 44812426135/1 44814866103/1 44815130255/1 44815287631/1 44815318750/1 44815788236/1 44823071091/1 44824096323/1 44824409928/2 44828166847/1 44833658753/1 44833864209/1 44835346433/1 44839548594/1 44839562710/1 44839682557/1 44840377110/1 44845207580/1 44846043020/1 44846082630/1 44851248160/1 44851396270/1 44851706763/1 44851995781/1 44852136007/1 44853394520/1 44854760463/1 44855316541/1 44857059895/1 44857862087/1 44857915554/1 44858878712/1 44860062360/1 44861960520/1 44862030208/1 44862038377/1 44863897707/1 44864840695/1 44866265531/1 44866922190/1 44868111302/1 44872780222/1 44873194528/1 44876346700/1 44878378105/1 44883209221/1 44883293508/1 44884467000/1 44884997940/1 44885793556/1 44889299977/1 44891549375/1 44891749013/1 44893206945/1 44896915346/1 44897133708/1 44901221227/1 44901265717/1 44905749652/1 44906172973/1 44910133651/1 44924512251/1 44931169815/1 44934792891/1 44936855036/1 44937025985/1 44946235438/1 44947319284/1 44956408780/1 44957028627/1 44957230904/1 44971139972/1 44971573720/1 44972015277/1 44972258482/1 44973098515/1 44991669639/1 44991908140/1 44991991429/1 44992169210/1 44992405352/1 44994492517/1 44996697826/1 44997334503/1 44999318666/1 45001705570/1 45001877746/1 45001898704/1 45002499038/1 45002977492/1 45004396897/1 45005495668/1 45006009697/1 45007318955/1 45007321482/1 45007415699/1 45008786724/1

</details>
