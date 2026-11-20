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
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
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
class Block:
    path: str
    lines: list
    text: str
    added: list
    doc: bool = False
    whole: bool = True
    rust_allow: bool = False


def language(path, first_line):
    if EXCLUDED.search(path):
        return None
    name = path.rsplit("/", 1)[-1]
    suffix = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    if not suffix and first_line.startswith("#!"):
        programs = (word.rstrip("0123456789.") for word in first_line[2:].replace("/", " ").split())
        suffix = SHEBANG.get(next((name for name in programs if name in SHEBANG), ""), "")
    for kind in (HASH, SLASH, CSS, HTML):
        if suffix in kind:
            return suffix
    return None


def files(diff):
    path, numbered, line_no = None, {}, None
    for raw in diff.splitlines():
        if raw.startswith("diff --git "):
            path, line_no = None, None
        elif raw.startswith("+++ "):
            target = raw[4:]
            path = target[2:] if target.startswith("b/") else None
            if path is not None:
                numbered.setdefault(path, [])
        elif path is None:
            continue
        elif (hunk := HUNK.match(raw)):
            line_no = int(hunk.group(1))
            numbered[path].append([])
        elif line_no is None or raw.startswith("-") or raw.startswith("\\"):
            continue
        elif raw.startswith("+") or raw.startswith(" ") or raw == "":
            numbered[path][-1].append((line_no, raw[1:], raw.startswith("+")))
            line_no += 1
    return numbered


def closing(text, i, quote):
    while i < len(text):
        if text.startswith(quote, i):
            return i
        i += 2 if text[i] == "\\" and len(quote) == 1 else 1
    return -1


def scan(suffix, text, state):
    pieces, code, i = [], False, 0
    quotes = {".rs": '"'}.get(suffix, "\"'`" if suffix in SLASH else "\"'")
    while i < len(text):
        if state.get("block"):
            end = text.find(state["block"], i)
            stop = len(text) if end < 0 else end + len(state["block"])
            pieces.append((text[i:stop], state["doc"]))
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
                pieces.append((rest, doc))
                state.update(block=closer, doc=doc)
                break
            pieces.append((text[i:end + len(closer)], doc))
            i = end + len(closer)
            continue
        if suffix in SLASH and rest.startswith("//"):
            doc = suffix == ".rs" and (rest.startswith("///") and not rest.startswith("////") or rest.startswith("//!"))
            pieces.append((rest, doc))
            break
        if suffix in HASH and rest.startswith("#") and (i == 0 or text[i - 1].isspace() or suffix in HASH_ANYWHERE):
            pieces.append((rest, False))
            break
        if suffix in HASH_ANYWHERE and rest[:3] in ('"""', "'''"):
            state["quote"], i = rest[:3], i + 3
            code = True
            continue
        if rest[0] in quotes:
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


def blocks(path, hunks):
    starts = bool(hunks) and bool(hunks[0]) and hunks[0][0][0] == 1
    suffix = language(path, hunks[0][0][1] if starts else "")
    found, top = [], set()
    if suffix is None:
        return found, top
    preamble = starts
    for number, hunk in enumerate(hunks):
        state, run, docstring, previous = {}, None, None, ""
        preamble = preamble and number == 0
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
            if opens and (previous.endswith(":") or (preamble and not previous)):
                delim = opens.group(1)
                rest = text[opens.end():]
                docstring = None if delim in rest else delim
                run = Block(path, [line_no], rest.replace(delim, "").strip(), [line_no] if added else [], doc=True)
                found.append(run)
                previous = text.rstrip()
                continue
            if text.strip():
                previous = text.rstrip()
            if suffix == ".rs" and added and RUST_ALLOW.match(text):
                found.append(Block(path, [line_no], text.strip(), [line_no], whole=False, rust_allow=True))
            continuing = run is not None and bool(state.get("block"))
            pieces, code = scan(suffix, text, state)
            preamble = preamble and not code
            if not pieces:
                run = None
                continue
            body = " ".join(strip(piece) for piece, _ in pieces)
            doc = any(flag for _, flag in pieces)
            if preamble:
                top.add(line_no)
            joins = continuing or (run is not None and run.whole and not code and run.doc == doc
                                   and run.lines[-1] == line_no - 1)
            if joins:
                run.lines.append(line_no)
                run.text = (run.text + " " + body).strip()
                if added:
                    run.added.append(line_no)
            else:
                run = Block(path, [line_no], body, [line_no] if added else [], doc=doc, whole=not code)
                found.append(run)
            if code and not state.get("block"):
                run = None
    return found, top


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
    for path, hunks in files(diff).items():
        found, top = blocks(path, hunks)
        for block in found:
            if not block.added:
                continue
            verdict, kind = judge(block, top, docs)
            excerpt = block.text if len(block.text) <= 80 else block.text[:77] + "..."
            where = f"{path}:{block.added[0]}"
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
