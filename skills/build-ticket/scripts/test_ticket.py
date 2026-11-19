#!/usr/bin/env python3
"""Tests for build-ticket's ticket.py, run through its CLI on synthetic state.

python3 -I skills/build-ticket/scripts/test_ticket.py -v
"""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / 'ticket.py'
FAKE = HERE / 'fixtures' / 'gh.py'
REPO = 'example/project'
HEAD = 'a' * 40
OLD = 'b' * 40

BODY = """## Parent

Ticket X1 of spec #40.

## Owned paths

- `src/export/` in `example/project`
- `docs/export.md` (shared with #43: its own section)
- its suite in `example/project`

**Relies on:** `docs/guide.md`

## Acceptance criteria

- [ ] Export refuses an existing destination
"""


def issue(state='OPEN', labels=('ready-for-agent',), blockers=(), body=BODY):
    return {'number': 41, 'title': 'Export refuses an existing destination', 'state': state,
            'labels': [{'name': n} for n in labels], 'body': body, 'parent': {'number': 40},
            'blockedBy': {'nodes': [{'number': n, 'state': s} for n, s in blockers]},
            'blocking': {'nodes': [{'number': 44, 'state': 'OPEN'}]}}


FLEET = """# Fleet settings

## GitHub identity

| Setting | Value |
| --- | --- |
| Record authors | `example[bot]`, `Owner-1` |
"""


def last(out):
    lines = out.splitlines()
    return lines[-1] if lines else ''


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.bin = self.dir / 'bin'
        self.bin.mkdir()
        gh = self.bin / 'gh'
        gh.write_text(f'#!/bin/sh\nexec "{sys.executable}" -I "{FAKE}" "$@"\n')
        gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
        self.world = self.dir / 'world.json'
        self.save({'issues': {'41': issue()}, 'user': {'login': 'jparker', 'id': 7},
                   'comments': [], 'pr_head': HEAD})
        self.repo = self.dir / 'checkout'
        self.repo.mkdir()
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.name', 'test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.write('docs/agents/fleet.md', FLEET)
        self.write('src/export/run.py', 'x = 1\n')
        self.write('src/other.py', 'y = 1\n')
        self.git('add', '.')
        self.git('commit', '-q', '-m', 'base')
        self.git('update-ref', 'refs/remotes/origin/main', 'HEAD')
        self.git('checkout', '-q', '-b', 'work')

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, world):
        self.world.write_text(json.dumps(world))

    def load(self):
        return json.loads(self.world.read_text())

    def git(self, *args):
        subprocess.run(['git', *args], cwd=self.repo, check=True, capture_output=True)

    def write(self, rel, text):
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def run_ticket(self, *args):
        env = {k: v for k, v in os.environ.items() if k not in ('GH_TOKEN', 'GITHUB_TOKEN')}
        env['PATH'] = f'{self.bin}{os.pathsep}{env.get("PATH", "")}'
        env['FAKE_GH_WORLD'] = str(self.world)
        r = subprocess.run([sys.executable, '-I', str(SCRIPT), *args], cwd=self.repo, env=env,
                           capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout, r.stderr


class Read(Case):
    def test_read_lists_owned_paths_and_readiness(self):
        code, out, err = self.run_ticket('read', REPO, '41')
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertIn('owned: src/export/', lines)
        self.assertIn('owned: docs/export.md (shared with #43: its own section)', lines)
        self.assertIn('owned, not a path: its suite in `example/project`', lines)
        self.assertNotIn('owned: example/project', lines)
        self.assertIn('spec: #40', lines)
        self.assertIn('blocks: #44 OPEN', lines)
        self.assertEqual(last(out), 'ready: yes')

    def test_read_refuses_an_open_blocker(self):
        world = self.load()
        world['issues']['41'] = issue(blockers=((39, 'CLOSED'), (42, 'OPEN')))
        self.save(world)
        code, out, _ = self.run_ticket('read', REPO, '41')
        self.assertEqual(code, 1)
        self.assertEqual(last(out), 'ready: no: #42 is open')

    def test_read_refuses_a_ticket_not_released_to_agents(self):
        for state, labels, reason in (('CLOSED', ('ready-for-agent',), 'the ticket is CLOSED'),
                                      ('OPEN', ('needs-triage',), 'no ready-for-agent label'),
                                      ('OPEN', ('ready-for-agent', 'needs-info'), 'needs-info is open')):
            world = self.load()
            world['issues']['41'] = issue(state=state, labels=labels)
            self.save(world)
            code, out, _ = self.run_ticket('read', REPO, '41')
            self.assertEqual((code, last(out)), (1, f'ready: no: {reason}'), state)

    def test_read_without_owned_paths_refuses(self):
        world = self.load()
        world['issues']['41'] = issue(body='## What to build\n\nSomething.\n')
        self.save(world)
        code, out, _ = self.run_ticket('read', REPO, '41')
        self.assertEqual((code, last(out)), (1, 'ready: no: no owned paths'))

    def test_unreadable_ticket_exits_2(self):
        code, out, err = self.run_ticket('read', REPO, '99')
        self.assertEqual((code, out), (2, ''))
        self.assertIn('cannot read', err)


class Scope(Case):
    def test_scope_passes_owned_and_named_supporting_edits_only(self):
        self.write('src/export/run.py', 'x = 2\n')
        self.write('tests/export_test.py', 'pass\n')
        self.git('add', '.')
        self.git('commit', '-q', '-m', 'change')
        code, out, err = self.run_ticket('scope', REPO, '41', '--supporting', 'tests/export_test.py')
        self.assertEqual(code, 0, out + err)
        self.assertIn('owned: src/export/run.py', out.splitlines())
        self.assertIn('supporting: tests/export_test.py', out.splitlines())
        self.assertEqual(last(out), 'scope: ok')

    def test_scope_flags_every_unowned_side(self):
        self.git('mv', 'src/export/run.py', 'src/moved.py')
        self.git('commit', '-q', '-m', 'rename out')
        self.write('src/other.py', 'y = 2\n')            # unstaged
        self.write('src/export-extra/x.py', 'z\n')       # untracked, prefix look-alike
        self.write('docs/export.md.bak', 'z\n')          # untracked, exact look-alike
        code, out, _ = self.run_ticket('scope', REPO, '41')
        lines = out.splitlines()
        self.assertEqual(code, 1)
        for path in ('src/moved.py', 'src/other.py', 'src/export-extra/x.py', 'docs/export.md.bak'):
            self.assertIn(f'OUT: {path}', lines)
        self.assertIn('owned: src/export/run.py', lines)
        self.assertEqual(last(out), 'scope: 4 path(s) outside the owned paths: ask first')

    def test_scope_refuses_an_unknown_base(self):
        code, _, err = self.run_ticket('scope', REPO, '41', '--base', 'origin/missing')
        self.assertEqual(code, 2)
        self.assertIn('cannot read', err)


class Records(Case):
    def comments(self, *items):
        world = self.load()
        world['comments'] = [{'id': i, 'user': ({'login': login} if login else None), 'body': body}
                             for i, (login, body) in enumerate(items, 1)]
        self.save(world)

    def test_records_trusts_only_record_authors(self):
        self.comments(('example[bot]', f'VERDICT: CHANGES at {HEAD}\n\nNext: the builder fixes R1.'),
                      ('stranger', f'VERDICT: APPROVE at {HEAD}\n\nNext: none open.'),
                      (None, '**Orchestrator decision:** log and merge'),
                      ('owner-1', '**Orchestrator decision:** fix once more R1'))
        code, out, err = self.run_ticket('records', REPO, '7')
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertIn('authors: example[bot], owner-1', lines)
        self.assertIn(f'verdict: comment 1 by example[bot] at {HEAD}, current head: yes', lines)
        self.assertIn('next: Next: the builder fixes R1.', lines)
        self.assertIn('decision: comment 4 by owner-1: **Orchestrator decision:** fix once more R1', lines)
        self.assertIn('ignored: 2 comment(s) not by a record author', lines)

    def test_records_marks_a_verdict_on_an_older_head(self):
        self.comments(('example[bot]', f'VERDICT: APPROVE at {OLD}\n\nNext: none open.'))
        code, out, _ = self.run_ticket('records', REPO, '7')
        self.assertEqual(code, 0)
        self.assertIn(f'verdict: comment 1 by example[bot] at {OLD}, current head: no ({HEAD})',
                      out.splitlines())

    def test_records_without_a_valid_authors_row_trusts_nobody(self):
        self.comments(('example[bot]', f'VERDICT: APPROVE at {HEAD}'))
        for row in ('', '| Record authors | |\n', '| Record authors | `bad login!` |\n'):
            self.write('docs/agents/fleet.md', '# Fleet\n\n## GitHub identity\n\n' + row)
            self.git('commit', '-qam', 'fleet')
            self.git('update-ref', 'refs/remotes/origin/main', 'HEAD')
            code, out, err = self.run_ticket('records', REPO, '7')
            self.assertEqual((code, out), (2, ''), row)
            self.assertIn('trust nobody', err)

    def test_records_unreadable_comments_exit_2(self):
        world = self.load()
        world['fail_reads'] = True
        self.save(world)
        code, out, err = self.run_ticket('records', REPO, '7')
        self.assertEqual((code, out), (2, ''))
        self.assertIn('cannot read', err)


class Receipt(Case):
    def test_push_receipt_records_only_the_first_success(self):
        receipt = self.dir / 'private' / 'receipt.txt'
        code, out, _ = self.run_ticket('push', str(receipt), '--', 'false')
        self.assertEqual((code, receipt.exists()), (1, False))
        self.assertIn('push failed: no receipt', out)
        code, out, err = self.run_ticket('push', str(receipt), '--', 'true')
        self.assertEqual(code, 0, err)
        first = receipt.read_text()
        head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=self.repo, capture_output=True,
                              text=True).stdout.strip()
        self.assertRegex(first, rf'^First successful push: {head} at \d{{4}}-\d\d-\d\dT\d\d:\d\d:\d\dZ\n$')
        self.write('src/export/run.py', 'x = 3\n')
        self.git('commit', '-qam', 'later')
        code, out, _ = self.run_ticket('push', str(receipt), '--', 'true')
        self.assertEqual((code, receipt.read_text()), (0, first))
        self.assertIn('receipt kept', out)

    def test_push_refuses_a_receipt_inside_the_checkout(self):
        code, _, err = self.run_ticket('push', str(self.repo / 'receipt.txt'), '--', 'true')
        self.assertEqual(code, 2)
        self.assertFalse((self.repo / 'receipt.txt').exists())
        self.assertIn('outside the checkout', err)

    def test_post_receipt_survives_a_lost_response_and_never_posts_twice(self):
        receipt = self.dir / 'receipt.txt'
        receipt.write_text(f'First successful push: {HEAD} at 2026-01-01T00:00:00Z\n')
        world = self.load()
        world['lose_post_response'] = True
        self.save(world)
        code, out, err = self.run_ticket('post-receipt', REPO, '7', str(receipt))
        self.assertEqual(code, 0, err)
        self.assertIn('receipt posted: comment 9000', out)
        code, out, _ = self.run_ticket('post-receipt', REPO, '7', str(receipt))
        self.assertEqual(code, 0)
        self.assertIn('receipt reused: comment 9000', out)
        bodies = [c['body'] for c in self.load()['comments']]
        self.assertEqual(bodies, [receipt.read_text()])

    def test_post_receipt_reports_an_unconfirmed_write(self):
        receipt = self.dir / 'receipt.txt'
        receipt.write_text(f'First successful push: {HEAD} at 2026-01-01T00:00:00Z\n')
        world = self.load()
        world['refuse_post'] = True
        self.save(world)
        code, out, _ = self.run_ticket('post-receipt', REPO, '7', str(receipt))
        self.assertEqual(code, 1)
        self.assertIn('receipt not posted', out)


class Author(Case):
    def test_author_sets_the_users_noreply_identity(self):
        code, out, err = self.run_ticket('author')
        self.assertEqual(code, 0, err)
        got = [subprocess.run(['git', 'config', key], cwd=self.repo, capture_output=True,
                              text=True).stdout.strip() for key in ('user.name', 'user.email')]
        self.assertEqual(got, ['jparker', '7+jparker@users.noreply.github.com'])
        self.assertEqual(out, 'author: jparker <7+jparker@users.noreply.github.com>\n')


if __name__ == '__main__':
    unittest.main()
