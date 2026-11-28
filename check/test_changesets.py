import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
        shutil.copy(ROOT / 'check/run.py', self.dir / 'check/run.py')
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

    def pr(self, change, skills=None):
        repo = Repo(self, skills or {'alpha': '0.2.0', 'beta': '0.2.0'})
        repo.branch()
        change(repo)
        repo.commit('topic')
        return repo.run('check', '--base', 'main')

    def test_a_skill_change_without_a_changeset_fails(self):
        code, out = self.pr(lambda r: r.write('skills/alpha/scripts/run.sh', 'echo changed\n'))
        self.assertEqual((code, out), (1, [
            'changeset check: `alpha` changed but no new changeset names it: '
            'add one under .changeset/ (see .changeset/README.md)',
            'changeset check: fail']))

    def test_a_skill_change_with_its_changeset_passes(self):
        def change(r):
            r.write('skills/alpha/SKILL.md', skill_md('alpha', body='Changed.'))
            r.note('alpha-fix', {'alpha': 'patch'})
        self.assertEqual(self.pr(change), (0, ['changeset check: pass (alpha)']))

    def test_every_changed_skill_needs_naming(self):
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
        repo = Repo(self, {'alpha': '0.2.0'})
        repo.note('earlier', {'alpha': 'patch'})
        repo.commit('earlier pull request')
        repo.git('tag', 'base')
        repo.branch()
        repo.write('skills/alpha/scripts/run.sh', 'echo changed\n')
        repo.commit('topic')
        self.assertEqual(repo.run('check', '--base', 'base')[0], 1)

    def test_only_the_version_line_needs_no_changeset(self):
        def change(r):
            r.write('skills/alpha/SKILL.md', skill_md('alpha', '0.2.1'))
            r.write('skills/beta/SKILL.md', skill_md('beta', None))
        self.assertEqual(self.pr(change), (0, ['changeset check: pass (no skill changed)']))

    def test_a_mode_only_skill_md_edit_needs_a_changeset(self):
        def change(r):
            (r.dir / 'skills/alpha/SKILL.md').chmod(0o755)
        self.assertEqual(self.pr(change), (1, [
            'changeset check: `alpha` changed but no new changeset names it: '
            'add one under .changeset/ (see .changeset/README.md)',
            'changeset check: fail']))

        def noted(r):
            (r.dir / 'skills/alpha/SKILL.md').chmod(0o755)
            r.note('mode', {'alpha': 'patch'}, 'Marks the skill executable.')
        self.assertEqual(self.pr(noted), (0, ['changeset check: pass (alpha)']))

    def test_a_non_skill_change_needs_no_changeset(self):
        self.assertEqual(self.pr(lambda r: r.write('README.md', 'Docs.\n')),
                         (0, ['changeset check: pass (no skill changed)']))

    def test_a_removed_skill_needs_a_bundle_note(self):
        code, out = self.pr(lambda r: r.remove('skills/beta'))
        self.assertEqual((code, out), (1, [
            'changeset check: `beta` was removed but no new changeset names `wizskills`',
            'changeset check: fail']))

        def noted(r):
            r.remove('skills/beta')
            r.note('remove-beta', {'wizskills': 'minor'}, 'Removes beta.')
        self.assertEqual(self.pr(noted), (0, ['changeset check: pass (beta)']))

    def test_a_malformed_changeset_is_refused(self):
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

    def release(self, repo, *args):
        repo.commit('pending')
        return repo.run('release', '--date', '2026-01-02', *args)

    def test_a_few_fixes_make_a_patch_bundle(self):
        repo = Repo(self, {'alpha': '0.2.0', 'beta': '0.2.0', 'gamma': '0.2.0'}, plugin='0.2.0')
        repo.note('one', {'alpha': 'patch', 'beta': 'patch'}, 'Fixes a typo.')
        repo.note('two', {'beta': 'patch'}, 'Fixes a link.')
        repo.commit('pending')
        before = repo.snapshot()
        self.assertEqual(repo.run('release', '--date', '2026-01-02'), (0, [
            'release: wizskills 0.2.0 -> 0.2.1 (patch)',
            'why: 2 skills changed, all patch',
            'skill alpha: 0.2.0 -> 0.2.1 (patch)',
            'skill beta: 0.2.0 -> 0.2.1 (patch)',
            'dry run: nothing written',
            '',
            '## 0.2.1 - 2026-01-02',
            '',
            '- `alpha` 0.2.1, `beta` 0.2.1: Fixes a typo.',
            '- `beta` 0.2.1: Fixes a link.',
        ]))
        self.assertEqual(repo.snapshot(), before)

    def test_one_note_prints_its_summary_once_and_a_second_note_stays(self):
        repo = Repo(self, {'alpha': '0.2.0', 'beta': '0.2.0'}, plugin='0.2.0')
        repo.note('both', {'alpha': 'patch', 'beta': 'patch'}, 'Fixes a typo.')
        repo.note('again', {'beta': 'patch'}, 'Fixes a typo.')
        code, out = self.release(repo)
        self.assertEqual((code, out), (0, [
            'release: wizskills 0.2.0 -> 0.2.1 (patch)',
            'why: 2 skills changed, all patch',
            'skill alpha: 0.2.0 -> 0.2.1 (patch)',
            'skill beta: 0.2.0 -> 0.2.1 (patch)',
            'dry run: nothing written',
            '',
            '## 0.2.1 - 2026-01-02',
            '',
            '- `beta` 0.2.1: Fixes a typo.',
            '- `alpha` 0.2.1, `beta` 0.2.1: Fixes a typo.',
        ]))

    def test_a_new_step_makes_a_minor_bundle(self):
        repo = Repo(self, {'alpha': '0.2.0'}, plugin='0.2.0')
        repo.note('step', {'alpha': 'minor'}, 'Adds a step.')
        code, out = self.release(repo)
        self.assertEqual((code, out[:3]), (0, ['release: wizskills 0.2.0 -> 0.3.0 (minor)',
                                               "why: a skill's minor bump",
                                               'skill alpha: 0.2.0 -> 0.3.0 (minor)']))

    def test_many_fixes_make_a_minor_bundle(self):
        skills = {n: '0.2.0' for n in ('alpha', 'beta', 'delta', 'gamma')}
        repo = Repo(self, skills, plugin='0.2.0')
        repo.note('many', {n: 'patch' for n in skills}, 'Fixes wording.')
        code, out = self.release(repo)
        self.assertEqual((code, out[:2]), (0, ['release: wizskills 0.2.0 -> 0.3.0 (minor)',
                                               'why: 4 skills changed']))

    def test_an_added_or_removed_skill_makes_a_minor_bundle(self):
        repo = Repo(self, {'alpha': '0.2.0', 'beta': '0.2.0'}, plugin='0.2.0')
        repo.remove('skills/beta')
        repo.write('skills/omega/SKILL.md', skill_md('omega', '0.1.0'))
        repo.note('catalog', {'omega': 'patch', 'wizskills': 'patch'}, 'Swaps beta for omega.')
        code, out = self.release(repo)
        self.assertEqual((code, out), (0, [
            'release: wizskills 0.2.0 -> 0.3.0 (minor)',
            'why: skills added: omega; skills removed: beta',
            'skill omega: 0.1.0 -> 0.1.1 (patch)',
            'dry run: nothing written',
            '',
            '## 0.3.0 - 2026-01-02',
            '',
            '- Skills added: `omega`.',
            '- Skills removed: `beta`.',
            '- `omega` 0.1.1: Swaps beta for omega.',
        ]))

    def test_a_breaking_change_makes_a_major_bundle(self):
        repo = Repo(self, {'alpha': '0.2.0', 'beta': '0.2.0'}, plugin='0.2.0')
        repo.note('records', {'alpha': 'major'}, 'Changes the record format.')
        code, out = self.release(repo)
        self.assertEqual((code, out[:3]), (0, ['release: wizskills 0.2.0 -> 1.0.0 (major)',
                                               "why: a skill's major bump",
                                               'skill alpha: 0.2.0 -> 1.0.0 (major)']))
        repo = Repo(self, {'alpha': '0.2.0'}, plugin='0.2.0')
        repo.note('rename', {'alpha': 'patch', 'wizskills': 'major'}, 'Renames a skill.')
        code, out = self.release(repo)
        self.assertEqual((code, out[:2]), (0, ['release: wizskills 0.2.0 -> 1.0.0 (major)',
                                               'why: `wizskills`: major in a changeset']))

    def test_nothing_pending_releases_nothing(self):
        repo = Repo(self, {'alpha': '0.2.0'})
        self.assertEqual(self.release(repo), (0, ['release: nothing pending']))

    def test_write_applies_the_plan(self):
        repo = Repo(self, {'alpha': '0.2.0', 'beta': '0.2.0'}, plugin='0.2.0')
        repo.note('one', {'alpha': 'patch'}, 'Fixes a typo.')
        code, out = self.release(repo, '--write')
        self.assertEqual((code, out[-1:]),
                         (0, ['written: 1 skill, plugin.json, CHANGELOG.md; 1 changeset consumed']))
        self.assertEqual((repo.dir / 'skills/alpha/SKILL.md').read_text(), skill_md('alpha', '0.2.1'))
        self.assertEqual((repo.dir / 'skills/beta/SKILL.md').read_text(), skill_md('beta', '0.2.0'))
        plugin = json.loads((repo.dir / '.claude-plugin/plugin.json').read_text())
        self.assertEqual(plugin['version'], '0.2.1')
        self.assertEqual((repo.dir / 'CHANGELOG.md').read_text(),
                         '# Changelog\n\n## 0.2.1 - 2026-01-02\n\n- `alpha` 0.2.1: Fixes a typo.\n\n'
                         '## 0.1.2 - 2026-01-01\n\n- Old line.\n')
        self.assertEqual(sorted(p.name for p in (repo.dir / '.changeset').iterdir()),
                         ['README.md', 'config.json'])
        status = repo.git('status', '--porcelain').splitlines()
        self.assertEqual(sorted(status), [' D .changeset/one.md', ' M .claude-plugin/plugin.json',
                                          ' M CHANGELOG.md', ' M skills/alpha/SKILL.md'])

    def test_a_bad_marketplace_leaves_versions_and_notes_unchanged(self):
        for text in ('{}\n', '{"plugins":[]}\n', 'not json\n', '{"plugins":[1]}\n', '[]\n',
                     marketplace_json(source='./other'), marketplace_json(version='0.2.1')):
            with self.subTest(text=text):
                repo = Repo(self, {'alpha': '0.2.0'}, plugin='0.2.0')
                repo.note('one', {'alpha': 'patch'}, 'Fixes a typo.')
                repo.write('.claude-plugin/marketplace.json', text)
                repo.commit('pending')
                before = repo.snapshot()
                self.assertEqual(repo.run('release', '--date', '2026-01-02')[0], 0)
                code, _out = repo.run('release', '--date', '2026-01-02', '--write')
                self.assertNotEqual(code, 0)
                self.assertEqual(repo.snapshot(), before)

    def test_write_updates_a_recorded_marketplace_version(self):
        repo = Repo(self, {'alpha': '0.2.0'}, plugin='0.2.0')
        repo.write('.claude-plugin/marketplace.json', marketplace_json())
        repo.note('one', {'alpha': 'patch'}, 'Fixes a typo.')
        code, _out = self.release(repo, '--write')
        self.assertEqual(code, 0)
        market = json.loads((repo.dir / '.claude-plugin/marketplace.json').read_text())
        self.assertEqual(market['plugins'][0]['version'], '0.2.1')
        self.assertFalse((repo.dir / '.changeset/one.md').exists())

    def test_a_failed_write_restores_versions_and_notes(self):
        repo = Repo(self, {'alpha': '0.2.0'}, plugin='0.2.0')
        repo.note('one', {'alpha': 'patch'}, 'Fixes a typo.')
        repo.commit('pending')
        before = repo.snapshot()
        (repo.dir / 'CHANGELOG.md').chmod(0o444)
        code, _out = repo.run('release', '--date', '2026-01-02', '--write')
        self.assertNotEqual(code, 0)
        self.assertEqual(repo.snapshot(), before)

    def test_a_short_write_never_truncates_the_previous_changelog(self):
        repo = Repo(self, {'alpha': '0.2.0'}, plugin='0.2.0')
        repo.note('one', {'alpha': 'patch'})
        before = repo.snapshot()
        write_text, reached = Path.write_text, []

        def short_write(path, text, **kwargs):
            if path.name == 'CHANGELOG.md' and repo.dir in path.parents:
                write_text(path, text[:10], **kwargs)
                reached.append(path)
                raise OSError('synthetic short write')
            return write_text(path, text, **kwargs)

        with patch.object(Path, 'write_text', short_write):
            self.assertEqual(run_release_here(repo), 2)
        self.assertEqual(len(reached), 1)
        self.assertEqual(repo.snapshot(), before)

    def test_an_interrupt_restores_versions_and_consumed_notes_before_retry(self):
        for rel in ('.claude-plugin/plugin.json', '.changeset/one.md'):
            with self.subTest(interrupted=rel):
                repo = Repo(self, {'alpha': '0.2.0'}, plugin='0.2.0')
                repo.note('one', {'alpha': 'patch'})
                repo.note('two', {'alpha': 'patch'})
                before = repo.snapshot()
                target = repo.dir / rel
                write_text, replace, unlink = Path.write_text, os.replace, Path.unlink
                reached = []

                def interrupt(path):
                    if path == target and not reached:
                        reached.append(path)
                        raise KeyboardInterrupt

                def write_then_interrupt(path, *args, **kwargs):
                    written = write_text(path, *args, **kwargs)
                    interrupt(path)
                    return written

                def replace_then_interrupt(source, destination):
                    replace(source, destination)
                    interrupt(Path(destination))

                def unlink_then_interrupt(path, *args, **kwargs):
                    unlink(path, *args, **kwargs)
                    interrupt(path)

                with patch.object(Path, 'write_text', write_then_interrupt), \
                        patch.object(os, 'replace', replace_then_interrupt), \
                        patch.object(Path, 'unlink', unlink_then_interrupt):
                    try:
                        code = run_release_here(repo)
                    except KeyboardInterrupt:
                        code = 130
                self.assertNotEqual(code, 0)
                self.assertEqual(reached, [target])
                self.assertEqual(repo.snapshot(), before)
                self.assertEqual(self.release(repo, '--write')[0], 0)
                self.assertEqual((repo.dir / 'skills/alpha/SKILL.md').read_text(), skill_md('alpha', '0.2.1'))
                self.assertFalse((repo.dir / '.changeset/one.md').exists())
                self.assertFalse((repo.dir / '.changeset/two.md').exists())

    def test_a_retry_refuses_when_an_earlier_write_still_needs_recovery(self):
        repo = Repo(self, {'alpha': '0.2.0'}, plugin='0.2.0')
        repo.note('one', {'alpha': 'patch'})
        repo.write('.wizskills-release/before/skills/alpha/SKILL.md', skill_md('alpha', '0.2.0'))
        repo.write('.wizskills-release/applying', '')
        repo.write('skills/alpha/SKILL.md', skill_md('alpha', '0.2.1'))
        before = repo.snapshot()
        for args in ((), ('--write',)):
            with self.subTest(args=args):
                self.assertEqual(repo.run('release', '--date', '2026-01-02', *args)[0], 2)
                self.assertEqual(repo.snapshot(), before)

    def test_the_version_plan_does_not_read_generated_package_changelogs(self):
        repo = Repo(self, {'alpha': '0.2.0'}, plugin='0.2.0')
        repo.note('one', {'alpha': 'patch'})
        read_text = Path.read_text

        def read_without_generated_changelog(path, *args, **kwargs):
            if path.name == 'CHANGELOG.md' and any(p.startswith('wizskills-release-') for p in path.parts):
                raise AssertionError('the version plan read a generated package changelog')
            return read_text(path, *args, **kwargs)

        with patch.object(Path, 'read_text', read_without_generated_changelog):
            self.assertEqual(run_release_here(repo, write=False), 0)


def marketplace_json(**entry):
    return json.dumps({'name': 'wizskills', 'owner': {'name': 'Synthetic'},
                       'plugins': [dict({'name': 'openwiz', 'source': './', 'version': '0.2.0'}, **entry)]}) + '\n'


def run_release_here(repo, write=True):
    spec = importlib.util.spec_from_file_location('synthetic_changesets', repo.dir / 'check/changesets.py')
    changesets = importlib.util.module_from_spec(spec)
    with patch.object(sys, 'dont_write_bytecode', True):
        spec.loader.exec_module(changesets)
    argv = ['release', '--date', '2026-01-02']
    if write:
        argv.append('--write')
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return changesets.main(argv)


IGNORED_NAMES = ('.hidden-fix.md', 'Readme.md', 'AGENTS.md', 'CLAUDE.md', 'GEMINI.md')
IGNORED_WHY = 'is a name Changesets ignores: rename it (see .changeset/README.md)'


def note_text(releases, summary='Synthetic change.'):
    return '\n'.join(['---', *(f'"{n}": {b}' for n, b in releases.items()), '---', '', summary, ''])


class Inputs(unittest.TestCase):

    def test_the_gate_refuses_a_note_changesets_ignores(self):
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
        repo = Repo(self, {'alpha': '0.2.0', 'beta': '0.2.0'}, plugin='0.2.0')
        repo.write('.changeset/.hidden-fix.md', note_text({'alpha': 'patch'}, 'Fixes alpha.'))
        repo.note('normal-beta', {'beta': 'patch'}, 'Fixes beta.')
        repo.commit('pending')
        before = repo.snapshot()
        self.assertEqual(repo.run('release', '--date', '2026-01-02', '--write'),
                         (1, [f'release: .changeset/.hidden-fix.md {IGNORED_WHY}']))
        self.assertEqual(repo.snapshot(), before)


class FirstBundle(unittest.TestCase):

    def wave(self):
        repo = Repo(self, {'alpha': '0.2.0', 'beta': '0.2.0', 'gamma': '0.2.0', 'old': '0.2.0'})
        repo.remove('skills/old')
        repo.note('wave-alpha', {'alpha': 'major'}, 'Alpha is rewritten.')
        repo.note('wave-beta', {'beta': 'minor', 'gamma': 'patch'}, 'Beta and gamma are rewritten.')
        repo.note('wave-bundle', {'wizskills': 'minor'}, 'Removes old.')
        repo.commit('wave')
        return repo

    def test_the_ordinary_release_refuses_the_first_bundle(self):
        repo = self.wave()
        before = repo.snapshot()
        for args in ((), ('--write',)):
            with self.subTest(args=args):
                self.assertEqual(repo.run('release', '--date', '2026-01-02', *args), (1, [
                    'release: the first bundle is 0.2.0 with every skill at 0.2.0: run `release --first`']))
        self.assertEqual(repo.snapshot(), before)

    def test_the_first_bundle_cuts_every_skill_at_0_2_0(self):
        repo = self.wave()
        section = ['## 0.2.0 - 2026-01-02', '',
                   '- Skills removed: `old`.',
                   '- `alpha` 0.2.0: Alpha is rewritten.',
                   '- `beta` 0.2.0, `gamma` 0.2.0: Beta and gamma are rewritten.',
                   '- Removes old.']
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
        repo = Repo(self, {'alpha': '0.2.0', 'beta': '0.1.0'})
        repo.note('wave', {'alpha': 'minor'}, 'Alpha is rewritten.')
        repo.commit('wave')
        self.assertEqual(repo.run('release', '--first', '--date', '2026-01-02'),
                         (1, ['release: --first needs every skill at 0.2.0: `beta` is 0.1.0']))


class Removal(unittest.TestCase):

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
        repo = self.removal({'beta': 'patch'})
        self.assertEqual(repo.run('check', '--base', 'main'), (1, [
            'changeset check: .changeset/remove-beta.md `beta` is not a skill or `wizskills`',
            'changeset check: `beta` was removed but no new changeset names `wizskills`',
            'changeset check: fail']))
        repo = self.removal()
        repo.note('beta-fix', {'beta': 'minor'}, 'Beta gets a bigger fix.')
        repo.commit('edits an older note')
        self.assertEqual(repo.run('check', '--base', 'main'), (1, [
            'changeset check: .changeset/beta-fix.md `beta` is not a skill or `wizskills`',
            'changeset check: fail']))

    def test_release_keeps_older_notes_summaries_and_other_bumps(self):
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
            '- Beta gets a fix.',
            '- `alpha` 0.3.0: Alpha and beta learn a step.',
            '- Removes beta.',
        ]))

    def test_release_refuses_a_new_or_edited_note_naming_a_removed_skill(self):
        for case in ('new', 'edited', 'uncommitted'):
            with self.subTest(case=case):
                repo = self.removal()
                if case == 'new':
                    repo.note('later', {'alpha': 'patch', 'beta': 'patch'}, 'Alpha and beta change again.')
                    repo.commit('a later pull request')
                    name = 'later'
                else:
                    repo.note('beta-fix', {'beta': 'minor'}, 'Beta gets a bigger fix.')
                    if case == 'edited':
                        repo.commit('edits an older note')
                    name = 'beta-fix'
                before = repo.snapshot()
                self.assertEqual(repo.run('release', '--date', '2026-01-02', '--write'),
                                 (1, [f'release: .changeset/{name}.md `beta` is not a skill or `wizskills`']))
                self.assertEqual(repo.snapshot(), before)

    def test_release_refuses_a_note_naming_a_skill_that_never_was(self):
        repo = self.removal()
        repo.note('typo', {'alpah': 'patch'}, 'Fixes a typo.')
        repo.commit('pending')
        self.assertEqual(repo.run('release', '--date', '2026-01-02'),
                         (1, ['release: .changeset/typo.md `alpah` is not a skill or `wizskills`']))


class GrillRecords(unittest.TestCase):
    def test_the_grill_records_suite_runs_isolated(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('wizskills_run_grill', ROOT / 'check/run.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.SUITES['grill'][1],
                         ['python3', '-I', 'skills/grill/scripts/test_records.py'])


if __name__ == '__main__':
    unittest.main()
