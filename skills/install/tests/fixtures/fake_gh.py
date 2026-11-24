#!/usr/bin/env python3
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

FLEET_GH = Path(__file__).resolve().parents[3] / 'launch-fleet/scripts/fixtures/gh.py'
FIELDS = {'nameWithOwner', 'isPrivate', 'defaultBranchRef', 'id'}


def repository(owner, name, branches):
    return {'full_name': '%s/%s' % (owner, name), 'private': True, 'visibility': 'private',
            'default_branch': 'main', 'permissions': {'push': True}, 'owner': {'login': owner, 'type': 'User'},
            'description': None, 'homepage': None, 'labels': [], 'pulls': [], 'branches': branches}


def demo(argv, api=False):
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
        known = {'nameWithOwner': found['full_name'], 'isPrivate': found['private'], 'id': node_id(found),
                 'defaultBranchRef': {'name': found['default_branch'] if has else ''}}
        print(json.dumps({f: known[f] for f in fields}))
        return 0
    readme = argv[3:] == ['--private', '--add-readme']
    if not (readme or argv[3:] == ['--private']) or found is not None or state.get('create') == 'fail':
        sys.stderr.write('synthetic create refused\n')
        return 1
    owner, short = name.split('/')
    made = repository(owner, short, {'main': {'README.md': '# %s\n' % short}} if readme else {})
    made['node_id'] = 'R_synthetic%d' % len(state['log'])
    state['repos'][name.lower()] = made
    state['log'].append(['POST', 'user/repos'])
    state['view_fails'] = state.get('fail_after_create', 0)
    Path(path).write_text(json.dumps(state))
    if state.get('create') == 'lost':
        return 1
    if not api:
        print('https://github.com/%s' % name)
        return 0
    print(json.dumps({'id': 1000 + len(state['log']), 'node_id': state.get('reply_id', made['node_id']),
                      'full_name': name, 'private': True}))
    return 0


def node_id(found):
    return found.get('node_id') or 'R_synthetic_' + hashlib.sha256(found['full_name'].encode()).hexdigest()[:8]


def api_create(argv):
    state = json.loads(Path(os.environ['FAKE_GH_REPOS']).read_text())
    short = argv[5][len('name='):]
    owner = state['user']['login'] if argv[3] == 'user/repos' else argv[3].split('/')[1]
    if argv[4:] != ['-f', 'name=' + short, '-F', 'private=true', '-F', 'auto_init=true'] or not short:
        sys.stderr.write('synthetic create refused\n')
        return 1
    return demo(['repo', 'create', '%s/%s' % (owner, short), '--private', '--add-readme'], api=True)


def replaced(state, name):
    if state.pop('replace_before_write', False):
        owner, short = name.split('/')
        state['repos'][name.lower()] = dict(repository(owner, short, {'main': {'README.md': '# %s\n' % short}}),
                                            node_id='R_replacement')


def graphql(argv):
    path = Path(os.environ['FAKE_GH_REPOS'])
    state = json.loads(path.read_text())
    fields = dict(value.split('=', 1) for value in argv[3::2])
    query = fields['query']

    def head(repo, branch):
        files = repo['branches'][branch]
        entry = files.get(fields['path'])
        return {'id': 'REF_%s_%s' % (node_id(repo), branch), 'name': branch, 'target': {
            'oid': hashlib.sha1(json.dumps(files, sort_keys=True).encode()).hexdigest(),
            'file': None if entry is None else {'object': {'text': entry}}}}

    def by_ref(ref):
        return next(((repo, branch) for repo in state['repos'].values() for branch in repo['branches']
                     if 'REF_%s_%s' % (node_id(repo), branch) == ref), (None, None))

    def answer(data, ok=True, errors=None):
        path.write_text(json.dumps(state))
        if errors is None and not ok:
            errors = [{'message': 'synthetic'}]
        sys.stdout.write(json.dumps({'data': data} if not errors else {'data': data, 'errors': errors}))
        return 0 if not errors else 1

    if 'createCommitOnBranch' in query:
        name = (by_ref(fields['ref'])[0] or {}).get('full_name')
        if name:
            replaced(state, name)
        repo, branch = by_ref(fields['ref'])
        if repo is None or head(repo, branch)['target']['oid'] != fields['oid']:
            return answer({'createCommitOnBranch': None}, ok=False)
        repo['branches'][branch][fields['path']] = base64.b64decode(fields['contents']).decode()
        state['log'].append(['POST', 'graphql createCommitOnBranch %s %s' % (repo['full_name'], fields['path'])])
        lost = state.get('seed_lost', 0) > 0
        state['seed_lost'] = state.get('seed_lost', 0) - lost
        oid = head(repo, branch)['target']['oid']
        if lost:
            path.write_text(json.dumps(state))
            sys.stderr.write('gh: synthetic lost reply (HTTP 502)\n')
            return 1
        return answer({'createCommitOnBranch': {'commit': {'oid': oid}}})
    if 'node(' in query:
        repo, branch = by_ref(fields['ref'])
        state['log'].append(['GET', 'graphql node %s' % fields['path']])
        if repo is None:
            return answer({'node': None}, errors=[{'type': 'NOT_FOUND', 'path': ['node'],
                                                   'message': 'Could not resolve to a node.'}])
        found = head(repo, branch)
        errors = None if found['target']['file'] is not None else [{
            'type': 'NOT_FOUND', 'path': ['node', 'target', 'file'],
            'message': "Could not resolve file for path '%s'." % fields['path']}]
        return answer({'node': found}, errors=errors)
    name = '%s/%s' % (fields['owner'], fields['name'])
    repo = state['repos'].get(name.lower())
    state['log'].append(['GET', 'graphql repository %s %s' % (name, fields['path'])])
    if repo is None or repo.get('hidden'):
        return answer({'repository': None}, errors=[{'type': 'NOT_FOUND', 'path': ['repository'],
                                                     'message': 'Could not resolve to a Repository.'}])
    has = repo['default_branch'] in repo['branches']
    found = head(repo, repo['default_branch']) if has else None
    errors = None if not found or found['target']['file'] is not None else [{
        'type': 'NOT_FOUND', 'path': ['repository', 'defaultBranchRef', 'target', 'file'],
        'message': "Could not resolve file for path '%s'." % fields['path']}]
    return answer({'repository': {'id': node_id(repo), 'defaultBranchRef': found}}, errors=errors)


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


def seeded_file(argv):
    read = len(argv) == 5 and argv[:4] == ['api', '--include', '-X', 'GET'] and re.fullmatch(
        r'repos/([^/]+/[^/]+)/contents/((?:tests|\.github)/[^?]+)\?ref=(.+)', argv[4])
    put = len(argv) in (10, 12) and argv[:3] == ['api', '-X', 'PUT'] and re.fullmatch(
        r'repos/([^/]+/[^/]+)/contents/((?:tests|\.github)/[^?]+)', argv[3])
    path = Path(os.environ['FAKE_GH_REPOS']) if os.environ.get('FAKE_GH_REPOS') else None
    if not (read or put) or path is None:
        return None
    state = json.loads(path.read_text())
    if put:
        replaced(state, put[1])
    repo = state['repos'].get((read or put)[1].lower())
    if repo is None:
        return None
    fields = dict(value.split('=', 1) for value in argv[5::2]) if put else {}
    files = repo['branches'].setdefault(read[3] if read else fields['branch'], {})
    if read:
        state['log'].append(['GET', argv[4]])
        path.write_text(json.dumps(state))
        if read[2] not in files:
            sys.stdout.write('HTTP/2.0 404 Fixture\r\n\r\n{"message": "Not Found"}')
            return 1
        sys.stdout.write('HTTP/2.0 200 Fixture\r\n\r\n' + json.dumps({
            'type': 'file', 'encoding': 'base64', 'sha': blob_sha(files[read[2]]),
            'content': base64.b64encode(files[read[2]].encode()).decode()}))
        return 0
    if (put[2] in files) != ('sha' in fields):
        sys.stderr.write('gh: sha mismatch (HTTP 409)\n')
        return 1
    files[put[2]] = base64.b64decode(fields['content']).decode()
    state['log'].append(['PUT', argv[3]])
    lost = state.get('seed_lost', 0) > 0
    state['seed_lost'] = state.get('seed_lost', 0) - lost
    path.write_text(json.dumps(state))
    if lost:
        sys.stderr.write('gh: synthetic lost reply (HTTP 502)\n')
        return 1
    print(json.dumps({'content': {'path': put[2]}}))
    return 0


def blob_sha(text):
    data = text.encode()
    return hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest()


def road(argv):
    path = Path(os.environ['FAKE_GH_WORLD'])
    world = json.loads(path.read_text())
    r = 'repos/%s' % world['repo']
    branches, pulls = world.setdefault('branches', {}), world.setdefault('host_pulls', [])

    def save():
        path.write_text(json.dumps(world))

    def http(status, body):
        sys.stdout.write('HTTP/2.0 %d Fixture\r\nContent-Type: text/plain\r\n\r\n%s' % (status, body))
        return 0 if status == 200 else 1

    def edited(ref, name):
        edit = world.get('edit_after_read', {}).get(ref, {})
        if name in edit:
            branches[ref][name] = edit.pop(name)
            save()

    raw = ['-H', 'Accept: application/vnd.github.raw+json']
    if argv[:2] == ['api', '--include'] and len(argv) in (3, 5) and argv[3:] in ([], raw):
        match = re.fullmatch(re.escape(r + '/contents/') + r'([^?]+)(?:\?ref=(.+))?', argv[2])
        if match:
            files = world['files'] if match[2] in (None, world['default']) else branches.get(match[2])
            if files is None or match[1] not in files:
                return http(404, '{"message": "Not Found"}')
            text = files[match[1]]
            edited(match[2], match[1])
            return http(200, text if argv[3:] else json.dumps({
                'type': 'file', 'sha': blob_sha(text), 'encoding': 'base64',
                'content': base64.b64encode(text.encode()).decode()}))
    match = re.fullmatch(re.escape(r + '/compare/') + r'([^.]+)\.\.\.(.+)', argv[1]) if len(argv) == 2 else None
    if match and argv[0] == 'api':
        base, head = world['files'], branches.get(match[2])
        if match[1] != world['default'] or head is None:
            sys.stderr.write('gh: Not Found (HTTP 404)\n')
            return 1
        files = [{'filename': name, 'status': 'removed' if name not in head else 'added' if name not in base
                  else 'modified'} for name in sorted(set(base) | set(head)) if base.get(name) != head.get(name)]
        print(json.dumps({'status': 'ahead', 'files': files}))
        return 0
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
        branches[name] = dict(world['files'])
        save()
        return 0
    match = re.fullmatch(re.escape(r + '/contents/') + r'(docs/agents/[^?]+)', argv[3]) if len(argv) > 3 else None
    if argv[:3] == ['api', '-X', 'PUT'] and match and len(argv) in (10, 12):
        fields = dict(value.split('=', 1) for value in argv[5::2])
        if world.get('put_fails'):
            sys.stderr.write('gh: synthetic server error (HTTP 502)\n')
            return 1
        files = branches.get(fields['branch'])
        if files is None or (match[1] in files) != ('sha' in fields) or (
                match[1] in files and fields['sha'] != blob_sha(files[match[1]])):
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
        print(blob_sha(branches[match[2]][match[1]]))
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
    if argv[:3] == ['api', '-X', 'POST'] and len(argv) == 10 and re.fullmatch(r'user/repos|orgs/[^/]+/repos', argv[3]):
        return api_create(argv)
    if argv[:2] == ['repo', 'create'] or (argv[:2] == ['repo', 'view'] and len(argv) > 2 and not argv[2].startswith('-')):
        return demo(argv)
    if argv[:2] == ['api', 'graphql'] and len(argv) % 2 == 0 and set(argv[2::2]) == {'-f'} and os.environ.get(
            'FAKE_GH_REPOS') and argv[3].startswith('query=') and any(a.startswith('path=') for a in argv[3::2]):
        return graphql(argv)
    answered = seeded_file(argv)
    if answered is not None:
        return answered
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
