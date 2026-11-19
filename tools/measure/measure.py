#!/usr/bin/env python3
"""Produce a workflow receipt from host counters and observed measurements."""

import argparse
import json
from pathlib import Path
import re
import sys


SCHEMA = "wizskills.measurement.v1"
IDENTITY = ("case", "commit", "host", "model", "effort")
OBSERVED = (
    "discovery_tokens", "entrypoint_tokens", "reference_tokens",
    "tool_output_tokens", "wall_ms", "retries",
)
CODEX_USAGE = ("input_tokens", "cached_input_tokens", "output_tokens")
CLAUDE_INPUT = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
CLAUDE_USAGE = (*CLAUDE_INPUT, "output_tokens")
LABEL = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def refuse_constant(_constant):
    raise ValueError("invalid JSON constant")


def fields(value, allowed):
    if not isinstance(value, dict) or value.keys() - set(allowed):
        raise ValueError("unexpected object shape")
    return value


def counters(value, keys):
    value = fields(value, keys) if value is not None else {}
    result = {key: value.get(key) for key in keys}
    for count in result.values():
        if count is not None and (type(count) is not int or count < 0):
            raise ValueError("invalid counter")
    return result


def complete_sum(values):
    values = list(values)
    return sum(values) if values and None not in values else None


def totals(host, usage):
    if usage is None:
        return None, None
    if host == "claude-code":
        counts = counters(usage, CLAUDE_USAGE)
        return complete_sum(counts[key] for key in CLAUDE_INPUT), counts["output_tokens"]

    if not isinstance(usage, list):
        raise ValueError("Codex usage needs a list")
    turns = [counters(turn, CODEX_USAGE) for turn in usage]
    for turn in turns:
        cached = turn["cached_input_tokens"]
        total = turn["input_tokens"]
        if cached is not None and total is not None and cached > total:
            raise ValueError("cached input exceeds total input")
    return (complete_sum(t["input_tokens"] for t in turns),
            complete_sum(t["output_tokens"] for t in turns))


def decode(text):
    return json.loads(text, object_pairs_hook=unique_object, parse_constant=refuse_constant)


def events(path):
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            event = decode(line)
            if not isinstance(event, dict) or not isinstance(event.get("type"), str):
                raise ValueError("invalid host event")
            yield event


def event_usage(event, keys):
    usage = event.get("usage")
    if usage is None:
        return None
    if not isinstance(usage, dict):
        raise ValueError("invalid host usage")
    return {key: usage[key] for key in keys if key in usage}


def codex_attempt(path):
    # A started turn without a usable completion contributes unknown usage.
    turns = []
    pending = False
    for event in events(path):
        kind = event["type"]
        if kind == "turn.started":
            if pending:
                raise ValueError("overlapping turns")
            pending = True
        elif kind in ("turn.completed", "turn.failed"):
            if not pending:
                raise ValueError("terminal event without a turn")
            counts = event_usage(event, CODEX_USAGE) if kind == "turn.completed" else None
            turns.append(counts)
            pending = False
    if pending:
        turns.append(None)
    return totals("codex", turns)


def claude_attempt(path):
    results = [event_usage(event, CLAUDE_USAGE) for event in events(path)
               if event["type"] == "result"]
    if len(results) > 1:
        raise ValueError("multiple Claude results for one attempt")
    return totals("claude-code", results[0] if results else None)


def receipt(record, logs):
    fields(record, (*IDENTITY, "metrics", "usage", "outcome"))
    for key in IDENTITY:
        if key not in record or not isinstance(record[key], str):
            raise ValueError("missing or invalid identity")
        pattern = r"[0-9a-f]{40}" if key == "commit" else LABEL
        if not re.fullmatch(pattern, record[key]):
            raise ValueError("invalid identity")
    host = record["host"]
    if host not in ("codex", "claude-code"):
        raise ValueError("unsupported host")
    outcome = record.get("outcome")
    if outcome not in (None, "pass", "fail"):
        raise ValueError("invalid outcome")
    metrics = counters(record.get("metrics"), OBSERVED)
    if logs:
        if "usage" in record or len({path.resolve() for path in logs}) != len(logs):
            raise ValueError("ambiguous usage sources")
        attempt = codex_attempt if host == "codex" else claude_attempt
        inputs, outputs = zip(*(attempt(path) for path in logs))
        token_totals = complete_sum(inputs), complete_sum(outputs)
    else:
        token_totals = totals(host, record.get("usage"))
    metrics["input_tokens"], metrics["output_tokens"] = token_totals
    return {
        "schema": SCHEMA,
        **{key: record[key] for key in IDENTITY},
        "outcome": outcome,
        "metrics": metrics,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-log", type=Path, action="append", default=[],
                        help="private JSONL log for one attempt, repeat for retries")
    args = parser.parse_args()
    try:
        result = receipt(decode(sys.stdin.read()), args.host_log)
    except (OSError, ValueError, RecursionError):
        # Parser errors can contain excerpts of private input.
        print("measure: invalid workflow input", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
