#!/usr/bin/env python3
"""Read back a project's fleet settings (#1183). Standard library only.

  settings.py check [--root DIR] [--labels FILE]

Reads the four files in DIR/docs/agents/ (default: the current folder) and
names each missing or unsafe setting: a missing file or section, a builder or
reviewer table or Fixer family row without each of its three flags exactly
once as one token, a template placeholder, a reviewer from the builder's model family, a
`## Models` table outside the models contract's form (openwiz.models.v1, #1807), not exactly
one valid Record authors row, or a triage role without exactly one label. FILE is the saved output of
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
# The whole Record authors cell, as the review and launch-fleet readers take it.
LOGIN = r'`[A-Za-z0-9](?:-?[A-Za-z0-9])*(?:\[bot\])?`'
CELL = re.compile(r'\s*%s(?:\s*,\s*%s)*\s*' % (LOGIN, LOGIN))
# The models contract's table (openwiz.models.v1): its header, rows and one ids rule.
MODELS_HEADER = ['Role', 'Harness', 'Model', 'Effort', '`room-cli thread spawn` flags']
MODEL_ROWS = ('Orchestrator', 'Builder', 'Reviewer', 'Small builder', 'Fixer')
ID = r'[A-Za-z0-9._-]+'
FLAGS_CELL = re.compile(r'`--provider (%s) --model (%s(?:/%s)*) --reasoning-level (%s)`' % (ID, ID, ID, ID))
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


def sections(text, exact=False):
    """Each heading's body; a repeated heading adds to it, as the fleet's readers read it.

    Launch strips the title; review (exact) strips only the whole line, so
    `##  GitHub identity` is not its section.
    """
    found = {}
    for part in re.split(r'^## ', text, flags=re.M)[1:]:
        title, _, body = part.partition('\n')
        title = title.rstrip() if exact else title.strip()
        found[title] = found.get(title, '') + body
    return found


def cells(line):
    return [cell.strip() for cell in line.strip()[1:-1].split('|')] if line.strip().endswith('|') else None


def models(text):
    """The `## Models` table as {role: (provider, model, effort), or None when it follows}; None without one.

    Raises ValueError whose one argument lists each break of the models
    contract: the first structural one, or every row's. The table is the
    section's first table.
    """
    lines = text.split('\n')
    headings = [n for n, line in enumerate(lines) if line.startswith('## ') and line[3:].strip() == 'Models']
    if not headings:
        return None
    if len(headings) > 1:
        raise ValueError(['more than one ## Models heading'])
    rows = []
    for line in lines[headings[0] + 1:]:
        if line.startswith('## '):
            break
        if line.startswith('|'):
            rows.append(line)
        elif rows:
            break
    if len(rows) < 2 or cells(rows[0]) != MODELS_HEADER or cells(rows[1]) != ['---'] * 5:
        raise ValueError(["the header is not the contract's"])
    body = [cells(row) for row in rows[2:]]
    names = [row[0] if row and len(row) == 5 else None for row in body]
    if names[:3] != list(MODEL_ROWS[:3]) or names[3:] not in ([], ['Small builder'], ['Fixer'],
                                                             ['Small builder', 'Fixer']):
        raise ValueError(['rows not Orchestrator, Builder, Reviewer, then optional Small builder, Fixer'])
    found, broken = {}, []
    for role, harness, model, effort, flags in body:
        match = FLAGS_CELL.fullmatch(flags)
        if harness == 'follows Builder':
            found[role] = None
            if role not in MODEL_ROWS[3:]:
                broken.append('%s: only Small builder and Fixer may follow' % role)
            elif model or effort or flags:
                broken.append('%s: a following row has empty Model, Effort and flags' % role)
        elif re.search(r'<[^>]*>', ''.join((harness, model, effort, flags))):
            broken.append('%s: unfilled' % role)
        elif not (harness and model and effort):
            broken.append('%s: Harness, Model and Effort need names' % role)
        elif not match:
            broken.append('%s: the flags are not one exact `--provider --model --reasoning-level`' % role)
        else:
            found[role] = match.groups()
    if broken:
        raise ValueError(broken)
    return found


def token(flag):
    return r'(?<![\w-])--%s(?![\w-])' % flag


def fixer(body, problems):
    """Each Fixer family row carries each flag exactly once, as `--flag value`."""
    rows = [line for line in body.splitlines() if line.startswith('|')
            and not re.fullmatch(r'\|[\s|:-]*', line)][1:]
    for row in rows:
        family = row.split('|')[1].strip()
        for flag in FLAGS:
            found = list(re.finditer(token(flag), row))
            if not found:
                problems.append('fleet.md: Fixer: %s: no --%s' % (family, flag))
            elif len(found) > 1:
                problems.append('fleet.md: Fixer: %s: --%s appears %d times' % (family, flag, len(found)))
            elif not re.match(r' (?!--)[^\s`|]+(?=[ `|])', row[found[0].end():]):
                problems.append('fleet.md: Fixer: %s: malformed --%s' % (family, flag))


def fleet(text, problems):
    found, exact = sections(text), sections(text, exact=True)
    try:
        table = models(text)
    except ValueError as error:
        problems.extend('fleet.md: Models: %s' % line for line in error.args[0])
        table = False  # refused: never read past it to the older tables
    if table:
        builder, reviewer = table['Builder'][0], table['Reviewer'][0]
        if reviewer not in FAMILY:
            problems.append('fleet.md: Models: Reviewer: %s has no known model family' % reviewer)
        elif FAMILY[reviewer] == FAMILY.get(builder):
            problems.append('fleet.md: Models: Reviewer: %s is not from another model family than the Builder'
                            % reviewer)
    for title in SECTIONS if table is None else SECTIONS[len(TABLES):]:
        if title not in (exact if title == 'GitHub identity' else found):
            problems.append('fleet.md: no ## %s section' % title)
    for title in TABLES:
        body = found.get(title)
        if body is None:
            continue
        values = {}
        for flag in FLAGS:
            # Launch takes each flag exactly once, as one backticked `--flag value`:
            # count every backticked mention first, whatever follows it.
            spans = [span for span in re.findall(r'`([^`]*)`', body) for _ in re.finditer(token(flag), span)]
            if not spans:
                problems.append('fleet.md: %s: no --%s' % (title, flag))
            elif len(spans) > 1:
                problems.append('fleet.md: %s: --%s appears %d times' % (title, flag, len(spans)))
            elif re.search(r'<[^>]*>', spans[0]):
                problems.append('fleet.md: %s: unfilled %s' % (title, spans[0].partition(' ')[2]))
            elif not re.fullmatch(r'--%s [^\s`]+' % flag, spans[0]):
                problems.append('fleet.md: %s: malformed `%s`' % (title, spans[0]))
            else:
                values[flag] = spans[0].partition(' ')[2]
        provider = values.get('provider')
        if title in REVIEWS and provider:
            if provider not in FAMILY:
                problems.append('fleet.md: %s: %s has no known model family' % (title, provider))
            elif FAMILY[provider] == REVIEWS[title]:
                problems.append('fleet.md: %s: %s is not from another model family' % (title, provider))
    if 'Fixer' in found:
        fixer(found['Fixer'], problems)
    identity = exact.get('GitHub identity')
    if identity is not None:
        rows = re.findall(r'^\| *Record authors *\|.*$', identity, re.M)
        cells = rows[0].split('|') if len(rows) == 1 else []
        if not rows:
            problems.append('fleet.md: GitHub identity: no Record authors row')
        elif len(rows) > 1:
            for number, row in enumerate(rows[1:], 2):
                problems.append('fleet.md: GitHub identity: Record authors row %d of %d: %s'
                                % (number, len(rows), row.strip()))
        elif len(cells) != 4 or cells[3].strip() or not CELL.fullmatch(cells[2]):
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
