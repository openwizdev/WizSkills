#!/usr/bin/env python3
import ast
import os
import re
import subprocess
import sys
from pathlib import Path

USAGE = 'usage: python3 -I check/integrity.py --base <rev> [--head <rev>] [--repo <path>]'
SKIP = {
    'pytest.mark.skip': 'pytest.mark.skip',
    'pytest.mark.skipif': 'pytest.mark.skipif',
    'pytest.mark.xfail': 'pytest.mark.xfail',
    'unittest.skip': 'unittest.skip',
    'unittest.skipIf': 'unittest.skipIf',
    'unittest.skipUnless': 'unittest.skipUnless',
    'unittest.expectedFailure': 'unittest.expectedFailure',
    'pytest.skip': 'pytest.skip',
    'pytest.xfail': 'pytest.xfail',
    'pytest.importorskip': 'pytest.importorskip',
}
PATCH_TAILS = ('patch.multiple', 'patch.dict', 'patch.object', 'patch')
MOCK_ROOTS = ('', 'unittest.mock.', 'mock.', 'mocker.')
MONKEY = {'monkeypatch.setattr', 'monkeypatch.delattr', 'monkeypatch.setitem'}
WARN_LINE = re.compile(
    r'(?i)(?:filterwarnings\s*=.*\bignore\b|-W\s*ignore\b|simplefilter\s*=.*\bignore\b)')
IGNORE_ENTRY = re.compile(r'(?i)^\s*["\']?ignore(?:\s*:|["\']|\s*$)')
DOC_SUFFIXES = ('.md', '.markdown', '.rst', '.txt')
CONFIG_NAMES = {'pytest.ini', 'pyproject.toml', 'setup.cfg', 'tox.ini', 'pytest.toml'}
WARN_CALLS = {
    'warnings.filterwarnings', 'warnings.simplefilter', 'filterwarnings', 'simplefilter',
    'pytest.mark.filterwarnings',
}
HUNK = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')
DEF_LINE = re.compile(r'^\s*(?:async\s+)?def\s+(test[A-Za-z0-9_]*)\s*\(')
SKIP_LINE = re.compile(
    r'^\s*@(?:(pytest\.mark\.(?:skipif|skip|xfail))|(unittest\.(?:skip(?:If|Unless)?|expectedFailure))'
    r'|(pytest\.(?:skip|xfail)))\b')
TEST_PARTS = {'test', 'tests', '__tests__'}
# As check/run.py finds suites: test.py, test.sh, test_*.py/.sh and test-*.py/.sh.
TEST_SCRIPT = re.compile(r'test(?:[_-][^/]*)?\.(?:py|sh)')


class Unreadable(Exception):
    pass


class Fn:
    def __init__(self, qual, line, shape):
        self.qual = qual
        self.line = line
        self.shape = shape


def git(repo, *args, check=True):
    run = subprocess.run(
        ['git', '-C', str(repo), '-c', 'core.autocrlf=false', '-c', 'core.quotepath=false',
         '-c', 'diff.noprefix=false', '-c', 'diff.mnemonicPrefix=false', *args],
        capture_output=True,
    )
    if check and run.returncode != 0:
        raise Unreadable()
    run.stdout = run.stdout.decode('utf-8', errors='replace')
    return run


def lines_of(text):
    lines = text.split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    return lines


def python_source(text):
    # Python also ends a line at a bare \r; git doesn't, so keep git's line numbers.
    return text.replace('\r\n', '\n').replace('\r', ' ')


def unprefix(path):
    if path.startswith(('a/', 'b/')):
        return path[2:]
    return path


def take_quoted(text):
    if not text.startswith('"'):
        raise Unreadable()
    out, i = [], 1
    while i < len(text):
        char = text[i]
        if char == '"':
            return ''.join(out), text[i + 1:]
        if char == '\\' and i + 1 < len(text):
            nxt = text[i + 1]
            out.append({'n': '\n', 't': '\t', '\\': '\\', '"': '"'}.get(nxt, nxt))
            i += 2
            continue
        out.append(char)
        i += 1
    raise Unreadable()


def git_paths(line):
    rest = line[len('diff --git '):]
    if rest.startswith('"'):
        old, rest = take_quoted(rest)
        new, _rest = take_quoted(rest.lstrip())
        return unprefix(old), unprefix(new)
    idx = rest.find(' b/')
    if idx < 1 or not rest.startswith('a/'):
        raise Unreadable()
    return unprefix(rest[:idx]), unprefix(rest[idx + 1:])


def hunk_starts(line):
    match = HUNK.match(line)
    if not match:
        raise Unreadable()
    old_count = int(match.group(2) or '1')
    new_count = int(match.group(4) or '1')
    return (int(match.group(1)) if old_count else None, int(match.group(3)) if new_count else None)


def parse_diff(text):
    changes, current = [], None
    old_line = new_line = None
    for line in lines_of(text):
        if line.startswith('diff --git '):
            old, new = git_paths(line)
            current = {'old': old, 'new': new, 'deleted': False,
                       'added_lines': set(), 'removed': []}
            changes.append(current)
            old_line = new_line = None
        elif current is None:
            continue
        elif line.startswith('deleted file mode'):
            current['deleted'] = True
        elif line.startswith('rename from '):
            current['old'] = line[len('rename from '):]
        elif line.startswith('rename to '):
            current['new'] = line[len('rename to '):]
        elif line.startswith('@@'):
            old_line, new_line = hunk_starts(line)
        elif old_line is None and new_line is None:
            continue
        elif line.startswith('+'):
            if new_line is not None:
                current['added_lines'].add(new_line)
                new_line += 1
        elif line.startswith('-'):
            if old_line is not None:
                current['removed'].append((old_line, line[1:]))
                old_line += 1
        elif line.startswith('\\'):
            continue
        elif line.startswith(' '):
            if old_line is not None:
                old_line += 1
            if new_line is not None:
                new_line += 1
        else:
            raise Unreadable()
    return changes


def is_test_path(path):
    if not path:
        return False
    name = path.rsplit('/', 1)[-1]
    if TEST_SCRIPT.fullmatch(name):
        return True
    if name.endswith('_test.py') or name.endswith(('.test.py', '.test.mjs', '.test.js', '.spec.js', '.spec.mjs')):
        return True
    folders = path.split('/')[:-1]
    return (name.endswith(('.py', '.sh', '.mjs', '.js'))
            and any(part in TEST_PARTS for part in folders))


def blob(repo, rev, path):
    if not path:
        return None
    run = git(repo, 'show', f'{rev}:{path}', check=False)
    if run.returncode != 0:
        return None
    return run.stdout


def shape(node):
    body = '|'.join(ast.dump(item) for item in node.body)
    return ast.dump(node.args) + '|' + body


def python_functions(source):
    if source is None:
        return []
    try:
        tree = ast.parse(python_source(source))
    except (SyntaxError, ValueError):
        return None
    found = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith('test'):
            found.append(Fn(node.name, node.lineno, shape(node)))
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith('test'):
                    found.append(Fn(f'{node.name}.{child.name}', child.lineno, shape(child)))
    return found


def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        if base:
            return base + '.' + node.attr
    return ''


def called(node):
    return node.func if isinstance(node, ast.Call) else node


def short_patch(name):
    if name in MONKEY:
        return name
    for root in MOCK_ROOTS:
        if name.startswith(root) and name[len(root):] in PATCH_TAILS:
            return name[len(root):]
    return None


def is_test_target(target):
    parts = [part for part in re.split(r'[.:]', target) if part]
    modules = parts[:-1] if len(parts) >= 2 else parts
    return any(part in TEST_PARTS or part.startswith('test_') for part in modules)


def resolve(name, bound):
    if not name:
        return name
    head, dot, tail = name.partition('.')
    base = bound.get(head)
    if not base:
        return name
    return base + (dot + tail if dot else '')


def bind_stmt(local, stmt):
    if isinstance(stmt, ast.Import):
        for alias in stmt.names:
            if alias.asname:
                local[alias.asname] = alias.name
            else:
                top = alias.name.split('.')[0]
                local[top] = top
        return True
    if isinstance(stmt, ast.ImportFrom) and stmt.module:
        for alias in stmt.names:
            if alias.name == '*':
                continue
            local[alias.asname or alias.name] = stmt.module + '.' + alias.name
        return True
    return False


def mock_label(node, bound):
    label = short_patch(resolve(dotted(called(node)), bound))
    if not label:
        return None
    target = None
    if isinstance(node, ast.Call) and node.args:
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            target = arg.value
    if target and is_test_target(target):
        return None
    return f'{label} {target}' if target else label


def action_expr(node):
    if node.args:
        return node.args[0]
    for keyword in node.keywords:
        if keyword.arg == 'action':
            return keyword.value
    return None


def changed_line(node, added):
    start = getattr(node, 'lineno', None)
    if start is None:
        return None
    if start in added:
        return start
    end = getattr(node, 'end_lineno', None) or start
    for line in range(start + 1, end + 1):
        if line in added:
            return line
    return None


def warning_line(node, bound, added):
    if not isinstance(node, ast.Call):
        return None
    name = resolve(dotted(node.func), bound)
    if name not in WARN_CALLS and not name.endswith(('.filterwarnings', '.simplefilter')):
        return None
    expr = action_expr(node)
    if not (isinstance(expr, ast.Constant) and isinstance(expr.value, str)
            and expr.value.lower().startswith('ignore')):
        return None
    return changed_line(expr, added)


def raise_skip(node, bound):
    if not isinstance(node, ast.Raise) or node.exc is None:
        return False
    exc = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
    return resolve(dotted(exc), bound) in {'unittest.SkipTest', 'SkipTest'}


def skip_label(node, bound):
    if isinstance(node, ast.Call):
        name = resolve(dotted(node.func), bound)
        if name == 'skipTest' or name.endswith('.skipTest'):
            return 'unittest.skip'
    return SKIP.get(resolve(dotted(called(node)), bound))


def text_fallback(source, added):
    found = []
    for number, line in enumerate(lines_of(source), 1):
        if number not in added:
            continue
        match = SKIP_LINE.match(line)
        if match:
            found.append(('skip', number, next(part for part in match.groups() if part)))
        elif 'monkeypatch.setattr' in line or re.search(r'\bpatch\s*\(', line):
            found.append(('mock', number, 'patch'))
    return found


def child_blocks(stmt):
    blocks = []
    for name in ('body', 'orelse', 'finalbody'):
        value = getattr(stmt, name, None)
        if isinstance(value, list) and value and isinstance(value[0], ast.stmt):
            blocks.append(value)
    for handler in getattr(stmt, 'handlers', None) or []:
        if isinstance(getattr(handler, 'body', None), list):
            blocks.append(handler.body)
    for case in getattr(stmt, 'cases', None) or []:
        if isinstance(getattr(case, 'body', None), list):
            blocks.append(case.body)
    return blocks


def header_nodes(stmt):
    inside = set()
    for nested in child_blocks(stmt):
        for sub in nested:
            for node in ast.walk(sub):
                inside.add(id(node))
    return [node for node in ast.walk(stmt) if id(node) not in inside]


def python_marks(source, added):
    try:
        tree = ast.parse(python_source(source))
    except (SyntaxError, ValueError):
        return text_fallback(source, added)
    found = []

    def take(node, bound):
        label = skip_label(node, bound)
        if label and node.lineno in added:
            found.append(('skip', node.lineno, label))
            return
        label = mock_label(node, bound)
        if label and node.lineno in added:
            found.append(('mock', node.lineno, label))
            return
        warned = warning_line(node, bound, added)
        if warned:
            found.append(('warn', warned, ''))

    def scan(nodes, bound):
        funcs = {id(node.func) for node in nodes if isinstance(node, ast.Call)}
        for node in nodes:
            if isinstance(node, ast.Call):
                take(node, bound)
            elif isinstance(node, (ast.Attribute, ast.Name)) and id(node) not in funcs:
                # A mark used as a value: a decorator, pytestmark = ..., or marks=...
                label = SKIP.get(resolve(dotted(node), bound))
                if label and node.lineno in added:
                    found.append(('skip', node.lineno, label))

    def block(stmts, bound):
        local = dict(bound)
        for stmt in stmts:
            if bind_stmt(local, stmt):
                continue
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for dec in stmt.decorator_list:
                    scan(list(ast.walk(dec)), local)
                block(stmt.body, local)
                continue
            if isinstance(stmt, ast.Raise) and stmt.lineno in added and raise_skip(stmt, local):
                found.append(('skip', stmt.lineno, 'unittest.skip'))
            scan(header_nodes(stmt), local)
            for nested in child_blocks(stmt):
                block(nested, local)

    block(tree.body, {})
    return found


def config_warnings(path, source, added):
    bare = path.rsplit('/', 1)[-1] in CONFIG_NAMES
    found = []
    if path.lower().endswith(DOC_SUFFIXES):
        return found
    for number, line in enumerate(lines_of(source), 1):
        if number not in added:
            continue
        if WARN_LINE.search(line) or (bare and IGNORE_ENTRY.search(line)):
            found.append(number)
    return found


def function_lines(path, old_fns, new_fns, removed):
    if new_fns is None:
        return []
    if old_fns is None:
        new_names = {fn.qual for fn in new_fns}
        new_names.update(name.rsplit('.', 1)[-1] for name in list(new_names))
        lines = []
        for line, text in removed:
            match = DEF_LINE.match(text)
            if match and match.group(1) not in new_names:
                lines.append(f'deleted test function: {path}:{line} {match.group(1)}')
        return lines
    new_names = {fn.qual for fn in new_fns}
    by_shape = {}
    for fn in new_fns:
        by_shape.setdefault(fn.shape, []).append(fn)
    used, lines = set(), []
    old_names = {fn.qual for fn in old_fns}
    for fn in old_fns:
        if fn.qual in new_names:
            continue
        match = next((candidate for candidate in by_shape.get(fn.shape, [])
                      if id(candidate) not in used and candidate.qual not in old_names), None)
        if match is None:
            lines.append(f'deleted test function: {path}:{fn.line} {fn.qual}')
        else:
            used.add(id(match))
            lines.append(f'renamed test function: {path}:{fn.line} {fn.qual} -> {match.qual}')
    return lines


def render(kind, path, line, label):
    if kind == 'skip':
        return f'new skip mark: {path}:{line} {label}'
    if kind == 'mock':
        return f'new mock: {path}:{line} {label}'
    return f'ignored warning: {path}:{line}'


def findings_for(repo, base, head, change):
    old_path, new_path = change['old'], change['new']
    old_test, new_test = is_test_path(old_path), is_test_path(new_path) and not change['deleted']
    lines = []
    if old_test and (change['deleted'] or not new_test):
        lines.append(f'deleted test file: {old_path}:1')
    old_source = blob(repo, base, old_path) if old_path.endswith('.py') else None
    new_source = None if change['deleted'] or not new_path.endswith('.py') else blob(repo, head, new_path)
    if old_test or new_test:
        old_fns = python_functions(old_source) if old_path.endswith('.py') else []
        if not new_test or not new_path.endswith('.py'):
            new_fns = []
        else:
            new_fns = python_functions(new_source)
        lines.extend(function_lines(old_path, old_fns, new_fns, change['removed']))
    if new_source is not None:
        for kind, line, label in python_marks(new_source, change['added_lines']):
            if new_test or kind == 'warn':
                lines.append(render(kind, new_path, line, label))
    watched = new_path if not change['deleted'] else None
    if watched and not watched.endswith('.py'):
        source = blob(repo, head, watched)
        if source is not None:
            for line in config_warnings(watched, source, change['added_lines']):
                lines.append(f'ignored warning: {watched}:{line}')
    return lines


def collect(repo, base, head):
    changes = parse_diff(git(repo, 'diff', '-U0', '--find-renames', '--no-color', '--no-ext-diff', base, head).stdout)
    lines = []
    for change in changes:
        lines.extend(findings_for(repo, base, head, change))
    return sorted(set(lines))


def parse_args(argv):
    base, head, repo = None, 'HEAD', Path.cwd()
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in ('--base', '--head', '--repo') and index + 1 >= len(argv):
            return None
        if arg == '--base':
            base = argv[index + 1]
            index += 2
        elif arg == '--head':
            head = argv[index + 1]
            index += 2
        elif arg == '--repo':
            repo = Path(argv[index + 1])
            index += 2
        else:
            return None
    if not base or base.startswith('-') or head.startswith('-'):
        return None
    return base, head, repo


def write_summary(lines):
    path = os.environ.get('GITHUB_STEP_SUMMARY')
    if not path:
        return
    if lines:
        text = ''.join(line + '\n' for line in lines)
        fence = '`' * max([3] + [len(run) + 1 for run in re.findall('`+', text)])
        body = f'{fence}text\n{text}{fence}\n'
    else:
        body = 'No findings.\n'
    with open(path, 'a', encoding='utf-8') as handle:
        handle.write('## Test integrity\n\n' + body)


def main(argv):
    if argv in (['-h'], ['--help']):
        print(USAGE)
        return 0
    parsed = parse_args(argv)
    if parsed is None:
        print(USAGE, file=sys.stderr)
        return 2
    base, head, repo = parsed
    try:
        lines = collect(repo, base, head)
    except Unreadable:
        print('integrity: cannot read the diff', file=sys.stderr)
        return 1
    sys.stdout.write(''.join(f'{line}\n' for line in lines))
    write_summary(lines)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
