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
REGULAR, EXECUTABLE, FOLDER, SYMLINK, SUBMODULE = 0o100644, 0o100755, 0o040000, 0o120000, 0o160000
FAKE_GH = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ['FAKE_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\\n')
world = json.loads(open(os.environ['FAKE_WORLD']).read())
if world.get('fail'):
    sys.exit('gh: Server Error (HTTP 502)')
if args[:2] == ['issue', 'view'] and len(args) == 7 and args[3] == '--repo' and args[5:] == ['--json', 'title']:
    title = world.get('titles', {}).get(args[4] + '#' + args[2])
    if title is None:
        sys.exit('gh: Issue not found')
    print(json.dumps({'title': title}))
    sys.exit(0)
if len(args) == 4 and args[0] == 'api' and args[2] == '--jq' and args[1].startswith('repos/'):
    owner, name, _, path = args[1][len('repos/'):].split('/', 3)
    mode = world.get('files', {}).get(owner + '/' + name + ':' + path)
    if 'answer' in world:
        print('null')
    elif mode is None:
        sys.exit('gh: Not Found (HTTP 404)')
    else:
        print({0o040000: 'folder', 0o160000: 'submodule'}.get(mode, 'file'))
    sys.exit(0)
flags, pairs = args[2::2], args[3::2]
if args[:2] != ['api', 'graphql'] or len(flags) != 4 or len(pairs) != 4 or set(flags) != {'-f'}:
    sys.exit('unexpected gh call: ' + repr(args))
sent = dict(pair.split('=', 1) for pair in pairs)
if sorted(sent) != ['name', 'owner', 'path', 'query'] or 'defaultBranchRef' not in sent['query']:
    sys.exit('unexpected gh call: ' + repr(args))
if 'answer' in world:
    print(json.dumps(world['answer']))
    sys.exit(world.get('exit', 0))
asked = sent['owner'] + '/' + sent['name']
mode = world.get('files', {}).get(asked + ':' + sent['path'])
answer = {'data': {'repository': {'nameWithOwner': world.get('renamed', asked), 'defaultBranchRef': {'target': {
    'file': None if mode is None else {'mode': mode}}}}}}
if mode is None:
    answer['errors'] = [{'type': 'NOT_FOUND', 'path': ['repository', 'defaultBranchRef', 'target', 'file'],
                         'message': 'Could not resolve file for path.'}]
print(json.dumps(answer))
if mode is None:
    sys.exit('gh: Could not resolve file for path.')
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
        for mode in (REGULAR, EXECUTABLE):
            with self.subTest(mode=oct(mode)):
                world = {'files': {f'{SECOND}:{CONTRACT}': mode}}
                out, calls = self.approve(self.plan('OPEN', relies), world)
                self.assertEqual(out.returncode, 0, out.stderr)
                self.assertEqual(calls, [])
                out, calls = self.approve(self.plan('CLOSED', relies), world)
                self.assertEqual(out.returncode, 0, out.stderr)
                self.assertTrue(out.stdout.startswith('**Machine plan approval, '), out.stdout[:80])
                self.assertEqual(len(calls), 1, calls)

    def test_a_missing_file_a_folder_or_another_repository_still_refuses(self):
        cases = [('missing', f'`{CONTRACT}` in `{SECOND}`', {}),
                 ('a folder there', f'`{CONTRACT}` in `{SECOND}`', {'files': {f'{SECOND}:{CONTRACT}': FOLDER}}),
                 ('a submodule there', f'`{CONTRACT}` in `{SECOND}`', {'files': {f'{SECOND}:{CONTRACT}': SUBMODULE}}),
                 ('the file in a third repository', f'`{CONTRACT}` in `synthetic-owner/third-repo`',
                  {'files': {f'{SECOND}:{CONTRACT}': REGULAR}})]
        for name, relies, world in cases:
            with self.subTest(case=name):
                out, calls = self.approve(self.plan('CLOSED', relies), world)
                self.assertEqual((out.returncode, out.stdout), (1, ''), out.stderr)
                self.assertIn('approve: relies: #9312: Relies on: ', out.stderr)
                self.assertEqual(len(calls), 1, calls)

    def test_a_symlink_to_an_existing_regular_file_still_refuses(self):
        world = {'files': {f'{SECOND}:{CONTRACT}': SYMLINK, f'{SECOND}:contracts/real.v1.md': REGULAR}}
        out, calls = self.approve(self.plan('CLOSED', f'`{CONTRACT}` in `{SECOND}`'), world)
        self.assertEqual((out.returncode, out.stdout), (1, ''), out.stderr)
        self.assertIn(f'approve: relies: #9312: Relies on: `{CONTRACT}` is in `{SECOND}`', out.stderr)
        self.assertEqual(len(calls), 1, calls)

    def test_a_path_under_a_dot_folder_is_read_like_any_other(self):
        for path in ('.github/contracts.md', '.contract.md', '-docs/.hidden/x.md'):
            with self.subTest(path=path):
                world = {'files': {f'{SECOND}:{path}': REGULAR}}
                out, calls = self.approve(self.plan('CLOSED', f'`{path}` in `{SECOND}`'), world)
                self.assertEqual(out.returncode, 0, out.stderr)
                self.assertEqual(len(calls), 1, calls)
                out, calls = self.approve(self.plan('CLOSED', f'`{path}` in `{SECOND}`'), {})
                self.assertEqual((out.returncode, out.stdout, len(calls)), (1, '', 1), out.stderr)

    def test_an_unreadable_default_branch_fails_closed(self):
        out, calls = self.approve(self.plan('CLOSED', f'`{CONTRACT}` in `{SECOND}`'), {'fail': True})
        self.assertEqual((out.returncode, out.stdout), (2, ''), out.stderr)
        self.assertIn(f'approve: unreadable input: cannot read `{CONTRACT}` in `{SECOND}`', out.stderr)
        self.assertEqual(len(calls), 1, calls)

    def test_an_answer_of_an_unknown_shape_is_unreadable_not_missing(self):
        def reply(file, **more):
            return {'data': {'repository': {'nameWithOwner': SECOND, 'defaultBranchRef': {'target': {'file': file}}}},
                    **more}
        answers = [('no data', {}), ('a list', []), ('no repository', {'data': {'repository': None}}),
                   ('a target that is no commit', {'data': {'repository': {
                       'nameWithOwner': SECOND, 'defaultBranchRef': {'target': {}}}}}),
                   ('no mode', reply({})), ('a text mode', reply({'mode': '33188'})),
                   ('a true mode', reply({'mode': True})), ('an unknown mode', reply({'mode': 0o100664})),
                   ('a file and an error', reply({'mode': REGULAR}, errors=[{'type': 'NOT_FOUND', 'path': [
                       'repository', 'defaultBranchRef', 'target', 'file']}])),
                   ('another error', reply(None, errors=[{'type': 'FORBIDDEN', 'path': [
                       'repository', 'defaultBranchRef', 'target', 'file']}])),
                   ('a missing repository', {'data': {'repository': None}, 'errors': [
                       {'type': 'NOT_FOUND', 'path': ['repository']}]})]
        for name, answer in answers:
            with self.subTest(case=name):
                out, calls = self.approve(self.plan('CLOSED', f'`{CONTRACT}` in `{SECOND}`'), {'answer': answer})
                self.assertEqual((out.returncode, out.stdout), (2, ''), out.stderr)
                self.assertIn(f'approve: unreadable input: cannot read `{CONTRACT}` in `{SECOND}`', out.stderr)
                self.assertEqual(len(calls), 1, calls)
        out, calls = self.approve(self.plan('CLOSED', f'`{CONTRACT}` in `{SECOND}`'),
                                  {'answer': reply({'mode': REGULAR}), 'exit': 1})
        self.assertEqual((out.returncode, out.stdout), (2, ''), out.stderr)
        out, calls = self.approve(self.plan('CLOSED', f'`{CONTRACT}` in `{SECOND}`'),
                                  {'files': {f'{SECOND}:{CONTRACT}': REGULAR}, 'renamed': 'synthetic-owner/moved-repo'})
        self.assertEqual((out.returncode, out.stdout, len(calls)), (2, '', 1), out.stderr)

    def test_a_present_errors_key_is_unreadable_whatever_its_value(self):
        clean = {'data': {'repository': {'nameWithOwner': SECOND, 'defaultBranchRef': {'target': {
            'file': {'mode': REGULAR}}}}}}
        for value in (None, False, 0, '', {}, []):
            with self.subTest(errors=repr(value)):
                out, calls = self.approve(self.plan('CLOSED', f'`{CONTRACT}` in `{SECOND}`'),
                                          {'answer': {**clean, 'errors': value}})
                self.assertEqual((out.returncode, out.stdout), (2, ''), out.stderr)
                self.assertIn(f'approve: unreadable input: cannot read `{CONTRACT}` in `{SECOND}`', out.stderr)
                self.assertEqual(len(calls), 1, calls)
        out, calls = self.approve(self.plan('CLOSED', f'`{CONTRACT}` in `{SECOND}`'), {'answer': clean})
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(out.stdout.startswith('**Machine plan approval, '), out.stdout[:80])
        self.assertEqual(len(calls), 1, calls)

    def test_a_bad_path_is_refused_without_a_read(self):
        for relies in (f'`../{CONTRACT}` in `{SECOND}`', f'`contracts/*.md` in `{SECOND}`',
                       f'`contracts/./shared.md` in `{SECOND}`', f'`{CONTRACT}` in `second-repo`'):
            with self.subTest(relies=relies):
                out, calls = self.approve(self.plan('CLOSED', relies), {})
                self.assertEqual((out.returncode, out.stdout), (1, ''), out.stderr)
                self.assertIn('approve: relies: #9312: Relies on: ', out.stderr)
                self.assertEqual(calls, [])

    def test_a_malformed_declaration_is_refused_before_any_read(self):
        world = {'files': {f'{SECOND}:{CONTRACT}': REGULAR, f'{SECOND}:docs/other.md': REGULAR}}
        good = f'`{CONTRACT}` in `{SECOND}`'
        for name, relies in (('a missing comma', f'{good} `docs/other.md` in `{SECOND}`'),
                             ('prose after it', f'{good} and friends'),
                             ('a bad repository beside a good one', f'{good}, `docs/other.md` in `second-repo`'),
                             ('a bad path beside a good one', f'{good}, `docs/*.md` in `{SECOND}`'),
                             ('a missing bare path beside it', f'{good}, `docs/absent.md`')):
            with self.subTest(case=name):
                out, calls = self.approve(self.plan('CLOSED', relies), world)
                self.assertEqual((out.returncode, out.stdout), (1, ''), out.stderr)
                self.assertIn('approve: relies: #9312: Relies on: ', out.stderr)
                self.assertEqual(calls, [])

    def test_a_bare_path_reads_nothing_and_checks_the_root_as_before(self):
        world = {'files': {f'{SECOND}:{CONTRACT}': REGULAR}}
        out, calls = self.approve(self.plan('CLOSED', f'`{CONTRACT}`'), world)
        self.assertEqual((out.returncode, out.stdout, calls), (1, '', []), out.stderr)
        self.assertIn('approve: relies: #9312: Relies on: file does not exist at its full path', out.stderr)
        (self.tmp / 'root/contracts').mkdir()
        (self.tmp / 'root' / CONTRACT).write_text('Synthetic contract.\n')
        out, calls = self.approve(self.plan('CLOSED', f'`{CONTRACT}`'), world)
        self.assertEqual((out.returncode, calls), (0, []), out.stderr)


FLAT = HERE.parent / 'test/flat'
FLAT_SINCE = '2026-11-28T00:00:00Z'


class FlatGraphs(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        (self.tmp / 'bin').mkdir()
        fake_gh = self.tmp / 'bin/gh'
        fake_gh.write_text(FAKE_GH)
        fake_gh.chmod(0o755)

    def approve(self, graph, created=FLAT_SINCE, extra='', titles=None):
        spec_body = SPEC_BODY + extra
        lines = [f'plan-graph revision v2\nspec #{graph["source"]["spec"]} body sha256 {sha(spec_body)}\n']
        for t in graph['tickets']:
            blockers = ' '.join(f'#{n}' for n in sorted(b['number'] for b in t['blocked_by'])) or 'none'
            lines.append(f'ticket #{t["number"]} blocked-by {blockers} body sha256 {sha(t["body"])} title {t["title"]}\n')
        (self.tmp / 'graph.json').write_text(json.dumps(graph))
        (self.tmp / 'revision.txt').write_text(''.join(lines))
        (self.tmp / 'spec.json').write_text(json.dumps({'body': spec_body, 'createdAt': created}))
        (self.tmp / 'world.json').write_text(json.dumps({'titles': titles or {}}))
        (self.tmp / 'gh.log').write_text('')
        env = dict(os.environ, PATH=f'{self.tmp / "bin"}:{os.environ["PATH"]}',
                   FAKE_LOG=str(self.tmp / 'gh.log'), FAKE_WORLD=str(self.tmp / 'world.json'))
        return subprocess.run(
            ['python3', '-I', str(APPROVE), '--graph', str(self.tmp / 'graph.json'),
             '--revision', str(self.tmp / 'revision.txt'), '--spec', str(self.tmp / 'spec.json'),
             '--grill', GRILL, '--number', '1', '--date', '2026-11-28', '--root', str(self.tmp)],
            capture_output=True, text=True, env=env)

    def settings(self, name):
        return json.loads((FLAT / f'settings-{name}.json').read_text())

    def chain(self, count, links, titles=None):
        tickets = [ticket(9320 + i, 'Size: S.', f'app/part{i}.py') for i in range(count)]
        for i, t in enumerate(tickets):
            t['title'] = (titles or {}).get(i, t['title'])
            if i in links:
                t['blocked_by'] = [{'number': 9320 + i - 1, 'state': 'OPEN'}]
                t['body'] = t['body'].replace('## Links\n\nnone\n', f'## Links\n\n- #{9320 + i - 1} real: {links[i]}\n')
        return {'schema': 'openwiz.plan-links.v1', 'kind': 'graph', 'repo': 'synthetic-owner/synthetic-repo',
                'read_at': '2026-11-28T12:00:00Z', 'source': {'kind': 'spec', 'spec': SPEC}, 'tickets': tickets}

    def test_the_settings_plan_is_refused_before_its_re_cut_and_passes_after(self):
        out = self.approve(self.settings('before'))
        self.assertEqual((out.returncode, out.stdout), (1, ''), out.stderr)
        width = [line for line in out.stderr.splitlines() if line.startswith('approve: width: ')]
        self.assertEqual(len(width), 1, out.stderr)
        self.assertIn('the critical chain is 7 for 13 open tickets', width[0])
        self.assertIn('Why deep:', width[0])
        links = [line for line in out.stderr.splitlines() if line.startswith('approve: links: ')]
        self.assertEqual([line.split(':')[2].strip() for line in links], ['#3379', '#3380', '#3381'], out.stderr)
        self.assertIn('the real line for #3377 names only an interface', links[0])
        out = self.approve(self.settings('after'))
        self.assertEqual((out.returncode, out.stderr), (0, ''), out.stderr)
        self.assertIn('Checks: 15 tickets; links 29;', out.stdout)
        self.assertIn('width: chain 5, widest 4;', out.stdout)

    def test_a_spec_before_flat_since_checks_exactly_as_before(self):
        out = self.approve(self.settings('before'), created='2026-11-27T23:59:59Z')
        self.assertEqual((out.returncode, out.stderr), (0, ''), out.stderr)
        self.assertIn('width: chain 7, widest 4;', out.stdout)

    def test_why_deep_must_name_one_of_the_graphs_tickets(self):
        graph = self.settings('before')
        for line in ('Why deep: the commands come one after another.', 'Why deep: #9999 is slow.',
                     'Why deep:', '<!-- Why deep: #3377 then #3976 -->'):
            with self.subTest(line=line):
                out = self.approve(graph, extra=f'\n{line}\n')
                self.assertIn('approve: width: the critical chain is 7', out.stderr)
        out = self.approve(graph, extra='\nWhy deep: #3977 undoes through the writer #3976 adds to the reader #3377.\n')
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertNotIn('approve: width:', out.stderr)
        self.assertIn('approve: links: #3379:', out.stderr)

    def test_a_chain_is_held_to_five_and_to_two_thirds_of_the_open_tickets_over_three(self):
        work = 'the reader that resolves each row, which the next part calls'
        for count, depth, refused in ((6, 6, True), (12, 6, True), (9, 5, False), (5, 4, True), (6, 4, False),
                                      (3, 3, False)):
            with self.subTest(count=count, depth=depth):
                out = self.approve(self.chain(count, {i: work for i in range(1, depth)}))
                self.assertEqual(out.returncode, 1 if refused else 0, out.stderr)
                self.assertEqual('approve: width: the critical chain' in out.stderr, refused, out.stderr)
                if not refused:
                    self.assertIn(f'width: chain {depth}, ', out.stdout)

    def test_the_skill_summary_states_the_depth_ratio_floor(self):
        skill = ' '.join((HERE.parent / 'SKILL.md').read_text().split())
        self.assertTrue('over 3 and over 2/3 of the open tickets' in skill, 'the summary must state the ratio floor')

    def test_an_open_native_blocker_outside_the_spec_can_be_contract_first(self):
        reason = '`tool show --json`, which the next part calls'
        graph = self.chain(4, {1: reason, 2: reason})
        graph['tickets'].pop(0)
        graph['tickets'][1]['blocked_by'][0]['number'] = 9320
        graph['tickets'][1]['body'] = graph['tickets'][1]['body'].replace('#9321 real:', '#9320 real:')
        key = f'{graph["repo"]}#9320'
        out = self.approve(graph, titles={key: 'The tool command, first'})
        self.assertEqual((out.returncode, out.stderr), (0, ''), out.stderr)
        calls = [json.loads(line) for line in (self.tmp / 'gh.log').read_text().splitlines()]
        self.assertEqual(calls, [['issue', 'view', '9320', '--repo', graph['repo'], '--json', 'title']])

        out = self.approve(graph, titles={key: 'Implement the tool command'})
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn('the real line for #9320 names only an interface', out.stderr)

        out = self.approve(graph)
        self.assertEqual(out.returncode, 2, out.stderr)
        self.assertIn('cannot read the title of #9320', out.stderr)

        out = self.approve(graph, created='2026-11-27T23:59:59Z')
        self.assertEqual((out.returncode, out.stderr), (0, ''), out.stderr)
        self.assertEqual((self.tmp / 'gh.log').read_text(), '')

    def test_a_real_line_that_names_only_an_interface_is_refused(self):
        refused = ('`tool show --json`, which the next part calls', 'the `tool set` command and its flags',
                   '`tool show` and `set` answers and exit codes, that the skill reads')
        passed = ('`tool show`, the reader that resolves each row, which the next part calls',
                  '`tool set`, which this ticket extends with a `--dry-run` flag',
                  'the `--runner` option on `tool plan`, which this ticket builds on')
        for reason in refused + passed:
            with self.subTest(reason=reason):
                out = self.approve(self.chain(3, {1: reason}))
                self.assertEqual(out.returncode, 1 if reason in refused else 0, out.stderr)
                if reason in refused:
                    self.assertEqual(out.stderr, 'approve: links: #9321: the real line for #9320 names only an '
                                     'interface, not the behaviour #9321 needs; name that behaviour, or say the '
                                     "ticket extends #9320's code, or block on a contract-first ticket instead\n")
        reason = refused[0]
        for name, graph in (('a contract-first blocker', self.chain(3, {1: reason}, {0: 'The tool command, first'})),
                            ('a live check', self.chain(3, {1: reason}, {1: 'Live check: the tool on a box'}))):
            with self.subTest(case=name):
                out = self.approve(graph)
                self.assertEqual((out.returncode, out.stderr), (0, ''), out.stderr)
        graph = self.chain(3, {1: reason})
        graph['tickets'][0]['state'] = 'CLOSED'
        graph['tickets'][1]['blocked_by'][0]['state'] = 'CLOSED'
        out = self.approve(graph)
        self.assertEqual((out.returncode, out.stderr), (0, ''), out.stderr)
        out = self.approve(self.chain(3, {1: reason}), created='2026-11-27T23:59:59Z')
        self.assertEqual((out.returncode, out.stderr), (0, ''), out.stderr)


if __name__ == '__main__':
    unittest.main()
