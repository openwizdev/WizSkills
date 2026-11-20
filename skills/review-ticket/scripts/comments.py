#!/usr/bin/env python3
import argparse
import re
import sys
from dataclasses import dataclass

HASH = {".py", ".pyi", ".sh", ".bash", ".yml", ".yaml", ".toml"}
HASH_ANYWHERE = {".py", ".pyi", ".toml"}
SLASH = {".rs", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx"}
CSS = {".css"}
HTML = {".html", ".htm"}
EXCLUDED = re.compile(r"(^|/)(vendor|vendored|third_party|third-party|node_modules)/|(^|/)fixtures/comments/"
                      r"|\.min\.(js|css)$")
LICENCE_FILE = re.compile(r"^(licen[cs]e|copying|notice)([.-].*)?$", re.I)
GENERATED = re.compile(r"@generated|\bDO NOT EDIT\b")
WORKFLOW = re.compile(r"(^|/)\.github/workflows/[^/]+\.ya?ml$|(^|/)action\.ya?ml$")
PINNED = re.compile(r"^\s*(?:-\s+)?uses:\s*([\"']?)[^\s\"'#]+@[0-9a-f]{40}\1\s*$")
VERSION = re.compile(r"^v?[0-9][0-9A-Za-z.+-]*$")
YAML_BLOCK = re.compile(r"^(\s*(?:-\s+)?)([^\s#][^#]*?):\s*[|>][0-9+-]*\s*$")
YAML_ITEM_BLOCK = re.compile(r"^(\s*)-\s+[|>][0-9+-]*\s*$")
HTML_TAG = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9-]*)")
HTML_ATTR = re.compile(r"\s*([^\s\"'>/=]+)(?:\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s\"'>]+))?")
JS_TYPES = re.compile(r"^(|module|(text|application)/(java|ecma)script)$", re.I)
SHELL = {".sh", ".bash"}
HEREDOC = re.compile(r"<<(-?)\s*([\"']?)([A-Za-z_][A-Za-z0-9_]*)\2")
TERMINATOR = re.compile(r"^\s*([A-Z_][A-Z0-9_]*)\s*$")
TRIPLE = re.compile(r"\"\"\"|'''")
ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}
HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
SHEBANG = {"python": ".py", "sh": ".sh", "bash": ".sh", "dash": ".sh", "zsh": ".sh", "node": ".js"}
DOCSTRING = re.compile(r"^\s*[rRuU]?(\"\"\"|''')")
ENCODING = re.compile(r"^#.*coding[:=]")
SWITCH = re.compile(r"^(noqa|type: ignore|pragma:|pylint:|fmt: (off|on|skip)|ruff:|mypy:|pyright:|isort:|eslint"
                    r"|prettier-ignore|@ts-ignore|@ts-expect-error|@ts-nocheck|biome-ignore|shellcheck |yamllint "
                    r"|stylelint-disable|stylelint-enable|istanbul ignore|c8 ignore|v8 ignore)")
SWITCH_REASON = re.compile(r" (--|#) \S")
RUST_ALLOW = re.compile(r"^\s*#!?\[(allow|expect)\(")
LICENCE = re.compile(r"SPDX-License-Identifier:|Copyright|Licensed under")
WARNING = re.compile(r"^(SECURITY|SAFETY|PRIVACY|DATA LOSS):\s*\S")
POINTER = re.compile(r"https://github\.com/jparker2006/ClosedWiz/(issues|pull)/[1-9]\d*#issuecomment-[1-9]\d*")
LINK = re.compile(r"https?://\S+")
OURS = re.compile(r"https?://github\.com/(openwizdev|jparker2006)/", re.I)
WORKAROUND = re.compile(r"\b(todo|fixme|xxx|hack|workaround|work around|kludge|for now|temporar\w*"
                        r"|do not (remove|move|touch|change)|don'?t (remove|move|touch|change)|important)\b", re.I)
JUSTIFICATION = re.compile(r"\b(because|on purpose|intentional\w*|deliberate\w*|so that|in order to|needed|needs to"
                           r"|otherwise|keep this|we (do|use|check|need|keep)|the reason|why)\b", re.I)
FIX = {
    "justification": "make the code say it: a clearer name, an extracted function, a type or a test that pins "
                     "the behaviour, then delete the comment",
    "workaround": "fix the cause, or turn the rule it guards into a test or a check (red first), then delete "
                  "the comment",
    "suppression": "remove the switch and fix the cause it hid; only a style rule keeps a switch, with "
                   "` -- <reason>`",
    "external-link": "link the outside source that shows the constraint, or turn the rule into a check and "
                     "delete the comment",
    "escape-tag-reason": "delete it, or turn what it meant into a name, a test or a check",
    "comment": "delete it, or turn what it meant into a name, a test or a check",
}


@dataclass
class Note:
    line: int
    text: str


@dataclass
class Block:
    path: str
    lines: list
    text: str
    added: list
    doc: bool = False
    whole: bool = True
    rust_allow: bool = False


def language(path, first_line):
    name = path.rsplit("/", 1)[-1]
    if EXCLUDED.search(path) or LICENCE_FILE.match(name):
        return None
    suffix = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    if not suffix and first_line.startswith("#!"):
        programs = (word.rstrip("0123456789.") for word in first_line[2:].replace("/", " ").split())
        suffix = SHEBANG.get(next((name for name in programs if name in SHEBANG), ""), "")
    for kind in (HASH, SLASH, CSS, HTML):
        if suffix in kind:
            return suffix
    return None


def unquote(quoted):
    out, i = bytearray(), 1
    while i < len(quoted) and quoted[i] != '"':
        if quoted[i] == "\\" and quoted[i + 1:i + 4].isdigit():
            out.append(int(quoted[i + 1:i + 4], 8))
            i += 4
        elif quoted[i] == "\\":
            out.append(ESCAPES.get(quoted[i + 1], ord(quoted[i + 1])))
            i += 2
        else:
            out += quoted[i].encode("utf-8")
            i += 1
    return bytes(out), quoted[1:i]


def git_path(header):
    if header.startswith('"'):
        raw, inner = unquote(header)
        if not raw.startswith(b"b/"):
            return None
        try:
            name = raw[2:].decode("utf-8")
            plain = not any(ord(c) < 32 or ord(c) == 127 for c in name)
        except UnicodeDecodeError:
            name, plain = raw[2:].decode("utf-8", "replace"), False
        return name, name if plain else '"' + inner[2:] + '"'
    header = header.split("\t", 1)[0]
    return (header[2:], header[2:]) if header.startswith("b/") else None


def files(diff):
    path, numbered, line_no, old_left, new_left = None, {}, None, 0, 0
    for raw in diff.splitlines():
        if old_left > 0 or new_left > 0:
            if raw.startswith("-"):
                old_left -= 1
            elif raw.startswith("+"):
                numbered[path][-1].append((line_no, raw[1:], True))
                line_no, new_left = line_no + 1, new_left - 1
            elif raw.startswith(" ") or raw == "":
                numbered[path][-1].append((line_no, raw[1:], False))
                line_no, old_left, new_left = line_no + 1, old_left - 1, new_left - 1
            continue
        if raw.startswith("diff --git "):
            path = None
        elif raw.startswith("+++ "):
            path = git_path(raw[4:])
            if path is not None:
                numbered.setdefault(path, [])
        elif path is not None and (hunk := HUNK.match(raw)):
            old_left = int(hunk.group(1) or 1)
            line_no, new_left = int(hunk.group(2)), int(hunk.group(3) or 1)
            numbered[path].append([])
    return numbered


def scalar_starts(text, i):
    before = text[:i].rstrip()
    if not before or before[-1] in "[{,":
        return True
    return len(before) < i and before[-1] in ":?-" and (
        before[-1] != "-" or before.lstrip() == "-" or before.endswith(" -"))


def closing(text, i, quote):
    while i < len(text):
        if text.startswith(quote, i):
            return i
        i += 2 if text[i] == "\\" and len(quote) == 1 else 1
    return -1


def scan(suffix, text, state, offset=0):
    pieces, code, i = [], False, 0
    if state.get("heredoc"):
        if text.strip() == state["heredoc"]:
            del state["heredoc"]
        return pieces, True
    quotes = {".rs": '"', ".html": "", ".htm": ""}.get(suffix, "\"'`" if suffix in SLASH else "\"'")
    while i < len(text):
        if state.get("block"):
            end = text.find(state["block"], i)
            stop = len(text) if end < 0 else end + len(state["block"])
            pieces.append((offset + i, text[i:stop], state["doc"]))
            if end < 0:
                break
            state["block"], i = None, stop
            continue
        if state.get("quote"):
            end = closing(text, i, state["quote"])
            if end < 0:
                if len(state["quote"]) == 1:
                    state["quote"] = None
                break
            state["quote"], i = None, end + len(state["quote"])
            continue
        if "embed" in state:
            close = re.compile(r"</" + state["tag"] + r"\b", re.I).search(text, i)
            stop = close.start() if close else len(text)
            if state["embed"]:
                inner, inner_code = scan(state["embed"], text[i:stop], state["inner"], offset + i)
                pieces, code = pieces + inner, code or inner_code
            else:
                code = code or bool(text[i:stop].strip())
            if not close:
                break
            del state["embed"]
            i = stop
        rest = text[i:]
        opener = None
        if suffix in HTML and rest.startswith("<!--"):
            opener, closer, doc = "<!--", "-->", False
        elif suffix in SLASH | CSS and rest.startswith("/*"):
            opener, closer = "/*", "*/"
            doc = suffix in SLASH and (rest.startswith("/**") and not rest.startswith("/**/")
                                       or (suffix == ".rs" and rest.startswith("/*!")))
        if opener:
            end = text.find(closer, i + len(opener))
            if end < 0:
                pieces.append((offset + i, rest, doc))
                state.update(block=closer, doc=doc)
                break
            pieces.append((offset + i, text[i:end + len(closer)], doc))
            i = end + len(closer)
            continue
        if suffix in HTML and (tag := HTML_TAG.match(text, i)):
            k, attributes = tag.end(), {}
            while k < len(text) and text[k] != ">":
                attribute = HTML_ATTR.match(text, k)
                if attribute and attribute.end() > k:
                    attributes[attribute.group(1).lower()] = (attribute.group(2) or "").strip("\"'").strip()
                    k = attribute.end()
                else:
                    k += 1
            name, code, i = tag.group(2).lower(), True, k + 1
            if not tag.group(1) and name in ("script", "style"):
                script = ".js" if JS_TYPES.match(attributes.get("type", "")) else None
                state.update(embed=".css" if name == "style" else script, tag=name, inner={})
            continue
        if suffix in SHELL and rest.startswith("<<") and not rest.startswith("<<<") and (
                heredoc := HEREDOC.match(text, i)):
            state["heredoc"], code, i = heredoc.group(3), True, heredoc.end()
            continue
        if suffix in SLASH and rest.startswith("//"):
            doc = suffix == ".rs" and (rest.startswith("///") and not rest.startswith("////") or rest.startswith("//!"))
            pieces.append((offset + i, rest, doc))
            break
        if suffix in HASH and rest.startswith("#") and (i == 0 or text[i - 1].isspace() or suffix in HASH_ANYWHERE):
            pieces.append((offset + i, rest, False))
            break
        if suffix in HASH_ANYWHERE and rest[:3] in ('"""', "'''"):
            state["quote"], i = rest[:3], i + 3
            code = True
            continue
        if rest[0] in quotes and (suffix not in {".yml", ".yaml"} or scalar_starts(text, i)):
            state["quote"], i = rest[0], i + 1
            code = True
            continue
        code = code or not rest[0].isspace()
        i += 2 if rest[0] == "\\" else 1
    return pieces, code


def strip(piece):
    text = piece.strip()
    for opener in ("<!--", "/**", "/*!", "/*", "///", "//!", "//", "#"):
        if text.startswith(opener):
            text = text[len(opener):]
            break
    for closer in ("-->", "*/"):
        if text.endswith(closer):
            text = text[:-len(closer)]
    return " ".join(part.strip().lstrip("*").strip() for part in text.splitlines()).strip()


def unseen_context(suffix, hunk):
    texts = [text for _, text, _ in hunk]
    if suffix in {".yml", ".yaml"}:
        return next((text for text in texts if text.strip()), "")[:1].isspace(), {}
    if suffix in HTML:
        seen = " ".join(texts).lower()
        closes = [seen.find(f"</{tag}") for tag in ("script", "style")]
        opens = [seen.find(f"<{tag}") for tag in ("script", "style")]
        return any(c >= 0 and (o < 0 or c < o) for c, o in zip(closes, opens)), {}
    if suffix in {".py", ".pyi"}:
        quotes = [(text, mark) for text in texts for mark in TRIPLE.finditer(text)]
        if len(quotes) % 2 and quotes[0][0][quotes[0][1].end():].strip() in ("", ")", ",", "),"):
            return True, {"quote": quotes[0][1].group()}
    if suffix in SHELL:
        for text in texts:
            if "<<" in text:
                break
            if (terminator := TERMINATOR.match(text)):
                return True, {"heredoc": terminator.group(1)}
    return False, {}


def blocks(path, hunks):
    starts = bool(hunks) and bool(hunks[0]) and hunks[0][0][0] == 1
    suffix = language(path, hunks[0][0][1] if starts else "")
    found, top, notes = [], set(), []
    if suffix is None:
        return found, top, notes
    if starts and GENERATED.search("\n".join(text for n, text, _ in hunks[0] if n <= 5)):
        return found, top, notes
    workflow, preamble = bool(WORKFLOW.search(path)), starts
    for number, hunk in enumerate(hunks):
        state, run, docstring, previous, scalar = {}, None, None, "", None
        preamble = preamble and number == 0
        if hunk and hunk[0][0] != 1:
            unseen, state = unseen_context(suffix, hunk)
            if unseen:
                notes.append(Note(hunk[0][0], "the hunk starts inside something the diff doesn't show (a YAML "
                                  "block scalar, a <script> or <style>, a string or a here-document): judge its "
                                  "comments by hand"))
        for line_no, text, added in hunk:
            if docstring:
                run.lines.append(line_no)
                run.text = (run.text + " " + text.strip().replace(docstring, "")).strip()
                if added:
                    run.added.append(line_no)
                docstring = None if docstring in text else docstring
                continue
            if (line_no == 1 and text.startswith("#!")) or (
                    line_no <= 2 and suffix in {".py", ".pyi"} and ENCODING.match(text)):
                run = None
                continue
            opens = DOCSTRING.match(text) if suffix in {".py", ".pyi"} and not state.get("quote") else None
            if opens and (previous.endswith(":") or preamble):
                delim = opens.group(1)
                rest = text[opens.end():]
                docstring = None if delim in rest else delim
                run = Block(path, [line_no], rest.replace(delim, "").strip(), [line_no] if added else [], doc=True)
                found.append(run)
                previous, preamble = text.rstrip(), False
                continue
            if suffix == ".rs" and added and RUST_ALLOW.match(text):
                found.append(Block(path, [line_no], text.strip(), [line_no], whole=False, rust_allow=True))
            continuing = run is not None and bool(state.get("block"))
            indent = len(text) - len(text.lstrip(" "))
            if scalar and (not text.strip() or indent > scalar[0]):
                pieces, code = scan(".sh", text, state.setdefault("shell", {})) if scalar[1] else ([], True)
            else:
                scalar = None
                pieces, code = scan(suffix, text, state)
                before = text[:pieces[0][0]] if pieces else text
                if suffix in {".yml", ".yaml"} and not state.get("quote"):
                    if (opened := YAML_BLOCK.match(before)):
                        scalar = (len(opened.group(1)), opened.group(2).strip() == "run")
                        state["shell"] = {}
                    elif (item := YAML_ITEM_BLOCK.match(before)):
                        scalar = (len(item.group(1)), False)
                if workflow and pieces and PINNED.match(before) and VERSION.match(strip(pieces[0][1])):
                    pieces, code = pieces[1:], True
            if code:
                previous = (text[:pieces[0][0]] if pieces else text).rstrip()
            preamble = preamble and not code
            if not pieces:
                run = None
                continue
            if preamble:
                top.add(line_no)
            whole = not code and len(pieces) == 1
            for index, (_, piece, doc) in enumerate(pieces):
                body = strip(piece)
                joins = index == 0 and (continuing or (
                    whole and run is not None and run.whole and run.doc == doc and run.lines[-1] == line_no - 1))
                if joins:
                    run.lines.append(line_no)
                    run.text = (run.text + " " + body).strip()
                    if added:
                        run.added.append(line_no)
                else:
                    run = Block(path, [line_no], body, [line_no] if added else [], doc=doc, whole=whole)
                    found.append(run)
            if not whole and not state.get("block"):
                run = None
    return found, top, notes


def judge(block, top, docs):
    text = block.text
    if block.rust_allow:
        return ("check", "suppression") if "reason" in text else ("finding", "suppression")
    if SWITCH.match(text):
        return ("check", "suppression") if SWITCH_REASON.search(text) else ("finding", "suppression")
    if LICENCE.search(text) and block.lines[0] in top:
        return "check", "licence"
    if text.startswith("External:"):
        outside = [link for link in LINK.findall(text) if not OURS.match(link)]
        return ("check", "external") if outside else ("finding", "external-link")
    if WARNING.match(text):
        return "check", "warning"
    if POINTER.search(text):
        return "check", "private-record pointer"
    if text.startswith("comment-ok:"):
        return ("check", "escape") if text[len("comment-ok:"):].strip() else ("finding", "escape-tag-reason")
    if block.doc and any(block.path.startswith(d) for d in docs):
        return "check", "docs"
    if WORKAROUND.search(text):
        return "finding", "workaround"
    if JUSTIFICATION.search(text):
        return "finding", "justification"
    return "finding", "comment"


def comment_pass(diff, docs):
    findings, checks = [], []
    for (path, shown), hunks in files(diff).items():
        found, top, notes = blocks(path, hunks)
        checks += [f"check {shown}:{note.line}: context: {note.text}" for note in notes]
        for block in found:
            if not block.added:
                continue
            verdict, kind = judge(block, top, docs)
            excerpt = block.text if len(block.text) <= 80 else block.text[:77] + "..."
            where = f"{shown}:{block.added[0]}"
            if verdict == "finding":
                findings.append(f"{where}: {kind}: {excerpt} Fix: {FIX[kind]}.")
            else:
                checks.append(f"check {where}: {kind}: {excerpt}")
    return findings, checks


def main():
    parser = argparse.ArgumentParser(description=(
        "review-ticket's comment pass over one pull request's diff: prints a finding with its code fix for each "
        "added comment outside the allowed kinds, and a check line for each allowed one the reviewer still "
        "judges. Exits 1 with findings, 0 without, 2 on an unreadable diff."))
    parser.add_argument("diff", help="the diff file, or - for standard input")
    parser.add_argument("--docs", action="append", default=[],
                        help="a path a published documentation build renders (repeatable)")
    args = parser.parse_args()
    try:
        if args.diff == "-":
            diff = sys.stdin.buffer.read().decode("utf-8")
        else:
            with open(args.diff, encoding="utf-8") as handle:
                diff = handle.read()
    except (OSError, UnicodeDecodeError) as error:
        print(f"unreadable: {error}")
        return 2
    findings, checks = comment_pass(diff, args.docs)
    for line in findings + checks:
        print(line)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
