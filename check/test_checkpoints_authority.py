import json
import re
import statistics
import sys
import time
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / 'contracts' / 'checkpoints.v1.md'
EXPECTED = (
    'Authority: Jake, 2026-11-20: planning writes two checkpoint answers, '
    'one-way door and user-visible; an early say covers a one-way door, a late '
    'look at a preview, screenshots or a short video covers what users see and '
    'every release, answering no to both leaves the spec to the agents\' checks, '
    'and no section means early only ([private record](https://github.com/jparker2006/'
    'ClosedWiz/issues/3065#issuecomment-7035053757)). It relies on the '
    '[open development contract](open-development.v1.md) for the decider, the '
    'pointer and the public record forms.'
)
COPY = (
    'This file is the copy the skill readers use, for RC2 and RC3. The Authority '
    'line is the public decision source. A rule stated in this copy and in '
    'OpenWiz\'s `contracts/checkpoints.v1.md` has to be edited in both.'
)
POINTER = 'https://github.com/jparker2006/ClosedWiz/issues/9004#issuecomment-9000000005'
AUTHORITY = re.compile(
    r'^Authority: (?P<decider>[A-Z][A-Za-z-]*), (?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2}): '
    r'(?P<decision>\S(?:.*\S)?) \(\[private record\]\((?P<pointer>[^)\s]+)\)\)\.(?P<rest>.*)\Z'
)
POINTER_FORM = re.compile(
    r'https://github\.com/jparker2006/ClosedWiz/(?:issues|pull)/[1-9][0-9]*#issuecomment-[1-9][0-9]*'
)
QUOTES = ('"', '\u201c', '\u201d')


def fence_mark(line):
    body = line.lstrip(' ')
    if len(line) - len(body) > 3:
        return None
    char = body[:1]
    if char not in ('`', '~'):
        return None
    length = len(body) - len(body.lstrip(char))
    if length < 3:
        return None
    rest = body[length:]
    if char == '`' and '`' in rest:
        return None
    return char, length, rest


def unfenced_lines(text):
    lines, open_mark = [], None
    for line in text.splitlines():
        mark = fence_mark(line)
        if open_mark is None:
            if mark is None:
                lines.append(line)
            else:
                open_mark = mark
            continue
        if (mark is not None and mark[0] == open_mark[0] and mark[1] >= open_mark[1]
                and mark[2].strip(' \t') == ''):
            open_mark = None
    return lines


def authority_lines(text):
    return [line for line in unfenced_lines(text) if line.startswith('Authority:')]


def real_date(value):
    year, month, day = (int(part) for part in value.split('-'))
    try:
        return date(year, month, day).isoformat() == value
    except ValueError:
        return False


def form_errors(line):
    found = AUTHORITY.fullmatch(line)
    if found is None:
        return ['source-form']
    errors = []
    if not real_date(found['date']):
        errors.append('date')
    if any(mark in found['decision'] for mark in QUOTES):
        errors.append('quoted-words')
    if POINTER_FORM.fullmatch(found['pointer']) is None:
        errors.append('pointer')
    return errors


def evaluate(text):
    lines = authority_lines(text)
    if len(lines) != 1:
        errors = ['authority-count']
    else:
        errors = form_errors(lines[0])
    marker = '\n## WizSkills copy\n'
    if marker not in text:
        return errors + ['copy-section']
    body = text.split(marker, 1)[1].strip()
    if 'byte-identical' in body:
        errors.append('byte-identical')
    if body != COPY:
        errors.append('copy-wording')
    return errors


def source_line(decision='every Codex thread runs in fast mode', when='2030-01-04',
                decider='Robin', pointer=POINTER):
    return (f'Authority: {decider}, {when}: {decision} '
            f'([private record]({pointer})).')


def document(authority, copy=COPY):
    return f'{authority}\n\n## WizSkills copy\n\n{copy}\n'


GRILL = (
    'Authority: spec #1828 and its confirmed grill, J239 R1 to R3, a private record. '
    'It relies on the open development contract for the decider, the pointer and the public record forms.'
)
OLD_COPY = (
    'WizSkills carries this file byte-identical at `contracts/checkpoints.v1.md`, '
    'for RC2 and RC3. Any change here changes both, in the same version.'
)
CASES = (
    ('public source form', document(source_line()), []),
    ('grill citation', document(GRILL), ['source-form']),
    ('day that is not in the month', document(source_line(when='2030-02-29')), ['date']),
    ('quoted decision', document(source_line(decision='the owner said \u201cmake them fast\u201d')),
     ['quoted-words']),
    ('pointer into the public repository', document(source_line(
        pointer='https://github.com/openwizdev/OpenWiz/issues/4001#issuecomment-4000000001')),
     ['pointer']),
    ('comment id with a leading zero', document(source_line(
        pointer='https://github.com/jparker2006/ClosedWiz/issues/9004#issuecomment-09000000005')),
     ['pointer']),
    ('two authority lines', document(source_line() + '\n' + source_line(decider='Jake')),
     ['authority-count']),
    ('byte-identical copy note', document(source_line(), OLD_COPY),
     ['byte-identical', 'copy-wording']),
    ('copy note that drops the both-copies rule',
     document(source_line(), 'This file is the copy the skill readers use.'), ['copy-wording']),
    ('fenced grill citation', '~~~\n' + GRILL + '\n~~~\n' + document(source_line()), []),
)


def contract_text():
    return CONTRACT.read_text(encoding='utf-8')


def bench(iterations=2000, repeats=7):
    text = contract_text()

    def median(fn):
        samples = []
        for _ in range(repeats):
            started = time.perf_counter()
            for _step in range(iterations):
                fn()
            samples.append((time.perf_counter() - started) * 1e6 / iterations)
        return round(statistics.median(samples), 3)

    failed = [name for name, sample, errors in CASES if evaluate(sample) != errors]
    return {
        'iterations': iterations,
        'repeats': repeats,
        'equality_us_median': median(lambda: authority_lines(text) == [EXPECTED]),
        'evaluate_us_median': median(lambda: evaluate(text)),
        'eval_cases': len(CASES),
        'eval_failed': failed,
        'contract_errors': evaluate(text),
    }


class CheckpointsAuthority(unittest.TestCase):
    def test_authority_line_is_the_public_source_form(self):
        text = contract_text()
        self.assertEqual(authority_lines(text), [EXPECTED])
        self.assertEqual(form_errors(EXPECTED), [])
        self.assertEqual(evaluate(text), [])

    def test_eval_cases(self):
        for name, sample, errors in CASES:
            with self.subTest(name):
                self.assertEqual(evaluate(sample), errors)

    def test_a_shorter_fence_does_not_close_the_block(self):
        text = '~~~~\n' + GRILL + '\n~~~\n' + document(source_line())
        self.assertEqual(authority_lines(text), [])
        self.assertEqual(evaluate(text), ['authority-count'])


def main(argv):
    if argv[1:2] == ['--eval']:
        report = {name: evaluate(sample) for name, sample, _errors in CASES}
        report['contract'] = evaluate(contract_text())
        print(json.dumps(report, indent=2))
        failed = [name for name, sample, errors in CASES if evaluate(sample) != errors]
        return 1 if failed or report['contract'] else 0
    if argv[1:2] == ['--bench']:
        print(json.dumps(bench()))
        return 0
    unittest.main()


if __name__ == '__main__':
    sys.exit(main(sys.argv))
