#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
LEDGER = HERE / 'ledger.py'
REPO = 'synthetic-owner/synthetic-work'
OTHER = 'synthetic-owner/synthetic-skills'
FLEET = '''# Fleet settings

## GitHub identity

| Setting | Value |
| --- | --- |
| Record authors | `synthetic-bot[bot]`, `synthetic-lead` |
'''

FAKE_GH = r'''
import json, os, sys
args = sys.argv[1:]
with open(os.environ['FAKE_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\n')
world = json.load(open(os.environ['FAKE_WORLD']))
if args[:1] == ['api'] and args[1].endswith('/contents/docs/agents/fleet.md'):
    if world.get('fleet') is None:
        sys.exit('HTTP 404')
    sys.stdout.write(world['fleet'])
    sys.exit(0)
if args[:2] != ['api', 'graphql']:
    sys.exit('fake gh: unexpected call')
fields = {}
for i, a in enumerate(args):
    if a in ('-f', '-F'):
        k, v = args[i + 1].split('=', 1)
        fields[k] = v
query = fields['query']
count = world['calls'] = world.get('calls', 0) + 1
json.dump(world, open(os.environ['FAKE_WORLD'], 'w'))
if world.get('fail_call') == count:
    sys.exit('HTTP 502: synthetic failure')
errors = [{'type': 'SYNTHETIC', 'message': 'synthetic error'}] if world.get('errors_call') == count else []

def answer(data):
    print(json.dumps({'data': data, **({'errors': errors} if errors else {})}))
if 'mutation' in query:
    sys.exit('fake gh: a write')

def page(items, size, after):
    start = int(after) if after else 0
    end = start + size
    return items[start:end], {'hasNextPage': end < len(items), 'endCursor': str(end)}

def comments(repo, number, after):
    raw = world['repos'][repo]['issues'][str(number)]['comments']
    made = [{'author': None if c['login'] is None else {'__typename': c.get('type', 'User'), 'login': c['login']},
             'body': c['body'], 'databaseId': 1000 * number + i, 'createdAt': '2026-01-01T00:%02d:00Z' % i}
            for i, c in enumerate(raw)]
    nodes, info = page(made, world['cpage'], after)
    return {'pageInfo': info, 'nodes': nodes}

def issue(repo, number):
    found = world['repos'][repo]['issues'][str(number)]
    return {'number': number, 'state': found['state'], 'repository': {'nameWithOwner': repo},
            'comments': comments(repo, number, None)}

repo = fields['owner'] + '/' + fields['name']
after = fields.get('after')
if 'subIssues' in query:
    subs = world['specs'].get(repo + '#' + fields['number'])
    if subs is None:
        answer({'repository': {'issue': None}})
        sys.exit(0)
    nodes, info = page([issue(s.split('#')[0], int(s.split('#')[1])) for s in subs], world['page'], after)
    answer({'repository': {'issue': {'subIssues': {'pageInfo': info, 'nodes': nodes}}}})
elif 'issues(' in query:
    closed = sorted(int(n) for n, i in world['repos'][repo]['issues'].items() if i['state'] == 'CLOSED')
    nodes, info = page([issue(repo, n) for n in closed], world['page'], after)
    answer({'repository': {'issues': {'pageInfo': info, 'nodes': nodes}}})
else:
    number = int(fields['number'])
    answer({'repository': {'issue': {'comments': comments(repo, number, after)}}})
'''


def by(login, body, kind='User'):
    return {'login': login, 'type': kind, 'body': body}


def lead(body):
    return by('synthetic-lead', body)


def known(ticket, pr, total):
    return lead(f'launch-fleet: cost: Ticket #{ticket} cost (PR #{pr}): builder {total} credits, unknown tokens; '
                f'reviewer 0 credits, unknown tokens; CI unknown; total {total} credits, unknown tokens, '
                'unknown runner minutes')


def closed(*comments):
    return {'state': 'CLOSED', 'comments': [lead('launch-fleet: archived'), *comments]}


class World:
    def __init__(self, test, issues, others=None, specs=None, fleet=FLEET, **faults):
        self.dir = Path(tempfile.mkdtemp())
        test.addCleanup(subprocess.run, ['rm', '-rf', str(self.dir)])
        (self.dir / 'bin').mkdir()
        gh = self.dir / 'bin/gh'
        gh.write_text('#!/bin/sh\nexec "%s" -I "%s" "$@"\n' % (sys.executable, self.dir / 'fake_gh.py'))
        gh.chmod(0o755)
        (self.dir / 'fake_gh.py').write_text(FAKE_GH)
        world = {'fleet': fleet, 'repos': {REPO: {'issues': issues}, OTHER: {'issues': others or {}}},
                 'specs': specs or {}, 'page': 2, 'cpage': 2, **faults}
        (self.dir / 'world.json').write_text(json.dumps(world))
        self.log = self.dir / 'calls.log'
        self.log.write_text('')
        self.env = dict(os.environ, PATH='%s:%s' % (self.dir / 'bin', os.environ['PATH']),
                        FAKE_WORLD=str(self.dir / 'world.json'), FAKE_LOG=str(self.log))

    def run(self, *args):
        r = subprocess.run([sys.executable, '-I', str(LEDGER), *args], capture_output=True, text=True,
                           env=self.env, cwd=self.dir, timeout=60)
        return r.returncode, r.stdout, r.stderr

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]


MIXED = {
    '10': closed(known(10, 110, '12.5')),
    '11': closed(lead('launch-fleet: cost unknown (PR #111): no cost command')),
    '12': closed(lead('launch-fleet: cost: Ticket #12 cost (PR #112): builder unknown; reviewer unknown; '
                      'CI 60.0 runner minutes; total unknown credits, unknown tokens, 60.0 runner minutes')),
    '13': closed(known(13, 113, '7.25')),
    '14': closed(lead('launch-fleet: cost unknown (PR synthetic-owner/synthetic-skills#9): the cost command '
                      "costs only tickets in the pull request's repository")),
    '15': closed(),
    '16': {'state': 'OPEN', 'comments': []},
}


class Ledger(unittest.TestCase):
    def test_rows_total_and_cost_per_merged_pr_count_unknown_rows(self):
        w = World(self, MIXED)
        self.assertEqual(w.run(REPO), (0, '#10  PR #110  12.50\n'
                                          '#11  PR #111  unknown\n'
                                          '#12  PR #112  unknown\n'
                                          '#13  PR #113  7.25\n'
                                          '#14  PR synthetic-owner/synthetic-skills#9  unknown\n'
                                          'Merged: 5; known: 2; unknown: 3; total: 19.75 credits; '
                                          'cost per merged PR: 9.88 credits (2 of 5 known)\n', ''))

    def test_no_known_row_gives_unknown_total_and_cost_per_merged_pr(self):
        w = World(self, {'11': MIXED['11'], '12': MIXED['12']})
        self.assertEqual(w.run(REPO), (0, '#11  PR #111  unknown\n#12  PR #112  unknown\n'
                                          'Merged: 2; known: 0; unknown: 2; total: unknown; '
                                          'cost per merged PR: unknown (0 of 2 known)\n', ''))

    def test_outsiders_are_ignored_and_the_newest_record_wins(self):
        issues = {
            '20': closed(known(20, 120, '5'), by('synthetic-stranger', 'launch-fleet: cost unknown (PR #120): x')),
            '21': closed(known(21, 121, '3'), by('synthetic-bot', 'launch-fleet: cost unknown (PR #121): no cost '
                                                 'command', kind='Bot')),
            '22': closed(by('synthetic-stranger', known(22, 122, '100')['body'])),
            '23': closed(lead('launch-fleet: cost unknown (PR #123): no cost command'), known(23, 123, '4.5')),
            '24': closed(by(None, known(24, 124, '9')['body'])),
            '25': closed(by('synthetic-bot', known(25, 125, '1')['body'], kind='User')),
        }
        self.assertEqual(World(self, issues).run(REPO), (0, '#20  PR #120  5.00\n'
                                                            '#21  PR #121  unknown\n'
                                                            '#23  PR #123  4.50\n'
                                                            'Merged: 3; known: 2; unknown: 1; total: 9.50 credits; '
                                                            'cost per merged PR: 4.75 credits (2 of 3 known)\n', ''))

    def test_spec_limits_rows_to_its_closed_sub_issues(self):
        others = {'7': closed(known(7, 70, '2'))}
        specs = {REPO + '#1': [REPO + '#10', REPO + '#11', REPO + '#16', OTHER + '#7']}
        w = World(self, MIXED, others=others, specs=specs)
        self.assertEqual(w.run(REPO, '--spec', '1'), (0, '#10  PR #110  12.50\n'
                                                         '#11  PR #111  unknown\n'
                                                         'synthetic-owner/synthetic-skills#7  PR synthetic-owner/synthetic-skills#70  2.00\n'
                                                         'Merged: 3; known: 2; unknown: 1; total: 14.50 credits; '
                                                         'cost per merged PR: 7.25 credits (2 of 3 known)\n', ''))

    def test_json_prints_the_same_fields(self):
        code, out, err = World(self, MIXED).run(REPO, '--json')
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(json.loads(out), {
            'rows': [{'ticket': '#10', 'pr': '#110', 'credits': 12.5},
                     {'ticket': '#11', 'pr': '#111', 'credits': None},
                     {'ticket': '#12', 'pr': '#112', 'credits': None},
                     {'ticket': '#13', 'pr': '#113', 'credits': 7.25},
                     {'ticket': '#14', 'pr': 'synthetic-owner/synthetic-skills#9', 'credits': None}],
            'merged': 5, 'known': 2, 'unknown': 3, 'total': 19.75, 'cost_per_merged_pr': 9.88})

    def assert_read_only(self, w):
        calls = w.calls()
        self.assertTrue(calls)
        for call in calls:
            self.assertNotIn('--method', call)
            self.assertFalse(any('mutation' in a for a in call), call)

    def test_it_writes_nothing(self):
        w = World(self, MIXED)
        self.assertEqual(w.run(REPO)[0], 0)
        self.assert_read_only(w)

    def test_the_read_only_check_sees_every_write_spelling_and_passes_every_read(self):
        path = f'repos/{REPO}/issues/10'
        writes = {'a short -X POST': ['api', '-X', 'POST', path + '/comments', '-f', 'body=x'],
                  'a joined -XPATCH': ['api', '-XPATCH', path, '-f', 'state=closed'],
                  'a long --method=DELETE': ['api', '--method=DELETE', path + '/labels/x'],
                  'a lower-case method': ['api', '--method', 'put', path + '/lock'],
                  'fields that make gh POST': ['api', path + '/comments', '-f', 'body=x'],
                  'a long --raw-field=': ['api', path + '/comments', '--raw-field=body=x'],
                  'a body from --input': ['api', path + '/comments', '--input', '-'],
                  'a GraphQL mutation': ['api', 'graphql', '-f', 'query=mutation { a: b(input: {}) { c } }'],
                  'a named mutation in a joined field': ['api', 'graphql', '-Fquery=mutation M { a { b } }'],
                  'a gh command that writes': ['issue', 'comment', '10', '--body', 'x']}
        reads = {'a GraphQL query sent with an explicit POST': ['api', 'graphql', '--method', 'POST', '-f',
                                                                'query=query { viewer { login } }'],
                 'a shorthand GraphQL query': ['api', 'graphql', '-f', 'query={ viewer { login } }'],
                 'a REST GET with query fields': ['api', '-X', 'GET', f'repos/{REPO}/issues', '-f', 'state=closed'],
                 'a plain REST read': ['api', f'repos/{REPO}/contents/docs/agents/fleet.md', '-H', 'Accept: x']}
        for name, args in {**writes, **reads}.items():
            with self.subTest(name):
                w = World(self, MIXED)
                subprocess.run(['gh', *args], capture_output=True, env=w.env, cwd=w.dir, timeout=60)
                if name in writes:
                    with self.assertRaises(AssertionError, msg='a write passed the read-only check'):
                        self.assert_read_only(w)
                else:
                    self.assert_read_only(w)

    def test_a_failed_or_partial_read_prints_nothing_and_exits_1(self):
        big = {str(n): closed(known(n, 100 + n, '1'), lead('launch-fleet: archived'), lead('launch-fleet: x'))
               for n in range(30, 36)}
        cases = {'no record authors': dict(fleet=None),
                 'the first page fails': dict(fail_call=1),
                 'the second read fails': dict(fail_call=2),
                 'the fourth read fails': dict(fail_call=4),
                 'a whole answer that also carries errors': dict(errors_call=3)}
        for name, faults in cases.items():
            with self.subTest(name):
                code, out, err = World(self, big, **faults).run(REPO)
                self.assertEqual((code, out), (1, ''))
                self.assertTrue(err.strip())
        with self.subTest('a missing spec'):
            code, out, _ = World(self, big).run(REPO, '--spec', '99')
            self.assertEqual((code, out), (1, ''))
        with self.subTest('a comment body that is not text'):
            odd = dict(big, **{'41': closed({'login': 'synthetic-lead', 'type': 'User', 'body': None})})
            code, out, _ = World(self, odd).run(REPO)
            self.assertEqual((code, out), (1, ''))
        with self.subTest('an issue state it does not know'):
            odd = dict(big, **{'42': dict(closed(known(42, 142, '1')), state='SYNTHETIC')})
            code, out, _ = World(self, odd, specs={REPO + '#1': [REPO + '#30', REPO + '#42']}).run(REPO, '--spec', '1')
            self.assertEqual((code, out), (1, ''))
        with self.subTest('an unreadable cost record'):
            odd = dict(big, **{'40': closed(lead('launch-fleet: cost: something else'))})
            code, out, _ = World(self, odd).run(REPO)
            self.assertEqual((code, out), (1, ''))

    def test_the_writers_grouped_credit_amounts_are_read(self):
        issues = {'10': closed(known(10, 110, '1,000.25')), '11': closed(known(11, 111, '2,500,000'))}
        self.assertEqual(World(self, issues).run(REPO), (0, '#10  PR #110  1000.25\n'
                                                            '#11  PR #111  2500000.00\n'
                                                            'Merged: 2; known: 2; unknown: 0; total: 2501000.25 credits; '
                                                            'cost per merged PR: 1250500.13 credits (2 of 2 known)\n', ''))
        for bad in ('1,00.25', '1000,000', ',100', '1,000,00'):
            with self.subTest(bad):
                code, out, _ = World(self, {'10': closed(known(10, 110, bad))}).run(REPO)
                self.assertEqual((code, out), (1, ''))

    def test_one_row_per_pull_request_when_several_tickets_carry_its_cost(self):
        issues = {'10': closed(known(10, 110, '12.5')), '11': closed(known(11, 110, '12.5')),
                  '12': closed(lead('launch-fleet: cost unknown (PR #120): no cost command')),
                  '13': closed(known(13, 120, '4')),
                  '14': closed(lead('launch-fleet: cost unknown (PR synthetic-owner/synthetic-work#110): x'))}
        self.assertEqual(World(self, issues).run(REPO), (0, '#13  PR #120  4.00\n'
                                                            '#14  PR #110  unknown\n'
                                                            'Merged: 2; known: 1; unknown: 1; total: 4.00 credits; '
                                                            'cost per merged PR: 4.00 credits (1 of 2 known)\n', ''))
        others = {'7': closed(known(7, 9, '2'))}
        same = {'14': closed(lead('launch-fleet: cost unknown (PR synthetic-owner/synthetic-skills#9): x'))}
        w = World(self, same, others=others, specs={REPO + '#1': [REPO + '#14', OTHER + '#7']})
        self.assertEqual(w.run(REPO, '--spec', '1'), (0, '#14  PR synthetic-owner/synthetic-skills#9  unknown\n'
                                                         'Merged: 1; known: 0; unknown: 1; total: unknown; '
                                                         'cost per merged PR: unknown (0 of 1 known)\n', ''))

    def test_every_page_is_read(self):
        big = {str(n): closed(lead('launch-fleet: x'), lead('launch-fleet: y'), known(n, 100 + n, '1'))
               for n in range(30, 37)}
        code, out, _ = World(self, big).run(REPO)
        self.assertEqual(code, 0)
        self.assertTrue(out.endswith('Merged: 7; known: 7; unknown: 0; total: 7.00 credits; '
                                     'cost per merged PR: 1.00 credits (7 of 7 known)\n'), out)


if __name__ == '__main__':
    unittest.main()
