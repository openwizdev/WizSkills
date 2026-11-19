"""Validate a saved short-road decision from openwiz.decisions.v1."""

import hashlib
import json
from pathlib import Path
import re
import sys


FIELDS = {
    "schema", "kind", "id", "status", "fingerprint", "risk", "ticket",
    "title", "owned_paths", "acceptance", "proof", "approvals",
}
PRIVATE_POINTER = re.compile(
    r"https://github[.]com/[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9][A-Za-z0-9_.-]*/"
    r"(?:issues|pull)/[1-9][0-9]*#issuecomment-[1-9][0-9]*"
)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        require(key not in obj, "duplicate JSON key")
        obj[key] = value
    return obj


def invalid_number(_):
    raise ValueError("decision numbers must be JSON integers")


def text(value):
    return isinstance(value, str) and bool(value)


def text_list(value):
    return isinstance(value, list) and bool(value) and all(map(text, value))


def check_batch(edits, owned_paths):
    require(isinstance(edits, list) and edits, "batch must list its edits")
    seen = set()
    for edit in edits:
        require(isinstance(edit, dict) and edit.keys() == {"path", "change", "mechanical"},
                "batch edit needs path, change and mechanical")
        require(edit["mechanical"] is True, "every batch edit must be mechanical")
        path, change = edit["path"], edit["change"]
        require(text(path) and text(change), "batch edit needs a path and change")
        require(path in owned_paths, "batch edit path must be owned")
        require((path, change) not in seen, "batch edits must be distinct")
        seen.add((path, change))


def check(plan):
    require(isinstance(plan, dict) and plan.get("schema") == "openwiz.decisions.v1",
            "expected an openwiz.decisions.v1 object")
    kind = plan.get("kind")
    require(kind in ("one_card_plan", "batch_plan"), "expected one_card_plan or batch_plan")
    fields = FIELDS | {"edits"} if kind == "batch_plan" else FIELDS
    require(plan.keys() == fields, "invalid short-road plan fields")
    require(plan["risk"] == "ordinary", "risk requires the big road")
    require(plan["status"] == "resolved", "short-road plan must be resolved")
    require(isinstance(plan["approvals"], list) and len(plan["approvals"]) == 1,
            "short-road plan needs exactly one recorded yes")
    pointer = plan["approvals"][0]
    require(text(pointer) and PRIVATE_POINTER.fullmatch(pointer),
            "approval needs a private-record comment pointer")
    require(text(plan["id"]) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", plan["id"]),
            "invalid decision id")
    require(type(plan["ticket"]) is int and plan["ticket"] > 0,
            "ticket must be a positive integer")
    require(text(plan["title"]) and text(plan["proof"]), "card needs a title and proof")
    paths = plan["owned_paths"]
    require(text_list(paths) and len(paths) == len(set(paths)), "card needs distinct owned paths")
    require(text_list(plan["acceptance"]), "card needs acceptance criteria")
    if kind == "batch_plan":
        check_batch(plan["edits"], set(paths))

    proposal = {k: v for k, v in plan.items() if k not in {"fingerprint", "status", "approvals"}}
    canonical = json.dumps(proposal, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    try:
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    except UnicodeError:
        raise ValueError("proposal needs valid Unicode") from None
    require(plan["fingerprint"] == fingerprint, "fingerprint does not match the proposal")


def main(path):
    try:
        with Path(path).open(encoding="utf-8") as source:
            plan = json.load(source, object_pairs_hook=unique_object,
                             parse_float=invalid_number, parse_constant=invalid_number)
        check(plan)
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError):
        print("check-approval.sh: cannot read strict decision JSON", file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"check-approval.sh: {error}", file=sys.stderr)
        return 1
    print("check-approval.sh: short-road approval is valid")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
