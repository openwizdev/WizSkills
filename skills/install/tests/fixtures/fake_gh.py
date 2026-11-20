#!/usr/bin/env python3
"""A recording fake `gh` for the onboarding journey (#1108).

The demo repository's creation and default-branch read-back share one
synthetic GitHub world at $FAKE_GH_REPOS. Its onboarding switches: "create":
"ok" | "lost" | "fail", "fail_after_create": N (the N `repo view` reads after a
create fail as a network error would), "view_fails". A plain create makes an
empty repository with no branch, as GitHub does; `--add-readme` is GitHub's
initial commit: its default branch `main` holding one README.md. "lost" creates
the repository but exits 1 with no answer, as a timed-out create. Creation and
`repo view` calls are logged to $FAKE_GH_CREATE_LOG.

It also answers the launch's read of a spec's comments (#636: `api --paginate
repos/R/issues/N/comments?per_page=100 --jq EXPR`) from launch-fleet's synthetic
world, through jq as gh does, or fails it when $FAKE_GH_COMMENTS_FAIL is set.
The onboarding road (#1358) adds the host setting pull request and the first
merge's read-back, from the same launch-fleet world: its `default` branch's
`files`, `branches` (name to files), `host_pulls` and `onboard_pulls`; `put_fails` makes every
contents write fail. When
$FAKE_GH_ARGV_LOG is set, every call is logged there as one JSON line.
Every other call goes to launch-fleet's fake gh unchanged, which refuses writes.
All values are synthetic.
"""
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys

FLEET_GH = Path(__file__).resolve().parents[3] / 'launch-fleet/scripts/fixtures/gh.py'
FIELDS = {'nameWithOwner', 'isPrivate', 'defaultBranchRef'}


def repository(owner, name, branches):
    """A repository as init's fake models it, created by this login."""
    return {'full_name': '%s/%s' % (owner, name), 'private': True, 'visibility': 'private',
            'default_branch': 'main', 'permissions': {'push': True}, 'owner': {'login': owner, 'type': 'User'},
            'description': None, 'homepage': None, 'labels': [], 'pulls': [], 'branches': branches}


def demo(argv):
    path = os.environ['FAKE_GH_REPOS']
    state = json.loads(Path(path).read_text())
    with open(os.environ['FAKE_GH_CREATE_LOG'], 'a') as log:
        log.write(json.dumps(argv) + '\n')
    if state.get('signed_out'):
        sys.stderr.write('To get started with GitHub CLI, please run: gh auth login\n')
        return 1
    name = argv[2]
    found = state['repos'].get(name.lower())
    if argv[1] == 'view' and state.get('view_fails', 0) > 0:
        state['view_fails'] -= 1
        Path(path).write_text(json.dumps(state))
        sys.stderr.write('synthetic network error\n')
        return 1
    if argv[1] == 'view':
        fields = argv[4].split(',') if argv[3:4] == ['--json'] and len(argv) == 5 else []
        if not fields or set(fields) - FIELDS or found is None or found.get('hidden'):
            sys.stderr.write("GraphQL: Could not resolve to a Repository with the name '%s'.\n" % name)
            return 1
        has = found['default_branch'] in found['branches']
        known = {'nameWithOwner': found['full_name'], 'isPrivate': found['private'],
                 'defaultBranchRef': {'name': found['default_branch'] if has else ''}}
        print(json.dumps({f: known[f] for f in fields}))
        return 0
    readme = argv[3:] == ['--private', '--add-readme']
    if not (readme or argv[3:] == ['--private']) or found is not None or state.get('create') == 'fail':
        sys.stderr.write('synthetic create refused\n')
        return 1
    owner, short = name.split('/')
    state['repos'][name.lower()] = repository(owner, short, {'main': {'README.md': '# %s\n' % short}} if readme else {})
    state['log'].append(['POST', 'user/repos'])
    state['view_fails'] = state.get('fail_after_create', 0)
    Path(path).write_text(json.dumps(state))
    if state.get('create') == 'lost':
        return 1
    print('https://github.com/%s' % name)
    return 0


def default_ref(target, name, branch):
    path = Path(os.environ['FAKE_GH_REPOS'])
    state = json.loads(path.read_text())
    state['log'].append(['GET', target])
    fault = next((entry for entry in state['faults']
                  if entry['method'] == 'GET' and entry['path'] == target
                  and entry['times'] > 0), None)
    if fault:
        fault['times'] -= 1
    path.write_text(json.dumps(state))
    if fault and fault['mode'] == 'drop':
        sys.stderr.write('synthetic connection reset\n')
        return 1
    repo = state['repos'].get(name.lower())
    if fault:
        status, body = fault['mode'], {'message': 'synthetic refusal'}
    elif repo and branch in repo['branches']:
        status, body = 200, {'object': {'sha': 'f' * 40}}
    else:
        status, body = 404, {'message': 'synthetic missing ref'}
    sys.stdout.write(f'HTTP/2.0 {status} Fixture\r\n\r\n{json.dumps(body)}')
    return 0 if status == 200 else 1


def road(argv):
    """The host setting pull request and the first merge's read-back, or None when not one of their calls."""
    path = Path(os.environ['FAKE_GH_WORLD'])
    world = json.loads(path.read_text())
    r = 'repos/%s' % world['repo']
    branches, pulls = world.setdefault('branches', {}), world.setdefault('host_pulls', [])

    def save():
        path.write_text(json.dumps(world))

    def http(status, body):
        sys.stdout.write('HTTP/2.0 %d Fixture\r\nContent-Type: text/plain\r\n\r\n%s' % (status, body))
        return 0 if status == 200 else 1

    raw = ['-H', 'Accept: application/vnd.github.raw+json']
    if argv[:2] == ['api', '--include'] and len(argv) == 5 and argv[3:] == raw:
        match = re.fullmatch(re.escape(r + '/contents/') + r'([^?]+)(?:\?ref=(.+))?', argv[2])
        if match:
            files = world['files'] if match[2] in (None, world['default']) else branches.get(match[2])
            if files is None or match[1] not in files:
                return http(404, '{"message": "Not Found"}')
            return http(200, files[match[1]])
    if argv == ['api', r, '--jq', '.default_branch']:
        print(world['default'])
        return 0
    match = re.fullmatch(re.escape(r + '/git/ref/heads/') + '(.+)', argv[1]) if len(argv) == 4 else None
    if match and argv[0] == 'api' and argv[2:] == ['--jq', '.object.sha']:
        if match[1] != world['default'] and match[1] not in branches:
            sys.stderr.write('gh: Not Found (HTTP 404)\n')
            return 1
        print(('a' if match[1] == world['default'] else 'b') * 40)
        return 0
    if argv[:4] == ['api', '-X', 'POST', r + '/git/refs'] and len(argv) == 8:
        name = argv[5][len('ref=refs/heads/'):]
        if name in branches:
            sys.stderr.write('gh: Reference already exists (HTTP 422)\n')
            return 1
        branches[name] = dict(world['files'])  # a new branch holds its base's files
        save()
        return 0
    match = re.fullmatch(re.escape(r + '/contents/') + r'(docs/agents/[^?]+)', argv[3]) if len(argv) > 3 else None
    if argv[:3] == ['api', '-X', 'PUT'] and match and len(argv) in (10, 12):
        fields = dict(value.split('=', 1) for value in argv[5::2])
        if world.get('put_fails'):
            sys.stderr.write('gh: synthetic server error (HTTP 502)\n')
            return 1
        files = branches.get(fields['branch'])
        if files is None or (match[1] in files) != ('sha' in fields):  # GitHub needs the sha to replace a file
            sys.stderr.write('gh: sha mismatch (HTTP 409)\n')
            return 1
        files[match[1]] = base64.b64decode(fields['content']).decode()
        save()
        return 0
    match = re.fullmatch(re.escape(r + '/contents/') + r'([^?]+)\?ref=(.+)', argv[1]) if len(argv) == 4 else None
    if match and argv[0] == 'api' and argv[2:] == ['--jq', '.sha']:
        if match[1] not in branches.get(match[2], {}):
            sys.stderr.write('gh: Not Found (HTTP 404)\n')
            return 1
        print('c' * 40)
        return 0
    if argv[:2] == ['pr', 'list'] and argv[2:4] == ['--repo', world['repo']]:
        head = argv[argv.index('--head') + 1]
        print(json.dumps([{'url': p['url'], 'state': p['state']} for p in pulls if p['head'] == head]))
        return 0
    if argv[:2] == ['pr', 'create'] and argv[2:4] == ['--repo', world['repo']]:
        head = argv[argv.index('--head') + 1]
        if head not in branches or any(p['head'] == head for p in pulls):
            return 1
        pulls.append({'head': head, 'state': 'OPEN', 'url': 'https://github.com/%s/pull/%d' % (
            world['repo'], 950 + len(pulls))})
        save()
        print(pulls[-1]['url'])
        return 0
    if argv[:2] == ['pr', 'view'] and argv[3:5] == ['--repo', world['repo']]:
        found = [p for p in world.get('onboard_pulls', []) if p['number'] == int(argv[2])]
        if not found:
            sys.stderr.write('GraphQL: Could not resolve to a PullRequest\n')
            return 1
        print(json.dumps({k: found[0][k] for k in argv[6].split(',')}))
        return 0
    return None


def main(argv):
    if os.environ.get('FAKE_GH_ARGV_LOG'):
        with open(os.environ['FAKE_GH_ARGV_LOG'], 'a') as log:
            log.write(json.dumps(argv) + '\n')
    if argv == ['api', 'user', '--jq', '.login']:
        state = json.loads(Path(os.environ['FAKE_GH_REPOS']).read_text())
        if state.get('signed_out'):
            sys.stderr.write('To get started with GitHub CLI, please run: gh auth login\n')
            return 1
        print(state['user']['login'])
        return 0
    if argv[:2] == ['repo', 'create'] or (argv[:2] == ['repo', 'view'] and len(argv) > 2 and not argv[2].startswith('-')):
        return demo(argv)
    if len(argv) == 5 and argv[:4] == ['api', '--include', '-X', 'GET']:
        match = re.fullmatch(r'repos/([^/]+/[^/]+)/git/ref/heads/(.+)', argv[4])
        if match:
            return default_ref(argv[4], match[1], match[2])
    if os.environ.get('FAKE_GH_WORLD'):
        answered = road(argv)
        if answered is not None:
            return answered
    if argv[:2] == ['api', '--paginate'] and len(argv) == 5 and argv[3] == '--jq':
        match = re.fullmatch(r'repos/([^/]+/[^/]+)/issues/([0-9]+)/comments\?per_page=100', argv[2])
        world = json.loads(Path(os.environ['FAKE_GH_WORLD']).read_text())
        if not match or match[1] != world['repo'] or os.environ.get('FAKE_GH_COMMENTS_FAIL'):
            sys.stderr.write('synthetic: HTTP 404\n')
            return 1
        issue = [i for i in world['issues'] if i['number'] == int(match[2])]
        page = [{'body': c['body'], 'user': {'login': c.get('author', 'synthetic-factory[bot]')}
                 if c.get('author', 'synthetic-factory[bot]') is not None else None}
                for c in (issue[0]['comments'] if issue else [])]
        return subprocess.run(['jq', '-r', argv[4]], input=json.dumps(page), text=True).returncode
    os.execv(sys.executable, [sys.executable, '-I', '-S', str(FLEET_GH), *argv])


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
