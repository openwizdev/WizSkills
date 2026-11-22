#!/usr/bin/env python3
import io
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench

START, END = '2026-01-10T00:00:00Z', '2026-01-17T00:00:00Z'
INSIDE, AFTER_END = '2026-01-12T00:00:00Z', '2026-01-18T00:00:00Z'
REVIEWER = {'login': 'jparker2006', '__typename': 'User'}
BOT = {'login': 'openwiz', '__typename': 'Bot'}
IMPOSTOR = {'login': 'openwiz', '__typename': 'User'}
STRANGER = {'login': 'someone', '__typename': 'User'}


def comment(body, author=REVIEWER, minute=0):
    return {'author': author, 'body': body, 'createdAt': '2026-01-11T%02d:%02d:00Z' % (minute // 60, minute % 60)}


def chatter(n, start):
    return [comment('Plain discussion %d.' % i, STRANGER, start + i) for i in range(n)]


def pr(number, comments=(), issues=(), diff=(10, 0), files=1, created='2026-01-09T00:00:00Z', merged=INSIDE):
    return {'number': number, 'title': 'Synthetic PR %d' % number, 'createdAt': created, 'mergedAt': merged,
            'additions': diff[0], 'deletions': diff[1], 'changedFiles': files,
            'comments': list(comments), 'closingIssuesReferences': [{'body': b} for b in issues]}


FIRST_REVIEW = '''VERDICT: CHANGES at aaaa

- **R1 [blocking]** `src/a.py:3` (Spec) Misses the empty input.
- **R2 [blocking]** `src/b.py:9` (Sweep) Fails open.
- **R3 [polish]** `src/c.py:1` (Standards) A comment.
'''
SECOND_REVIEW = '''VERDICT: CHANGES at bbbb

- **R1 [blocking]** resolved at bbbb: fixed.
- **R2 [blocking]** still open: the guard still fails open (Sweep).
- **R4 [blocking]** `src/d.py:7` (Standards) Rule broken.
'''
LAST_REVIEW = 'VERDICT: APPROVE at cccc\n\n- **R4 [blocking]** resolved at cccc: fixed.\n'


def alpha():
    big = (chatter(5, 0) + [comment(FIRST_REVIEW, minute=5)] + chatter(114, 6)
           + [comment(SECOND_REVIEW, minute=120)] + chatter(9, 121)
           + [comment('VERDICT: CHANGES at dddd\n\n- **R9 [blocking]** `x.py:1` (Spec) Not a record author.',
                      STRANGER, 130)] + chatter(18, 131) + [comment(LAST_REVIEW, minute=149)])
    assert len(big) == 150
    many = ['Not a ticket %d.' % i for i in range(100)] + ['## Parent\n\nTicket of spec. Size: S.\n']
    return [
        pr(1, big, ['Ticket of spec. Size: M.\n'], diff=(500, 200), files=7, created='2026-01-10T06:00:00Z'),
        pr(2, [], [], diff=(1, 1), created='2026-01-10T06:00:00Z'),
        pr(3, [comment('VERDICT: APPROVE at e%d' % i, minute=i) for i in range(5)], many,
           diff=(100, 20), files=2, created='2026-01-10T06:00:00Z'),
        pr(4, [comment('VERDICT: CHANGES at 1111')], ['Size: L.'], merged=AFTER_END, created='2026-01-10T06:00:00Z'),
        pr(5, [comment('VERDICT: CHANGES at 2222\n- **R1 [blocking]** `z.py:1` (Spec) Impostor.', IMPOSTOR, 1),
               comment('VERDICT: APPROVE at 3333', BOT, 2)], [], created='2026-01-08T00:00:00Z'),
    ]


def beta():
    return [pr(7, [comment('VERDICT: CHANGES at 4444\n\n- **R1 [blocking]** `q.py:2` (Spec) Wrong.', minute=1),
                   comment('VERDICT: CHANGES at 5555\n\n- **R2 [blocking]** `q.py:5` (Sweep) Leak.', minute=2),
                   comment('VERDICT: CHANGES at 6666\n\n- **R2 [blocking]** resolved at 6666.', minute=3),
                   comment('VERDICT: APPROVE at 7777', minute=4)],
               ['Ticket. Size: XS.'], diff=(1000, 500), files=30, created='2026-01-10T06:00:00Z')]


def gamma():
    return [pr(100 + i, [comment('VERDICT: APPROVE at 8888')], [], created='2026-01-10T06:00:00Z') for i in range(45)]


class FakeGitHub:
    def __init__(self, repos, issue_count=None):
        self.repos = repos
        self.issue_count = issue_count
        self.documents = []

    @staticmethod
    def page(items, first, after):
        start = int(after) if after else 0
        chunk = items[start:start + first]
        end = start + len(chunk)
        return {'pageInfo': {'hasNextPage': end < len(items), 'endCursor': str(end)}, 'nodes': chunk}

    def graphql(self, document, variables):
        bench.read_only(document)
        self.documents.append(document)
        if 'search(' in document:
            repo = re.match(r'repo:(\S+) is:pr is:merged merged:\S+\.\.\S+ sort:created-asc$', variables['q']).group(1)
            first = int(re.search(r'search\(type: ISSUE, query: \$q, first: (\d+)', document).group(1))
            page = self.page(self.repos[repo], first, variables.get('after'))
            nodes = []
            for node in page['nodes']:
                shaped = dict(node)
                for field in bench.CONNECTIONS:
                    size = int(re.search(field + r'\(first: (\d+)\)', document).group(1))
                    shaped[field] = self.page(node[field], size, None)
                nodes.append(shaped)
            count = len(self.repos[repo]) if self.issue_count is None else self.issue_count
            return {'search': {'issueCount': count, 'pageInfo': page['pageInfo'], 'nodes': nodes}}
        field, first = re.search(r'pullRequest\(number: \$number\) \{ (\w+)\(first: (\d+), after: \$after\)',
                                 document).groups()
        repo = variables['owner'] + '/' + variables['name']
        node = next(n for n in self.repos[repo] if n['number'] == variables['number'])
        return {'repository': {'pullRequest': {field: self.page(node[field], int(first), variables['after'])}}}


ARGS = ['--repo', 'synthetic/alpha', '--repo', 'synthetic/beta', '--repo', 'synthetic/gamma',
        '--merged-from', START, '--merged-to', END]


def run(argv, fake):
    out, err = io.StringIO(), io.StringIO()
    stderr, sys.stderr = sys.stderr, err
    try:
        code = bench.main(argv, graphql=fake.graphql, out=out)
    finally:
        sys.stderr = stderr
    return code, out.getvalue(), err.getvalue()


def result_of(text):
    return json.loads(text.split('```json\n', 1)[1].rsplit('\n```', 1)[0])


def fixture():
    return FakeGitHub({'synthetic/alpha': alpha(), 'synthetic/beta': beta(), 'synthetic/gamma': gamma()})


class FixtureCounts(unittest.TestCase):
    def setUp(self):
        code, self.text, err = run(ARGS, fixture())
        self.assertEqual((code, err), (0, ''))
        self.result = result_of(self.text)

    def test_alpha_reads_past_the_first_100_comments(self):
        a = self.result['all']['synthetic/alpha']
        self.assertEqual((a['merged'], a['reviewed'], a['verdicts']), (4, 3, 9))
        self.assertEqual(a['rounds'], {'mean': 3.0, 'median': 3, 'p90': 5, 'max': 5})
        self.assertEqual(a['changes'], {'total': 2, 'mean': 0.67})
        self.assertEqual(a['approve_first'], {'count': 2, 'pct': 67})
        self.assertEqual(a['three_plus'], {'count': 2, 'pct': 67})
        self.assertEqual(a['distribution'], {'1': 1, '2': 0, '3': 1, '4': 0, '5+': 1})
        self.assertEqual(a['reapprovals'], 4)
        self.assertEqual(a['findings'], {
            'first': {'Spec': 1, 'Sweep': 1, 'Standards': 0, 'total': 2},
            'rechecks': {'Spec': 0, 'Sweep': 0, 'Standards': 1, 'total': 1, 'count': 6, 'with_new_blocker': 1}})

    def test_overall_counts(self):
        a = self.result['all']['All']
        self.assertEqual((a['merged'], a['reviewed'], a['verdicts']), (50, 49, 58))
        self.assertEqual(a['rounds'], {'mean': 1.18, 'median': 1, 'p90': 1, 'max': 5})
        self.assertEqual(a['changes'], {'total': 5, 'mean': 0.1})
        self.assertEqual(a['approve_first'], {'count': 47, 'pct': 96})
        self.assertEqual(a['three_plus'], {'count': 3, 'pct': 6})
        self.assertEqual(a['distribution'], {'1': 46, '2': 0, '3': 1, '4': 1, '5+': 1})
        self.assertEqual(a['findings'], {
            'first': {'Spec': 2, 'Sweep': 1, 'Standards': 0, 'total': 3},
            'rechecks': {'Spec': 0, 'Sweep': 1, 'Standards': 1, 'total': 2, 'count': 9, 'with_new_blocker': 2}})
        self.assertEqual(self.result['all']['synthetic/gamma']['merged'], 45)

    def test_ticket_prs_by_size_and_band(self):
        t = self.result['tickets']
        self.assertEqual([t[k]['merged'] for k in ('synthetic/alpha', 'synthetic/beta', 'synthetic/gamma', 'All')],
                         [2, 0, 0, 2])
        self.assertEqual(t['All']['rounds'], {'mean': 4.0, 'median': 4.0, 'p90': 5, 'max': 5})
        bands = self.result['ticket_bands']
        self.assertEqual({k: v['merged'] for k, v in bands.items()},
                         {'under 300': 1, '300-599': 0, '600+': 1, '600-999': 1, '1000+': 0})
        self.assertEqual(bands['600+']['changes'], {'total': 2, 'mean': 2.0})
        self.assertEqual(bands['under 300']['approve_first'], {'count': 1, 'pct': 100})
        self.assertEqual(self.result['ticket_sizes'], {'S': {'count': 1, 'median_diff': 120},
                                                       'M': {'count': 1, 'median_diff': 700},
                                                       'L': {'count': 0, 'median_diff': None}})

    def test_worst_ranks_by_changes_then_rounds(self):
        worst = [(w['repo'], w['number'], w['rounds'], w['changes']) for w in self.result['worst']]
        self.assertEqual(worst[:5], [('synthetic/beta', 7, 4, 3), ('synthetic/alpha', 1, 3, 2),
                                     ('synthetic/alpha', 3, 5, 0), ('synthetic/alpha', 5, 1, 0),
                                     ('synthetic/gamma', 100, 1, 0)])
        self.assertEqual(len(worst), 10)

    def assertRowIn(self, row):
        self.assertTrue(row in self.text.splitlines(), 'missing row: ' + row)

    def test_markdown_rows(self):
        self.assertRowIn('| All | 50 | 49 | 1.18 | 1 | 1 | 5 | 0.10 | 47 (96%) | 3 (6%) | 3 (2/1/0) | 2 of 9 | 2 (0/1/1) |')
        self.assertRowIn('| synthetic/alpha | 4 | 3 | 3 | 3 | 5 | 5 | 0.67 | 2 (67%) | 2 (67%) | 2 (1/1/0) | 1 of 6 | 1 (0/0/1) |')
        self.assertRowIn('| beta#7 | 4 (3) | none | 1500 | 30 |')
        self.assertRowIn('| alpha#1 | 3 (2) | M | 700 | 7 |')


class Cohorts(unittest.TestCase):
    def test_opened_after_drops_older_prs(self):
        code, text, _ = run(ARGS + ['--opened-after', '2026-01-09T12:00:00Z'], fixture())
        a = result_of(text)['all']
        self.assertEqual(code, 0)
        self.assertEqual((a['synthetic/alpha']['merged'], a['synthetic/alpha']['reviewed']), (3, 2))
        self.assertEqual((a['synthetic/beta']['merged'], a['synthetic/gamma']['merged']), (1, 45))

    def test_search_over_the_cap_fails_closed(self):
        code, text, err = run(ARGS, FakeGitHub({'synthetic/alpha': alpha(), 'synthetic/beta': beta(),
                                                'synthetic/gamma': gamma()}, issue_count=1001))
        self.assertEqual((code, text), (1, ''))
        self.assertIn('over the search cap', err)

    def test_short_search_fails_closed(self):
        code, text, err = run(ARGS, FakeGitHub({'synthetic/alpha': alpha(), 'synthetic/beta': beta(),
                                                'synthetic/gamma': gamma()}, issue_count=46))
        self.assertEqual((code, text), (1, ''))
        self.assertIn('synthetic/alpha: search reported 46 PRs but returned 5', err)


    def test_a_repeated_search_result_fails_closed(self):
        code, text, err = run(ARGS, FakeGitHub({'synthetic/alpha': alpha() + alpha()[:1], 'synthetic/beta': beta(),
                                                'synthetic/gamma': gamma()}))
        self.assertEqual((code, text), (1, ''))
        self.assertIn('synthetic/alpha: search returned PR 1 twice', err)

    def test_bad_arguments_exit_2(self):
        for argv in (ARGS[:-1] + ['2026-01-17T00:00:00'], ARGS[:-1] + ['soon'], ['--repo', 'no-slash'] + ARGS[6:],
                     ARGS + ['--repo', 'synthetic/alpha'], ARGS[:-3] + [END, '--merged-to', START]):
            stderr, sys.stderr = sys.stderr, io.StringIO()
            try:
                with self.assertRaises(SystemExit) as raised:
                    bench.main(argv, graphql=fixture().graphql, out=io.StringIO())
            finally:
                sys.stderr = stderr
            self.assertEqual(raised.exception.code, 2, argv)


class Transport(unittest.TestCase):
    def reply(self, stdout, code=0):
        class Done:
            returncode, stderr = code, 'synthetic failure'
        Done.stdout = stdout
        return bench.gh_graphql(bench.SEARCH, {'q': 'x', 'after': None}, lambda args, **kw: Done())

    def test_unreadable_or_failed_replies_fail_closed(self):
        for stdout, code in (('not json', 0), ('[1]', 0), ('{"errors": [{"message": "x"}], "data": null}', 0),
                             ('{"data": null}', 0), ('{"data": {}}', 1)):
            with self.assertRaises(bench.BenchError, msg=stdout):
                self.reply(stdout, code)
        self.assertEqual(self.reply('{"data": {"search": 1}}'), {'search': 1})


class ReadOnly(unittest.TestCase):
    def test_every_document_sent_is_a_query(self):
        fake = fixture()
        run(ARGS, fake)
        self.assertEqual(len(fake.documents), 6)
        for document in fake.documents:
            self.assertRegex(document, r'^query\(')
            self.assertNotRegex(document, r'\bmutation\b')

    def test_a_mutation_never_reaches_gh(self):
        calls = []
        with self.assertRaises(bench.BenchError):
            bench.gh_graphql('mutation { addComment(input: {}) { clientMutationId } }', {}, runner=calls.append)
        with self.assertRaises(bench.BenchError):
            bench.gh_graphql(bench.SEARCH + ' extra { x }', {}, runner=calls.append)
        with self.assertRaises(bench.BenchError):
            bench.gh_graphql('query { viewer { login } }', {}, runner=calls.append)
        self.assertEqual(calls, [])

    def test_gh_gets_only_a_graphql_query(self):
        calls = []

        class Done:
            returncode, stdout, stderr = 0, '{"data": {"ok": 1}}', ''

        def runner(args, **kwargs):
            calls.append(args)
            return Done()

        self.assertEqual(bench.gh_graphql(bench.MORE % ('comments', 100, bench.COMMENT_NODE),
                                          {'owner': 'o', 'name': 'n', 'number': 3, 'after': None}, runner), {'ok': 1})
        self.assertEqual(calls[0][:4], ['gh', 'api', 'graphql', '-f'])
        self.assertEqual(calls[0][5:], ['-f', 'owner=o', '-f', 'name=n', '-F', 'number=3'])

    def test_source_has_no_mutation(self):
        with open(bench.__file__, encoding='utf-8') as handle:
            self.assertNotRegex(handle.read(), r'(?i)\bmutation\b')


if __name__ == '__main__':
    unittest.main()
