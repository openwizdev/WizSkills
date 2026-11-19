#!/usr/bin/env python3
"""P4 (#1254): status.py on a synthetic tracker with a fake `gh`.

Run: python3 -I skills/launch-fleet/scripts/test-status.py
Every value here is synthetic. The fake gh keeps the tracker in a JSON file,
logs every call, and refuses what GitHub refuses (editing another author's
comment). The expected bodies, labels and lines come from the contract,
contracts/agent-status.v1.md, never from status.py.
"""
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
MARKER = '<!-- openwiz.agent-status.v1 -->'

FAKE_GH = r'''
import json, os, sys
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
                   'closedByPullRequestsReferences': {'nodes': it.get('prs', [])}} for it in chunk]}}}})
assert '/'.join(seg[:3]) == 'repos/' + world['repo'], path
seg = seg[3:]
if method == 'GET' and seg == ['contents', 'docs', 'agents', 'fleet.md']:
    assert accept == 'Accept: application/vnd.github.raw'
    if world.get('fleet_md') is None: fail(404, 'Not Found')
    sys.stdout.write(world['fleet_md']); sys.exit(0)
if method == 'GET' and seg == ['labels']:
    out(page([{'name': l['name']} for l in world['labels']], query))
if method == 'POST' and seg == ['labels']:
    if any(l['name'].lower() == body['name'].lower() for l in world['labels']): fail(422, 'Validation Failed')
    world['labels'].append(body); save(); out(body)
if seg[0] == 'issues' and len(seg) == 2 and method == 'GET':
    it = issue(seg[1]); out({'number': it['number'], 'state': it['state'], 'labels': [{'name': l} for l in it['labels']]})
if seg[0] == 'issues' and seg[2:] == ['labels'] and method == 'POST':
    it = issue(seg[1])
    for l in body['labels']:
        if not any(x['name'] == l for x in world['labels']): world['labels'].append({'name': l})
        if l not in it['labels']: it['labels'].append(l)
    save(); out([{'name': l} for l in it['labels']])
if seg[0] == 'issues' and len(seg) == 4 and seg[2] == 'labels' and method == 'DELETE':
    it = issue(seg[1])
    if seg[3] not in it['labels']: fail(404, 'Label does not exist')
    it['labels'].remove(seg[3]); save(); out([{'name': l} for l in it['labels']])
if seg[0] == 'issues' and seg[2:] == ['comments'] and method == 'GET':
    it = issue(seg[1]); out(page([{'id': c['id'], 'user': {'login': c['author']} if c['author'] else None, 'body': c['body']} for c in it['comments']], query))
if seg[0] == 'issues' and seg[2:] == ['comments'] and method == 'POST':
    it = issue(seg[1]); world['next_id'] += 1
    c = {'id': world['next_id'], 'author': world['login'], 'body': body['body']}
    it['comments'].append(c); save(); out({'id': c['id'], 'body': c['body']})
if seg[:2] == ['issues', 'comments'] and len(seg) == 3 and method == 'PATCH':
    for it in world['issues']:
        for c in it['comments']:
            if c['id'] == int(seg[2]):
                if c['author'] != world['login']: fail(403, 'Must have admin rights to Repository.')
                c['body'] = body['body']; save(); out({'id': c['id'], 'body': c['body']})
    fail(404, 'Not Found')
fail(404, 'Not Found: ' + method + ' ' + path)
'''


def comment(cid, author, body):
    return {'id': cid, 'author': author, 'body': body}


def status_body(kind, harness, model, step, time, pr='none', preview='none'):
    """The text form the contract fixes, field by field."""
    return '\n'.join([MARKER, '**Agent status**', '',
                      '- **Kind:** ' + kind, '- **Harness:** ' + harness, '- **Model:** ' + model,
                      '- **Last step:** ' + step, '- **Time:** ' + time,
                      '- **Pull request:** ' + pr, '- **Preview:** ' + preview])


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
            'labels': [{'name': 'ready-for-agent'}, {'name': 'held', 'color': 'ededed', 'description': 'synthetic own'}],
            'issues': [{'number': 12, 'state': 'open', 'labels': ['ready-for-agent'], 'comments': [
                comment(101, 'synthetic-owner', 'launch-fleet: started'),
                # Anyone may comment on a public ticket: a planted marker is not a status.
                comment(102, 'synthetic-outsider', MARKER + '\nplanted'),
                comment(103, None, MARKER + '\nfrom a deleted account'),
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

    def run_status(self, *args):
        env = dict(os.environ, PATH=str(self.dir / 'bin') + ':' + os.environ['PATH'],
                   FAKE_GH_WORLD=str(self.dir / 'world.json'), FAKE_GH_LOG=str(self.dir / 'gh.log'),
                   FAKE_GH_PAGE=self.page)
        for key in ('GH_TOKEN', 'GITHUB_TOKEN', 'GH_REPO'):
            env.pop(key, None)
        return subprocess.run([sys.executable, '-I', str(SCRIPT), *args], env=env,
                              capture_output=True, text=True, timeout=60)

    def write(self, state, step, time, *extra, kind='builder'):
        return self.run_status('write', '--repo', REPO, '--ticket', '12', '--state', state, '--kind', kind,
                               '--harness', 'Claude Code', '--model', 'Opus 5.5 Medium',
                               '--step', step, '--time', time, *extra)

    def ticket(self, world=None):
        return next(it for it in (world or self.load())['issues'] if it['number'] == 12)


class Write(Tracker):
    def test_second_run_edits_the_one_status_comment_and_swaps_the_label(self):
        # catches: a second run posting another status comment, an old state label left on,
        # a missing label created again, or a stranger's planted marker taken as the status.
        self.save()
        first = self.write('building', 'started the build', '2030-01-02T03:00:00Z')
        self.assertEqual((first.returncode, first.stdout, first.stderr),
                         (0, '#12: building, status comment 9001 posted\n', ''))
        world = self.load()
        self.assertEqual(self.ticket(world)['labels'], ['ready-for-agent', 'building'])
        self.assertIn({'name': 'building', 'color': 'fbca04',
                       'description': 'An agent is building this ticket (openwiz.agent-status.v1)'}, world['labels'])
        self.assertEqual([c['id'] for c in self.ticket(world)['comments']], [101, 102, 103, 9001])
        self.assertEqual(self.ticket(world)['comments'][3]['body'],
                         status_body('builder', 'Claude Code', 'Opus 5.5 Medium', 'started the build', '2030-01-02T03:00:00Z'))

        pr = 'https://github.com/example/skills/pull/31'
        second = self.write('in-review', 'handed back; CI is green', '2030-01-02T04:00:00Z', '--pr', pr)
        self.assertEqual((second.returncode, second.stdout, second.stderr),
                         (0, '#12: in-review, status comment 9001 edited\n', ''))
        third = self.write('in-review', 'answered the review', '2030-01-02T05:00:00Z', '--pr', pr,
                           '--preview', 'https://31.example-site.pages.dev', kind='builder')
        self.assertEqual((third.returncode, third.stdout), (0, '#12: in-review, status comment 9001 edited\n'))
        world = self.load()
        self.assertEqual(self.ticket(world)['labels'], ['ready-for-agent', 'in-review'])
        self.assertEqual([c['id'] for c in self.ticket(world)['comments']], [101, 102, 103, 9001])
        self.assertEqual(self.ticket(world)['comments'][1]['body'], MARKER + '\nplanted')
        self.assertEqual(self.ticket(world)['comments'][3]['body'],
                         status_body('builder', 'Claude Code', 'Opus 5.5 Medium', 'answered the review',
                                     '2030-01-02T05:00:00Z', pr, 'https://31.example-site.pages.dev'))
        writes = [(c['method'], c['path']) for c in self.calls() if c['method'] != 'GET']
        self.assertEqual(writes, [
            ('POST', 'repos/example/tracker/labels'),
            ('POST', 'repos/example/tracker/issues/12/labels'),
            ('POST', 'repos/example/tracker/issues/12/comments'),
            ('POST', 'repos/example/tracker/labels'),
            ('DELETE', 'repos/example/tracker/issues/12/labels/building'),
            ('POST', 'repos/example/tracker/issues/12/labels'),
            ('PATCH', 'repos/example/tracker/issues/comments/9001'),
            ('PATCH', 'repos/example/tracker/issues/comments/9001'),
        ])

    def test_held_keeps_the_existing_label_and_none_clears_every_state(self):
        # catches: an existing label recreated or recoloured, or `none` leaving a state label on.
        self.ticket(self.world)['labels'] = ['ready-for-agent', 'building', 'in-review']
        self.save()
        held = self.write('held', 'held by the fleet', '2030-01-02T03:00:00Z', kind='fleet')
        self.assertEqual(held.returncode, 0, held.stderr)
        world = self.load()
        self.assertEqual(self.ticket(world)['labels'], ['ready-for-agent', 'held'])
        self.assertIn({'name': 'held', 'color': 'ededed', 'description': 'synthetic own'}, world['labels'])
        self.assertEqual([c for c in self.calls() if c['path'] == 'repos/example/tracker/labels' and c['method'] == 'POST'], [])
        clear = self.write('none', 'released the ticket', '2030-01-02T04:00:00Z', kind='fleet')
        self.assertEqual((clear.returncode, clear.stdout), (0, '#12: none, status comment 9001 edited\n'))
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent'])

    def test_a_status_comment_past_the_first_page_is_edited_not_posted_again(self):
        # catches: reading only the first page of comments and posting a second status comment.
        self.ticket(self.world)['comments'] += [comment(104, 'synthetic-owner', 'note'),
                                                comment(105, 'openwiz[bot]', MARKER + '\nold'),
                                                comment(106, 'Synthetic-Owner', MARKER + '\nlater')]
        self.save()
        self.page = '2'
        result = self.write('building', 'started the build', '2030-01-02T03:00:00Z')
        self.assertEqual((result.returncode, result.stdout), (0, '#12: building, status comment 105 edited\n'))
        comments = self.ticket()['comments']
        self.assertEqual([c['id'] for c in comments], [101, 102, 103, 104, 105, 106])
        self.assertEqual(comments[5]['body'], MARKER + '\nlater')

    def test_the_contract_example_is_what_the_writer_writes(self):
        # catches: the writer's text drifting from the contract the app parses.
        self.save()
        result = self.write('in-review', 'opened the pull request; CI is running', '2030-01-02T03:04:05Z',
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
                result = self.write('building', 'started the build', '2030-01-02T03:00:00Z')
                self.assertEqual((result.returncode, result.stdout), (2, ''))
                self.assertIn('record authors', result.stderr)
                self.assertEqual([c['method'] for c in self.calls()], ['GET'])
                self.assertEqual(self.load(), self.world)


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
    ('--step', 'Robin said "ship it"'),
    ('--step', 'Robin said \u201cship it\u201d'),
    ('--step', '> ship it'),
]
# Shape refusals: the schema refuses them too.
BAD_SHAPE = [
    ('--kind', 'helper'),
    ('--step', ''),
    ('--step', 'two\nlines'),
    ('--step', 'tab\there'),
    ('--step', 'x' * 301),
    ('--model', 'm' * 61),
    ('--time', '2030-01-02 03:00:00'),
    ('--pr', 'https://github.com/example/skills/issues/31'),
    ('--pr', '#31'),
    ('--preview', 'javascript:alert(1)'),
    ('--preview', 'http://31.example-site.pages.dev'),
    ('--preview', 'https://example.invalid/<script>'),
]
GOOD_SHAPE = [
    ('--kind', 'reviewer'),
    ('--step', 'x' * 300),
    ('--model', 'm' * 60),
    ('--step', 'checked https://github.com/acme/home/pull/1 and a/home/b'),
    ('--pr', 'https://github.com/example/skills/pull/31'),
    ('--preview', 'https://31.example-site.pages.dev/app?x=1'),
]
FIELD = {'--kind': 'kind', '--harness': 'harness', '--model': 'model', '--step': 'step',
         '--time': 'time', '--pr': 'pr', '--preview': 'preview'}


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
    if 'const' in node and value != node['const']:
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
        values = {'--kind': 'builder', '--harness': 'Claude Code', '--model': 'Opus 5.5 Medium',
                  '--step': 'started the build', '--time': '2030-01-02T03:00:00Z'}
        values[flag] = value
        args = ['write', '--repo', REPO, '--ticket', '12', '--state', 'building']
        for key, item in values.items():
            args += [key, item]
        return args, values

    def test_private_or_bad_text_is_refused_before_any_call(self):
        # catches: a thread id, machine path, CloudRoom id, quoted words or a bad shape
        # reaching the public status comment, or a refusal that comes after a write.
        self.save()
        for flag, value in PRIVATE + BAD_SHAPE:
            with self.subTest(flag=flag, value=value):
                result = self.run_status(*self.args(flag, value)[0])
                self.assertEqual((result.returncode, result.stdout), (2, ''))
                self.assertRegex(result.stderr, r'^status\.py: refused: ' + FIELD[flag] + r': ')
                self.assertNotIn(value, result.stderr) if value else None
                self.assertEqual(self.calls(), [])
        self.assertEqual(self.load(), self.world)

    def test_the_schema_and_the_writer_agree_on_each_shape(self):
        # catches: the schema the app validates with and the writer accepting different values.
        schema = json.loads(SCHEMA.read_text())
        base = {'schema': 'openwiz.agent-status.v1', 'kind': 'builder', 'harness': 'Claude Code',
                'model': 'Opus 5.5 Medium', 'step': 'started the build', 'time': '2030-01-02T03:00:00Z',
                'pr': 'none', 'preview': 'none'}
        self.assertTrue(valid(schema, schema, base))
        for flag, value, good in [(f, v, False) for f, v in BAD_SHAPE] + [(f, v, True) for f, v in GOOD_SHAPE]:
            with self.subTest(flag=flag, value=value):
                self.save()
                result = self.run_status(*self.args(flag, value)[0])
                self.assertEqual(result.returncode == 0, good, result.stderr)
                self.assertEqual(valid(schema, schema, dict(base, **{FIELD[flag]: value})), good)
        self.assertEqual(schema['$defs']['label']['enum'], ['building', 'in-review', 'needs-you', 'held'])


class Check(Tracker):
    def test_check_lists_each_planted_mismatch_and_changes_nothing(self):
        # catches: a stale state label the wake misses, a closed ticket or an unlabelled one
        # reported, a page of issues skipped, or a check that writes.
        def pr(n, state):
            return {'number': n, 'state': state, 'url': 'https://github.com/example/skills/pull/%d' % n}
        def it(n, labels, prs=(), state='open'):
            return {'number': n, 'state': state, 'labels': labels, 'comments': [], 'prs': list(prs)}
        self.world['issues'] = [
            it(20, ['ready-for-agent', 'building'], [pr(30, 'CLOSED'), pr(31, 'MERGED')]),
            it(21, ['ready-for-agent', 'in-review'], [pr(32, 'CLOSED')]),
            it(22, ['ready-for-agent', 'in-review'], [pr(33, 'OPEN')]),
            it(23, ['building', 'held']),
            it(24, ['building'], [pr(34, 'CLOSED')]),
            it(25, ['needs-you'], [pr(35, 'MERGED')]),
            it(26, ['ready-for-agent'], [pr(36, 'MERGED')]),
            it(27, ['in-review'], [pr(37, 'MERGED')], state='closed'),
            it(28, ['held'], [pr(38, 'MERGED')]),
        ]
        self.save()
        self.page = '2'
        before = (self.dir / 'world.json').read_bytes()
        result = self.run_status('check', '--repo', REPO)
        self.assertEqual((result.returncode, result.stderr), (1, ''))
        self.assertEqual(result.stdout,
                         '#20 building: pull request https://github.com/example/skills/pull/31 merged\n'
                         '#21 in-review: no open pull request closes it\n'
                         '#23 building, held: more than one state label\n'
                         '#25 needs-you: pull request https://github.com/example/skills/pull/35 merged\n')
        self.assertEqual((self.dir / 'world.json').read_bytes(), before)
        self.assertEqual([c['path'] for c in self.calls()], ['graphql'] * 4)

        self.world['issues'] = [it(22, ['in-review'], [pr(33, 'OPEN')]), it(26, [], [pr(36, 'MERGED')])]
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
