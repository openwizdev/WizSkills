#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ABOUT = """gh-meter.py through its shim and its report (OpenWiz#2621, FR5 of #2428).

python3 -I skills/launch-fleet/scripts/test-gh-meter.py

Each case installs the shim, puts a fake real `gh` behind it on PATH and runs
the shim as a script would. The fake answers `api rate_limit` with a `used`
that every other call raises by one, so the before and after values are known.
Expected values are literals, never computed the way the meter computes them.
"""

HERE = Path(__file__).resolve().parent
METER = HERE / 'gh-meter.py'
SHA = '0123456789abcdef0123456789abcdef01234567'
SECRETS = ('ghs_SyntheticToken000', 'SYNTHETIC-BODY', 'SYNTHETIC-HEADER', 'SYNTHETIC-ENV', 'SYNTHETIC-OUT',
           'SYNTHETIC-RATE')

FAKE_GH = r'''
import json, os, sys
state = os.environ['FAKE_STATE']
used = int(open(state).read()) if os.path.exists(state) else 100
args = sys.argv[1:]
with open(os.environ['FAKE_CALLS'], 'a') as f:
    f.write(json.dumps(args) + '\n')
if args == ['api', 'rate_limit']:
    if os.environ.get('FAKE_NO_RATE'):
        sys.exit(1)
    print(json.dumps({'resources': {'core': {'used': used, 'remaining': 5000 - used, 'note': 'SYNTHETIC-RATE'},
                                    'graphql': {'used': 7, 'remaining': 4993}}}))
    sys.exit(0)
open(state, 'w').write(str(used + 1))
data = sys.stdin.read() if '--input' in args else ''
if '--include' in args or '-i' in args:
    status = os.environ.get('FAKE_STATUS', '200 OK')
    for page in range(int(os.environ.get('FAKE_PAGES', '1'))):
        print('HTTP/2.0 %s' % status)
        print('X-Oauth-Scopes: repo SYNTHETIC-HEADER')
        print('X-Ratelimit-Used: %d' % used)
        print()
        print('{"out": "SYNTHETIC-OUT"}')
else:
    print('fake out ' + data.strip())
sys.exit(int(os.environ.get('FAKE_EXIT', '0')))
'''


class Meter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        real = self.dir / 'real'
        real.mkdir()
        (real / 'gh').write_text('#!%s\n%s' % (sys.executable, FAKE_GH))
        (real / 'gh').chmod(0o755)
        self.shim = self.dir / 'shim'
        run = subprocess.run([sys.executable, '-I', str(METER), 'install', str(self.shim)],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.log = self.dir / 'meter.jsonl'
        self.env = {'PATH': '%s:%s:%s' % (self.shim, real, os.environ['PATH']), 'GH_METER_LOG': str(self.log),
                    'FAKE_STATE': str(self.dir / 'state'), 'FAKE_CALLS': str(self.dir / 'calls'),
                    'GH_TOKEN': 'SYNTHETIC-ENV'}

    def tearDown(self):
        self.tmp.cleanup()

    def gh(self, *args, stdin='', **env):
        return subprocess.run(['gh', *args], input=stdin, capture_output=True, text=True,
                              env=dict(self.env, **env))

    def lines(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def report(self, *logs):
        return subprocess.run([sys.executable, '-I', str(METER), 'report', *map(str, logs)],
                              capture_output=True, text=True)

    def test_endpoint_templates(self):
        cases = [
            (['api', 'repos/synthetic-owner/synthetic-repo/issues/123/comments?per_page=100&page=2'],
             'GET', 'repos/synthetic-owner/synthetic-repo/issues/:n/comments', 'rest'),
            (['api', '-X', 'PATCH', 'repos/synthetic-owner/synthetic-repo/pulls/45'],
             'PATCH', 'repos/synthetic-owner/synthetic-repo/pulls/:n', 'rest'),
            (['api', '--method=DELETE', '/repos/synthetic-owner/synthetic-repo/issues/comments/9876543210'],
             'DELETE', 'repos/synthetic-owner/synthetic-repo/issues/comments/:n', 'rest'),
            (['api', 'repos/{owner}/{repo}/commits/%s/check-runs' % SHA, '--jq', '.total_count'],
             'GET', 'repos/{owner}/{repo}/commits/:sha/check-runs', 'rest'),
            (['api', 'repos/synthetic-owner/synthetic-repo/commits/0123abc/status'],
             'GET', 'repos/synthetic-owner/synthetic-repo/commits/:sha/status', 'rest'),
            (['api', '-f', 'body=x', 'repos/synthetic-owner/synthetic-repo/issues/7/comments'],
             'POST', 'repos/synthetic-owner/synthetic-repo/issues/:n/comments', 'rest'),
            (['api', '-H', 'Accept: application/json', '--paginate', 'repos/synthetic-owner/synthetic-repo/issues'],
             'GET', 'repos/synthetic-owner/synthetic-repo/issues', 'rest'),
            (['api', 'graphql', '-f', 'query=query { viewer { login } }', '-F', 'n=12'],
             'POST', 'graphql', 'graphql'),
            (['issue', 'view', '12', '--json', 'body'], 'view', 'issue view', 'graphql'),
            (['pr', 'comment', '3', '--body', 'x'], 'comment', 'pr comment', 'graphql'),
            (['run', 'view', '991', '--log-failed'], 'view', 'run view', 'rest'),
            (['-R', 'synthetic-owner/synthetic-repo', 'pr', 'view', '3'], 'view', 'pr view', 'graphql'),
            (['auth', 'status'], 'status', 'auth status', 'none'),
        ]
        for args, *_ in cases:
            self.assertEqual(self.gh(*args).returncode, 0, args)
        got = [(c['method'], c['endpoint'], c['kind']) for c in self.lines()]
        self.assertEqual(got, [tuple(c[1:]) for c in cases])

    def test_role_field(self):
        self.gh('api', 'user', GH_METER_ROLE='reviewer')
        self.gh('api', 'user', GH_METER_ROLE='heartbeat')
        self.gh('api', 'user')
        self.gh('api', 'user', GH_METER_ROLE='synthetic-boss')
        self.assertEqual([c['role'] for c in self.lines()], ['reviewer', 'heartbeat', 'other', 'other'])

    def test_rest_used_before_and_after(self):
        self.gh('api', 'user')
        self.gh('api', 'user')
        self.gh('api', 'user', FAKE_NO_RATE='1')
        self.gh('api', 'user', GH_METER_RATE='0')
        self.assertEqual([(c['rest_used_before'], c['rest_used_after']) for c in self.lines()],
                         [(100, 101), (101, 102), (None, None), (None, None)])
        reads = [json.loads(line) for line in (self.dir / 'calls').read_text().splitlines()]
        self.assertEqual(reads.count(['api', 'user']), 4)
        self.assertEqual(len(self.lines()), 4, 'the meter logs only the caller\'s own calls')

    def test_passes_through_output_input_and_status(self):
        run = self.gh('api', '--input', '-', 'repos/synthetic-owner/synthetic-repo/issues', stdin='{"a": 1}\n',
                      FAKE_EXIT='3')
        self.assertEqual((run.returncode, run.stdout), (3, 'fake out {"a": 1}\n'))
        line, = self.lines()
        self.assertEqual((line['method'], line['exit']), ('POST', 3))
        included = self.gh('api', '-i', 'user')
        self.assertEqual(included.stdout.splitlines()[0], 'HTTP/2.0 200 OK')

    def test_rest_units(self):
        self.gh('api', 'user')
        self.gh('api', '--include', 'user', FAKE_STATUS='304 Not Modified')
        self.gh('api', '--include', '--paginate', 'repos/synthetic-owner/synthetic-repo/issues', FAKE_PAGES='3')
        self.gh('api', 'graphql', '-f', 'query=x')
        self.gh('api', 'rate_limit')
        self.gh('auth', 'token')
        self.assertEqual([c['rest_units'] for c in self.lines()], [1, 0, 3, 0, 0, 0])

    def test_never_logs_a_token_body_or_other_header(self):
        self.gh('api', '-H', 'Authorization: token ghs_SyntheticToken000', '-f', 'body=SYNTHETIC-BODY',
                'repos/synthetic-owner/synthetic-repo/issues/1/comments?access_token=ghs_SyntheticToken000')
        self.gh('api', '--include', '--input', '-', 'repos/synthetic-owner/synthetic-repo/issues',
                stdin='{"body": "SYNTHETIC-BODY"}')
        self.gh('issue', 'comment', '1', '--body', 'SYNTHETIC-BODY')
        self.gh('api', 'graphql', '-f', 'query=mutation { x(body: "SYNTHETIC-BODY") }')
        text = self.log.read_text()
        for secret in SECRETS:
            self.assertNotIn(secret, text)
        allowed = {'time', 'role', 'method', 'endpoint', 'kind', 'rest_used_before', 'rest_used_after',
                   'rest_units', 'exit'}
        for line in self.lines():
            self.assertLessEqual(set(line), allowed | {'status'})

    def test_report_per_role_per_endpoint_and_top_five(self):
        calls = [('fleet', 'repos/o/r/issues/1/comments', 6), ('fleet', 'repos/o/r/issues/2', 5),
                 ('builder', 'repos/o/r/pulls/3', 4), ('reviewer', 'repos/o/r/commits/%s/status' % SHA, 3),
                 ('orchestrator', 'repos/o/r/git/ref/heads/main', 2), ('heartbeat', 'user', 1)]
        for role, endpoint, n in calls:
            for _ in range(n):
                self.gh('api', endpoint, GH_METER_ROLE=role)
        for _ in range(9):
            self.gh('api', 'graphql', '-f', 'query=x', GH_METER_ROLE='fleet')
        half = self.lines()
        first, second = self.dir / 'a.jsonl', self.dir / 'b.jsonl'
        first.write_text(''.join(json.dumps(c) + '\n' for c in half[:10]))
        second.write_text(''.join(json.dumps(c) + '\n' for c in half[10:]))
        run = self.report(first, second)
        self.assertEqual(run.returncode, 0, run.stderr)
        out = run.stdout
        top = out[out.index('Top five endpoints by REST units'):].splitlines()[1:6]
        self.assertEqual(top, [
            '1. GET repos/o/r/issues/:n/comments: 6 units, 6 calls',
            '2. GET repos/o/r/issues/:n: 5 units, 5 calls',
            '3. GET repos/o/r/pulls/:n: 4 units, 4 calls',
            '4. GET repos/o/r/commits/:sha/status: 3 units, 3 calls',
            '5. GET repos/o/r/git/ref/heads/main: 2 units, 2 calls',
        ])
        self.assertIn('| fleet | 20 | 11 | 9 | 11 | 20 |', out)
        self.assertIn('| heartbeat | 1 | 1 | 0 | 1 | 1 |', out)
        self.assertIn('| POST | graphql | graphql | 9 | 0 |', out)
        self.assertIn('Total: 30 calls, 21 REST units, 9 GraphQL calls', out)

    def test_report_refuses_a_bad_log(self):
        good = {'time': '2026-01-01T00:00:00Z', 'role': 'fleet', 'method': 'GET', 'endpoint': 'user',
                'kind': 'rest', 'exit': 0, 'rest_units': 1, 'rest_used_before': None, 'rest_used_after': None}
        ok = self.dir / 'ok.jsonl'
        ok.write_text(json.dumps(good) + '\n')
        self.assertEqual(self.report(ok).returncode, 0)
        bad = ['not json', '[]', json.dumps(dict(good, role='boss')), json.dumps(dict(good, kind='soap')),
               json.dumps(dict(good, rest_units='1')), json.dumps(dict(good, rest_units=True)),
               json.dumps(dict(good, rest_units=-1)), json.dumps(dict(good, rest_used_before='5')),
               json.dumps(dict(good, endpoint=7)), json.dumps(dict(good, extra=1)),
               json.dumps({k: v for k, v in good.items() if k != 'method'}),
               json.dumps(good)[:-1] + ', "role": "builder"}']
        for i, text in enumerate(bad):
            path = self.dir / ('bad%d.jsonl' % i)
            path.write_text(json.dumps(good) + '\n' + text + '\n')
            run = self.report(path)
            self.assertEqual((run.returncode, run.stdout), (2, ''), text)
        self.assertEqual(self.report(self.dir / 'missing.jsonl').returncode, 2)

    def test_install_refuses_a_quote_in_the_path(self):
        run = subprocess.run([sys.executable, '-I', str(METER), 'install', str(self.dir / "it's")],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 2)

    def test_no_log_is_a_plain_pass_through(self):
        env = dict(self.env)
        del env['GH_METER_LOG']
        run = subprocess.run(['gh', 'api', 'user'], capture_output=True, text=True, env=env)
        self.assertEqual((run.returncode, run.stdout), (0, 'fake out \n'))
        self.assertFalse(self.log.exists())
        reads = (self.dir / 'calls').read_text().splitlines()
        self.assertEqual(reads, ['["api", "user"]'])


    def counting_wrapper(self, name):
        d = self.dir / name
        d.mkdir()
        count = self.dir / (name + '.count')
        (d / 'gh').write_text('#!/bin/sh\necho . >> "%s"\n[ "$(wc -l < "%s")" -le 3 ] || exit 99\n'
                              'exec "%s" "$@"\n' % (count, count, self.shim / 'gh'))
        (d / 'gh').chmod(0o755)
        return d, count

    def test_a_wrapper_before_the_shim_that_calls_it_back_reaches_the_real_gh_once(self):
        wrapper, count = self.counting_wrapper('before')
        run = self.gh('api', 'user', PATH='%s:%s' % (wrapper, self.env['PATH']))
        self.assertEqual((run.returncode, run.stdout), (0, 'fake out \n'))
        self.assertEqual(count.read_text(), '.\n')
        self.assertEqual((self.dir / 'calls').read_text().splitlines(),
                         ['["api", "rate_limit"]', '["api", "user"]', '["api", "rate_limit"]'])
        self.assertEqual([(c['endpoint'], c['exit']) for c in self.lines()], [('user', 0)])

    def test_a_shim_whose_dir_is_not_on_path_refuses_and_runs_no_gh(self):
        run = subprocess.run([str(self.shim / 'gh'), 'api', 'user'], capture_output=True, text=True,
                             env=dict(self.env, PATH=self.env['PATH'].split(':', 1)[1]))
        self.assertEqual((run.returncode, run.stdout), (127, ''))
        self.assertIn("the shim's directory is not on PATH", run.stderr)
        self.assertFalse((self.dir / 'calls').exists())

    def test_a_wrapper_after_the_shim_that_calls_it_back_is_refused_at_the_second_entry(self):
        wrapper, count = self.counting_wrapper('after')
        shim, rest = self.env['PATH'].split(':', 1)
        run = self.gh('api', 'user', PATH='%s:%s:%s' % (shim, wrapper, rest), GH_METER_RATE='0')
        self.assertEqual(run.returncode, 127)
        self.assertIn('the shim called itself', run.stderr)
        self.assertEqual(count.read_text(), '.\n')
        self.assertFalse((self.dir / 'calls').exists())


if __name__ == '__main__':
    unittest.main()
