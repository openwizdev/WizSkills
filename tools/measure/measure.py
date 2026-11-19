#!/usr/bin/env python3
"""Produce a workflow receipt from host counters and observed measurements."""

import json
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


def receipt(record):
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
    metrics["input_tokens"], metrics["output_tokens"] = totals(host, record.get("usage"))
    return {
        "schema": SCHEMA,
        **{key: record[key] for key in IDENTITY},
        "outcome": outcome,
        "metrics": metrics,
    }


def main():
    try:
        record = json.load(sys.stdin, object_pairs_hook=unique_object,
                           parse_constant=refuse_constant)
        result = receipt(record)
    except (ValueError, UnicodeError, RecursionError):
        # Parser errors can contain excerpts of private input.
        print("measure: invalid workflow input", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
