#!/usr/bin/env python3
"""The user's own skills that block OpenWiz's `install skills` (#2182). Standard library only.

  skill_clash.py list --build BUILD
  skill_clash.py rename --build BUILD --yes --operation ID

OpenWiz 0.1.0's `install skills` refuses the whole step when an agent's skills
folder already holds a folder with one of OpenWiz's skill names that OpenWiz did
not put there, and it names only the first one per agent. `list` finds every
such folder in every agent folder `install skills` writes to, the same way the
installer tells its own copies (the `.openwiz-skill` mark), and prints each one,
the free `<name>-mine` (or `-mine-2`, ...) it would move to, the one question to
ask, and an operation id. It changes nothing.

`rename`, only with --yes and that id, moves each listed folder to its new name
and sets its SKILL.md `name:` line to match, then checks each move: the new
folder is there with the new name line and the old path is gone. A different
plan than the one listed (the id no longer matches) is refused with nothing
moved. It never touches a folder OpenWiz put there, a link or a file.

Exits: 0 done (list: read; rename: every move checked), 2 usage,
5 refused, nothing moved, 6 a move did not check out.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

# The agent folders `install skills` writes to, as OpenWiz 0.1.0's tools/install/harness.py names them.
AGENTS = (('claude-code', '.claude', 'Claude Code'), ('codex', '.codex', 'Codex'),
          ('cursor', '.cursor', 'Cursor'), ('opencode', '.config/opencode', 'OpenCode'),
          ('grok', '.grok', 'Grok'))
MARKED = re.compile(rb'openwiz\.skill-copy\.v1\n[0-9a-f]{40}\n')  # the installer's copy mark
NAME = re.compile(r'^name:[ \t]*\S.*$', re.M)


def real_dir(path):
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    return stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()


def openwizs(path):
    """True when the folder holds OpenWiz's copy mark exactly, as the installer checks it."""
    try:
        fd = os.open(path / '.openwiz-skill', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return False
    try:
        text = os.read(fd, 64) if stat.S_ISREG(os.fstat(fd).st_mode) else b''
    finally:
        os.close(fd)
    return MARKED.fullmatch(text) is not None


def exists(path):
    return os.path.lexists(path)


def plan(build):
    skills = Path(build) / 'runtime/skills'
    names = sorted(p.name for p in skills.iterdir() if p.is_dir() and not p.is_symlink())
    if not names:
        raise SystemExit('refused: %s ships no skills' % skills)
    home, codex_home = Path(os.environ['HOME']), os.environ.get('CODEX_HOME')
    clashes, blocked = [], []
    for agent, relative, plain in AGENTS:
        folder = (Path(codex_home) if agent == 'codex' and codex_home else home / relative) / 'skills'
        if not real_dir(folder):
            continue
        for name in names:
            path = folder / name
            if not exists(path) or real_dir(path) and openwizs(path):
                continue
            if not real_dir(path):
                blocked.append({'agent': plain, 'path': str(path),
                                'why': 'a link or a file, not a folder of yours: look at it yourself'})
                continue
            n, new = 1, name + '-mine'
            while exists(folder / new):
                n += 1
                new = '%s-mine-%d' % (name, n)
            clashes.append({'agent': plain, 'name': name, 'path': str(path), 'rename_to': new,
                            'new_path': str(folder / new)})
    return clashes, blocked


def joined(words):
    return words[0] if len(words) == 1 else ', '.join(words[:-1]) + ' and ' + words[-1]


def question(clashes):
    if not clashes:
        return None
    names = list(dict.fromkeys(c['name'] for c in clashes))
    targets = list(dict.fromkeys(c['rename_to'] for c in clashes))
    taken = list(dict.fromkeys('%s-mine is already taken, so yours becomes %s.' % (c['name'], c['rename_to'])
                               for c in clashes if c['rename_to'] != c['name'] + '-mine'))
    one = len(clashes) == 1
    return ' '.join(['You already have your own %s named %s.' % ('skill' if len(names) == 1 else 'skills', joined(names))]
                    + taken
                    + ['Rename yours to %s (and %s) so OpenWiz can install?' % (joined(targets),
                                                                                 'its name line' if one else 'their name lines'),
                       'They keep working under the new names. (yes/no)'])


def operation(clashes):
    return hashlib.sha256(json.dumps(clashes, sort_keys=True).encode()).hexdigest()[:16]


def rename(clash):
    """Move one folder and set its name line; then check it. Returns the result line."""
    old, new = Path(clash['path']), Path(clash['new_path'])
    if exists(new) or not real_dir(old) or openwizs(old):
        return dict(clash, result='refused', why='changed since the list; nothing moved')
    os.rename(old, new)
    skill = new / 'SKILL.md'
    named = False
    if real_dir(new) and skill.is_file() and not skill.is_symlink():
        text = skill.read_text()
        head = re.match(r'---\n(.*?\n)---', text, re.S)
        if head and NAME.search(head[1]):
            body = NAME.sub('name: ' + clash['rename_to'], head[1], count=1)
            skill.write_text('---\n' + body + text[head.end(1):])
            named = True
    ok = (real_dir(new) and not exists(old)
          and (not named or re.search(r'^name: %s$' % re.escape(clash['rename_to']),
                                      skill.read_text(), re.M) is not None))
    return dict(clash, result='moved' if ok else 'unchecked',
                name_line='name: ' + clash['rename_to'] if named else 'none (its SKILL.md has no name line)')


def main(argv):
    parser = argparse.ArgumentParser(prog='skill_clash.py')
    parser.add_argument('command', choices=['list', 'rename'])
    parser.add_argument('--build', required=True)
    parser.add_argument('--yes', action='store_true')
    parser.add_argument('--operation')
    args = parser.parse_args(argv)
    clashes, blocked = plan(args.build)
    op = operation(clashes)
    if args.command == 'list':
        print(json.dumps({'clashes': clashes, 'blocked': blocked, 'question': question(clashes),
                          'operation': op if clashes else None}, indent=1))
        return 0
    if not args.yes or not args.operation:
        print('refused: rename needs --yes and the --operation `list` printed; nothing moved', file=sys.stderr)
        return 2
    if not clashes or args.operation != op:
        print('refused: the folders changed since `list` (run it again and ask again); nothing moved',
              file=sys.stderr)
        return 5
    results = [rename(c) for c in clashes]
    print(json.dumps({'renamed': results}, indent=1))
    return 0 if all(r['result'] == 'moved' for r in results) else 6


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
