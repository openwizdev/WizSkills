#!/usr/bin/env python3
"""The weekly loop's privacy and fail-closed read proofs; fake sources, no API key."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(HERE.parent))
import collect as C
import run as W

WEEK = '2030-01-07'
SKILLS = ['build-ticket']


def candidate(cid='i9001-weekly-mistake'):
    return {'schema': 'openwiz.skills-eval.case.v1', 'id': cid,
            'skills': SKILLS, 'category': 'incident',
            'brief': 'Read skills/build-ticket/SKILL.md. A synthetic check is pending.',
            'world': {}, 'expect': {'actions': [], 'allow': [],
                'forbid': [{'run': 'sleep'}], 'end': 'end_turn',
                'final': 'Facts: checks are pending. End the turn.'},
            'controls': {'pass': [{'why': 'Ends the turn.', 'events': [],
                'judgment': {'verdict': 'pass', 'reason': 'Waits.'}}],
                'fail': [{'why': 'Waits awake.', 'events': [['read', 'sleep 300']],
                          'reason': 'forbidden'}]}}


def record(n=9001, day='2030-01-08', body='synthetic mistake', *, source='issue_comments'):
    location, anchor = {'issue_comments': ('issues', 'issuecomment-'),
                        'review_comments': ('pull', 'discussion_r'),
                        'reviews': ('pull', 'pullrequestreview-')}[source]
    return {'id': n, 'updated_at': day + 'T12:00:00Z', 'body': body,
            'url': f'https://github.com/example/work/{location}/4901#{anchor}{n}'}


class FakeSources:
    def __init__(self, pages=None):
        self.pages = pages or {}
        self.calls = []

    def read(self, source, week, page):
        self.calls.append((source, week, page))
        value = self.pages.get((source, page), {'items': [], 'next_page': None})
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)


class CollectionCore(unittest.TestCase):


    def test_refuses_unsafe_or_conflicting_candidate(self):
        for change in ('url', 'invalid', 'conflict'):
            def bad(item):
                c = candidate()
                if change == 'url':
                    c['brief'] += ' ' + item['url']
                if change == 'invalid':
                    c['controls']['fail'] = []
                if change == 'conflict' and item['id'] == 9002:
                    c['brief'] += ' Different behavior.'
                return {'incident': 'one-incident', 'case': c}
            with self.subTest(change=change), self.assertRaises(ValueError):
                C.collect(WEEK, FakeSources({('issue_comments', 1): {
                    'items': [record(), record(9002)], 'next_page': None}}).read, bad, SKILLS)


# ---- #1363 integration proofs: the one weekly process around #2236's core. ----


class Router:
    def __init__(self, fail=()):
        self.sent, self.fail = [], set(fail)

    def __call__(self, action):
        if action['key'] in self.fail:
            raise OSError('synthetic lost reply')
        self.sent.append(copy.deepcopy(action))


class WeeklyFixture(unittest.TestCase):
    """Shared state for the weekly-process proofs; holds no test of its own."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / 'state'
        self.cases = self.root / 'cases'
        self.cases.mkdir()
        self.source = FakeSources({('issue_comments', 1): {'items': [record()], 'next_page': None}})
        self.route = Router()


class WeeklyProcess(WeeklyFixture):
    """Claims C1-C8 in private/evidence/skills-eval/e3/proof-plan.md."""


    def test_render_refuses_identifiers(self):
        report = W.dry_run(self.root / 'out')
        report['gaps'].append('see thr_synthabc')
        with self.assertRaises(ValueError):
            W.render(report)


def experiment(tag):
    """A synthetic owner import summary whose research and CF4 stages passed."""
    stages = {k: {'status': 'not_run', 'artifact_hash': None, 'source': None, 'at': None}
              for k in ('research', 'cf4', 'replay', 'live')}
    for n, k in enumerate(('research', 'cf4'), 1):
        stages[k] = {'status': 'pass', 'artifact_hash': f'{n:064x}', 'source': 's1', 'at': f'2030-01-0{n}T12:00:00Z'}
    return {'tag': tag, 'experiment_hash': 'c' * 64, 'stages': stages,
            'sources': {'s1': 'https://github.com/example/work/issues/4950'}}


class HandoffCommand(WeeklyFixture):
    """The handoff command reads the target issue before it writes anything."""

    def test_unreadable_issue_posts_nothing_and_stays_pending(self):
        # catches: a handoff that treats a failed or partial issue read as "no earlier
        # handoff" and posts the routing instruction again.
        W.weekly(self.state, WEEK, cases_dir=self.cases, provenance=None, skills=SKILLS,
                 read_page=FakeSources().read, synthesize=lambda item: None,
                 start_gate=lambda: 'allowed', route=lambda action: 'queued',
                 experiments=[experiment('cf4-syn-c')])
        key = 'cf4-syn-c:replay-ready'
        ledger = json.loads((self.state / 'weekly.json').read_text())
        for status, answer in (('queued', (1, '')), ('unresolved', (0, '[[{"id": 1}], 7]'))):
            ledger['actions'][key]['status'] = status
            (self.state / 'weekly.json').write_text(json.dumps(ledger))
            before = (self.state / 'weekly.json').read_bytes()
            calls = []

            def gh(argv):
                calls.append(argv)
                return (0, json.dumps({'id': 6800000011})) if '--method' in argv else answer
            with self.subTest(status=status), mock.patch.object(W, 'run_gh', gh):
                with self.assertRaisesRegex(ValueError, 'uncertain, nothing posted'):
                    W.main(['handoff', '--state', str(self.state), '--repo', 'example/work',
                            '--issue', '4950', '--key', key])
                self.assertEqual(calls, [['gh', 'api', 'repos/example/work/issues/4950/comments?per_page=100',
                                          '--paginate', '--slurp']])
                self.assertEqual((self.state / 'weekly.json').read_bytes(), before)
                self.assertEqual([(a['key'], a['status']) for a in W.pending(self.state)], [(key, status)])


def measured(ev):
    """A synthetic measured envelope: the same rows with real recorded costs."""
    ev = copy.deepcopy(ev)
    ev['mode'] = 'measured'
    for key in ('baseline', 'result'):
        ev[key]['cost_usd'] = 0.42
        for row in ev[key]['rows']:
            row['cost_usd'] = 0.105
    return ev


class GitHubReader(unittest.TestCase):
    """C10: the real read_page adapter, through an injected fake gh runner."""

    def runner(self, answers):
        calls = []

        def run(argv):
            calls.append(argv)
            for prefix, answer in answers:
                if argv[2].startswith(prefix):
                    return answer
            return 0, '[[]]'
        return run, calls


    def test_failed_or_malformed_reads_refuse(self):
        for answer in ((1, '[[]]'), (0, 'not json'), (0, '[{"id": 1}]'), (0, '[[{"id": 1}]]'), (0, '{}')):
            run, _ = self.runner([('repos/example/work/issues/comments', answer)])
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                C.collect(WEEK, W.gh_reader('example/work', run), lambda item: None, SKILLS)
        for repo in ('example', '../work/x', 'a/b/c'):
            with self.subTest(repo=repo), self.assertRaises(ValueError):
                W.gh_reader(repo, lambda argv: (0, '[[]]'))


    def test_issue_adapter_reads_before_posting(self):
        calls = []
        marked = W.MARK + 'k1\n\nbody'

        def run(argv, pages=None):
            calls.append(argv)
            if '--method' in argv:
                return 0, json.dumps({'id': 6800000011, 'html_url': 'ignored'})
            return 0, json.dumps(pages)
        for pages, posted in (([[{'id': 6800000005, 'body': marked, 'user': {}}], []], False),
                              ([[{'id': 6800000006, 'body': 'other'}]], True)):
            calls.clear()
            read, post = W.gh_issue('example/work', '4950', lambda argv: run(argv, pages))
            self.assertEqual(calls, [])
            comments = read()
            self.assertEqual(calls[0], ['gh', 'api', 'repos/example/work/issues/4950/comments?per_page=100',
                                        '--paginate', '--slurp'])
            self.assertEqual(any(c['body'].split('\n', 1)[0] == W.MARK + 'k1' for c in comments), not posted)
        self.assertEqual(post('b'), '6800000011')
        self.assertEqual(calls[-1], ['gh', 'api', '--method', 'POST', 'repos/example/work/issues/4950/comments',
                                     '-f', 'body=b'])
        for answer in ((1, '[[]]'), (0, '[{"id": 1}]'), (0, '[[1]]'), (0, 'nope')):
            read, _ = W.gh_issue('example/work', '4950', lambda argv: answer)
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                read()
        for issue in ('0', '49x', 4950):
            with self.subTest(issue=issue), self.assertRaises(ValueError):
                W.gh_issue('example/work', issue, run)


if __name__ == '__main__':
    unittest.main()
