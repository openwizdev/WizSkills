#!/usr/bin/env python3
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import unittest

ROUTER = Path(__file__).resolve().with_name('events.py')
FIXTURES = ROUTER.parents[3] / 'contracts/fixtures/github-events'
REPO = 'example-org/example-repo'
LEDGER = Path('.openwiz/home/github-events.json')

FAKE_GH = r"""#!/usr/bin/env python3
import json
import os
from pathlib import Path
import re
import sys

log = Path('reads')
if (sys.argv[1:] != ['api', 'graphql', '--input', '-']
        or 'OPENWIZ_WEBHOOK_SECRET' in os.environ):
    with log.open('a') as f:
        f.write('unexpected command or environment\n')
    sys.exit(1)
request = json.load(sys.stdin)
query = request['query']
if not query.startswith('query ') or re.search(r'\bmutation\b', query):
    with log.open('a') as f:
        f.write('unexpected query\n')
    sys.exit(1)
with log.open('a') as f:
    f.write('read\n')
variables = request['variables']
repo = variables['owner'] + '/' + variables['name']
world = json.loads(Path('world.json').read_text())

def issue(ref):
    repo, number = ref.split('#')
    return {'repository': {'nameWithOwner': repo}, 'number': int(number)}

def ticket(ref):
    parent = world['parents'].get(ref)
    return dict(issue(ref), parent=issue(parent) if parent else None)

items = {}
for alias, number, fragment in re.findall(
        r'(i[0-9]+): issueOrPullRequest\(number: ([0-9]+)\) \{ ... on (Issue|PullRequest)\b', query):
    ref = repo + '#' + number
    if fragment == 'PullRequest':
        refs = world['closing_tickets'].get(ref, [])
        page = int(variables.get('after' + number) or '0')
        pages = world.get('pages', {}).get(ref, [refs])
        cursor = str(page + 1) if page + 1 < len(pages) else None
        items[alias] = {'closingIssuesReferences': {
            'pageInfo': {'hasNextPage': cursor is not None, 'endCursor': cursor},
            'nodes': [ticket(ref) for ref in pages[page]],
        }}
    else:
        items[alias] = ticket(ref)
if not items or 'parent { number repository { nameWithOwner } }' not in query:
    sys.exit(1)
answer = {'data': {'repository': items}}
if Path('fail-read').exists():
    answer['errors'] = [{'message': 'example partial response'}]
print(json.dumps(answer))
"""


class EventsTest(unittest.TestCase):
    def sandbox(self, world):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        gh = root / 'gh'
        gh.write_text(FAKE_GH)
        gh.chmod(0o700)
        (root / 'world.json').write_text(json.dumps(world))
        return root

    def run_delivery(self, root, delivery, secret=None, file_suffix=''):
        body = json.dumps(delivery['body'], ensure_ascii=False, indent=2).encode()
        env = dict(os.environ, GH_REPO=REPO, PATH=f"{root}{os.pathsep}{os.environ['PATH']}")
        env.pop('OPENWIZ_WEBHOOK_SECRET', None)
        if secret:
            env['OPENWIZ_WEBHOOK_SECRET'] = secret
        cmd = [sys.executable, '-I', str(ROUTER)]
        if delivery['headers'] is not None:
            headers = delivery['headers'].copy()
            if delivery.get('sign_body'):
                headers['X-Hub-Signature-256'] = 'sha256=' + hmac.new(
                    secret.encode(), body, hashlib.sha256).hexdigest()
            headers_file = root / f'headers{file_suffix}.json'
            body_file = root / f'body{file_suffix}.json'
            headers_file.write_text(json.dumps(headers))
            body_file.write_bytes(body)
            cmd += ['--headers', str(headers_file), '--body', str(body_file)]
        result = subprocess.run(cmd, cwd=root, env=env, input=body, capture_output=True, timeout=30)
        if secret:
            self.assertTrue(secret.encode() not in result.stdout + result.stderr, 'secret leaked to output')
        return result.returncode, result.stdout

    def reads(self, root):
        log = root / 'reads'
        return log.read_text().splitlines() if log.exists() else []

    def seed(self, root, ids):
        ledger = root / LEDGER
        ledger.parent.mkdir(parents=True)
        ledger.write_text(json.dumps(ids))
        return ledger

    def test_contract_fixtures(self):
        fixtures = sorted(FIXTURES.glob('*.json'))
        self.assertTrue(fixtures, 'no contract fixtures found')
        for fixture in fixtures:
            world = json.loads(fixture.read_text())
            root = self.sandbox(world)
            secret = secrets.token_hex(32) if world.get('secret_configured') else None
            if 'ledger_fill' in world:
                self.seed(root, [f'example-history-{i}' for i in range(1, world['ledger_fill'] + 1)])
            for index, delivery in enumerate(world['deliveries']):
                with self.subTest(fixture=fixture.stem, delivery=index):
                    before = len(self.reads(root))
                    expected = delivery['expected']
                    stdout = ''.join(line + '\n' for line in expected['stdout']).encode()
                    self.assertEqual(self.run_delivery(root, delivery, secret), (expected['exit_code'], stdout))
                    reads = self.reads(root)[before:]
                    self.assertLessEqual(len(reads), 3)
                    self.assertTrue(all(call == 'read' for call in reads))
                    if expected['exit_code'] == 2 or (fixture.stem == 'duplicate-delivery' and index):
                        self.assertEqual(reads, [])
                    if secret:
                        self.assertFalse(any(secret.encode() in file.read_bytes()
                                             for file in root.rglob('*') if file.is_file()), 'secret leaked to a file')

    def test_failed_read_preserves_ledger_and_allows_retry(self):
        world = json.loads((FIXTURES / 'duplicate-delivery.json').read_text())
        root = self.sandbox(world)
        ledger = self.seed(root, ['example-earlier-delivery'])
        previous = ledger.read_bytes()
        failure = root / 'fail-read'
        failure.touch()
        delivery = world['deliveries'][0]
        self.assertEqual(self.run_delivery(root, delivery), (2, b''))
        self.assertEqual(ledger.read_bytes(), previous)
        failure.unlink()
        stdout = ''.join(line + '\n' for line in delivery['expected']['stdout']).encode()
        self.assertEqual(self.run_delivery(root, delivery), (0, stdout))
        self.assertEqual(json.loads(ledger.read_text()),
                         ['example-earlier-delivery', delivery['headers']['X-GitHub-Delivery']])
        self.assertEqual(self.run_delivery(root, delivery), (0, b''))
        self.assertEqual(self.reads(root), ['read', 'read'])

    def test_paged_references_respect_read_budget(self):
        world = json.loads((FIXTURES / 'pull-request-synchronized.json').read_text())
        delivery = world['deliveries'][0]
        pull = next(iter(world['closing_tickets']))
        outside = 'example-org/example-other#18020'
        world['parents'][outside] = REPO + '#1008'
        other_spec = 'example-org/example-other#18021'
        world['parents'][other_spec] = 'example-org/example-other#333'
        pages = [world['closing_tickets'][pull], [other_spec], [outside]]
        for extra_page in (False, True):
            with self.subTest(extra_page=extra_page):
                world['pages'] = {pull: pages + ([[]] if extra_page else [])}
                root = self.sandbox(world)
                expected = (2, b'') if extra_page else (0, b'check spec 82\ncheck spec 1008\n')
                self.assertEqual(self.run_delivery(root, delivery), expected)
                self.assertEqual(self.reads(root), ['read'] * 3)

    def test_concurrent_deliveries_claim_once(self):
        world = json.loads((FIXTURES / 'duplicate-delivery.json').read_text())
        root = self.sandbox(world)
        delivery = world['deliveries'][0]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda suffix: self.run_delivery(root, delivery, file_suffix=suffix), ('1', '2')))
        stdout = ''.join(line + '\n' for line in delivery['expected']['stdout']).encode()
        self.assertCountEqual(results, [(0, stdout), (0, b'')])
        self.assertEqual(self.reads(root), ['read'])


if __name__ == '__main__':
    unittest.main()
