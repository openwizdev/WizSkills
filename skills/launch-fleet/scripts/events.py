#!/usr/bin/env python3
import argparse
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

LEDGER = Path('.openwiz/home/github-events.json')
WINDOW = 1000
READ_BUDGET = 3
SECRET = 'OPENWIZ_WEBHOOK_SECRET'
REPO = re.compile(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}')
ROUTE = Path(__file__).resolve().with_name('route.py')
RULES = {
    ('check_suite', 'completed'): 'check_suite',
    ('check_run', 'completed'): 'check_run',
    ('pull_request', 'closed'): 'pull_request',
    ('pull_request', 'synchronize'): 'pull_request',
    ('pull_request_review', 'submitted'): 'pull_request',
    ('issue_comment', 'created'): 'issue',
    ('issues', 'labeled'): 'issue',
    ('issues', 'unlabeled'): 'issue',
}
PARENT = 'parent { number repository { nameWithOwner } }'


class Refused(Exception):
    pass


class Arguments(argparse.ArgumentParser):
    def error(self, _message):
        raise Refused('provide both --headers and --body, or read the body on stdin')


def object_or_empty(value):
    return value if isinstance(value, dict) else {}


def issue_number(value):
    return type(value) is int and 0 < value <= 2_147_483_647


def targets(body, event):
    action = body.get('action')
    matches = [(name, key) for (name, expected), key in RULES.items()
               if expected == action and key in body and (event is None or event == name)]
    if len(matches) != 1:
        return None
    name, key = matches[0]
    item = object_or_empty(body[key])
    if name == 'pull_request' and action == 'closed' and item.get('merged') is not True:
        return None
    if key in ('check_suite', 'check_run'):
        pulls = item.get('pull_requests', [])
        if not isinstance(pulls, list):
            raise Refused('invalid pull request list')
        items = pulls
    else:
        items = [item]
    is_pull = key != 'issue' or (name == 'issue_comment' and 'pull_request' in item)
    numbers = {object_or_empty(target).get('number') for target in items
               if issue_number(object_or_empty(target).get('number'))}
    return is_pull, numbers


def lookup(repo, is_pull, cursors):
    owner, name = repo.split('/')
    variables = {'owner': owner, 'name': name}
    declarations = ['$owner: String!', '$name: String!']
    items = []
    for number, cursor in sorted(cursors.items()):
        if is_pull:
            after = f'after{number}'
            declarations.append(f'${after}: String')
            variables[after] = cursor
            field = (f'... on PullRequest {{ closingIssuesReferences(first: 100, after: ${after}) {{ '
                     f'pageInfo {{ hasNextPage endCursor }} nodes {{ {PARENT} }} }} }}')
        else:
            field = f'... on Issue {{ {PARENT} }}'
        items.append(f'i{number}: issueOrPullRequest(number: {number}) {{ {field} }}')
    query = (f'query Events({", ".join(declarations)}) {{ repository(owner: $owner, name: $name) '
             f'{{ {" ".join(items)} }} }}')
    command = [sys.executable, '-I', str(ROUTE), 'gh', 'api', 'graphql', '--input', '-']
    env = {key: value for key, value in os.environ.items() if key != SECRET}
    result = subprocess.run(command, input=json.dumps({'query': query, 'variables': variables}).encode(),
                            capture_output=True, timeout=15, env=env)
    if result.returncode:
        raise Refused('GitHub lookup failed')
    answer = json.loads(result.stdout)
    if answer.get('errors'):
        raise Refused('GitHub lookup was incomplete')
    return answer['data']['repository']


def resolve(repo, spec_repo, is_pull, numbers):
    cursors = dict.fromkeys(numbers)
    specs = set()
    for _ in range(READ_BUDGET):
        if not cursors:
            return sorted(specs)
        items = lookup(repo, is_pull, cursors)
        following = {}
        for number in cursors:
            item = items[f'i{number}']
            if item is None or item == {}:
                continue
            tickets = [item]
            if is_pull:
                connection = item['closingIssuesReferences']
                tickets = connection['nodes']
                page = connection['pageInfo']
                if page['hasNextPage'] is True:
                    cursor = page['endCursor']
                    if not isinstance(cursor, str) or not cursor or cursor == cursors[number]:
                        raise Refused('invalid GitHub page cursor')
                    following[number] = cursor
                elif page['hasNextPage'] is not False:
                    raise Refused('invalid GitHub page state')
            if not isinstance(tickets, list):
                raise Refused('invalid GitHub issue list')
            for ticket in tickets:
                parent = ticket['parent']
                if parent is None:
                    continue
                parent_repo = parent['repository']['nameWithOwner']
                spec = parent['number']
                if not isinstance(parent_repo, str) or not issue_number(spec):
                    raise Refused('invalid GitHub parent')
                if parent_repo.lower() == spec_repo:
                    specs.add(spec)
        cursors = following
    if cursors:
        raise Refused('GitHub lookup exceeded its read budget')
    return sorted(specs)


def ledger_ids():
    try:
        mode = LEDGER.lstat().st_mode
    except FileNotFoundError:
        return []
    if not stat.S_ISREG(mode):
        raise Refused('delivery ledger is not a regular file')
    ids = json.loads(LEDGER.read_bytes())
    if (not isinstance(ids, list) or len(ids) > WINDOW
            or any(not isinstance(value, str) or not value for value in ids)
            or len(set(ids)) != len(ids)):
        raise Refused('invalid delivery ledger')
    return ids


def store_ids(ids):
    with tempfile.NamedTemporaryFile(mode='w', dir=LEDGER.parent, delete=False) as output:
        staged = Path(output.name)
        try:
            json.dump(ids[-WINDOW:], output)
            output.flush()
            os.fsync(output.fileno())
            os.replace(staged, LEDGER)
        finally:
            staged.unlink(missing_ok=True)


def route_delivery(delivery, repo, spec_repo, is_pull, numbers):
    if not delivery:
        return resolve(repo, spec_repo, is_pull, numbers)
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ids = ledger_ids()
        if delivery in ids:
            return []
        specs = resolve(repo, spec_repo, is_pull, numbers)
        store_ids(ids + [delivery])
        return specs


def read_delivery():
    parser = Arguments()
    parser.add_argument('--headers', type=Path)
    parser.add_argument('--body', type=Path)
    args = parser.parse_args()
    if (args.headers is None) != (args.body is None):
        parser.error('')
    if args.headers is None:
        return sys.stdin.buffer.read(), None
    body = args.body.read_bytes()
    supplied = json.loads(args.headers.read_bytes())
    headers = {name.lower(): value for name, value in supplied.items()}
    if len(headers) != len(supplied) or any(not isinstance(value, str) for value in headers.values()):
        raise Refused('invalid delivery headers')
    secret = os.environ.get(SECRET)
    if secret:
        expected = b'sha256=' + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest().encode()
        signature = headers.get('x-hub-signature-256', '').encode()
        if not hmac.compare_digest(signature, expected):
            raise Refused('webhook signature refused')
    return body, headers


def main():
    raw, headers = read_delivery()
    body = json.loads(raw)
    event = None if headers is None else headers.get('x-github-event', '')
    found = targets(body, event)
    if found is None:
        return
    repo = object_or_empty(body.get('repository')).get('full_name', '')
    spec_repo = os.environ.get('GH_REPO', '')
    is_pull, numbers = found
    if numbers and (not REPO.fullmatch(repo) or not REPO.fullmatch(spec_repo)):
        raise Refused('delivery and GH_REPO must name owner/repository')
    delivery = (headers or {}).get('x-github-delivery')
    for spec in route_delivery(delivery, repo, spec_repo.lower(), is_pull, numbers):
        print(f'check spec {spec}')


if __name__ == '__main__':
    try:
        main()
    except Refused as error:
        print(f'events.py: {error}', file=sys.stderr)
        sys.exit(2)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.TimeoutExpired):
        print('events.py: could not read or record the delivery', file=sys.stderr)
        sys.exit(2)
