#!/usr/bin/env python3
"""P4 (#1254, revision 4): status.py on a synthetic tracker with a fake `gh`.

Run: python3 -I skills/launch-fleet/scripts/test-status.py
Every value here is synthetic. The fake gh keeps the tracker in a JSON file,
logs every call, stamps GitHub's updated_at on each comment it writes, and
refuses what GitHub refuses (editing another author's comment). Expected notes,
labels and lines come from the contract, contracts/agent-status.v1.md, never
from status.py. Ages are 5 minutes (live) or 31 to 90 minutes (lapsed) against
the real clock, far from the 30-minute edge.
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SCRIPT = HERE / 'status.py'
CONTRACT = ROOT / 'contracts/agent-status.v1.md'
SCHEMA = ROOT / 'contracts/agent-status.v1.schema.json'
REPO = 'example/tracker'
BOT = 'openwiz[bot]'
FLEET_MD = '# Fleet settings\n\n## GitHub identity\n\n| Setting | Value |\n| --- | --- |\n| Record authors | `openwiz[bot]`, `synthetic-owner` |\n'
MARKER = '<!-- openwiz:status v1 -->'

FAKE_GH = r'''
import json, os, sys
from datetime import datetime, timezone
from urllib.parse import urlsplit, parse_qs, unquote
args = sys.argv[1:]
world_path = os.environ['FAKE_GH_WORLD']
world = json.load(open(world_path))
assert args[0] == 'api', args
args = args[1:]
method, path, accept, body = 'GET', None, None, None
i = 0
while i < len(args):
    a = args[i]
    if a == '--method': method = args[i + 1]; i += 2
    elif a == '-H': accept = args[i + 1]; i += 2
    elif a == '--input': assert args[i + 1] == '-'; body = json.loads(sys.stdin.read()); i += 2
    else: assert path is None, args; path = a; i += 1
with open(os.environ['FAKE_GH_LOG'], 'a') as log:
    log.write(json.dumps({'method': method, 'path': path, 'body': body}) + '\n')
size = int(os.environ.get('FAKE_GH_PAGE', '100'))
now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
def out(value):
    sys.stdout.write(json.dumps(value)); sys.exit(0)
def fail(code, text):
    sys.stderr.write('gh: %s (HTTP %d)\n' % (text, code)); sys.exit(1)
def save():
    json.dump(world, open(world_path, 'w'), indent=1, sort_keys=True)
def issue(n):
    for it in world['issues']:
        if it['number'] == int(n): return it
    fail(404, 'Not Found')
def rest(c):
    return {'id': c['id'], 'user': {'login': c['author']} if c['author'] else None,
            'body': c['body'], 'updated_at': c['updated']}
def page(items, query):
    k = int(query.get('page', ['1'])[0]); n = min(int(query.get('per_page', ['30'])[0]), size)
    return items[(k - 1) * n:k * n]
parts = urlsplit(path); query = parse_qs(parts.query)
seg = [unquote(s) for s in parts.path.split('/')]
if path == 'graphql':
    assert method == 'POST' and 'mutation' not in body['query'], body
    v = body['variables']; assert v['owner'] + '/' + v['name'] == world['repo']
    open_issues = [it for it in world['issues'] if it['state'] == 'open']
    start = int(v.get('cursor') or 0)
    chunk = open_issues[start:start + size]
    out({'data': {'repository': {'issues': {
        'pageInfo': {'hasNextPage': start + size < len(open_issues), 'endCursor': str(start + size)},
        'nodes': [{'number': it['number'], 'labels': {'nodes': [{'name': l} for l in it['labels']]},
                   'comments': {'pageInfo': {'hasNextPage': len(it['comments']) > size},
                                'nodes': [{'databaseId': c['id'], 'author': {'login': c['author']} if c['author'] else None,
                                           'body': c['body'], 'updatedAt': c['updated']} for c in it['comments'][:size]]},
                   'closedByPullRequestsReferences': {'nodes': it.get('prs', [])}} for it in chunk]}}}})
assert '/'.join(seg[:3]) == 'repos/' + world['repo'], path
seg = seg[3:]
if method == 'GET' and seg == ['contents', 'docs', 'agents', 'fleet.md']:
    assert accept == 'Accept: application/vnd.github.raw'
    if world.get('fleet_md') is None: fail(404, 'Not Found')
    sys.stdout.write(world['fleet_md']); sys.exit(0)
if seg[0] == 'issues' and len(seg) == 2 and method == 'GET':
    it = issue(seg[1]); out({'number': it['number'], 'state': it['state'], 'labels': [{'name': l} for l in it['labels']]})
if seg[0] == 'issues' and seg[2:] == ['labels'] and method == 'POST':
    it = issue(seg[1])
    for l in body['labels']:
        if l not in it['labels']: it['labels'].append(l)
    save(); out([{'name': l} for l in it['labels']])
if seg[0] == 'issues' and len(seg) == 4 and seg[2] == 'labels' and method == 'DELETE':
    it = issue(seg[1])
    if seg[3] not in it['labels']: fail(404, 'Label does not exist')
    it['labels'].remove(seg[3]); save(); out([{'name': l} for l in it['labels']])
if seg[0] == 'issues' and seg[2:] == ['comments'] and method == 'GET':
    it = issue(seg[1]); out(page([rest(c) for c in it['comments']], query))
if seg[0] == 'issues' and seg[2:] == ['comments'] and method == 'POST':
    it = issue(seg[1])
    # A rival agent's note that reached GitHub a moment before this one.
    for rival in world.pop('race', []):
        world['next_id'] += 1
        it['comments'].append(dict(rival, id=world['next_id'], updated=now))
    world['next_id'] += 1
    c = {'id': world['next_id'], 'author': world['login'], 'body': body['body'], 'updated': now}
    it['comments'].append(c); save(); out(rest(c))
if seg[:2] == ['issues', 'comments'] and len(seg) == 3 and method == 'PATCH':
    for it in world['issues']:
        for c in it['comments']:
            if c['id'] == int(seg[2]):
                if c['author'] != world['login']: fail(403, 'Must have admin rights to Repository.')
                c['body'] = body['body']; c['updated'] = now; save(); out(rest(c))
    fail(404, 'Not Found')
fail(404, 'Not Found: ' + method + ' ' + path)
'''


def ago(minutes):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).strftime('%Y-%m-%dT%H:%M:%SZ')


def note(agent='builder', state='working', step='started the build', time='2030-01-02T03:00:00Z',
         pr=None, preview=None, harness='Claude Code', model='Opus 5.5 Medium', skills='build-ticket@0.1.2'):
    """The text form the contract fixes, key by key."""
    lines = [MARKER, 'agent: ' + agent, 'state: ' + state, 'harness: ' + harness, 'model: ' + model,
             'skills: ' + skills, 'step: ' + step, 'time: ' + time]
    lines += ['pr: ' + pr] if pr else []
    lines += ['preview: ' + preview] if preview else []
    return '\n'.join(lines)


def comment(cid, author, body, minutes=5):
    return {'id': cid, 'author': author, 'body': body, 'updated': ago(minutes)}


def contract_example():
    text = CONTRACT.read_text()
    section = text.split('Example (synthetic):\n\n```text\n', 1)[1]
    return section.split('\n```', 1)[0]


class Tracker(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / 'bin').mkdir()
        (self.dir / 'gh.py').write_text(FAKE_GH)
        gh = self.dir / 'bin' / 'gh'
        gh.write_text('#!/bin/sh\nexec ' + sys.executable + ' -I -S ' + str(self.dir / 'gh.py') + ' "$@"\n')
        gh.chmod(0o755)
        self.world = {
            'repo': REPO, 'login': BOT, 'fleet_md': FLEET_MD, 'next_id': 9000,
            'issues': [{'number': 12, 'state': 'open', 'labels': ['ready-for-agent'], 'comments': [
                comment(101, 'synthetic-owner', 'launch-fleet: started'),
                # Anyone may comment on a public ticket: a planted marker is not a note.
                comment(102, 'synthetic-outsider', note()),
                comment(103, None, note()),
            ]}],
        }
        self.page = '100'

    def save(self):
        (self.dir / 'world.json').write_text(json.dumps(self.world))

    def load(self):
        return json.loads((self.dir / 'world.json').read_text())

    def calls(self):
        log = self.dir / 'gh.log'
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def writes(self):
        return [(c['method'], c['path']) for c in self.calls() if c['method'] != 'GET' and c['path'] != 'graphql']

    def run_status(self, *args):
        env = dict(os.environ, PATH=str(self.dir / 'bin') + ':' + os.environ['PATH'],
                   FAKE_GH_WORLD=str(self.dir / 'world.json'), FAKE_GH_LOG=str(self.dir / 'gh.log'),
                   FAKE_GH_PAGE=self.page)
        for key in ('GH_TOKEN', 'GITHUB_TOKEN', 'GH_REPO'):
            env.pop(key, None)
        return subprocess.run([sys.executable, '-I', str(SCRIPT), *args], env=env,
                              capture_output=True, text=True, timeout=60)

    def write(self, state, step, time, *extra, agent='builder'):
        return self.run_status('write', '--repo', REPO, '--ticket', '12', '--agent', agent, '--state', state,
                               '--harness', 'Claude Code', '--model', 'Opus 5.5 Medium',
                               '--skills', 'build-ticket@0.1.2', '--step', step, '--time', time, *extra)

    def ticket(self, world=None):
        return next(it for it in (world or self.load())['issues'] if it['number'] == 12)


class Write(Tracker):
    def test_second_run_edits_the_one_note_and_asking_sets_then_clears_needs_info(self):
        # catches: a second run posting another note, the skills the agent passed not written
        # as given, a stranger's planted marker taken as the agent's note, asking without needs-info, needs-info left after asking, or any
        # building or in-review label written.
        self.save()
        first = self.write('working', 'started the build', '2030-01-02T03:00:00Z')
        self.assertEqual((first.returncode, first.stdout, first.stderr),
                         (0, '#12: builder working, status note 9001 posted\n', ''))
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent'])
        self.assertEqual(self.ticket()['comments'][3]['body'], note())

        asking = self.write('asking', 'asked which file to change', '2030-01-02T04:00:00Z', '--note', '9001')
        self.assertEqual((asking.returncode, asking.stdout, asking.stderr),
                         (0, '#12: builder asking, status note 9001 edited\n', ''))
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent', 'needs-info'])

        pr = 'https://github.com/example/skills/pull/31'
        back = self.write('working', 'handed back; CI is green', '2030-01-02T05:00:00Z', '--note', '9001',
                          '--pr', pr, '--preview', 'https://31.example-site.pages.dev',
                          '--skills', 'build-ticket@0.1.2, diagnose@0.1.3')
        self.assertEqual((back.returncode, back.stdout), (0, '#12: builder working, status note 9001 edited\n'))
        world = self.load()
        self.assertEqual(self.ticket(world)['labels'], ['ready-for-agent'])
        self.assertEqual([c['id'] for c in self.ticket(world)['comments']], [101, 102, 103, 9001])
        self.assertEqual(self.ticket(world)['comments'][1]['body'], note())
        self.assertEqual(self.ticket(world)['comments'][3]['body'],
                         note(step='handed back; CI is green', time='2030-01-02T05:00:00Z', pr=pr,
                              preview='https://31.example-site.pages.dev', skills='build-ticket@0.1.2, diagnose@0.1.3'))
        self.assertEqual(self.writes(), [
            ('POST', 'repos/example/tracker/issues/12/comments'),
            ('PATCH', 'repos/example/tracker/issues/comments/9001'),
            ('POST', 'repos/example/tracker/issues/12/labels'),
            ('PATCH', 'repos/example/tracker/issues/comments/9001'),
            ('DELETE', 'repos/example/tracker/issues/12/labels/needs-info'),
        ])
        self.assertEqual([c['body'] for c in self.calls() if c['path'].endswith('/12/labels')], [{'labels': ['needs-info']}])

    def test_leaving_asking_keeps_a_needs_info_it_did_not_set(self):
        # catches: a note that was never asking clearing a needs-info a person set.
        self.ticket(self.world)['labels'] = ['ready-for-agent', 'needs-info', 'held']
        self.ticket(self.world)['comments'].append(comment(104, BOT, note()))
        self.save()
        done = self.write('done', 'merged', '2030-01-02T06:00:00Z', '--note', '104')
        self.assertEqual((done.returncode, done.stdout), (0, '#12: builder done, status note 104 edited\n'))
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent', 'needs-info', 'held'])
        self.assertEqual(self.writes(), [('PATCH', 'repos/example/tracker/issues/comments/104')])

    def test_a_note_past_the_first_page_is_found(self):
        # catches: reading only the first page of comments, so a claim or the agent's own note is missed.
        self.ticket(self.world)['comments'] += [comment(104, 'synthetic-owner', 'note'),
                                                comment(105, BOT, note(state='working')),
                                                comment(106, BOT, note(agent='fleet'))]
        self.save()
        self.page = '2'
        edit = self.write('asking', 'asked a question', '2030-01-02T03:00:00Z', '--note', '105')
        self.assertEqual((edit.returncode, edit.stdout), (0, '#12: builder asking, status note 105 edited\n'))
        claim = self.write('working', 'started the build', '2030-01-02T03:00:00Z')
        self.assertEqual((claim.returncode, claim.stdout), (3, ''))
        self.assertIn('note 105 holds the builder claim', claim.stderr)
        self.assertEqual([c['id'] for c in self.ticket()['comments']], [101, 102, 103, 104, 105, 106])

    def test_the_contract_example_is_what_the_writer_writes(self):
        # catches: the writer's text drifting from the contract the app parses.
        self.save()
        result = self.write('working', 'opened the pull request; CI is running', '2030-01-02T03:04:05Z',
                            '--pr', 'https://github.com/example/site/pull/42',
                            '--preview', 'https://42.example-site.pages.dev')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.ticket()['comments'][-1]['body'], contract_example())

    def test_no_record_authors_refuses_before_any_write(self):
        # catches: a writer that trusts every commenter when the record authors can't be read.
        for fleet_md in (None, '# Fleet settings\n', FLEET_MD.replace('`openwiz[bot]`, `synthetic-owner`', '')):
            with self.subTest(fleet_md=fleet_md):
                self.world['fleet_md'] = fleet_md
                self.save()
                (self.dir / 'gh.log').unlink(missing_ok=True)
                result = self.write('working', 'started the build', '2030-01-02T03:00:00Z')
                self.assertEqual((result.returncode, result.stdout), (2, ''))
                self.assertIn('record authors', result.stderr)
                self.assertEqual([c['method'] for c in self.calls()], ['GET'])
                self.assertEqual(self.load(), self.world)


class Claims(Tracker):
    def test_the_oldest_live_note_of_a_kind_holds_the_claim(self):
        # catches: a second builder claiming a ticket another builder holds, a lapsed or
        # stopped note still blocking, another kind's note blocking a builder, or a note
        # without a well-formed skills line read as a claim.
        cases = [
            ('a live builder note blocks', [comment(104, BOT, note())], 3),
            ('an asking builder note blocks', [comment(104, 'Synthetic-Owner', note(state='asking'))], 3),
            ('a lapsed builder note does not', [comment(104, BOT, note(), minutes=31)], 0),
            ('a stopped builder note does not', [comment(104, BOT, note(state='stopped (lease expired)'))], 0),
            ('a done builder note does not', [comment(104, BOT, note(state='done'))], 0),
            ('a live fleet note does not', [comment(104, BOT, note(agent='fleet'))], 0),
            ('an unreadable note does not', [comment(104, BOT, MARKER + '\nagent: builder')], 0),
            ('a note without skills does not', [comment(104, BOT, note().replace('skills: build-ticket@0.1.2\n', ''))], 0),
            ('a note with a bad skills line does not', [comment(104, BOT, note(skills='build-ticket'))], 0),
        ]
        base = json.loads(json.dumps(self.world))
        for name, planted, code in cases:
            with self.subTest(name):
                self.world = json.loads(json.dumps(base))
                self.ticket(self.world)['comments'] += planted
                self.save()
                (self.dir / 'gh.log').unlink(missing_ok=True)
                result = self.write('working', 'started the build', '2030-01-02T03:00:00Z')
                self.assertEqual(result.returncode, code, result.stderr)
                if code:
                    self.assertEqual((result.stdout, self.writes()), ('', []))
                    self.assertEqual(self.load(), self.world)
                else:
                    self.assertEqual(self.writes(), [('POST', 'repos/example/tracker/issues/12/comments')])

    def test_the_fence_stops_a_writer_whose_note_is_no_longer_live(self):
        # catches: an agent writing on after its claim was stopped, lost or taken by another kind.
        cases = [
            ('stopped by the fleet', [comment(104, BOT, note(state='stopped (lease expired)'))], '104'),
            ('an older live claim', [comment(104, BOT, note()), comment(105, BOT, note())], '105'),
            ('gone', [], '104'),
            ('not a record author', [comment(104, 'synthetic-outsider', note())], '104'),
            ('another kind', [comment(104, BOT, note(agent='reviewer'))], '104'),
            ('not a note', [comment(104, BOT, 'launch-fleet: started')], '104'),
        ]
        base = json.loads(json.dumps(self.world))
        for name, planted, own in cases:
            with self.subTest(name):
                self.world = json.loads(json.dumps(base))
                self.ticket(self.world)['comments'] += planted
                self.save()
                (self.dir / 'gh.log').unlink(missing_ok=True)
                result = self.write('asking', 'asked a question', '2030-01-02T03:00:00Z', '--note', own)
                self.assertEqual((result.returncode, result.stdout), (3, ''))
                self.assertRegex(result.stderr, r'^status\.py: stop: ')
                self.assertEqual(self.writes(), [])
                self.assertEqual(self.load(), self.world)
        # A lapsed note that nobody took over is still its agent's: an edit revives it.
        self.world = json.loads(json.dumps(base))
        self.ticket(self.world)['comments'].append(comment(104, BOT, note(), minutes=90))
        self.save()
        revived = self.write('working', 'CI finished', '2030-01-02T03:00:00Z', '--note', '104')
        self.assertEqual((revived.returncode, revived.stdout), (0, '#12: builder working, status note 104 edited\n'))

    def test_a_writer_that_loses_the_race_stops_its_own_note(self):
        # catches: two builders both keeping a claim when their notes reach GitHub together.
        self.ticket(self.world)['labels'] = ['ready-for-agent']
        self.world['race'] = [{'author': BOT, 'body': note(step='a rival started')}]
        self.save()
        result = self.write('asking', 'asked a question', '2030-01-02T03:00:00Z')
        self.assertEqual((result.returncode, result.stdout), (3, ''))
        self.assertIn('note 9001 holds the builder claim', result.stderr)
        comments = self.ticket()['comments']
        self.assertEqual([c['id'] for c in comments], [101, 102, 103, 9001, 9002])
        self.assertEqual(comments[4]['body'], note(state='stopped (lost claim)', step='asked a question'))
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent'])
        self.assertEqual(self.writes(), [('POST', 'repos/example/tracker/issues/12/comments'),
                                         ('PATCH', 'repos/example/tracker/issues/comments/9002')])


# Each value is refused before any call (exit 2, no gh call). A field's flag and a value.
PRIVATE = [
    ('--step', 'resumed thread thr_synbuilder1'),
    ('--step', 'ran it in /home/synthetic-dev/openwiz'),
    ('--model', 'Opus /Users/example/x'),
    ('--step', 'saved to ~/work/notes'),
    ('--step', r'copied C:\Users\example\x'),
    ('--step', 'logs in /tmp/synthetic-run'),
    ('--step', 'on /code/synthetic-repo'),
    ('--harness', 'Codex on mch_synbox1'),
    ('--step', 'project prj_synfleet1'),
    ('--preview', 'https://example.invalid/thr_synpreview1'),
    ('--why', 'thread thr_synbuilder1 ended'),
    ('--skills', 'build-ticket@0.1.2, /home/synthetic-dev/skills/grill'),
    ('--skills', '~/skills/build-ticket@0.1.2'),
    ('--skills', 'build-ticket@0.1.2, thr_synbuilder1'),
    ('--skills', '"build-ticket@0.1.2"'),
    ('--step', 'Robin said "ship it"'),
    ('--step', 'Robin said \u201cship it\u201d'),
    ('--step', '> ship it'),
]
# Shape refusals: the schema refuses them too.
BAD_SHAPE = [
    ('--agent', 'helper'),
    ('--state', 'building'),
    ('--state', 'in-review'),
    ('--why', 'two (parts)'),
    ('--why', 'w' * 101),
    ('--step', ''),
    ('--step', 'two\nlines'),
    ('--step', 'tab\there'),
    ('--step', 'x' * 301),
    ('--model', 'm' * 61),
    ('--skills', 'build-ticket'),
    ('--skills', 'build-ticket@0.1'),
    ('--skills', 'build-ticket@v0.1.2'),
    ('--skills', 'Build-Ticket@0.1.2'),
    ('--skills', 'build_ticket@0.1.2'),
    ('--skills', 'build-ticket@0.1.2,review-ticket@0.1.0'),
    ('--skills', 'build-ticket@0.1.2, '),
    ('--skills', 'skills/build-ticket@0.1.2'),
    ('--skills', 'https://github.com/example/skills@0.1.2'),
    ('--skills', ', '.join(['build-ticket@0.1.2'] * 16)),
    ('--time', '2030-01-02 03:00:00'),
    ('--pr', 'https://github.com/example/skills/issues/31'),
    ('--pr', '#31'),
    ('--preview', 'javascript:alert(1)'),
    ('--preview', 'http://31.example-site.pages.dev'),
    ('--preview', 'https://example.invalid/<script>'),
]
GOOD_SHAPE = [
    ('--agent', 'reviewer'),
    ('--state', 'done'),
    ('--why', 'lease expired'),
    ('--step', 'x' * 300),
    ('--model', 'm' * 60),
    ('--skills', 'build-ticket@0.1.1, review-ticket@0.1.0'),
    ('--skills', 'launch-fleet@10.20.30'),
    ('--skills', ', '.join(['build-ticket@0.1.2'] * 15)),
    ('--step', 'checked https://github.com/acme/home/pull/1 and a/home/b'),
    ('--pr', 'https://github.com/example/skills/pull/31'),
    ('--preview', 'https://31.example-site.pages.dev/app?x=1'),
]
FIELD = {'--agent': 'agent', '--state': 'state', '--why': 'state', '--harness': 'harness', '--model': 'model',
         '--skills': 'skills',
         '--step': 'step', '--time': 'time', '--pr': 'pr', '--preview': 'preview'}


def valid(schema, node, value):
    """The subset of JSON Schema 2020-12 the status schema uses."""
    if '$ref' in node:
        if not valid(schema, schema['$defs'][node['$ref'].split('/')[-1]], value):
            return False
    if node.get('type') == 'object':
        if not isinstance(value, dict) or set(node['required']) - set(value):
            return False
        if node.get('additionalProperties') is False and set(value) - set(node['properties']):
            return False
        return all(valid(schema, node['properties'][k], v) for k, v in value.items())
    if node.get('type') == 'string' and not isinstance(value, str):
        return False
    if 'enum' in node and value not in node['enum']:
        return False
    if 'minLength' in node and len(value) < node['minLength']:
        return False
    if 'maxLength' in node and len(value) > node['maxLength']:
        return False
    return 'pattern' not in node or re.search(node['pattern'], value) is not None


class Refuse(Tracker):
    def args(self, flag, value):
        values = {'--agent': 'builder', '--state': 'working', '--harness': 'Claude Code',
                  '--model': 'Opus 5.5 Medium', '--skills': 'build-ticket@0.1.2', '--step': 'started the build',
                  '--time': '2030-01-02T03:00:00Z'}
        if flag == '--why':
            values['--state'] = 'stopped'
        if value is None:
            del values[flag]
        else:
            values[flag] = value
        args = ['write', '--repo', REPO, '--ticket', '12']
        for key, item in values.items():
            args += [key, item]
        return args

    def test_private_or_bad_text_is_refused_before_any_call(self):
        # catches: a thread id, machine path, CloudRoom id, quoted words or a bad shape
        # reaching the public note (in any field, skills included), a note written with no
        # skills line, or a refusal that comes after a call.
        self.save()
        for flag, value in PRIVATE + BAD_SHAPE:
            with self.subTest(flag=flag, value=value):
                result = self.run_status(*self.args(flag, value))
                self.assertEqual((result.returncode, result.stdout), (2, ''))
                self.assertRegex(result.stderr, r'^status\.py: refused: ' + FIELD[flag] + r': ')
                if value:
                    self.assertNotIn(value, result.stderr)
                self.assertEqual(self.calls(), [])
        self.assertEqual(self.load(), self.world)
        missing = self.run_status(*self.args('--skills', None))
        self.assertEqual((missing.returncode, missing.stdout, self.calls()), (2, '', []))
        self.assertRegex(missing.stderr, r'^status\.py: refused: skills: missing')
        why = self.run_status(*self.args('--state', 'working') + ['--why', 'lease expired'])
        self.assertEqual((why.returncode, why.stdout, self.calls()), (2, '', []))
        self.assertRegex(why.stderr, r'^status\.py: refused: state: ')

    def test_the_schema_and_the_writer_agree_on_each_shape(self):
        # catches: the schema the app validates with and the writer accepting different values.
        schema = json.loads(SCHEMA.read_text())
        base = {'agent': 'builder', 'state': 'working', 'harness': 'Claude Code', 'model': 'Opus 5.5 Medium',
                'skills': 'build-ticket@0.1.2', 'step': 'started the build', 'time': '2030-01-02T03:00:00Z'}
        self.assertTrue(valid(schema, schema, base))
        for flag, value, good in [(f, v, False) for f, v in BAD_SHAPE] + [(f, v, True) for f, v in GOOD_SHAPE]:
            with self.subTest(flag=flag, value=value):
                self.save()
                result = self.run_status(*self.args(flag, value))
                self.assertEqual(result.returncode == 0, good, result.stderr)
                field = dict(base, state='stopped (%s)' % value) if flag == '--why' else dict(base, **{FIELD[flag]: value})
                self.assertEqual(valid(schema, schema, field), good)
        self.assertFalse(valid(schema, schema, {k: v for k, v in base.items() if k != 'skills'}))
        self.assertEqual(schema['$defs']['label']['enum'], ['spec', 'ready-for-agent', 'ready-for-human', 'needs-info', 'held'])
        self.assertEqual(schema['$defs']['state']['enum'], ['working', 'asking', 'done', 'stopped'])


class Check(Tracker):
    def test_check_lists_each_planted_mismatch_and_changes_nothing(self):
        # catches: a note GitHub contradicts or a lapsed claim the wake misses, a closed
        # ticket, a stranger's note or a finished note reported, a page skipped, or a write.
        def pr(n, state):
            return {'number': n, 'state': state, 'url': 'https://github.com/example/skills/pull/%d' % n}
        def it(n, comments, labels=('ready-for-agent',), prs=(), state='open'):
            return {'number': n, 'state': state, 'labels': list(labels), 'comments': comments, 'prs': list(prs)}
        self.world['issues'] = [
            it(20, [comment(201, BOT, note())], prs=[pr(30, 'CLOSED'), pr(31, 'MERGED')]),
            it(21, [comment(211, BOT, note(state='asking'), minutes=45)], labels=['ready-for-agent', 'needs-info']),
            it(22, [comment(221, BOT, note(state='asking'))]),
            it(23, [comment(231, BOT, note()), comment(232, BOT, note(agent='fleet')), comment(233, BOT, note())]),
            it(24, [comment(241, BOT, note(state='done'))], prs=[pr(34, 'MERGED')]),
            it(25, [comment(251, 'synthetic-outsider', note())], prs=[pr(35, 'MERGED')]),
            it(26, [comment(261, BOT, note(state='stopped (lease expired)'), minutes=90),
                    comment(262, BOT, note(state='asking'))], labels=['needs-info', 'held'], prs=[pr(36, 'OPEN')]),
            it(27, [comment(271, BOT, note())], prs=[pr(37, 'MERGED')], state='closed'),
            it(28, [comment(281, 'synthetic-owner', 'plain'), comment(282, BOT, 'plain'),
                    comment(283, BOT, note(agent='reviewer'), minutes=60)]),
        ]
        self.save()
        self.page = '2'
        before = (self.dir / 'world.json').read_bytes()
        result = self.run_status('check', '--repo', REPO)
        self.assertEqual((result.returncode, result.stderr), (1, ''))
        self.assertEqual(result.stdout,
                         '#20 note 201 builder working: pull request https://github.com/example/skills/pull/31 merged\n'
                         '#21 note 211 builder asking: lapsed, no edit for 30 minutes\n'
                         '#22 note 221 builder asking: no needs-info label\n'
                         '#23 note 233 builder working: note 231 holds the builder claim\n'
                         '#28 note 283 reviewer working: lapsed, no edit for 30 minutes\n')
        self.assertEqual((self.dir / 'world.json').read_bytes(), before)
        self.assertEqual({c['method'] for c in self.calls()}, {'GET', 'POST'})
        self.assertEqual({c['path'] for c in self.calls() if c['method'] == 'POST'}, {'graphql'})
        self.assertIn(('GET', 'repos/example/tracker/issues/28/comments?per_page=100&page=1'),
                      [(c['method'], c['path']) for c in self.calls()])

        self.world['issues'] = [it(24, [comment(241, BOT, note(state='done'))], prs=[pr(34, 'MERGED')]),
                                it(29, [], labels=['needs-info'])]
        self.save()
        clean = self.run_status('check', '--repo', REPO)
        self.assertEqual((clean.returncode, clean.stdout, clean.stderr), (0, '', ''))

    def test_check_that_cannot_read_says_so(self):
        # catches: a failed read reported as "no mismatch".
        self.world['repo'] = 'example/other'
        self.save()
        result = self.run_status('check', '--repo', REPO)
        self.assertEqual((result.returncode, result.stdout), (2, ''))
        self.assertIn('could not read', result.stderr)


if __name__ == '__main__':
    unittest.main()
