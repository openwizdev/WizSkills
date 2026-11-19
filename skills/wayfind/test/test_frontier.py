#!/usr/bin/env python3
"""frontier.py through its CLI, against a fake `gh` serving synthetic GraphQL.

Each case runs the script with PATH holding only the fake `gh` and python3,
so the real `gh` is never reached. All issue data is synthetic.

Usage: python3 -I skills/wayfind/test/test_frontier.py
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/frontier.py'
FAKE_GH = '''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ['FIXTURE_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\\n')
if args[:2] != ['api', 'graphql']:
    sys.exit(90)
number = next(a.split('=', 1)[1] for a in args if a.startswith('number='))
served = json.load(open(os.environ['FIXTURE']))[number]
if served == 'fail':
    sys.exit(1)
print(json.dumps(served))
'''
URL = 'https://github.com/example/widgets/issues/{n}#issuecomment-{c}'


def conn(nodes, total=None):
    return {'totalCount': len(nodes) if total is None else total, 'nodes': nodes}


def question(n, kind='wayfind:grill', state='OPEN', blockers=(), comments=(), title=None):
    labels = [] if kind is None else [kind] if isinstance(kind, str) else list(kind)
    return {'number': n, 'title': title or f'Synthetic question {n}', 'state': state,
            'labels': conn([{'name': name} for name in labels]),
            'blockedBy': conn([{'number': b, 'state': s} for b, s in blockers]),
            'comments': conn([{'url': URL.format(n=n, c=c), 'body': body} for c, body in comments])}


def served(issue):
    return {'data': {'repository': {'issue': issue}}}


def a_map(n, questions, total=None):
    return served({'number': n, 'title': 'Synthetic map', 'state': 'OPEN',
                   'subIssues': conn(questions, total)})


CLAIM = 'wayfind: claimed'


class FrontierTest(unittest.TestCase):
    def run_script(self, fixture, *args):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tools = root / 'tools'
            tools.mkdir()
            (tools / 'python3').symlink_to(sys.executable)
            (tools / 'gh').write_text(FAKE_GH)
            (tools / 'gh').chmod(0o700)
            (root / 'fixture.json').write_text(json.dumps(fixture))
            result = subprocess.run(
                [sys.executable, '-I', str(SCRIPT), *args], capture_output=True, text=True,
                env={'PATH': str(tools), 'FIXTURE': str(root / 'fixture.json'),
                     'FIXTURE_LOG': str(root / 'log'), 'GH_REPO': 'example/widgets'})
            reads = [json.loads(line) for line in (root / 'log').read_text().splitlines()] \
                if (root / 'log').exists() else []
            return result, reads

    def test_map_lists_each_open_question_and_its_frontier_in_map_order(self):
        # catches: a closed, blocked, claimed or kind-less question offered as
        # frontier, or the map's order lost so "the first frontier" changes.
        fixture = {'1': a_map(1, [
            question(14, kind='wayfind:research', title='Which API limits apply?'),
            question(10, state='CLOSED'),
            question(11, blockers=[(10, 'CLOSED'), (12, 'OPEN'), (13, 'OPEN')]),
            question(12, comments=[(500, CLAIM)]),
            question(13, kind=None),
            question(15, kind=('wayfind:grill', 'wayfind:task')),
            question(16, blockers=[(10, 'CLOSED')]),
        ])}
        result, reads = self.run_script(fixture, 'map', '1')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout, (
            '#14 frontier wayfind:research: Which API limits apply?\n'
            '#11 blocked by #12 #13: Synthetic question 11\n'
            '#12 held by 500: Synthetic question 12\n'
            '#13 no kind label: Synthetic question 13\n'
            '#15 no kind label: Synthetic question 15\n'
            '#16 frontier wayfind:grill: Synthetic question 16\n'))
        self.assertEqual(len(reads), 1)

    def test_clear_map_says_so(self):
        # catches: an empty frontier read as "nothing to do" when questions
        # remain open, or a clear map mistaken for an unread one.
        result, _ = self.run_script({'2': a_map(2, [question(20, state='CLOSED')])}, 'map', '2')
        self.assertEqual((result.returncode, result.stdout), (0, 'no open question\n'))

    def test_earliest_unreleased_claim_holds(self):
        # catches: a later claim, or a released one, treated as the holder;
        # the comment id taken from anything but the #issuecomment- suffix.
        for ids, holder in [([100, 101, 103], '100'), ([101, 103, 104], '103')]:
            with self.subTest(claims=ids):
                comments = [(c, CLAIM) for c in ids] + [(110, 'wayfind: released 101')]
                result, _ = self.run_script({'9': served(question(9, comments=comments))},
                                            'holder', '9')
                self.assertEqual((result.returncode, result.stdout), (0, f'held by {holder}\n'))
        result, _ = self.run_script({'9': served(question(9, comments=[
            (100, CLAIM), (101, 'wayfind: released 100'), (102, 'Synthetic note')]))}, 'holder', '9')
        self.assertEqual(result.stdout, 'unclaimed\n')

    def test_mine_says_yours_only_for_the_holding_claim(self):
        # catches: an agent working on a question an earlier claim holds.
        comments = [(100, CLAIM), (101, CLAIM)]
        fixture = {'9': served(question(9, comments=comments))}
        self.assertEqual(self.run_script(fixture, 'holder', '9', '--mine', '100')[0].stdout, 'yours\n')
        self.assertEqual(self.run_script(fixture, 'holder', '9', '--mine', '101')[0].stdout,
                         'held by 100\n')
        closed = {'9': served(question(9, state='CLOSED', comments=comments))}
        self.assertEqual(self.run_script(closed, 'holder', '9', '--mine', '100')[0].stdout, 'closed\n')

    def test_incomplete_or_unreadable_read_prints_nothing_and_exits_2(self):
        # catches: a partial read reported as a frontier or a holder, so a
        # claim on an unread comment page or an unread question is missed.
        cases = {
            'gh fails': ({'1': 'fail'}, 'map'),
            'graphql error': ({'1': {'errors': [{'message': 'Synthetic'}]}}, 'map'),
            'no such issue': ({'1': served(None)}, 'map'),
            'questions truncated': ({'1': a_map(1, [question(11)], total=101)}, 'map'),
            'comments truncated': ({'1': a_map(1, [dict(question(11), comments=conn([], 101))])}, 'map'),
            'blockers truncated': ({'1': served(dict(question(1), blockedBy=conn([], 101)))}, 'holder'),
            'claim without its id': ({'1': served(dict(question(1), comments=conn(
                [{'url': 'https://github.com/example/widgets/issues/1', 'body': CLAIM}])))}, 'holder'),
        }
        for name, (fixture, verb) in cases.items():
            with self.subTest(name):
                result, _ = self.run_script(fixture, verb, '1')
                self.assertEqual((result.returncode, result.stdout), (2, ''))
                self.assertTrue(result.stderr.startswith('frontier: '), result.stderr)


if __name__ == '__main__':
    unittest.main()
