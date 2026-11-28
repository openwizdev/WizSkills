#!/usr/bin/env python3
import argparse
import re
import sys

ABOUT = ('The completion check a builder runs before handing back. It prints one line per gap and '
         'exits 1 on any, `complete: ok` and exit 0 on none, exit 2 on an unreadable input. '
         'Owned paths stay with `ticket.py scope`.')
BOX = re.compile(r'\s*[-*]\s+\[[ xX]\]\s+(.+)')
FENCE = re.compile(r'\s*(```|~~~)')
RANGE_SEPARATOR = r'(?:[-–]|\s*to\s*)'
NUMBERED = re.compile(rf'(?i)\b(?:criteri(?:on|a)|acs?)[ \t]*#?'
                      rf'(\d+(?:(?:{RANGE_SEPARATOR}|(?:\s*(?:,|&|and)\s*)+)#?\d+)*)')
SPAN = re.compile(rf'(?i)(\d+){RANGE_SEPARATOR}#?(\d+)')
BEFORE = re.compile(r'(?i)[\s#>*_-]*before\b')
AFTER = re.compile(r'(?i)[\s#>*_-]*after\b')
INLINE_AFTER = re.compile(r'(?i)\bafter[ \t*_]*:')
FAILURE = re.compile(r'(?i)\b(?:fail(?:ed|ure|ures|ing|s)?|red|assertionerror|errors?)\b')
PROVED = re.compile(r'"base_runs":\s*\[\s*"failed"(?:\s*,\s*"failed")*\s*\]')
CLOSES = re.compile(r'(?im)^\s*closes\s+(?:[\w.-]+/[\w.-]+)?#(\d+)\b')


class Unreadable(Exception):
    pass


def read(path, what):
    try:
        with open(path, encoding='utf-8') as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError) as error:
        raise Unreadable(f'{what}: {error}')


def section(text, heading):
    lines, inside, fence = [], False, None
    for line in text.splitlines():
        mark = FENCE.match(line)
        if mark and fence in (None, mark.group(1)):
            fence = None if fence else mark.group(1)
        elif fence is None and line.startswith('## '):
            inside = line[3:].strip().lower() == heading
            continue
        if inside:
            lines.append(line)
    return lines


def words(text):
    return ' '.join(re.sub(r'[`*_]', '', text).lower().split())


def named_numbers(line):
    out = set()
    for match in NUMBERED.finditer(line):
        run = match.group(1)
        out.update(int(n) for n in re.findall(r'\d+', run))
        for low, high in SPAN.findall(run):
            if int(high) - int(low) < 1000:
                out.update(range(int(low), int(high) + 1))
    return out


def red_first(evidence):
    in_before = False
    for line in evidence:
        if AFTER.match(line):
            in_before = False
            continue
        in_before = in_before or bool(BEFORE.match(line))
        if in_before:
            after = INLINE_AFTER.search(line)
            if after:
                line = line[:after.start()]
            if FAILURE.search(line):
                return True
            if after:
                in_before = False
        if PROVED.search(line):
            return True
    return False


def gaps(ticket, description, paths):
    criteria = [m.group(1).strip() for m in map(BOX.fullmatch, section(ticket, 'acceptance criteria')) if m]
    if not criteria:
        raise Unreadable('the ticket has no `## Acceptance criteria` boxes')
    evidence = section(description, 'evidence')
    lines = [line for line in evidence + section(description, 'self-check') if line.strip()]
    numbers = set().union(*map(named_numbers, lines)) if lines else set()
    texts = [words(line) for line in lines]
    out = [f'criterion without evidence: {criterion}' for n, criterion in enumerate(criteria, 1)
           if n not in numbers and not any(words(criterion) in text for text in texts)]
    if not red_first(evidence):
        out.append('no red-first evidence')
    closes = CLOSES.search(description)
    note = re.compile(rf'(?:\./)?changes/{closes.group(1) if closes else "[0-9]+"}\.md')
    if not any(note.fullmatch(path.strip()) for path in paths.splitlines()) and 'no-changelog' not in description:
        out.append('no changelog line')
    return out


def main(argv):
    parser = argparse.ArgumentParser(prog='complete.py', description=ABOUT)
    parser.add_argument('--ticket', required=True, help='a file holding the ticket body')
    parser.add_argument('--description', required=True, help='a file holding the pull request description')
    parser.add_argument('--diff', required=True, help='a file listing the changed paths, one per line')
    args = parser.parse_args(argv)
    try:
        ticket = read(args.ticket, 'ticket')
        found = gaps(ticket, read(args.description, 'description'), read(args.diff, 'changed paths'))
    except Unreadable as error:
        print(f'complete: unreadable: {error}', file=sys.stderr)
        return 2
    for line in found:
        print(line)
    if 'no red-first evidence' in found:
        proof = ' '.join(' '.join(section(ticket, 'proof')).split())
        if proof:
            print(f'proof: {proof}', file=sys.stderr)
    if not found:
        print('complete: ok')
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
