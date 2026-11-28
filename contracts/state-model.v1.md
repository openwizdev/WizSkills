# OpenWiz state-model contract, version 1 (`openwiz.state-model.v1`)

[OpenWiz #3710](https://github.com/openwizdev/OpenWiz/issues/3710) defines the model shared by the checker and the state-hunt skill. [The schema](state-model.v1.schema.json) describes the model at its root and the report at `#/$defs/report`.

## Model

The input is one UTF-8 JSON object with unique keys and the following fields. Objects have only the fields shown in the schema.

| Field | Meaning |
| --- | --- |
| `schema` | The literal `openwiz.state-model.v1`. |
| `machine` | A short name for the machine. |
| `sources` | `{"commit": "<40 lowercase hex digits>", "files": ["relative/path"]}`. All files belong to the pinned commit of the modelled repository. Paths name files relative to that repository, with no `.` or `..` segments. |
| `variables` | A map from variable names to finite domains. An enum is `{"type":"enum","values":["idle","busy"]}`. An integer is `{"type":"int","min":0,"max":3}`, with inclusive bounds. A set is `{"type":"set","items":["a","b"],"maxSize":1}`. |
| `init` | A map with exactly one value from its domain for each variable. Sets are arrays of distinct items. |
| `actions` | An ordered array of `{"name": ..., "guard": ..., "effect": [...], "cites": [...]}` objects. Every action has a unique name and at least one cite of the form `{"file": ..., "start": ..., "end": ...}`. Each cite names one of `sources.files` with a one-based inclusive line range. |
| `invariants` | A map from invariant names to predicates that must hold in every reached state. |
| `progress` | Optional map from milestone names to predicates. Each milestone must remain reachable from every reachable non-final state, including by zero steps. Names are distinct from invariant names. |
| `final` | Optional predicate identifying completed states. The default is `false`. |
| `bound` | Positive maximum number of distinct states to inspect, counting the initial state. |

Names other than `machine` start with an ASCII letter or underscore and continue with ASCII letters, digits, underscores or hyphens. Numbers denoting integers are limited to the range −(2⁵³−1) through 2⁵³−1, which Node can represent exactly.

## Predicates and effects

Terms are literal strings, integers, arrays of distinct strings, or objects of the form `{"var":"phase"}` that read a declared variable in the current state. JSON strings are literal data. Predicates are JSON booleans or objects with an `op` and an `args` array.

| Predicate operator | Arguments and result |
| --- | --- |
| `eq`, `ne` | Two terms of the same kind. Sets compare by membership. |
| `lt`, `le`, `gt`, `ge` | Two integer terms, compared in that order. |
| `in` | A string term followed by a set term. True when the string is a member. |
| `and`, `or` | At least two predicates. True when all or at least one is true, respectively. |
| `not` | One predicate, negated. |

An effect is an array of updates. `{"op":"assign","var":"phase","value":"busy"}` replaces a variable with a term of the same kind. `{"op":"add","var":"tags","item":"a"}` and `{"op":"remove","var":"tags","item":"a"}` add or remove a named item in that variable's declared set. Adding a present item or removing an absent item preserves the set.

Each variable has at most one update per action. All updates read the state before the action and take effect together. An empty effect is a self-loop. An action is enabled when its guard is true and its updated values all fit their declared domains. The domain check prevents a transition past a bound, including adding a new item to a full set. Unmentioned variables retain their values.

These are the complete forms. The checker interprets them as data over the current model's variables. Citations are metadata for a reviewer. Checking uses no code evaluation, file reads through expressions or citations, network access, or child processes.

## Validation

Validate the whole model before starting the search, including expressions in unreachable branches. The schema checks the shape of the model. To check variable names against the declaration map, also validate with the same schema after adding the keys of `variables` as an `enum` alongside the `$ref` in `$defs.variableName`. For an empty declaration map, set `$defs.variableName` to `false`. A checker can enforce the same rule with membership checks.

The language additionally checks that integer bounds are ordered, a set's `maxSize` is no larger than its item list, `init` supplies exactly the declared keys and fits each domain, and every operand and update has the specified kind. Literal assignments must fit their target domain, and set updates must name an item in that set's domain. Check the uniqueness of action names and update targets, the disjointness of progress and invariant names, and that each cite names a declared file with `start <= end`. All these checks use the model alone.

## Search and report

Explore breadth first from `init`. Count a state when it is taken from the queue for inspection. Visit each distinct state once, comparing states by their values and sets by membership. Enqueue enabled successors in action-array order and keep the first path to each state. Check invariants in ascending ASCII name order at each state, followed by the stuck-state check. A stuck state has no enabled action and fails `final`. A final state can have enabled actions and is still checked for invariant violations.

When the queue empties without a local counterexample, check `progress` on the complete explored graph. Each non-final state must be able to reach a match for each named milestone along some path. Choose the first failing state in breadth-first order and then the first failing name in ascending ASCII order. Report it as a named invariant counterexample. This checks for an available path. It places no requirement on which actions are taken.

If uninspected states remain after `bound` inspections, report `bound-reached`. If the queue is exhausted exactly at the bound, apply the ordinary completion rules. A counterexample found on the last allowed inspection takes precedence over `bound-reached`.

Print one JSON report to standard output. Every report includes `status` and `statesExplored`.

| Exit | Status | Additional fields |
| --- | --- | --- |
| 0 | `ok` | The search finished and all checks passed. |
| 1 | `counterexample` | `kind` is `invariant` or `stuck`. A named violation includes `name`. Both include `trace`, the shortest action path from `init` to the reported state. Each step is `{"action":"pack","state":{...}}` with the complete state after the action. The trace is empty for a failure at `init`. Output set arrays sorted by Unicode code point. |
| 2 | `invalid` | `statesExplored` is 0. `reason` is `unreadable` for a failed file read, `unknown-expression` for an unknown predicate or update operator, `unbounded-domain` for a missing integer endpoint or set size limit, `missing-cite` for missing or empty `cites`, `unknown-variable` for a reference to an undeclared variable, or `invalid-model` for another JSON, schema or language refusal. When several refusal reasons apply, any applicable reason is valid. |
| 3 | `bound-reached` | The search has uninspected states. Treat this status as incomplete. |

## Fixtures

[The synthetic models](fixtures/state-model/) each have a matching entry in [expected.json](fixtures/state-model/expected.json), holding the expected `exit` and `report` from SM2. The passing model exhausts its search at the bound. The broken invariant has both a direct and a longer path to the same broken state. The stuck and progress failures each have a one-step trace.

Run the standard-library schema proof from the repository root:

```sh
python3 -I contracts/fixtures/state-model/test_schema.py
```
