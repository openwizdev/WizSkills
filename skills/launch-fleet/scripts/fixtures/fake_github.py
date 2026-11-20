#!/usr/bin/env python3
"""A synthetic `gh` for post.py's and merge.py's tests (WS8). Never networked.

The world is the JSON file named by FAKE_WORLD. Each write is appended to its
`writes`. `faults` makes the next matching call fail: `post`, `patch` or
`merge` set to `fail` (no effect, exit 1) or `lost` (the effect happens, the
response is lost: exit 1). `merge` may also be `queue` (the queue takes it).
`readback` set to `fail` fails the first comment-list read after a write.
"""
import json
import os
import sys

path = os.environ['FAKE_WORLD']
with open(path) as f:
    world = json.load(f)
args = sys.argv[1:]


def save():
    with open(path, 'w') as f:
        json.dump(world, f)


def fault(kind):
    value = world.get('faults', {}).pop(kind, None)
    save()
    return value


def flag(name):
    for i, a in enumerate(args):
        if a == name:
            return args[i + 1]
        if a.startswith(name + '='):
            return a.split('=', 1)[1]
    return None


def field(name):
    for i, a in enumerate(args):
        if a in ('-f', '-F', '--raw-field', '--field') and args[i + 1].startswith(name + '='):
            return args[i + 1].split('=', 1)[1]
    return None


def comments(number):
    return world.setdefault('comments', {}).setdefault(str(number), [])


def find(comment_id):
    for items in world.get('comments', {}).values():
        for c in items:
            if c['id'] == comment_id:
                return c
    return None


def out(value):
    print(json.dumps(value))
    sys.exit(0)


def fail(text):
    print(text, file=sys.stderr)
    sys.exit(1)


repo = world['repo']
if args[:2] == ['pr', 'merge']:
    pr = world['pr']
    if flag('--repo') != repo or args[2] != str(pr['number']) or '--merge' not in args:
        fail('unexpected merge')
    kind = fault('merge')
    if kind == 'fail':
        fail('merge refused')
    if '--admin' in args:
        fail('synthetic repository refuses admin merges')
    if flag('--match-head-commit') != pr['headRefOid']:
        fail('Head branch was modified')
    world['writes'].append({'merge': pr['number'], 'head': pr['headRefOid'], 'body': flag('--body')})
    if kind == 'queue' or pr['isMergeQueueEnabled']:
        pr.update(isInMergeQueue=True, mergeQueueEntry={'headCommit': {'oid': pr['headRefOid']}})
    elif kind != 'pending':
        pr.update(state='MERGED', mergeCommit={'oid': 'f' * 40})
    save()
    if kind == 'lost':
        fail('connection reset')
    sys.exit(0)

if args[:2] != ['api', 'graphql'] and args[0] == 'api':
    method = flag('--method') or 'GET'
    endpoint = next(a for a in args[1:] if a.startswith('repos/'))
    base = 'repos/%s/' % repo
    if not endpoint.startswith(base):
        fail('HTTP 404')
    rest = endpoint[len(base):].split('?')[0]
    if rest == 'contents/docs/agents/fleet.md':
        if world.get('fleet_md') is None:
            fail('HTTP 404')
        sys.stdout.write(world['fleet_md'])
        sys.exit(0)
    parts = rest.split('/')
    if method == 'POST' and parts[0] == 'issues' and parts[2:] == ['comments']:
        kind = fault('post')
        if kind == 'fail':
            fail('HTTP 502')
        world['next_id'] += 1
        c = {'id': world['next_id'], 'body': field('body'), 'user': {'login': world['me']},
             'created_at': '2026-01-01T00:00:00Z'}
        comments(parts[1]).append(c)
        world['writes'].append({'post': int(parts[1]), 'body': c['body']})
        save()
        if kind == 'lost':
            fail('connection reset')
        out(c)
    if parts[:2] == ['issues', 'comments'] and len(parts) == 3:
        c = find(int(parts[2]))
        if c is None:
            fail('HTTP 404')
        if method == 'PATCH':
            kind = fault('patch')
            if kind == 'fail':
                fail('HTTP 502')
            c['body'] = field('body')
            world['writes'].append({'patch': c['id'], 'body': c['body']})
            save()
            if kind == 'lost':
                fail('connection reset')
        out(c)
    if method == 'GET' and parts[0] == 'issues' and parts[2:] == ['comments']:
        if world['writes'] and world.get('faults', {}).get('readback') == 'fail':
            fault('readback')
            fail('HTTP 502')
        page = comments(parts[1])
        out([page] if '--slurp' in args else page)
    fail('unexpected api call: %s' % ' '.join(args))

if args[:2] == ['api', 'graphql']:
    if fault('graphql') == 'fail':
        fail('HTTP 502')
    pr = world.get('pr')
    if pr is None or field('number') != str(pr['number']):
        out({'data': {'repository': {'defaultBranchRef': {'name': 'main'}, 'pullRequest': None}}})
    node = {k: pr[k] for k in ('state', 'baseRefName', 'headRefOid', 'isMergeQueueEnabled', 'isInMergeQueue',
                               'mergeCommit', 'mergeQueueEntry', 'mergeable')}
    node['timelineItems'] = {'nodes': [pr['left']] if pr.get('left') else []}
    node['commits'] = {'nodes': [{'commit': {'oid': pr['headRefOid'], 'statusCheckRollup': {'contexts': {
        'pageInfo': {'hasNextPage': pr.get('more_checks', False)}, 'nodes': pr['checks']}}}}]}
    out({'data': {'repository': {'defaultBranchRef': {'name': 'main'}, 'pullRequest': node}}})

fail('unexpected gh call: %s' % ' '.join(args))
