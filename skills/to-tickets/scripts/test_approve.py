"""approve.py's size limit (openwizdev/OpenWiz#2495): run approve.py on synthetic graph, revision and spec files."""
import hashlib
import json
from pathlib import Path
import re
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
        # catches: a post-cutoff plan with an L ticket or a bare M still getting a machine approval.
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
        # catches: an empty reason, or a `Why M:` outside Parent, counting as the reason.
        for tail in ('Size: M.\nWhy M:', 'Size: M.\nWhy M:   ', 'Size: M. Why M: one file, no seam.',
                     'Size: M.\n\n## Notes\n\nWhy M: one file, no seam.'):
            with self.subTest(tail=tail):
                out = self.approve(SINCE, self.plan(tail, l_ticket=False))
                self.assertEqual(out.returncode, 1, out.stderr)
                self.assertRegex(out.stderr, r'approve: sizes: #9302 .*Why M:')

    def test_a_new_spec_passes_with_s_and_a_reasoned_m(self):
        # catches: the new rule refusing a plan that keeps to it.
        out = self.approve(SINCE, self.plan('Size: M.\nWhy M: one parser and its only caller; no seam to cut.',
                                            l_ticket=False))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn('sizes S 1, M 1, L 0;', out.stdout)

    def test_an_older_spec_checks_exactly_as_before(self):
        # catches: the cutoff reaching back and failing an existing approved plan.
        out = self.approve('2026-11-22T23:59:59Z', self.plan())
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stderr, '')
        self.assertIn('Checks: 3 tickets; links 0; relies 3; sizes S 1, M 1, L 1;', out.stdout)

    def test_the_cutoff_is_the_ruled_merge_day(self):
        # catches: the cutoff moving without a ruling.
        text = APPROVE.read_text()
        self.assertEqual(re.findall(r"^SIZES_SINCE = '(\S+)'$", text, re.M), [SINCE])

    def test_to_tickets_gives_the_line_and_file_limit_and_the_m_rule(self):
        # catches: the planner's text and approve.py disagreeing on the limit.
        skill = (HERE.parent / 'SKILL.md').read_text()
        step = ' '.join(skill.split('## 2. Cut the tickets', 1)[1].split('\n## 3.', 1)[0].split())
        inputs = ' '.join((HERE.parent / 'tickets.md').read_text().split())
        for text in (step, inputs):
            for words in ('about 400 changed lines', '10 files or fewer', '`Why M: <reason it can\'t split>`'):
                self.assertIn(words, text)
            self.assertRegex(text, r'L is split')


if __name__ == '__main__':
    unittest.main()
