#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "mcp" / "server.py"
PROTOCOL_FIXTURE = ROOT / "contracts" / "fixtures" / "skills-mcp" / "protocol.json"

sys.path.insert(0, str(ROOT))
import mcp.server as server_mod


def materialize_checkout(base, fixture):
    for rel, text in fixture["files"].items():
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    for rel, raw_bytes in fixture.get("binaryFiles", {}).items():
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(bytes(raw_bytes))
    for rel, link_target in fixture.get("links", {}).items():
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(link_target, target)


class StdioClient:
    def __init__(self, checkout=None, extra_args=()):
        cmd = [sys.executable, "-I", str(SERVER)]
        if checkout is not None:
            cmd += ["--from", str(checkout)]
        cmd += list(extra_args)
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def send_raw(self, payload_bytes):
        self.proc.stdin.write(payload_bytes)
        self.proc.stdin.flush()

    def send_json(self, obj):
        self.send_raw((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))

    def read_reply(self):
        line = self.proc.stdout.readline()
        if not line:
            stderr = self.proc.stderr.read().decode("utf-8", errors="replace")
            raise AssertionError(f"server closed stdout early; stderr={stderr!r}")
        return json.loads(line.decode("utf-8"))

    def close(self):
        self.proc.stdin.close()
        remaining = self.proc.stdout.read()
        stderr = self.proc.stderr.read().decode("utf-8", errors="replace")
        code = self.proc.wait(timeout=10)
        return code, remaining, stderr


class SkillsMcpServerTest(unittest.TestCase):
    def run_steps(self, client, steps):
        for step in steps:
            if "send" in step:
                client.send_json(step["send"])
            else:
                client.send_raw((step["line"] + "\n").encode("utf-8"))
            expected = step["reply"]
            if expected is not None:
                self.assertEqual(client.read_reply(), expected)

    def test_protocol_fixtures_over_stdio(self):
        fixture = json.loads(PROTOCOL_FIXTURE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            checkout = Path(tmp)
            materialize_checkout(checkout, fixture)
            for case in fixture["cases"]:
                with self.subTest(case=case["name"]):
                    client = StdioClient(checkout)
                    try:
                        if not case.get("fresh"):
                            self.run_steps(client, fixture["start"])
                        self.run_steps(client, case["steps"])
                        code, remaining, stderr = client.close()
                    except Exception:
                        client.proc.kill()
                        client.proc.wait(timeout=5)
                        raise
                    self.assertEqual(code, 0, stderr)
                    self.assertEqual(remaining, b"")
                    self.assertEqual(stderr, "")

    def test_default_checkout_serves_all_skills_and_text_resources_only(self):
        client = StdioClient()
        try:
            client.send_json({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "syn-client", "version": "1"},
                },
            })
            init = client.read_reply()
            self.assertEqual(init["result"]["protocolVersion"], "2025-11-25")
            client.send_json({"jsonrpc": "2.0", "method": "notifications/initialized"})

            client.send_json({"jsonrpc": "2.0", "id": 2, "method": "prompts/list"})
            prompts = client.read_reply()["result"]["prompts"]
            expected_skills = sorted(
                p.parent.name for p in (ROOT / "skills").glob("*/SKILL.md")
            )
            self.assertEqual([p["name"] for p in prompts], expected_skills)
            by_name = {p["name"]: p["description"] for p in prompts}
            self.assertTrue(by_name["wait-what"].startswith("Re-pitch the last message"))
            self.assertFalse(by_name["wait-what"].startswith('"'))

            client.send_json({
                "jsonrpc": "2.0",
                "id": 3,
                "method": "prompts/get",
                "params": {"name": "build-ticket", "arguments": {}},
            })
            prompt = client.read_reply()["result"]
            self.assertEqual(prompt["description"], by_name["build-ticket"])
            self.assertEqual(len(prompt["messages"]), 1)
            self.assertEqual(prompt["messages"][0]["role"], "user")
            self.assertIn("# Build a ticket", prompt["messages"][0]["content"]["text"])
            self.assertFalse(prompt["messages"][0]["content"]["text"].startswith("---"))

            client.send_json({"jsonrpc": "2.0", "id": 4, "method": "resources/list"})
            resources = client.read_reply()["result"]["resources"]
            uris = [r["uri"] for r in resources]
            self.assertEqual(uris, sorted(uris))
            self.assertIn("wizskills://build-ticket/SKILL.md", uris)
            self.assertNotIn("wizskills://image/references/dark-craft-desktop.png", uris)

            client.send_json({
                "jsonrpc": "2.0",
                "id": 5,
                "method": "resources/read",
                "params": {"uri": "wizskills://build-ticket/SKILL.md"},
            })
            contents = client.read_reply()["result"]["contents"]
            self.assertEqual(len(contents), 1)
            self.assertEqual(
                contents[0]["text"],
                (ROOT / "skills" / "build-ticket" / "SKILL.md").read_text(encoding="utf-8"),
            )
            code, remaining, stderr = client.close()
        except Exception:
            client.proc.kill()
            client.proc.wait(timeout=5)
            raise
        self.assertEqual(code, 0, stderr)
        self.assertEqual(remaining, b"")
        self.assertEqual(stderr, "")

    def test_error_paths_and_strict_jsonrpc_without_exiting(self):
        fixture = json.loads(PROTOCOL_FIXTURE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            checkout = Path(tmp)
            materialize_checkout(checkout, fixture)
            (checkout / "outside-dir").mkdir()
            (checkout / "outside-dir" / "secret.txt").write_text("outside\n", encoding="utf-8")
            os.symlink("../../outside-dir", checkout / "skills" / "syn-alpha" / "dir-link")

            client = StdioClient(checkout)
            try:
                client.send_raw(b"\xff\xfe\n")
                self.assertEqual(
                    client.read_reply(),
                    {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}},
                )

                client.send_raw(b'{"jsonrpc":"2.0","id":1,"id":2,"method":"prompts/list"}\n')
                self.assertEqual(
                    client.read_reply(),
                    {"jsonrpc": "2.0", "error": {"code": -32600, "message": "Invalid Request"}},
                )

                for bad_req in (
                    {"jsonrpc": "1.0", "id": 1, "method": "prompts/list"},
                    {"jsonrpc": "2.0", "id": True, "method": "prompts/list"},
                    {"jsonrpc": "2.0", "id": None, "method": "prompts/list"},
                    {"jsonrpc": "2.0", "id": 1, "method": "prompts/list", "extra": 1},
                ):
                    client.send_json(bad_req)
                    reply = client.read_reply()
                    self.assertEqual(reply["error"], {"code": -32600, "message": "Invalid Request"})
                    if isinstance(bad_req.get("id"), (str, int)) and not isinstance(bad_req.get("id"), bool):
                        self.assertEqual(reply.get("id"), bad_req["id"])
                    else:
                        self.assertNotIn("id", reply)

                for req_id, method, params in (
                    (20, "initialize", {"protocolVersion": "2025-11-25"}),
                    (21, "prompts/list", {"cursor": "x"}),
                    (22, "prompts/get", {}),
                    (23, "prompts/get", {"name": "syn-alpha", "arguments": {"a": "b"}}),
                    (24, "resources/list", {"cursor": "x"}),
                    (25, "resources/read", {}),
                    (26, "resources/read", {"uri": "wizskills://syn-alpha/SKILL.md", "extra": 1}),
                ):
                    client.send_json({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
                    self.assertEqual(
                        client.read_reply(),
                        {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "Invalid params"}},
                    )

                for req_id, uri in (
                    (30, "wizskills://syn-alpha/../../outside.txt"),
                    (31, "wizskills://syn-beta/read me.md"),
                    (32, "wizskills://syn-alpha/dir-link/secret.txt"),
                ):
                    client.send_json({"jsonrpc": "2.0", "id": req_id, "method": "resources/read", "params": {"uri": uri}})
                    self.assertEqual(
                        client.read_reply(),
                        {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32002, "message": "Resource not found"}},
                    )

                client.send_json({"jsonrpc": "2.0", "id": 33, "method": "prompts/list"})
                self.assertEqual(
                    [p["name"] for p in client.read_reply()["result"]["prompts"]],
                    ["syn-alpha", "syn-beta"],
                )
                code, remaining, stderr = client.close()
            except Exception:
                client.proc.kill()
                client.proc.wait(timeout=5)
                raise
            self.assertEqual(code, 0, stderr)
            self.assertEqual(remaining, b"")
            self.assertEqual(stderr, "")

    def test_runtime_confinement_refuses_post_startup_symlink_swap(self):
        fixture = json.loads(PROTOCOL_FIXTURE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            checkout = Path(tmp)
            materialize_checkout(checkout, fixture)
            swap_path = checkout / "skills" / "syn-alpha" / "swap.txt"
            swap_path.write_text("safe\n", encoding="utf-8")

            client = StdioClient(checkout)
            try:
                client.send_json({"jsonrpc": "2.0", "id": 1, "method": "resources/list"})
                uris = [r["uri"] for r in client.read_reply()["result"]["resources"]]
                self.assertIn("wizskills://syn-alpha/swap.txt", uris)

                swap_path.unlink()
                os.symlink("../../outside.txt", swap_path)

                client.send_json({
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "resources/read",
                    "params": {"uri": "wizskills://syn-alpha/swap.txt"},
                })
                self.assertEqual(
                    client.read_reply(),
                    {"jsonrpc": "2.0", "id": 2, "error": {"code": -32002, "message": "Resource not found"}},
                )
                code, remaining, stderr = client.close()
            except Exception:
                client.proc.kill()
                client.proc.wait(timeout=5)
                raise
            self.assertEqual(code, 0, stderr)
            self.assertEqual(remaining, b"")
            self.assertEqual(stderr, "")

    def test_startup_refusals_and_filter_hook(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does-not-exist"
            res = subprocess.run(
                [sys.executable, "-I", str(SERVER), "--from", str(missing)],
                input="",
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(res.returncode, 0)
            self.assertEqual(res.stdout, "")
            self.assertIn("source-unavailable", res.stderr)

            empty_dir = Path(tmp) / "no-skills"
            empty_dir.mkdir()
            res = subprocess.run(
                [sys.executable, "-I", str(SERVER), "--from", str(empty_dir)],
                input="",
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(res.returncode, 0)
            self.assertEqual(res.stdout, "")
            self.assertIn("source-unavailable", res.stderr)

            checkout = Path(tmp) / "checkout"
            fixture = json.loads(PROTOCOL_FIXTURE.read_text(encoding="utf-8"))
            materialize_checkout(checkout, fixture)
            inventory = server_mod.load_inventory(checkout, skill_filter=lambda names: ["syn-alpha"])
            self.assertEqual(list(inventory.skills), ["syn-alpha"])
            self.assertTrue(all(u.startswith("wizskills://syn-alpha/") for u in inventory.resources))
            self.assertEqual(
                server_mod.handle_request(
                    {"jsonrpc": "2.0", "id": 1, "method": "prompts/get", "params": {"name": "syn-beta"}},
                    inventory,
                ),
                {"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "Invalid params"}},
            )
            self.assertEqual(
                server_mod.handle_request(
                    {"jsonrpc": "2.0", "id": 2, "method": "resources/read", "params": {"uri": "wizskills://syn-beta/SKILL.md"}},
                    inventory,
                ),
                {"jsonrpc": "2.0", "id": 2, "error": {"code": -32002, "message": "Resource not found"}},
            )
            with self.assertRaises(server_mod.StartupError) as ctx:
                server_mod.load_inventory(checkout, skill_filter=lambda names: ["syn-absent"])
            self.assertEqual(ctx.exception.reason, "unknown-skill")


if __name__ == "__main__":
    unittest.main(verbosity=2)
