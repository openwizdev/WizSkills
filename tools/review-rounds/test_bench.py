#!/usr/bin/env python3
import inspect
import io
import json
import os
import re
import subprocess
import sys
import tempfile
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

    def test_a_repository_named_twice_in_any_case_is_refused(self):
        fake = FakeGitHub({'synthetic/alpha': alpha(), 'Synthetic/Alpha': alpha()})
        for second in ('Synthetic/Alpha', 'SYNTHETIC/alpha', 'synthetic/alpha'):
            stderr, sys.stderr = sys.stderr, io.StringIO()
            try:
                with self.assertRaises(SystemExit) as raised:
                    bench.main(['--repo', 'synthetic/alpha', '--repo', second, '--merged-from', START, '--merged-to', END],
                               graphql=fake.graphql, out=io.StringIO())
                message = sys.stderr.getvalue()
            finally:
                sys.stderr = stderr
            self.assertEqual(raised.exception.code, 2, second)
            self.assertIn('--repo repeated: synthetic/alpha and ' + second, message)
        self.assertEqual(fake.documents, [])

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


GIT_ENV = {'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_AUTHOR_NAME': 'Synthetic',
           'GIT_AUTHOR_EMAIL': 'synthetic@example.invalid', 'GIT_COMMITTER_NAME': 'Synthetic',
           'GIT_COMMITTER_EMAIL': 'synthetic@example.invalid', 'GIT_AUTHOR_DATE': '2026-01-01T00:00:00Z',
           'GIT_COMMITTER_DATE': '2026-01-01T00:00:00Z'}


def synthetic_clone(where):
    def git(*args):
        return subprocess.run(['git', '-C', where] + list(args), check=True, capture_output=True, text=True,
                              env=dict(os.environ, **GIT_ENV)).stdout.strip()

    def commit(files, message):
        for name, lines in files.items():
            os.makedirs(os.path.dirname(os.path.join(where, name)) or where, exist_ok=True)
            with open(os.path.join(where, name), 'w', encoding='utf-8') as handle:
                handle.write(''.join(line + '\n' for line in lines))
        git('add', '-A')
        git('commit', '-q', '--no-gpg-sign', '-m', message)
        return git('rev-parse', 'HEAD')

    git('init', '-q')
    base = commit({'README.md': ['base']}, 'O')
    a_lines = ['a%d' % i for i in range(1, 11)]
    a = commit({'a.py': a_lines, 'b.py': ['b%d' % i for i in range(1, 6)], 'tests/test_a.py': ['t1', 't2', 't3']}, 'A')
    fixed = ['new0', 'new1'] + a_lines[:4] + ['A5'] + a_lines[5:]
    b = commit({'a.py': fixed, 'c.py': ['c1']}, 'B')
    c = commit({'a.py': fixed[:10] + ['A9', 'a10']}, 'C')
    return base, a, b, c


def late_repos(base, a, b, c):
    rounds = [
        comment('VERDICT: CHANGES at %s\n\n- **R1 [blocking]** `a.py:5` (Spec) First review.' % a, minute=1),
        comment('VERDICT: CHANGES at %s\n\n- **R1 [blocking]** resolved at %s.\n'
                '- **R2 [blocking]** `a.py:7` (Spec) On the fixed line.\n'
                '- **R3 [blocking]** `a.py:5` (Sweep) On an untouched line the fix moved down.\n'
                '- **R4 [blocking]** `b.py:2` (Standards) In a file the fix left alone.\n'
                '- **R5 [blocking]** `c.py:1` (Spec) In a file the fix added.\n'
                '- **R6 [blocking]** `a.py:2-4` (Spec) A range that starts on an added line.\n'
                '- **R7 [blocking]** `docs/x.md` (Spec) No line named.\n'
                '- **R0 [polish]** `b.py:1` (Spec) Not blocking. Polish issue: #31.\n' % (b, b), minute=2),
        comment('VERDICT: CHANGES at %s\n\n- **R8 [blocking]** `a.py:11` (Sweep) On the later fix.\n'
                '- **R9 [blocking]** `a.py:12` (Spec) Untouched since the first review.\n'
                '- **R10 [polish]** `a.py:1` (Sweep) Polish issue: #32.\n' % c, minute=3),
        comment('VERDICT: APPROVE at %s\n\n- **R3 [blocking]** withdrawn: the evidence holds.\n'
                '- **R0 [polish]** Polish issue: #31.\n- **R10 [polish]** Polish issue: #32.\n'
                '- **R11 [polish]** Polish issue: #33.\n- **R12 [polish]** Polish issue: #34.\n' % c, minute=4),
        comment('VERDICT: APPROVE at %s\n\n- **R3 [blocking]** withdrawn: still withdrawn.\n' % c, minute=5),
    ]
    missing = [comment('VERDICT: CHANGES at %s' % a, minute=1),
               comment('VERDICT: CHANGES at %s\n\n- **R1 [blocking]** `a.py:1` (Spec) Head not in the clone.'
                       % ('e' * 40), minute=2),
               comment('VERDICT: APPROVE at %s\n\n- **R1 [blocking]** withdrawn: not reproduced.\n'
                       '- **R2 [polish]** Polish issue: #40.\n- **R3 [polish]** Polish issue: #41.\n'
                       '- **R4 [polish]** Polish issue: #42.\n' % ('e' * 40), minute=3)]
    fixed = pr(8, rounds, ['Ticket. Size: S.'])
    fixed.update(baseRefOid=base, headRefOid=c)
    fixed['closingIssuesReferences'][0]['repository'] = {'nameWithOwner': 'synthetic/late'}
    gone = pr(9, missing, ['Ticket. Size: M.'], diff=(400, 0))
    gone.update(baseRefOid=base, headRefOid='e' * 40)
    gone['closingIssuesReferences'][0]['repository'] = {'nameWithOwner': 'synthetic/tickets'}
    recent = pr(10, [comment('VERDICT: APPROVE at %s\n\n- **R1 [polish]** Polish issue: #35.\n' % c)],
                merged='2026-01-16T00:00:00Z')
    return {'synthetic/late': [fixed, gone, recent], 'synthetic/beta': beta()}


NOW = '2026-01-20T00:00:00Z'


def polish(number, state='OPEN', reason=None, closed=None, title=None):
    return {'number': number, 'title': title or 'A claim (polish for #1, R%d)' % number, 'state': state,
            'stateReason': reason, 'closedAt': closed}


ISSUES = {
    ('synthetic/late', 31): polish(31, 'CLOSED', 'COMPLETED', '2026-01-13T00:00:00Z'),
    ('synthetic/late', 32): polish(32),
    ('synthetic/late', 33): polish(33, 'CLOSED', 'NOT_PLANNED', '2026-01-13T00:00:00Z'),
    ('synthetic/late', 34): polish(34, 'CLOSED', 'COMPLETED', '2026-01-19T12:00:00Z'),
    ('synthetic/late', 35): polish(35),
    ('synthetic/tickets', 40): polish(40, 'CLOSED', 'COMPLETED', '2026-01-14T00:00:00Z'),
    ('synthetic/tickets', 42): polish(42, title='Not a polish issue'),
    ('synthetic/late', 40): polish(40),
}


def fake_issue(lookups):
    def issue(repo, number):
        lookups.append((repo, number))
        return ISSUES.get((repo, number))
    return issue


LATE_ARGS = ['--repo', 'synthetic/late', '--repo', 'synthetic/beta', '--merged-from', START, '--merged-to', END]


def run_late(argv, fake, git=None, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    stderr, sys.stderr = sys.stderr, err
    if git is not None:
        kwargs['git'] = git
    kwargs = {k: v for k, v in kwargs.items() if k in inspect.signature(bench.main).parameters}
    try:
        code = bench.main(argv, graphql=fake.graphql, out=out, **kwargs)
    except SystemExit as stop:
        code = stop.code
    finally:
        sys.stderr = stderr
    return code, out.getvalue(), err.getvalue()


class LateFindings(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.clone = self.temp.name
        self.heads = synthetic_clone(self.clone)
        self.addCleanup(self.temp.cleanup)

    def late_run(self, git=None, lookups=None):
        code, text, err = run_late(LATE_ARGS + ['--clone', 'synthetic/late=' + self.clone],
                                   FakeGitHub(late_repos(*self.heads)), git,
                                   issue=fake_issue([] if lookups is None else lookups), now=bench.parse_time(NOW))
        self.assertEqual((code, err), (0, ''))
        return text, result_of(text)

    def test_late_counts_split_by_what_the_fix_changed(self):
        text, result = self.late_run()
        self.assertEqual(result['all']['synthetic/late']['late'],
                         {'blocking': 10, 'late': 9, 'pct': 90, 'changed': 4, 'unchanged': 3, 'unknown': 2})
        self.assertEqual(result['all']['synthetic/beta']['late'],
                         {'blocking': 2, 'late': 1, 'pct': 50, 'changed': 0, 'unchanged': 0, 'unknown': 1})
        self.assertEqual(result['all']['All']['late'],
                         {'blocking': 12, 'late': 10, 'pct': 83, 'changed': 4, 'unchanged': 3, 'unknown': 3})
        self.assertEqual(result['all']['All']['rounds']['mean'], 3.25)
        self.assertIn('| All | 4 | 4 | 3.25 | 12 | 10 (83%) | 4 (40%) | 3 (30%) | 3 (30%) |', text.splitlines())

    def test_withdrawn_blockers_and_ignored_polish_issues(self):
        lookups = []
        text, result = self.late_run(lookups=lookups)
        self.assertEqual(result['all']['synthetic/late'].get('withdrawn_ignored'), {
            'blocking': 10, 'withdrawn': 2, 'withdrawn_pct': 20,
            'polish': 8, 'not_due': 1, 'unknown': 2, 'due': 5, 'ignored': 3, 'ignored_pct': 60,
            'either_pct': 33})
        self.assertEqual(result['all']['synthetic/beta']['withdrawn_ignored'], {
            'blocking': 2, 'withdrawn': 0, 'withdrawn_pct': 0, 'polish': 0, 'not_due': 0, 'unknown': 0, 'due': 0,
            'ignored': 0, 'ignored_pct': None, 'either_pct': 0})
        self.assertEqual(sorted(lookups), [('synthetic/late', n) for n in (31, 32, 33, 34)]
                         + [('synthetic/tickets', n) for n in (40, 41, 42)])
        self.assertIn('| synthetic/late | 3 | 3 | 3 | 10 | 2 (20%) | 8 | 1 | 2 | 3 of 5 (60%) | 33% |',
                      text.splitlines())

    def test_diff_size_splits_tests_from_code_in_the_bands(self):
        text, result = self.late_run()
        size = {'sized': 1, 'unknown': 2, 'code_lines': 18, 'test_lines': 3, 'code_files': 3, 'test_files': 1}
        self.assertEqual(result['all']['synthetic/late'].get('size'), size)
        self.assertEqual(result['ticket_bands']['under 300']['size'], dict(size, unknown=0))
        self.assertEqual(result['ticket_bands']['300-599']['size'], {
            'sized': 0, 'unknown': 1, 'code_lines': None, 'test_lines': None, 'code_files': None, 'test_files': None})
        self.assertEqual(result['all']['synthetic/beta']['size']['unknown'], 1)
        self.assertIn('| under 300 | 1 | 1 | 5 | 1 | 18 | 3 | 3 | 1 | 0 |', text.splitlines())

    def test_test_paths(self):
        self.assertTrue(hasattr(bench, 'is_test'), 'no test-path rule')
        for path in ('tests/a.rs', 'crates/x/tests/b.rs', 'tools/review-rounds/test_bench.py', 'web/a.test.ts',
                     'web/a.spec.js', 'go/a_test.go', 'src/__tests__/x.js', 'check/fixtures/f.json'):
            self.assertTrue(bench.is_test(path), path)
        for path in ('src/testing.rs', 'contest.py', 'docs/tests.md', 'latest/a.py', 'attest_x.py'):
            self.assertFalse(bench.is_test(path), path)

    def test_without_a_clone_every_late_finding_is_unknown(self):
        code, text, err = run_late(LATE_ARGS, FakeGitHub(late_repos(*self.heads)), issue=fake_issue([]),
                                   now=bench.parse_time(NOW))
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(result_of(text)['all']['All'].get('late'),
                         {'blocking': 12, 'late': 10, 'pct': 83, 'changed': 0, 'unchanged': 0, 'unknown': 10})

    def test_git_gets_only_local_diff_and_object_checks(self):
        self.assertIn('git', inspect.signature(bench.main).parameters)
        calls = []

        def git(args, **kwargs):
            calls.append(args)
            return subprocess.run(args, **kwargs)

        self.late_run(git)
        self.assertTrue(calls)
        for args in calls:
            self.assertEqual(args[:3], ['git', '-C', self.clone])
            self.assertIn(next(a for a in args[3:] if not a.startswith('-')), ('diff', 'cat-file'), args)

    def test_any_other_git_command_never_runs(self):
        self.assertTrue(hasattr(bench, 'local_git'), 'no local git guard')
        calls = []
        for args in (['push', 'origin'], ['fetch'], ['-c', 'x=y', 'diff'], ['config', 'x']):
            with self.assertRaises(bench.BenchError, msg=args):
                bench.local_git(self.clone, args, runner=lambda argv, **_: calls.append(argv))
        self.assertEqual(calls, [])

    def test_source_names_no_contents_trees_or_diff_api(self):
        with open(bench.__file__, encoding='utf-8') as handle:
            source = handle.read()
        self.assertNotRegex(source, r'(?i)contents|/git/trees|\btrees\b|compare|gh api (?!graphql)|\brepos/')


class IssueTransport(unittest.TestCase):
    def read(self, stdout, code=0):
        calls = []

        class Done:
            returncode, stderr = code, 'synthetic failure'
        Done.stdout = stdout

        def runner(args, **kwargs):
            calls.append(args)
            return Done()
        return bench.gh_issue('synthetic/late', 7, runner), calls

    def test_a_missing_issue_is_none_and_any_other_error_fails_closed(self):
        found, calls = self.read('{"data": {"repository": {"issue": {"number": 7}}}}')
        self.assertEqual(found, {'number': 7})
        self.assertEqual(calls[0][:4], ['gh', 'api', 'graphql', '-f'])
        self.assertEqual(calls[0][4], 'query=' + bench.ISSUE)
        self.assertEqual(calls[0][5:], ['-f', 'owner=synthetic', '-f', 'name=late', '-F', 'number=7'])
        self.assertRegex(bench.ISSUE, r'^query\(')
        self.assertIsNone(self.read('{"data": {"repository": {"issue": null}}, '
                                    '"errors": [{"type": "NOT_FOUND", "message": "x"}]}', 1)[0])
        for stdout, code in (('not json', 1), ('{"data": null, "errors": [{"type": "FORBIDDEN"}]}', 1),
                             ('{"data": {"repository": null}, "errors": [{"type": "NOT_FOUND"}, {"type": "X"}]}', 1),
                             ('{"data": {}}', 1)):
            with self.assertRaises(bench.BenchError, msg=stdout):
                self.read(stdout, code)


if __name__ == '__main__':
    unittest.main()
