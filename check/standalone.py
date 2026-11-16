#!/usr/bin/env python3
"""WizSkills standalone check (openwiz.wizskills.v1, WZ2 #2630).

Every relative Markdown link, script path, import and file read in a copied
skill must resolve to an existing file inside the staged tree. A refusal is
one JSON record per finding, with only rule, package-relative file and line.
Standard library only; it reads the tree and never runs or writes anything.
"""
import argparse
import ast
import fnmatch
import importlib.util
import json
import os
from pathlib import Path
import posixpath
import re
import sys
from urllib.parse import unquote

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
# Two homes, chosen by where this file is, never by what happens to exist.
# In ClosedWiz (tools/skills-copy/) it reads the contract and the privacy
# check. Anywhere else, as the copy places it at WizSkills' check/standalone.py,
# it reads only the two files the copy writes beside it (WZ14, #2891): the
# contract's normative values and the privacy check's redaction. Never a
# file outside that tree; a missing one refuses.
CLOSEDWIZ = HERE.name == 'skills-copy' and HERE.parent.name == 'tools'
CONTRACT = HERE.parents[1] / 'contracts/wizskills.v1.md' if CLOSEDWIZ else HERE / 'wizskills.v1.json'
REDACTION = HERE.parent / 'privacy-check' / 'check.py' if CLOSEDWIZ else HERE / 'redact.py'
RULES = ('link', 'script', 'import', 'read', 'symlink')
WEB = ('http', 'https', 'mailto')
SCRIPT_SUFFIXES = ('.sh', '.py', '.mjs', '.js', '.cjs')


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


def normative_block(text):
    """The text of the contract's one machine-readable block."""
    blocks = re.findall(r'^```wizskills-v1\n(.*?)^```', text, re.M | re.S)
    if len(blocks) != 1:
        raise ValueError('expected one wizskills-v1 block')
    return blocks[0]


def contract_rules(text):
    """The contract's one normative block: carried contracts and project settings."""
    return normative_rules(normative_block(text))


def normative_rules(block):
    """The normative values, checked, from the block's JSON text alone."""
    rules = json.loads(block, object_pairs_hook=unique_object)
    if not isinstance(rules, dict) or rules.get('schema') != 'openwiz.wizskills.v1':
        raise ValueError('wrong schema')
    for key in ('carried_contracts', 'project_settings'):
        values = rules.get(key)
        if (not isinstance(values, list) or not all(isinstance(v, str) and v for v in values)
                or len(set(values)) != len(values)):
            raise ValueError('bad ' + key)
    for path in rules['carried_contracts']:
        if (not path.startswith('contracts/') or posixpath.normpath(path) != path
                or '..' in path.split('/') or '\\' in path):
            raise ValueError('carried contract outside contracts/')
    return rules


def setting(target, settings):
    parts = target.split('/')
    return any(len(parts) == len(p.split('/')) and all(
        fnmatch.fnmatchcase(a, b) for a, b in zip(parts, p.split('/'))) for p in settings)


def inside(tree, path):
    # Containment by real path, so a link inside the tree cannot carry it out.
    root = os.path.realpath(tree)
    real = os.path.realpath(os.path.join(root, path))
    return (real == root or real.startswith(root + os.sep)) and os.path.exists(real)


def judge(tree, ref, settings):
    """One discovered reference: None when it stands alone, else its refusal."""
    kind = ref['kind']
    if kind in ('words', 'data'):
        return None
    record = {'rule': 'standalone.' + (kind if kind in RULES else 'read'),
              'file': ref['file'], 'line': ref['line']}
    target = ref.get('target')
    if kind == 'symlink' or not isinstance(target, str) or not target:
        return record
    if 'context' in ref:
        return None if operand(tree, ref, settings) else record
    if ref.get('project'):
        # The consumer project's own settings, read from it at run time.
        return None if kind == 'read' and setting(target, settings) else record
    if kind == 'link':
        if target.startswith('#'):
            return None
        scheme = re.match(r'([A-Za-z][A-Za-z0-9+.-]*):', target)
        if scheme:
            return None if scheme[1].lower() in WEB else record
        target = re.split(r'[#?]', target, maxsplit=1)[0]
        if not target:
            return record
    target = unquote(target)
    if target.startswith('/') or '\\' in target or '\0' in target:
        return record
    path = posixpath.normpath(posixpath.join(ref.get('base') or '.', target))
    if path == '..' or path.startswith('../') or not inside(tree, path):
        return record
    return None


# A literal operand (a script an instruction runs, a file a script opens) has a
# working context: 'project', the consumer project's root (also the package
# root, where skills/<name>/ lives), or an anchored folder a script changed to.
PLACEHOLDER = re.compile(r'^<([^<>/]+)>')


def placeholder(target, skill, tree):
    """A leading skill-folder placeholder, as instructions write it: its own
    (<this skill's folder>, <skill-directory>) or a named skill's carried folder
    (<build-ticket skill's folder>, <research-skill-folder>, <installed-huntr>,
    <build-ticket>). Anything else stays unresolved."""
    m = PLACEHOLDER.match(target)
    if not m:
        return target
    inner = m[1].strip().lower()
    name = inner[len('installed-'):] if inner.startswith('installed-') else None
    words = re.split(r"[\s_'-]+", inner)
    if name is None and 'skill' in words and set(words) & {'folder', 'directory', 'dir'}:
        name = re.sub(r"^(?:this|the)\b", '', inner.split('skill')[0]).strip(" -_'")
    elif name is None:
        name = inner
    if not name:
        return skill + target[m.end():]
    if re.fullmatch('[a-z0-9][a-z0-9-]*', name) and (Path(tree) / 'skills' / name).is_dir():
        return 'skills/' + name + target[m.end():]
    return target
SYSTEM = ('/dev/', '/proc/', '/sys/', '/etc/', '/usr/', '/bin/', '/tmp/', '/var/')


def operand(tree, ref, settings):
    skill = '/'.join(ref['file'].split('/')[:2])
    target = placeholder(ref['target'], skill, tree)
    if '<' in target or '>' in target or '\\' in target or '\0' in target:
        return False  # An unresolved placeholder is an unresolved dependency.
    if target.startswith('/'):
        return target.startswith(SYSTEM) and '..' not in target.split('/')
    context = ref['context']
    candidates = [join(context, target)]
    if context == '.' and ref.get('skill_relative'):
        # Instructions may also be relative to their skill or their own file.
        candidates[:0] = [join(skill, target), join(posixpath.dirname(ref['file']), target)]
    if any(c != '..' and not c.startswith('../') and inside(tree, c) for c in candidates):
        return True
    return context == '.' and ref['kind'] == 'read' and setting(posixpath.normpath(target), settings)


def up(path, levels=1):
    for _ in range(levels):
        path = posixpath.normpath(posixpath.join(path, '..'))
    return path


def join(path, part):
    return posixpath.normpath(posixpath.join(path, part))


def in_skills(path):
    return path == 'skills' or path.startswith('skills/')


class Finder:
    """References in one file. A value is ('p', path), or ('d', base) when
    an anchored path continues with a part only known at run time."""

    def __init__(self, rel):
        self.rel, self.dir, self.refs = rel, posixpath.dirname(rel), []

    def emit(self, kind, value, line):
        tag, path = value
        if tag == 'd':
            # Dynamic parts below skills/ stay in the package; above it they
            # are unresolved dependencies, refused rather than skipped.
            target = path if in_skills(path) else ''
        else:
            target = path
        self.refs.append({'kind': kind, 'file': self.rel, 'line': line, 'base': '.', 'target': target})

    def literal(self, kind, target, line, context='.', skill_relative=False):
        # Runtime values ($VAR, ~, tokens) are inputs, not package files.
        target = target.strip().strip('"\'')
        if not target or target.startswith(('-', '~')) or any(c in target for c in '$`\0*?'):
            return
        if context is None:
            return  # The script changed to a folder this check cannot know.
        self.refs.append({'kind': kind, 'file': self.rel, 'line': line, 'target': target,
                          'context': context, 'skill_relative': skill_relative})

    def commands(self, line, n, context='.', skill_relative=False, cargo_requirement=True):
        # This executable requirement names OpenWiz's absent Rust workspace.
        # Treat it as an unresolved script, preserving the fixed report shape.
        if cargo_requirement and re.search(r'(?:^|[;&|`]|\b(?:then|do|exec)\s)\s*cargo\s+test\s+'
                     r'(?:[^;&|`]*?\s)?(?:-p\s+|--package(?:=|\s+))openwiz-tests(?:\s|$)', line):
            self.refs.append({'kind': 'script', 'file': self.rel, 'line': n, 'target': ''})
        for m in SH_DIRECT.finditer(line):
            self.literal('script', m[1], n, context, skill_relative)
        for m in SH_COMMAND.finditer(line):
            flags, word = m[3].split(), m[4].strip('"\'')
            if any(f in ('-c', '-m', '-e', '--eval', '-p', '--print') for f in flags):
                continue
            # A path operand: a folder part or a file suffix (not `. as $x` in jq).
            if '/' in word or re.search(r'\.[A-Za-z0-9]+$', word):
                self.literal('script', word, n, context, skill_relative)


# Markdown ---------------------------------------------------------------

FENCE = re.compile(r'^ {0,3}(`{3,}|~{3,})')
CODE_SPAN = re.compile(r'(`+)(?:(?!\1).)+?\1')
INLINE = re.compile(r'\]\(\s*(<[^>\n]*>|[^\s()<>]*(?:\([^\s()]*\)[^\s()<>]*)*)'
                    r'(?:\s+(?:"[^"]*"|\'[^\']*\'|\([^)]*\)))?\s*\)')
DEFINITION = re.compile(r'^ {0,3}\[[^\]]+\]:\s*(<[^>\n]*>|\S+)')


# A local file run directly, in command position: `./x`, or a relative path
# ending in a script suffix (`tools/setup.py --flag`), after any VAR=value.
SH_DIRECT = re.compile(r'(?:^|[;&|(]|\$\(|\b(?:then|do|exec|else)\b)\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*'
                       r'(\./[^\s;&|()<>`\'"]+|[A-Za-z0-9_.<>\'-]+(?:/[A-Za-z0-9_.<>\' -]*?[A-Za-z0-9_.>-])+'
                       r'\.(?:py|sh|mjs|js|cjs))(?=\s|$|[;&|)`])')
SHELL_FENCES = {'sh', 'bash', 'shell', 'zsh', 'console', 'shell-session', 'sh-session'}
SH_COMMAND = re.compile(r'(?:(?:^|[;&|(]|\$\(|`|\b(?:then|do|exec|else)\b)\s*(python3?|node|sh|bash|zsh|dash)'
                        r'|(?:^|;|&&|\|\|)\s*(source|\.))'
                        r'((?:\s+-[^\s]+)*)\s+("[^"]*"|\'[^\']*\'|<[^<>\n]*>[^\s;&|()<>`]*|[^\s;&|()<>`]+)')


def markdown(finder, text):
    # Links outside code; commands an instruction runs inside shell fences and
    # code spans, from the consumer project (or, failing that, the skill folder).
    fence = info = None
    for n, line in enumerate(text.splitlines(), 1):
        mark = FENCE.match(line)
        if mark:
            if fence is None:
                fence = mark[1][0]
                info = line[mark.end():].strip().split(' ')[0].lower()
            elif mark[1][0] == fence:
                fence = None
            continue
        if fence:
            if info in SHELL_FENCES:
                command = line.strip()
                if info == 'console' or info.endswith('session'):
                    if not command.startswith('$ '):
                        continue  # Output, not a command.
                    command = command[2:]
                finder.commands(command, n, skill_relative=True)
            continue
        for span in CODE_SPAN.finditer(line):
            # Cargo isn't a file path. In prose, refuse it as a workspace
            # requirement, while retaining archived results as data. Shell
            # fences and executable scripts always remain requirements.
            prefix = line[:span.start()].strip(' -*')
            result = re.match(r'\s*:\s*(?:[0-9]+\s+(?:passed|failed)|pass\b|fail\b)',
                              line[span.end():])
            operative = bool(re.search(r'\b(?:run|runs|running|execute|invoke|use|must|require[sd]?|verify|verification|check)\b',
                                       prefix, re.I)) or (not prefix and not result)
            finder.commands(span[0].strip('`').strip(), n, skill_relative=True,
                            cargo_requirement=operative)
        line = CODE_SPAN.sub(' ', line)
        targets = [m[1] for m in INLINE.finditer(line)]
        definition = DEFINITION.match(line)
        if definition:
            targets.append(definition[1])
        for target in targets:
            if target.startswith('<') and target.endswith('>'):
                target = target[1:-1]
            finder.refs.append({'kind': 'link', 'file': finder.rel, 'line': n,
                                'base': finder.dir, 'target': target})


# Python -----------------------------------------------------------------

PATH_CALLS = {'Path', 'PurePath', 'PosixPath', 'pathlib.Path', 'pathlib.PurePath', 'os.path.abspath',
              'os.path.realpath', 'os.path.normpath', 'str', 'os.fspath', 'os.path.join'}
IMPORT_CALLS = {'sys.path.insert', 'sys.path.append', 'spec_from_file_location', 'run_path',
                'SourceFileLoader', 'addsitedir', 'exec'}
INTERPRETERS = {'python', 'python3', 'node', 'sh', 'bash', 'zsh', 'dash'}
SCRIPT_CALLS = {'run', 'call', 'check_call', 'check_output', 'Popen', 'system', 'execv', 'execve',
                'execvp', 'execl', 'execlp', 'spawnv', 'spawnl'}


def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return base + '.' + node.attr if base else node.attr
    return ''


class Python(Finder):
    def __init__(self, rel):
        super().__init__(rel)
        self.env, self.calls, self.syspath = {}, [], []

    def join_all(self, value, parts):
        if value is None:
            return None
        tag, path = value
        for part in parts:
            if tag == 'p' and isinstance(part, ast.Constant) and isinstance(part.value, str):
                path = join(path, part.value)
            else:
                tag = 'd'
        return tag, path

    def value(self, node):
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                return ('p', self.rel) if node.id == '__file__' else self.env.get(node.id)
            return None
        if isinstance(node, ast.Attribute) and node.attr == 'parent':
            inner = self.value(node.value)
            return inner and (inner[0], up(inner[1]))
        if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute)
                and node.value.attr == 'parents' and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, int) and node.slice.value >= 0):
            inner = self.value(node.value.value)
            return inner and (inner[0], up(inner[1], node.slice.value + 1))
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            return self.join_all(self.value(node.left), [node.right])
        if isinstance(node, ast.Call):
            name = dotted(node.func)
            if isinstance(node.func, ast.Attribute) and node.func.attr in ('resolve', 'absolute', 'expanduser'):
                return self.value(node.func.value)
            if isinstance(node.func, ast.Attribute) and node.func.attr == 'joinpath':
                return self.join_all(self.value(node.func.value), node.args)
            if name == 'os.path.dirname' and len(node.args) == 1:
                inner = self.value(node.args[0])
                return inner and (inner[0], up(inner[1]))
            if name in PATH_CALLS and node.args:
                return self.join_all(self.value(node.args[0]), node.args[1:])
        if isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.FormattedValue):
            base = self.value(node.values[0].value)
            if base is None:
                return None
            parts = [v if isinstance(v, ast.Constant) else None for v in node.values[1:]]
            if None in parts:
                return 'd', base[1]
            return self.join_all(base, [ast.Constant(''.join(p.value for p in parts).lstrip('/') or '.')])
        return None

    def kind(self):
        names = set()
        for name in self.calls:
            names.update((name, name.rsplit('.', 1)[-1]))
        if names & IMPORT_CALLS:
            return 'import'
        if names & SCRIPT_CALLS:
            return 'script'
        return 'read'

    def visit(self, node, anchored=False):
        if isinstance(node, ast.Assign):
            found = self.visit(node.value, anchored)
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if found and found[0] == 'p':
                        self.env[target.id] = found
                    else:
                        self.env.pop(target.id, None)
                else:
                    self.visit(target, anchored)
            return None
        found = self.value(node) if isinstance(node, ast.expr) else None
        if found and not anchored:
            kind = self.kind()
            self.emit(kind, found, node.lineno)
            if kind == 'import' and found[0] == 'p':
                self.syspath.append(found[1])
        call = isinstance(node, ast.Call)
        if call:
            self.sinks(node)
            self.calls.append(dotted(node.func))
        for child in ast.iter_child_nodes(node):
            self.visit(child, anchored or bool(found))
        if call:
            self.calls.pop()
        return found

    def sinks(self, node):
        # Literal operands: files opened or run with a literal path.
        name = dotted(node.func)
        last = name.rsplit('.', 1)[-1]
        text = [a.value if isinstance(a, ast.Constant) and isinstance(a.value, str) else None for a in node.args]
        plain = isinstance(node.func, ast.Name) or (isinstance(node.func, ast.Attribute)
                                                    and isinstance(node.func.value, ast.Name))
        if plain and name in ('open', 'io.open', 'codecs.open') and text and text[0]:
            self.literal('read', text[0], node.lineno)
        elif (isinstance(node.func, ast.Attribute) and node.func.attr in ('read_text', 'read_bytes', 'open')
              and isinstance(node.func.value, ast.Call) and dotted(node.func.value.func) in PATH_CALLS
              and len(node.func.value.args) == 1 and isinstance(node.func.value.args[0], ast.Constant)
              and isinstance(node.func.value.args[0].value, str)):
            self.literal('read', node.func.value.args[0].value, node.lineno)
        elif last == 'run_path' and text and text[0]:
            self.literal('import', text[0], node.lineno)
        elif last == 'spec_from_file_location' and len(text) > 1 and text[1]:
            self.literal('import', text[1], node.lineno)
        elif last in SCRIPT_CALLS and node.args and isinstance(node.args[0], (ast.List, ast.Tuple)):
            argv = node.args[0].elts
            context = '.'
            for keyword in node.keywords:
                if keyword.arg == 'cwd':
                    found = self.value(keyword.value)
                    context = found[1] if found and found[0] == 'p' else None
            words = [e.value if isinstance(e, ast.Constant) and isinstance(e.value, str) else
                     ('<python>' if dotted(e) == 'sys.executable' else None) for e in argv]
            if words and (words[0] == '<python>' or (words[0] and posixpath.basename(words[0]) in INTERPRETERS)):
                for word in words[1:]:
                    if word is None or word in ('-c', '-m', '-e', '--eval'):
                        break
                    if not word.startswith('-'):
                        self.literal('script', word, node.lineno, context)
                        break
            elif words and words[0] and '/' in words[0]:
                self.literal('script', words[0], node.lineno, context)

    def scan(self, tree, text):
        try:
            module = ast.parse(text)
        except (SyntaxError, ValueError) as error:
            self.refs.append({'kind': 'import', 'file': self.rel,
                              'line': max(getattr(error, 'lineno', None) or 1, 1), 'target': ''})
            return
        self.visit(module)
        for node in ast.walk(module):
            if isinstance(node, ast.Import):
                names = [(0, a.name) for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = ([(node.level, node.module)] if node.module else
                         [(node.level, a.name) for a in node.names])
            else:
                continue
            for level, name in names:
                if not self.module(tree, level, name):
                    self.refs.append({'kind': 'import', 'file': self.rel, 'line': node.lineno, 'target': ''})

    def module(self, tree, level, name):
        top = name.split('.')[0]
        if level == 0 and (top in sys.stdlib_module_names or top == '__future__'):
            return True
        folders = [up(self.dir, level - 1)] if level else [self.dir, *self.syspath]
        relative = name.replace('.', '/')
        return any(not join(f, relative).startswith('..') and (
            inside(tree, join(f, relative) + '.py') or inside(tree, join(f, relative)))
            for f in folders)


# Shell and JavaScript (lexical) -----------------------------------------

TOKEN = re.compile('\0([0-9]+)\0')
SH_ANCHOR = re.compile(r'\$\(\s*dirname\s+(?:--\s+)?"?\$(?:0|\{0\}|\{BASH_SOURCE(?:\[0\])?\})"?\s*\)|\$\{0%/\*\}')
SH_CD = re.compile(r'\$\(\s*cd\s+(?:-[LP]\s+)?(?:--\s+)?("?\0[0-9]+\0[^"\s]*"?)\s*&&\s*pwd(?:\s+-[LP])?\s*\)')
SH_USE = re.compile('\0([0-9]+)\0"?((?:/[^\\s"\'`$;|&<>(){}\\\\\0]*)?)')
SH_ASSIGN = re.compile(r'\s*(?:export\s+|local\s+|readonly\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)')
SH_CHDIR = re.compile(r'(?:^|[;&|(])\s*(?:cd|pushd)\b(?:\s+-[LP])*(?:\s+("[^"]*"|[^\s;&|()]+))?')
SH_RUN = re.compile(r'(?:^|[\s;|&(])(?:exec\s+)?(?:python3?|node|sh|bash|dash|\.|source)\s')
JS_DIR = re.compile(r'(?:path\.)?dirname\(\s*(?:url\.)?fileURLToPath\(\s*import\.meta\.url\s*\)\s*\)|import\.meta\.dirname')
JS_FILE = re.compile(r'(?:url\.)?fileURLToPath\(\s*import\.meta\.url\s*\)|import\.meta\.filename')
JS_URL = re.compile(r'new\s+URL\(\s*([\'"])([^\'"]*)\1\s*,\s*import\.meta\.url\s*\)')
JS_JOIN = re.compile('(?:path\\.)?(?:join|resolve)\\(\\s*\0([0-9]+)\0((?:\\s*,\\s*(?:\'[^\']*\'|"[^"]*"|[^,()]+))*)\\s*\\)')
JS_TEMPLATE = re.compile('`\\$\\{\\s*\0([0-9]+)\0\\s*\\}([^`$]*)`')
JS_ASSIGN = re.compile('\\s*(?:export\\s+)?(?:const|let|var)\\s+([A-Za-z_$][A-Za-z0-9_$]*)\\s*=\\s*\0([0-9]+)\0\\s*;?\\s*$')
JS_IMPORT = re.compile(r'''(?:\bimport\s+(?:[^'"]*?\s+from\s+)?|\bexport\s+[^'"]*?\s+from\s+|\bimport\(\s*|\brequire\(\s*|^\s*\}\s*from\s+)(['"])([^'"]+)\1''')
JS_LITERAL = re.compile(r"""('(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*"|`(?:[^`\\]|\\.)*`"""
                        r"""|(?<=[(,=:\[!&|?{};])\s*/(?![/*])(?:[^/\\\n]|\\.)+/[a-z]*)""")
JS_READ = re.compile(r'''\b(?:readFileSync|readFile|createReadStream)\(\s*(['"])([^'"]+)\1''')
JS_SPAWN = re.compile(r'''\b(?:spawn|spawnSync|execFile|execFileSync)\(\s*(['"])(?:node|python3?|sh|bash)\1\s*,\s*\['''
                      r'''\s*(?:(['"])-[^'"]*\2\s*,\s*)*(['"])([^'"]+)\3''')
JS_RUN = re.compile(r'\b(?:spawn|spawnSync|exec|execSync|execFile|execFileSync|fork)\(')


class Lexical(Finder):
    def __init__(self, rel):
        super().__init__(rel)
        self.values, self.env = [], {}

    def token(self, value):
        self.values.append(value)
        return '\0' + str(len(self.values) - 1) + '\0'

    def names(self, line, shell):
        if not shell:
            # A JavaScript name is a use only in code: never inside a string or
            # regular expression literal, and in a template only as ${name}.
            parts = JS_LITERAL.split(line)
            return ''.join(self.names_in(part, 'template' if part.startswith('`') else None)
                           if i % 2 else self.names_in(part, 'code') for i, part in enumerate(parts))
        return self.names_in(line, 'shell')

    def names_in(self, text, where):
        if where is None:
            return text
        for name in sorted(self.env, key=len, reverse=True):
            pattern = {'shell': r'\$\{' + re.escape(name) + r'\}|\$' + re.escape(name) + r'(?![A-Za-z0-9_])',
                       'code': r'(?<![.\w$])' + re.escape(name) + r'(?![\w$:])',
                       'template': r'(?<=\$\{)\s*' + re.escape(name) + r'\s*(?=\})'}[where]
            text = re.sub(pattern, lambda m, n=name: self.token(self.env[n]), text)
        return text

    def remaining(self, line, kind_of):
        for m in SH_USE.finditer(line):
            tag, path = self.values[int(m[1])]
            suffix = m[2]
            if any(c in suffix for c in '*?['):
                tag, suffix = 'd', suffix[:min(suffix.find(c) for c in '*?[' if c in suffix)].rsplit('/', 1)[0]
            following = line[m.end():m.end() + 1]
            if following == '$' or following == '\0':
                tag = 'd'
            path = join(path, suffix.lstrip('/')) if suffix.strip('/') else path
            self.emit(kind_of(path), (tag, path), self.line)

    def shell(self, text):
        self.cwd = '.'
        for self.line, raw in enumerate(text.splitlines(), 1):
            if raw.lstrip().startswith('#'):
                continue
            line = SH_ANCHOR.sub(lambda m: self.token(('p', self.dir)), raw)
            line = self.names(line, True)
            while True:
                reduced = SH_CD.sub(lambda m: self.cd(m[1]), line)
                if reduced == line:
                    break
                line = reduced
            run = bool(SH_RUN.search(raw))
            self.remaining(line, lambda p: 'script' if run or p.endswith(SCRIPT_SUFFIXES) else 'read')
            for change in SH_CHDIR.finditer(line):
                use = SH_USE.fullmatch(change[1].strip('"')) if change[1] else None
                if use and '$' not in use[2]:
                    _, path = self.values[int(use[1])]
                    self.cwd = join(path, use[2].lstrip('/')) if use[2].strip('/') else path
                else:
                    self.cwd = None
            # A quoted multi-word string (usage text, a jq program) runs
            # nothing here; a quoted single word stays an operand.
            self.commands(re.sub(r"'([^']*)'", lambda m: m[0] if not re.search(r'\s', m[1]) else "''", line),
                          self.line, self.cwd)
            assign = SH_ASSIGN.match(line)
            if assign:
                use = SH_USE.search(assign[2])
                self.env.pop(assign[1], None)
                if use and use.start() <= 1:
                    tag, path = self.values[int(use[1])]
                    if tag == 'p' and '$' not in use[2]:
                        self.env[assign[1]] = ('p', join(path, use[2].lstrip('/')) if use[2].strip('/') else path)

    def cd(self, inner):
        use = SH_USE.fullmatch(inner.strip('"'))
        if not use:
            return ''
        tag, path = self.values[int(use[1])]
        return self.token((tag, join(path, use[2].lstrip('/')) if use[2].strip('/') else path))

    def javascript(self, text):
        for self.line, raw in enumerate(text.splitlines(), 1):
            stripped = raw.lstrip()
            if stripped.startswith(('//', '*', '/*')):
                continue
            for m in JS_READ.finditer(raw):
                self.literal('read', m[2], self.line)
            for m in JS_SPAWN.finditer(raw):
                self.literal('script', m[4], self.line)
            for m in JS_IMPORT.finditer(raw):
                if m[2].startswith(('./', '../', '/')):
                    self.refs.append({'kind': 'import', 'file': self.rel, 'line': self.line,
                                      'base': self.dir, 'target': m[2]})
            line = JS_URL.sub(lambda m: self.token(('p', join(self.dir, m[2] or '.'))), raw)
            line = JS_DIR.sub(lambda m: self.token(('p', self.dir)), line)
            line = JS_FILE.sub(lambda m: self.token(('p', self.rel)), line)
            line = self.names(line, False)
            while True:
                reduced = JS_TEMPLATE.sub(lambda m: self.joined(m[1], [m[2]], literal=True), line)
                reduced = JS_JOIN.sub(lambda m: self.joined(m[1], re.findall(
                    r'\s*,\s*(\'[^\']*\'|"[^"]*"|[^,()]+)', m[2])), reduced)
                if reduced == line:
                    break
                line = reduced
            run = bool(JS_RUN.search(raw))
            self.remaining(line, lambda p: 'script' if run or p.endswith(SCRIPT_SUFFIXES) else 'read')
            assign = JS_ASSIGN.match(line)
            if assign:
                self.env[assign[1]] = self.values[int(assign[2])]

    def joined(self, index, parts, literal=False):
        tag, path = self.values[int(index)]
        for part in parts:
            part = part.strip()
            if literal:
                path = join(path, part.lstrip('/') or '.')
            elif len(part) >= 2 and part[0] == part[-1] and part[0] in '\'"':
                path = join(path, part[1:-1] or '.')
            else:
                tag = 'd'
        return self.token((tag, path))


# The tree ---------------------------------------------------------------

def language(name, text, executable=False):
    suffix = posixpath.splitext(name)[1]
    if suffix in ('.md', '.markdown'):
        return 'md'
    if suffix == '.py':
        return 'py'
    if suffix in ('.sh', '.bash'):
        return 'sh'
    if suffix in ('.mjs', '.js', '.cjs'):
        return 'js'
    first = text.split('\n', 1)[0]
    if (suffix == '' or executable) and first.startswith('#!'):
        if 'python' in first:
            return 'py'
        if 'node' in first:
            return 'js'
        if re.search(r'\b(?:sh|bash|dash|zsh)\b', first):
            return 'sh'
        return 'unsupported'  # A script this check cannot read for dependencies.
    return None


def references(tree, rel):
    data = (Path(tree) / rel).read_bytes()
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        # Binary resources (images) carry no file references; code or Markdown
        # that cannot be read cannot be checked, so it is refused.
        if posixpath.splitext(rel)[1] in ('.md', '.markdown', '.py', '.sh', '.bash', '.mjs', '.js', '.cjs'):
            return [{'kind': 'read', 'file': rel, 'line': 1, 'target': ''}]
        return []
    kind = language(rel, text, bool((Path(tree) / rel).stat().st_mode & 0o111))
    if kind == 'unsupported':
        return [{'kind': 'read', 'file': rel, 'line': 1, 'target': ''}]
    if kind == 'md':
        finder = Finder(rel)
        markdown(finder, text)
    elif kind == 'py':
        finder = Python(rel)
        finder.scan(tree, text)
    elif kind in ('sh', 'js'):
        finder = Lexical(rel)
        finder.shell(text) if kind == 'sh' else finder.javascript(text)
    else:
        return []  # Data files: any synthetic path in them is data.
    return finder.refs


def check(tree, settings):
    """All refusals for the skills under tree/skills, sorted, one per finding."""
    tree = Path(tree)
    skills = tree / 'skills'
    if skills.is_symlink() or not skills.is_dir():
        raise ValueError('no skills folder')
    found = set()
    def unreadable(error):
        raise error  # An unreadable folder is unchecked, never a pass.

    for folder, dirs, files in os.walk(skills, onerror=unreadable):
        base = Path(folder)
        for name in sorted(dirs + files):
            path = base / name
            rel = path.relative_to(tree).as_posix()
            if path.is_symlink():
                found.add(('standalone.symlink', rel, 1))
                if name in dirs:
                    dirs.remove(name)
            elif name in files:
                if not path.is_file():
                    raise ValueError('unsupported file')
                for ref in references(tree, rel):
                    result = judge(tree, ref, settings)
                    if result:
                        found.add((result['rule'], result['file'], result['line']))
    return [{'rule': r, 'file': f, 'line': n}
            for r, f, n in sorted(found, key=lambda x: (x[1], x[2], x[0]))]


def redacted(refusals, literals=()):
    """Records safe to print: each file location passed through the privacy
    check's own redaction, so a refused file's name cannot leak a private form."""
    spec = importlib.util.spec_from_file_location('privacy_check_redact', REDACTION)
    if spec is None or not REDACTION.is_file() or REDACTION.is_symlink():
        raise OSError('redaction helper missing')
    privacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(privacy)
    return [dict(record, file=privacy.redact(record['file'], literals)) for record in refusals]


def by_skill(refusals):
    result = {}
    for record in refusals:
        result.setdefault(record['file'].split('/')[1], []).append(record)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n', 1)[0])
    parser.add_argument('--tree', type=Path, required=True, help='staged WizSkills tree')
    parser.add_argument('--contract', type=Path, default=CONTRACT,
                        help='wizskills.v1 contract, or its normative values as .json')
    args = parser.parse_args(argv)
    try:
        text = args.contract.read_text(encoding='utf-8')
        rules = normative_rules(text) if args.contract.suffix == '.json' else contract_rules(text)
        settings = rules['project_settings']
        refusals = redacted(check(args.tree, settings))
    except (OSError, ValueError, UnicodeError, RecursionError):
        # Paths and contents can be private: name no input.
        print('standalone: refused; unreadable tree or contract', file=sys.stderr)
        return 1
    for record in refusals:
        print(json.dumps(record))
    return 1 if refusals else 0


if __name__ == '__main__':
    sys.exit(main())
