#!/usr/bin/env python3
import argparse
import ast
from bisect import bisect_right
import fnmatch
import io
import json
import os
import re
import subprocess
import sys
import tokenize

SCHEMA = 'openwiz.comments.v1'
EXTENSIONS = {
    '.rs': 'rust', '.py': 'python', '.pyi': 'python', '.sh': 'shell', '.bash': 'shell',
    '.yml': 'yaml', '.yaml': 'yaml', '.toml': 'toml',
    '.js': 'javascript', '.mjs': 'javascript', '.cjs': 'javascript', '.jsx': 'javascript',
    '.ts': 'typescript', '.mts': 'typescript', '.cts': 'typescript', '.tsx': 'typescript',
    '.css': 'css', '.html': 'html', '.htm': 'html',
}
SHEBANGS = [(re.compile(r'^#!.*\bpython[0-9.]*\b'), 'python'), (re.compile(r'^#!.*\b(sh|bash|dash|zsh)\b'), 'shell'),
            (re.compile(r'^#!.*\bnode\b'), 'javascript')]
VENDORED = {'vendor', 'vendored', 'third_party', 'third-party', 'node_modules'}
LICENCE_FILE = re.compile(r'^(licen[cs]e|copying|notice)([.-].*)?$', re.I)
GENERATED = re.compile(r'@generated|\bDO NOT EDIT\b')
ESCAPE = re.compile(r'^comment-ok:(.*)$', re.S)
WARNING = re.compile(r'^(SECURITY|SAFETY|PRIVACY|DATA LOSS):\s*\S')
EXTERNAL = re.compile(r'^External:')
OUR_LINK = re.compile(r'github\.com/(openwizdev|jparker2006)/', re.I)
LINK = re.compile(r'https?://[^\s)>\]"\']+')
PRIVATE_REPOSITORY = '/'.join(('jparker2006', 'Closed' + 'Wiz'))
POINTER = re.compile(r'https://github\.com/' + re.escape(PRIVATE_REPOSITORY) + r'/(issues|pull)/[1-9][0-9]*#issuecomment-[1-9][0-9]*')
LICENCE = re.compile(r'SPDX-License-Identifier:|\bCopyright\b|\bLicensed under\b')
DIRECTIVE = re.compile(
    r'^(noqa\b|type:\s*ignore\b|pragma:|pylint:|fmt:\s*(off|on|skip)\b|ruff:|mypy:|pyright:|isort:|'
    r'eslint(-disable|-enable)?\b|prettier-ignore\b|@ts-(ignore|expect-error|nocheck)\b|biome-ignore\b|'
    r'shellcheck\s|yamllint\s|stylelint-(disable|enable)|istanbul\s+ignore\b|c8\s+ignore\b|v8\s+ignore\b)')
REASON = re.compile(r'\s(--|#)\s+\S')
CODING = re.compile(r'^[ \t\f]*#.*?coding[:=]')
PINNED = re.compile(r'^\s*(?:-\s+)?uses:\s*(["\']?)[^\s"\'#]+@[0-9a-f]{40}\1\s*$')
VERSION = re.compile(r'^v?[0-9][0-9A-Za-z.+-]*$')


class Span:
    def __init__(self, l1, c1, l2, c2, text, doc=False):
        self.l1, self.c1, self.l2, self.c2, self.text, self.doc = l1, c1, l2, c2, text, doc


class Lines:
    def __init__(self, text):
        self.starts = [0] + [m.end() for m in re.finditer('\n', text)]

    def at(self, i):
        line = bisect_right(self.starts, i)
        return line, i - self.starts[line - 1]

    def span(self, start, end, text, doc=False):
        l1, c1 = self.at(start)
        l2, c2 = self.at(end)
        return Span(l1, c1, l2, c2, text, doc)


def skip_quoted(s, i, quote, newline_ends=True):
    n = len(s)
    j = i + 1
    while j < n:
        c = s[j]
        if c == '\\':
            j += 2
            continue
        if c == quote:
            return j + 1
        if c == '\n' and newline_ends:
            return j
        j += 1
    return n


DOC_BLOCKS = {'rust': ('**', '*!'), 'js': ('**',)}


def block_comment(s, i, lines, out, nested=False, docs=None):
    depth, j, n = 1, i + 2, len(s)
    while j < n and depth:
        if nested and s.startswith('/*', j):
            depth, j = depth + 1, j + 2
        elif s.startswith('*/', j):
            depth, j = depth - 1, j + 2
        else:
            j += 1
    body = s[i + 2:j - 2] if not depth else s[i + 2:]
    opener = s[i + 1:i + 3]
    doc = (opener in DOC_BLOCKS.get(docs, ()) and not s.startswith('/***', i) and not s.startswith('/**/', i))
    out.append(lines.span(i, j, '\n'.join(l.strip().lstrip('*').strip() for l in body.split('\n')).strip(), doc))
    return j


def line_comment(s, i, lines, out, marker, doc=False):
    j = s.find('\n', i)
    j = len(s) if j < 0 else j
    out.append(lines.span(i, j, s[i + len(marker):j].lstrip('/!').strip() if marker == '//' else s[i:j].lstrip('#').strip(), doc))
    return j


RUST_RAW = re.compile(r'[bc]?r(#*)"')
RUST_CHAR = re.compile(r"'(\\(x[0-9a-fA-F]{2}|u\{[0-9a-fA-F]{1,6}\}|.)|[^\\'\n])'")
WORD = re.compile(r'[A-Za-z_$][A-Za-z0-9_$]*')
RUST_WORD = re.compile(r'\w+')


def scan_rust(s):
    lines, out, i, n = Lines(s), [], 0, len(s)
    while i < n:
        c = s[i]
        if s.startswith('//', i):
            body = s[i + 2:]
            i = line_comment(s, i, lines, out, '//', (body.startswith('/') and not body.startswith('//')) or body.startswith('!'))
        elif s.startswith('/*', i):
            i = block_comment(s, i, lines, out, nested=True, docs='rust')
        elif c == '"':
            i = skip_quoted(s, i, '"', newline_ends=False)
        elif c == "'":
            m = RUST_CHAR.match(s, i)
            i = m.end() if m else i + 1
        elif c.isalpha() or c == '_':
            m = RUST_RAW.match(s, i)
            if m:
                end = s.find('"' + m.group(1), m.end())
                i = n if end < 0 else end + 1 + len(m.group(1))
            else:
                i = RUST_WORD.match(s, i).end()
        else:
            i += 1
    return out


def skip_triple(s, i):
    q, j, n = s[i], i + 3, len(s)
    while j < n:
        if q == '"' and s[j] == '\\':
            j += 2
        elif s.startswith(q * 3, j):
            j += 3
            for _ in range(2):
                if j < n and s[j] == q:
                    j += 1
            return j
        else:
            j += 1
    return n


def scan_hash(s, triple=True):
    lines, out, i, n = Lines(s), [], 0, len(s)
    while i < n:
        c = s[i]
        if c == '#':
            i = line_comment(s, i, lines, out, '#')
        elif triple and (s.startswith('"""', i) or s.startswith("'''", i)):
            i = skip_triple(s, i)
        elif c == '"':
            i = skip_quoted(s, i, '"')
        elif c == "'":
            end = s.find("'", i + 1)
            nl = s.find('\n', i + 1)
            if end < 0 or 0 <= nl < end:
                i = n if nl < 0 else nl
            else:
                i = end + 1
        else:
            i += 1
    return out


def scan_python(s):
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(s).readline))
        tree = ast.parse(s)
    except (SyntaxError, tokenize.TokenError, ValueError):
        return scan_hash(s)
    out = [Span(t.start[0], t.start[1], t.end[0], t.end[1], t.string.lstrip('#').strip())
           for t in tokens if t.type == tokenize.COMMENT]
    src = s.split('\n')
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            span = Span(node.lineno, 0, node.end_lineno, len(src[node.end_lineno - 1]), node.value.value.strip(), True)
            span.string = True
            out.append(span)
    return out


HEREDOC = re.compile(r'<<(-?)[ \t]*(["\']?)([A-Za-z0-9_.-]+)\2')
SHELL_BREAK = ' \t\n;&|()<>'
SHELL_WORD = re.compile(r'[A-Za-z_]+(?=[ \t\n;&|()<>]|$)')
SHELL_LEADS = {'then', 'do', 'else', 'elif', 'if', 'while', 'until', 'time', '!', '{'}


def skip_parens(s, i):
    depth, j, n = 0, i, len(s)
    while j < n:
        if s[j] == '(':
            depth += 1
        elif s[j] == ')':
            depth -= 1
            if depth == 0:
                return j + 1
        elif s[j] == '\\':
            j += 1
        j += 1
    return n


class ShellRead:
    def __init__(self, s):
        self.s, self.lines, self.out, self.first, self.lost = s, Lines(s), [], None, False


def shell_quoted(r, i, nested=False):
    s, n, j, sure = r.s, len(r.s), i + 1, True
    while j < n:
        if s[j] == '\\':
            j += 2
        elif s[j] == '"':
            return j + 1, sure
        elif s.startswith('$((', j):
            j = skip_parens(s, j + 1)
        elif s.startswith('$(', j):
            r.first = j if r.first is None else r.first
            kept, r.out = r.out, []
            j, inner = shell_words(r, j + 2, nested=True)
            r.out = kept + r.out if inner else kept
            sure = sure and inner
        elif s[j] == '`':
            j = skip_quoted(s, j, '`', newline_ends=False)
            sure = sure and not nested
        else:
            j += 1
    r.lost = True
    return n, False


def continued(s, j, start):
    k = j - 1
    while k > start and s[k - 1] == '\\':
        k -= 1
    return s[j - 1] == '\n' and (j - 1 - k) % 2 == 1


def command_start(s, i, start):
    j = i
    while j > start and (s[j - 1] in ' \t' or continued(s, j, start)):
        j -= 2 if s[j - 1] == '\n' else 1
    if j == start or s[j - 1] in ';&|()\n':
        return True
    k = j
    while k > start and s[k - 1] not in SHELL_BREAK:
        k -= 1
    return s[k:j] in SHELL_LEADS and (k == start or s[k - 1] in SHELL_BREAK)


def scan_shell(s):
    r = ShellRead(s)
    shell_words(r, 0)
    if r.lost and r.first is not None:
        cut = r.lines.at(r.first)[0]
        return [sp for sp in r.out if sp.l1 < cut]
    return r.out


def shell_words(r, i, nested=False):
    s, lines = r.s, r.lines
    n, pending, boundary, depth, cases, start, sure, quiet = len(s), [], True, 0, [], i, True, 0
    while i < n:
        c = s[i]
        if c == '\n' and pending:
            i += 1
            for strip, word in pending:
                while i < n:
                    end = s.find('\n', i)
                    end = n if end < 0 else end
                    line = s[i:end]
                    i = end + 1
                    if (line.lstrip('\t') if strip else line) == word:
                        break
            pending, boundary = [], True
        elif s.startswith('$((', i) or (boundary and s.startswith('((', i)):
            i, boundary = skip_parens(s, i + 1 if c == '$' else i), False
        elif nested and s.startswith('$(', i):
            i, sure, boundary = shell_words(r, i + 2, nested=True)[0], False, False
        elif s.startswith('$[', i):
            end = s.find(']', i)
            i, boundary = (n if end < 0 else end + 1), False
        elif s.startswith('<<<', i):
            i, boundary = i + 3, True
        elif s.startswith('<<', i):
            m = HEREDOC.match(s, i)
            if m:
                pending.append((m.group(1) == '-', m.group(3)))
                i, sure = m.end(), sure and not nested
            else:
                i += 2
            boundary = m is None
        elif c in SHELL_BREAK:
            if nested and c == '(':
                depth += 1
            elif nested and c == ')' and cases[-1:] != [depth]:
                depth -= 1
                if depth < 0:
                    return i + 1, sure
            i, boundary = i + 1, True
        elif c == '#' and boundary:
            if lines.at(i)[0] == quiet:
                end = s.find('\n', i)
                i = n if end < 0 else end
            else:
                i = line_comment(s, i, lines, r.out, '#')
        elif c == "'":
            end = s.find("'", i + 1)
            i, boundary = (n if end < 0 else end + 1), False
        elif c == '$' and s.startswith("$'", i):
            i, boundary = skip_quoted(s, i + 1, "'", newline_ends=False), False
        elif c == '"':
            i, inner = shell_quoted(r, i, nested)
            sure, boundary = sure and inner, False
            quiet = quiet if inner else lines.at(i - 1)[0]
        elif c == '`':
            i, boundary = skip_quoted(s, i, c, newline_ends=False), False
            sure = sure and not nested
        elif c == '\\':
            i, boundary = i + 2, boundary and s.startswith('\\\n', i)
        elif nested and boundary and SHELL_WORD.match(s, i):
            word = SHELL_WORD.match(s, i).group()
            if word in ('case', 'esac') and command_start(s, i, start):
                sure = False
                if word == 'case':
                    cases.append(depth)
                elif cases:
                    cases.pop()
            i, boundary = i + len(word), False
        else:
            i, boundary = i + 1, False
    if nested:
        r.lost = True
        return n, False
    return n, sure


YAML_BLOCK = re.compile(r'^(\s*(?:-\s+)?)([^\s#][^#]*?):\s*[|>][0-9+-]*\s*$')
YAML_ITEM_BLOCK = re.compile(r'^(\s*)-\s+[|>][0-9+-]*\s*$')


def scalar_starts(line, j):
    before = line[:j].rstrip()
    if not before or before[-1] in '[{,':
        return True
    return len(before) < j and before[-1] in ':?-' and (before[-1] != '-' or before.lstrip() == '-' or before.endswith(' -'))


def yaml_line_comment(line, quote):
    j = 0
    while j < len(line):
        c = line[j]
        if quote:
            if c == '\\' and quote == '"':
                j += 1
            elif c == quote == "'" and line[j + 1:j + 2] == "'":
                j += 1
            elif c == quote:
                quote = None
        elif c in '"\'' and scalar_starts(line, j):
            quote = c
        elif c == '#' and (j == 0 or line[j - 1] in ' \t'):
            return j, None
        j += 1
    return -1, quote


def scan_yaml(s):
    src = s.split('\n')
    out, block, run, quote = [], None, [], None

    def flush():
        if run:
            first = run[0][0]
            for sp in scan_shell('\n'.join(text for _, text in run)):
                out.append(Span(sp.l1 + first - 1, sp.c1, sp.l2 + first - 1, sp.c2, sp.text))
            run.clear()

    for number, line in enumerate(src, 1):
        if block is not None:
            indent = len(line) - len(line.lstrip(' '))
            if not line.strip() or indent > block[0]:
                if block[1]:
                    run.append((number, line))
                continue
            flush()
            block = None
        was_quoted = quote is not None
        j, quote = yaml_line_comment(line, quote)
        code = line if j < 0 else line[:j]
        if j >= 0:
            out.append(Span(number, j, number, len(line), line[j:].lstrip('#').strip()))
        if was_quoted or quote:
            continue
        m = YAML_BLOCK.match(code)
        if m:
            block = (len(m.group(1)), m.group(2).strip() == 'run')
        elif YAML_ITEM_BLOCK.match(code):
            block = (len(YAML_ITEM_BLOCK.match(code).group(1)), False)
    flush()
    return out


REGEX_AFTER = set('(,=:[!&|?{};+-*%<>~^}') | {'', 'return', 'typeof', 'case', 'do', 'else', 'in', 'of', 'new',
                                             'delete', 'void', 'throw', 'yield', 'await', 'instanceof'}


def skip_regex(s, i):
    j, n, cls = i + 1, len(s), False
    while j < n and s[j] != '\n':
        c = s[j]
        if c == '\\':
            j += 2
            continue
        if c == '[':
            cls = True
        elif c == ']':
            cls = False
        elif c == '/' and not cls:
            j += 1
            while j < n and (s[j].isalnum()):
                j += 1
            return j
        j += 1
    return j


def scan_js(s, base=0, lines=None, out=None):
    lines = lines or Lines(s)
    out = [] if out is None else out
    i, n, stack, prev = base, len(s), [], ''
    if base == 0 and s.startswith('#!'):
        i = n if s.find('\n') < 0 else s.find('\n')

    def template(j):
        while j < n:
            if s[j] == '\\':
                j += 2
            elif s[j] == '`':
                return j + 1, 'a'
            elif s.startswith('${', j):
                stack.append(0)
                return j + 2, '('
            else:
                j += 1
        return n, 'a'

    while i < n:
        c = s[i]
        if c in ' \t\r\n':
            i += 1
        elif s.startswith('//', i):
            i = line_comment(s, i, lines, out, '//')
        elif s.startswith('/*', i):
            i = block_comment(s, i, lines, out, docs='js')
        elif c in '"\'':
            i, prev = skip_quoted(s, i, c), 'a'
        elif c == '`':
            i, prev = template(i + 1)
        elif c == '{':
            if stack:
                stack[-1] += 1
            i, prev = i + 1, '{'
        elif c == '}':
            if stack and stack[-1] == 0:
                stack.pop()
                i, prev = template(i + 1)
            else:
                if stack:
                    stack[-1] -= 1
                i, prev = i + 1, '}'
        elif c == '/':
            if prev in REGEX_AFTER:
                i, prev = skip_regex(s, i), 'a'
            else:
                i, prev = i + 1, '/'
        elif c.isalnum() or c in '_$':
            m = WORD.match(s, i)
            word = m.group(0) if m else c
            i, prev = i + len(word), (word if word in REGEX_AFTER else 'a')
        else:
            i, prev = i + 1, c
    return out


def scan_css(s, base=0, lines=None, out=None):
    lines = lines or Lines(s)
    out = [] if out is None else out
    i, n = base, len(s)
    while i < n:
        if s.startswith('/*', i):
            i = block_comment(s, i, lines, out)
        elif s[i] in '"\'':
            i = skip_quoted(s, i, s[i])
        else:
            i += 1
    return out


HTML_TAG = re.compile(r'<(/?)([A-Za-z][A-Za-z0-9-]*)')
HTML_ATTR = re.compile(r'\s*([^\s"\'>/=]+)(?:\s*=\s*("[^"]*"|\'[^\']*\'|[^\s"\'>]+))?')
JS_TYPES = re.compile(r'^(|module|(text|application)/(java|ecma)script)$', re.I)


def scan_html(s):
    lines, out, i, n = Lines(s), [], 0, len(s)
    while True:
        j = s.find('<', i)
        if j < 0:
            return out
        if s.startswith('<!--', j):
            end = s.find('-->', j + 4)
            end = n if end < 0 else end + 3
            out.append(lines.span(j, end, s[j + 4:max(j + 4, end - 3)].strip()))
            i = end
            continue
        m = HTML_TAG.match(s, j)
        if not m:
            i = j + 1
            continue
        k, attrs = m.end(), {}
        while k < n and s[k] != '>':
            a = HTML_ATTR.match(s, k)
            if a and a.end() > k:
                attrs[a.group(1).lower()] = (a.group(2) or '').strip('"\'').strip()
                k = a.end()
            else:
                k += 1
        i, tag = min(k + 1, n), m.group(2).lower()
        if m.group(1) or tag not in ('script', 'style', 'title', 'textarea'):
            continue
        close = re.compile(r'</' + tag + r'(?=[\t\n\f\r />])', re.I).search(s, i)
        stop = n if not close else close.start()
        if tag == 'style':
            scan_css(s[:stop], i, lines, out)
        elif tag == 'script' and JS_TYPES.match(attrs.get('type', '')):
            scan_js(s[:stop], i, lines, out)
        i = stop


SCANNERS = {'rust': scan_rust, 'python': scan_python, 'shell': scan_shell, 'yaml': scan_yaml, 'toml': scan_hash,
            'javascript': scan_js, 'typescript': scan_js, 'css': scan_css, 'html': scan_html}


def language(path, text):
    for ext, name in EXTENSIONS.items():
        if path.endswith(ext):
            return name
    if '.' not in path.rsplit('/', 1)[-1]:
        first = text.split('\n', 1)[0]
        for pattern, name in SHEBANGS:
            if pattern.match(first):
                return name
    return None


def matches(path, globs):
    for g in globs:
        g = g[2:] if g.startswith('./') else g
        if g.endswith('/') and path.startswith(g):
            return True
        if fnmatch.fnmatchcase(path, g) or fnmatch.fnmatchcase(path, g.rstrip('/') + '/*'):
            return True
    return False


def excluded(path, text, attributes, extra):
    parts = path.split('/')
    if VENDORED & set(parts[:-1]) or LICENCE_FILE.match(parts[-1]) or path in attributes:
        return True
    if parts[-1].endswith(('.min.js', '.min.css')) or any(a == 'fixtures' and b == 'comments' for a, b in zip(parts, parts[1:-1])):
        return True
    return bool(GENERATED.search('\n'.join(text.split('\n', 5)[:5]))) or matches(path, extra)


class Judged:
    def __init__(self, text, lang, docs, path=''):
        self.src = text.split('\n')
        self.workflow = path.startswith('.github/workflows/') or path.rsplit('/', 1)[-1] in ('action.yml', 'action.yaml')
        self.failures, kept, masked = [], [], []
        for sp in SCANNERS[lang](text):
            (masked if self.is_code(sp, lang) else kept).append(sp)
        self.lines = set()
        for sp in kept:
            self.lines.update(range(sp.l1, sp.l2 + 1))
        covered = {}
        for sp in kept + masked:
            for ln in range(sp.l1, sp.l2 + 1):
                covered.setdefault(ln, []).append(sp)
        self.code = {ln for ln, line in enumerate(self.src, 1) if self.has_code(ln, line, covered.get(ln, []))}
        self.bad_lines = set()
        for block in self.blocks(kept):
            reason = self.judge(block, docs)
            if reason:
                lines = set()
                for sp in block:
                    lines.update(range(sp.l1, sp.l2 + 1))
                self.failures.append((lines, reason))
                self.bad_lines |= lines

    def is_code(self, sp, lang):
        if sp.l1 == 1 and sp.c1 == 0 and self.src[0].startswith('#!'):
            return True
        if lang == 'python' and sp.l1 <= 2 and CODING.match(self.src[sp.l1 - 1]):
            return True
        if lang == 'yaml' and self.workflow and PINNED.match(self.src[sp.l1 - 1][:sp.c1]) and VERSION.match(sp.text):
            return True
        if not getattr(sp, 'string', False) and DIRECTIVE.match(sp.text):
            if REASON.search(sp.text):
                return True
            sp.directive = True
        return False

    def has_code(self, ln, line, spans):
        chars = list(line)
        for sp in spans:
            start = sp.c1 if sp.l1 == ln else 0
            stop = sp.c2 if sp.l2 == ln else len(chars)
            chars[start:stop] = [' '] * (stop - start)
        return bool(''.join(chars).strip())

    def full(self, sp):
        return not self.src[sp.l1 - 1][:sp.c1].strip() and not self.src[sp.l2 - 1][sp.c2:].strip()

    def blocks(self, spans):
        spans = sorted(spans, key=lambda sp: (sp.l1, sp.c1))
        block = []
        for sp in spans:
            last = block[-1] if block else None
            if (last and self.full(sp) and self.full(last) and sp.l1 == last.l2 + 1 and sp.doc == last.doc
                    and not getattr(sp, 'directive', False) and not getattr(last, 'directive', False)):
                block.append(sp)
                continue
            if block:
                yield block
            block = [sp]
        if block:
            yield block

    def judge(self, block, docs):
        text = '\n'.join(sp.text for sp in block).strip()
        first = text.split('\n', 1)[0].strip()
        if getattr(block[0], 'directive', False):
            return 'directive-reason'
        m = ESCAPE.match(first)
        if m:
            return None if m.group(1).strip() else 'escape-tag-reason'
        if WARNING.match(first) or POINTER.search(text):
            return None
        if EXTERNAL.match(first):
            return None if any(not OUR_LINK.search(u) for u in LINK.findall(text)) else 'external-link'
        if LICENCE.search(text) and not any(ln in self.code for ln in range(1, block[0].l1)):
            return None
        if docs and all(sp.doc for sp in block):
            return None
        return 'comment'


MESSAGES = {
    'comment': 'a comment outside the allowed kinds: delete it, or turn what it meant into a name, a test or a check',
    'escape-tag-reason': 'the escape tag needs a reason after "comment-ok:"',
    'external-link': 'an "External:" constraint needs a link to the outside source',
    'directive-reason': 'a lint or formatter switch needs its reason after " -- " or " # "',
    'unreadable': 'a file in a listed language that is not UTF-8 text, so its comments cannot be read',
}


def raw(path):
    return path.encode('utf-8', 'surrogateescape')


def text(data):
    return data.decode('utf-8', 'surrogateescape')


def fail(message):
    print(f'comment-check: {message}', file=sys.stderr)
    sys.exit(2)


def git(*args, stdin=None):
    run = subprocess.run(['git', *args], capture_output=True, input=stdin,
                         env={**os.environ, 'GIT_LITERAL_PATHSPECS': '1'})
    if run.returncode:
        fail(f'git {" ".join(text(a) if isinstance(a, bytes) else a for a in args)}: {run.stderr.decode(errors="replace").strip()}')
    return run.stdout


def shown(path):
    if all(31 < ord(c) != 127 and not 0xdc80 <= ord(c) <= 0xdcff for c in path):
        return path
    escapes = {7: 'a', 8: 'b', 9: 't', 10: 'n', 11: 'v', 12: 'f', 13: 'r', 34: '"', 92: '\\'}
    out = ''
    for b in raw(path):
        if b in escapes:
            out += '\\' + escapes[b]
        elif b < 32 or b >= 127:
            out += '\\%03o' % b
        else:
            out += chr(b)
    return f'"{out}"'


def read_blobs(blobs):
    if not blobs:
        return {}
    data, out, i = git('cat-file', '--batch', stdin=''.join(f'{sha}\n' for sha in blobs.values()).encode()), {}, 0
    for path, sha in blobs.items():
        end = data.index(b'\n', i)
        header = data[i:end].split()
        i = end + 1
        if len(header) != 3 or header[0].decode() != sha or header[1] != b'blob':
            fail(f'git cat-file: blob {sha} for {shown(path)} is missing')
        size = int(header[2])
        blob, i = data[i:i + size], i + size + 1
        try:
            out[path] = None if b'\0' in blob else blob.decode('utf-8')
        except UnicodeDecodeError:
            out[path] = None
    return out


def attributes(rev, paths):
    if not paths:
        return set()
    run = subprocess.run(['git', 'check-attr', f'--source={rev}', '-z', '--stdin', 'linguist-generated', 'linguist-vendored'],
                         input=b''.join(raw(p) + b'\0' for p in paths), capture_output=True)
    fields = text(run.stdout).split('\0')
    return {fields[k] for k in range(0, len(fields) - 2, 3) if fields[k + 2] not in ('unspecified', 'unset', 'false')}


def files_at(rev, pathspecs, extra):
    blobs = {}
    for entry in text(git('ls-tree', '-r', '-z', '--full-tree', rev, '--', *pathspecs)).split('\0'):
        if entry:
            meta, path = entry.split('\t', 1)
            mode, kind, sha = meta.split()
            if kind == 'blob' and mode in ('100644', '100755'):
                blobs[path] = sha
    texts = {p: t for p, t in read_blobs(blobs).items() if t is not None}
    marked = attributes(rev, list(texts))
    for path, body in texts.items():
        lang = language(path, body)
        if lang and not excluded(path, body, marked, extra):
            yield path, lang, body


def tally(rev, pathspecs, docs, extra, by_file):
    sha = text(git('rev-parse', '--verify', f'{rev}^{{commit}}')).strip()
    out = {'rev': sha, 'files': 0, 'comment_lines': 0, 'disallowed_lines': 0, 'languages': {}}
    per = {}
    for path, lang, body in files_at(sha, pathspecs, extra):
        judged = Judged(body, lang, matches(path, docs), path)
        out['files'] += 1
        out['comment_lines'] += len(judged.lines)
        out['disallowed_lines'] += len(judged.bad_lines)
        entry = out['languages'].setdefault(lang, {'files': 0, 'comment_lines': 0})
        entry['files'] += 1
        entry['comment_lines'] += len(judged.lines)
        if judged.lines:
            per[shown(path)] = len(judged.lines)
    out['languages'] = dict(sorted(out['languages'].items()))
    if by_file:
        out['by_file'] = dict(sorted(per.items()))
    return out


HUNK = re.compile(rb'^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@')


def changed_files(base, head):
    fields, files, k = text(git('diff', '--raw', '-z', '--no-abbrev', '-M', '--diff-filter=d', f'{base}...{head}')).split('\0'), [], 0
    while k < len(fields) and fields[k].startswith(':'):
        meta = fields[k].split()
        paths = fields[k + 1:k + 3] if meta[4][0] in 'RC' else fields[k + 1:k + 2]
        k += 1 + len(paths)
        if meta[1] in ('100644', '100755'):
            files.append((paths, meta[3]))
    return files


def added_lines(base, head, paths):
    patch = git('diff', '--no-color', '--no-ext-diff', '--text', '-U0', '-M', f'{base}...{head}', '--', *map(raw, paths))
    added = set()
    for line in patch.split(b'\n'):
        m = HUNK.match(line)
        if m:
            start, count = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
            added.update(range(start, start + count))
    return added


def diff_mode(args):
    head = text(git('rev-parse', '--verify', f'{args.head}^{{commit}}')).strip()
    added, blobs = {}, {}
    for paths, sha in changed_files(args.base, head):
        lines = added_lines(args.base, head, paths)
        if lines:
            added[paths[-1]], blobs[paths[-1]] = lines, sha
    texts = read_blobs(blobs)
    marked = attributes(head, list(texts))
    found = []
    for path, body in sorted(texts.items()):
        lang = language(path, body or '')
        if not lang or excluded(path, body or '', marked, args.exclude):
            continue
        if body is None:
            found.append((path, min(added[path]), 'unreadable'))
            continue
        judged = Judged(body, lang, matches(path, args.docs), path)
        for lines, reason in judged.failures:
            hit = lines & added[path]
            if hit:
                found.append((path, min(hit), reason))
    for path, line, reason in sorted(found):
        print(f'{shown(path)}:{line}: {reason}: {MESSAGES[reason]}')
    print(f'comment-check: {len(found)} disallowed comment(s) in added lines' if found else 'comment-check: ok', file=sys.stderr)
    return 1 if found else 0


def count_mode(args):
    report = {'schema': SCHEMA, 'paths': args.paths, 'docs': args.docs, 'exclude': args.exclude,
              'before': tally(args.before, args.paths, args.docs, args.exclude, args.by_file) if args.before else None,
              'after': tally(args.at, args.paths, args.docs, args.exclude, args.by_file)}
    print(json.dumps(report, indent=2))
    return 0


def main(argv):
    parser = argparse.ArgumentParser(prog='check.py', description='The comments contract, openwiz.comments.v1.')
    sub = parser.add_subparsers(dest='mode', required=True)
    for name in ('diff', 'count'):
        p = sub.add_parser(name)
        p.add_argument('--docs', action='append', default=[], metavar='PATH')
        p.add_argument('--exclude', action='append', default=[], metavar='GLOB')
    d = sub.choices['diff']
    d.add_argument('--base', required=True, metavar='REV')
    d.add_argument('--head', default='HEAD', metavar='REV')
    c = sub.choices['count']
    c.add_argument('--before', metavar='REV')
    c.add_argument('--at', default='HEAD', metavar='REV')
    c.add_argument('--by-file', action='store_true')
    c.add_argument('paths', nargs='*')
    args = parser.parse_args(argv)
    return diff_mode(args) if args.mode == 'diff' else count_mode(args)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
