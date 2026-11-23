#!/usr/bin/env python3
import ast
import re
import subprocess
import sys

RULES = {'exact-counts': 'Assert exact counts.', 'clock': 'Never race the clock.',
         'own-temp': 'Tests share nothing.'}
SOURCE = {'.py': 'python', '.sh': 'shell', '.js': 'js', '.mjs': 'js', '.cjs': 'js', '.ts': 'js'}
TEST_NAME = re.compile(r'(?:^|/)(?:tests?/(?:[^/]+/)*[^/]+|test[^/]*|[^/]*\.test\.[^/]+)$')
ARGS = r'[^()]*(?:\([^()]*\)[^()]*)*'
COUNT = r'(?:\blen\(' + ARGS + r'\)|\.count\(' + ARGS + r'\)|\.length\b)'
SHELL_COUNT = r'\$\([^()]*\b(?:grep -c|wc -l)\b[^()]*\)"?'
CLOCK = (r'(?:\btime\.(?:time|monotonic|perf_counter)(?:_ns)?\(|\bdatetime\.(?:now|utcnow)\(|'
         r'\bDate\.now\(|\bperformance\.now\()')
CHECKS = {
    'exact-counts': (re.compile('|'.join((
        r'\bassert(?:Greater|GreaterEqual)\(\s*' + COUNT + r'\s*,',
        r'\bassertNotEqual\(\s*' + COUNT + r'\s*,\s*0\s*\)',
        r'\bassert.*' + COUNT + r'\s*(?:>=?\s*\d|!=\s*0\b)',
        r'\bassert.*\b\d+\s*<=?\s*' + COUNT + r'(?!\s*<)',
        r'\[\s+' + SHELL_COUNT + r'\s+-g[te]\s+\d'))),
        'assert the exact number, never "at least"'),
    'clock': (re.compile(r'\bassert.*' + CLOCK + r'|\[\s+.*(?:\$SECONDS\b|\$\(date\b)'),
              'compare only what the test controls, never a measured time'),
}
TEMP_PATH = r'''/(?:var/)?tmp/([\w.$-][^\s'"`),;]*)'''
FIXED_TEMP = {'python': re.compile(r'''['"]''' + TEMP_PATH), 'js': re.compile(r'''['"`]''' + TEMP_PATH),
              'shell': re.compile(r'''(?:^|[\s'"=])''' + TEMP_PATH)}
TEMP_MESSAGE = 'use a fresh temporary folder of its own, never a fixed path under /tmp'
STRINGS = {'python': r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|#.*''',
           'js': r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|//.*''',
           'shell': r"""'[^']*'|(?:^|\s)#.*"""}
BINARY = re.compile(rb'^Binary files .* and ("?b/.*) differ$')
HUNK = re.compile(rb'^@@ -[0-9]+(?:,([0-9]+))? \+([0-9]+)(?:,([0-9]+))? @@')


def path_of(field):
    if field.startswith(b'"'):
        field = ast.literal_eval('b' + field.decode('ascii'))
    elif field.endswith(b'\t'):
        field = field[:-1]
    if not field.startswith(b'b/'):
        raise ValueError(field)
    return field[2:].decode('utf-8')


def added(patch):
    path, old, new, line = None, 0, 0, 0
    for raw in patch.split(b'\n'):
        if old or new:
            if raw.startswith(b'-'):
                old -= 1
            elif raw.startswith(b'+') and new:
                new -= 1
                if path is not None:
                    yield path, line, raw[1:]
                line += 1
            elif not raw.startswith(b'\\'):
                raise ValueError('a hunk ends early')
        elif raw.startswith(b'diff --git '):
            path = None
        elif BINARY.match(raw) and language(path_of(BINARY.match(raw)[1])):
            raise ValueError('a test source git calls binary')
        elif raw.startswith(b'+++ '):
            path = None if raw == b'+++ /dev/null' else path_of(raw[4:])
        elif raw.startswith(b'@@'):
            hunk = HUNK.match(raw)
            old, line, new = int(hunk[1] or 1), int(hunk[2]), int(hunk[3] or 1)


def language(path):
    suffix = path[path.rfind('.'):] if '.' in path.rsplit('/', 1)[-1] else ''
    return SOURCE.get(suffix) if TEST_NAME.search(path) else None


def findings(patch):
    for path, number, raw in added(patch):
        kind = language(path)
        if kind is None:
            continue
        text = raw.decode('utf-8')
        code = re.sub(STRINGS[kind], '""', text)
        for rule, (pattern, message) in CHECKS.items():
            if pattern.search(code):
                yield f'{rule} {path}:{number}: {message}'
        if any('XXX' not in name for name in FIXED_TEMP[kind].findall(text)):
            yield f'own-temp {path}:{number}: {TEMP_MESSAGE}'


def main(argv):
    if len(argv) != 3 or argv[:2] != ['diff', '--base']:
        print('usage: python3 -I check/checklist_rules.py diff --base <rev>', file=sys.stderr)
        return 2
    run = subprocess.run(['git', '-c', 'core.quotePath=true', 'diff', '--no-color', '--no-ext-diff', '-U0', '-M',
                          '--src-prefix=a/', '--dst-prefix=b/', f'{argv[2]}...HEAD', '--'], capture_output=True)
    try:
        if run.returncode:
            raise ValueError('git diff failed')
        found = list(findings(run.stdout))
    except (ValueError, TypeError, SyntaxError, UnicodeDecodeError):
        print(f'checklist: unreadable diff against {argv[2]!r}', file=sys.stderr)
        return 2
    for line in found:
        print(f'checklist: {line}')
    print(f'checklist: fail ({len(found)})' if found else 'checklist: pass')
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
