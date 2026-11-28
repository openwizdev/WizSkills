#!/usr/bin/env python3
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import sys
from urllib.parse import quote

PROTOCOL_VERSION = "2025-11-25"
SERVER_INFO = {"name": "wizskills", "version": "1"}
CAPABILITIES = {"prompts": {}, "resources": {}}
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ALLOWED_TOP_KEYS = frozenset({"jsonrpc", "id", "method", "params"})
KNOWN_METHODS = frozenset({
    "initialize",
    "prompts/list",
    "prompts/get",
    "resources/list",
    "resources/read",
})
REPO_ROOT = Path(__file__).resolve().parent.parent


class StartupError(Exception):
    def __init__(self, reason, detail=""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


class DuplicateKeyError(ValueError):
    pass


@dataclass(frozen=True)
class SkillPrompt:
    name: str
    description: str
    body: str


@dataclass(frozen=True)
class SkillResource:
    uri: str
    skill: str
    name: str
    rel_parts: tuple[str, ...]
    mime_type: str = "text/plain"


@dataclass(frozen=True)
class Inventory:
    skills_root: Path
    skills: dict[str, SkillPrompt]
    resources: dict[str, SkillResource]


def reject_duplicate_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise DuplicateKeyError(key)
        out[key] = value
    return out


def decode_yaml_scalar(rest):
    raw = rest.strip()
    if not raw or not rest.startswith(" "):
        return None
    if raw.startswith('"'):
        if len(raw) < 2 or not raw.endswith('"'):
            return None
        chars = iter(raw[1:-1])
        out = []
        for ch in chars:
            if ch == "\\":
                nxt = next(chars, None)
                if nxt is None:
                    return None
                escapes = {'"': '"', "\\": "\\", "n": "\n", "t": "\t", "r": "\r"}
                out.append(escapes.get(nxt, nxt))
            elif ch == '"':
                return None
            else:
                out.append(ch)
        return "".join(out)
    if raw.startswith("'"):
        if len(raw) < 2 or not raw.endswith("'"):
            return None
        inner = raw[1:-1]
        if "'" in inner.replace("''", ""):
            return None
        return inner.replace("''", "'")
    return raw


def parse_skill_markdown(text):
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return None
    end_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].rstrip("\r\n") == "---":
            end_idx = idx
            break
    if end_idx is None:
        return None
    values = {}
    for raw_line in lines[1:end_idx]:
        line = raw_line.rstrip("\r\n")
        key, sep, rest = line.partition(":")
        if not sep or key in values:
            continue
        parsed = decode_yaml_scalar(rest)
        if parsed is not None:
            values[key] = parsed
    name = values.get("name")
    description = values.get("description")
    if not isinstance(name, str) or not SKILL_NAME_RE.fullmatch(name):
        return None
    if not isinstance(description, str) or not description:
        return None
    body = "".join(lines[end_idx + 1 :])
    return name, description, body


def read_confined_text(skills_root, rel_parts):
    current = skills_root
    if current.is_symlink() or not current.is_dir():
        return None
    try:
        resolved_root = current.resolve(strict=True)
    except OSError:
        return None
    for idx, part in enumerate(rel_parts):
        if part in ("", ".", "..") or "/" in part or "\\" in part:
            return None
        current = current / part
        try:
            st = os.lstat(current)
        except OSError:
            return None
        if stat.S_ISLNK(st.st_mode):
            return None
        is_last = idx == len(rel_parts) - 1
        if is_last:
            if not stat.S_ISREG(st.st_mode):
                return None
        elif not stat.S_ISDIR(st.st_mode):
            return None
    try:
        resolved_target = current.resolve(strict=True)
        resolved_target.relative_to(resolved_root)
    except (OSError, ValueError):
        return None
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(current, flags)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None
        with os.fdopen(fd, "rb") as handle:
            fd = -1
            raw = handle.read()
    except OSError:
        if fd >= 0:
            os.close(fd)
        return None
    if b"\x00" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def encode_resource_uri(skill_name, rel_parts):
    encoded = "/".join(quote(segment, safe="-._~") for segment in rel_parts)
    return f"wizskills://{skill_name}/{encoded}"


def apply_filter(inventory, skill_filter):
    if skill_filter is None:
        return inventory
    selected = list(skill_filter(list(inventory.skills.keys())))
    allowed = set()
    for name in selected:
        if not isinstance(name, str) or name not in inventory.skills:
            raise StartupError("unknown-skill", f"skill not in inventory: {name}")
        allowed.add(name)
    skills = {k: v for k, v in inventory.skills.items() if k in allowed}
    resources = {u: r for u, r in inventory.resources.items() if r.skill in allowed}
    return Inventory(skills_root=inventory.skills_root, skills=skills, resources=resources)


def resolve_source(from_arg):
    if from_arg is None:
        root = REPO_ROOT
    else:
        if not isinstance(from_arg, str) or not from_arg or from_arg.startswith("github:"):
            raise StartupError("invalid-source", "expected a local checkout folder")
        root = Path(from_arg)
    if not root.exists() or not root.is_dir():
        raise StartupError("source-unavailable", "checkout folder does not exist")
    skills_dir = root / "skills"
    if skills_dir.is_symlink() or not skills_dir.is_dir():
        raise StartupError("source-unavailable", "checkout has no skills directory")
    return root.resolve(strict=True)


def walk_skill_resources(skills_root, skill_name, skill_dir):
    found = []
    stack = [(skill_dir, ())]
    while stack:
        current_dir, prefix = stack.pop()
        try:
            entries = sorted(os.scandir(current_dir), key=lambda e: e.name)
        except OSError:
            continue
        subdirs = []
        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    subdirs.append((Path(entry.path), prefix + (entry.name,)))
                elif entry.is_file(follow_symlinks=False):
                    rel_parts = prefix + (entry.name,)
                    text = read_confined_text(skills_root, (skill_name,) + rel_parts)
                    if text is not None:
                        uri = encode_resource_uri(skill_name, rel_parts)
                        found.append(
                            SkillResource(
                                uri=uri,
                                skill=skill_name,
                                name="/".join(rel_parts),
                                rel_parts=(skill_name,) + rel_parts,
                            )
                        )
            except OSError:
                continue
        for sub in reversed(subdirs):
            stack.append(sub)
    return found


def load_inventory(checkout_root, skill_filter=None):
    skills_root = Path(checkout_root) / "skills"
    if skills_root.is_symlink() or not skills_root.is_dir():
        raise StartupError("source-unavailable", "checkout has no skills directory")
    skills_root = skills_root.resolve(strict=True)
    skills = {}
    resources_list = []
    try:
        entries = sorted(os.scandir(skills_root), key=lambda e: e.name)
    except OSError as exc:
        raise StartupError("source-unavailable", "cannot read skills directory") from exc
    for entry in entries:
        try:
            if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                continue
        except OSError:
            continue
        folder = entry.name
        if not SKILL_NAME_RE.fullmatch(folder):
            continue
        skill_text = read_confined_text(skills_root, (folder, "SKILL.md"))
        if skill_text is None:
            continue
        parsed = parse_skill_markdown(skill_text)
        if parsed is None:
            continue
        name, description, body = parsed
        if name != folder:
            continue
        skills[name] = SkillPrompt(name=name, description=description, body=body)
        resources_list.extend(walk_skill_resources(skills_root, name, Path(entry.path)))
    ordered_skills = {name: skills[name] for name in sorted(skills)}
    resources_list.sort(key=lambda item: item.uri)
    ordered_resources = {item.uri: item for item in resources_list}
    inventory = Inventory(
        skills_root=skills_root,
        skills=ordered_skills,
        resources=ordered_resources,
    )
    return apply_filter(inventory, skill_filter)


def valid_request_id(value):
    return isinstance(value, (str, int)) and not isinstance(value, bool)


def error_reply(code, message, req_id=None, include_id=False):
    out = {"jsonrpc": "2.0", "error": {"code": code, "message": message}}
    if include_id:
        out["id"] = req_id
    return out


def result_reply(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def validate_initialize_params(params):
    if not isinstance(params, dict):
        return False
    version = params.get("protocolVersion")
    capabilities = params.get("capabilities")
    client_info = params.get("clientInfo")
    if not isinstance(version, str) or not version:
        return False
    if not isinstance(capabilities, dict):
        return False
    if not isinstance(client_info, dict) or not isinstance(client_info.get("name"), str):
        return False
    return True


def handle_request(obj, inventory):
    if not isinstance(obj, dict):
        return error_reply(-32600, "Invalid Request")
    has_id = "id" in obj
    req_id = obj.get("id")
    if has_id and not valid_request_id(req_id):
        return error_reply(-32600, "Invalid Request")
    if not set(obj.keys()).issubset(ALLOWED_TOP_KEYS):
        return error_reply(-32600, "Invalid Request", req_id, include_id=has_id)
    if obj.get("jsonrpc") != "2.0":
        return error_reply(-32600, "Invalid Request", req_id, include_id=has_id)
    method = obj.get("method")
    if not isinstance(method, str) or not method:
        return error_reply(-32600, "Invalid Request", req_id, include_id=has_id)
    has_params = "params" in obj
    params = obj.get("params")
    if not has_id:
        if has_params and not isinstance(params, dict):
            return error_reply(-32600, "Invalid Request")
        return None
    if method not in KNOWN_METHODS:
        return error_reply(-32601, "Method not found", req_id, include_id=True)
    if method == "initialize":
        if not validate_initialize_params(params):
            return error_reply(-32602, "Invalid params", req_id, include_id=True)
        return result_reply(
            req_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": CAPABILITIES,
                "serverInfo": SERVER_INFO,
            },
        )
    if method == "prompts/list":
        if has_params and params != {}:
            return error_reply(-32602, "Invalid params", req_id, include_id=True)
        prompts = [
            {"name": item.name, "description": item.description}
            for item in inventory.skills.values()
        ]
        return result_reply(req_id, {"prompts": prompts})
    if method == "prompts/get":
        if not isinstance(params, dict):
            return error_reply(-32602, "Invalid params", req_id, include_id=True)
        if not set(params.keys()).issubset({"name", "arguments"}):
            return error_reply(-32602, "Invalid params", req_id, include_id=True)
        name = params.get("name")
        if not isinstance(name, str) or not name:
            return error_reply(-32602, "Invalid params", req_id, include_id=True)
        if "arguments" in params and params["arguments"] != {}:
            return error_reply(-32602, "Invalid params", req_id, include_id=True)
        skill = inventory.skills.get(name)
        if skill is None:
            return error_reply(-32602, "Invalid params", req_id, include_id=True)
        return result_reply(
            req_id,
            {
                "description": skill.description,
                "messages": [
                    {
                        "role": "user",
                        "content": {"type": "text", "text": skill.body},
                    }
                ],
            },
        )
    if method == "resources/list":
        if has_params and params != {}:
            return error_reply(-32602, "Invalid params", req_id, include_id=True)
        resources = [
            {"uri": item.uri, "name": item.name, "mimeType": item.mime_type}
            for item in inventory.resources.values()
        ]
        return result_reply(req_id, {"resources": resources})
    if not isinstance(params, dict) or set(params.keys()) != {"uri"}:
        return error_reply(-32602, "Invalid params", req_id, include_id=True)
    uri = params.get("uri")
    if not isinstance(uri, str) or not uri:
        return error_reply(-32602, "Invalid params", req_id, include_id=True)
    resource = inventory.resources.get(uri)
    if resource is None:
        return error_reply(-32002, "Resource not found", req_id, include_id=True)
    text = read_confined_text(inventory.skills_root, resource.rel_parts)
    if text is None:
        return error_reply(-32002, "Resource not found", req_id, include_id=True)
    return result_reply(
        req_id,
        {"contents": [{"uri": resource.uri, "mimeType": resource.mime_type, "text": text}]},
    )


def handle_line(raw_line, inventory):
    try:
        text = raw_line.decode("utf-8")
    except UnicodeDecodeError:
        return error_reply(-32700, "Parse error")
    try:
        obj = json.loads(text, object_pairs_hook=reject_duplicate_keys)
    except DuplicateKeyError:
        return error_reply(-32600, "Invalid Request")
    except ValueError:
        return error_reply(-32700, "Parse error")
    return handle_request(obj, inventory)


def serve(inventory, stdin, stdout):
    while True:
        raw_line = stdin.readline()
        if not raw_line:
            return 0
        reply = handle_line(raw_line, inventory)
        if reply is not None:
            encoded = json.dumps(reply, ensure_ascii=False, separators=(",", ":")) + "\n"
            stdout.write(encoded.encode("utf-8"))
            stdout.flush()


def parse_args(argv):
    from_arg = None
    idx = 0
    while idx < len(argv):
        token = argv[idx]
        if token == "--from":
            if idx + 1 >= len(argv) or from_arg is not None:
                raise StartupError("invalid-source", "usage: server.py [--from <folder>]")
            from_arg = argv[idx + 1]
            idx += 2
        elif token.startswith("--from="):
            if from_arg is not None:
                raise StartupError("invalid-source", "usage: server.py [--from <folder>]")
            from_arg = token.split("=", 1)[1]
            idx += 1
        else:
            raise StartupError("invalid-source", "unknown argument")
    return from_arg


def main(argv=None, skill_filter=None):
    args = sys.argv[1:] if argv is None else list(argv)
    try:
        from_arg = parse_args(args)
        checkout_root = resolve_source(from_arg)
        inventory = load_inventory(checkout_root, skill_filter=skill_filter)
    except StartupError as exc:
        sys.stderr.write(f"wizskills-mcp: {exc.reason}\n")
        sys.stderr.flush()
        return 2
    return serve(inventory, sys.stdin.buffer, sys.stdout.buffer)


if __name__ == "__main__":
    raise SystemExit(main())
