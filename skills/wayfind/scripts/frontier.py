#!/usr/bin/env python3
"""Read a wayfind map's frontier, or who holds one question's claim.

  python3 -I frontier.py map <map>
      One line per open question, in the map's order:
        #<n> frontier <kind label>: <title>
        #<n> blocked by #<a> #<b>: <title>
        #<n> held by <claim comment id>: <title>
        #<n> no kind label: <title>      (not exactly one wayfind: kind)
      or `no open question` when every question is closed.
  python3 -I frontier.py holder <question> [--mine <claim comment id>]
      `unclaimed`, `held by <id>`, `yours` (your claim holds) or `closed`.

A claim is a comment whose body is `wayfind: claimed`; its id is the
numeric `#issuecomment-` suffix of its URL. `wayfind: released <id>` after
it releases that claim. The earliest unreleased claim holds the question.

Exits 2 with the reason on stderr and nothing on stdout when any part of
the read fails or is incomplete. Never read that as an empty frontier.
Needs gh (signed in); uses GH_REPO or the current clone's repository.
"""
import json
import re
import subprocess
import sys

KINDS = ('wayfind:grill', 'wayfind:research', 'wayfind:prototype', 'wayfind:task')
CLAIM = 'wayfind: claimed'
RELEASE = re.compile(r'wayfind: released ([1-9][0-9]*)')
COMMENT_ID = re.compile(r'#issuecomment-([1-9][0-9]*)')
QUESTION = '''number title state
  labels(first: 100) { totalCount nodes { name } }
  blockedBy(first: 100) { totalCount nodes { number state } }
  comments(first: 100) { totalCount nodes { url body } }'''
QUERY = '''query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) { issue(number: $number) { %s } }
}'''


class Refuse(Exception):
    pass


def read(number, fields):
    try:
        out = subprocess.run(
            ['gh', 'api', 'graphql', '-F', 'owner={owner}', '-F', 'repo={repo}',
             '-F', f'number={number}', '-f', 'query=' + QUERY % fields],
            capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Refuse(f'gh could not run: {error}')
    if out.returncode != 0:
        raise Refuse(f'gh failed reading #{number}')
    try:
        data = json.loads(out.stdout)
    except ValueError:
        raise Refuse(f'gh returned no JSON for #{number}')
    if not isinstance(data, dict) or data.get('errors'):
        raise Refuse(f'GitHub returned an error for #{number}')
    issue = ((data.get('data') or {}).get('repository') or {}).get('issue')
    if not isinstance(issue, dict):
        raise Refuse(f'#{number} is not a readable issue')
    return issue


def nodes(issue, field):
    connection = issue.get(field)
    if not isinstance(connection, dict) or not isinstance(connection.get('nodes'), list):
        raise Refuse(f'#{issue.get("number")} has no {field}')
    if connection.get('totalCount') != len(connection['nodes']):
        raise Refuse(f'#{issue.get("number")} has more {field} than one read returns')
    return connection['nodes']


def holder(issue):
    claims = []
    for comment in nodes(issue, 'comments'):
        body = (comment.get('body') or '').strip()
        if body == CLAIM:
            found = COMMENT_ID.search(comment.get('url') or '')
            if not found or not comment['url'].endswith(found.group(0)):
                raise Refuse(f'#{issue["number"]} has a claim without its comment id')
            claims.append(found.group(1))
        elif RELEASE.fullmatch(body) and RELEASE.fullmatch(body).group(1) in claims:
            claims.remove(RELEASE.fullmatch(body).group(1))
    return claims[0] if claims else None


def line(question):
    kinds = [l['name'] for l in nodes(question, 'labels') if l.get('name', '').startswith('wayfind:')]
    blockers = [b['number'] for b in nodes(question, 'blockedBy') if b.get('state') != 'CLOSED']
    held = holder(question)
    if len(kinds) != 1 or kinds[0] not in KINDS:
        what = 'no kind label'
    elif blockers:
        what = 'blocked by ' + ' '.join(f'#{n}' for n in blockers)
    elif held:
        what = f'held by {held}'
    else:
        what = f'frontier {kinds[0]}'
    return f'#{question["number"]} {what}: {question["title"]}'


def main(argv):
    if len(argv) == 2 and argv[0] == 'map' and argv[1].isdigit():
        issue = read(int(argv[1]), 'number subIssues(first: 100) { totalCount nodes { %s } }' % QUESTION)
        lines = [line(q) for q in nodes(issue, 'subIssues') if q.get('state') == 'OPEN']
        return '\n'.join(lines) if lines else 'no open question'
    if len(argv) in (2, 4) and argv[0] == 'holder' and argv[1].isdigit() and \
            (len(argv) == 2 or (argv[2] == '--mine' and argv[3].isdigit())):
        issue = read(int(argv[1]), QUESTION)
        nodes(issue, 'labels'), nodes(issue, 'blockedBy')
        held = holder(issue)
        if issue.get('state') != 'OPEN':
            return 'closed'
        if held is None:
            return 'unclaimed'
        return 'yours' if len(argv) == 4 and held == argv[3] else f'held by {held}'
    raise Refuse('usage: frontier.py map <map> | holder <question> [--mine <claim comment id>]')


if __name__ == '__main__':
    try:
        print(main(sys.argv[1:]))
    except Refuse as error:
        print(f'frontier: {error}', file=sys.stderr)
        sys.exit(2)
