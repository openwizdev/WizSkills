"""Exercise the receipt command at its JSON boundary using synthetic inputs."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


CLI = Path(__file__).with_name("measure.py")


class ReceiptTests(unittest.TestCase):
    def run_cli(self, host, usage, **observed):
        data = {
            "case": "synthetic.case",
            "commit": "a" * 40,
            "host": host,
            "model": "example-model",
            "effort": "medium",
            "usage": usage,
            **observed,
        }
        return self.run_raw(json.dumps(data))

    def run_raw(self, payload):
        return subprocess.run(
            [sys.executable, "-I", str(CLI)], input=payload,
            text=True, capture_output=True, check=False,
        )

    def run_log(self, host, *logs, **observed):
        with tempfile.TemporaryDirectory() as folder:
            args = []
            for index, events in enumerate(logs):
                log = Path(folder) / f"attempt-{index}.jsonl"
                log.write_text("".join(json.dumps(event) + "\n" for event in events))
                args.extend(("--host-log", str(log)))
            return subprocess.run(
                [sys.executable, "-I", str(CLI), *args], text=True, capture_output=True,
                input=json.dumps({
                    "case": "synthetic.case", "commit": "a" * 40,
                    "host": host, "model": "example-model", "effort": "medium",
                    **observed,
                }),
                check=False,
            )

    def test_codex_jsonl_counts_completed_turns_and_only_outputs_receipt(self):
        result = self.run_log("codex", [
            {"type": "thread.started", "thread_id": "synthetic-hidden-id"},
            {"type": "turn.started"},
            {"type": "item.completed", "item": {"text": "synthetic-hidden-content"}},
            {"type": "turn.completed", "usage": {
                "input_tokens": 401, "cached_input_tokens": 100, "output_tokens": 17,
            }},
        ], [
            {"type": "turn.started"},
            {"type": "turn.completed", "usage": {
                "input_tokens": 509, "cached_input_tokens": 100, "output_tokens": 23,
            }},
        ], metrics={"wall_ms": 847, "retries": 1}, outcome="pass")
        self.assertEqual(result.returncode, 0, result.stderr)
        metrics = self.read_receipt(result)
        self.assertEqual((metrics["input_tokens"], metrics["output_tokens"]), (910, 40))
        self.assertEqual((metrics["wall_ms"], metrics["retries"]), (847, 1))
        self.assertNotIn("synthetic-hidden", result.stdout)

    def test_codex_incomplete_attempt_does_not_publish_partial_total(self):
        complete = [
            {"type": "turn.started"},
            {"type": "turn.completed", "usage": {"input_tokens": 33, "output_tokens": 4}},
        ]
        control = self.run_log("codex", complete)
        metrics = self.read_receipt(control)
        self.assertEqual((metrics["input_tokens"], metrics["output_tokens"]), (33, 4))
        for end in [[], [{"type": "turn.failed"}]]:
            with self.subTest(end=end):
                result = self.run_log("codex", [
                    *complete, {"type": "turn.started"}, *end,
                ], outcome="fail")
                self.assertEqual(result.returncode, 0, result.stderr)
                metrics = self.read_receipt(result)
                self.assertIsNone(metrics["input_tokens"])
                self.assertIsNone(metrics["output_tokens"])
                self.assertEqual(json.loads(result.stdout)["outcome"], "fail")

    def test_claude_jsonl_uses_result_usage_once_per_attempt(self):
        first = [
            {"type": "assistant", "message": {"usage": {"input_tokens": 8}}},
            {"type": "result", "is_error": True, "usage": {
                "input_tokens": 9, "cache_creation_input_tokens": 20,
                "cache_read_input_tokens": 30, "output_tokens": 7, "server_tool_use": {},
            }},
        ]
        second = [{"type": "result", "usage": {
            "input_tokens": 6, "cache_creation_input_tokens": 10,
            "cache_read_input_tokens": 60, "output_tokens": 4,
        }}]
        result = self.run_log("claude-code", first, second, outcome="pass")
        self.assertEqual(result.returncode, 0, result.stderr)
        metrics = self.read_receipt(result)
        self.assertEqual((metrics["input_tokens"], metrics["output_tokens"]), (135, 11))

    def test_host_logs_refuse_ambiguous_or_conflicting_sources(self):
        completed = {"type": "result", "usage": {"output_tokens": 3}}
        for logs, extra in [
            (([completed, completed],), {}),
            (([completed],), {"usage": {"output_tokens": 3}}),
        ]:
            with self.subTest(logs=logs, extra=extra):
                result = self.run_log("claude-code", *logs, **extra)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")

    def read_receipt(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(
            {key: receipt.get(key) for key in ("schema", "case", "commit", "model", "effort")},
            {
                "schema": "wizskills.measurement.v1",
                "case": "synthetic.case",
                "commit": "a" * 40,
                "model": "example-model",
                "effort": "medium",
            },
        )
        return receipt["metrics"]

    def test_codex_sums_turns_without_adding_cached_input_twice(self):
        result = self.run_cli(
            "codex",
            [
                {"input_tokens": 500, "cached_input_tokens": 400, "output_tokens": 70},
                {"input_tokens": 300, "cached_input_tokens": 100, "output_tokens": 30},
            ],
            metrics={"entrypoint_tokens": 123, "reference_tokens": 32,
                     "tool_output_tokens": 45, "discovery_tokens": 8,
                     "wall_ms": 620, "retries": 1},
            outcome="pass",
        )
        self.assertEqual(json.loads(result.stdout).get("metrics"), {
            "entrypoint_tokens": 123, "reference_tokens": 32, "tool_output_tokens": 45,
            "discovery_tokens": 8, "input_tokens": 800, "output_tokens": 100,
            "wall_ms": 620, "retries": 1,
        })
        self.read_receipt(result)
        self.assertEqual(json.loads(result.stdout)["outcome"], "pass")

    def test_claude_counts_cache_writes_and_reads_in_input(self):
        result = self.run_cli("claude-code", {
            "input_tokens": 6, "cache_creation_input_tokens": 42,
            "cache_read_input_tokens": 100, "output_tokens": 15,
        })
        self.assertEqual(json.loads(result.stdout).get("metrics", {}).get("input_tokens"), 148)
        self.assertEqual(self.read_receipt(result)["output_tokens"], 15)

    def test_incomplete_usage_stays_unknown_per_field(self):
        result = self.run_cli(
            "codex",
            [{"input_tokens": 12, "output_tokens": 0}, {"output_tokens": 0}],
            metrics={"tool_output_tokens": 0, "wall_ms": 14}, outcome="fail",
        )
        self.assertEqual(json.loads(result.stdout).get("metrics"), {
            "entrypoint_tokens": None, "reference_tokens": None, "tool_output_tokens": 0,
            "discovery_tokens": None, "input_tokens": None, "output_tokens": 0,
            "wall_ms": 14, "retries": None,
        })
        self.read_receipt(result)
        self.assertEqual(json.loads(result.stdout)["outcome"], "fail")

    def test_absent_and_partial_host_counters_remain_unknown(self):
        for host, usage in [
            ("codex", []), ("codex", None), ("claude-code", None),
            ("claude-code", {"input_tokens": 5, "cache_read_input_tokens": 0}),
        ]:
            with self.subTest(host=host, usage=usage):
                result = self.run_cli(host, usage)
                self.assertEqual(json.loads(result.stdout).get("metrics"), dict.fromkeys(
                    ["entrypoint_tokens", "reference_tokens", "tool_output_tokens", "discovery_tokens",
                     "input_tokens", "output_tokens", "wall_ms", "retries"]
                ))
                self.read_receipt(result)
                self.assertIsNone(json.loads(result.stdout)["outcome"])

    def test_invalid_or_duplicate_counters_refuse_without_a_receipt(self):
        valid = ('{"case":"synthetic.case","commit":"' + "a" * 40
                 + '","host":"codex","model":"example-model","effort":"medium",')
        for payload in [
            valid + '"usage":[{"input_tokens":2,"input_tokens":3}]}',
            valid + '"usage":[{"input_tokens":true}]}',
            valid + '"usage":[{"input_tokens":-1}]}',
            valid + '"usage":[{"input_tokens":1.5}]}',
            valid + '"usage":[{"input_tokens":1,"cached_input_tokens":2}]}',
            valid + '"usage":[{"input_tokens":NaN}]}',
            valid + '"metrics":{"wall_ms":"private fixture placeholder"}}',
            valid + '"metrics":{"input_tokens":100},"usage":[{"input_tokens":2}]}',
            valid + '"unexpected":"private fixture placeholder"}',
        ]:
            with self.subTest(payload=payload):
                result = self.run_raw(payload)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertNotIn("private fixture placeholder", result.stderr)


if __name__ == "__main__":
    unittest.main()
