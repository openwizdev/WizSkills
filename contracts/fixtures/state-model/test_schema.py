import json
import math
from pathlib import Path
import re
import unittest

HERE = Path(__file__).resolve().parent
SCHEMA = HERE.parents[1] / "state-model.v1.schema.json"
TYPES = {
    "array": lambda value: type(value) is list,
    "boolean": lambda value: type(value) is bool,
    "integer": lambda value: type(value) is int or (
        type(value) is float and math.isfinite(value) and value.is_integer()
    ),
    "object": lambda value: type(value) is dict,
    "string": lambda value: type(value) is str,
}
KEYWORDS = {
    "$defs", "$id", "$ref", "$schema", "title", "type", "const", "enum",
    "anyOf", "required", "properties", "propertyNames", "additionalProperties",
    "items", "minItems", "maxItems", "uniqueItems", "minLength", "pattern",
    "minimum", "maximum",
}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def equal(left, right):
    if type(left) is bool or type(right) is bool:
        return type(left) is type(right) and left == right
    return left == right


def matches(root, rule, value):
    if type(rule) is bool:
        return rule
    assert not (rule.keys() - KEYWORDS), rule.keys() - KEYWORDS
    if "$ref" in rule:
        prefix = "#/$defs/"
        assert rule["$ref"].startswith(prefix), rule["$ref"]
        if not matches(root, root["$defs"][rule["$ref"][len(prefix):]], value):
            return False
    if "type" in rule and not TYPES[rule["type"]](value):
        return False
    if "const" in rule and not equal(value, rule["const"]):
        return False
    if "enum" in rule and not any(equal(value, item) for item in rule["enum"]):
        return False
    if "anyOf" in rule and not any(matches(root, child, value) for child in rule["anyOf"]):
        return False
    if type(value) is dict:
        properties = rule.get("properties", {})
        extra = rule.get("additionalProperties", {})
        return (
            value.keys() >= set(rule.get("required", []))
            and all(matches(root, rule.get("propertyNames", {}), key) for key in value)
            and all(matches(root, properties.get(key, extra), item) for key, item in value.items())
        )
    if type(value) is list:
        return (
            rule.get("minItems", 0) <= len(value) <= rule.get("maxItems", len(value))
            and (
                not rule.get("uniqueItems")
                or all(not equal(item, other) for i, item in enumerate(value) for other in value[:i])
            )
            and all(matches(root, rule.get("items", {}), item) for item in value)
        )
    if type(value) is str:
        return len(value) >= rule.get("minLength", 0) and re.search(rule.get("pattern", ""), value) is not None
    if TYPES["integer"](value):
        return rule.get("minimum", value) <= value <= rule.get("maximum", value)
    return True


def model_matches(schema, model):
    if not matches(schema, schema, model):
        return False
    if "variableName" not in schema.get("$defs", {}):
        return True
    names = list(model["variables"])
    declaration = {**schema["$defs"]["variableName"], "enum": names} if names else False
    bound_schema = {**schema, "$defs": {**schema["$defs"], "variableName": declaration}}
    return matches(bound_schema, bound_schema, model)


class StateModelSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = read(SCHEMA) if SCHEMA.is_file() else {}
        cls.cases = read(HERE / "expected.json")

    def test_schema_declares_the_model_and_report(self):
        self.assertEqual(self.schema.get("title"), "openwiz.state-model.v1")
        self.assertIn("report", self.schema["$defs"])

    def test_fixture_models_are_accepted_or_refused(self):
        self.assertEqual(set(self.cases), {path.stem for path in HERE.glob("*.json")} - {"expected"})
        for name, expected in self.cases.items():
            with self.subTest(model=name):
                model = read(HERE / f"{name}.json")
                self.assertEqual(model_matches(self.schema, model), expected["exit"] != 2)

    def test_expected_reports_match_status_exit_and_shape(self):
        exits = {"ok": 0, "counterexample": 1, "invalid": 2, "bound-reached": 3}
        report = self.schema.get("$defs", {}).get("report", {})
        for name, expected in self.cases.items():
            with self.subTest(model=name):
                self.assertEqual(expected["exit"], exits[expected["report"]["status"]])
                self.assertTrue(matches(self.schema, report, expected["report"]))
        self.assertFalse(matches(self.schema, report, {"status": "counterexample", "statesExplored": 1}))
        self.assertFalse(matches(self.schema, report, {"status": "ok", "statesExplored": 0}))

    def test_references_in_assignment_targets_are_checked(self):
        model = read(HERE / "ok.json")
        model["actions"][0]["effect"][0]["var"] = "undeclared"
        self.assertFalse(model_matches(self.schema, model))


if __name__ == "__main__":
    unittest.main()
