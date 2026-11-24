#!/usr/bin/env python3
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUDGET = Path('check', 'context-budget.json')
LABEL = 'context-increase'
USAGE = 'usage: python3 -I check/context_budget.py compare <base.json> <head.json> [--allow-increase]'
HELP = (
    'check/context-budget.json holds the UTF-8 byte size of every skill\'s SKILL.md, '
    'and CI fails a pull request that raises any of them above its base, a new skill counting as growth from 0. '
    'After you edit a SKILL.md, run `python3 -I check/run.py --write-context-budget` and commit the file with the edit; '
    'a shrink always passes. If the skill must grow, first cut what you can, then ask a maintainer '
    f'for the `{LABEL}` label, saying why the extra bytes earn their place in every agent\'s context, '
    'and rerun the job once it is added.'
)


def measure(root):
    return {path.parent.name: len(path.read_bytes())
            for path in sorted((root / 'skills').glob('*/SKILL.md')) if path.is_file()}


def render(sizes):
    return json.dumps(dict(sorted(sizes.items())), indent=2) + '\n'


def write(root):
    sizes = measure(root)
    (root / BUDGET).write_text(render(sizes), encoding='utf-8')
    return sizes


def grown(base, head):
    return [(name, base.get(name, 0), size) for name, size in sorted(head.items()) if size > base.get(name, 0)]


def load(path):
    sizes = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(sizes, dict) or not all(
            isinstance(k, str) and type(v) is int and v >= 0 for k, v in sizes.items()):
        raise ValueError(f'{path}: not an object of skill names to byte counts')
    return sizes


def main(argv):
    if argv in (['--help'], ['-h']):
        print(USAGE + '\n\n' + HELP)
        return 0
    allow = '--allow-increase' in argv
    args = [a for a in argv if a != '--allow-increase']
    if len(args) != 3 or args[0] != 'compare':
        print(USAGE, file=sys.stderr)
        return 2
    try:
        base, head = load(args[1]), load(args[2])
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
