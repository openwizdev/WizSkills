#!/usr/bin/env python3
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
REPO = 'synthetic-owner/synthetic-repo'
FLEET_MD = ('# Fleet settings\n\n## GitHub identity\n\n| Setting | Value |\n| --- | --- |\n'
            '| Record authors | `openwiz[bot]`, `synthetic-owner` |\n')

FAKE_GH = r'''
import hashlib, json, os, re, sys
from urllib.parse import parse_qs, urlsplit
W = json.load(open(os.environ['FAKE_WORLD']))
LOG = os.environ['FAKE_LOG']
args = sys.argv[1:]

def log(line):
    with open(LOG, 'a') as f:
        f.write(line + '\n')

def flag(name):
    out = {}
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            k, _, v = args[i + 1].partition('=')
            out[k] = v
    return out

def gql_author(c):
    if c['author'].endswith('[bot]'):
        return {'login': c['author'][:-5], '__typename': 'Bot'}
    return {'login': c['author'], '__typename': 'User'}

def gql_comments(item, after, first):
    start = int(after or 0)
    rows = item['comments'][start:start + first]
    nodes = [{'databaseId': c['id'], 'author': gql_author(c), 'createdAt': c['created_at'],
              'updatedAt': c['updated_at'], 'body': c['body']} for c in rows]
    end = start + len(rows)
    return {'totalCount': len(item['comments']), 'nodes': nodes,
            'pageInfo': {'hasNextPage': end < len(item['comments']), 'endCursor': str(end)}}

def gql_item(item, cfirst):
    node = {'number': item['number'], 'title': item['title'], 'state': 'OPEN', 'body': item['body'],
            'updatedAt': item['updated_at'],
            'labels': {'nodes': [{'name': n} for n in item['labels']], 'pageInfo': {'hasNextPage': False}},
            'comments': gql_comments(item, None, cfirst)}
    if item['kind'] == 'pull':
        node['headRefOid'] = item['head']
        node['closingIssuesReferences'] = {
            'nodes': [{'number': n, 'repository': {'nameWithOwner': W['repo']}} for n in item['closes']],
            'pageInfo': {'hasNextPage': False}}
    return node

def faults(kind, page):
    return [f for f in W.get('faults', []) if f['kind'] == kind and f.get('page', 1) == page]

def graphql():
    q = flag('-f').get('query', '')
    v = {**flag('-f'), **flag('-F')}
    op = re.search(r'query (\w+)', q).group(1)
    log('graphql ' + op)
    if W.get('graphql_error'):
        print(json.dumps({'data': None, 'errors': [{'message': 'synthetic failure'}]}))
        return 0
    rate = {'remaining': W.get('mid', W['rate'])['graphql'], 'limit': 5000}
    if op == 'SnapshotComments':
        item = next(i for i in W['items'] if i['number'] == int(v['number']))
        conn = gql_comments(item, v.get('after'), int(v['first']))
        page = int(v.get('after') or 0) // int(v['first']) + 1
        for f in faults('comments', page):
            conn['nodes'][f['at']] = None
        field = 'pullRequest' if item['kind'] == 'pull' else 'issue'
        print(json.dumps({'data': {'rateLimit': rate, 'repository': {'issueOrPullRequest': {'comments': conn}}}}))
        return 0
    kind = 'pull' if op == 'SnapshotPulls' else 'issue'
    rows = [i for i in W['items'] if i['kind'] == kind]
    first, start = int(v['first']), int(v.get('after') or 0)
    chunk = rows[start:start + first]
    nodes = [gql_item(i, int(v['cfirst'])) for i in chunk]
    page = start // first + 1
    for f in faults(kind + 's', page):
        if f.get('drop'):
            nodes.pop()
        else:
            nodes[f['at']] = None
    end = start + len(chunk)
    conn = {'totalCount': len(rows), 'nodes': nodes,
            'pageInfo': {'hasNextPage': end < len(rows), 'endCursor': str(end)}}
    repo = {'issues' if kind == 'issue' else 'pullRequests': conn,
            'fleet': {'text': W['fleet_md']}}
    print(json.dumps({'data': {'rateLimit': rate, 'repository': repo}}))
    return 0

def rest_item(i):
    out = {'number': i['number'], 'title': i['title'], 'state': 'open', 'body': i['body'],
           'updated_at': i['updated_at'], 'labels': [{'name': n} for n in i['labels']],
           'comments': len(i['comments'])}
    if i['kind'] == 'pull':
        out['pull_request'] = {'url': 'synthetic'}
    return out

def rest(path, headers):
    url = urlsplit(path)
    qs = {k: v[0] for k, v in parse_qs(url.query).items()}
    per, page = int(qs.get('per_page', 30)), int(qs.get('page', 1))
    parts = url.path.split('/')
    raw = False
    if url.path == 'repos/%s/issues' % W['repo']:
        rows, kind = [rest_item(i) for i in W['items']], 'issues'
    elif url.path == 'repos/%s/pulls' % W['repo']:
        rows, kind = [{'number': i['number'], 'head': {'sha': i['head']}} for i in W['items']
                      if i['kind'] == 'pull'], 'pulls'
    elif parts[-1] == 'comments':
        item = next(i for i in W['items'] if i['number'] == int(parts[-2]))
        rows = [{'id': c['id'], 'user': {'login': c['author']}, 'created_at': c['created_at'],
                 'updated_at': c['updated_at'], 'body': c['body']} for c in item['comments']]
        kind = 'comments'
    elif url.path == 'repos/%s/contents/docs/agents/fleet.md' % W['repo']:
        rows, kind, raw = None, 'fleet', True
    else:
        log('rest 404 ' + path)
        sys.stderr.write('gh: Not Found (HTTP 404)\n')
        return 1
    if raw:
        body, link = W['fleet_md'], ''
    else:
        chunk = rows[(page - 1) * per:page * per]
        for f in faults('rest-' + kind, page):
            if f.get('drop'):
                chunk.pop()
            else:
                chunk[f['at']] = None
        body = json.dumps(chunk)
        link = ''
        if page * per < len(rows):
            nxt = path.replace('page=%d' % page, 'page=%d' % (page + 1))
            link = 'Link: <https://api.github.com/%s>; rel="next"\r\n' % nxt
    etag = 'W/"%s"' % hashlib.sha256(body.encode()).hexdigest()[:20]
    remaining = 'X-Ratelimit-Remaining: %d\r\n' % W.get('mid', W['rate'])['core']
    if headers.get('if-none-match') == etag:
        log('rest 304 ' + path)
        sys.stdout.write('HTTP/2.0 304 Not Modified\r\nEtag: %s\r\n%s\r\n' % (etag, remaining))
        sys.stderr.write('gh: HTTP 304\n')
        return 1
    log('rest 200 ' + path + (' conditional' if 'if-none-match' in headers else ''))
    if '-i' in args or '--include' in args:
        sys.stdout.write('HTTP/2.0 200 OK\r\nEtag: %s\r\n%s%s\r\n' % (etag, link, remaining))
    sys.stdout.write(body)
    return 0

def main():
    if args[:2] == ['api', 'rate_limit']:
        log('rate_limit')
        r = W['rate']
        print(json.dumps({'resources': {'core': {'remaining': r['core'], 'limit': 5000},
                                        'graphql': {'remaining': r['graphql'], 'limit': 5000}}}))
        return 0
    if args[:2] == ['api', 'graphql']:
        return graphql()
    if args[0] == 'api':
        headers = {}
        for i, a in enumerate(args):
            if a == '-H':
                k, _, val = args[i + 1].partition(':')
                headers[k.strip().lower()] = val.strip()
        path = next(a for a in args[1:] if a.startswith('repos/'))
        return rest(path, headers)
    log('unexpected ' + ' '.join(args))
    return 1

sys.exit(main())
'''


def comment(cid, author, body, minute=0):
    t = '2026-01-01T00:%02d:00Z' % (minute % 60)
    return {'id': cid, 'author': author, 'created_at': t, 'updated_at': t, 'body': body}


def item(number, kind='issue', comments=(), **extra):
    value = {'number': number, 'kind': kind, 'title': 'Synthetic %s %d' % (kind, number),
             'body': 'Body of %d.' % number, 'labels': ['ready-for-agent'], 'updated_at': '2026-01-01T00:00:00Z',
             'head': None, 'closes': [], 'comments': list(comments)}
    if kind == 'pull':
        value.update(head='%040x' % number, closes=[1], body='Closes #1\n\nBody of %d.' % number)
    value.update(extra)
    return value


def busy_world():
    items = [item(n) for n in range(1, 61)]
    items[6]['comments'] = [comment(10000 + k, 'someone-else' if k % 3 else 'synthetic-owner',
                                    'comment %d' % k, k) for k in range(250)]
    items += [item(n, 'pull') for n in (61, 62, 63)]
    return items


class World:

    def __init__(self, test, items, core=5000, graphql=5000, **extra):
        self.dir = Path(tempfile.mkdtemp())
        test.addCleanup(subprocess.run, ['rm', '-rf', str(self.dir)])
        bin_dir = self.dir / 'bin'
        bin_dir.mkdir()
        (self.dir / 'fake_gh.py').write_text(FAKE_GH)
        gh = bin_dir / 'gh'
        gh.write_text('#!/bin/sh\nexec "%s" -I "%s" "$@"\n' % (sys.executable, self.dir / 'fake_gh.py'))
        gh.chmod(0o755)
        self.path, self.log = self.dir / 'world.json', self.dir / 'calls.log'
        self.log.write_text('')
        self.save({'repo': REPO, 'fleet_md': FLEET_MD, 'items': items, 'faults': [],
                   'rate': {'core': core, 'graphql': graphql}, **extra})
        env = {k: v for k, v in os.environ.items() if k != 'OPENWIZ_GITHUB_APP_KEY'}
        self.env = dict(env, PATH='%s:%s' % (bin_dir, os.environ['PATH']), FAKE_WORLD=str(self.path),
                        FAKE_LOG=str(self.log))
        self.out = self.dir / 'snap' / 'snapshot.json'
        self.out.parent.mkdir()

    def save(self, value):
        self.path.write_text(json.dumps(value))

    def update(self, **changes):
        value = json.loads(self.path.read_text())
        value.update(changes)
        self.save(value)

    def run(self, *args):
        r = subprocess.run([sys.executable, '-I', str(HERE / 'snapshot.py'), *map(str, args)],
                           capture_output=True, text=True, env=self.env, cwd=self.dir, timeout=120)
        return r.returncode, r.stdout, r.stderr

    def write(self):
        return self.run('write', REPO, self.out)

    def calls(self):
        lines = self.log.read_text().splitlines()
        self.log.write_text('')
        return lines

    def snapshot(self):
        return json.loads(self.out.read_text())


def by_number(snap):
    return {i['number']: i for i in snap['items']}


class GraphqlWrite(unittest.TestCase):

    def test_two_page_list_and_long_history_read_in_full(self):
        w = World(self, busy_world())
        code, out, err = w.write()
        self.assertEqual(code, 0, err)
        snap = w.snapshot()
        self.assertEqual((snap['repo'], snap['complete'], snap['via']), (REPO, True, 'graphql'))
        datetime.strptime(snap['read_at'], '%Y-%m-%dT%H:%M:%SZ')
        items = by_number(snap)
        self.assertEqual(sorted(items), list(range(1, 64)))
        seven = items[7]
        self.assertEqual([c['id'] for c in seven['comments']], [10000 + k for k in range(250)])
        self.assertEqual(seven['comments'][249]['body'], 'comment 249')
        self.assertEqual(set(seven['comments'][0]), {'id', 'author', 'created_at', 'updated_at', 'body'})
        pr = items[62]
        self.assertEqual((pr['kind'], pr['head'], pr['closing_issues']), ('pull', '%040x' % 62, [REPO + '#1']))
        self.assertEqual((items[3]['kind'], items[3]['state'], items[3]['labels']),
                         ('issue', 'OPEN', ['ready-for-agent']))
        self.assertEqual(items[3]['updated_at'], '2026-01-01T00:00:00Z')
        calls = w.calls()
        self.assertEqual(calls[0], 'rate_limit')
        self.assertEqual(sorted(calls[1:]), sorted(['graphql SnapshotIssues'] * 2 + ['graphql SnapshotPulls']
                                                   + ['graphql SnapshotComments'] * 2))

    def test_partial_issue_page_writes_nothing(self):
        w = World(self, busy_world())
        w.update(faults=[{'kind': 'issues', 'page': 2, 'drop': True}])
        w.out.write_text('previous snapshot')
        code, out, err = w.write()
        self.assertEqual(code, 2, err)
        self.assertEqual(w.out.read_text(), 'previous snapshot')
        self.assertEqual(sorted(p.name for p in w.out.parent.iterdir()), ['snapshot.json'])

    def test_null_comment_node_writes_nothing(self):
        w = World(self, busy_world())
        w.update(faults=[{'kind': 'comments', 'page': 3, 'at': 5}])
        code, out, err = w.write()
        self.assertEqual(code, 2, err)
        self.assertFalse(w.out.exists())

    def test_null_pull_node_writes_nothing(self):
        w = World(self, busy_world())
        w.update(faults=[{'kind': 'pulls', 'page': 1, 'at': 0}])
        self.assertEqual(w.write()[0], 2)
        self.assertFalse(w.out.exists())

    def test_graphql_allowance_falling_under_1500_mid_read_writes_nothing(self):
        w = World(self, busy_world(), mid={'core': 5000, 'graphql': 1499})
        code, out, err = w.write()
        self.assertEqual(code, 2)
        self.assertIn('1,500', err)
        self.assertFalse(w.out.exists())

    def test_graphql_error_writes_nothing(self):
        w = World(self, busy_world(), graphql_error=True)
        self.assertEqual(w.write()[0], 2)
        self.assertFalse(w.out.exists())


class RestWrite(unittest.TestCase):

    def rest_world(self, **extra):
        items = [item(n) for n in range(1, 121)]
        items[4]['comments'] = [comment(20000 + k, 'synthetic-owner', 'c%d' % k, k) for k in range(130)]
        items += [item(121, 'pull', comments=[comment(30000, 'openwiz[bot]', 'launch-fleet: merge queued')])]
        return World(self, items, core=4000, graphql=2000, **extra)

    def test_reads_by_rest_when_graphql_is_lower_and_revalidates_with_304s(self):
        w = self.rest_world()
        code, out, err = w.write()
        self.assertEqual(code, 0, err)
        first = w.snapshot()
        self.assertEqual(first['via'], 'rest')
        items = by_number(first)
        self.assertEqual(sorted(items), list(range(1, 122)))
        self.assertEqual([c['id'] for c in items[5]['comments']], [20000 + k for k in range(130)])
        self.assertEqual((items[121]['kind'], items[121]['head'], items[121]['closing_issues']),
                         ('pull', '%040x' % 121, [REPO + '#1']))
        calls = w.calls()
        self.assertFalse([c for c in calls if c.startswith('graphql')], calls)
        self.assertTrue(all(c.startswith('rest 200 ') and not c.endswith('conditional') for c in calls[1:]), calls)
        code, out, err = w.write()
        self.assertEqual(code, 0, err)
        calls = w.calls()
        rest = [c for c in calls if c.startswith('rest')]
        self.assertEqual(len(rest), 7, calls)
        self.assertEqual([c for c in rest if not c.startswith('rest 304 ')], [])
        second = w.snapshot()
        self.assertEqual(second['items'], first['items'])

    def test_changed_page_is_read_again_and_the_rest_stay_304(self):
        w = self.rest_world()
        self.assertEqual(w.write()[0], 0)
        w.calls()
        world = json.loads(w.path.read_text())
        world['items'][119]['title'] = 'Renamed'
        w.save(world)
        self.assertEqual(w.write()[0], 0)
        calls = w.calls()
        fresh = [c for c in calls if c.startswith('rest 200 ')]
        self.assertEqual(fresh, ['rest 200 repos/%s/issues?state=open&per_page=100&page=2 conditional' % REPO])
        self.assertEqual(by_number(w.snapshot())[120]['title'], 'Renamed')

    def test_short_rest_page_before_the_last_writes_nothing(self):
        w = self.rest_world(faults=[{'kind': 'rest-issues', 'page': 1, 'drop': True}])
        self.assertEqual(w.write()[0], 2)
        self.assertFalse(w.out.exists())

    def test_null_rest_comment_writes_nothing(self):
        w = self.rest_world(faults=[{'kind': 'rest-comments', 'page': 2, 'at': 0}])
        self.assertEqual(w.write()[0], 2)
        self.assertFalse(w.out.exists())

    def test_rest_allowance_falling_under_1500_mid_read_writes_nothing(self):
        w = self.rest_world(mid={'core': 1499, 'graphql': 2000})
        code, out, err = w.write()
        self.assertEqual(code, 2)
        self.assertIn('1,500', err)
        self.assertFalse(w.out.exists())

    def test_both_allowances_under_1500_write_nothing(self):
        w = World(self, busy_world(), core=1499, graphql=1200)
        w.out.write_text('previous snapshot')
        code, out, err = w.write()
        self.assertEqual(code, 2)
        self.assertIn('1,500', err)
        self.assertEqual(w.calls(), ['rate_limit'])
        self.assertEqual(w.out.read_text(), 'previous snapshot')

    def test_graphql_under_1500_with_rest_above_reads_rest(self):
        w = self.rest_world()
        w.update(rate={'core': 1600, 'graphql': 1400})
        self.assertEqual(w.write()[0], 0)
        self.assertEqual(w.snapshot()['via'], 'rest')


class Facts(unittest.TestCase):

    def written(self, items, **rate):
        w = World(self, items, **rate)
        code, out, err = w.write()
        self.assertEqual(code, 0, err)
        return w

    def test_counts_only_record_author_comments_newest_first(self):
        comments = [comment(1, 'someone-else', 'not a record', 1),
                    comment(2, 'synthetic-owner', 'owner record', 2),
                    comment(3, 'openwiz[bot]', 'launch-fleet: started', 3),
                    comment(4, 'openwiz', 'a user named like the bot', 4)]
        w = self.written([item(9, comments=comments, labels=['ready-for-agent', 'P2'])])
        code, out, err = w.run('facts', w.out, 9)
        self.assertEqual(code, 0, err)
        self.assertIn('Synthetic issue 9', out)
        self.assertIn('ready-for-agent, P2', out)
        self.assertIn('Body of 9.', out)
        self.assertNotIn('not a record', out)
        self.assertNotIn('a user named like the bot', out)
        self.assertIn('launch-fleet: started', out)
        self.assertLess(out.index('launch-fleet: started'), out.index('owner record'))
        self.assertIn('2 of 4 comments', out)

    def test_rest_snapshot_reads_the_same_authors(self):
        comments = [comment(3, 'openwiz[bot]', 'launch-fleet: started', 3), comment(1, 'someone-else', 'nope', 1)]
        w = self.written([item(9, comments=comments)], core=4000, graphql=2000)
        code, out, err = w.run('facts', w.out, 9)
        self.assertEqual(code, 0, err)
        self.assertIn('launch-fleet: started', out)
        self.assertNotIn('nope', out)

    def test_caps_the_block_with_a_stated_cut(self):
        comments = [comment(k, 'synthetic-owner', ('record %d ' % k) + 'x' * 4000, k) for k in range(40)]
        w = self.written([item(9, comments=comments)])
        code, out, err = w.run('facts', w.out, 9)
        self.assertEqual(code, 0, err)
        self.assertLessEqual(len(out.encode()), 60 * 1024)
        self.assertIn('record 39 ', out)
        self.assertNotIn('record 0 ', out)
        self.assertIn('cut', out.splitlines()[-1])
        self.assertIn('60 KB', out.splitlines()[-1])

    def test_caps_a_huge_body(self):
        w = self.written([item(9, body='y' * 70000)])
        code, out, err = w.run('facts', w.out, 9)
        self.assertEqual(code, 0, err)
        self.assertLessEqual(len(out.encode()), 60 * 1024)
        self.assertIn('60 KB', out.splitlines()[-1])

    def test_refuses_stale_incomplete_or_missing(self):
        w = self.written([item(9)])
        snap = w.snapshot()
        for name, change in [('stale', {'read_at': (datetime.now(timezone.utc) - timedelta(minutes=31))
                                         .strftime('%Y-%m-%dT%H:%M:%SZ')}),
                             ('incomplete', {'complete': False}),
                             ('no flag', {'complete': None})]:
            with self.subTest(name):
                w.out.write_text(json.dumps({**snap, **change}))
                code, out, err = w.run('facts', w.out, 9)
                self.assertEqual((code, out), (2, ''), err)
        w.out.write_text(json.dumps(snap))
        self.assertEqual(w.run('facts', w.out, 9)[0], 0)
        self.assertEqual(w.run('facts', w.out, 10)[:2], (2, ''))
        w.out.write_text('{not json')
        self.assertEqual(w.run('facts', w.out, 9)[:2], (2, ''))

    def test_fresh_within_30_minutes_is_served(self):
        w = self.written([item(9)])
        snap = w.snapshot()
        snap['read_at'] = (datetime.now(timezone.utc) - timedelta(minutes=29)).strftime('%Y-%m-%dT%H:%M:%SZ')
        w.out.write_text(json.dumps(snap))
        self.assertEqual(w.run('facts', w.out, 9)[0], 0)


if __name__ == '__main__':
    unittest.main()
