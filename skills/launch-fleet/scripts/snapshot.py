#!/usr/bin/env python3
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

USAGE = """One read of a repository's open work per wake (#2625, spec #2428 FR8).

  snapshot.py write OWNER/NAME OUT   read every open issue and pull request with
                                     every comment into OUT, atomically
  snapshot.py facts OUT N            print issue or pull request N's bounded facts

`write` checks `gh api rate_limit` (free) first and reads through whichever of
GraphQL or REST has more left, refusing while that is under 1,500. REST pages go
out with `If-None-Match` and the ETags saved beside OUT (`OUT.etags`), so an
unchanged page is a free 304. Any partial page, null node, count mismatch or
error writes nothing. `facts` refuses a snapshot that is incomplete, older than
30 minutes or has no N. It shows only record authors' comments, read from the
repository's `docs/agents/fleet.md` at write time the way post.py reads them.

Exit 0 done, 2 refused or unreadable (the reason on stderr). Python 3.11+
standard library and `gh`.
"""

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('launch_fleet_grants', HERE / 'grants.py')
grants = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(grants)

REPO = re.compile(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+')
RESERVE = 1500
FRESH = timedelta(minutes=30)
CAP, CUT_ROOM = 60 * 1024, 1024
DELETED_ACCOUNT = 'ghost'
PAGE, COMMENTS, REST_PAGE = 50, 100, 100
STAMP = '%Y-%m-%dT%H:%M:%SZ'
CLOSES = re.compile(r'\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+([A-Za-z0-9-]+/[A-Za-z0-9_.-]+)?#(\d+)\b',
                    re.I)


class Stop(Exception):
    pass


def need(ok, why):
    if not ok:
        raise Stop(why)


def gh(*args):
    try:
        r = subprocess.run(['gh', *args], capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Stop(f'gh did not run: {type(e).__name__}')
    return r


def as_json(text, what):
    try:
        return json.loads(text)
    except ValueError:
        raise Stop(f'{what}: unreadable answer')


def allowances():
    r = gh('api', 'rate_limit')
    need(r.returncode == 0, 'rate_limit unreadable')
    res = as_json(r.stdout, 'rate_limit').get('resources') or {}
    left = {k: (res.get(k) or {}).get('remaining') for k in ('graphql', 'core')}
    need(all(type(v) is int for v in left.values()), 'rate_limit names no remaining allowance')
    return left


COMMENT_FIELDS = ('totalCount pageInfo { hasNextPage endCursor } '
                  'nodes { databaseId author { login __typename } createdAt updatedAt body }')
ITEM_FIELDS = ('number title state body updatedAt labels(first: 100) { pageInfo { hasNextPage } nodes { name } } '
               'comments(first: $cfirst) { %s }' % COMMENT_FIELDS)
LIST = ('query %s($owner: String!, $name: String!, $first: Int!, $cfirst: Int!, $after: String) { '
        'rateLimit { remaining } repository(owner: $owner, name: $name) { '
        'fleet: object(expression: "HEAD:docs/agents/fleet.md") { ... on Blob { text } } '
        '%s(states: OPEN, first: $first, after: $after, orderBy: {field: CREATED_AT, direction: ASC}) { '
        'totalCount pageInfo { hasNextPage endCursor } nodes { %s } } } }')
ISSUES = LIST % ('SnapshotIssues', 'issues', ITEM_FIELDS)
PULLS = LIST % ('SnapshotPulls', 'pullRequests', ITEM_FIELDS + ' headRefOid closingIssuesReferences(first: 100) '
                '{ pageInfo { hasNextPage } nodes { number repository { nameWithOwner } } }')
MORE = ('query SnapshotComments($owner: String!, $name: String!, $number: Int!, $first: Int!, $after: String) { '
        'rateLimit { remaining } repository(owner: $owner, name: $name) { issueOrPullRequest(number: $number) { '
        '... on Issue { comments(first: $first, after: $after) { %s } } '
        '... on PullRequest { comments(first: $first, after: $after) { %s } } } } }' % (COMMENT_FIELDS, COMMENT_FIELDS))


def graphql(query, **variables):
    args = ['api', 'graphql', '-f', 'query=' + query]
    for k, v in variables.items():
        if v is not None:
            args += ['-F' if type(v) is int else '-f', f'{k}={v}']
    r = gh(*args)
    data = as_json(r.stdout, 'GraphQL') if r.stdout.strip() else None
    need(r.returncode == 0 and isinstance(data, dict) and not data.get('errors'), 'GraphQL read failed')
    data = data.get('data')
    need(isinstance(data, dict) and isinstance(data.get('repository'), dict), 'GraphQL answer has no repository')
    left = (data.get('rateLimit') or {}).get('remaining')
    need(type(left) is int and left >= RESERVE, 'the GraphQL allowance fell under 1,500 mid-read')
    return data['repository']


def connection(conn, what):
    need(isinstance(conn, dict) and type(conn.get('nodes')) is list and isinstance(conn.get('pageInfo'), dict),
         f'partial page: {what}')
    need(all(isinstance(n, dict) for n in conn['nodes']), f'null node: {what}')
    info = conn['pageInfo']
    need(type(info.get('hasNextPage')) is bool, f'partial page: {what}')
    need(not info['hasNextPage'] or type(info.get('endCursor')) is str, f'partial page: {what}')
    return conn['nodes'], info['hasNextPage'], info.get('endCursor')


def stamp(value, number):
    try:
        datetime.strptime(value, STAMP)
    except (TypeError, ValueError):
        raise Stop(f'null node: #{number} has an unreadable time')
    return value


def names(labels, number):
    need(all(isinstance(x, dict) and type(x.get('name')) is str for x in labels), f'null node: #{number} label')
    return [x['name'] for x in labels]


def gql_login(author):
    if author is None:
        return DELETED_ACCOUNT
    need(isinstance(author, dict) and type(author.get('login')) is str, 'null node: comment author')
    return author['login'] + '[bot]' if author.get('__typename') == 'Bot' else author['login']


def gql_comments(owner, name, number, first_conn):
    nodes, more, cursor = connection(first_conn, f'#{number} comments')
    total, out = first_conn.get('totalCount'), list(nodes)
    while more:
        repo = graphql(MORE, owner=owner, name=name, number=number, first=COMMENTS, after=cursor)
        conn = ((repo.get('issueOrPullRequest') or {}).get('comments'))
        nodes, more, cursor = connection(conn, f'#{number} comments')
        out += nodes
    need(type(total) is int and total == len(out), f'partial page: #{number} has {total} comments, read {len(out)}')
    comments = []
    for c in out:
        need(type(c.get('databaseId')) is int and type(c.get('body')) is str, f'null node: #{number} comment')
        comments.append({'id': c['databaseId'], 'author': gql_login(c.get('author')),
                         'created_at': stamp(c.get('createdAt'), number), 'updated_at': stamp(c.get('updatedAt'), number),
                         'body': c['body']})
    return comments


def gql_item(owner, name, node, kind):
    number = node.get('number')
    need(type(number) is int and type(node.get('title')) is str, 'null node: an item')
    labels, more, _ = connection(node.get('labels'), f'#{number} labels')
    need(not more, f'#{number} has over 100 labels; refusing a partial list')
    need(node.get('state') in ('OPEN',) and type(node.get('body')) is str, f'null node: #{number}')
    item = {'number': number, 'kind': kind, 'title': node['title'], 'state': node['state'],
            'labels': names(labels, number), 'body': node['body'],
            'updated_at': stamp(node.get('updatedAt'), number), 'head': None, 'closing_issues': [],
            'comments': gql_comments(owner, name, number, node.get('comments'))}
    if kind == 'pull':
        need(type(node.get('headRefOid')) is str, f'null node: #{number} head')
        refs, more, _ = connection(node.get('closingIssuesReferences'), f'#{number} closing issues')
        need(not more, f'#{number} closes over 100 issues; refusing a partial list')
        item['head'] = node['headRefOid']
        item['closing_issues'] = ['%s#%d' % ((r.get('repository') or {}).get('nameWithOwner'), r.get('number'))
                                  for r in refs]
    return item


def read_graphql(repo):
    owner, name = repo.split('/')
    items, fleet_md = [], None
    for query, field, kind in ((ISSUES, 'issues', 'issue'), (PULLS, 'pullRequests', 'pull')):
        cursor, got, total = None, 0, None
        while True:
            page = graphql(query, owner=owner, name=name, first=PAGE, cfirst=COMMENTS, after=cursor)
            fleet_md = ((page.get('fleet') or {}).get('text')) if fleet_md is None else fleet_md
            conn = page.get(field)
            nodes, more, cursor = connection(conn, field)
            total = conn.get('totalCount') if total is None else total
            got += len(nodes)
            items += [gql_item(owner, name, n, kind) for n in nodes]
            if not more:
                break
        need(type(total) is int and total == got, f'partial page: {total} open {field}, read {got}')
    return items, fleet_md


def rest(path, cache, raw=False):
    args = ['api', '-i', path]
    if raw:
        args += ['-H', 'Accept: application/vnd.github.raw+json']
    saved = cache.get(path)
    if saved:
        args += ['-H', 'If-None-Match: ' + saved['etag']]
    r = gh(*args)
    head, sep, body = r.stdout.replace('\r\n', '\n').partition('\n\n')
    lines = head.split('\n')
    status = lines[0].split(' ')[1] if len(lines[0].split(' ')) > 1 else ''
    headers = {}
    for line in lines[1:]:
        k, _, v = line.partition(':')
        headers[k.strip().lower()] = v.strip()
    left = headers.get('x-ratelimit-remaining', '')
    need(left.isdigit() and int(left) >= RESERVE, f'the REST allowance fell under 1,500 mid-read ({path})')
    if status == '304' and saved:
        return saved['body'], saved.get('next')
    need(r.returncode == 0 and status == '200' and sep, f'REST read failed: {path}')
    nxt = re.search(r'<https://api\.github\.com/([^>]+)>;\s*rel="next"', headers.get('link', ''))
    nxt = nxt and nxt.group(1)
    if headers.get('etag'):
        cache[path] = {'etag': headers['etag'], 'body': body, 'next': nxt}
    return body, nxt


def rest_list(path, cache, what):
    rows, page = [], 1
    while True:
        body, nxt = rest(f'{path}per_page={REST_PAGE}&page={page}', cache)
        chunk = as_json(body, what)
        need(type(chunk) is list, f'partial page: {what}')
        need(all(isinstance(x, dict) for x in chunk), f'null node: {what}')
        need(len(chunk) == REST_PAGE or not nxt, f'partial page: {what} page {page} has {len(chunk)}')
        rows += chunk
        if not nxt:
            return rows
        page += 1


def rest_login(user):
    need(user is None or (isinstance(user, dict) and type(user.get('login')) is str), 'null node: comment author')
    return DELETED_ACCOUNT if user is None else user['login']


def read_rest(repo, cache):
    fleet_md, _ = rest(f'repos/{repo}/contents/docs/agents/fleet.md', cache, raw=True)
    issues = rest_list(f'repos/{repo}/issues?state=open&', cache, 'open issues')
    heads = {p.get('number'): (p.get('head') or {}).get('sha')
             for p in rest_list(f'repos/{repo}/pulls?state=open&', cache, 'open pull requests')}
    pulls = {i.get('number') for i in issues if 'pull_request' in i}
    need(pulls == set(heads), 'the open pull requests and the issue list disagree; read again')
    items = []
    for i in issues:
        number = i.get('number')
        need(type(number) is int and type(i.get('title')) is str and type(i.get('comments')) is int
             and i.get('state') == 'open' and type(i.get('labels')) is list, 'null node: an item')
        rows = rest_list(f'repos/{repo}/issues/{number}/comments?', cache, f'#{number} comments') \
            if i['comments'] else []
        need(len(rows) == i['comments'], f'partial page: #{number} has {i["comments"]} comments, read {len(rows)}')
        comments = []
        for c in rows:
            need(type(c.get('id')) is int and type(c.get('body')) is str, f'null node: #{number} comment')
            comments.append({'id': c['id'], 'author': rest_login(c.get('user')),
                             'created_at': stamp(c.get('created_at'), number),
                             'updated_at': stamp(c.get('updated_at'), number), 'body': c['body']})
        kind = 'pull' if number in pulls else 'issue'
        need(i.get('body') is None or type(i['body']) is str, f'null node: #{number} body')
        body = i.get('body') or ''
        closing = []
        if kind == 'pull':
            need(type(heads[number]) is str, f'null node: #{number} head')
            for other, n in CLOSES.findall(body):
                ref = '%s#%s' % (other or repo, n)
                if ref not in closing:
                    closing.append(ref)
        items.append({'number': number, 'kind': kind, 'title': i['title'], 'state': 'OPEN',
                      'labels': names(i['labels'], number), 'body': body,
                      'updated_at': stamp(i.get('updated_at'), number), 'head': heads.get(number) if kind == 'pull' else None,
                      'closing_issues': closing, 'comments': comments})
    return items, fleet_md


def atomic(path, text):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name + '.')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def write(repo, out):
    need(REPO.fullmatch(repo), 'repository must be OWNER/NAME')
    left = allowances()
    via = 'graphql' if left['graphql'] >= left['core'] else 'rest'
    need(left['graphql' if via == 'graphql' else 'core'] >= RESERVE,
         'both allowances are under 1,500 (graphql %d, core %d); back off' % (left['graphql'], left['core']))
    read_at = datetime.now(timezone.utc).strftime(STAMP)
    etags = Path(str(out) + '.etags')
    if via == 'graphql':
        items, fleet_md = read_graphql(repo)
    else:
        try:
            cache = json.loads(etags.read_text())
        except (OSError, ValueError):
            cache = {}
        cache = cache if isinstance(cache, dict) else {}
        items, fleet_md = read_rest(repo, cache)
    try:
        authors = sorted(grants.record_authors(fleet_md or ''))
    except ValueError:
        raise Stop('docs/agents/fleet.md names no record authors, so no record can be read')
    numbers = [i['number'] for i in items]
    need(len(numbers) == len(set(numbers)), 'an item was read twice: the list moved between pages; read again')
    snap = {'repo': repo, 'read_at': read_at, 'complete': True, 'via': via, 'record_authors': authors,
            'items': sorted(items, key=lambda i: i['number'])}
    atomic(out, json.dumps(snap, indent=1) + '\n')
    if via == 'rest':
        atomic(etags, json.dumps(cache) + '\n')
    comments = sum(len(i['comments']) for i in items)
    print(f'snapshot: {repo} read by {via}: {len(items)} open items, {comments} comments, at {read_at}')


def load(out):
    try:
        snap = json.loads(Path(out).read_text())
    except (OSError, ValueError):
        raise Stop('snapshot unreadable')
    need(isinstance(snap, dict) and snap.get('complete') is True, 'snapshot incomplete')
    try:
        read_at = datetime.strptime(snap.get('read_at'), STAMP).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        raise Stop('snapshot has no read time')
    need(datetime.now(timezone.utc) - read_at <= FRESH, 'snapshot older than 30 minutes')
    need(type(snap.get('items')) is list and type(snap.get('record_authors')) is list, 'snapshot incomplete')
    return snap


def facts(out, number):
    snap = load(out)
    item = next((i for i in snap['items'] if isinstance(i, dict) and i.get('number') == number), None)
    need(item is not None, f'snapshot has no #{number}')
    authors = frozenset(a.lower() for a in snap['record_authors'])
    every = item.get('comments') or []
    records = sorted((c for c in every if grants.authored(c.get('author'), authors)),
                     key=lambda c: (c.get('created_at') or '', c.get('id') or 0), reverse=True)
    kind = 'pull request' if item.get('kind') == 'pull' else 'issue'
    head = [f"## {snap['repo']}#{number}: {item.get('title')}", '',
            f"{kind}, {item.get('state')}; labels: {', '.join(item.get('labels') or []) or 'none'}; "
            f"updated {item.get('updated_at')}"]
    if item.get('kind') == 'pull':
        head.append(f"head {item.get('head')}; closes {', '.join(item.get('closing_issues') or []) or 'none'}")
    head.append('')
    parts = ['\n'.join(head) + '\n', '### Body\n\n' + (item.get('body') or '') + '\n\n',
             f'### Record-author comments, newest first ({len(records)} of {len(every)} comments)\n\n']
    parts += [f"#### {c.get('author')} at {c.get('created_at')} (comment {c.get('id')}, "
              f"updated {c.get('updated_at')})\n\n{c.get('body')}\n\n" for c in records]
    shown, used, text = 0, 0, []
    cut = None
    for k, part in enumerate(parts):
        size = len(part.encode())
        room = CAP - used - CUT_ROOM
        if size <= room or (k == len(parts) - 1 and used + size <= CAP):
            text.append(part)
            used += size
            shown += k >= 3
            continue
        if k == 1:
            text.append(part.encode()[:max(room, 0)].decode(errors='ignore') + '\n\n')
        cut = (f'[cut: this block is capped at 60 KB; {shown} of {len(records)} record-author comments shown'
               f'{", the body cut short" if k == 1 else ""}; read GitHub for the rest]')
        break
    block = ''.join(text).rstrip('\n') + '\n'
    if cut:
        block += '\n' + cut + '\n'
    sys.stdout.write(block)


def main(argv):
    try:
        if len(argv) == 3 and argv[0] == 'write':
            write(argv[1], argv[2])
        elif len(argv) == 3 and argv[0] == 'facts' and argv[2].isdigit():
            facts(argv[1], int(argv[2]))
        else:
            print(USAGE, end='', file=sys.stderr)
            return 2
    except Stop as e:
        print(f'snapshot: refused: {e}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
