import json
import os
import signal
import sys
from urllib.parse import parse_qs, urlsplit

REPO = 'openwizdev/OpenWiz'


def respond(status, data, include=True):
    text = json.dumps(data)
    if include:
        sys.stdout.write(f'HTTP/2.0 {status} Synthetic\nContent-Type: application/json; charset=utf-8\n\n')
    sys.stdout.write(text)
    if status >= 400:
        sys.stderr.write(f'gh: synthetic (HTTP {status})\n')
        sys.exit(1)
    sys.exit(0)


def issue_json(i, name=REPO):
    out = {'number': i['number'], 'title': i['title'], 'body': i['body'], 'user': i['user'],
           'repository_url': 'https://api.github.com/repos/' + name,
           'html_url': f'https://github.com/{name}/issues/{i["number"]}'}
    if 'pull_request' in i:
        out['pull_request'] = i['pull_request']
    return out


def main(argv):
    payload = sys.stdin.read() if '--input' in argv else ''
    with open(os.environ['FAKE_GH_LOG'], 'a') as log:
        log.write(json.dumps({'argv': argv, 'stdin': payload}) + '\n')
    path = os.environ['FAKE_GH_SCENARIO']
    with open(path) as f:
        world = json.load(f)
    token = world.get('token_user') if os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN') else None
    if argv[:2] == ['auth', 'status']:
        if argv[2:] != ['--json', 'hosts', '--hostname', 'github.com']:
            sys.stderr.write(f'fake gh: unsupported arguments {argv}\n')
            sys.exit(3)
        stored = world.get('accounts', [world['user']['login']] if world['user'] else [])
        entries = ([{'state': 'success', 'active': True, 'host': 'github.com', 'login': token['login'],
                     'tokenSource': 'GH_TOKEN', 'gitProtocol': 'https'}] if token else [])
        entries += [{'state': 'success', 'active': not entries and n == 0, 'host': 'github.com', 'login': login,
                     'tokenSource': 'keyring', 'gitProtocol': 'https'} for n, login in enumerate(stored)]
        sys.stdout.write(json.dumps({'hosts': {'github.com': entries} if entries else {}}))
        sys.exit(0)
    if argv[:1] != ['api']:
        sys.stderr.write(f'fake gh: unsupported command {argv[:1]}\n')
        sys.exit(3)
    args = argv[1:]
    include = '--include' in args
    method = args[args.index('--method') + 1] if '--method' in args else 'GET'
    rest = [a for a in args if a not in ('--include', '--paginate', '--slurp', '--input', '-', '--method', method)]
    if len(rest) != 1:
        sys.stderr.write(f'fake gh: unsupported arguments {args}\n')
        sys.exit(3)
    url = urlsplit(rest[0])
    name = world.get('name', REPO)
    route = url.path.lower()
    repo = f'repos/{REPO}'.lower()
    if method == 'GET' and url.path == 'user':
        if token:
            respond(200, token, include)
        if world['user'] is None:
            respond(401, {'message': 'Requires authentication'}, include)
        respond(200, world['user'], include)
    if method == 'GET' and route == repo:
        if world['repo'] == 'fail':
            sys.exit(1)
        respond(200, world['repo'], include)
    if method == 'POST' and route == repo + '/issues':
        create = world['create']
        if create.get('kill_parent'):
            os.kill(os.getppid(), signal.SIGKILL)
            sys.exit(1)
        if create.get('drop'):
            sys.stderr.write('Post "https://api.github.com/...": connection reset by peer\n')
            sys.exit(1)
        if create['status'] != 201:
            respond(create['status'], {'message': 'synthetic refusal'}, include)
        sent = json.loads(payload)
        number = world['next_number']
        issue = {'number': number, 'title': sent['title'], 'body': sent['body'], 'user': world['user']}
        world['issues'].append(issue)
        world['next_number'] = number + 1
        world['just_created'] = number
        with open(path, 'w') as f:
            json.dump(world, f)
        respond(201, issue_json(issue, name), include)
    if method == 'GET' and route.startswith(repo + '/issues/'):
        number = int(url.path.rsplit('/', 1)[1])
        if world.get('just_created') == number and world.get('readback') == 'fail':
            sys.exit(1)
        for i in world['issues']:
            if i['number'] == number:
                shown = issue_json(i, name)
                if world.get('just_created') == number and world.get('readback') == 'differs':
                    shown['body'] += ' (edited)'
                respond(200, shown, include)
        respond(404, {'message': 'Not Found'}, include)
    if method == 'GET' and route == repo + '/issues' and '--paginate' in args and '--slurp' in args:
        if world.get('list') == 'fail':
            sys.stderr.write('gh: synthetic (HTTP 502)\n')
            sys.exit(1)
        query = parse_qs(url.query)
        creator = query['creator'][0]
        found = [issue_json(i, name) for i in world['issues'] if i['user']['login'] == creator]
        sys.stdout.write(json.dumps([found[:100]] if len(found) <= 100 else [found[:100], found[100:]]))
        sys.exit(0)
    sys.stderr.write(f'fake gh: unsupported {method} {rest[0]}\n')
    sys.exit(3)


if __name__ == '__main__':
    main(sys.argv[1:])
