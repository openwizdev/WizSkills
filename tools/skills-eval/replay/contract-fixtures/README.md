# Synthetic paired replay fixtures

`synthetic_assumptions`: every historical revision, source, first-review context,
sealed key, fresh-run key, finding, severity, score and usage reference is invented.
The contexts are manifest attestations, not proof of an actual isolation boundary.

paired.json: two known problems; old catch/miss/false-positive = 1/1/1, candidate
2/0/0. partial.json retains the old result and an explicit candidate error;
selection is none and estimated avoided rounds is unknown. The same validator
also accepts not_run/no-result and clean-control rows; unresolved adjudications
prevent selection. No replay runs or private answer files are created by tests.

Terminal attempt timestamps let partial-pair scoring wait for both dispositions;
a pending counterpart never exposes the sealed key early.
