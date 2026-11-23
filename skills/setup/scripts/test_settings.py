#!/usr/bin/env python3
"""settings.py check: the read-back setup's last step relies on (#1183).

Each case writes a synthetic docs/agents/ folder, runs the public command and
reads only its exit code and short result.
"""
import base64
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parent / 'settings.py'
SKILLS = Path(__file__).resolve().parents[2]


def reader(path):
    """A consumer of the settings, loaded from its own skill so this test reads its real rules."""
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def table(title, provider, model):
    return ('## %s\n\nOne line.\n\n| Setting | Value | `room-cli thread spawn` flag |\n| --- | --- | --- |\n'
            '| Harness | Synthetic | `--provider %s` |\n| Model | Synthetic | `--model %s` |\n'
            '| Effort | High | `--reasoning-level high` |\n\nSource: synthetic decision.\n\n' % (title, provider, model))


FLEET = ('# Fleet settings\n\nIntro.\n\n'
         + table('Builder', 'claude-code', 'syn-claude-1')
         + table('Builder for small tickets', 'codex', 'syn-codex-1')
         + table('Reviewer for Claude-built', 'codex', 'syn-codex-1')
         + table('Reviewer for GPT-built', 'claude-code', 'syn-claude-1')
         + '## Test commands\n\n| # | Folder | Command | CI check |\n| --- | --- | --- | --- |\n'
           '| 1 | root | `make test` | `build` |\n\nSource: synthetic workflow.\n\n'
           '## CI checks\n\n| Check | Runs | Required on |\n| --- | --- | --- |\n| `build` | 1 | `main` |\n\n'
           'Source: synthetic workflow.\n\n'
           '## Standing merge rules\n\nNone yet: every merge waits for the user.\n\nSource: synthetic.\n\n'
           '## GitHub identity\n\n| Setting | Value |\n| --- | --- |\n'
           '| Record authors | `synthetic-factory[bot]`, `synthetic-owner` |\n\nSource: synthetic.\n')

def models(*rows):
    return ('## Models\n\nOne line.\n\n| Role | Harness | Model | Effort | `room-cli thread spawn` flags |\n'
            '| --- | --- | --- | --- | --- |\n' + ''.join(row + '\n' for row in rows) + '\nSource: synthetic decision.\n\n')


def choice(role, provider, model, effort='medium'):
    return '| %s | Synthetic | Synthetic | Medium | `--provider %s --model %s --reasoning-level %s` |' % (
        role, provider, model, effort)


MODELS = models(choice('Orchestrator', 'claude-code', 'syn-claude-1'), choice('Builder', 'claude-code', 'syn-claude-1'),
                choice('Reviewer', 'codex', 'syn-codex-1'), '| Small builder | follows Builder | | | |',
                '| Fixer | follows Builder | | | |')
OLDER = FLEET[FLEET.index('## Builder\n'):FLEET.index('## Test commands')]
NEW = FLEET.replace(OLDER, MODELS)
TEMPLATE = Path(__file__).resolve().parents[1] / 'templates/fleet.md'
ROLES = ('needs-triage', 'needs-info', 'ready-for-agent', 'ready-for-human', 'wontfix')
LABELS = ('# Triage labels\n\n## Labels\n\n| Role | Label here | Meaning |\n| --- | --- | --- |\n'
          + ''.join('| `%s` | `%s` | Synthetic |\n' % (r, r) for r in ROLES))
FILES = {'fleet.md': FLEET, 'triage-labels.md': LABELS,
         'issue-tracker.md': '# Issue tracker: GitHub\n\nSynthetic.\n', 'domain.md': '# Domain docs\n\nSynthetic.\n'}
STARTING = "| Claude Code | harness | local | orchestrator, builder, reviewer, helper | syn-owner's App |"
ROSTER_HEADER = '| Name | Kind | Driver | Roles | Writes as |\n| --- | --- | --- | --- | --- |\n'


def roster(*rows, heading='## Roster'):
    return '%s\n\nWho may take which role.\n\n%s%s\n' % (heading, ROSTER_HEADER, ''.join(r + '\n' for r in rows))


def with_roster(section):
    return NEW.replace('## Test commands', section + '\n## Test commands')


DEFAULT_RULES = ('Ask before publishing a release, a tag or a package',
                 'Ask before spending money or credits beyond the recorded limits',
                 'Ask before adding, reading or changing a secret', 'Ask before deleting user data',
                 'Ask before a cut-over', 'Ask before installing the repository webhook')


def rules(*rows, heading='## Approval rules'):
    return '%s\n\nEach rule asks its approver.\n\n| Rule | Approver |\n| --- | --- |\n%s\nSource: synthetic.\n\n' % (
        heading, ''.join('| %s | %s |\n' % row for row in rows))


def with_rules(section):
    return NEW.replace('## Standing merge rules', section + '## Standing merge rules')


class Check(unittest.TestCase):

    def project(self, **changes):
        root = Path(tempfile.mkdtemp(prefix='setup-check-'))
        self.addCleanup(shutil.rmtree, root, True)
        (root / 'docs/agents').mkdir(parents=True)
        for name, text in dict(FILES, **changes).items():
            if text is not None:
                (root / 'docs/agents' / name).write_text(text)
        return root

    def check(self, root, *args):
        result = subprocess.run([sys.executable, '-I', str(SCRIPT), 'check', '--root', str(root), *args],
                                capture_output=True, text=True, timeout=60)
        return result.returncode, result.stdout

    def test_complete_settings_read_back_verified(self):
        # catches: a correct project refused, so no fleet can start after setup.
        code, out = self.check(self.project())
        self.assertEqual(code, 0, out)
        self.assertEqual(out.splitlines()[-1], 'Settings: verified (4 files).')

    def test_a_missing_setting_is_named_and_repair_reads_back(self):
        # catches: setup reporting done while a setting every fleet reads is gone
        # (the setup.repair case), or a repaired file still refused.
        broken = FLEET.replace('| Record authors | `synthetic-factory[bot]`, `synthetic-owner` |\n', '')
        root = self.project(**{'fleet.md': broken})
        code, out = self.check(root)
        self.assertEqual(code, 5, out)
        self.assertIn('fleet.md: GitHub identity: no Record authors row', out)
        (root / 'docs/agents/fleet.md').write_text(FLEET)
        self.assertEqual(self.check(root)[0], 0)

    def test_every_required_file_and_section_is_named_when_missing(self):
        # catches: a missing settings file or section passed over silently.
        code, out = self.check(self.project(**{'domain.md': None, 'fleet.md': FLEET.replace('## CI checks', '## Checks')}))
        self.assertEqual(code, 5, out)
        self.assertIn('domain.md: missing', out)
        self.assertIn('fleet.md: no ## CI checks section', out)

    def test_a_linked_settings_file_is_refused(self):
        # catches: a settings file read through a link to somewhere outside the project.
        root = self.project()
        outside = Path(tempfile.mkdtemp(prefix='setup-outside-'))
        self.addCleanup(shutil.rmtree, outside, True)
        (outside / 'fleet.md').write_text(FLEET)
        (root / 'docs/agents/fleet.md').unlink()
        os.symlink(outside / 'fleet.md', root / 'docs/agents/fleet.md')
        code, out = self.check(root)
        self.assertEqual(code, 5, out)
        self.assertIn('fleet.md: not a regular file', out)

    def test_a_reviewer_from_the_builders_family_is_refused(self):
        # catches: a same-family reviewer table, which breaks the builder-reviewer split.
        same = FLEET.replace(table('Reviewer for Claude-built', 'codex', 'syn-codex-1'),
                             table('Reviewer for Claude-built', 'claude-code', 'syn-claude-1'))
        code, out = self.check(self.project(**{'fleet.md': same}))
        self.assertEqual(code, 5, out)
        self.assertIn('fleet.md: Reviewer for Claude-built: claude-code is not from another model family', out)

    def test_an_unfilled_template_value_is_refused(self):
        # catches: a template placeholder shipped as a setting.
        placeholder = FLEET.replace('`--model syn-codex-1`', '`--model <id>`', 1)
        code, out = self.check(self.project(**{'fleet.md': placeholder}))
        self.assertEqual(code, 5, out)
        self.assertIn('fleet.md: Builder for small tickets: unfilled <id>', out)

    def test_each_triage_role_has_one_label_that_exists_once(self):
        # catches: a role with no label or two, and a label missing from (or
        # repeated in) the tracker, which leaves triage unable to sort.
        twice = LABELS + '| `needs-info` | `waiting` | Synthetic |\n'
        code, out = self.check(self.project(**{'triage-labels.md': twice}))
        self.assertEqual(code, 5, out)
        self.assertIn('triage-labels.md: needs-info: mapped 2 times', out)
        root = self.project()
        saved = root / 'labels.json'
        saved.write_text(json.dumps([{'name': n} for n in ROLES if n != 'wontfix'] + [{'name': 'needs-info'}]))
        code, out = self.check(root, '--labels', str(saved))
        self.assertEqual(code, 5, out)
        self.assertIn('triage-labels.md: wontfix: label wontfix is not in the tracker', out)
        self.assertIn('triage-labels.md: needs-info: label needs-info is in the tracker 2 times', out)

    def test_a_second_record_authors_row_is_refused_and_named(self):
        # catches: setup verifying a repair that left two Record authors rows,
        # which the review helper then refuses, so no review is admitted (#1500).
        row = '| Record authors | `synthetic-factory[bot]`, `synthetic-owner` |\n'
        old = '| Record authors | `synthetic-old` |\n'
        code, out = self.check(self.project(**{'fleet.md': FLEET.replace(row, row + old)}))
        self.assertEqual(code, 5, out)
        self.assertIn('fleet.md: GitHub identity: Record authors row 2 of 2: %s' % old.strip(), out)
        # A second GitHub identity section is read as the readers read it, not skipped.
        code, out = self.check(self.project(**{'fleet.md': FLEET + '\n## GitHub identity\n\n' + old}))
        self.assertEqual(code, 5, out)
        self.assertIn('Record authors row 2 of 2', out)

    def test_setup_checks_the_app_identity_row_is_exactly_on_or_off(self):
        row = '| Record authors | `synthetic-factory[bot]`, `synthetic-owner` |\n'
        for value in ('on', 'off', '`on`'):
            fleet = FLEET.replace(row, row + '| App identity | %s |\n' % value)
            code, out = self.check(self.project(**{'fleet.md': fleet}))
            self.assertEqual(code, 0, value + '\n' + out)
        for value in ('yes', 'On', '<on or off>', 'on | note'):
            fleet = FLEET.replace(row, row + '| App identity | %s |\n' % value)
            code, out = self.check(self.project(**{'fleet.md': fleet}))
            self.assertEqual(code, 5, value + '\n' + out)
            self.assertIn('fleet.md: GitHub identity: App identity must be exactly on or off', out)
        two = FLEET.replace(row, row + '| App identity | on |\n| App identity | off |\n')
        code, out = self.check(self.project(**{'fleet.md': two}))
        self.assertEqual(code, 5, out)
        self.assertIn('fleet.md: GitHub identity: App identity row 2 of 2: | App identity | off |', out)

    def test_a_record_authors_cell_is_validated_whole(self):
        # catches: a row the readers refuse whole (text beside the logins, an extra
        # cell) passed because each backticked login parsed on its own.
        row = '| Record authors | `synthetic-factory[bot]`, `synthetic-owner` |'
        for bad in (row.replace(', `synthetic-owner`', ' and `synthetic-owner`'), row + ' note |'):
            code, out = self.check(self.project(**{'fleet.md': FLEET.replace(row, bad)}))
            self.assertEqual(code, 5, bad + '\n' + out)
            self.assertIn('fleet.md: GitHub identity: Record authors needs one or more exact logins', out)

    def test_a_duplicate_or_malformed_spawn_flag_is_refused_and_named(self):
        # catches: setup verifying an agent table the first-fleet launch reader
        # refuses: a second --model left in a note, or a value that is not one token (#1520).
        for title, provider, model in (('Builder', 'claude-code', 'syn-claude-1'),
                                       ('Builder for small tickets', 'codex', 'syn-codex-1'),
                                       ('Reviewer for Claude-built', 'codex', 'syn-codex-1'),
                                       ('Reviewer for GPT-built', 'claude-code', 'syn-claude-1')):
            good = table(title, provider, model)
            noted = good.replace('Source: synthetic decision.', 'Was `--model syn-old`. Source: synthetic decision.')
            code, out = self.check(self.project(**{'fleet.md': FLEET.replace(good, noted)}))
            self.assertEqual(code, 5, out)
            self.assertIn('fleet.md: %s: --model appears 2 times' % title, out)
            split = good.replace('`--reasoning-level high`', '`--reasoning-level high extra`')
            code, out = self.check(self.project(**{'fleet.md': FLEET.replace(good, split)}))
            self.assertEqual(code, 5, out)
            self.assertIn('fleet.md: %s: malformed `--reasoning-level high extra`' % title, out)
        # A repeated section heading adds its flags to the same section, as launch reads it.
        extra = '## Builder\n\nOld: `--provider codex`.\n\n'
        code, out = self.check(self.project(**{'fleet.md': FLEET.replace('## Test commands', extra + '## Test commands')}))
        self.assertEqual(code, 5, out)
        self.assertIn('fleet.md: Builder: --provider appears 2 times', out)

    def test_each_fixer_row_carries_each_flag_once(self):
        # catches: a Fixer family row with a leftover second --model, or a
        # malformed flag, verified although the fresh round cannot pick one model (R1).
        fixer = ('## Fixer\n\nOne line.\n\n| Builder family | Harness | Model | Effort | `room-cli thread spawn` flags |\n'
                 '| --- | --- | --- | --- | --- |\n'
                 '| Claude | Claude Code | Syn | High | `--provider claude-code --model syn-claude-1 --reasoning-level high` |\n'
                 '| GPT | Codex | Syn | XHigh | `--provider codex --model syn-codex-1 --reasoning-level xhigh` |\n\n')
        valid = FLEET.replace('## Test commands', fixer + '## Test commands')
        code, out = self.check(self.project(**{'fleet.md': valid}))
        self.assertEqual(code, 0, out)
        twice = valid.replace('--model syn-claude-1 ', '--model syn-claude-1 --model syn-old ')
        code, out = self.check(self.project(**{'fleet.md': twice}))
        self.assertEqual(code, 5, out)
        self.assertIn('fleet.md: Fixer: Claude: --model appears 2 times', out)
        self.assertNotIn('Fixer: GPT', out)
        missing = valid.replace(' --reasoning-level xhigh', ' --reasoning-level')
        code, out = self.check(self.project(**{'fleet.md': missing}))
        self.assertEqual(code, 5, out)
        self.assertIn('fleet.md: Fixer: GPT: malformed --reasoning-level', out)

    def test_a_malformed_flag_is_counted_beside_an_old_note(self):
        # catches: a tab-separated new flag skipped, so an old well-formed flag
        # in a note is read as the only one and launch picks the old model (R2).
        good = table('Builder', 'claude-code', 'syn-claude-1')
        bad = good.replace('`--model syn-claude-1`', '`--model\tsyn-new`').replace(
            'Source: synthetic decision.', 'Was `--model syn-claude-1`. Source: synthetic decision.')
        code, out = self.check(self.project(**{'fleet.md': FLEET.replace(good, bad)}))
        self.assertEqual(code, 5, out)
        self.assertIn('fleet.md: Builder: --model appears 2 times', out)

    def test_the_identity_heading_is_read_exactly_as_review_reads_it(self):
        # catches: `##  GitHub identity` (an extra space) verified although the
        # review helper finds no record authors there and admits no review (R3).
        code, out = self.check(self.project(**{'fleet.md': FLEET.replace('## GitHub identity', '##  GitHub identity')}))
        self.assertEqual(code, 5, out)
        self.assertIn('fleet.md: no ## GitHub identity section', out)

    def test_setup_never_verifies_settings_the_readers_refuse(self):
        # catches: setup verifying a file the real review or launch reader then
        # refuses (#1500, #1520). Setup may be stricter: on a tab-separated flag
        # beside an old note, launch reads the old model, so setup refuses (R2).
        review = reader(SKILLS / 'review-ticket/scripts/review.py')
        launch = reader(SKILLS / 'install/scripts/first_fleet.py')
        row = '| Record authors | `synthetic-factory[bot]`, `synthetic-owner` |'
        builder = table('Builder', 'claude-code', 'syn-claude-1')
        cases = [FLEET]
        cases += [FLEET.replace(row, bad) for bad in (
            row + '\n| Record authors | `synthetic-old` |', row.replace('`, `', '` and `'), row + ' x |',
            row.replace('synthetic-owner', 'synthetic--owner'), '| Record authors | |')]
        cases += [FLEET.replace(builder, bad) for bad in (
            builder + 'Was `--model syn-old`.\n', builder.replace('`--provider claude-code`', '`--provider claude code`'),
            builder.replace('`--model syn-claude-1`', '`--model  syn-claude-1`'),
            builder.replace('`--model syn-claude-1`', '`--model\tsyn-new`') + 'Was `--model syn-claude-1`.\n')]
        cases.append(FLEET.replace('## GitHub identity', '##  GitHub identity'))
        for text in cases:
            try:
                review.record_authors(text)
                authors = True
            except review.Refusal:
                authors = False
            sections = {}
            for line in text.split('\n'):
                if line.startswith('## '):
                    name = line[3:].strip()
                    sections.setdefault(name, [])
                elif sections:
                    sections[name].append(line)
            tables = all(launch.agent(sections[t]) for t in ('Builder', 'Builder for small tickets',
                                                             'Reviewer for Claude-built', 'Reviewer for GPT-built'))
            code, out = self.check(self.project(**{'fleet.md': text}))
            self.assertTrue(code != 0 or (authors and tables), text + '\n' + out)

    def test_one_models_table_reads_back_verified(self):
        code, out = self.check(self.project(**{'fleet.md': NEW}))
        self.assertEqual(code, 0, out)
        self.assertEqual(out.splitlines()[-1], 'Settings: verified (4 files).')
        mixed = NEW.replace('| Small builder | follows Builder | | | |\n', '').replace(
            '| Fixer | follows Builder | | | |', choice('Fixer', 'codex', 'vendor/syn-codex-2'))
        code, out = self.check(self.project(**{'fleet.md': mixed}))
        self.assertEqual(code, 0, out)
        code, out = self.check(self.project(**{'fleet.md': FLEET.replace(OLDER, MODELS + OLDER)}))
        self.assertEqual(code, 0, out)

    def test_the_template_carries_the_one_models_table(self):
        template = TEMPLATE.read_text()
        for title in ('Builder', 'Builder for small tickets', 'Reviewer for Claude-built', 'Reviewer for GPT-built',
                      'Fixer'):
            self.assertNotIn('\n## %s\n' % title, template)
        self.assertEqual(template.count('\n## Models\n'), 1)
        code, out = self.check(self.project(**{'fleet.md': template}))
        self.assertEqual(code, 5, out)
        models = [line for line in out.splitlines() if 'Models' in line]
        self.assertEqual(models, ['fleet.md: Models: Orchestrator: unfilled', 'fleet.md: Models: Builder: unfilled',
                                  'fleet.md: Models: Reviewer: unfilled'], out)

    def test_a_broken_models_table_is_refused_by_name_never_read_past(self):
        follows = '| Small builder | follows Builder | | | |'
        builder = choice('Builder', 'claude-code', 'syn-claude-1')
        cases = {
            'header': (NEW.replace('| Effort |', '| Level |'), 'fleet.md: Models: the header is not the contract\'s'),
            'order': (NEW.replace(builder + '\n' + choice('Reviewer', 'codex', 'syn-codex-1'),
                                  choice('Reviewer', 'codex', 'syn-codex-1') + '\n' + builder),
                      'fleet.md: Models: rows not Orchestrator, Builder, Reviewer, then optional Small builder, Fixer'),
            'missing': (NEW.replace(builder + '\n', ''),
                        'fleet.md: Models: rows not Orchestrator, Builder, Reviewer, then optional Small builder, Fixer'),
            'follow cells': (NEW.replace(follows, '| Small builder | follows Builder | Opus | | |'),
                             'fleet.md: Models: Small builder: a following row has empty Model, Effort and flags'),
            'reviewer follows': (NEW.replace(choice('Reviewer', 'codex', 'syn-codex-1'),
                                             '| Reviewer | follows Builder | | | |'),
                                 'fleet.md: Models: Reviewer: only Small builder and Fixer may follow'),
            'flags': (NEW.replace(builder, builder.replace('--model syn-claude-1 ', '--model  syn-claude-1 ')),
                      'fleet.md: Models: Builder: the flags are not one exact `--provider --model --reasoning-level`'),
            'model id': (NEW.replace(builder, builder.replace('syn-claude-1', 'vendor//syn')),
                         'fleet.md: Models: Builder: the flags are not one exact `--provider --model --reasoning-level`'),
            'empty name': (NEW.replace(builder, builder.replace('| Synthetic | Synthetic |', '| | Synthetic |')),
                           'fleet.md: Models: Builder: Harness, Model and Effort need names'),
            'second heading': (NEW + '## Models\n\nOld.\n', 'fleet.md: Models: more than one ## Models heading'),
            'same family': (NEW.replace(choice('Reviewer', 'codex', 'syn-codex-1'),
                                        choice('Reviewer', 'claude-code', 'syn-claude-2')),
                            'fleet.md: Models: Reviewer: claude-code is not from another model family than the Builder'),
            'unknown family': (NEW.replace(choice('Reviewer', 'codex', 'syn-codex-1'),
                                           choice('Reviewer', 'syn-harness', 'syn-1')),
                               'fleet.md: Models: Reviewer: syn-harness has no known model family'),
        }
        for name, (text, line) in cases.items():
            with self.subTest(name):
                code, out = self.check(self.project(**{'fleet.md': text}))
                self.assertEqual(code, 5, out)
                self.assertIn(line, out.splitlines())
        broken = FLEET.replace(OLDER, cases['order'][0][cases['order'][0].index('## Models'):].split('## Test')[0] + OLDER)
        code, out = self.check(self.project(**{'fleet.md': broken}))
        self.assertEqual(code, 5, 'never falls back to the older tables past a broken Models table\n' + out)

    def test_the_launch_reads_every_models_table_setup_verifies(self):
        launch = reader(SKILLS / 'install/scripts/first_fleet.py')
        builder = choice('Builder', 'claude-code', 'syn-claude-1')
        reviewer = choice('Reviewer', 'codex', 'syn-codex-1')
        cases = [NEW, NEW.replace('| Fixer | follows Builder | | | |\n', ''),
                 NEW.replace(reviewer, choice('Reviewer', 'claude-code', 'syn-claude-2')),
                 NEW.replace(builder, builder.replace('syn-claude-1', 'vendor/syn')),
                 NEW.replace(builder, builder.replace('syn-claude-1', 'vendor//syn'))]
        for text in cases:
            code, out = self.check(self.project(**{'fleet.md': text}))
            if code == 0:
                rules = launch.settings_rules(text)
                self.assertTrue(rules['reviewer_claude'] and rules['orchestrator'], text)

    def test_a_fresh_setup_writes_the_starting_roster_and_its_check_passes_it(self):
        template = TEMPLATE.read_text()
        self.assertEqual(template.count('\n## Roster\n'), 1, 'the template writes one Roster')
        section = '## Roster\n' + template.split('\n## Roster\n', 1)[1].split('\n## ', 1)[0]
        rows = [line for line in section.splitlines() if line.startswith('|')]
        self.assertEqual(rows[:2], ROSTER_HEADER.splitlines())
        self.assertEqual(len(rows), 3, 'one starting row')
        code, out = self.check(self.project(**{'fleet.md': with_roster(section)}))
        self.assertEqual(code, 5, out)
        self.assertTrue(any(line.startswith('fleet.md: Roster refused: row 1') for line in out.splitlines()), out)
        for harness, driver, person in (('Claude Code', 'local', 'syn-owner'), ('Codex', 'cloudroom', 'syn-maker')):
            values = iter((harness, driver, person))
            filled = section.replace(rows[2], re.sub(r'<[^>]*>', lambda _: next(values), rows[2]))
            self.assertEqual(next(values, None), None, 'the row has three blanks: harness, driver, person')
            if person == 'syn-owner':
                self.assertIn('\n' + STARTING + '\n', filled)
            code, out = self.check(self.project(**{'fleet.md': with_roster(filled)}))
            self.assertEqual(code, 0, out)
        for text in (with_roster(roster("| Demo Bot | bot | demo-bot | orchestrator | syn-owner's App |",
                                        "| Claude Code | harness | cloudroom | builder, reviewer | syn-owner's App |",
                                        "| Own computer | host | local | helper,builder | syn-owner's App |")),
                     with_roster(roster("| Codex | harness | local | builder | syn-maker's App |",
                                        "| Helper Bot | bot | helper-bot | orchestrator, builder, reviewer, helper "
                                        "| syn-maker's App |")),
                     NEW):
            code, out = self.check(self.project(**{'fleet.md': text}))
            self.assertEqual(code, 0, out)

    def test_a_malformed_roster_or_unknown_role_is_refused_by_name(self):
        good = "| Claude Code | harness | local | builder | syn-owner's App |"
        cases = {
            'role': (roster(good, "| Demo Bot | bot | demo-bot | orchestrator, deployer | syn-owner's App |"),
                     'Roster refused: row 2 (Demo Bot): unknown role: deployer'),
            'repeated-role': (roster("| Demo Bot | bot | demo-bot | builder, reviewer, builder | syn-owner's App |"),
                              'Roster refused: row 1 (Demo Bot): role listed twice: builder'),
            'no-role': (roster("| Demo Bot | bot | demo-bot |  | syn-owner's App |"),
                        'Roster refused: row 1 (Demo Bot): no roles'),
            'cells': (roster(good, '| Codex | harness | local | reviewer |'),
                      'Roster refused: row 2 has 4 cells, not 5'),
            'name': (roster("| Demo/Bot | bot | demo-bot | orchestrator | syn-owner's App |"),
                     'Roster refused: row 1: bad name: Demo/Bot'),
            'duplicate-name': (roster("| Codex | harness | local | builder | syn-owner's App |",
                                      "| codex | harness | cloudroom | reviewer | syn-owner's App |"),
                               'Roster refused: row 2: codex is already an entry'),
            'kind': (roster("| Demo Bot | agent | demo-bot | orchestrator | syn-owner's App |"),
                     'Roster refused: row 1 (Demo Bot): unknown kind: agent'),
            'driver': (roster("| Demo Bot | bot | Demo_Bot | orchestrator | syn-owner's App |"),
                       'Roster refused: row 1 (Demo Bot): bad driver: Demo_Bot'),
            'writes-as': (roster(good, '| Demo Bot | bot | demo-bot | builder | its own account |'),
                          "Roster refused: row 2 (Demo Bot): writes as its own account, not <person>'s App"),
            'person': (roster(good, "| Demo Bot | bot | demo-bot | builder | syn-other's App |"),
                       "Roster refused: row 2 (Demo Bot): writes as syn-other's App, not syn-owner's App like row 1"),
            'label': (roster("| A long synthetic entry name | host | local | builder "
                             "| syn-owner-with-a-longer-login's App |"),
                      'Roster refused: row 1 (A long synthetic entry name): A long synthetic entry name via '
                      'syn-owner-with-a-longer-login is longer than 60 characters'),
            'header': (roster().replace('| Kind | Driver | Roles |', '| Kind | Roles | Driver |')
                       + "| Claude Code | harness | builder | local | syn-owner's App |\n",
                       'Roster refused: the header is not Name, Kind, Driver, Roles, Writes as'),
            'empty': (roster(), 'Roster refused: the table has no entries'),
            'no-table': ("## Roster\n\nEvery entry writes as syn-owner's App, but there is no table.\n\n## Loop\n\n"
                         + ROSTER_HEADER + good + '\n',
                         'Roster refused: the Roster section has no table'),
            'headings': (roster(good) + '\n' + roster(good), 'Roster refused: more than one ## Roster heading'),
            'heading-form': (roster(good, heading='## Roster ##'),
                             'Roster refused: the Roster heading must be exactly ## Roster: ## Roster ##'),
            'heading-form-underlined': (roster(good, heading='Roster\n------'),
                                        'Roster refused: the Roster heading must be exactly ## Roster: Roster'),
            'heading-form-level': (roster(good, heading='### roster'),
                                   'Roster refused: the Roster heading must be exactly ## Roster: ### roster'),
            'heading-form-indented': (roster(good, heading='  ## Roster'),
                                      'Roster refused: the Roster heading must be exactly ## Roster:   ## Roster'),
        }
        for name, (section, line) in cases.items():
            with self.subTest(name):
                code, out = self.check(self.project(**{'fleet.md': with_roster(section)}))
                self.assertEqual(code, 5, out)
                self.assertIn('fleet.md: ' + line, out.splitlines())
                self.assertEqual(sum('Roster' in got for got in out.splitlines()), 1, 'the first broken rule only')

    def test_approval_rules_are_optional_and_a_broken_row_is_refused_by_row(self):
        valid = [(rule, 'syn-owner') for rule in DEFAULT_RULES]
        for n, text in enumerate((NEW, FLEET, with_rules(rules(*valid)), NEW.replace('Intro.\n', 'Intro.\n\nApproval rules\n'))):
            with self.subTest(passes=n):
                code, out = self.check(self.project(**{'fleet.md': text}))
                self.assertEqual(code, 0, out)
        here = 'fleet.md: Approval rules: '
        cases = {
            'blank': ((DEFAULT_RULES[3], ' '), 'row 2 (%s): no approver' % DEFAULT_RULES[3]),
            'the user': ((DEFAULT_RULES[3], '`The User`'), 'row 2 (%s): the approver is "the user", not a person'
                         % DEFAULT_RULES[3]),
            'the user spaced': ((DEFAULT_RULES[3], '**The  User**'), 'row 2 (%s): the approver is "the user", not a person'
                                % DEFAULT_RULES[3]),
            'placeholder': ((DEFAULT_RULES[3], '<a name>'), 'row 2 (%s): unfilled approver <a name>' % DEFAULT_RULES[3]),
            'wording': (('Publish only with a yes', 'syn-owner'),
                        'row 2 (Publish only with a yes): the rule does not start "Ask before"'),
            'repeat': ((DEFAULT_RULES[0].replace('a tag', 'A  tag'), 'syn-other'),
                       'row 2 (%s): repeats row 1' % DEFAULT_RULES[0].replace('a tag', 'A  tag')),
        }
        for name, (row, line) in cases.items():
            with self.subTest(name):
                code, out = self.check(self.project(**{'fleet.md': with_rules(rules(valid[0], row))}))
                self.assertEqual(code, 5, out)
                self.assertIn(here + line, out.splitlines())
        for text, line in ((with_rules(rules(*valid) * 2), 'more than one ## Approval rules heading'),
                           (with_rules(rules(*valid).replace('| Approver |', '| Who |')),
                            'the table is not | Rule | Approver |'),
                           (with_rules(rules(valid[0], (DEFAULT_RULES[3], 'the user'), heading='### Approval Rules')),
                            'the heading must be exactly ## Approval rules: ### Approval Rules'),
                           (with_rules(rules(valid[0], (DEFAULT_RULES[3], 'the user'), heading='## Approval rules ##')),
                            'the heading must be exactly ## Approval rules: ## Approval rules ##'),
                           (with_rules(rules(valid[0], (DEFAULT_RULES[3], 'the user'), heading='Approval rules\n---')),
                            'the heading must be exactly ## Approval rules: Approval rules'),
                           (with_rules(rules(valid[0], (DEFAULT_RULES[3], 'the user')).replace('\n| Ask before d', '\n  | Ask before d')),
                            'row 2 (%s): the approver is "the user", not a person' % DEFAULT_RULES[3])):
            with self.subTest(line):
                code, out = self.check(self.project(**{'fleet.md': text}))
                self.assertEqual(code, 5, out)
                self.assertIn(here + line, out.splitlines())

    def test_an_indented_code_block_is_not_the_approval_rules_table(self):
        valid = rules(*[(rule, 'syn-owner') for rule in DEFAULT_RULES])
        table = re.compile(r'^(?=\|)', re.M)
        for name, indent in (('four spaces', '    '), ('tab', '\t'), ('space and tab', ' \t')):
            with self.subTest(name):
                code, out = self.check(self.project(**{'fleet.md': with_rules(table.sub(indent, valid))}))
                self.assertEqual(code, 5, out)
                self.assertIn('fleet.md: Approval rules: the table is not | Rule | Approver |', out.splitlines())
        with self.subTest('indented delimiter row'):
            code, out = self.check(self.project(**{'fleet.md': with_rules(valid.replace('\n| --- |', '\n    | --- |'))}))
            self.assertEqual(code, 5, out)
            self.assertIn('fleet.md: Approval rules: the table is not | Rule | Approver |', out.splitlines())
        for name, indent in (('one space', ' '), ('three spaces', '   ')):
            with self.subTest(name):
                code, out = self.check(self.project(**{'fleet.md': with_rules(table.sub(indent, valid))}))
                self.assertEqual(code, 0, out)

    def test_only_a_rendered_table_is_the_approval_rules(self):
        valid = rules(*[(rule, 'syn-owner') for rule in DEFAULT_RULES])
        here = 'fleet.md: Approval rules: '
        second = '| %s | syn-owner |' % DEFAULT_RULES[1]
        refused = {
            'second delimiter under an indented one': (valid.replace('| --- | --- |\n', '    | --- | --- |\n| --- | --- |\n'),
                                                       'a row indented as code ends the table: | --- | --- |'),
            'indented rule row': (valid.replace('\n' + second, '\n    ' + second),
                                  'a row indented as code ends the table: ' + second),
            'tab indented rule row': (valid.replace('\n' + second, '\n\t' + second),
                                      'a row indented as code ends the table: ' + second),
            'backtick fence': (valid.replace('| Rule |', '```\n| Rule |').replace('\nSource:', '```\nSource:'),
                               'the table is not | Rule | Approver |'),
            'tilde fence': (valid.replace('| Rule |', '~~~~ md\n| Rule |').replace('\nSource:', '~~~~\nSource:'),
                            'the table is not | Rule | Approver |'),
            'unclosed fence': (valid.replace('| Rule |', '```\n| Rule |'), 'the table is not | Rule | Approver |'),
        }
        for name, (text, line) in refused.items():
            with self.subTest(name):
                code, out = self.check(self.project(**{'fleet.md': with_rules(text)}))
                self.assertEqual(code, 5, out)
                self.assertIn(here + line, out.splitlines())
        example = '```\n| Rule | Approver |\n| --- | --- |\n| Ask before x | the user |\n```\n\n'
        passes = {
            'a fenced example before the table': valid.replace('| Rule |', example + '| Rule |', 1),
            'a fence closed by a longer one': valid.replace('| Rule |', example.replace('```\n\n', '````\n\n') + '| Rule |', 1),
            'three spaces on every row': re.sub(r'^(?=\|)', '   ', valid, flags=re.M),
        }
        for name, text in passes.items():
            with self.subTest(name):
                code, out = self.check(self.project(**{'fleet.md': with_rules(text)}))
                self.assertEqual(code, 0, out)

    def test_the_template_writes_the_six_default_rules_and_a_filled_copy_passes(self):
        template = TEMPLATE.read_text()
        self.assertEqual(template.count('\n## Approval rules\n'), 1)
        self.assertLess(template.index('\n## Approval rules\n'), template.index('\n## Standing merge rules\n'))
        section = '## Approval rules\n' + template.split('\n## Approval rules\n', 1)[1].split('\n## ', 1)[0] + '\n'
        rows = [line.strip('|').split('|') for line in section.splitlines() if line.startswith('|')][2:]
        self.assertEqual([rule.strip() for rule, _ in rows], list(DEFAULT_RULES))
        self.assertIn('\nSource: ', section)
        code, out = self.check(self.project(**{'fleet.md': with_rules(section)}))
        self.assertEqual(code, 5, out)
        self.assertEqual(sum('unfilled approver' in line for line in out.splitlines()), 6, out)
        code, out = self.check(self.project(**{'fleet.md': with_rules(re.sub(r'<[^>]*>', 'syn-owner', section))}))
        self.assertEqual(code, 0, out)

    def test_usage_errors_exit_2(self):
        # catches: a mistyped command read as a verified project.
        result = subprocess.run([sys.executable, '-I', str(SCRIPT), 'verify'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stdout.startswith('usage: settings.py check'), result.stdout)


ON, OFF = '| App identity | on |\n', '| App identity | off |\n'
TABLE = '| Setting | Value |\n| --- | --- |\n'
NOTE_288 = ("`App identity` stays `off`: nothing reads this row yet (OpenWiz #2394), so no value lets agents or "
            "`loop.sh` mint the App's token (`openwiz github token`).\n")


def identity(base, before='', row='', tail='', table=None, crlf=False):
    head, mark, rest = base.partition('\n## GitHub identity\n')
    end = rest.index('\n', rest.index('| Record authors |')) + 1
    rest = rest[:end] + row + rest[end:]
    if table is not None:
        rest = rest.replace(TABLE, table, 1)
    text = head + '\n' + before + mark[1:] + rest + tail
    return text.replace('\n', '\r\n') if crlf else text


def case(name, on, check, callers=True, **parts):
    return name, on, check, callers, parts


FENCE = '```md\n| Setting | Value |\n| --- | --- |\n| App identity | on |\n```\n'
APP_IDENTITY = (
    case('one canonical on row', True, True, row=ON),
    case('one canonical on row with CRLF line ends', True, True, callers=False, row=ON, crlf=True),
    case('no App identity row', False, True),
    case('the row off', False, True, row=OFF),
    case('the row a backticked off', False, True, row='| App identity | `off` |\n'),
    case('the row a backticked on', False, True, row='| App identity | `on` |\n'),
    case('the row ON', False, False, row='| App identity | ON |\n'),
    case('the row On', False, False, row='| App identity | On |\n'),
    case('the row yes', False, False, row='| App identity | yes |\n'),
    case('the row empty', False, False, row='| App identity |  |\n'),
    case('an on row with a third cell', False, False, row='| App identity | on | extra |\n'),
    case('an off row with a third cell', False, False, row='| App identity | off | extra |\n'),
    case('a backticked off row with a third cell', False, False, row='| App identity | `off` | extra |\n'),
    case('an on row with an escaped pipe', False, False, row='| App identity | on \\| off |\n'),
    case('an on row without its closing pipe', False, False, row='| App identity | on\n'),
    case('R6: an on row, then an off row indented one space', False, False, row=ON + ' ' + OFF),
    case('R6: an on row, then an off row indented by a tab', False, False, row=ON + '\t' + OFF),
    case('R6: an on row, then an off row indented four spaces', False, False, row=ON + '    ' + OFF),
    case('R6: an on row in a one-line comment', False, False, tail='\n<!-- | App identity | on | -->\n'),
    case('R6: an on row in a multi-line comment', False, False, tail='\n<!--\n| App identity | on |\n-->\n'),
    case('R6: an on row in a comment opened mid-line', False, False,
         tail='\nA synthetic note. <!-- hidden\n| App identity | on |\n-->\n'),
    case('an on row in a ``` fence', False, False, tail='\n' + FENCE),
    case('an on row in a ~~~ fence', False, False, tail='\n' + FENCE.replace('```', '~~~')),
    case('an on row in a fence indented two spaces', False, False,
         tail='\n' + ''.join('  ' + line + '\n' for line in FENCE.splitlines())),
    case('an on row in an unclosed fence', False, False, tail='\n' + FENCE[:-4]),
    case('an on row in another section', False, False, tail='\n## Elsewhere\n\n' + TABLE + ON),
    case('an on row after the table ends', False, False, tail='\n' + ON),
    case('an on row in a second table', False, False, tail='\n' + TABLE + ON),
    case('an on row under a second GitHub identity heading', False, False,
         tail='\n## GitHub identity\n\n' + TABLE + ON),
    case('an on row and another on row', False, False, row=ON + ON),
    case('an on row and an off row', False, False, row=ON + OFF),
    case('an off row and an on row', False, False, row=OFF + ON),
    case('an on row and an indented on row', False, False, row=ON + '  ' + ON),
    case('an indented on row and an off row', False, False, row='  ' + ON + OFF),
    case('an on row and a lower-case key off row', False, False, row=ON + '| app identity | off |\n'),
    case('an on row and an entity-encoded key off row', False, False, row=ON + '| App identit&#121; | off |\n'),
    case('an on row and a no-break-space key off row', False, False, row=ON + '| App&nbsp;identity | off |\n'),
    case('an on row and a marked-up key off row', False, False, row=ON + '| **App** identity | off |\n'),
    case('an on row and a lazy off row', False, False, row=ON + 'App identity | off |\n'),
    case('an on row and an inline-comment off row', False, False, row=ON + '<!-- | App identity | off | -->\n'),
    case('an on row and an off row a lone CR hides', False, False, callers=False, row=ON[:-1] + '\r' + OFF),
    case('an on row and a fenced example with its own heading and an off row', False, False, row=ON,
         tail='\n```md\n## Example\n\n' + OFF + '```\n'),
    case('an on row and a second GitHub identity heading with no row', False, False, row=ON,
         tail='\n## GitHub identity\n\nSynthetic.\n'),
    case('an on row and a ### GitHub identity lookalike', False, False, row=ON, tail='\n### GitHub identity\n\nSynthetic.\n'),
    case('an on row and a ## Github Identity lookalike', False, False, row=ON, tail='\n## Github Identity\n\nSynthetic.\n'),
    case('an on row and an underlined GitHub identity lookalike', False, False, row=ON,
         tail='\nGitHub identity\n---------------\n\nSynthetic.\n'),
    case('an on row in an upper-case PRE block', False, False, before='<PRE>\n\n', row=ON, tail='\n</PRE>\n'),
    case('an on row after a pre block with attributes', False, False, before='<pre class="synthetic">\n\n', row=ON,
         tail='\n</pre>\n'),
    case('an on row after a processing instruction', False, False, before='<?synthetic\n\n', row=ON, tail='\n?>\n'),
    case('an on row inside an open comment', False, False, before='<!--\n\n', row=ON, tail='\n-->\n'),
    case('an on row after a code span that opens a comment', False, False,
         before='Write `<!--` to hide synthetic text.\n\n', row=ON),
    case('an off row after a closed fence', False, True, before='```sh\necho synthetic\n```\n\n', row=OFF),
    case('an on row after a closed fence', True, True, before='```sh\necho synthetic\n```\n\n', row=ON),
    case('an on row after an unpaired fence', False, False, before='```sh\necho synthetic\n\n', row=ON),
    case('an on row after a fence closed by a shorter marker', False, False, before='````sh\nx\n```\n\n', row=ON),
    case('an on row after a fence closed by the other marker', False, False, before='```sh\nx\n~~~\n\n', row=ON),
    case('an on row after a fence whose closer has trailing text', False, False, before='```sh\nx\n``` x\n\n', row=ON),
    case('an on row after a fence with a four-space-indented closer inside', False, False,
         before='```sh\nx\n    ```\n```\n\n', row=ON),
    case('an on row after an indented fence', False, False, before='  ```sh\nx\n  ```\n\n', row=ON),
    case("an off row and #288's template note", False, True, row=OFF, tail='\n' + NOTE_288),
    case("an on row and #288's template note", True, True, row=ON, tail='\n' + NOTE_288),
    case('an on row and prose with a pipe in a code span', True, True, row=ON,
         tail='\nThe row reads like `App identity | example` in prose.\n'),
    case('an on row and a prose line opening with that code span', True, True, row=ON,
         tail='\n`App identity | example` is prose.\n'),
    case('an on row and an unsupported key', False, False, row=ON + '| Other | synthetic |\n'),
    case('an on row with a marked-up key', False, False, row='| **App identity** | on |\n'),
    case('an on row indented one space', False, False, row=' ' + ON),
    case('an on row with a blank line between header and delimiter', False, False, row=ON,
         table='| Setting | Value |\n\n| --- | --- |\n'),
    case('an on row under a |---|---| delimiter', False, False, row=ON, table='| Setting | Value |\n|---|---|\n'),
    case('an on row under an aligned delimiter', False, False, row=ON, table='| Setting | Value |\n| :-- | --- |\n'),
    case('an on row under a three-column delimiter', False, False, row=ON,
         table='| Setting | Value |\n| --- | --- | --- |\n'),
)


def contents(data, width=60, **changes):
    encoded = base64.b64encode(data).decode()
    lines = [encoded[n:n + width] for n in range(0, len(encoded), width)]
    answer = {'type': 'file', 'encoding': 'base64', 'size': len(data), 'name': 'fleet.md',
              'path': 'docs/agents/fleet.md', 'content': ''.join(line + '\n' for line in lines)}
    answer.update(changes)
    return json.dumps(answer).encode()


class AppIdentity(unittest.TestCase):
    project, check = Check.project, Check.check

    def reads(self, stdin, *args):
        result = subprocess.run([sys.executable, '-I', str(SCRIPT), 'app-identity', *args], input=stdin,
                                capture_output=True, timeout=60)
        return result.returncode

    def test_one_parse_decides_the_reader_and_check_on_every_fixture(self):
        module = reader(SCRIPT)
        for name, on, valid, _, parts in APP_IDENTITY:
            with self.subTest(name):
                text = identity(FLEET, **parts)
                self.assertEqual(module.app_identity_on(text), on, 'app_identity_on')
                root = self.project()
                (root / 'docs/agents/fleet.md').write_bytes(text.encode())
                code, out = self.check(root)
                self.assertEqual(code, 0 if valid else 5, out)
                named = [line for line in out.splitlines() if line.startswith('fleet.md: GitHub identity: App identity')]
                self.assertEqual(bool(named), not valid, out)
                self.assertEqual(self.reads(contents(text.encode())), 0 if on else 1, 'app-identity')

    def test_only_a_whole_successful_read_of_one_on_row_reads_on(self):
        data = identity(FLEET, row=ON).encode()
        whole = contents(data)
        self.assertEqual(self.reads(whole), 0)
        self.assertEqual(self.reads(whole.replace(b'\\n"', b'"')), 0)
        encoded = base64.b64encode(data).decode()
        broken = {
            'empty stdin': b'',
            'cut JSON': whole[:len(whole) // 2],
            'a JSON list': json.dumps([json.loads(whole)]).encode(),
            'not a file': contents(data, type='dir'),
            'encoding none': contents(data, encoding='none', content=''),
            'no content': json.dumps({k: v for k, v in json.loads(whole).items() if k != 'content'}).encode(),
            'a character outside base64': contents(data, content='*' + encoded[1:60] + '\n' + encoded[60:]),
            'a 59-character line': contents(data, width=59),
            'one unwrapped line': contents(data, width=len(encoded)),
            'a size one more': contents(data, size=len(data) + 1),
            'a size as text': contents(data, size=str(len(data))),
            'bytes that are not UTF-8': contents(data + b'\xff'),
        }
        for name, stdin in broken.items():
            with self.subTest(name):
                self.assertEqual(self.reads(stdin), 1)
        self.assertEqual(self.reads(whole, 'extra'), 2)


def export(base, folder):
    base = Path(base).read_text(encoding='utf-8')
    for number, (name, on, _, callers, parts) in enumerate(APP_IDENTITY, 1):
        if callers:
            (Path(folder) / ('%d.md' % number)).write_bytes(identity(base, **parts).encode())
            print('%d %s %s' % (number, 'on' if on else 'off', name))


if __name__ == '__main__':
    if sys.argv[1:2] == ['fixtures'] and len(sys.argv) == 4:
        export(*sys.argv[2:])
    else:
        unittest.main()
