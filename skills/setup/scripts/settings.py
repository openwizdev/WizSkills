#!/usr/bin/env python3
"""Read back a project's fleet settings (#1183). Standard library only.

  settings.py check [--root DIR] [--labels FILE]

Reads the four files in DIR/docs/agents/ (default: the current folder) and
names each missing or unsafe setting: a missing file or section, a builder or
reviewer table without its three flags, a template placeholder, a reviewer from the builder's model family, no Record authors
row, or a triage role without exactly one label. FILE is the saved output of
`gh label list --limit 500 --json name`; with it, each mapped label must exist
in the tracker exactly once. It writes nothing and runs nothing.

Exits: 0 verified; 2 usage; 5 refused, each problem on its own line.
"""
import json
import os
from pathlib import Path
import re
import stat
import sys

FILES = ('issue-tracker.md', 'triage-labels.md', 'domain.md', 'fleet.md')
TABLES = ('Builder', 'Builder for small tickets', 'Reviewer for Claude-built', 'Reviewer for GPT-built')
SECTIONS = TABLES + ('Test commands', 'CI checks', 'Standing merge rules', 'GitHub identity')
FLAGS = ('provider', 'model', 'reasoning-level')
FAMILY = {'claude-code': 'claude', 'codex': 'gpt'}
REVIEWS = {'Reviewer for Claude-built': 'claude', 'Reviewer for GPT-built': 'gpt'}
ROLES = ('needs-triage', 'needs-info', 'ready-for-agent', 'ready-for-human', 'wontfix')
LOGIN = r'[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\[bot\])?'
USAGE = 'usage: settings.py check [--root DIR] [--labels FILE]'


def read(path, problems):
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        problems.append('%s: missing' % path.name)
        return None
    if not stat.S_ISREG(info.st_mode):
        problems.append('%s: not a regular file' % path.name)
        return None
    try:
        return path.read_text(encoding='utf-8')
    except (OSError, UnicodeError):
        problems.append('%s: unreadable' % path.name)
        return None


def sections(text):
    found = {}
    for part in re.split(r'^## ', text, flags=re.M)[1:]:
        title, _, body = part.partition('\n')
        found.setdefault(title.strip(), body)
    return found


def fleet(text, problems):
    found = sections(text)
    for title in SECTIONS:
        if title not in found:
            problems.append('fleet.md: no ## %s section' % title)
    for title in TABLES:
        body = found.get(title)
        if body is None:
            continue
        values = {}
        for flag in FLAGS:
            match = re.search(r'`--%s ([^`]+)`' % flag, body)
            if not match:
                problems.append('fleet.md: %s: no --%s' % (title, flag))
            elif re.search(r'<[^>]*>', match[1]):
                problems.append('fleet.md: %s: unfilled %s' % (title, match[1]))
            else:
                values[flag] = match[1]
        provider = values.get('provider')
        if title in REVIEWS and provider:
            if provider not in FAMILY:
                problems.append('fleet.md: %s: %s has no known model family' % (title, provider))
            elif FAMILY[provider] == REVIEWS[title]:
                problems.append('fleet.md: %s: %s is not from another model family' % (title, provider))
    identity = found.get('GitHub identity')
    if identity is not None:
        row = re.search(r'^\| Record authors \|([^|\n]*)\|', identity, re.M)
        logins = re.findall(r'`([^`]*)`', row[1]) if row else []
        if not row:
            problems.append('fleet.md: GitHub identity: no Record authors row')
        elif not logins or not all(re.fullmatch(LOGIN, login) for login in logins):
            problems.append('fleet.md: GitHub identity: Record authors needs one or more exact logins')


def triage(text, labels, problems):
    rows = re.findall(r'^\| `([^`]+)` \| `([^`]+)` \|', text, re.M)
    for role in ROLES:
        mapped = [label for name, label in rows if name == role]
        if len(mapped) != 1:
            problems.append('triage-labels.md: %s: mapped %d times' % (role, len(mapped)))
        elif re.search(r'<[^>]*>', mapped[0]):
            problems.append('triage-labels.md: %s: unfilled %s' % (role, mapped[0]))
        elif labels is not None and labels.count(mapped[0]) != 1:
            count = labels.count(mapped[0])
            problems.append('triage-labels.md: %s: label %s %s' % (
                role, mapped[0], 'is not in the tracker' if not count else 'is in the tracker %d times' % count))


def main(argv):
    if not argv or argv[0] != 'check':
        print(USAGE)
        return 2
    got, rest = {}, argv[1:]
    while rest:
        name = rest.pop(0)
        if name not in ('--root', '--labels') or name in got or not rest:
            print(USAGE)
            return 2
        got[name] = rest.pop(0)
    labels = None
    if '--labels' in got:
        try:
            labels = [item['name'] for item in json.loads(Path(got['--labels']).read_text(encoding='utf-8'))]
        except (OSError, ValueError, TypeError, KeyError):
            print('The saved label list is unreadable; run gh label list --limit 500 --json name again.')
            return 2
    folder = Path(got.get('--root', '.')) / 'docs/agents'
    problems = []
    texts = {name: read(folder / name, problems) for name in FILES}
    if texts['fleet.md'] is not None:
        fleet(texts['fleet.md'], problems)
    if texts['triage-labels.md'] is not None:
        triage(texts['triage-labels.md'], labels, problems)
    for line in problems:
        print(line)
    if problems:
        print('Settings: refused (%d problems).' % len(problems))
        return 5
    print('Settings: verified (4 files).')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
