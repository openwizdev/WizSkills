import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
APPROVE = HERE / 'approve.py'
SINCE = '2026-11-23T00:00:00Z'
SPEC = 9300
GRILL = 'https://github.com/synthetic-owner/synthetic-private/issues/1#issuecomment-1'
SPEC_BODY = ('## Problem Statement\n\nSynthetic problem.\n\n## Proof\n\nSynthetic proof.\n\n'
             '## Checkpoints\n\n- One-way door: yes\n- User-visible: no\n')


def body(n, parent_tail, path):
    return (f'## Parent\n\nTicket {n} of spec #{SPEC}. {parent_tail}\n\n## What to build\n\nSynthetic work.\n\n'
            f'## Owned paths\n\n- `{path}`\n\n**Relies on:** nothing\n\n## Links\n\nnone\n\n'
            '## Acceptance criteria\n\n- [ ] Synthetic criterion.\n')


def ticket(n, parent_tail, path):
    return {'number': n, 'title': f'Synthetic ticket {n}', 'state': 'OPEN', 'labels': [], 'milestone': 'Synthetic',
            'parent': SPEC, 'blocked_by': [], 'body': body(n, parent_tail, path), 'start_recorded': False,
            'pull_requests': []}


def sha(text):
    return hashlib.sha256((text + '\n').encode()).hexdigest()


class SizeLimit(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def approve(self, created, tickets):
        graph = {'schema': 'openwiz.plan-links.v1', 'kind': 'graph', 'repo': 'synthetic-owner/synthetic-repo',
                 'read_at': '2026-11-23T12:00:00Z', 'source': {'kind': 'spec', 'spec': SPEC}, 'tickets': tickets}
        revision = ''.join([f'plan-graph revision v2\nspec #{SPEC} body sha256 {sha(SPEC_BODY)}\n'] + [
            f'ticket #{t["number"]} blocked-by none body sha256 {sha(t["body"])} title {t["title"]}\n'
            for t in tickets])
        (self.tmp / 'graph.json').write_text(json.dumps(graph))
        (self.tmp / 'revision.txt').write_text(revision)
        (self.tmp / 'spec.json').write_text(json.dumps({'body': SPEC_BODY, 'createdAt': created}))
        return subprocess.run(
            ['python3', '-I', str(APPROVE), '--graph', str(self.tmp / 'graph.json'),
             '--revision', str(self.tmp / 'revision.txt'), '--spec', str(self.tmp / 'spec.json'),
             '--grill', GRILL, '--number', '1', '--date', '2026-11-23', '--root', str(self.tmp)],
            capture_output=True, text=True)

    def plan(self, m_tail='Size: M.', l_ticket=True):
        tickets = [ticket(9301, 'Size: S.', 'app/one.py'), ticket(9302, m_tail, 'app/two.py')]
        return tickets + ([ticket(9303, 'Size: L.', 'app/three.py')] if l_ticket else [])

    def test_a_new_spec_refuses_an_l_ticket_and_an_m_without_its_reason(self):
        for created in (SINCE, '2026-12-01T08:00:00Z'):
            with self.subTest(created=created):
                out = self.approve(created, self.plan())
                self.assertEqual((out.returncode, out.stdout), (1, ''), out.stderr)
                sizes = [line for line in out.stderr.splitlines() if line.startswith('approve: sizes: ')]
                self.assertEqual(len(sizes), 2, out.stderr)
                self.assertIn('#9302', sizes[0])
                self.assertIn('Why M:', sizes[0])
                self.assertIn('#9303', sizes[1])
                self.assertIn('Size: L', sizes[1])
                self.assertNotIn('#9301', out.stderr)

    def test_an_m_needs_a_reason_line_in_parent(self):
        for tail in ('Size: M.\nWhy M:', 'Size: M.\nWhy M:   ', 'Size: M. Why M: one file, no seam.',
                     'Size: M.\n\n## Notes\n\nWhy M: one file, no seam.'):
            with self.subTest(tail=tail):
                out = self.approve(SINCE, self.plan(tail, l_ticket=False))
                self.assertEqual(out.returncode, 1, out.stderr)
                self.assertRegex(out.stderr, r'approve: sizes: #9302 .*Why M:')

    def test_a_new_spec_passes_with_s_and_a_reasoned_m(self):
        out = self.approve(SINCE, self.plan('Size: M.\nWhy M: one parser and its only caller; no seam to cut.',
                                            l_ticket=False))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn('sizes S 1, M 1, L 0;', out.stdout)

    def test_an_older_spec_checks_exactly_as_before(self):
        out = self.approve('2026-11-22T23:59:59Z', self.plan())
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stderr, '')
        self.assertIn('Checks: 3 tickets; links 0; relies 3; sizes S 1, M 1, L 1;', out.stdout)


SECOND = 'synthetic-owner/second-repo'
CONTRACT = 'contracts/shared.v1.md'
FAKE_GH = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ['FAKE_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\\n')
world = json.loads(open(os.environ['FAKE_WORLD']).read())
if len(args) != 4 or args[0] != 'api' or args[2] != '--jq' or not args[1].startswith('repos/'):
    sys.exit('unexpected gh call: ' + repr(args))
if world.get('fail'):
    sys.exit('gh: Server Error (HTTP 502)')
kind = world.get('files', {}).get(args[1])
if kind is None:
    sys.exit('gh: Not Found (HTTP 404)')
print(kind)
"""


class CrossRepositoryRelies(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        (self.tmp / 'bin').mkdir()
        (self.tmp / 'bin/gh').write_text(FAKE_GH)
        (self.tmp / 'bin/gh').chmod(0o755)
        (self.tmp / 'root').mkdir()

    def plan(self, contract_state, relies):
        contract = ticket(9311, 'Size: S.', CONTRACT)
        contract['body'] = contract['body'].replace(f'`{CONTRACT}`', f'`{CONTRACT}` in `{SECOND}`')
        contract['state'] = contract_state
        user = ticket(9312, 'Size: S.', 'app/use.py')
        user['blocked_by'] = [{'number': 9311, 'state': contract_state}]
        user['body'] = user['body'].replace('**Relies on:** nothing', f'**Relies on:** {relies}').replace(
            '## Links\n\nnone\n', '## Links\n\n- #9311 real: the shared record, which the app reads\n')
        return [contract, user]

    def approve(self, tickets, world):
        graph = {'schema': 'openwiz.plan-links.v1', 'kind': 'graph', 'repo': 'synthetic-owner/synthetic-repo',
                 'read_at': '2026-11-23T12:00:00Z', 'source': {'kind': 'spec', 'spec': SPEC}, 'tickets': tickets}
        lines = [f'plan-graph revision v2\nspec #{SPEC} body sha256 {sha(SPEC_BODY)}\n']
        for t in tickets:
            blockers = ' '.join(f'#{b["number"]}' for b in t['blocked_by']) or 'none'
            lines.append(f'ticket #{t["number"]} blocked-by {blockers} body sha256 {sha(t["body"])} title {t["title"]}\n')
        revision = ''.join(lines)
        (self.tmp / 'graph.json').write_text(json.dumps(graph))
        (self.tmp / 'revision.txt').write_text(revision)
        (self.tmp / 'spec.json').write_text(json.dumps({'body': SPEC_BODY, 'createdAt': SINCE}))
        (self.tmp / 'world.json').write_text(json.dumps(world))
        (self.tmp / 'gh.log').write_text('')
        env = dict(os.environ, PATH=f'{self.tmp / "bin"}:{os.environ["PATH"]}',
                   FAKE_LOG=str(self.tmp / 'gh.log'), FAKE_WORLD=str(self.tmp / 'world.json'))
        out = subprocess.run(
            ['python3', '-I', str(APPROVE), '--graph', str(self.tmp / 'graph.json'),
             '--revision', str(self.tmp / 'revision.txt'), '--spec', str(self.tmp / 'spec.json'),
             '--grill', GRILL, '--number', '1', '--date', '2026-11-23', '--root', str(self.tmp / 'root')],
            capture_output=True, text=True, env=env)
        calls = [json.loads(line) for line in (self.tmp / 'gh.log').read_text().splitlines()]
        return out, calls

    def test_a_merged_blockers_file_in_another_repository_re_approves_unchanged(self):
        relies = f'`{CONTRACT}` in `{SECOND}`'
        world = {'files': {f'repos/{SECOND}/contents/{CONTRACT}': 'file'}}
        out, calls = self.approve(self.plan('OPEN', relies), world)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(calls, [])
        out, calls = self.approve(self.plan('CLOSED', relies), world)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(out.stdout.startswith('**Machine plan approval, '), out.stdout[:80])
        self.assertEqual([call[:2] for call in calls], [['api', f'repos/{SECOND}/contents/{CONTRACT}']])

    def test_a_missing_file_a_folder_or_another_repository_still_refuses(self):
        cases = [('missing', f'`{CONTRACT}` in `{SECOND}`', {}),
                 ('a folder there', f'`{CONTRACT}` in `{SECOND}`',
                  {'files': {f'repos/{SECOND}/contents/{CONTRACT}': 'folder'}}),
                 ('a symlink there', f'`{CONTRACT}` in `{SECOND}`',
                  {'files': {f'repos/{SECOND}/contents/{CONTRACT}': 'symlink'}}),
                 ('the file in a third repository', f'`{CONTRACT}` in `synthetic-owner/third-repo`',
                  {'files': {f'repos/{SECOND}/contents/{CONTRACT}': 'file'}})]
        for name, relies, world in cases:
            with self.subTest(case=name):
                out, calls = self.approve(self.plan('CLOSED', relies), world)
                self.assertEqual((out.returncode, out.stdout), (1, ''), out.stderr)
                self.assertIn('approve: relies: #9312: Relies on: ', out.stderr)
                self.assertEqual(len(calls), 1, calls)

    def test_an_unreadable_default_branch_fails_closed(self):
        out, calls = self.approve(self.plan('CLOSED', f'`{CONTRACT}` in `{SECOND}`'), {'fail': True})
        self.assertEqual((out.returncode, out.stdout), (2, ''), out.stderr)
        self.assertIn(f'approve: unreadable input: cannot read `{CONTRACT}` in `{SECOND}`', out.stderr)
        self.assertEqual(len(calls), 1, calls)

    def test_a_bad_path_is_refused_without_a_read(self):
        for relies in (f'`../{CONTRACT}` in `{SECOND}`', f'`contracts/*.md` in `{SECOND}`',
                       f'`{CONTRACT}` in `second-repo`'):
            with self.subTest(relies=relies):
                out, calls = self.approve(self.plan('CLOSED', relies), {})
                self.assertEqual((out.returncode, out.stdout), (1, ''), out.stderr)
                self.assertIn('approve: relies: #9312: Relies on: ', out.stderr)
                self.assertEqual(calls, [])

    def test_a_bare_path_reads_nothing_and_checks_the_root_as_before(self):
        world = {'files': {f'repos/{SECOND}/contents/{CONTRACT}': 'file'}}
        out, calls = self.approve(self.plan('CLOSED', f'`{CONTRACT}`'), world)
        self.assertEqual((out.returncode, out.stdout, calls), (1, '', []), out.stderr)
        self.assertIn('approve: relies: #9312: Relies on: file does not exist at its full path', out.stderr)
        (self.tmp / 'root/contracts').mkdir()
        (self.tmp / 'root' / CONTRACT).write_text('Synthetic contract.\n')
        out, calls = self.approve(self.plan('CLOSED', f'`{CONTRACT}`'), world)
        self.assertEqual((out.returncode, calls), (0, []), out.stderr)


if __name__ == '__main__':
    unittest.main()
