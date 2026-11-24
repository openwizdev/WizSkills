#!/usr/bin/env python3
"""Print a fleet role's project context or check text before a public write."""

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys


CARD = 'docs/agents/public-writes.md'
FLEET = 'docs/agents/fleet.md'
AGENTS = 'docs/agents/'
GLOSSARY = 'GLOSSARY.md'
WORDS = ('Use the words in `GLOSSARY.md`; read it when you name something new, '
         'and the ADRs in `docs/adr/` that touch your area.')
ROLE_SECTIONS = {
    'builder': ('Supporting edits', 'Test commands', 'Approval rules'),
    'reviewer': ('Supporting edits', 'Test commands', 'CI checks', 'Approval rules'),
    'planner': ('Labels', 'Supporting edits', 'Approval rules'),
}
LEGACY_MODELS = {'Builder', 'Builder for small tickets', 'Reviewer for Claude-built',
                 'Reviewer for GPT-built', 'Fixer'}


def git(root, *args):
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env['GIT_NO_LAZY_FETCH'] = '1'
    result = subprocess.run(['git', *args], cwd=root, env=env, capture_output=True, text=True)
    return result.stdout.rstrip('\n') if result.returncode == 0 else ''


def sections(text):
    result = {}
    heading = None
    fence = ''
    for line in text.splitlines(keepends=True):
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if marker:
            run, tail = marker.groups()
            if not fence:
                fence = run
            elif run.startswith(fence) and not tail.strip():
                fence = ''
        if not fence and line.startswith('## '):
            heading = line[3:].strip()
            result[heading] = []
        if heading is not None:
            result[heading].append(line)
    return {name: ''.join(lines).strip() for name, lines in result.items()}


def selected_sections(path, text, names):
    found = sections(text)
    if names is None:
        excluded = {'Test commands', 'Supporting edits'}
        if 'Models' in found:
            excluded.update(LEGACY_MODELS)
        names = [name for name in found if name not in excluded]
    return [found.get(name, f'No `{name}` section in `{path}`.') for name in names]


def labels_table(text):
    labels = sections(text).get('Labels', '')
    match = re.search(r'^ *\|[^\n]+\n *\|[ |:\-]+(?:\n *\|[^\n]+)*', labels, re.M)
    return match[0] if match else 'No Labels table in `docs/agents/triage-labels.md`.'


def read_optional(path):
    try:
        return path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return None


def print_role(role, root):
    head = git(root, 'rev-parse', 'HEAD')
    short = git(root, 'rev-parse', '--short', head) if head else 'no commit'
    blobs = []
    parts = []
    sources = [(CARD, None), (FLEET, ROLE_SECTIONS.get(role))]
    if role == 'fleet':
        sources += [(AGENTS + 'triage-labels.md', None), (AGENTS + 'host.md', None)]
    if role == 'planner':
        sources += [(AGENTS + 'issue-tracker.md', ('Where things live', 'Repositories')),
                    (AGENTS + 'triage-labels.md', None),
                    (AGENTS + 'domain.md', ('Private storage',)), (AGENTS + 'roads.md', None)]
    if role != 'fleet':
        sources.append((GLOSSARY, None))
    for path, names in sources:
        if path == GLOSSARY and role != 'planner':
            text = '' if (root / path).is_file() else None
        else:
            text = read_optional(root / path)
        if text is None:
            if path == CARD:
                parts.append('Missing public-writes card: read the open-development contract before your first public write.')
            if path == FLEET:
                parts.append('No `docs/agents/fleet.md`: run the `setup` skill first.')
            continue
        blob = git(root, 'rev-parse', '--verify', f'{head}:{path}') if head else ''
        blobs.append(f'{path} {blob or "untracked"}')
        if path == GLOSSARY:
            if role == 'planner':
                terms = re.findall(r'^\*\*([^*\n]+)\*\*:', text, re.M)
                if terms:
                    parts.append(', '.join(terms))
            parts.append(WORDS)
        elif role == 'planner' and path == AGENTS + 'triage-labels.md':
            parts.append(labels_table(text))
        elif path == FLEET or names is not None:
            parts.extend(selected_sections(path, text, names))
        else:
            parts.append(text.rstrip('\n'))
    print(f'# Context for {role} at {short}\n\nBlobs: ' + (', '.join(blobs) or 'none') + '\n')
    if parts:
        print('\n\n'.join(parts))


ID_SUFFIX = r'_(?!(?:syn|web))[A-Za-z0-9]'
PATTERNS = (
    ('thread id', re.compile(r'(?<![A-Za-z0-9])thr' + ID_SUFFIX)),
    ('loop id', re.compile(r'(?<![A-Za-z0-9])loop' + ID_SUFFIX)),
    ('CloudRoom id', re.compile(r'(?<![A-Za-z0-9])(?:proj|prj|mch|usr|acct|auto|cr)' + ID_SUFFIX)),
    ('token shape', re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]+|github_pat_[A-Za-z0-9_]+'
                               r'|AKIA[0-9A-Z]{16}|(?:sk|xox[baprs])-[A-Za-z0-9_-]{16,})')),
    ('quoted decision words', re.compile(r'(?<!\*)\*\*(?=\S)(?:(?!\*\*).)+?:\*\*[ \t]*\\?["“”]')),
)
HOME = re.compile(r'''/(?:Users|home)/([^/\s"'\x60>:;,()\[\]{}]+)''')
EMAIL = re.compile(r'(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@([A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,})')
EXAMPLE_DOMAINS = {'example.com', 'example.org', 'example.net', 'example.invalid', 'users.noreply.github.com'}


def private_kinds(line):
    for kind, pattern in PATTERNS:
        if pattern.search(line):
            yield kind
    if any(name not in {'runner', 'cache', 'token', 'secret', 'someone'}
           and not name.startswith(('synthetic', 'example', '<')) for name in HOME.findall(line)):
        yield 'home folder'
    if any(m[1].lower() not in EXAMPLE_DOMAINS and not m[1].lower().endswith('.example')
           and m[0].lower() != 'noreply@github.com' for m in EMAIL.finditer(line)):
        yield 'email address'


def file_label(path, index):
    return path if path.isprintable() and not next(private_kinds(path), None) else f'file {index}'


def delegated_findings(tool, path, root):
    result = subprocess.run([sys.executable, '-I', tool, '--title-file', os.devnull, '--body-file', path],
                            cwd=root, capture_output=True)
    if result.returncode == 0:
        return []
    if result.returncode != 1:
        raise OSError('project privacy check could not run')
    rules = re.findall(rb'^(T[123]|READ) pr-body:([1-9][0-9]{0,8})$', result.stdout, re.M)
    return [(line.decode(), f'project privacy check {rule.decode()}') for rule, line in rules] or [
        ('1', 'project privacy check')]


def check_files(root, files):
    tool = root / 'tools/privacy-check/check.py'
    try:
        tool.lstat()
    except FileNotFoundError:
        tool = None
    count = 0
    for index, path in enumerate(files, 1):
        label = file_label(path, index)
        try:
            lines = Path(path).read_text(encoding='utf-8').splitlines()
        except (OSError, UnicodeError, ValueError):
            print(f'{label}: could not read public text')
            return 2
        findings = [(number, kind) for number, line in enumerate(lines, 1) for kind in private_kinds(line)]
        if tool is not None:
            try:
                findings.extend(delegated_findings(tool, Path(path).absolute(), root))
            except OSError:
                print(f'{label}: project privacy check could not run')
                return 2
        for line, kind in findings:
            print(f'{label}:{line}: {kind}')
        count += len(findings)
    print(f'check: refused ({count})' if count else 'check: ok')
    return int(bool(count))


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, 'context.py: invalid arguments\n')


def main():
    parser = Parser(description=__doc__)
    commands = parser.add_subparsers(dest='role', required=True)
    for role in (*ROLE_SECTIONS, 'fleet'):
        commands.add_parser(role).add_argument('--root', type=Path)
    commands.add_parser('check').add_argument('files', nargs='+')
    args = parser.parse_args()
    try:
        root = getattr(args, 'root', None)
        if root is None:
            root = Path(git(Path.cwd(), 'rev-parse', '--show-toplevel') or '.')
        root = root.absolute()
        if args.role == 'check':
            return check_files(root, args.files)
        print_role(args.role, root)
        return 0
    except (OSError, UnicodeError, ValueError):
        print('context.py: could not read project context', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
