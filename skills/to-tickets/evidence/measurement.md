# WS4 workflow measurements

Use the [WS1 counter](../../../tools/measure/README.md) with the pinned
[before](static-before-paths.json) and [after](static-after-paths.json)
manifests. The spec case stops at confirmation and excludes the link
contract. The graph case uses the original WS1 approval branch. Both
after cases include the record guidance and its required reads. Owning
project settings, rendered media and script output are outside this
static measure.

| Workflow | Before static tokens | After static tokens | Observed before | Observed after |
| --- | ---: | ---: | --- | --- |
| Confirmed grill to spec confirmation | 33,948 | 22,871 | Unknown | Unknown |
| Confirmed spec to graph approval | 38,193 | 27,549 | Pass on the WS1 repeat | Unknown |

[Before report](static-before.json) · [After report](static-after.json) ·
[WS1 observed results](../../../tools/measure/evidence/README.md)

The original entrypoint is 580 lines and 9,008 words. The new entrypoints
are 86 lines and 663 words for to-spec, and 97 lines and 780 words for
to-tickets. Local synthetic helpers and kept suites prove their own
boundaries. Actual loaded tokens, host wall time and after agent outcomes
remain unknown for both workflows. The static totals measure required
packaged reading.
