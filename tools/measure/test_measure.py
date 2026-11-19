"""Exercise the receipt command at its JSON boundary using synthetic inputs."""
import json
from pathlib import Path
import subprocess
import sys
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
