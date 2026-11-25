import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


CLI = Path(__file__).with_name('context.py').resolve()
CARD = 'docs/agents/public-writes.md'
FLEET = 'docs/agents/fleet.md'
LABELS = 'docs/agents/triage-labels.md'
TABLE = '| Role | Label |\n| --- | --- |\n| triage | needs-triage |\n'


def section(name):
    return f'## {name}\n\nSynthetic {name}.\n'


class ContextTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        self.git('init', '-q')

    def git(self, *args):
        return subprocess.check_output(
            ['git', '-c', 'user.name=Synthetic', '-c', 'user.email=fixture@example.com',
             '-c', 'core.hooksPath=/dev/null', *args], cwd=self.root, env=self.env, text=True).strip()

    def put(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def run_cli(self, *args, cwd=None):
        return subprocess.run([sys.executable, '-I', CLI, *args], cwd=cwd or self.root,
                              env=self.env, capture_output=True, text=True)

    def test_role_sections_and_sources(self):
        builder = ['Supporting edits', 'Test commands', 'Approval rules']
        reviewer = ['Supporting edits', 'Test commands', 'CI checks', 'Approval rules']
        planner = ['Labels', 'Supporting edits']
        fleet = ['Models', 'CI checks', 'Labels', 'Other', 'Approval rules']
        legacy = ['Builder', 'Builder for small tickets', 'Reviewer for Claude-built',
                  'Reviewer for GPT-built', 'Fixer']
        self.put(FLEET, '# Fleet\n\n' + '\n'.join(map(section, legacy + fleet + builder[:2])))
        self.put(CARD, '# Public writes\n\nSynthetic card.\n')
        self.put(LABELS, '# Triage\n\n## Labels\n\nLead prose.\n\n' + TABLE + '\nTail prose.\n')
        self.put('docs/agents/host.md', '# Host\n\nSynthetic host.\n')
        self.put('docs/agents/roads.md', '# Roads\n\nSynthetic roads.\n')
        self.put('docs/agents/domain.md', section('Public') + '\n' + section('Private storage'))
        self.put('docs/agents/issue-tracker.md',
                 '\n'.join(map(section, ['Where things live', 'Unused', 'Repositories'])))
        self.put('GLOSSARY.md', '# Terms\n\n**Cherry**:\n\nDefinition with **emphasis**.\n\n**Pear**: Fruit.\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'Synthetic project')
        glossary = ('Use the words in `GLOSSARY.md`; read it when you name something new, '
                    'and the ADRs in `docs/adr/` that touch your area.')
        tracker = 'docs/agents/issue-tracker.md'
        domain = 'docs/agents/domain.md'
        roads = 'docs/agents/roads.md'
        host = 'docs/agents/host.md'
        cases = [
            ('builder', builder, [('GLOSSARY.md', glossary)]),
            ('reviewer', ['Models', *reviewer], [('GLOSSARY.md', glossary)]),
            ('fleet', fleet, [(LABELS, '# Triage\n\n## Labels\n\nLead prose.\n\n' + TABLE + '\nTail prose.'),
                              (host, '# Host\n\nSynthetic host.')]),
            ('planner', planner, [(tracker, section('Where things live').strip() + '\n\n'
                                    + section('Repositories').strip()),
                                   (LABELS, TABLE.strip()), (domain, section('Private storage').strip()),
                                   (roads, '# Roads\n\nSynthetic roads.'),
                                   ('GLOSSARY.md', glossary)]),
        ]
        for role, sections, extras in cases:
            with self.subTest(role=role):
                result = self.run_cli(role, '--root', str(self.root), cwd=self.root / 'docs')
                header, _, body = result.stdout.partition('\n\n')
                source_line, _, body = body.partition('\n\n')
                paths = [CARD, FLEET, *(path for path, _ in extras)]
                self.assertEqual(body, '\n\n'.join(['# Public writes\n\nSynthetic card.',
                                 *(section(name).strip() for name in sections),
                                 *(value for _, value in extras)]) + '\n')
                self.assertEqual(header, f'# Context for {role} at {self.git("rev-parse", "--short", "HEAD")}')
                self.assertEqual(source_line, 'Blobs: ' + ', '.join(
                    f'{path} {self.git("rev-parse", f"HEAD:{path}")}' for path in paths))
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stderr, '')

        with self.subTest(role='reviewer', settings='legacy'):
            claude_table = 'Reviewer for Claude-built'
            gpt_table = 'Reviewer for GPT-built'
            self.put(FLEET, '\n'.join(map(section, [gpt_table, 'Builder', *reviewer, claude_table])))
            result = self.run_cli('reviewer')
            body = result.stdout.split('\n\n', 2)[-1]
            self.assertEqual(body, '\n\n'.join([
                '# Public writes\n\nSynthetic card.',
                *(section(name).strip() for name in [claude_table, gpt_table, *reviewer]),
                glossary,
            ]) + '\n')
            self.assertEqual((result.returncode, result.stderr), (0, ''))

    def test_reviewer_and_fleet_keep_the_private_record_link_only(self):
        url = 'https://github.com/jparker2006/ClosedWiz/issues/' + '4' + '#issuecomment-' + '2'
        self.put(CARD, '# Public writes\n\nSynthetic card.\n')
        self.put(FLEET, '\n'.join([
            '## Models', '', 'Synthetic models.', '',
            f'Source: a long provenance note ([private record]({url})).', '',
            '**Kept for older skills:** keep the five tables.', '',
            '## Supporting edits', '',
            f'Keep this rule. Source: Jake ([private record]({url})).', '',
            '## Test commands', '', 'Run the local proof.', '',
            'Source: see the workflow.', '',
            '## CI checks', '', 'Synthetic checks.', '',
            '## Approval rules', '', 'Synthetic rules.',
        ]))
        self.git('add', '.')
        self.git('commit', '-qm', 'Synthetic project')
        reviewer = self.run_cli('reviewer')
        fleet = self.run_cli('fleet')
        builder = self.run_cli('builder')
        self.assertEqual((reviewer.returncode, fleet.returncode, builder.returncode), (0, 0, 0))
        for result in (reviewer, fleet):
            self.assertIn(f'Source: {url}', result.stdout)
            self.assertIn('**Kept for older skills:** keep the five tables.', result.stdout)
            self.assertNotIn('long provenance note', result.stdout)
        self.assertIn('Keep this rule.', reviewer.stdout)
        self.assertNotIn('see the workflow', reviewer.stdout)
        self.assertNotIn('Source: Jake', reviewer.stdout)
        self.assertIn('see the workflow', builder.stdout)
        self.assertIn('Source: Jake', builder.stdout)

    def test_missing_sources_and_legacy_only_settings(self):
        missing = self.run_cli('builder')
        self.assertIn('read the open-development contract before your first public write.', missing.stdout)
        self.assertIn('run the `setup` skill first', missing.stdout)
        self.assertEqual(missing.returncode, 0)
        self.put(FLEET, section('Builder') + '\n' + section('Test commands'))
        reader = self.run_cli('builder', cwd=self.root / 'docs')
        self.assertIn(f'{FLEET} untracked', reader.stdout)
        self.assertIn(f'No `Supporting edits` section in `{FLEET}`.\n', reader.stdout)
        self.assertIn(f'No `Approval rules` section in `{FLEET}`.\n', reader.stdout)
        legacy = self.run_cli('fleet')
        self.assertIn(section('Builder'), legacy.stdout)
        self.assertNotIn('## Test commands', legacy.stdout)
        self.assertEqual((reader.returncode, legacy.returncode), (0, 0))

    def test_reports_kinds_and_locations_without_echo(self):
        planted = [('thr_' + 'planted1', 'thread id'), ('loop_' + 'planted1', 'loop id'),
                   *((prefix + '_planted1', 'CloudRoom id')
                     for prefix in ('proj', 'prj', 'mch', 'usr', 'acct', 'auto', 'cr')),
                   ('/Users/' + 'planted', 'home folder'), ('/home/' + 'runner-planted', 'home folder'),
                   ('fixture@' + 'planted.invalid', 'email address'),
                   ('fixture@example.com.' + 'planted.invalid', 'email address'),
                   ('fixture@host.example.' + 'planted.invalid', 'email address'),
                   ('fixture@' + 'github.com', 'email address'),
                   ('ghp_' + 'syntheticSeed', 'token shape'), ('github_pat_' + 'synthetic_seed', 'token shape'),
                   ('AKIA' + '0' * 16, 'token shape'), ('sk-' + 'X' * 16, 'token shape'),
                   ('xoxb-' + 'X' * 16, 'token shape'),
                   ('**Synthetic decision:** \\"Fixture words"', 'quoted decision words'),
                   ('**Synthetic decision:** “Fixture words”', 'quoted decision words')]
        self.put('comment.md', '\n'.join(value for value, _ in planted))
        self.put('other.md', 'Plain text\n' + planted[0][0])
        result = self.run_cli('check', 'comment.md', 'other.md')
        self.assertEqual(result.stdout.splitlines(), [
            *(f'comment.md:{i}: {kind}' for i, (_, kind) in enumerate(planted, 1)),
            'other.md:2: thread id', f'check: refused ({len(planted) + 1})'])
        self.assertEqual((result.returncode, result.stderr), (1, ''))

    def test_allows_synthetic_forms(self):
        self.put('comment.md', ' '.join([
            *(f'{prefix}_{example}1' for prefix in ('thr', 'loop', 'proj', 'prj', 'mch', 'usr', 'acct', 'auto', 'cr')
              for example in ('syn', 'web')),
            *('/home/' + name for name in ('runner', 'cache', 'token', 'secret', 'someone', 'synthetic-name',
                                           'example-name', '<name>')),
            'fixture@example.com fixture@example.org fixture@example.net fixture@example.invalid',
            'fixture@two.host.example 123+fixture@users.noreply.github.com noreply@github.com',
            'Ordinary prose:** "A quotation without a bold lead."',
            '**Ordinary emphasis** followed by prose:** "An unrelated quotation."',
        ]))
        result = self.run_cli('check', 'comment.md')
        self.assertEqual((result.stdout, result.returncode, result.stderr), ('check: ok\n', 0, ''))

    def test_delegate_is_read_only_and_fails_closed(self):
        self.put('tools/privacy-check/check.py', """import argparse
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--title-file', type=Path, required=True)
p.add_argument('--body-file', type=Path, required=True)
a = p.parse_args()
assert a.title_file.read_bytes() == b''
body = a.body_file.read_text()
if body == 'Refuse':
    print('T3 pr-body:1')
    print('Sensitive fixture diagnostic')
    raise SystemExit(1)
raise SystemExit(3 if body == 'Broken' else 0)
""")
        self.put('ok.md', 'Allow')
        self.put('bad.md', 'Refuse')
        self.put('broken.md', 'Broken')
        files = list(self.root.rglob('*'))
        result = self.run_cli('check', 'ok.md', 'bad.md', 'bad.md')
        self.assertEqual((result.stdout, result.returncode, result.stderr),
                         ('bad.md:1: project privacy check T3\nbad.md:1: project privacy check T3\n'
                          'check: refused (2)\n', 1, ''))
        result = self.run_cli('check', 'broken.md')
        self.assertEqual((result.returncode, result.stderr), (2, ''))
        self.assertIn('project privacy check could not run', result.stdout)
        self.assertCountEqual(self.root.rglob('*'), files)

    def test_bad_arguments_and_unreadable_text(self):
        (self.root / 'invalid.md').write_bytes(b'\xff')
        for args in (('check',), ('builder', 'extra'), ('check', '--root', '.'),
                     ('check', 'missing.md'), ('check', 'invalid.md'), ('check', '.')):
            with self.subTest(args=args):
                self.assertEqual(self.run_cli(*args).returncode, 2)


if __name__ == '__main__':
    unittest.main()
