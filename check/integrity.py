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
    'pytest.skip': 'pytest.skip',
    'pytest.xfail': 'pytest.xfail',
    'pytest.importorskip': 'pytest.importorskip',
}
PATCH_TAILS = ('patch.multiple', 'patch.dict', 'patch.object', 'patch')
MONKEY = {'monkeypatch.setattr', 'monkeypatch.delattr', 'monkeypatch.setitem'}
WARN_LINE = re.compile(
    r'(?i)(?:filterwarnings\s*=.*\bignore\b|-W\s*ignore\b|simplefilter\s*=.*\bignore\b)')
HUNK = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')
DEF_LINE = re.compile(r'^(?:async\s+)?def\s+(test[A-Za-z0-9_]*)\s*\(')
SKIP_LINE = re.compile(
    r'^\s*@(?:(pytest\.mark\.(?:skipif|skip|xfail))|(unittest\.skip(?:If|Unless)?)|(pytest\.(?:skip|xfail)))\b')
TEST_PARTS = {'test', 'tests', '__tests__'}


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
        capture_output=True, text=True, encoding='utf-8', errors='replace',
    )
    if check and run.returncode != 0:
        raise Unreadable()
    return run


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
    for line in text.splitlines():
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
        elif line.startswith('+') and not line.startswith('+++'):
            if new_line is not None:
                current['added_lines'].add(new_line)
                new_line += 1
        elif line.startswith('-') and not line.startswith('---'):
            if old_line is not None:
                current['removed'].append((old_line, line[1:]))
                old_line += 1
        elif line.startswith('\\'):
            continue
        else:
            if old_line is not None and not line.startswith(('diff ', 'index ', 'old mode', 'new mode',
                                                             'similarity ', 'rename ', 'deleted ', 'new file',
                                                             'copy ', 'dissimilarity ')):
                old_line += 1
            if new_line is not None and not line.startswith(('diff ', 'index ', 'old mode', 'new mode',
                                                             'similarity ', 'rename ', 'deleted ', 'new file',
                                                             'copy ', 'dissimilarity ')):
                new_line += 1
    return changes


def is_test_path(path):
    if not path:
        return False
    name = path.rsplit('/', 1)[-1]
    if name.startswith('test_') and name.endswith(('.py', '.sh')):
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
        tree = ast.parse(source)
    except SyntaxError:
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


def is_patch(name):
    if name in MONKEY:
        return True
    return any(name == tail or name.endswith('.' + tail) for tail in PATCH_TAILS)


def short_patch(name):
    if name in MONKEY:
        return name
    for tail in PATCH_TAILS:
        if name == tail or name.endswith('.' + tail):
            return tail
    return name


def is_test_target(target):
    parts = [part for part in re.split(r'[.:]', target) if part]
    modules = parts[:-1] if len(parts) >= 2 else parts
    return any(part in TEST_PARTS or part.startswith('test_') for part in modules)


def mock_label(node):
    name = dotted(called(node))
    if not is_patch(name):
        return None
    target = None
    if isinstance(node, ast.Call) and node.args:
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            target = arg.value
    if target and is_test_target(target):
        return None
    label = short_patch(name)
    return f'{label} {target}' if target else label


def warning_call(node):
    if not isinstance(node, ast.Call) or not node.args:
        return False
    name = dotted(node.func)
    if name not in {'warnings.filterwarnings', 'warnings.simplefilter', 'filterwarnings', 'simplefilter',
                    'pytest.mark.filterwarnings'} and not name.endswith(('.filterwarnings', '.simplefilter')):
        return False
    arg = node.args[0]
    return isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.lower().startswith('ignore')


def raise_skip(node):
    if not isinstance(node, ast.Raise) or node.exc is None:
        return False
    exc = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
    return dotted(exc) in {'unittest.SkipTest', 'SkipTest'}


def skip_label(node):
    if isinstance(node, ast.Call):
        name = dotted(node.func)
        if name == 'skipTest' or name.endswith('.skipTest'):
            return 'unittest.skip'
    return SKIP.get(dotted(called(node)))


def text_fallback(source, added):
    found = []
    for number, line in enumerate(source.splitlines(), 1):
        if number not in added:
            continue
        match = SKIP_LINE.match(line)
        if match:
            found.append(('skip', number, next(part for part in match.groups() if part)))
        elif 'monkeypatch.setattr' in line or re.search(r'\bpatch\s*\(', line):
            found.append(('mock', number, 'patch'))
    return found


def python_marks(source, added):
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return text_fallback(source, added)
    decorators = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            decorators.extend(node.decorator_list)
    decorator_ids = {id(item) for item in decorators}
    found = []

    def take(node):
        if node.lineno not in added:
            return
        label = skip_label(node)
        if label:
            found.append(('skip', node.lineno, label))
            return
        label = mock_label(node)
        if label:
            found.append(('mock', node.lineno, label))
            return
        if warning_call(node):
            found.append(('warn', node.lineno, ''))

    for node in decorators:
        take(node)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and id(node) not in decorator_ids:
            take(node)
        elif isinstance(node, ast.Raise) and node.lineno in added and raise_skip(node):
            found.append(('skip', node.lineno, 'unittest.skip'))
    return found


def config_warnings(source, added):
    found = []
    for number, line in enumerate(source.splitlines(), 1):
        if number in added and WARN_LINE.search(line):
            found.append(number)
    return found


def function_lines(path, old_fns, new_fns, removed):
    if old_fns is None:
        new_names = set()
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
        new_fns = [] if not new_test or not new_path.endswith('.py') else python_functions(new_source)
        if new_fns is None:
            new_fns = []
        lines.extend(function_lines(old_path, old_fns, new_fns, change['removed']))
    if new_source is not None:
        for kind, line, label in python_marks(new_source, change['added_lines']):
            if new_test or kind == 'warn':
                lines.append(render(kind, new_path, line, label))
    watched = new_path if not change['deleted'] else None
    if watched and not watched.endswith('.py'):
        source = blob(repo, head, watched)
        if source is not None:
            for line in config_warnings(source, change['added_lines']):
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
    body = '\n'.join(lines) if lines else 'No findings.'
    with open(path, 'a', encoding='utf-8') as handle:
        handle.write('## Test integrity\n\n' + body + '\n')


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
