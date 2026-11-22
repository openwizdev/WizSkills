#!/usr/bin/env python3
"""Pick the shards a pull request's changes need (WQ4, openwizdev/OpenWiz#2274).

python3 -I check/select.py --event <event> --base <rev> < shards.json > selected.json

Reads `check/run.py --list`'s JSON (contracts/check-shards.v1.md) on stdin and
prints the shards to run, in the same shape and list order. Only a
`pull_request` narrows the list; any other event runs every shard. A pull
request runs `rules`, `standalone` and the shards of each skill whose folder it
changes, plus every shard whose suites read that skill's files (found by
scanning, transitively). A new `.changeset/<name>.md` needs no shard: the gates
job reads it. Any other path (the check, the workflow, contracts, docs, a
folder without its own shards) runs every shard, and so does an empty diff.

The changed paths are `git diff --name-only --no-renames <rev> HEAD`, so a rename
counts both sides. stderr names each changed path and each shard as
`select: <shard>: run` or `select: <shard>: skipped`. Exits 0 with a list, 1
when git cannot diff (printing no list), 2 on bad arguments or input.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALWAYS = ('rules', 'standalone')
KEYS = {'name', 'skill', 'commands', 'env'}
NAME = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*')
# Another skill's path in a suite's code: `skills/<name>`, a sibling
# `../<name>`, or a quoted `<name>` joined onto a path (`/ 'name'`,
# `join(..., 'name'`). The lookaheads stop `beta` matching `beta-two`,
# `betamax` or `beta.x`, while `../beta/x.py` still matches.
PATH = r'(?:skills/|\.\./)({names})(?![\w-])(?!\.[\w])'
JOIN = r'''(?:/\s*|join(?:path)?\([^)\n]*?)['"]({names})['"]'''
# A file that joins the skills folder with a variable (`'skills' / name`,
# `skills/$name`) reads every skill it names in quotes, such as a loop's tuple.
BY_NAME = re.compile(r'''['"]skills['"]\s*(?:/|,)\s*[A-Za-z_]|skills/\$\{?[A-Za-z_]''')
QUOTED = r'''['"]({names})['"]'''
# A file that lists the skills folder reads every skill: an iterdir, glob or
# rglob of it, or a shell glob of it from the root, from two levels up or
# above a variable (never a `case` pattern of dot-dot components).
EVERY = re.compile(r'''['"]skills['"]\s*\)\s*\.\s*(?:iterdir|r?glob)\(|skills/\*|(?:\.\.|\$\{?\w+\}?"?)/\.\./\*''')
# Only code reads: Markdown and data (JSON fixtures, logs) never open a file.
CODE = {'.py', '.sh', '.mjs', '.js', '.cjs', '.ts'}
CHANGESET = re.compile(r'\.changeset/[^/]+\.md')
NOT_CHANGESETS = {'readme.md'}


def homes(shards):
    """Each SUITES row (a shard's skill) and the folder its suites live in."""
    rows = {}
    for shard in shards:
        skill = shard['skill']
        if skill is not None:
            rows[skill] = Path('skills', skill) if skill != 'check' else Path('check')
    return rows


def scanned(folder):
    for path in sorted(folder.rglob('*')):
        if path.is_file() and not path.is_symlink():
            text = path.read_text(encoding='utf-8', errors='replace')
            if path.suffix.lower() in CODE or text.startswith('#!'):
                yield text


def reads(root, shards):
    """{row: the skills whose files that row's suites read}, closed transitively."""
    rows = homes(shards)
    skills = sorted(name for name in rows if (root / 'skills' / name).is_dir())
    names = '|'.join(map(re.escape, sorted(skills, key=len, reverse=True)))
    found = {}
    for row, home in rows.items():
        hits = set()
        if names:
            forms = re.compile(PATH.format(names=names) + '|' + JOIN.format(names=names))
            for text in scanned(root / home):
                if EVERY.search(text):
                    hits.update(skills)
                hits.update(a or b for a, b in forms.findall(text))
                if BY_NAME.search(text):
                    hits.update(re.findall(QUOTED.format(names=names), text))
        hits.discard(row)
        found[row] = hits
    changed = True
    while changed:
        changed = False
        for row, hits in found.items():
            more = set().union(*(found.get(skill, set()) for skill in hits)) - hits - {row}
            if more:
                hits |= more
                changed = True
    return found


def skill_of(path, rows):
    """The skill a changed path belongs to, '' for a gate-only path, None if unplaceable."""
    if CHANGESET.fullmatch(path) and path.split('/')[1].lower() not in NOT_CHANGESETS:
        return ''
    parts = path.split('/')
    if len(parts) >= 3 and parts[0] == 'skills' and parts[1] in rows and parts[1] != 'check' \
            and all(part not in ('', '.', '..') for part in parts) and '\\' not in path:
        return parts[1]
    return None


def select(root, shards, changed, event):
    """(the shards to run, the reason every shard runs or None)."""
    if event != 'pull_request':
        return list(shards), f'event {event}'
    if not changed:
        return list(shards), 'no changed file'
    rows = homes(shards)
    picked = set()
    for path in changed:
        skill = skill_of(path, rows)
        if skill is None:
            return list(shards), f'{path or "(empty path)"} needs every shard'
        if skill:
            picked.add(skill)
    if picked:
        found = reads(root, shards)
        picked |= {row for row, read in found.items() if read & picked}
    return [s for s in shards if s['name'] in ALWAYS or s['skill'] in picked], None


def parse(text):
    shards = json.loads(text)
    if not isinstance(shards, list) or not shards:
        raise ValueError('not a non-empty list')
    seen = set()
    for shard in shards:
        if not isinstance(shard, dict) or set(shard) != KEYS:
            raise ValueError(f'a shard is not an object with exactly {sorted(KEYS)}')
        name, skill = shard['name'], shard['skill']
        if not isinstance(name, str) or name in seen or not (skill is None or isinstance(skill, str)):
            raise ValueError(f'bad or repeated shard {name!r}')
        if skill is not None and not NAME.fullmatch(skill):
            raise ValueError(f'bad skill {skill!r}')
        seen.add(name)
    return shards


def main(argv):
    if len(argv) != 4 or argv[0] != '--event' or argv[2] != '--base' or argv[3].startswith('-'):
        print('usage: python3 -I check/select.py --event <event> --base <rev> < shards.json',
              file=sys.stderr)
        return 2
    event, base = argv[1], argv[3]
    try:
        shards = parse(sys.stdin.read())
    except ValueError as e:
        print(f'select: bad shard list: {e}', file=sys.stderr)
        return 2
    changed = []
    if event == 'pull_request':
        git = subprocess.run(['git', '-C', str(ROOT), 'diff', '--name-only', '--no-renames', '-z',
                              base, 'HEAD', '--'], capture_output=True)
        if git.returncode != 0:
            print(f'select: cannot diff {base}: {git.stderr.decode(errors="replace").strip()}',
                  file=sys.stderr)
            return 1
        changed = [p for p in git.stdout.decode('utf-8', errors='replace').split('\0') if p]
    for path in changed:
        print(f'select: changed: {path}', file=sys.stderr)
    chosen, every = select(ROOT, shards, changed, event)
    if every:
        print(f'select: every shard: {every}', file=sys.stderr)
    names = {s['name'] for s in chosen}
    for shard in shards:
        print(f"select: {shard['name']}: {'run' if shard['name'] in names else 'skipped'}", file=sys.stderr)
    print(json.dumps(chosen))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
