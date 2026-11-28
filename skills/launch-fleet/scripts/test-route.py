#!/usr/bin/env python3
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
HOME = 'synthetic-org/project'
SAT = 'synthetic-org/skills'

FAKE_GH = r'''
import json, os, re, sys
world = json.load(open(os.environ['FAKE_WORLD']))
with open(os.environ['FAKE_LOG'], 'a') as log:
    log.write(json.dumps(sys.argv[1:]) + '\n')
if sys.argv[1:3] != ['api', 'graphql'] or world.get('fail'):
    print('gh: synthetic failure', file=sys.stderr)
    sys.exit(1)
fields = dict(a.split('=', 1) for a in sys.argv[3:] if '=' in a)
if '%s/%s' % (fields.get('o'), fields.get('n')) != world['repo']:
    print('gh: wrong repository', file=sys.stderr)
    sys.exit(1)
query = ' '.join(fields.get('query', '').split())
outer = re.fullmatch(
    r'query\s*\(\s*\$o\s*:\s*String!\s*,?\s*\$n\s*:\s*String!\s*\)\s*'
    r'\{\s*repository\s*\(\s*owner\s*:\s*\$o\s*,?\s*name\s*:\s*\$n\s*\)\s*\{\s*(.+?)\s*\}\s*\}',
    query)
if not outer:
    print('GraphQL: invalid query envelope', file=sys.stderr)
    sys.exit(1)
item_re = re.compile(
    r'([A-Za-z_][A-Za-z0-9_]*)\s*:\s*issueOrPullRequest\s*\(\s*number\s*:\s*([1-9][0-9]*)\s*\)\s*\{'
    r'\s*__typename\s+\.\.\.\s*on\s+PullRequest\s*\{'
    r'\s*closingIssuesReferences\s*\(\s*first\s*:\s*([1-9][0-9]*)\s*\)\s*\{'
    r'\s*pageInfo\s*\{\s*hasNextPage\s*\}\s*'
    r'nodes\s*\{\s*number\s+repository\s*\{\s*nameWithOwner\s*\}\s*\}\s*'
    r'\}\s*\}\s*\}\s*')
pos, body, asked, seen = 0, outer.group(1), [], set()
while pos < len(body):
    m = item_re.match(body, pos)
    if not m or m.group(1) in seen or int(m.group(3)) > 100:
        print('GraphQL: invalid closing-reference selection', file=sys.stderr)
        sys.exit(1)
    seen.add(m.group(1))
    asked.append((m.group(1), int(m.group(2))))
    pos = m.end()
if not asked:
    print('GraphQL: empty selection', file=sys.stderr)
    sys.exit(1)
items, errors = {}, []
for alias, number in asked:
    item = world['items'].get(str(number))
    items[alias] = item
    if item is None:
        errors.append({'type': 'NOT_FOUND', 'path': ['repository', alias]})
if world.get('error'):
    errors.append({'type': world['error'], 'message': 'synthetic %s' % world['error']})
print(json.dumps({'data': {'repository': items}, **({'errors': errors} if errors else {})}))
sys.exit(1 if errors else 0)
'''


FAKE_FLEET = r'''python3 -I -c '
import json, os, sys
w = json.load(open(os.environ["FAKE_WORLD"]))
open(os.environ["FAKE_LOG"], "a").write(json.dumps(["fleet.sh"] + sys.argv[1:]) + "\n")
for line in w.get("fleet_lines", []):
    print(line)
if w.get("fleet_code"):
    print("fleet.sh: synthetic refusal", file=sys.stderr)
sys.exit(w.get("fleet_code", 0))
' "$@"
'''


def pr(*closes, more=False):
    return {'__typename': 'PullRequest', 'closingIssuesReferences': {
        'pageInfo': {'hasNextPage': more},
        'nodes': [{'number': int(c.split('#')[1]), 'repository': {'nameWithOwner': c.split('#')[0]}}
                  for c in closes]}}


ISSUE = {'__typename': 'Issue'}


class World:
    def __init__(self, test, repo=SAT, items=None, fail=False, error=None):
        self.dir = Path(tempfile.mkdtemp())
        test.addCleanup(subprocess.run, ['rm', '-rf', str(self.dir)])
        (self.dir / 'bin').mkdir()
        gh = self.dir / 'bin/gh'
        gh.write_text('#!/bin/sh\nexec "%s" -I "%s" "$@"\n' % (sys.executable, self.dir / 'fake_gh.py'))
        gh.chmod(0o755)
        (self.dir / 'fake_gh.py').write_text(FAKE_GH)
        self.world = {'repo': repo, 'items': items or {}, 'fail': fail, 'error': error}
        (self.dir / 'world.json').write_text(json.dumps(self.world))
        self.log = self.dir / 'calls.log'
        self.log.write_text('')
        fleet = self.dir / 'bin/fleet.sh'
        fleet.write_text(FAKE_FLEET)
        self.env = dict(os.environ, PATH='%s:%s' % (self.dir / 'bin', os.environ['PATH']),
                        FAKE_WORLD=str(self.dir / 'world.json'), FAKE_LOG=str(self.log), GH_REPO=HOME,
                        ROUTE_FLEET_SH=str(fleet))

    def fleet(self, lines=(), code=0):
        self.world.update(fleet_lines=list(lines), fleet_code=code)

    def run(self, *args, env=None):
        (self.dir / 'world.json').write_text(json.dumps(self.world))
        r = subprocess.run([sys.executable, '-I', str(HERE / 'route.py'), *args], capture_output=True, text=True,
                           env=dict(self.env, **(env or {})), cwd=self.dir, timeout=60)
        return r.returncode, r.stdout, r.stderr

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def loops(self, value):
        path = self.dir / ('loops-%d.json' % len(list(self.dir.glob('loops-*.json'))))
        path.write_text(value if isinstance(value, str) else json.dumps(value))
        return str(path)


class Refs(unittest.TestCase):
    def test_a_satellite_pull_request_names_the_project_ticket_it_closes(self):
        w = World(self, items={'29': pr(HOME + '#1183')})
        self.assertEqual(w.run('refs', SAT, '29'), (0, '1183\n', ''))
        self.assertEqual(len(w.calls()), 1)

    def test_only_the_project_s_tickets_are_named_once_each_in_order(self):
        w = World(self, items={'7': pr(HOME + '#40', 'synthetic-org/other#41', SAT + '#3', HOME + '#12'),
                               '8': pr(HOME + '#12')})
        self.assertEqual(w.run('refs', SAT, '8', '7', '8'), (0, '12 40\n', ''))
        self.assertEqual(len(w.calls()), 1, 'one batched read for every number')

    def test_issues_unknown_numbers_and_unlinked_pull_requests_name_nothing(self):
        w = World(self, items={'5': ISSUE, '6': pr()})
        self.assertEqual(w.run('refs', SAT, '5', '6', '404'), (0, '', ''))

    def test_the_project_s_own_numbers_pass_through_unread(self):
        w = World(self, repo=HOME)
        self.assertEqual(w.run('refs', HOME, '31', '12', '31'), (0, '12 31\n', ''))
        self.assertEqual(w.calls(), [])

    def test_a_partial_or_failed_read_is_never_a_quiet_nothing(self):
        for world, reason in ((World(self, items={'9': pr(HOME + '#1', more=True)}), 'more than one page'),
                              (World(self, fail=True), 'synthetic failure'),
                              (World(self, items={'9': pr(HOME + '#1')}, error='FORBIDDEN'), 'FORBIDDEN')):
            code, out, err = world.run('refs', SAT, '9')
            self.assertEqual((code, out), (2, ''))
            self.assertIn(reason, err)

    def test_bad_arguments_are_refused_before_any_read(self):
        w = World(self)
        for args in (('refs', SAT), ('refs', 'not a repo', '1'), ('refs', SAT, '-1'), ('refs', SAT, '1x'),
                     ('refs', SAT, '0'), ('refs', 'a/b/c', '1'), ('nope',)):
            self.assertEqual(w.run(*args)[:2], (2, ''), args)
        self.assertEqual(w.run('refs', SAT, '1', env={'GH_REPO': ''})[:2], (2, ''))
        self.assertEqual(w.calls(), [])

    def test_the_fake_checks_the_closing_reference_query_and_answers_its_aliases(self):
        w = World(self, items={'29': pr(HOME + '#1183')})
        owner, name = SAT.split('/')
        ask = lambda q: subprocess.run([str(w.dir / 'bin/gh'), 'api', 'graphql', '-f', 'query=' + q,
                                        '-f', 'o=' + owner, '-f', 'n=' + name],
                                       capture_output=True, text=True, env=w.env, timeout=60)
        sel = '{ __typename ... on PullRequest { closingIssuesReferences(first: 50) { pageInfo { hasNextPage } nodes { number repository { nameWithOwner } } } } }'
        good = 'query($o: String!, $n: String!) { repository(owner: $o, name: $n) { p29: issueOrPullRequest(number: 29) %s p404: issueOrPullRequest(number: 404) %s } }' % (sel, sel)
        r = ask(good)
        self.assertEqual(r.returncode, 1, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(sorted(data['data']['repository']), ['p29', 'p404'])
        self.assertEqual(data['data']['repository']['p29'], pr(HOME + '#1183'))
        self.assertEqual(data['errors'], [{'type': 'NOT_FOUND', 'path': ['repository', 'p404']}])
        for kind, bad in (
                ('nonexistent field', good.replace('closingIssuesReferences', 'closingIssues')),
                ('bad subfield', good.replace('nameWithOwner', 'unknownField')),
                ('bad envelope', 'query { repository(owner: "a", name: "b") { p29: issueOrPullRequest(number: 29) %s } }' % sel)):
            with self.subTest(kind=kind):
                r = ask(bad)
                self.assertEqual((r.returncode, r.stdout), (1, ''), kind)
                self.assertIn('GraphQL:', r.stderr)


class Loop(unittest.TestCase):
    ID = '0f1e2d3c-synthetic-loop'

    def test_a_handle_resolves_to_its_spec_s_loop_id(self):
        w = World(self)
        path = w.loops({'repo': HOME, 'loops': {'10': self.ID, '40': 'other-synthetic-loop'}})
        self.assertEqual(w.run('loop', path, '10'), (0, self.ID + '\n', ''))
        self.assertEqual(w.calls(), [], 'the private map is read from disk only')

    def test_a_missing_handle_prints_nothing_and_exits_cleanly(self):
        w = World(self)
        cases = {
            'no file': str(w.dir / 'absent.json'),
            'no key': w.loops({'repo': HOME, 'loops': {'40': self.ID}}),
            'another repository': w.loops({'repo': SAT, 'loops': {'10': self.ID}}),
            'not JSON': w.loops('{"repo": '),
            'no loops object': w.loops({'repo': HOME, 'loops': [self.ID]}),
            'a flag for an id': w.loops({'repo': HOME, 'loops': {'10': '--all'}}),
            'a space in the id': w.loops({'repo': HOME, 'loops': {'10': 'a b'}}),
            'not a string': w.loops({'repo': HOME, 'loops': {'10': 7}}),
        }
        for name, path in cases.items():
            self.assertEqual(w.run('loop', path, '10'), (0, '', ''), name)

    def test_a_malformed_spec_number_is_refused(self):
        w = World(self)
        path = w.loops({'repo': HOME, 'loops': {'10': self.ID}})
        for s in ('', '-10', '10 40', 'S'):
            self.assertEqual(w.run('loop', path, s)[:2], (2, ''), s)


class Tick(unittest.TestCase):
    ID = '0f1e2d3c-synthetic-loop'

    def world(self, **kw):
        w = World(self, **kw)
        return w, w.loops({'repo': HOME, 'loops': {'10': self.ID}})

    def test_a_satellite_message_runs_its_spec_s_loop(self):
        w, path = self.world(items={'29': pr(HOME + '#13')})
        w.fleet(['wake fleet #10: room-cli loop run fleet-10'])
        self.assertEqual(w.run('tick', SAT, path, '29'), (0, 'wake fleet #10: room-cli loop run %s\n' % self.ID, ''))
        self.assertEqual([c for c in w.calls() if c[0] == 'fleet.sh'], [['fleet.sh', 'wake', '13']])

    def test_a_missing_handle_is_reported_privately_and_writes_nothing(self):
        w, _ = self.world(items={'29': pr(HOME + '#13')})
        w.fleet(['wake fleet #10: room-cli loop run fleet-10'])
        for path in (str(w.dir / 'absent.json'), w.loops({'repo': HOME, 'loops': {}})):
            self.assertEqual(w.run('tick', SAT, path, '29'), (0, 'wake fleet #10: unresolved\n', ''))
        gh = [c for c in w.calls() if c[0] != 'fleet.sh']
        self.assertTrue(gh and all(c[:2] == ['api', 'graphql'] and 'mutation' not in ' '.join(c) for c in gh), gh)

    def test_a_group_with_no_project_ticket_ends_quietly(self):
        w, path = self.world(items={'5': ISSUE, '6': pr(SAT + '#2')})
        self.assertEqual(w.run('tick', SAT, path, '5', '6'), (0, '', ''))
        self.assertEqual([c for c in w.calls() if c[0] == 'fleet.sh'], [])

    def test_the_project_s_own_numbers_go_straight_to_wake(self):
        w, path = self.world(repo=HOME)
        w.fleet(['start #41: G1: gadget model (spec #40)', 'wake fleet #10: room-cli loop run fleet-10'])
        self.assertEqual(w.run('tick', HOME, path, '41', '13'),
                         (0, 'start #41: G1: gadget model (spec #40)\nwake fleet #10: room-cli loop run %s\n' % self.ID,
                          ''))
        self.assertEqual(w.calls(), [['fleet.sh', 'wake', '13', '41']])

    def test_a_failed_lookup_or_wake_is_a_failure(self):
        w, path = self.world(fail=True)
        code, out, err = w.run('tick', SAT, path, '29')
        self.assertEqual((code, out), (2, ''))
        self.assertEqual([c for c in w.calls() if c[0] == 'fleet.sh'], [])
        w, path = self.world(repo=HOME)
        w.fleet(code=2)
        code, out, err = w.run('tick', HOME, path, '13')
        self.assertEqual((code, out), (2, ''))
        self.assertIn('synthetic refusal', err)


class Setup(unittest.TestCase):
    def test_the_webhook_address_never_touches_a_file_or_an_argument(self):
        skill = HERE.parent
        text = '\n'.join(p.read_text() for p in sorted(skill.rglob('*.md')))
        self.assertFalse('launch-fleet-wakes.json' in text, 'a setup step saves the address to a file')
        commands, block, cur = [], False, ''
        for line in text.splitlines():
            if line.strip().startswith('```'):
                block = not block
                continue
            if block:
                cur += line.strip()
                if not cur.endswith('\\'):
                    commands.append(cur)
                    cur = ''
                else:
                    cur = cur[:-1] + ' '
        risky = [c for c in commands if ('loop create' in c and '--webhook' in c) or 'loop hook' in c]
        self.assertGreaterEqual(len(risky), 2, 'the wake loop is created and its address issued in the setup')
        for c in risky:
            head, tail = re.sub(r'<[^<>]*>', 'X', c).split('room-cli loop', 1)
            self.assertNotRegex(head, r"(\$\(|`|=)\s*$", c)
            self.assertRegex(tail, r"\|\s*jq ", c)
            self.assertNotRegex(tail, r"(^|[^|&])>|\btee\b|--slurpfile|--rawfile", c)
        for c in commands:
            if 'loop hook' in c:
                self.assertRegex(re.sub(r'<[^<>]*>', 'X', c), r"\|\s*python3 -I \"X/scripts/route\.py\" gh api --method (POST|PATCH) '?repos/[^ ]+/hooks(/X)?'? --input -", c)
            if 'loop create' in c and '--webhook' in c:
                self.assertIn('| jq -r .id', c)



ADDRESS = 'https://synthetic.invalid/wake/SYNTHETIC-ADDRESS-0000'
TRACING = {'GH_DEBUG': 'api', 'DEBUG': 'api', 'GODEBUG': 'http2debug=2', 'SYNTHETIC_FUTURE_TRACE': '1'}


def documented_hook_calls():
    text = (HERE.parent / 'references/launch.md').read_text()
    fenced = [b.replace('\\\n', ' ') for b in re.findall(r'```sh\n(.*?)```', text, re.S)]
    spans = re.findall(r'`([^`\n]*gh api[^`\n]*)`', re.sub(r'```.*?```', '', text, flags=re.S))
    calls = [' '.join(c.split()) for c in fenced + spans if 'gh api' in c and '/hooks' in c]
    fill = {'<wake loop id>': 'loop_synthetic', '<id>': '7', '<webhook id>': '7', "<this skill's folder>": str(HERE.parent)}
    return [re.sub(r'<[^<>]*>', lambda m: fill[m.group(0)], c) for c in calls]


FAKE_GITHUB = r'''
const [mode, key, cert, address] = process.argv.slice(2);
const fs = require('fs');
const opts = {key: fs.readFileSync(key), cert: fs.readFileSync(cert)};
const handle = (req, res) => {
  const parts = [];
  req.on('data', c => parts.push(c));
  req.on('end', () => {
    const body = Buffer.concat(parts).toString();
    const url = body ? JSON.parse(body).config.url : address;
    console.log(JSON.stringify({v: req.httpVersion, m: req.method, got: body.includes(address)}));
    const hook = {id: 7, events: ['issues'], active: true, config: {url, content_type: 'json'}};
    if (req.method === 'DELETE') { res.writeHead(204); res.end(); return; }
    const out = JSON.stringify(req.method === 'GET' ? [hook] : hook);
    res.writeHead(req.method === 'POST' ? 201 : 200, {'content-type': 'application/json'});
    res.end(out);
  });
};
const server = mode === 'h2' ? require('http2').createSecureServer(opts, handle) : require('https').createServer(opts, handle);
server.listen(0, '127.0.0.1', () => console.log(server.address().port));
'''


class SetupUnderTracing(unittest.TestCase):

    def setUp(self):
        for tool in ('gh', 'jq', 'openssl', 'node'):
            self.assertTrue(shutil.which(tool), 'this proof needs %s on PATH' % tool)
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        bin_ = self.dir / 'bin'
        bin_.mkdir()
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-subj', '/CN=localhost',
                        '-addext', 'subjectAltName=DNS:localhost', '-keyout', str(bin_ / 'key.pem'),
                        '-out', str(bin_ / 'cert.pem')], check=True, capture_output=True)
        (bin_ / 'fake-github.js').write_text(FAKE_GITHUB)
        (bin_ / 'room-cli').write_text('#!/bin/sh\nprintf \'{"id":"loop_synthetic","url":"%s"}\\n\'\n' % ADDRESS)
        (bin_ / 'gh').write_text('#!/bin/sh\ncase "$* $(env)" in *SYNTHETIC-ADDRESS*) echo leaked >> "%s";; esac\n'
                                 'env | sed "s/=.*//" >> "%s"\nexec "%s" "$@"\n'
                                 % (self.dir / 'shim.log', self.dir / 'names.log', shutil.which('gh')))
        for tool in ('room-cli', 'gh'):
            (bin_ / tool).chmod(0o755)
        self.bin = bin_

    def serve(self, mode):
        server = subprocess.Popen(['node', str(self.bin / 'fake-github.js'), mode, str(self.bin / 'key.pem'),
                                   str(self.bin / 'cert.pem'), ADDRESS], stdout=subprocess.PIPE, text=True)
        self.addCleanup(server.wait, 10)
        self.addCleanup(server.terminate)
        host = 'localhost:%s' % server.stdout.readline().strip()
        env = {k: v for k, v in os.environ.items() if not k.startswith(('GH_', 'GITHUB_', 'GO'))}
        env.update(PATH='%s:%s' % (self.bin, os.environ['PATH']), SSL_CERT_FILE=str(self.bin / 'cert.pem'),
                   GH_HOST=host, GH_REPO='%s/synthetic-org/project' % host, GH_ENTERPRISE_TOKEN='synthetic',
                   GH_CONFIG_DIR=str(self.dir / 'config'), HOME=str(self.dir), **TRACING)
        return server, env

    def run_call(self, call, env):
        return subprocess.run(['sh', '-c', call], capture_output=True, text=True, env=env, cwd=self.dir, timeout=60)

    def test_tracing_never_shows_the_address(self):
        calls = documented_hook_calls()
        verbs = [m.group(1) if (m := re.search(r'--method (\w+)', c)) else 'GET' for c in calls]
        with self.subTest('documented commands'):
            self.assertEqual(sorted(verbs), ['DELETE', 'GET', 'PATCH', 'POST'],
                             'the setup, the rotation (PATCH), the list and the delete are all documented as commands')
        for mode, version in (('h2', '2.0'), ('h1', '1.1')):
            server, env = self.serve(mode)
            for call in calls:
                with self.subTest(mode=mode, call=call):
                    (self.dir / 'names.log').write_text('')
                    r = self.run_call(call, env)
                    self.assertEqual(r.returncode, 0, r.stderr[-2000:])
                    self.assertNotIn('SYNTHETIC-ADDRESS', r.stdout, 'the address reaches the terminal')
                    self.assertNotIn('SYNTHETIC-ADDRESS', r.stderr, 'tracing writes the address to stderr')
                    self.assertFalse((self.dir / 'shim.log').exists(), 'the address reaches gh as an argument or variable')
                    names = set((self.dir / 'names.log').read_text().split())
                    self.assertTrue(names, 'gh ran')
                    self.assertFalse(names & set(TRACING), 'gh starts with the caller\'s trace settings')
                    for f in self.dir.rglob('*'):
                        if f.is_file() and f.parent != self.bin:
                            self.assertNotIn(b'SYNTHETIC-ADDRESS', f.read_bytes(), 'the address reaches %s' % f)
                    seen = json.loads(server.stdout.readline())
                    self.assertEqual(seen['v'], version, 'the call ran over the protocol under test')
                    self.assertEqual(seen['got'], seen['m'] in ('POST', 'PATCH'), 'the webhook gets the address')
            r = self.run_call("gh api 'repos/{owner}/{repo}/hooks'", env)
            self.assertIn('SYNTHETIC-ADDRESS', r.stderr, 'tracing is on in the caller (%s)' % mode)
            server.stdout.readline()

if __name__ == '__main__':
    unittest.main()
