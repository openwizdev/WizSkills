#!/usr/bin/env python3
"""Read back a project's fleet settings (#1183). Standard library only.

  settings.py check [--root DIR] [--labels FILE]
  settings.py app-identity < contents.json

Reads the four files in DIR/docs/agents/ (default: the current folder) and
names each missing or unsafe setting: a missing file or section, a builder or
reviewer table or Fixer family row without each of its three flags exactly
once as one token, a template placeholder, a reviewer from the builder's model family, not exactly
one valid Record authors row, or a triage role without exactly one label. FILE is the saved output of
`gh label list --limit 500 --json name`; with it, each mapped label must exist
in the tracker exactly once. It writes nothing and runs nothing.

app-identity reads GitHub's Contents API answer for docs/agents/fleet.md on
stdin and exits 0 only when its App identity is on: one bare `on` row in the
one canonical `## GitHub identity` table. check refuses what it refuses.

Exits: 0 verified; 2 usage; 5 refused, each problem on its own line.
"""
import base64
import html
import json
import os
from pathlib import Path
import re
import stat
import sys
import unicodedata

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
MODELS_HEADER = ['Role', 'Harness', 'Model', 'Effort', '`room-cli thread spawn` flags']
MODEL_ROWS = ('Orchestrator', 'Builder', 'Reviewer', 'Small builder', 'Fixer')
ID = r'[A-Za-z0-9._-]+'
FLAGS_CELL = re.compile(r'`--provider (%s) --model (%s(?:/%s)*) --reasoning-level (%s)`' % (ID, ID, ID, ID))
ROSTER_HEADER = ['Name', 'Kind', 'Driver', 'Roles', 'Writes as']
KINDS = ('harness', 'host', 'bot')
ROSTER_ROLES = ('orchestrator', 'builder', 'reviewer', 'helper')
USAGE = 'usage: settings.py check [--root DIR] [--labels FILE] | settings.py app-identity < contents.json'


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


def word(text, most, chars, sep):
    return (0 < len(text) <= most and all(c in chars or c == sep for c in text)
            and text[0] != sep and text[-1] != sep and sep * 2 not in text)


ALNUM = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'


def roster(text):
    lines = [line.rstrip() for line in text.split('\n')]

    def is_roster(word):
        return word.isascii() and word.lower() == 'roster'

    def names_roster(line):
        line = line.strip()
        level = len(line) - len(line.lstrip('#'))
        rest = line[level:]
        return (1 <= level <= 6 and (not rest or rest[0] in ' \t')
                and is_roster(rest.strip().rstrip('#').strip()))

    def underlined(n):
        below = lines[n + 1].strip() if n + 1 < len(lines) else ''
        return is_roster(lines[n].strip()) and below != '' and set(below) in ({'='}, {'-'})

    for n, line in enumerate(lines):
        if (line != '## Roster' and names_roster(line)) or underlined(n):
            raise ValueError('Roster refused: the Roster heading must be exactly ## Roster: %s' % line)
    at = [n for n, line in enumerate(lines) if line == '## Roster']
    if len(at) > 1:
        raise ValueError('Roster refused: more than one ## Roster heading')
    if not at:
        return None
    section = []
    for line in lines[at[0] + 1:]:
        if line.startswith(('# ', '## ')):
            break
        section.append(line)
    first = next((n for n, line in enumerate(section) if line.lstrip().startswith('|')), None)
    if first is None:
        raise ValueError('Roster refused: the Roster section has no table')
    table = []
    for line in section[first:]:
        if not line.lstrip().startswith('|'):
            break
        table.append(line)
    rule = cells(table[1]) if len(table) > 1 else None
    if cells(table[0]) != ROSTER_HEADER or not rule or len(rule) != 5 or not all(
            len(cell) >= 3 and set(cell) == {'-'} for cell in rule):
        raise ValueError('Roster refused: the header is not Name, Kind, Driver, Roles, Writes as')
    if len(table) == 2:
        raise ValueError('Roster refused: the table has no entries')
    entries, person = [], None
    for n, line in enumerate(table[2:], 1):
        row = cells(line) or []
        if len(row) != 5:
            raise ValueError('Roster refused: row %d has %d cells, not 5' % (n, len(row)))
        name, kind, driver, roles, writes = row
        if not (word(name, 40, ALNUM + '._-', ' ') and name[0] in ALNUM and name[-1] in ALNUM):
            raise ValueError('Roster refused: row %d: bad name: %s' % (n, name))
        if any(entry[0].lower() == name.lower() for entry in entries):
            raise ValueError('Roster refused: row %d: %s is already an entry' % (n, name))
        here = 'Roster refused: row %d (%s)' % (n, name)
        if kind not in KINDS:
            raise ValueError('%s: unknown kind: %s' % (here, kind))
        if not word(driver, 40, ALNUM[:26] + ALNUM[52:], '-'):
            raise ValueError('%s: bad driver: %s' % (here, driver))
        if not roles:
            raise ValueError('%s: no roles' % here)
        taken = []
        for role in (part.strip() for part in roles.split(',')):
            if role not in ROSTER_ROLES:
                raise ValueError('%s: unknown role: %s' % (here, role))
            if role in taken:
                raise ValueError('%s: role listed twice: %s' % (here, role))
            taken.append(role)
        login = writes[:-len("'s App")] if writes.endswith("'s App") else ''
        if not word(login, 39, ALNUM, '-'):
            raise ValueError("%s: writes as %s, not <person>'s App" % (here, writes))
        if person is not None and login != person:
            raise ValueError("%s: writes as %s, not %s's App like row 1" % (here, writes, person))
        person = login
        label = '%s via %s' % (name, login)
        if len(label) > 60:
            raise ValueError('%s: %s is longer than 60 characters' % (here, label))
        entries.append((name, kind, driver, taken, label))
    return entries


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
        table = False
    try:
        roster(text)
    except ValueError as error:
        problems.append('fleet.md: %s' % error.args[0])
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
    approval(text, problems)
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
    state, reasons = app_identity(text)
    if state == 'refused':
        problems.extend('fleet.md: GitHub identity: ' + reason for reason in reasons)


APP_KEYS = ('Record authors', 'App identity')
FENCE_LIKE = re.compile(r'[ \t>]*(?:(?:[-*+]|[0-9]+[.)])[ \t]+)?(`{3,}|~{3,})')
SWALLOWS = re.compile(r'[ \t]{0,3}<(?:(?:pre|script|style|textarea)(?:[\s>]|$)|\?|![A-Za-z]|!\[CDATA\[)', re.I)
HEADING = re.compile(r'[ \t>]*#{1,6}(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*')
CANONICAL_ROW = re.compile(r'\|([^|\\]*)\|([^|\\]*)\|')


def plain(cell):
    cell = re.sub(r'<[^>]*>', '', html.unescape(cell))
    cell = ''.join(c for c in cell if unicodedata.category(c) not in ('Cf', 'Cc') or c in ' \t')
    cell = re.sub(r'\\(?=[!-/:-@\[-`{-~])', '', cell)
    return ' '.join(re.sub(r'[`*_~]', '', cell).split()).casefold()


def split_cells(line):
    line = re.sub(r'^(?:[ \t>]|<!--|(?:[-*+]|[0-9]+[.)])[ \t])*', '', line)
    if not line.startswith('|') and '|' not in re.sub(r'(`+)(?:(?!\1).)+?\1', '', line):
        return None
    cells = re.split(r'(?<!\\)\|', line)
    if len(cells) < 2:
        return None
    return cells[1:] if line.startswith('|') else cells


def app_rows(lines):
    rows = []
    for number, line in enumerate(lines):
        cells = split_cells(line)
        if cells and plain(cells[0]) == 'app identity':
            rows.append(number)
    return rows


def hidden_heading(lines, at):
    fence, comment = None, False
    for line in lines[:at]:
        mark = FENCE_LIKE.match(line)
        if fence:
            if line == fence:
                fence = None
            elif mark:
                return 'a fence-like line inside a fence: ' + line
            continue
        if mark and not comment:
            opener = re.fullmatch(r'(`{3,})[^`]*|(~{3,}).*', line)
            if not opener:
                return 'a fence that does not open at column 0: ' + line
            fence = opener.group(1) or opener.group(2)
            continue
        if not comment and SWALLOWS.match(line):
            return 'raw HTML that can run past the heading: ' + line
        rest = line
        while rest:
            mark = rest.find('-->' if comment else '<!--')
            if mark < 0:
                break
            comment, rest = not comment, rest[mark + (3 if comment else 4):]
    if fence:
        return 'a fence still open: ' + fence
    if comment:
        return 'an HTML comment still open'
    return None


def canonical(lines, row):
    at = [n for n, line in enumerate(lines) if line == '## GitHub identity']
    named = [n for n, line in enumerate(lines)
             if (HEADING.fullmatch(line) and plain(HEADING.fullmatch(line).group(1) or '') == 'github identity')
             or (plain(line) == 'github identity' and n + 1 < len(lines)
                 and re.fullmatch(r'[ \t]{0,3}(=+|-+)[ \t]*', lines[n + 1]))]
    if len(at) != 1 or named != at:
        return 'the heading is not one exact ## GitHub identity'
    at = at[0]
    if at and lines[at - 1]:
        return 'no blank line before ## GitHub identity'
    why = hidden_heading(lines, at)
    if why:
        return why
    if lines[at + 1:at + 4] != ['', '| Setting | Value |', '| --- | --- |']:
        return 'the table under ## GitHub identity is not | Setting | Value | then | --- | --- |'
    keys, number = [], at + 4
    while number < len(lines) and lines[number]:
        match = CANONICAL_ROW.fullmatch(lines[number])
        key = match.group(1).strip() if match else None
        if key not in APP_KEYS or key in keys:
            return 'a table line that is not one | Record authors | or | App identity | row: ' + lines[number]
        keys.append(key)
        number += 1
    return None if at + 4 <= row < number else 'the App identity row is not in the ## GitHub identity table'


def app_identity(raw):
    try:
        text = raw.decode('utf-8') if isinstance(raw, bytes) else raw
    except UnicodeDecodeError:
        return 'refused', ['fleet.md is not UTF-8']
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    rows = app_rows(lines)
    if not rows:
        return 'off', ['no App identity row']
    if len(rows) > 1:
        return 'refused', ['App identity row %d of %d: %s' % (n, len(rows), lines[row].strip())
                           for n, row in enumerate(rows[1:], 2)]
    line = lines[rows[0]]
    cells = split_cells(line)
    value = cells[1].strip() if len(cells) == 3 and not cells[2].strip() and '\\|' not in line else None
    if value in ('off', '`off`', '`on`'):
        return 'off', ['the App identity row is ' + value]
    if value != 'on':
        return 'refused', ['App identity must be exactly on or off: ' + line.strip()]
    why = canonical(lines, rows[0])
    if why:
        return 'refused', ['App identity on is refused: ' + why]
    return 'on', ['one App identity on row in the ## GitHub identity table']


def app_identity_on(text):
    return app_identity(text)[0] == 'on'


def contents(stdin):
    try:
        answer = json.loads(stdin.decode('utf-8'))
        content, size = answer['content'], answer['size']
        if (not isinstance(answer, dict) or answer['type'] != 'file' or answer['encoding'] != 'base64'
                or not isinstance(content, str) or type(size) is not int):
            return None
        lines = content.split('\n')
        if lines[-1] == '':
            lines.pop()
        if any(len(line) != 60 for line in lines[:-1]) or (lines and not 0 < len(lines[-1]) <= 60):
            return None
        data = base64.b64decode(''.join(lines).encode('ascii'), validate=True)
    except (ValueError, TypeError, KeyError, UnicodeError):
        return None
    return data if len(data) == size else None


def approval(text, problems):
    lines = text.split('\n')
    at = [n for n, line in enumerate(lines) if line.startswith('## ') and line[3:].strip() == 'Approval rules']
    here = 'fleet.md: Approval rules: '
    for n, line in enumerate(lines):
        atx = re.fullmatch(r'\s*#{1,6}(?:\s+(.*?))?(?:\s+#+)?\s*', line)
        below = lines[n + 1].strip() if n + 1 < len(lines) else ''
        title = (atx.group(1) or '') if atx else (line if below and set(below) in ({'='}, {'-'}) else '')
        if line != '## Approval rules' and ' '.join(title.split()).lower() == 'approval rules':
            problems.append(here + 'the heading must be exactly ## Approval rules: ' + line)
    if len(at) > 1:
        problems.append(here + 'more than one ## Approval rules heading')
    if len(at) != 1:
        return
    table, fence = [], None
    for line in lines[at[0] + 1:]:
        mark = re.match(r' {0,3}(`{3,}|~{3,})(.*)', line)
        if line.startswith(('# ', '## ')):
            break
        if fence:
            if mark and mark.group(1)[0] == fence[0] and len(mark.group(1)) >= len(fence) and not mark.group(2).strip():
                fence = None
        elif re.match(r' {0,3}\|', line):
            table.append(cells(line))
        elif table and line.lstrip().startswith('|'):
            problems.append(here + 'a row indented as code ends the table: ' + line.strip())
            break
        elif table:
            break
        elif mark:
            fence = mark.group(1)
    if len(table) < 3 or table[0] != ['Rule', 'Approver'] or table[1] != ['---', '---']:
        problems.append(here + 'the table is not | Rule | Approver |')
        return
    seen = []
    for n, row in enumerate(table[2:], 1):
        if not row or len(row) != 2:
            problems.append(here + 'row %d: not two cells' % n)
            continue
        rule, approver = row[0], ' '.join(row[1].strip('`*_ .').split())
        name, key = 'row %d (%s): ' % (n, rule), ' '.join(rule.lower().split())
        if not rule.startswith('Ask before '):
            problems.append(here + name + 'the rule does not start "Ask before"')
        elif key in seen:
            problems.append(here + name + 'repeats row %d' % (seen.index(key) + 1))
        elif not approver:
            problems.append(here + name + 'no approver')
        elif re.search(r'<[^>]*>', approver):
            problems.append(here + name + 'unfilled approver ' + row[1])
        elif approver.lower() == 'the user':
            problems.append(here + name + 'the approver is "the user", not a person')
        seen.append(key)


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
    if argv[:1] == ['app-identity']:
        if len(argv) != 1:
            print(USAGE)
            return 2
        data = contents(sys.stdin.buffer.read())
        state, reasons = app_identity(data) if data is not None else ('refused', ['not one whole Contents API file'])
        print('App identity: %s: %s' % (state, '; '.join(reasons)))
        return 0 if state == 'on' else 1
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
