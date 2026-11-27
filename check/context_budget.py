#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABEL = 'context-increase'
USAGE = 'usage: python3 -I check/context_budget.py compare <base-rev> <head-rev> [--allow-increase] [--repo <path>]'
HELP = (
    'CI measures the UTF-8 byte size of every skill\'s SKILL.md at the pull request\'s base '
    'and head, and fails when any of them grows, a new skill counting as growth from 0; '
    'a shrink or removal always passes. If a skill must grow, first cut what you can, '
    f'then ask a maintainer for the `{LABEL}` label, saying why the extra bytes earn '
    'their place in every agent\'s context, and rerun the job once it is added.'
)


def measure_rev(repo, rev):
    if not rev or rev.startswith('-'):
        raise ValueError(f'invalid git revision: {rev!r}')
    run = subprocess.run(
        ['git', 'ls-tree', '-r', '-l', '-z', rev, '--', 'skills/'],
        cwd=repo, capture_output=True,
    )
    if run.returncode != 0:
        raise ValueError(f'git ls-tree failed for {rev!r}')
    if not run.stdout:
        return {}
    try:
        text = run.stdout.decode('utf-8')
    except UnicodeDecodeError as error:
        raise ValueError(f'non-UTF-8 path in {rev!r}') from error
    sizes = {}
    for entry in text.split('\0'):
        if not entry:
            continue
        header, sep, path = entry.partition('\t')
        fields = header.split()
        if not sep or len(fields) != 4:
            raise ValueError(f'unexpected ls-tree entry in {rev!r}')
        mode, kind, _oid, size_text = fields
        parts = path.split('/')
        if len(parts) == 3 and parts[0] == 'skills' and parts[2] == 'SKILL.md':
            if kind != 'blob' or mode not in ('100644', '100755'):
                raise ValueError(f'{rev}:{path}: not a regular file')
            size = int(size_text)
            if size < 0:
                raise ValueError(f'{rev}:{path}: negative size')
            sizes[parts[1]] = size
    return dict(sorted(sizes.items()))


def grown(base, head):
    return [(name, base.get(name, 0), size) for name, size in sorted(head.items()) if size > base.get(name, 0)]


def parse_args(argv):
    allow = False
    repo = ROOT
    positional = []
    idx = 0
    while idx < len(argv):
        arg = argv[idx]
        if arg == '--allow-increase':
            allow = True
        elif arg == '--repo':
            if idx + 1 >= len(argv):
                return None
            repo = Path(argv[idx + 1])
            idx += 1
        else:
            positional.append(arg)
        idx += 1
    if len(positional) != 3 or positional[0] != 'compare':
        return None
    return positional[1], positional[2], allow, repo


def main(argv):
    if argv in (['--help'], ['-h']):
        print(USAGE + '\n\n' + HELP)
        return 0
    parsed = parse_args(argv)
    if parsed is None:
        print(USAGE, file=sys.stderr)
        return 2
    base_rev, head_rev, allow, repo = parsed
    try:
        base, head = measure_rev(repo, base_rev), measure_rev(repo, head_rev)
    except (OSError, ValueError) as error:
        print(f'context budget: unreadable: {error}', file=sys.stderr)
        return 2
    growth = grown(base, head)
    if not growth:
        print('context budget: no skill grew')
        return 0
    print('context budget: grew compared to the base:')
    for name, before, after in growth:
        print(f'  {name}: {before} -> {after} bytes (+{after - before})')
    if allow:
        print(f'context budget: accepted by the {LABEL} label')
        return 0
    print(HELP)
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
