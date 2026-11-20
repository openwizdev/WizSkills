# WS1 evidence

The before inventory uses WizSkills
`89fc285ce551f341b8d308732bcd8d4467ace353`, before the catalog removals.
The [21 baseline rows](baseline.csv) record Git source size and available
workflow observations. [Static loaded-path counts](static-baseline.json) are
a separate, reproducible estimate from the [pinned manifest](../baseline-paths.json)
using `js-tiktoken@1.0.21` and `o200k_base`. Static counts measure the
required packaged paths for the planned branch, including for an observed
attempt that stopped before reaching that branch's end.

## LV1 outcomes and trial accounting

The [read-back receipts](lv1.json) preserve the four original attempts and
the one authorized plan-graph repeat at the baseline pin. Each receipt
reports zero retries within its attempt. Host token fields remain unknown
for all five attempts.

| Workflow and attempt | Observed outcome | Fixture workflow time | Spawn-to-receipt upper bound | Cloud Credits |
| --- | --- | ---: | ---: | ---: |
| `grill.new` | Pass | Unknown | 329 s | 3 |
| `plan-graph.approval`, original | Unknown. The simulator rejected the GraphQL read before graph display or approval. | Unknown | 279 s | 4 |
| `plan-graph.approval`, repeat | Pass | 8,849 ms | 299 s | 3 |
| `build-ticket.regression` | Pass | Unknown | 253 s | 4 |
| `review-ticket.exact-head` | Pass | Unknown | 235 s | 3 |

The [repeat receipt](https://github.com/openwizdev/OpenWiz/issues/1174#issuecomment-6999562018)
records a pass after the simulator's GraphQL field parser was fixed. The first
sandbox was unavailable, so the operator reconstructed the fixture from its
sanitized receipt. The original revision bytes and fingerprint could not be
compared. The repeat's instrumented workflow timer excludes setup and receipt
publication. The baseline CSV uses the repeat's outcome and time for its
single plan-graph summary row.

The [combined read-back](https://github.com/openwizdev/OpenWiz/issues/1174#issuecomment-6999575215)
reports 17 Cloud Credits across five attempts and retains the
[original four-attempt accounting](https://github.com/openwizdev/OpenWiz/issues/1174#issuecomment-6999452169).
Spawn-to-receipt bounds include startup, fixture preparation and publication,
rounded up for timestamp precision. Cloud Credits cover the reported thread
activity and stay outside the workflow receipt's elapsed time and token fields.

Other representative cases and the additional pilot acceptance cases were
unrun. The evidence establishes the observed before outcomes and static
baseline. After trials and any measured token delta under SK-C remain open.

## Failing-first proofs

- [Receipt accounting](1174-red.txt)
- [Host-log accounting](1174-host-log-red.txt)
- [Static path accounting](1174-static-red.txt)

## After (WS14)

The [after measurements](after.md) compare the 0.2.0 candidate with this
baseline, per skill and in total, using the same harness and stops.
