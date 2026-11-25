#!/usr/bin/env python3
import json
import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CONTRACT_MD = ROOT / "contracts" / "dream-cycle.v1.md"
SCHEMA_PATH = ROOT / "contracts" / "dream-cycle.v1.schema.json"
FIXTURES = HERE / "fixtures" / "contract"

ALLOWED_KEYWORDS = {
    "$schema", "$id", "$defs", "$ref", "title", "description", "type",
    "required", "properties", "additionalProperties", "items", "enum",
    "const", "oneOf", "allOf", "if", "then", "not", "minimum", "maximum",
    "minLength", "maxLength", "minItems", "maxItems", "pattern",
}

TEN_LINK_TYPES = [
    "says-vs-does",
    "promise-to-work",
    "need-to-person",
    "enemy-move-to-us",
    "spend-to-use",
    "answers",
    "pattern",
    "duplicates",
    "drifted-copy",
    "contradicts",
]

FIVE_LINK_ROUTES = [
    "ticket",
    "pillar-inbox",
    "people-draft",
    "question-comment",
    "spec-candidate",
]

LEDGER_STATES = {
    "proposed",
    "accepted",
    "rejected",
    "later",
    "expired",
    "superseded",
}

REPORT_SECTIONS = [
    "## Areas",
    "## Top deletes",
    "## Top fixes",
    "## Top links",
    "## Rejected",
    "## Unconfirmed reads",
    "## Tickets filed",
]


def _no_duplicates(pairs):
    seen = set()
    out = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"duplicate key: {key}")
        seen.add(key)
        out[key] = value
    return out


def parse_json_strict(raw):
    return json.loads(raw, object_pairs_hook=_no_duplicates)


def _resolve_ref(schema, ref):
    if not ref.startswith("#/$defs/"):
        raise ValueError(f"unresolved $ref: {ref}")
    name = ref[len("#/$defs/"):]
    if name not in schema.get("$defs", {}):
        raise ValueError(f"unknown $defs entry: {name}")
    return schema["$defs"][name]


def lint_schema(schema):
    def walk(node):
        unknown = set(node) - ALLOWED_KEYWORDS
        if unknown:
            raise ValueError(f"unsupported schema keywords: {sorted(unknown)}")
        if "$ref" in node:
            _resolve_ref(schema, node["$ref"])
        for group in ("$defs", "properties"):
            for child in node.get(group, {}).values():
                walk(child)
        for group in ("oneOf", "allOf"):
            for child in node.get(group, []):
                walk(child)
        for key in ("if", "then", "not", "items"):
            if key in node:
                walk(node[key])
    walk(schema)


def _check_type(expected, value, path):
    type_map = {
        "object": dict,
        "array": list,
        "string": str,
        "integer": int,
        "boolean": bool,
        "null": type(None),
    }
    allowed = expected if isinstance(expected, list) else [expected]
    if not any(type(value) is type_map[t] for t in allowed):
        raise ValueError(f"{path}: expected type {expected}, got {type(value).__name__}")


def validate(schema, node, value, path="$"):
    if "$ref" in node:
        validate(schema, _resolve_ref(schema, node["$ref"]), value, path)
    if "type" in node:
        _check_type(node["type"], value, path)
    if "const" in node:
        expected = node["const"]
        if type(value) is not type(expected) or value != expected:
            raise ValueError(f"{path}: const mismatch (expected {expected!r})")
    if "enum" in node:
        if not any(type(value) is type(item) and value == item for item in node["enum"]):
            raise ValueError(f"{path}: value {value!r} not in enum {node['enum']!r}")
    if "not" in node:
        matched = True
        try:
            validate(schema, node["not"], value, path)
        except ValueError:
            matched = False
        if matched:
            raise ValueError(f"{path}: matched forbidden 'not' schema")
    if type(value) is dict:
        required = node.get("required", [])
        for key in required:
            if key not in value:
                raise ValueError(f"{path}: missing required key {key!r}")
        props = node.get("properties", {})
        if node.get("additionalProperties") is False:
            extra = sorted(set(value) - set(props))
            if extra:
                raise ValueError(f"{path}: extra keys not allowed: {extra!r}")
        for key, child in value.items():
            if key in props:
                validate(schema, props[key], child, f"{path}.{key}")
    if type(value) is list:
        if "minItems" in node and len(value) < node["minItems"]:
            raise ValueError(f"{path}: minItems {node['minItems']} not met (got {len(value)})")
        if "maxItems" in node and len(value) > node["maxItems"]:
            raise ValueError(f"{path}: maxItems {node['maxItems']} exceeded (got {len(value)})")
        if "items" in node:
            for idx, item in enumerate(value):
                validate(schema, node["items"], item, f"{path}[{idx}]")
    if type(value) is str:
        if "minLength" in node and len(value) < node["minLength"]:
            raise ValueError(f"{path}: minLength {node['minLength']} not met")
        if "maxLength" in node and len(value) > node["maxLength"]:
            raise ValueError(f"{path}: maxLength {node['maxLength']} exceeded")
        if "pattern" in node and re.fullmatch(node["pattern"], value) is None:
            raise ValueError(f"{path}: pattern {node['pattern']!r} not matched")
    if type(value) is int:
        if "minimum" in node and value < node["minimum"]:
            raise ValueError(f"{path}: minimum {node['minimum']} not met (got {value})")
        if "maximum" in node and value > node["maximum"]:
            raise ValueError(f"{path}: maximum {node['maximum']} exceeded (got {value})")
    if "allOf" in node:
        for idx, sub in enumerate(node["allOf"]):
            validate(schema, sub, value, path)
    if "if" in node and "then" in node:
        matched = True
        try:
            validate(schema, node["if"], value, path)
        except ValueError:
            matched = False
        if matched:
            validate(schema, node["then"], value, path)
    if "oneOf" in node:
        matches = 0
        errors = []
        for sub in node["oneOf"]:
            try:
                validate(schema, sub, value, path)
                matches += 1
            except ValueError as exc:
                errors.append(str(exc))
        if matches != 1:
            raise ValueError(f"{path}: oneOf matched {matches} branches ({'; '.join(errors)})")


class DreamCycleContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not SCHEMA_PATH.is_file():
            cls.schema = None
        else:
            cls.schema = parse_json_strict(SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_contract_markdown_and_schema_exist(self):
        self.assertTrue(CONTRACT_MD.is_file(), f"missing {CONTRACT_MD}")
        self.assertTrue(SCHEMA_PATH.is_file(), f"missing {SCHEMA_PATH}")
        lint_schema(self.schema)
        md = CONTRACT_MD.read_text(encoding="utf-8")
        for needle in (
            "dream-cycle.v1",
            "docs/agents/dream-cycle.md",
            "Loops",
            "CONFIRMED",
            "PLAUSIBLE",
            "REJECTED",
            "## Top deletes",
            "## Top fixes",
            "## Top links",
            "## Rejected",
            "## Unconfirmed reads",
            "## Tickets filed",
            "link_budget",
        ):
            self.assertIn(needle, md, f"contract doc missing {needle!r}")

    def test_link_types_and_routes_listed_once_matching_schema(self):
        self.assertIsNotNone(self.schema, f"missing {SCHEMA_PATH}")
        defs = self.schema.get("$defs", {})
        self.assertIn("link_type", defs)
        self.assertIn("link_route", defs)
        self.assertEqual(defs["link_type"]["enum"], TEN_LINK_TYPES + ["unknown"])
        self.assertEqual(defs["link_route"]["enum"], FIVE_LINK_ROUTES)

        md = CONTRACT_MD.read_text(encoding="utf-8")
        self.assertEqual(md.count("### Link types"), 1)
        self.assertEqual(md.count("### Link routes"), 1)

        def _table_first_column(heading):
            match = re.search(
                rf"^{re.escape(heading)}\n+(.*?)(?=\n##|\Z)",
                md,
                flags=re.MULTILINE | re.DOTALL,
            )
            self.assertIsNotNone(match, f"missing section {heading!r}")
            rows = []
            for line in match.group(1).splitlines():
                cell = re.match(r"^\|\s*`([^`]+)`\s*\|", line)
                if cell:
                    rows.append(cell.group(1))
            return rows

        type_rows = _table_first_column("### Link types")
        route_rows = _table_first_column("### Link routes")
        self.assertEqual(type_rows, TEN_LINK_TYPES + ["unknown"])
        self.assertEqual(route_rows, FIVE_LINK_ROUTES)

        for path in (ROOT / "skills" / "dream-cycle").rglob("*.md"):
            text = path.read_text(encoding="utf-8")
            self.assertFalse(
                all(t in text for t in TEN_LINK_TYPES),
                f"link types duplicated outside contract in {path}",
            )
            self.assertFalse(
                all(r in text for r in FIVE_LINK_ROUTES),
                f"link routes duplicated outside contract in {path}",
            )

    def test_valid_findings_pass_schema(self):
        self.assertIsNotNone(self.schema, f"missing {SCHEMA_PATH}")
        lines = [
            line for line in (FIXTURES / "valid_findings.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertGreaterEqual(len(lines), 4)
        kinds = set()
        repos = set()
        for idx, raw in enumerate(lines, 1):
            with self.subTest(line=idx):
                record = parse_json_strict(raw)
                validate(self.schema, {"$ref": "#/$defs/finding"}, record)
                kinds.add(record["kind"])
                repos.add(record["repo"])
        self.assertEqual(kinds, {"delete", "fix", "link", "summary"})
        self.assertIn("Loops", repos)

    def test_invalid_findings_fail_with_reason(self):
        self.assertIsNotNone(self.schema, f"missing {SCHEMA_PATH}")
        cases = json.loads((FIXTURES / "invalid_findings.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cases), 8)
        for case in cases:
            with self.subTest(case=case["name"]):
                with self.assertRaises(ValueError) as ctx:
                    record = parse_json_strict(case["raw"])
                    validate(self.schema, {"$ref": "#/$defs/finding"}, record)
                self.assertIn(case["expected_reason"], str(ctx.exception))

    def test_valid_verdicts_pass_schema(self):
        self.assertIsNotNone(self.schema, f"missing {SCHEMA_PATH}")
        lines = [
            line for line in (FIXTURES / "valid_verdicts.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        verdicts = set()
        for idx, raw in enumerate(lines, 1):
            with self.subTest(line=idx):
                record = parse_json_strict(raw)
                validate(self.schema, {"$ref": "#/$defs/verdict"}, record)
                verdicts.add(record["verdict"])
        self.assertEqual(verdicts, {"CONFIRMED", "PLAUSIBLE", "REJECTED"})

    def test_invalid_verdicts_fail_with_reason(self):
        self.assertIsNotNone(self.schema, f"missing {SCHEMA_PATH}")
        cases = json.loads((FIXTURES / "invalid_verdicts.json").read_text(encoding="utf-8"))
        for case in cases:
            with self.subTest(case=case["name"]):
                with self.assertRaises(ValueError) as ctx:
                    record = parse_json_strict(case["raw"])
                    validate(self.schema, {"$ref": "#/$defs/verdict"}, record)
                self.assertIn(case["expected_reason"], str(ctx.exception))

    def test_valid_and_invalid_inventory_fixtures(self):
        self.assertIsNotNone(self.schema, f"missing {SCHEMA_PATH}")
        valid = json.loads((FIXTURES / "valid_inventory.json").read_text(encoding="utf-8"))
        for name, value in valid.items():
            with self.subTest(valid=name):
                validate(self.schema, {"$ref": "#/$defs/inventory"}, value)
        invalid = json.loads((FIXTURES / "invalid_inventory.json").read_text(encoding="utf-8"))
        for case in invalid:
            with self.subTest(invalid=case["name"]):
                with self.assertRaises(ValueError) as ctx:
                    validate(self.schema, {"$ref": "#/$defs/inventory"}, case["value"])
                self.assertIn(case["expected_reason"], str(ctx.exception))

    def test_valid_links_pass_schema(self):
        self.assertIsNotNone(self.schema, f"missing {SCHEMA_PATH}")
        lines = [
            line for line in (FIXTURES / "valid_links.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertGreaterEqual(len(lines), 5)
        routes = set()
        types = set()
        for idx, raw in enumerate(lines, 1):
            with self.subTest(line=idx):
                record = parse_json_strict(raw)
                self.assertEqual(record["kind"], "link")
                validate(self.schema, {"$ref": "#/$defs/finding"}, record)
                routes.add(record["route"])
                types.add(record["link_type"])
        self.assertEqual(routes, set(FIVE_LINK_ROUTES))
        self.assertIn("pattern", types)
        self.assertIn("unknown", types)

    def test_invalid_links_fail_with_reason(self):
        self.assertIsNotNone(self.schema, f"missing {SCHEMA_PATH}")
        cases = json.loads((FIXTURES / "invalid_links.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cases), 15)
        for case in cases:
            with self.subTest(case=case["name"]):
                with self.assertRaises(ValueError) as ctx:
                    record = parse_json_strict(case["raw"])
                    validate(self.schema, {"$ref": "#/$defs/finding"}, record)
                self.assertIn(case["expected_reason"], str(ctx.exception))

    def test_valid_ledger_passes_schema(self):
        self.assertIsNotNone(self.schema, f"missing {SCHEMA_PATH}")
        lines = [
            line for line in (FIXTURES / "valid_ledger.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertGreaterEqual(len(lines), 6)
        states = set()
        has_closed = False
        for idx, raw in enumerate(lines, 1):
            with self.subTest(line=idx):
                record = parse_json_strict(raw)
                validate(self.schema, {"$ref": "#/$defs/ledger_entry"}, record)
                states.add(record["state"])
                if record["invalid_at"] is not None:
                    has_closed = True
        self.assertEqual(states, LEDGER_STATES)
        self.assertTrue(has_closed)

    def test_invalid_ledger_fails_with_reason(self):
        self.assertIsNotNone(self.schema, f"missing {SCHEMA_PATH}")
        cases = json.loads((FIXTURES / "invalid_ledger.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cases), 10)
        for case in cases:
            with self.subTest(case=case["name"]):
                with self.assertRaises(ValueError) as ctx:
                    record = parse_json_strict(case["raw"])
                    validate(self.schema, {"$ref": "#/$defs/ledger_entry"}, record)
                self.assertIn(case["expected_reason"], str(ctx.exception))

    def test_valid_and_invalid_link_cards(self):
        self.assertIsNotNone(self.schema, f"missing {SCHEMA_PATH}")
        valid = json.loads((FIXTURES / "valid_link_cards.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(valid), 2)
        for idx, card in enumerate(valid, 1):
            with self.subTest(valid=idx):
                validate(self.schema, {"$ref": "#/$defs/link_card"}, card)
        invalid = json.loads((FIXTURES / "invalid_link_cards.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(invalid), 8)
        for case in invalid:
            with self.subTest(invalid=case["name"]):
                with self.assertRaises(ValueError) as ctx:
                    validate(self.schema, {"$ref": "#/$defs/link_card"}, case["value"])
                self.assertIn(case["expected_reason"], str(ctx.exception))

    def test_sample_report_contains_required_sections_and_loops_area(self):
        self.assertTrue(CONTRACT_MD.is_file(), f"missing {CONTRACT_MD}")
        report = (FIXTURES / "sample_report.md").read_text(encoding="utf-8")
        self.assertTrue(report.startswith("# Dream cycle report — 2030-01-15"))
        for header_field in ("- **Date:**", "- **Scope:**", "- **Window:**", "- **Counts:**"):
            self.assertIn(header_field, report)
        self.assertIn("Loops", report)
        positions = []
        for heading in REPORT_SECTIONS:
            idx = report.find(f"\n{heading}\n")
            self.assertNotEqual(idx, -1, f"missing section heading {heading!r}")
            positions.append(idx)
        self.assertEqual(positions, sorted(positions), "report sections out of contract order")
        for card_field in (
            "score ",
            "owner `",
            "route `",
            "- **End 1:**",
            "- **End 2:**",
            "- **Changes:**",
            "- **Best reason not a link:**",
        ):
            self.assertIn(card_field, report, f"sample report link card missing {card_field!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
