import json
from pathlib import Path
import runpy
import unittest

FIXTURES = Path(__file__).resolve().parent
CONTRACTS = FIXTURES.parents[1]
REPO = "example-org/example-repo"

VALIDATOR_SOURCE = CONTRACTS.parent / "skills/dream-cycle/test/test_contract.py"
VALIDATE = runpy.run_path(str(VALIDATOR_SOURCE))["validate"]


def validate_output(schema, output):
    VALIDATE(schema, schema, output)
    lines = output["stdout"]
    if schema["properties"]["stdout"].get("uniqueItems") and len(lines) != len(set(lines)):
        raise ValueError("$.stdout: uniqueItems not met")


class GitHubEventsContractTests(unittest.TestCase):
    def fixture_outputs(self):
        paths = sorted(FIXTURES.glob("*.json"))
        self.assertTrue(paths, "no GitHub events fixtures")
        for path in paths:
            fixture = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(fixture["deliveries"], path.name)
            for delivery in fixture["deliveries"]:
                yield path.name, delivery["expected"]

    def schema(self):
        path = CONTRACTS / "github-events.v1.schema.json"
        self.assertTrue(path.is_file(), f"missing {path.name}")
        return json.loads(path.read_text(encoding="utf-8"))

    def test_contract_names_the_operational_rules(self):
        path = CONTRACTS / "github-events.v1.md"
        self.assertTrue(path.is_file(), f"missing {path.name}")
        contract = path.read_text(encoding="utf-8")
        for term in ("openwiz.github-events.v1", "check spec <S>", "X-GitHub-Delivery",
                     ".openwiz/home/github-events.json", "1,000", "X-Hub-Signature-256",
                     "OPENWIZ_WEBHOOK_SECRET", "30-minute"):
            with self.subTest(term=term):
                self.assertIn(term, contract)

    def test_schema_accepts_each_expected_output(self):
        schema = self.schema()
        for name, expected in self.fixture_outputs():
            with self.subTest(fixture=name, expected=expected):
                validate_output(schema, expected)
                specs = [int(line.removeprefix("check spec ")) for line in expected["stdout"]]
                self.assertEqual(specs, sorted(set(specs)))

    def test_router_command_with_header_and_body_files(self):
        contract = (CONTRACTS / "github-events.v1.md").read_text(encoding="utf-8")
        invocation = contract.partition("\n## Router command\n")[2].split("\n## ", 1)[0]
        self.assertIn(
            "`skills/launch-fleet/scripts/events.py --headers <file> --body <file>`",
            invocation,
            "the router command must accept explicit header and body files",
        )

    def test_router_command_with_body_on_stdin(self):
        contract = (CONTRACTS / "github-events.v1.md").read_text(encoding="utf-8")
        invocation = contract.partition("\n## Router command\n")[2].split("\n## ", 1)[0]
        self.assertRegex(
            invocation,
            r"(?m)^- Without headers, .*`skills/launch-fleet/scripts/events\.py`.*standard input",
            "the router command must accept a body on stdin when headers are unavailable",
        )

    def test_schema_rejects_malformed_outputs(self):
        schema = self.schema()
        for malformed in (
            {"exit_code": 0},
            {"exit_code": 0, "stdout": "check spec 82"},
            {"exit_code": 0, "stdout": ["check spec 82\n"]},
            {"exit_code": 0, "stdout": ["check spec 82\ncheck spec 1008"]},
            {"exit_code": 0, "stdout": ["check spec 0"]},
            {"exit_code": 0, "stdout": ["check spec 82", "check spec 82"]},
            {"exit_code": 2, "stdout": ["check spec 82"]},
            {"exit_code": 1, "stdout": []},
        ):
            with self.subTest(malformed=malformed), self.assertRaises(ValueError):
                validate_output(schema, malformed)

    def test_fixtures_cover_dispatch_and_use_synthetic_identifiers(self):
        paths = sorted(FIXTURES.glob("*.json"))
        self.assertTrue(paths, "no GitHub events fixtures")
        dispatch = set()
        for path in paths:
            with self.subTest(fixture=path.name):
                fixture = json.loads(path.read_text(encoding="utf-8"))
                self.assertSetEqual(set(fixture) - {"ledger_fill", "secret_configured"},
                                    {"closing_tickets", "parents", "deliveries"})
                refs = list(fixture["closing_tickets"]) + list(fixture["parents"])
                for tickets in fixture["closing_tickets"].values():
                    refs.extend(tickets)
                refs.extend(parent for parent in fixture["parents"].values() if parent is not None)
                for ref in refs:
                    self.assertRegex(ref, rf"\A{REPO}#[1-9][0-9]*\Z")
                for delivery in fixture["deliveries"]:
                    headers, body = delivery["headers"], delivery["body"]
                    self.assertEqual(body["repository"]["full_name"], REPO)
                    self.assertNotRegex(json.dumps(delivery), r'"(?:login|sender|secret|token)"\s*:')
                    if headers is not None:
                        self.assertRegex(headers["X-GitHub-Delivery"], r"\Aexample-[a-z0-9-]+\Z")
                        if delivery["expected"]["stdout"]:
                            dispatch.add((headers["X-GitHub-Event"], body["action"]))
        self.assertEqual(dispatch, {
            ("check_suite", "completed"), ("check_run", "completed"),
            ("pull_request", "closed"), ("pull_request", "synchronize"),
            ("pull_request_review", "submitted"), ("issue_comment", "created"),
            ("issues", "labeled"), ("issues", "unlabeled"),
        })


if __name__ == "__main__":
    unittest.main()
