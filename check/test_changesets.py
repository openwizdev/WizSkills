"""The changeset gate and the release dry-run (WS18, J205 and J206).

python3 -I check/test_changesets.py

Each test builds its own synthetic Git repository with a copy of
`check/changesets.py`, `.changeset/config.json` and a link to this tree's
pinned `node_modules` (run `npm ci` first), then runs the script there.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GIT_ENV = {'GIT_AUTHOR_NAME': 'Synthetic', 'GIT_AUTHOR_EMAIL': 'synthetic@example.invalid',
           'GIT_COMMITTER_NAME': 'Synthetic', 'GIT_COMMITTER_EMAIL': 'synthetic@example.invalid',
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull}


def skill_md(name, version='0.2.0', body='Body.'):
    head = f'---\nname: {name}\ndescription: Synthetic skill {name}.\n'
    if version is not None:
        head += f'version: {version}\n'
    return head + f'---\n\n# {name}\n\n{body}\n'


class Repo:
    def __init__(self, test, skills, plugin='0.1.2'):
        self.dir = Path(tempfile.mkdtemp(prefix='ws18-'))
        test.addCleanup(shutil.rmtree, self.dir, True)
        (self.dir / 'check').mkdir()
        shutil.copy(ROOT / 'check/changesets.py', self.dir / 'check/changesets.py')
        (self.dir / '.changeset').mkdir()
        shutil.copy(ROOT / '.changeset/config.json', self.dir / '.changeset/config.json')
        (self.dir / '.changeset/README.md').write_text('# Changesets\n')
        (self.dir / 'node_modules').symlink_to(ROOT / 'node_modules')
        (self.dir / '.gitignore').write_text('/node_modules\n')
        (self.dir / '.claude-plugin').mkdir()
        self.plugin(plugin, skills)
        (self.dir / 'CHANGELOG.md').write_text('# Changelog\n\n## 0.1.2 - 2026-01-01\n\n- Old line.\n')
        for name, version in skills.items():
            self.write(f'skills/{name}/SKILL.md', skill_md(name, version))
            self.write(f'skills/{name}/scripts/run.sh', 'echo synthetic\n')
        self.git('init', '-q', '-b', 'main')
        self.commit('base')
        self.git('tag', f'v{plugin}')

    def plugin(self, version, skills):
        data = {'name': 'openwiz', 'version': version,
                'skills': [f'./skills/{n}' for n in sorted(skills)]}
        (self.dir / '.claude-plugin/plugin.json').write_text(json.dumps(data, indent=2) + '\n')

    def write(self, rel, text):
        path = self.dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def remove(self, rel):
        shutil.rmtree(self.dir / rel)

    def note(self, slug, releases, summary='Synthetic change.'):
        lines = ['---', *(f'"{n}": {b}' for n, b in releases.items()), '---', '', summary, '']
        self.write(f'.changeset/{slug}.md', '\n'.join(lines))

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.dir, check=True, capture_output=True,
                              text=True, env={**os.environ, **GIT_ENV}).stdout

    def commit(self, message):
        self.git('add', '-A')
        self.git('commit', '-q', '--allow-empty', '-m', message)

    def branch(self):
        self.git('switch', '-q', '-c', 'topic')

    def run(self, *args):
        p = subprocess.run([sys.executable, '-I', 'check/changesets.py', *args], cwd=self.dir,
                           capture_output=True, text=True, env={**os.environ, **GIT_ENV})
        return p.returncode, p.stdout.splitlines()

    def snapshot(self):
        return {p.relative_to(self.dir).as_posix(): p.read_bytes()
                for p in sorted(self.dir.rglob('*'))
                if p.is_file() and '.git' not in p.parts and 'node_modules' not in p.parts}


class Gate(unittest.TestCase):
    """`check --base REF`: a pull request that changes a skill needs a changeset."""

    def pr(self, change, skills=None):
        repo = Repo(self, skills or {'alpha': '0.2.0', 'beta': '0.2.0'})
        repo.branch()
        change(repo)
        repo.commit('topic')
        return repo.run('check', '--base', 'main')

    def test_a_skill_change_without_a_changeset_fails(self):
        # catches: CI passing a skill-changing pull request that carries no changeset
        code, out = self.pr(lambda r: r.write('skills/alpha/scripts/run.sh', 'echo changed\n'))
        self.assertEqual((code, out), (1, [
            'changeset check: `alpha` changed but no new changeset names it: '
            'add one under .changeset/ (see .changeset/README.md)',
            'changeset check: fail']))

    def test_a_skill_change_with_its_changeset_passes(self):
        # catches: the gate refusing a correctly noted pull request
        def change(r):
            r.write('skills/alpha/SKILL.md', skill_md('alpha', body='Changed.'))
            r.note('alpha-fix', {'alpha': 'patch'})
        self.assertEqual(self.pr(change), (0, ['changeset check: pass (alpha)']))

    def test_every_changed_skill_needs_naming(self):
        # catches: one note for one skill letting a second changed skill go unbumped
        def change(r):
            r.write('skills/alpha/scripts/run.sh', 'echo changed\n')
            r.write('skills/beta/scripts/run.sh', 'echo changed\n')
            r.note('alpha-fix', {'alpha': 'patch'})
        code, out = self.pr(change)
        self.assertEqual((code, out), (1, [
            'changeset check: `beta` changed but no new changeset names it: '
            'add one under .changeset/ (see .changeset/README.md)',
            'changeset check: fail']))

    def test_an_existing_changeset_does_not_count(self):
        # catches: a note already pending on main satisfying a later pull request
        repo = Repo(self, {'alpha': '0.2.0'})
        repo.note('earlier', {'alpha': 'patch'})
        repo.commit('earlier pull request')
        repo.git('tag', 'base')
        repo.branch()
        repo.write('skills/alpha/scripts/run.sh', 'echo changed\n')
        repo.commit('topic')
        self.assertEqual(repo.run('check', '--base', 'base')[0], 1)

    def test_only_the_version_line_needs_no_changeset(self):
        # catches: the release pull request (and WS18's own) failing for its version lines
        def change(r):
            r.write('skills/alpha/SKILL.md', skill_md('alpha', '0.2.1'))
            r.write('skills/beta/SKILL.md', skill_md('beta', None))
        self.assertEqual(self.pr(change), (0, ['changeset check: pass (no skill changed)']))

    def test_a_non_skill_change_needs_no_changeset(self):
        # catches: the gate blocking docs or check-only pull requests
        self.assertEqual(self.pr(lambda r: r.write('README.md', 'Docs.\n')),
                         (0, ['changeset check: pass (no skill changed)']))

    def test_a_removed_skill_needs_a_bundle_note(self):
        # catches: a skill removed with no release note at all
        code, out = self.pr(lambda r: r.remove('skills/beta'))
        self.assertEqual((code, out), (1, [
            'changeset check: `beta` was removed but no new changeset names `wizskills`',
            'changeset check: fail']))

        def noted(r):
            r.remove('skills/beta')
            r.note('remove-beta', {'wizskills': 'minor'}, 'Removes beta.')
        self.assertEqual(self.pr(noted), (0, ['changeset check: pass (beta)']))

    def test_a_malformed_changeset_is_refused(self):
        # catches: a note Changesets cannot read (or that bumps nothing real) reaching main
        bad = {
            'unknown': ('---\n"gamma": patch\n---\n\nX.\n', '`gamma` is not a skill or `wizskills`'),
            'type': ('---\n"alpha": tiny\n---\n\nX.\n', 'a bump is patch, minor or major'),
            'twice': ('---\n"alpha": patch\n"alpha": minor\n---\n\nX.\n', 'names `alpha` twice'),
            'empty': ('---\n---\n\nX.\n', 'names no skill and no `wizskills`'),
            'summary': ('---\n"alpha": patch\n---\n\n', 'has no summary'),
            'shape': ('"alpha": patch\n\nX.\n',
                      'opens with `---`, one `"<skill>": patch|minor|major` line each, then `---` and a summary'),
        }
        for slug, (text, why) in bad.items():
            with self.subTest(slug=slug):
                def change(r):
                    r.write('skills/alpha/scripts/run.sh', 'echo changed\n')
                    r.note('alpha-fix', {'alpha': 'patch'})
                    r.write(f'.changeset/{slug}.md', text)
                code, out = self.pr(change)
                self.assertEqual((code, out), (1, [f'changeset check: .changeset/{slug}.md {why}',
                                                   'changeset check: fail']))


class Release(unittest.TestCase):
    """`release`: Changesets turns the pending notes into per-skill bumps and one bundle."""

    def release(self, repo, *args):
        repo.commit('pending')
        return repo.run('release', '--date', '2026-01-02', *args)

    def test_a_few_fixes_make_a_patch_bundle(self):
        # catches: wrong per-skill bumps or notes, or a dry run that writes files
        repo = Repo(self, {'alpha': '0.2.0', 'beta': '0.2.0', 'gamma': '0.2.0'})
        repo.note('one', {'alpha': 'patch', 'beta': 'patch'}, 'Fixes a typo.')
        repo.note('two', {'beta': 'patch'}, 'Fixes a link.')
        repo.commit('pending')
        before = repo.snapshot()
        self.assertEqual(repo.run('release', '--date', '2026-01-02'), (0, [
            'release: wizskills 0.1.2 -> 0.1.3 (patch)',
            'why: 2 skills changed, all patch',
            'skill alpha: 0.2.0 -> 0.2.1 (patch)',
            'skill beta: 0.2.0 -> 0.2.1 (patch)',
            'dry run: nothing written',
            '',
            '## 0.1.3 - 2026-01-02',
            '',
            '- `alpha` 0.2.1: Fixes a typo.',
            '- `beta` 0.2.1: Fixes a typo.',
            '- `beta` 0.2.1: Fixes a link.',
        ]))
        self.assertEqual(repo.snapshot(), before)

    def test_a_new_step_makes_a_minor_bundle(self):
        # catches: a skill's new ability shipping as a bundle patch
        repo = Repo(self, {'alpha': '0.2.0'})
        repo.note('step', {'alpha': 'minor'}, 'Adds a step.')
        code, out = self.release(repo)
        self.assertEqual((code, out[:3]), (0, ['release: wizskills 0.1.2 -> 0.2.0 (minor)',
                                               "why: a skill's minor bump",
                                               'skill alpha: 0.2.0 -> 0.3.0 (minor)']))

    def test_many_fixes_make_a_minor_bundle(self):
        # catches: many changed skills shipping as a bundle patch
        skills = {n: '0.2.0' for n in ('alpha', 'beta', 'delta', 'gamma')}
        repo = Repo(self, skills)
        repo.note('many', {n: 'patch' for n in skills}, 'Fixes wording.')
        code, out = self.release(repo)
        self.assertEqual((code, out[:2]), (0, ['release: wizskills 0.1.2 -> 0.2.0 (minor)',
                                               'why: 4 skills changed']))

    def test_an_added_or_removed_skill_makes_a_minor_bundle(self):
        # catches: a catalog change since the last release shipping as a bundle patch
        repo = Repo(self, {'alpha': '0.2.0', 'beta': '0.2.0'})
        repo.remove('skills/beta')
        repo.write('skills/omega/SKILL.md', skill_md('omega', '0.1.0'))
        repo.note('catalog', {'omega': 'patch', 'wizskills': 'patch'}, 'Swaps beta for omega.')
        code, out = self.release(repo)
        self.assertEqual((code, out), (0, [
            'release: wizskills 0.1.2 -> 0.2.0 (minor)',
            'why: skills added: omega; skills removed: beta',
            'skill omega: 0.1.0 -> 0.1.1 (patch)',
            'dry run: nothing written',
            '',
            '## 0.2.0 - 2026-01-02',
            '',
            '- Skills added: `omega`.',
            '- Skills removed: `beta`.',
            '- Swaps beta for omega.',
            '- `omega` 0.1.1: Swaps beta for omega.',
        ]))

    def test_a_breaking_change_makes_a_major_bundle(self):
        # catches: a records-format change or a rename shipping as a minor or patch bundle
        repo = Repo(self, {'alpha': '0.2.0', 'beta': '0.2.0'})
        repo.note('records', {'alpha': 'major'}, 'Changes the record format.')
        code, out = self.release(repo)
        self.assertEqual((code, out[:3]), (0, ['release: wizskills 0.1.2 -> 1.0.0 (major)',
                                               "why: a skill's major bump",
                                               'skill alpha: 0.2.0 -> 1.0.0 (major)']))
        repo = Repo(self, {'alpha': '0.2.0'})
        repo.note('rename', {'alpha': 'patch', 'wizskills': 'major'}, 'Renames a skill.')
        code, out = self.release(repo)
        self.assertEqual((code, out[:2]), (0, ['release: wizskills 0.1.2 -> 1.0.0 (major)',
                                               'why: `wizskills`: major in a changeset']))

    def test_nothing_pending_releases_nothing(self):
        # catches: an empty bundle being cut with no change in it
        repo = Repo(self, {'alpha': '0.2.0'})
        self.assertEqual(self.release(repo), (0, ['release: nothing pending']))

    def test_write_applies_the_plan(self):
        # catches: the written tree disagreeing with the dry run, or edits beyond the version line
        repo = Repo(self, {'alpha': '0.2.0', 'beta': '0.2.0'})
        repo.note('one', {'alpha': 'patch'}, 'Fixes a typo.')
        code, out = self.release(repo, '--write')
        self.assertEqual((code, out[-1:]),
                         (0, ['written: 1 skill, plugin.json, CHANGELOG.md; 1 changeset consumed']))
        self.assertEqual((repo.dir / 'skills/alpha/SKILL.md').read_text(), skill_md('alpha', '0.2.1'))
        self.assertEqual((repo.dir / 'skills/beta/SKILL.md').read_text(), skill_md('beta', '0.2.0'))
        plugin = json.loads((repo.dir / '.claude-plugin/plugin.json').read_text())
        self.assertEqual(plugin['version'], '0.1.3')
        self.assertEqual((repo.dir / 'CHANGELOG.md').read_text(),
                         '# Changelog\n\n## 0.1.3 - 2026-01-02\n\n- `alpha` 0.2.1: Fixes a typo.\n\n'
                         '## 0.1.2 - 2026-01-01\n\n- Old line.\n')
        self.assertEqual(sorted(p.name for p in (repo.dir / '.changeset').iterdir()),
                         ['README.md', 'config.json'])
        status = repo.git('status', '--porcelain').splitlines()
        self.assertEqual(sorted(status), [' D .changeset/one.md', ' M .claude-plugin/plugin.json',
                                          ' M CHANGELOG.md', ' M skills/alpha/SKILL.md'])


IGNORED_NAMES = ('.hidden-fix.md', 'Readme.md', 'AGENTS.md', 'CLAUDE.md', 'GEMINI.md')
IGNORED_WHY = 'is a name Changesets ignores: rename it (see .changeset/README.md)'


def note_text(releases, summary='Synthetic change.'):
    return '\n'.join(['---', *(f'"{n}": {b}' for n, b in releases.items()), '---', '', summary, ''])


class Inputs(unittest.TestCase):
    """#1501: the gate and the release select notes as the pinned Changesets reader does."""

    def test_the_gate_refuses_a_note_changesets_ignores(self):
        # catches: a note the reader skips passing the gate, so its skill's bump never ships
        for name in IGNORED_NAMES:
            with self.subTest(name=name):
                repo = Repo(self, {'alpha': '0.2.0', 'beta': '0.2.0'})
                repo.branch()
                repo.write('skills/alpha/scripts/run.sh', 'echo changed\n')
                repo.write('skills/beta/scripts/run.sh', 'echo changed\n')
                repo.write(f'.changeset/{name}', note_text({'alpha': 'patch'}))
                repo.note('normal-beta', {'beta': 'patch'})
                repo.commit('topic')
                self.assertEqual(repo.run('check', '--base', 'main'), (1, [
                    f'changeset check: .changeset/{name} {IGNORED_WHY}',
                    'changeset check: `alpha` changed but no new changeset names it: '
                    'add one under .changeset/ (see .changeset/README.md)',
                    'changeset check: fail']))

    def test_release_never_consumes_a_note_it_did_not_process(self):
        # catches: release --write deleting an ignored note whose bump and summary were never applied
        repo = Repo(self, {'alpha': '0.2.0', 'beta': '0.2.0'}, plugin='0.2.0')
        repo.write('.changeset/.hidden-fix.md', note_text({'alpha': 'patch'}, 'Fixes alpha.'))
        repo.note('normal-beta', {'beta': 'patch'}, 'Fixes beta.')
        repo.commit('pending')
        before = repo.snapshot()
        self.assertEqual(repo.run('release', '--date', '2026-01-02', '--write'),
                         (1, [f'release: .changeset/.hidden-fix.md {IGNORED_WHY}']))
        self.assertEqual(repo.snapshot(), before)


class FirstBundle(unittest.TestCase):
    """#1576: the first bundle is 0.2.0, cut once from the rewrite wave's notes."""

    def wave(self):
        repo = Repo(self, {'alpha': '0.2.0', 'beta': '0.2.0', 'gamma': '0.2.0', 'old': '0.2.0'})
        repo.remove('skills/old')
        repo.note('wave-alpha', {'alpha': 'major'}, 'Alpha is rewritten.')
        repo.note('wave-beta', {'beta': 'minor', 'gamma': 'patch'}, 'Beta and gamma are rewritten.')
        repo.note('wave-bundle', {'wizskills': 'minor'}, 'Removes old.')
        repo.commit('wave')
        return repo

    def test_the_ordinary_release_refuses_the_first_bundle(self):
        # catches: the documented dry run proposing bundle 1.0.0 and skills above 0.2.0 for the first bundle
        repo = self.wave()
        before = repo.snapshot()
        for args in ((), ('--write',)):
            with self.subTest(args=args):
                self.assertEqual(repo.run('release', '--date', '2026-01-02', *args), (1, [
                    'release: the first bundle is 0.2.0 with every skill at 0.2.0: run `release --first`']))
        self.assertEqual(repo.snapshot(), before)

    def test_the_first_bundle_cuts_every_skill_at_0_2_0(self):
        # catches: the wave's notes bumped again on top of the initialised versions, or their summaries lost
        repo = self.wave()
        section = ['## 0.2.0 - 2026-01-02', '',
                   '- Skills removed: `old`.',
                   '- Removes old.',
                   '- `alpha` 0.2.0: Alpha is rewritten.',
                   '- `beta` 0.2.0: Beta and gamma are rewritten.',
                   '- `gamma` 0.2.0: Beta and gamma are rewritten.']
        head = ['release: wizskills 0.1.2 -> 0.2.0 (first bundle)',
                'why: the first bundle, every skill at 0.2.0']
        self.assertEqual(repo.run('release', '--first', '--date', '2026-01-02'),
                         (0, [*head, 'dry run: nothing written', '', *section]))
        self.assertEqual(repo.run('release', '--first', '--date', '2026-01-02', '--write'), (0, [
            *head, '', *section, 'written: 0 skills, plugin.json, CHANGELOG.md; 3 changesets consumed']))
        for name in ('alpha', 'beta', 'gamma'):
            self.assertEqual((repo.dir / f'skills/{name}/SKILL.md').read_text(), skill_md(name, '0.2.0'))
        self.assertEqual(json.loads((repo.dir / '.claude-plugin/plugin.json').read_text())['version'], '0.2.0')
        self.assertEqual((repo.dir / 'CHANGELOG.md').read_text(), '# Changelog\n\n' + '\n'.join(section)
                         + '\n\n## 0.1.2 - 2026-01-01\n\n- Old line.\n')
        self.assertEqual(sorted(repo.git('status', '--porcelain').splitlines()), [
            ' D .changeset/wave-alpha.md', ' D .changeset/wave-beta.md', ' D .changeset/wave-bundle.md',
            ' M .claude-plugin/plugin.json', ' M CHANGELOG.md'])

    def test_the_first_bundle_is_cut_once_and_later_releases_bump(self):
        # catches: --first re-cutting 0.2.0 over a released bundle, or later releases losing J206's rules
        repo = self.wave()
        self.assertEqual(repo.run('release', '--first', '--date', '2026-01-02', '--write')[0], 0)
        repo.commit('release 0.2.0')
        repo.git('tag', 'v0.2.0')
        repo.note('later', {'alpha': 'major'}, 'Changes the record format.')
        repo.commit('later pull request')
        before = repo.snapshot()
        self.assertEqual(repo.run('release', '--first', '--date', '2026-01-03'),
                         (1, ['release: --first cuts the first bundle once; wizskills is already 0.2.0']))
        self.assertEqual(repo.snapshot(), before)
        code, out = repo.run('release', '--date', '2026-01-03')
        self.assertEqual((code, out[:3]), (0, ['release: wizskills 0.2.0 -> 1.0.0 (major)',
                                               "why: a skill's major bump",
                                               'skill alpha: 0.2.0 -> 1.0.0 (major)']))

    def test_the_first_bundle_refuses_a_skill_not_at_0_2_0(self):
        # catches: the first bundle shipping a skill whose version was never initialised to 0.2.0
        repo = Repo(self, {'alpha': '0.2.0', 'beta': '0.1.0'})
        repo.note('wave', {'alpha': 'minor'}, 'Alpha is rewritten.')
        repo.commit('wave')
        self.assertEqual(repo.run('release', '--first', '--date', '2026-01-02'),
                         (1, ['release: --first needs every skill at 0.2.0: `beta` is 0.1.0']))


class Removal(unittest.TestCase):
    """#1600: removing a skill keeps older pending notes valid; new notes stay strict."""

    def removal(self, extra=None):
        repo = Repo(self, {'alpha': '0.2.0', 'beta': '0.2.0'}, plugin='0.2.0')
        repo.note('earlier', {'alpha': 'minor', 'beta': 'patch'}, 'Alpha and beta learn a step.')
        repo.note('beta-fix', {'beta': 'patch'}, 'Beta gets a fix.')
        repo.commit('earlier pull requests')
        repo.branch()
        repo.remove('skills/beta')
        repo.note('remove-beta', {'wizskills': 'minor', **(extra or {})}, 'Removes beta.')
        repo.commit('topic')
        return repo

    def test_the_gate_passes_a_noted_removal_with_older_notes_naming_it(self):
        # catches: required CI refusing a correctly noted removal, now and on every later pull request
        repo = self.removal()
        self.assertEqual(repo.run('check', '--base', 'main'), (0, ['changeset check: pass (beta)']))
        repo.git('switch', '-q', 'main')
        repo.git('merge', '-q', '--ff-only', 'topic')
        repo.git('switch', '-q', '-c', 'later')
        repo.write('skills/alpha/scripts/run.sh', 'echo changed\n')
        repo.note('alpha-fix', {'alpha': 'patch'})
        repo.commit('later pull request')
        self.assertEqual(repo.run('check', '--base', 'main'), (0, ['changeset check: pass (alpha)']))

    def test_a_new_or_edited_note_naming_a_removed_skill_is_refused(self):
        # catches: the leniency for older notes letting a new or rewritten note bump a skill that is gone
        repo = self.removal({'beta': 'patch'})
        self.assertEqual(repo.run('check', '--base', 'main'), (1, [
            'changeset check: .changeset/remove-beta.md `beta` is not a skill or `wizskills`',
            'changeset check: fail']))
        repo = self.removal()
        repo.note('beta-fix', {'beta': 'minor'}, 'Beta gets a bigger fix.')
        repo.commit('edits an older note')
        self.assertEqual(repo.run('check', '--base', 'main'), (1, [
            'changeset check: .changeset/beta-fix.md `beta` is not a skill or `wizskills`',
            'changeset check: fail']))

    def test_release_keeps_older_notes_summaries_and_other_bumps(self):
        # catches: release refusing after a removal, or dropping alpha's bump or a removed skill's summary
        repo = self.removal()
        self.assertEqual(repo.run('release', '--date', '2026-01-02'), (0, [
            'release: wizskills 0.2.0 -> 0.3.0 (minor)',
            "why: `wizskills`: minor in a changeset; skills removed: beta; a skill's minor bump",
            'skill alpha: 0.2.0 -> 0.3.0 (minor)',
            'dry run: nothing written',
            '',
            '## 0.3.0 - 2026-01-02',
            '',
            '- Skills removed: `beta`.',
            '- Removes beta.',
            '- Beta gets a fix.',
            '- `alpha` 0.3.0: Alpha and beta learn a step.',
        ]))

    def test_release_refuses_a_note_naming_a_skill_that_never_was(self):
        # catches: the removed-skill leniency accepting any unknown name at release
        repo = self.removal()
        repo.note('typo', {'alpah': 'patch'}, 'Fixes a typo.')
        repo.commit('pending')
        self.assertEqual(repo.run('release', '--date', '2026-01-02'),
                         (1, ['release: .changeset/typo.md `alpah` is not a skill or `wizskills`']))


if __name__ == '__main__':
    unittest.main()
