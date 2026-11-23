#!/usr/bin/env python3
import ast
import re
import subprocess
import sys

RULES = {'exact-counts': 'Assert exact counts.', 'clock': 'Never race the clock.',
         'own-temp': 'Tests share nothing.'}
COUNTED = r'(?:len\(|\.count\(|\.length\b|grep -c|wc -l)'
CHECKS = {
    'exact-counts': (re.compile('|'.join((
        r'assert(?:Greater|GreaterEqual)\(\s*' + COUNTED,
        r'\bassert\b.*' + COUNTED + r'.*(?:>|>=|!=\s*0)',
        r'assert(?:True|\.ok)?\(.*' + COUNTED + r'.*(?:>|>=|!=\s*0)',
        r'assertNotEqual\(\s*' + COUNTED + r'.*,\s*0\s*\)',
        COUNTED + r'.*\s-g[et]\s'))),
        'assert the exact number, never "at least"'),
    'clock': (re.compile(
        r'\bassert.*(?:\btime\.(?:time|monotonic|perf_counter)(?:_ns)?\(|\bdatetime\.(?:now|utcnow)\(|'
        r'\bDate\.now\(|\bperformance\.now\(|\$\(date\b|\$SECONDS\b)'),
        'compare only what the test controls, never a measured time'),
    'own-temp': (re.compile(r'''(?:^|[\s'"`=(:,])/(?:var/)?tmp/'''),
                 'use a fresh temporary folder of its own, never a fixed path under /tmp'),
}
TEST_FILE = re.compile(r'(?:^|/)(?:tests?/.*|test[^/]*|[^/]*\.test\.[^/]*)$')
HUNK = re.compile(r'^@@ -[0-9,]+ \+([0-9]+)(?:,[0-9]+)? @@')


def path_of(field):
    if field.startswith('"'):
        field = ast.literal_eval('b' + field).decode('utf-8')
    if not field.startswith('b/'):
        raise ValueError(field)
    return field[2:]


def added(patch):
    path, line = None, None
    for text in patch.split('\n'):
        if text.startswith('+++ '):
            path = None if text == '+++ /dev/null' else path_of(text[4:])
        elif text.startswith('@@'):
            line = int(HUNK.match(text)[1])
        elif text.startswith('+') and path is not None:
            yield path, line, text[1:]
            line += 1


def findings(patch):
    for path, number, text in added(patch):
        if TEST_FILE.search(path):
            for rule, (pattern, message) in CHECKS.items():
                if pattern.search(text):
                    yield f'{rule} {path}:{number}: {message}'


def main(argv):
    if len(argv) != 3 or argv[:2] != ['diff', '--base']:
        print('usage: python3 -I check/checklist_rules.py diff --base <rev>', file=sys.stderr)
        return 2
    run = subprocess.run(['git', '-c', 'core.quotePath=true', 'diff', '--no-color', '--no-ext-diff', '--text',
                          '-U0', '-M', '--src-prefix=a/', '--dst-prefix=b/', f'{argv[2]}...HEAD', '--'],
                         capture_output=True)
    try:
        if run.returncode:
            raise ValueError('git diff failed')
        found = list(findings(run.stdout.decode('utf-8')))
    except (ValueError, TypeError, SyntaxError, UnicodeDecodeError):
        print(f'checklist: unreadable diff against {argv[2]!r}', file=sys.stderr)
        return 2
    for line in found:
        print(f'checklist: {line}')
    print(f'checklist: fail ({len(found)})' if found else 'checklist: pass')
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
