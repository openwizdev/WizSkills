#!/usr/bin/env python3
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALWAYS = ('rules', 'standalone')
KEYS = {'name', 'skill', 'commands', 'env'}
NAME = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*')
SKILL_PATH = r'(?:skills/|\.\./)({names})(?![\w-])(?!\.[\w])'
SKILL_JOINED = r'''(?:/\s*|join(?:path)?\([^)\n]*?)['"]({names})['"]'''
SKILL_PATH_STRING = r'''['"]({names})/'''
JOINS_SKILLS_BY_VARIABLE = re.compile(r'''['"]skills['"]\s*(?:/|,)\s*[A-Za-z_]|skills/\$\{?[A-Za-z_]''')
QUOTED_SKILL = r'''['"]({names})['"]'''
LISTS_EVERY_SKILL = re.compile(r'''['"]skills['"]\s*\)\s*\.\s*(?:iterdir|r?glob)\(|skills/\*|(?:\.\.|\$\{?\w+\}?"?)/\.\./\*''')
CODE_SUFFIXES = {'.py', '.sh', '.mjs', '.js', '.cjs', '.ts'}
NEW_CHANGESET = re.compile(r'\.changeset/[^/]+\.md')
NOT_CHANGESET_NOTES = {'readme.md', 'agents.md', 'claude.md', 'gemini.md'}
CHECK = 'check'


def suite_folders(shards):
    rows = {}
    for shard in shards:
        skill = shard['skill']
        if skill is not None:
            rows[skill] = Path('skills', skill) if skill != CHECK else Path(CHECK)
    return rows


def code_in(folder):
    for path in sorted(folder.rglob('*')):
        if path.is_file() and not path.is_symlink():
            text = path.read_text(encoding='utf-8', errors='replace')
            if path.suffix.lower() in CODE_SUFFIXES or text.startswith('#!'):
                yield text


def reads(root, shards):
    rows = suite_folders(shards)
    skills_dir = root / 'skills'
    carried = ({p.name for p in skills_dir.iterdir()
                if p.is_dir() and not p.is_symlink() and (p / 'SKILL.md').is_file()}
               if skills_dir.is_dir() and not skills_dir.is_symlink() else set())
    skills = sorted({name for name in rows if (skills_dir / name).is_dir()} | carried)
    names = '|'.join(map(re.escape, sorted(skills, key=len, reverse=True)))
    found = {}
    for row, home in rows.items():
        hits = set()
        if names:
            forms = re.compile('|'.join(form.format(names=names) for form in (SKILL_PATH, SKILL_JOINED, SKILL_PATH_STRING)))
            for text in code_in(root / home):
                if LISTS_EVERY_SKILL.search(text):
                    hits.update(skills)
                hits.update(''.join(groups) for groups in forms.findall(text))
                if JOINS_SKILLS_BY_VARIABLE.search(text):
                    hits.update(re.findall(QUOTED_SKILL.format(names=names), text))
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


def new_changeset_note(path, added):
    name = path.split('/')[-1]
    return path in added and bool(NEW_CHANGESET.fullmatch(path)) and not name.startswith('.') \
        and name.lower() not in NOT_CHANGESET_NOTES


def owning_skill(path, rows, added):
    if new_changeset_note(path, added):
        return ''
    parts = path.split('/')
    if len(parts) >= 3 and parts[0] == 'skills' and parts[1] in rows and parts[1] != CHECK \
            and all(part not in ('', '.', '..') for part in parts) and '\\' not in path:
        return parts[1]
    return None


def select(root, shards, changed, event, added=frozenset()):
    if event != 'pull_request':
        return list(shards), f'event {event}'
    if not changed:
        return list(shards), 'no changed file'
    rows = suite_folders(shards)
    picked = set()
    for path in changed:
        skill = owning_skill(path, rows, added)
        if skill is None:
            return list(shards), f'{path or "(empty path)"} needs every shard'
        if skill:
            picked.add(skill)
    if picked:
        found = reads(root, shards)
        readers = sorted(row for row, read in found.items() if row != CHECK and read & picked)
        if readers:
            return list(shards), f"{', '.join(sorted(picked))} read by {', '.join(readers)}'s suites"
        if found.get(CHECK, set()) & picked:
            picked.add(CHECK)
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
        if not isinstance(name, str) or name in seen or not (skill is None or isinstance(skill, str)) \
                or not isinstance(shard['commands'], list) or not isinstance(shard['env'], dict):
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
    changed, added = [], set()
    if event == 'pull_request':
        git = subprocess.run(['git', '-C', str(ROOT), 'diff', '--name-status', '--no-renames', '-z',
                              base, 'HEAD', '--'], capture_output=True)
        if git.returncode != 0:
            print(f'select: cannot diff {base}: {git.stderr.decode(errors="replace").strip()}',
                  file=sys.stderr)
            return 1
        fields = git.stdout.decode('utf-8', errors='replace').split('\0')[:-1]
        statuses = dict(zip(fields[1::2], fields[0::2]))
        changed = list(statuses)
        added = {path for path, status in statuses.items() if status == 'A'}
    for path in changed:
        print(f'select: changed: {path}', file=sys.stderr)
    chosen, every = select(ROOT, shards, changed, event, added)
    if every:
        print(f'select: every shard: {every}', file=sys.stderr)
    names = {s['name'] for s in chosen}
    for shard in shards:
        print(f"select: {shard['name']}: {'run' if shard['name'] in names else 'skipped'}", file=sys.stderr)
    print(json.dumps(chosen))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
