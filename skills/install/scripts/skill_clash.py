#!/usr/bin/env python3
"""The user's own skills that block OpenWiz's `install skills` (#2182). Standard library only.

  skill_clash.py list --build BUILD [--root ROOT]
  skill_clash.py rename --build BUILD [--root ROOT] --yes --operation ID

OpenWiz 0.1.0's `install skills` refuses the whole step when an agent's skills
folder already holds a folder with one of OpenWiz's skill names that OpenWiz did
not put there, and it names only the first one per agent. `list` finds every
such folder in every agent folder `install skills` writes to, with the free
`<name>-mine` (or `-mine-2`, ...) it would move to, the one question to ask and
an operation id. It changes nothing.

It resolves the agent folders and checks them exactly as the 0.1.0 installer
does (tools/install/harness.py and install.py at v0.1.0): an absolute plain
path, no linked or non-folder ancestor, folders of this user's, OpenWiz's own
copies by their exact `.openwiz-skill` mark, no stray staging or backup folder,
and `<root>/skills` too when --root is given. It runs those checks as if the
listed moves were done. When the installer would still refuse anything, or a
clashing folder cannot be renamed safely (its SKILL.md is a link or not a plain
file of this user's, or has no frontmatter), each is in `blocked` with why, and
there is no question and no operation: nothing may move.

`rename`, only with --yes and the id `list` printed, runs the same checks
again, refuses with nothing moved if anything changed, then moves each folder
and rewrites its SKILL.md `name:` line (a new file put in place, so a hard link
elsewhere is not changed). A move counts only when the new folder's SKILL.md is
read back with the new name line and the old path is gone.

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
import tempfile

# The agent folders `install skills` writes to: (id, the folder under HOME, its plain name), as 0.1.0 names them.
AGENTS = (('claude-code', '.claude', 'Claude Code'), ('codex', '.codex', 'Codex'),
          ('cursor', '.cursor', 'Cursor'), ('opencode', '.config/opencode', 'OpenCode'),
          ('grok', '.grok', 'Grok'))
MARKED = re.compile(rb'openwiz\.skill-copy\.v1\n[0-9a-f]{40}\n')  # the installer's copy mark
FRONT = re.compile(r'\A---\n(.*?\n)---(\n|\Z)', re.S)
NAME = re.compile(r'^name:[ \t]*(.*?)[ \t]*$', re.M)


class Refused(Exception):
    pass


def require(value, reason):
    if not value:
        raise Refused(reason)


# --- the 0.1.0 installer's checks, as tools/install/install.py and harness.py make them ---

def path_guard(path):
    require(path.is_absolute() and '..' not in path.parts and '.' not in path.parts, 'absolute plain path required')
    for parent in (path, *path.parents):
        if parent.exists() or parent.is_symlink():
            require(not parent.is_symlink() and parent.is_dir(), 'symlink or non-directory ancestor')


def owned_dir(path):
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid(),
            f'{path} is a link or not your folder; nothing was changed')
    return True


def ours(path):
    if not owned_dir(path):
        return True
    try:
        fd = os.open(path / '.openwiz-skill', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return False
    try:
        text = os.read(fd, 64) if stat.S_ISREG(os.fstat(fd).st_mode) else b''
    finally:
        os.close(fd)
    return MARKED.fullmatch(text) is not None


def guard_parent(base, plain):
    try:
        path_guard(base.parent)
    except Refused:
        culprit = next((p for p in (base.parent, *base.parent.parents)
                        if p.is_symlink() or (p.exists() and not p.is_dir())), base.parent)
        raise Refused(f'{culprit} is a link or not a folder, so OpenWiz will not write {plain}\'s skills '
                      f'through it; nothing was changed.') from None


def check(folder, names, moving):
    """harness.check, with the folders in `moving` taken as already moved away."""
    path_guard(folder)
    if not owned_dir(folder):
        return
    for name in names:
        target = folder / name
        require(target in moving or ours(target), f'{target} is not an OpenWiz copy; nothing was changed')
        for path in (folder / f'.openwiz-stage-{name}', folder / f'.openwiz-old-{name}'):
            try:
                clear = ours(path)
            except Refused:
                clear = False
            require(clear, f'{path} is in the way and OpenWiz did not make it; nothing was changed.')


# --- the plan ---

def skill_md_problem(folder):
    """Why this folder's SKILL.md can't have its name line rewritten safely, or None (no SKILL.md is fine)."""
    skill = folder / 'SKILL.md'
    try:
        info = os.lstat(skill)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode):
        return f'{skill} is a link, so its name line cannot be changed safely here; nothing was changed'
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        return f'{skill} is not a plain file of yours; nothing was changed'
    head = FRONT.match(skill.read_text())
    if not head or not NAME.search(head[1]):
        return f'{skill} has no name line in its frontmatter, so it cannot be renamed safely; nothing was changed'
    return None


def plan(build, root):
    skills = Path(build) / 'runtime/skills'
    names = sorted(p.name for p in skills.iterdir() if p.is_dir() and not p.is_symlink())
    require(names, f'{skills} ships no skills')
    home, codex_home = Path(os.environ['HOME']), os.environ.get('CODEX_HOME')
    clashes, blocked, folders = [], [], []
    for agent, relative, plain in AGENTS:
        base = Path(codex_home) if agent == 'codex' and codex_home else home / relative
        try:
            require(base.is_absolute(), f'{base} is not an absolute folder')
            try:
                present = owned_dir(base)
            except NotADirectoryError:
                present = False
            if not present:
                continue
            guard_parent(base, plain)
            folder = base / 'skills'
            path_guard(folder)
            if owned_dir(folder):
                for name in names:
                    path = folder / name
                    if ours(path):
                        continue
                    problem = skill_md_problem(path)
                    if problem:
                        blocked.append({'agent': plain, 'path': str(path), 'why': problem})
                        continue
                    n, new = 1, name + '-mine'
                    while os.path.lexists(folder / new):
                        n += 1
                        new = '%s-mine-%d' % (name, n)
                    clashes.append({'agent': plain, 'name': name, 'path': str(path), 'rename_to': new,
                                    'new_path': str(folder / new)})
            folders.append((plain, folder))
        except Refused as refusal:
            blocked.append({'agent': plain, 'path': str(base), 'why': str(refusal)})
        except OSError as error:
            blocked.append({'agent': plain, 'path': str(error.filename or base),
                            'why': f'OpenWiz could not look inside it ({error.strerror}); nothing was changed'})
    if root:
        folders.append(('OpenWiz', Path(root) / 'skills'))
    moving = {Path(c['path']) for c in clashes}
    for plain, folder in folders:  # the installer's own check, as if every listed move were done
        try:
            check(folder, names, moving)
        except Refused as refusal:
            if not any(b['path'] in str(refusal) for b in blocked):
                blocked.append({'agent': plain, 'path': str(folder), 'why': str(refusal)})
        except OSError as error:
            blocked.append({'agent': plain, 'path': str(error.filename or folder),
                            'why': f'OpenWiz could not look inside it ({error.strerror}); nothing was changed'})
    return clashes, blocked


def joined(words):
    return words[0] if len(words) == 1 else ', '.join(words[:-1]) + ' and ' + words[-1]


def question(clashes):
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


def name_line(skill):
    """The frontmatter name of a plain, unlinked SKILL.md, or None."""
    try:
        if not stat.S_ISREG(os.lstat(skill).st_mode):
            return None
    except FileNotFoundError:
        return None
    head = FRONT.match(skill.read_text())
    found = head and NAME.search(head[1])
    return found[1] if found else None


def rename(clash):
    """Move one folder, put a new SKILL.md with the new name line in place, then read it back."""
    old, new = Path(clash['path']), Path(clash['new_path'])
    os.rename(old, new)
    skill = new / 'SKILL.md'
    had = os.path.lexists(skill)
    if had:
        text = skill.read_text()
        head = FRONT.match(text)
        body = NAME.sub('name: ' + clash['rename_to'], head[1], count=1)
        fd, temp = tempfile.mkstemp(dir=new, prefix='.SKILL.md.')
        with os.fdopen(fd, 'w') as out:
            out.write('---\n' + body + text[head.end(1):])
        os.chmod(temp, stat.S_IMODE(os.lstat(skill).st_mode))
        os.replace(temp, skill)
    read = name_line(skill)
    ok = owned_dir(new) and not os.path.lexists(old) and (read == clash['rename_to'] if had else read is None)
    return dict(clash, result='moved' if ok else 'unchecked',
                name_line=('name: %s' % read) if had else 'none (it has no SKILL.md)')


def main(argv):
    parser = argparse.ArgumentParser(prog='skill_clash.py')
    parser.add_argument('command', choices=['list', 'rename'])
    parser.add_argument('--build', required=True)
    parser.add_argument('--root')
    parser.add_argument('--yes', action='store_true')
    parser.add_argument('--operation')
    args = parser.parse_args(argv)
    try:
        clashes, blocked = plan(args.build, args.root)
    except (Refused, OSError) as refusal:
        print('refused: %s' % refusal, file=sys.stderr)
        return 5
    ready = bool(clashes) and not blocked
    if args.command == 'list':
        print(json.dumps({'clashes': clashes, 'blocked': blocked, 'question': question(clashes) if ready else None,
                          'operation': operation(clashes) if ready else None}, indent=1))
        return 0
    if not args.yes or not args.operation:
        print('refused: rename needs --yes and the --operation `list` printed; nothing moved', file=sys.stderr)
        return 2
    if not ready or args.operation != operation(clashes):
        why = '; '.join(b['why'].rstrip('.') for b in blocked) or 'the folders changed since `list` (run it again and ask again)'
        print('refused: %s; nothing moved' % why, file=sys.stderr)
        return 5
    results = [rename(c) for c in clashes]
    print(json.dumps({'renamed': results}, indent=1))
    return 0 if all(r['result'] == 'moved' for r in results) else 6


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
