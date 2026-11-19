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

The [four read-back receipts](lv1.json) each record one attempt at the
baseline pin. All four have zero retries. Host token fields and
workflow-only wall time remain unknown for all four.

| Workflow | Observed outcome | Spawn-to-receipt upper bound | Cloud Credits |
| --- | --- | ---: | ---: |
| `grill.new` | Pass | 329 s | 3 |
| `plan-graph.approval` | Unknown. Fixture rejected the GraphQL read before graph display or approval. | 279 s | 4 |
| `build-ticket.regression` | Pass | 253 s | 4 |
| `review-ticket.exact-head` | Pass | 235 s | 3 |

The [supplemental read-back](https://github.com/openwizdev/OpenWiz/issues/1174#issuecomment-6999452169)
reports 14 Cloud Credits in total. The bounds include startup, fixture work
and publishing the receipt, rounded up for timestamp precision. Credits
cover the logged thread activity in the source hour, including any archive
turn. Both stay outside the workflow receipt's elapsed time and token fields.

Other representative cases and the additional pilot acceptance cases were
unrun. The evidence establishes the observed before outcomes and static
baseline. After trials and any measured token delta under SK-C remain open.

## Failing-first proofs

- [Receipt accounting](1174-red.txt)
- [Host-log accounting](1174-host-log-red.txt)
- [Static path accounting](1174-static-red.txt)
