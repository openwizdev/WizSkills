#!/usr/bin/env python3
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
BUDGET = HERE / 'budget.py'
NOW = 1900000000
RESET = NOW + 1800
SECRET = 'synthetic-secret-marker-7f3a'

FAKE_GH = r'''
import json, os, sys
with open(os.environ['FAKE_LOG'], 'a') as log:
    log.write(json.dumps(sys.argv[1:]) + '\n')
world = json.load(open(os.environ['FAKE_WORLD']))
if world.get('fail'):
    print('gh: synthetic failure', file=sys.stderr)
    sys.exit(1)
sys.stdout.write(world['out'])
'''


def headers(limit=5000, remaining=4000, reset=RESET, resource='core', status='200 OK',
            drop=(), extra='', body='{"synthetic": true}\n'):
    rows = [('X-Ratelimit-Limit', limit), ('X-Ratelimit-Remaining', remaining),
            ('X-Ratelimit-Reset', reset), ('X-Ratelimit-Resource', resource),
            ('X-Ratelimit-Used', None)]
    lines = ['HTTP/2.0 %s' % status, 'Content-Type: application/json; charset=utf-8']
    for name, value in rows:
        if name.lower() in drop:
            continue
        if name == 'X-Ratelimit-Used':
            value = limit - remaining if isinstance(limit, int) and isinstance(remaining, int) else 0
        lines.append('%s: %s' % (name, value))
    return '\r\n'.join(lines) + '\r\n' + extra + '\r\n' + body


def rate_limit(limit=5000, remaining=4000, reset=RESET, core=True, graphql_remaining=4500, graphql=True):
    pool = {'limit': limit, 'remaining': remaining, 'reset': reset,
            'used': 0, 'resource': 'core'}
    points = {'limit': 5000, 'remaining': graphql_remaining, 'reset': RESET + 60,
              'used': 0, 'resource': 'graphql'}
    resources = {'graphql': points} if graphql else {}
    if core:
        resources['core'] = pool
    return json.dumps({'resources': resources, 'rate': pool}) + '\n'


class Budget(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        bin_dir = self.tmp / 'bin'
        bin_dir.mkdir()
        gh = bin_dir / 'gh'
        gh.write_text('#!%s\n%s' % (sys.executable, FAKE_GH), encoding='utf-8')
        gh.chmod(0o755)
        self.log = self.tmp / 'gh.log'
        self.world = self.tmp / 'world.json'
        self.gh_world(out=rate_limit())
        self.env = {'PATH': '%s:/usr/bin:/bin' % bin_dir, 'HOME': str(self.tmp),
                    'FAKE_LOG': str(self.log), 'FAKE_WORLD': str(self.world),
                    'LAUNCH_FLEET_NOW': str(NOW)}

    def gh_world(self, **world):
        self.world.write_text(json.dumps(world), encoding='utf-8')

    def file(self, text, name='h.txt'):
        path = self.tmp / name
        path.write_text(text, encoding='utf-8')
        return str(path)

    def admit(self, *args):
        result = subprocess.run([sys.executable, '-I', str(BUDGET), 'admit', *map(str, args)],
                                env=self.env, capture_output=True, text=True, timeout=60)
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        return result

    def asked(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def decision(self, result, code):
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 1, result.stdout)
        answer = json.loads(lines[0])
        self.assertEqual(sorted(answer), ['allowed', 'limit', 'reason', 'remaining', 'reset', 'resource'])
        self.assertIn(answer['resource'], ('core', 'graphql', None))
        self.assertIs(answer['allowed'], code == 0)
        self.assertIsInstance(answer['reason'], str)
        self.assertTrue(answer['reason'])
        return answer

    def test_plenty_admits(self):
        answer = self.decision(self.admit(10, self.file(headers())), 0)
        self.assertEqual((answer['remaining'], answer['limit'], answer['reset']), (4000, 5000, RESET))
        self.assertEqual(answer['resource'], 'core')
        self.assertEqual(self.asked(), [])

    def test_at_the_1500_floor_admits_and_one_more_backs_off(self):
        path = self.file(headers(remaining=1510))
        self.decision(self.admit(10, path), 0)
        answer = self.decision(self.admit(11, path), 1)
        self.assertEqual((answer['remaining'], answer['limit'], answer['reset']), (1510, 5000, RESET))
        self.assertIn('2030-03-17T18:16:40Z', answer['reason'])
        self.assertIn('1500', answer['reason'])

    def test_a_quarter_above_the_floor_is_kept_whole(self):
        self.decision(self.admit(1, self.file(headers(limit=15001, remaining=3752))), 0)
        self.decision(self.admit(2, self.file(headers(limit=15001, remaining=3752))), 1)

    def test_floor_overrides_the_1500(self):
        path = self.file(headers(remaining=1300))
        self.decision(self.admit(10, path), 1)
        self.decision(self.admit(10, '--floor', 500, path), 0)
        self.decision(self.admit(41, '--floor', 500, path), 1)
        self.decision(self.admit(1, '--floor', 2000, self.file(headers(remaining=1990), 'b.txt')), 1)
        self.decision(self.admit(1, '--floor', 0, path), 0)
        for bad in ('-1', 'ten', ''):
            with self.subTest(bad):
                result = self.admit(1, '--floor', bad, path)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(result.stdout, '')

    def test_empty_backs_off_until_the_reset(self):
        answer = self.decision(self.admit(1, self.file(headers(remaining=0, status='403 Forbidden'))), 1)
        self.assertEqual(answer['remaining'], 0)
        self.assertIn('2030-03-17T18:16:40Z', answer['reason'])

    def test_graphql_headers_are_read_as_graphql(self):
        answer = self.decision(self.admit(1, self.file(headers(resource='graphql', remaining=3000))), 0)
        self.assertEqual((answer['resource'], answer['remaining']), ('graphql', 3000))
        answer = self.decision(self.admit(1, self.file(headers(resource='graphql', remaining=1500))), 1)
        self.assertEqual(answer['resource'], 'graphql')

    def test_another_resource_is_unknown(self):
        answer = self.decision(self.admit(1, self.file(headers(resource='search'))), 2)
        self.assertIn('search', answer['reason'])

    def test_core_and_graphql_answers_together_are_unknown(self):
        core = self.file(headers(), 'core.txt')
        points = self.file(headers(resource='graphql'), 'points.txt')
        self.decision(self.admit(1, core, points), 2)
        self.decision(self.admit(1, '--resource', 'core', points), 2)
        self.assertEqual(self.decision(self.admit(1, '--resource', 'graphql', points), 0)['resource'], 'graphql')

    def test_missing_headers_are_unknown(self):
        for name in ('x-ratelimit-limit', 'x-ratelimit-remaining', 'x-ratelimit-reset', 'x-ratelimit-resource'):
            with self.subTest(name):
                self.decision(self.admit(1, self.file(headers(drop=(name,)))), 2)
        self.decision(self.admit(1, self.file('')), 2)
        self.decision(self.admit(1, self.file('{"synthetic": true}\n')), 2)
        self.assertEqual(self.asked(), [])

    def test_malformed_or_contradictory_headers_are_unknown(self):
        cases = {
            'word': headers(remaining='many'),
            'negative': headers(remaining=-1),
            'above the limit': headers(limit=5000, remaining=5001),
            'zero limit': headers(limit=0, remaining=0),
            'duplicate': headers(extra='X-Ratelimit-Remaining: 3999\r\n'),
        }
        for name, text in cases.items():
            with self.subTest(name):
                self.decision(self.admit(1, self.file(text)), 2)

    def test_the_newest_answer_decides_whatever_the_order(self):
        old = self.file(headers(remaining=4000, reset=RESET - 3600), 'old.txt')
        early = self.file(headers(remaining=3000), 'early.txt')
        late = self.file(headers(remaining=1255), 'late.txt')
        for n, order in enumerate(([old, early, late], [late, early, old], [early, late, old])):
            with self.subTest(order=n):
                answer = self.decision(self.admit(10, *order), 1)
                self.assertEqual(answer['remaining'], 1255)

    def test_resets_a_second_apart_are_one_window(self):
        older = self.file(headers(remaining=3000, reset=RESET + 1), 'older.txt')
        newer = self.file(headers(remaining=1255, reset=RESET), 'newer.txt')
        self.assertEqual(self.decision(self.admit(10, older, newer), 1)['remaining'], 1255)

    def test_every_page_of_a_paginated_answer_counts(self):
        pages = headers(remaining=3000) + headers(remaining=1255)
        self.assertEqual(self.decision(self.admit(10, self.file(pages)), 1)['remaining'], 1255)

    def test_one_unknown_answer_makes_the_batch_unknown(self):
        good = self.file(headers(), 'good.txt')
        bad = self.file(headers(drop=('x-ratelimit-reset',)), 'bad.txt')
        self.decision(self.admit(1, good, bad), 2)
        self.decision(self.admit(1, good, str(self.tmp / 'absent.txt')), 2)
        windows = self.file(headers(limit=5000, remaining=3000) + headers(limit=15000, remaining=3000))
        self.decision(self.admit(1, windows), 2)

    def test_never_prints_a_token_or_a_body(self):
        text = headers(remaining='bad', extra='Authorization: token %s\r\n' % SECRET, body=SECRET + '\n')
        self.decision(self.admit(1, self.file(text)), 2)
        self.gh_world(out='{"message": "%s"}\n' % SECRET)
        self.decision(self.admit(1), 2)

    def test_without_headers_it_reads_rate_limit(self):
        answer = self.decision(self.admit(10), 0)
        self.assertEqual((answer['remaining'], answer['limit'], answer['reset']), (4000, 5000, RESET))
        self.assertEqual(self.asked(), [['api', 'rate_limit']])
        self.gh_world(out=rate_limit(remaining=1255))
        self.decision(self.admit(10), 1)
        self.gh_world(out=rate_limit(remaining=0))
        self.decision(self.admit(1), 1)

    def test_rate_limit_gives_the_graphql_pool_when_asked(self):
        answer = self.decision(self.admit(10, '--resource', 'graphql'), 0)
        self.assertEqual((answer['resource'], answer['remaining'], answer['reset']), ('graphql', 4500, RESET + 60))
        self.gh_world(out=rate_limit(graphql_remaining=1505))
        self.decision(self.admit(10, '--resource', 'graphql'), 1)
        self.gh_world(out=rate_limit(graphql=False))
        self.decision(self.admit(1, '--resource', 'graphql'), 2)
        self.assertEqual(self.decision(self.admit(1), 0)['resource'], 'core')
        result = self.admit(1, '--resource', 'search')
        self.assertEqual((result.returncode, result.stdout), (2, ''))

    def test_an_unreadable_rate_limit_is_unknown(self):
        cases = {
            'gh fails': {'fail': True},
            'not json': {'out': 'synthetic\n'},
            'no core': {'out': rate_limit(core=False)},
            'a word': {'out': rate_limit(remaining='many')},
            'a quoted number': {'out': rate_limit(remaining='4000')},
            'a true': {'out': rate_limit(remaining=True)},
            'above the limit': {'out': rate_limit(remaining=6000)},
            'nothing': {'out': ''},
        }
        for name, world in cases.items():
            with self.subTest(name):
                self.gh_world(**world)
                self.decision(self.admit(1), 2)

    def test_headers_past_their_reset_read_rate_limit_again(self):
        stale = self.file(headers(remaining=0, reset=NOW - 1))
        self.assertEqual(self.decision(self.admit(1, stale), 0)['remaining'], 4000)
        self.assertEqual(self.asked(), [['api', 'rate_limit']])
        self.gh_world(fail=True)
        self.decision(self.admit(1, stale), 2)
        self.gh_world(out=rate_limit(remaining=0))
        points = self.file(headers(resource='graphql', remaining=0, reset=NOW - 1), 'points.txt')
        answer = self.decision(self.admit(1, points), 0)
        self.assertEqual((answer['resource'], answer['remaining']), ('graphql', 4500))

    def test_a_bad_batch_size_is_refused(self):
        path = self.file(headers())
        for n in ('0', '-1', 'ten', ''):
            with self.subTest(n):
                result = self.admit(n, path)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(result.stdout, '')
        result = subprocess.run([sys.executable, '-I', str(BUDGET)], env=self.env,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 2)


if __name__ == '__main__':
    unittest.main()
