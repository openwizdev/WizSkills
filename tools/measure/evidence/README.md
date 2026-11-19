# WS1 evidence

The before inventory is pinned to WizSkills
`89fc285ce551f341b8d308732bcd8d4467ace353`, before the catalog removals.
[Baseline rows](baseline.csv) cover all 21 entrypoints and join to the
[representative cases](../cases.md). Git blob sizes are observed. Each
representative trial's runtime counters and outcome are unknown pending an
authorized host run. The pilot acceptance cases are also unrun. This snapshot
does not establish a before/after token delta for SK-C.

The synthetic receipt tests exercise parsing and accounting. They cannot
supply workflow telemetry or an agent success verdict. See the failing-first
[receipt tests](1174-red.txt) and [host-log tests](1174-host-log-red.txt).
