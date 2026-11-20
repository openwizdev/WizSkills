#!/usr/bin/env python3
"""route.py on a synthetic GitHub (FF2, #1332): GitHub's messages from every repository reach the right fleet loop.

python3 -I skills/launch-fleet/scripts/test-route.py

Synthetic repositories, numbers and loop ids only. The fake `gh` serves one
GraphQL answer from a JSON world and logs every call, so a test can count reads.
"""
import http.server
import json
import os
import re
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest

HERE = Path(__file__).resolve().parent
HOME = 'synthetic-org/project'
SAT = 'synthetic-org/skills'

FAKE_GH = r'''
import json, os, sys
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
items, errors = {}, []
for number in world['asked']:
    item = world['items'].get(str(number))
    items['i%d' % number] = item
    if item is None:
        errors.append({'type': 'NOT_FOUND', 'path': ['repository', 'i%d' % number]})
if world.get('error'):
    errors.append({'type': world['error'], 'message': 'synthetic %s' % world['error']})
print(json.dumps({'data': {'repository': items}, **({'errors': errors} if errors else {})}))
sys.exit(1 if errors else 0)
'''


# A fake `fleet.sh`, run by `sh`: it logs its arguments and prints the world's lines.
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
    """A pull request closing each `owner/name#N` in `closes`."""
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
        self.world = {'repo': repo, 'items': items or {}, 'fail': fail, 'error': error, 'asked': []}
        self.log = self.dir / 'calls.log'
        self.log.write_text('')
        fleet = self.dir / 'bin/fleet.sh'
        fleet.write_text(FAKE_FLEET)
        self.env = dict(os.environ, PATH='%s:%s' % (self.dir / 'bin', os.environ['PATH']),
                        FAKE_WORLD=str(self.dir / 'world.json'), FAKE_LOG=str(self.log), GH_REPO=HOME,
                        ROUTE_FLEET_SH=str(fleet))

    def fleet(self, lines=(), code=0):
        """What the fake `fleet.sh wake` prints, and its exit status."""
        self.world.update(fleet_lines=list(lines), fleet_code=code)

    def run(self, *args, env=None):
        first = {'refs': 2, 'tick': 3}.get(args[0] if args else None)
        asked = [int(a) for a in args[first:] if a.isdigit()] if first else []
        (self.dir / 'world.json').write_text(json.dumps(dict(self.world, asked=asked)))
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
        # catches: a WizSkills, WizSite or WizRoom message whose pull request number is read as a project
        # ticket, or read in its own repository, so its fleet is never woken (red on 2026-11-19: exit 2).
        w = World(self, items={'29': pr(HOME + '#1183')})
        self.assertEqual(w.run('refs', SAT, '29'), (0, '1183\n', ''))
        self.assertEqual(len(w.calls()), 1)

    def test_only_the_project_s_tickets_are_named_once_each_in_order(self):
        # catches: a closing reference to a third repository's issue, or a duplicate, reaching fleet.sh wake.
        w = World(self, items={'7': pr(HOME + '#40', 'synthetic-org/other#41', SAT + '#3', HOME + '#12'),
                               '8': pr(HOME + '#12')})
        self.assertEqual(w.run('refs', SAT, '8', '7', '8'), (0, '12 40\n', ''))
        self.assertEqual(len(w.calls()), 1, 'one batched read for every number')

    def test_issues_unknown_numbers_and_unlinked_pull_requests_name_nothing(self):
        # catches: a satellite issue or a missing number failing the whole wake instead of naming nothing.
        w = World(self, items={'5': ISSUE, '6': pr()})
        self.assertEqual(w.run('refs', SAT, '5', '6', '404'), (0, '', ''))

    def test_the_project_s_own_numbers_pass_through_unread(self):
        # catches: the project's own wake loop paying a read, or dropping its numbers, for a satellite rule.
        w = World(self, repo=HOME)
        self.assertEqual(w.run('refs', HOME, '31', '12', '31'), (0, '12 31\n', ''))
        self.assertEqual(w.calls(), [])

    def test_a_partial_or_failed_read_is_never_a_quiet_nothing(self):
        # catches: a pull request with more closing references than one page, or a failed read, waking no fleet
        # while looking like "nothing due".
        for world, reason in ((World(self, items={'9': pr(HOME + '#1', more=True)}), 'more than one page'),
                              (World(self, fail=True), 'synthetic failure'),
                              (World(self, items={'9': pr(HOME + '#1')}, error='FORBIDDEN'), 'FORBIDDEN')):
            code, out, err = world.run('refs', SAT, '9')
            self.assertEqual((code, out), (2, ''))
            self.assertIn(reason, err)

    def test_bad_arguments_are_refused_before_any_read(self):
        # catches: a message value (a flag, a path, a query fragment) reaching gh or fleet.sh.
        w = World(self)
        for args in (('refs', SAT), ('refs', 'not a repo', '1'), ('refs', SAT, '-1'), ('refs', SAT, '1x'),
                     ('refs', SAT, '0'), ('refs', 'a/b/c', '1'), ('nope',)):
            self.assertEqual(w.run(*args)[:2], (2, ''), args)
        self.assertEqual(w.run('refs', SAT, '1', env={'GH_REPO': ''})[:2], (2, ''))
        self.assertEqual(w.calls(), [])


class Loop(unittest.TestCase):
    ID = '0f1e2d3c-synthetic-loop'

    def test_a_handle_resolves_to_its_spec_s_loop_id(self):
        # catches: the wake running another spec's loop, or none, for a `wake fleet #S` line.
        w = World(self)
        path = w.loops({'repo': HOME, 'loops': {'10': self.ID, '40': 'other-synthetic-loop'}})
        self.assertEqual(w.run('loop', path, '10'), (0, self.ID + '\n', ''))
        self.assertEqual(w.calls(), [], 'the private map is read from disk only')

    def test_a_missing_handle_prints_nothing_and_exits_cleanly(self):
        # catches: a missing or unusable loop map failing the wake, instead of leaving the spec to its own
        # loop (the safety net) with no error.
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
        # catches: a due line's text, rather than a spec number, choosing the key.
        w = World(self)
        path = w.loops({'repo': HOME, 'loops': {'10': self.ID}})
        for s in ('', '-10', '10 40', 'S'):
            self.assertEqual(w.run('loop', path, s)[:2], (2, ''), s)


class Tick(unittest.TestCase):
    """One webhook tick's group of messages, from the numbers to the effect lines it acts on."""
    ID = '0f1e2d3c-synthetic-loop'

    def world(self, **kw):
        w = World(self, **kw)
        return w, w.loops({'repo': HOME, 'loops': {'10': self.ID}})

    def test_a_satellite_message_runs_its_spec_s_loop(self):
        # catches: the tick's three steps (refs, wake, loop id) not joining up for another repository's message.
        w, path = self.world(items={'29': pr(HOME + '#13')})
        w.fleet(['wake fleet #10: room-cli loop run fleet-10'])
        self.assertEqual(w.run('tick', SAT, path, '29'), (0, 'wake fleet #10: room-cli loop run %s\n' % self.ID, ''))
        self.assertEqual([c for c in w.calls() if c[0] == 'fleet.sh'], [['fleet.sh', 'wake', '13']])

    def test_a_missing_handle_is_reported_privately_and_writes_nothing(self):
        # catches (R1): a missing loop id posting a GitHub record, whose own issue_comment message comes back
        # through the same webhook and wakes the same missing handle again, over and over.
        w, _ = self.world(items={'29': pr(HOME + '#13')})
        w.fleet(['wake fleet #10: room-cli loop run fleet-10'])
        for path in (str(w.dir / 'absent.json'), w.loops({'repo': HOME, 'loops': {}})):
            self.assertEqual(w.run('tick', SAT, path, '29'), (0, 'wake fleet #10: unresolved\n', ''))
        gh = [c for c in w.calls() if c[0] != 'fleet.sh']
        self.assertTrue(gh and all(c[:2] == ['api', 'graphql'] and 'mutation' not in ' '.join(c) for c in gh), gh)

    def test_a_group_with_no_project_ticket_ends_quietly(self):
        # catches (R3): a satellite issue, or a pull request closing nothing, calling `fleet.sh wake` with no
        # numbers, which prints its usage and exits 2.
        w, path = self.world(items={'5': ISSUE, '6': pr(SAT + '#2')})
        self.assertEqual(w.run('tick', SAT, path, '5', '6'), (0, '', ''))
        self.assertEqual([c for c in w.calls() if c[0] == 'fleet.sh'], [])

    def test_the_project_s_own_numbers_go_straight_to_wake(self):
        # catches: the project's own messages paying the satellite read, or losing a line wake prints.
        w, path = self.world(repo=HOME)
        w.fleet(['start #41: G1: gadget model (spec #40)', 'wake fleet #10: room-cli loop run fleet-10'])
        self.assertEqual(w.run('tick', HOME, path, '41', '13'),
                         (0, 'start #41: G1: gadget model (spec #40)\nwake fleet #10: room-cli loop run %s\n' % self.ID,
                          ''))
        self.assertEqual(w.calls(), [['fleet.sh', 'wake', '13', '41']])

    def test_a_failed_lookup_or_wake_is_a_failure(self):
        # catches: a refused read or a refused `fleet.sh wake` passing as a quiet nothing due.
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
        # catches (R2): a setup step that saves the wake loop's address to a file, prints it, or passes it on a
        # command line, where it outlives the step or shows in a process list.
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
            head, tail = re.sub(r'<[^<>]*>', 'X', c).split('room-cli loop', 1)  # placeholders aren't redirects
            self.assertNotRegex(head, r"(\$\(|`|=)\s*$", c)
            self.assertRegex(tail, r"\|\s*jq ", c)
            self.assertNotRegex(tail, r"(^|[^|&])>|\btee\b|--slurpfile|--rawfile", c)
        for c in commands:
            if 'loop hook' in c:
                self.assertRegex(c, r"\|\s*(env (-u \w+ )+)?gh api --method POST '?repos/[^ ]+/hooks'? --input -", c)
            if 'loop create' in c and '--webhook' in c:
                self.assertIn('| jq -r .id', c)



ADDRESS = 'https://synthetic.invalid/wake/SYNTHETIC-ADDRESS-0000'


def documented_hook_calls():
    """Every documented command whose `gh api` call sends or reads a webhook, with its placeholders filled in."""
    text = (HERE.parent / 'references/launch.md').read_text()
    fenced = [b.replace('\\\n', ' ') for b in re.findall(r'```sh\n(.*?)```', text, re.S)]
    spans = re.findall(r'`([^`\n]*gh api[^`\n]*)`', re.sub(r'```.*?```', '', text, flags=re.S))
    calls = [' '.join(c.split()) for c in fenced + spans if 'gh api' in c and '/hooks' in c]
    fill = {'<wake loop id>': 'loop_synthetic', '<id>': '7', '<webhook id>': '7'}
    return [re.sub(r'<[^<>]*>', lambda m: fill[m.group(0)], c) for c in calls]


class FakeGitHub(http.server.BaseHTTPRequestHandler):
    """A local HTTPS GitHub that answers like the real one: a webhook's address comes back in `config.url`."""
    def answer(self):
        body = self.rfile.read(int(self.headers.get('Content-Length') or 0))
        hook = {'id': 7, 'events': ['issues'], 'active': True,
                'config': {'url': json.loads(body)['config']['url'] if body else ADDRESS, 'content_type': 'json'}}
        out = b'' if self.command == 'DELETE' else json.dumps([hook] if self.command == 'GET' else hook).encode()
        self.send_response(204 if self.command == 'DELETE' else 201 if self.command == 'POST' else 200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(out)))
        self.end_headers()
        self.wfile.write(out)
    do_GET = do_POST = do_PATCH = do_DELETE = answer

    def log_message(self, *args):
        pass


class SetupUnderTracing(unittest.TestCase):
    """The documented webhook setup run for real, with the real GitHub CLI and HTTP tracing on in the caller's shell."""

    def setUp(self):
        for tool in ('gh', 'jq', 'openssl'):
            self.assertTrue(shutil.which(tool), 'this proof needs %s on PATH' % tool)
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        bin_ = self.dir / 'bin'
        bin_.mkdir()
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-subj', '/CN=localhost',
                        '-addext', 'subjectAltName=DNS:localhost', '-keyout', str(self.dir / 'key.pem'),
                        '-out', str(self.dir / 'cert.pem')], check=True, capture_output=True)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(self.dir / 'cert.pem', self.dir / 'key.pem')
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), FakeGitHub)
        server.socket = tls.wrap_socket(server.socket, server_side=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        # Cloudroom's side: `loop hook` prints a fresh synthetic address on stdout, as the real one does.
        (bin_ / 'room-cli').write_text('#!/bin/sh\nprintf \'{"id":"loop_synthetic","url":"%s"}\\n\'\n' % ADDRESS)
        # A shim in front of the real gh records only whether the address is in its arguments or environment.
        (bin_ / 'gh').write_text('#!/bin/sh\ncase "$* $(env)" in *SYNTHETIC-ADDRESS*) echo leaked >> "%s";; esac\n'
                                 'exec "%s" "$@"\n' % (self.dir / 'shim.log', shutil.which('gh')))
        for tool in ('room-cli', 'gh'):
            (bin_ / tool).chmod(0o755)
        host = 'localhost:%d' % server.server_address[1]
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(('GH_', 'GITHUB_'))}
        self.env.update(PATH='%s:%s' % (bin_, os.environ['PATH']), SSL_CERT_FILE=str(self.dir / 'cert.pem'),
                        GH_HOST=host, GH_REPO='%s/synthetic-org/project' % host, GH_ENTERPRISE_TOKEN='synthetic',
                        GH_CONFIG_DIR=str(self.dir / 'config'), GH_NO_UPDATE_NOTIFIER='1', GH_PROMPT_DISABLED='1',
                        HOME=str(self.dir), GH_DEBUG='api', DEBUG='api')

    def test_tracing_never_shows_the_address(self):
        # catches (R2): a URL-bearing gh call that inherits GH_DEBUG=api (or the legacy DEBUG=api), so the GitHub
        # CLI writes the request and response bodies, address and all, to stderr before --jq filters stdout.
        calls = documented_hook_calls()
        self.assertGreaterEqual(len(calls), 3, 'the setup, the list and the delete are all documented')
        for call in calls:
            with self.subTest(call=call):
                r = subprocess.run(['sh', '-c', call], capture_output=True, text=True, env=self.env,
                                   cwd=self.dir, timeout=60)
                self.assertEqual(r.returncode, 0, r.stderr[-2000:])
                self.assertNotIn('SYNTHETIC-ADDRESS', r.stdout, 'the address reaches the terminal')
                self.assertNotIn('SYNTHETIC-ADDRESS', r.stderr, 'HTTP tracing writes the address to stderr')
                self.assertFalse((self.dir / 'shim.log').exists(), 'the address reaches gh as an argument or variable')
                for f in self.dir.rglob('*'):
                    if f.is_file() and f.parent.name != 'bin':  # bin holds the synthetic room-cli itself
                        self.assertNotIn(b'SYNTHETIC-ADDRESS', f.read_bytes(), 'the address reaches %s' % f)
        self.assertTrue(any(c.startswith('room-cli loop hook') for c in calls), calls)
        # Not vacuous: in this same environment, a plain gh call does trace its request and response bodies.
        r = subprocess.run(['sh', '-c', "gh api 'repos/{owner}/{repo}/hooks'"], capture_output=True, text=True,
                           env=self.env, cwd=self.dir, timeout=60)
        self.assertIn('SYNTHETIC-ADDRESS', r.stderr, 'tracing is on in the caller')

if __name__ == '__main__':
    unittest.main()
