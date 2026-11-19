# Measure a WizSkills workflow

Reuse the [workflow cases](cases.md) at the same input state, permissions,
host, model and effort for before and after. Start each trial in a fresh
context, except where the case calls for a resume within the workflow. Pin the
skill checkout by full commit. Run only in an authorized environment with
synthetic state and isolated or simulated effects. Keep the trace outside Git.
Score the observable check in the case, including any refusal or recovery
required. Record setup failures that prevented the workflow from running as
unknown outcomes.

Run the standard-library receipt tool from WizSkills with Python 3.11+.

```sh
python3 -I tools/measure/measure.py --host-log "$trial_log" < "$trial_metadata"
python3 -I tools/measure/test_measure.py -v
```

Repeat `--host-log` in attempt order to include retries. Capture the complete
host JSONL stream for each attempt. Use Codex exec JSON output or Claude Code
stream JSON output with the terminal result present. Supply the metadata on
stdin as one JSON object. For example, this is synthetic metadata for a
successful Codex trial with wall time and a separately observed tool count.

```json
{
  "case": "grill.new",
  "commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "host": "codex",
  "model": "example-model",
  "effort": "medium",
  "outcome": "pass",
  "metrics": {"tool_output_tokens": 240, "wall_ms": 12340, "retries": 0}
}
```

The five identity fields are required. Use public-safe labels for case, host,
model and effort, and a lowercase 40-character commit. Supported hosts are
`codex` and `claude-code`. The tool prints one `wizskills.measurement.v1`
receipt with identity, outcome and all eight counters. Input errors exit 2
with a short diagnostic and no receipt. Raw host events are never echoed.
Check the sanitized receipt for publication before saving it under
[evidence](evidence/).

| Field | What to record |
| --- | --- |
| `discovery_tokens` | Catalog metadata actually injected during discovery, if measured. |
| `entrypoint_tokens` | Selected skill bodies delivered to the model, including invoked skill entrypoints. Count repeated deliveries. |
| `reference_tokens` | Reference content actually delivered, including partial and repeated reads. |
| `tool_output_tokens` | Tool output delivered besides already attributed skill and reference content, after truncation by the host. |
| `input_tokens`, `output_tokens` | Host-reported totals across the full workflow, including every observed retry and cache traffic. |
| `wall_ms` | Whole trial elapsed milliseconds from an external monotonic timer, including retries and waits within the case. |
| `retries` | Additional attempts made to recover the same workflow. |
| `outcome` | `pass` or `fail` from the case's check. Use `null` when it was not observed. |

Where the host provides category counters, use those. Otherwise attribute
delivered fragments from the trace with the same host/model tokenizer in both
runs. Record component counts only with complete attribution for that field.
A script execution counts its delivered output. Its source counts only when
the agent reads it. Totals include other host input, prompt history across
model calls, and framing. Compare like fields under matched trial conditions
and preserve unknowns in any aggregate. Git lines and words are source size.

For Codex, the tool sums deltas from `turn.completed.usage` and treats
`cached_input_tokens` as part of `input_tokens`. A failed or unfinished turn
has unknown usage. For Claude Code, it reads only the terminal `result.usage`
per attempt and adds its uncached input, cache creation and cache read counts.
Assistant-message usage can overlap the terminal result. A missing terminal
result has unknown usage. Each total is independently unknown if any of its
contributing counters are missing. A truncated JSON line is invalid. Keep the
raw file private and record only fields supported by an intact observation.

For a host capture with counters already extracted, omit `--host-log` and add
an optional `usage` field to stdin. Codex accepts a list of per-turn objects
with `input_tokens`, `cached_input_tokens` and `output_tokens`. Use a
`null` element for each unobserved or failed turn. Claude Code accepts one
workflow-wide usage object with `input_tokens`, `cache_creation_input_tokens`,
`cache_read_input_tokens` and `output_tokens`. For multiple attempts use the
log route, or preserve any unavailable aggregate field as `null` when
extracting counters. Supply only nonnegative integer counts, or `null`.
Omissions and `null` mean unknown, and zero means observed zero.

The [before snapshot](evidence/baseline.csv) pins the pre-catalog inventory
and recorded values. The static columns can be checked by reading each
`skills/<skill>/SKILL.md` blob with `git show <commit>:<path>` and counting
UTF-8 text with Python `splitlines()` for lines and `split()` for words.
