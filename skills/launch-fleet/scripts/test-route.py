#!/usr/bin/env python3
"""route.py on a synthetic GitHub (FF2, #1332): GitHub's messages from every repository reach the right fleet loop.

python3 -I skills/launch-fleet/scripts/test-route.py

Synthetic repositories, numbers and loop ids only. The fake `gh` serves one
GraphQL answer from a JSON world and logs every call, so a test can count reads.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
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
        self.env = dict(os.environ, PATH='%s:%s' % (self.dir / 'bin', os.environ['PATH']),
                        FAKE_WORLD=str(self.dir / 'world.json'), FAKE_LOG=str(self.log), GH_REPO=HOME)

    def run(self, *args, env=None):
        asked = [int(a) for a in args[2:] if a.isdigit()] if args[:1] == ('refs',) else []
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


if __name__ == '__main__':
    unittest.main()
