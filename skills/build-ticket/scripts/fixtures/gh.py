#!/usr/bin/env python3
"""Synthetic `gh` for ticket.py's tests. State is the JSON file in FAKE_GH_WORLD.

Answers only the calls ticket.py makes; anything else exits 9 so a test sees it.
"""
import json
import os
import sys

path = os.environ['FAKE_GH_WORLD']
with open(path, encoding='utf-8') as f:
    world = json.load(f)
args = sys.argv[1:]
world.setdefault('calls', []).append(args)


def save():
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(world, f)


def answer(value, code=0):
    save()
    print(json.dumps(value))
    sys.exit(code)


if args[:2] == ['issue', 'view']:
    issue = world.get('issues', {}).get(args[2])
    if issue is None or world.get('fail_reads'):
        save()
        sys.exit(1)
    answer(issue)
if args == ['api', 'user']:
    answer(world['user'])
if args[:1] == ['api'] and args[-1].endswith('/comments') and '--paginate' in args:
    if world.get('fail_reads'):
        save()
        sys.exit(1)
    comments = world.get('comments', [])
    answer([comments[:2], comments[2:]] if '--slurp' in args else comments)
if args[:1] == ['api'] and '/pulls/' in args[-1]:
    answer({'head': {'sha': world['pr_head']}})
if args[:3] == ['api', '--method', 'POST']:
    body = next(a[len('body='):] for a in args if a.startswith('body='))
    if world.get('refuse_post'):
        save()
        sys.exit(1)
    comment = {'id': 9000 + len(world.get('comments', [])), 'user': {'login': 'jparker'},
               'body': body}
    world.setdefault('comments', []).append(comment)
    if world.get('lose_post_response'):
        world['lose_post_response'] = False
        save()
        sys.exit(1)
    answer(comment)
save()
sys.exit(9)
