import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('wizskills_select', HERE / 'select.py')
select = importlib.util.module_from_spec(spec)
spec.loader.exec_module(select)


def shard(name, skill):
    return {'name': name, 'skill': skill, 'commands': [], 'env': {}}


SHARDS = [shard('rules', None), shard('standalone', None), shard('alpha', 'alpha'),
          shard('beta', 'beta'), shard('fleet.1', 'fleet'), shard('fleet.2', 'fleet'),
          shard('fleet', 'fleet'), shard('gamma', 'gamma'), shard('delta', 'delta'),
          shard('check', 'check')]
EVERY = [s['name'] for s in SHARDS]
ALWAYS = ['rules', 'standalone']


def tree(tmp, files=None):
    root = Path(tmp)
    for name in ('alpha', 'beta', 'fleet', 'gamma', 'delta'):
        (root / 'skills' / name).mkdir(parents=True)
        (root / 'skills' / name / 'SKILL.md').write_text(f'# {name}\n', encoding='utf-8')
    (root / 'check').mkdir()
    (root / 'check' / 'test_check.py').write_text('# reads only check/\n', encoding='utf-8')
    for rel, text in (files or {}).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding='utf-8')
    return root


def picked(root, changed, event='pull_request'):
    return [s['name'] for s in select.select(root, SHARDS, changed, event)[0]]


class OneSkill(unittest.TestCase):
    def test_a_one_skill_change_selects_that_skills_shards_and_the_two_always(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tree(tmp)
            self.assertEqual(picked(root, ['skills/alpha/scripts/a.py']), [*ALWAYS, 'alpha'])
            self.assertEqual(picked(root, ['skills/alpha/SKILL.md', 'skills/alpha/test/test_a.py']),
                             [*ALWAYS, 'alpha'])

    def test_a_split_skill_selects_every_part_by_skill_never_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tree(tmp)
            self.assertEqual(picked(root, ['skills/fleet/scripts/test.sh']),
                             [*ALWAYS, 'fleet.1', 'fleet.2', 'fleet'])

    def test_two_skills_select_both_in_list_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tree(tmp)
            self.assertEqual(picked(root, ['skills/gamma/x.py', 'skills/alpha/x.py']),
                             [*ALWAYS, 'alpha', 'gamma'])

    def test_a_new_changeset_needs_no_shard_but_the_changeset_folder_itself_does(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tree(tmp)
            self.assertEqual(picked(root, ['skills/alpha/x.py', '.changeset/alpha-fix.md']),
                             [*ALWAYS, 'alpha'])
            for path in ('.changeset/README.md', '.changeset/config.json', '.changeset/sub/x.md',
                         '.changeset/readme.MD', '.changeset/notes.txt'):
                with self.subTest(path=path):
                    self.assertEqual(picked(root, ['skills/alpha/x.py', path]), EVERY)


class EveryShard(unittest.TestCase):
    def test_the_check_the_workflow_contracts_and_unplaceable_files_select_every_shard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tree(tmp)
            for path in ('check/run.py', 'check/select.py', '.github/workflows/ci.yml', 'contracts/x.v1.md',
                         'README.md', 'package.json', 'docs/agents/fleet.md', 'skills/README.md',
                         'skills/no-suites/SKILL.md', 'skills', 'skills/alpha', 'tools/x.py',
                         'skills/Alpha/x.py', 'skills/alpha\\x.py', '', 'skills//alpha/x.py',
                         'skills/./alpha/x.py', 'skills/../check/run.py', '/skills/alpha/x.py'):
                with self.subTest(path=path):
                    self.assertEqual(picked(root, ['skills/alpha/x.py', path]), EVERY)

    def test_no_changed_file_runs_every_shard(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(picked(tree(tmp), []), EVERY)

    def test_every_event_but_a_pull_request_runs_every_shard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tree(tmp)
            for event in ('merge_group', 'push', 'workflow_dispatch', 'pull_request_target', '',
                          'Pull_Request', 'pull_request '):
                with self.subTest(event=event):
                    self.assertEqual(picked(root, ['skills/alpha/x.py'], event), EVERY)


class CrossSkillReads(unittest.TestCase):

    def assertReads(self, files, reader='alpha', changed='skills/beta/scripts/b.py'):
        with tempfile.TemporaryDirectory() as tmp:
            root = tree(tmp, files)
            self.assertEqual(picked(root, [changed]),
                             [s['name'] for s in SHARDS if s['name'] in (*ALWAYS, reader, 'beta')]
                             if reader else [*ALWAYS, 'beta'])

    def test_each_form_of_path_to_another_skill_is_found(self):
        forms = {
            'repo path': "ROOT / 'skills/beta/SKILL.md'\n",
            'repo path, shell': 'cat "$ROOT/skills/beta/references/x.md"\n',
            'repo path, folder': 'shutil.copytree(ROOT / "skills/beta", dst)\n',
            'sibling, shell': 'cp "$HERE/../../beta/revision.sh" "$work/"\n',
            'sibling, folder': 'cp -R "$HERE/../../beta" "$rel/skills/"\n',
            'sibling, js': "import x from '../beta/lib.mjs';\n",
            'path join': "SKILLS = HERE.parent.parent\nB = SKILLS / 'beta' / 'x.py'\n",
            'path join, double quotes': 'skill = HELPER.parent.parent.parent / "beta"\n',
            'parents join': "B = Path(__file__).resolve().parents[2] / 'beta'\n",
            'join with a path': "SKILLS = HERE.parents[2]\nB = SKILLS / 'beta/scripts/b.py'\n",
            'a helper given the path': 'def section(path):\n    return (SKILLS / path).read_text()\n'
                                       'setup = section("beta/SKILL.md")\n',
            'os.path.join': "os.path.join(skills, 'beta', 'x.py')\n",
            'joinpath': "root.joinpath('skills', 'beta')\n",
        }
        for form, text in forms.items():
            with self.subTest(form=form):
                self.assertReads({'skills/alpha/test/test_a.py': text})

    def test_a_suite_that_lists_every_skill_reads_them_all(self):
        forms = {
            'iterdir': "for p in (ROOT / 'skills').iterdir():\n",
            'rglob': "files = (root / 'skills').rglob('*')\n",
            'glob': 'for p in sorted((ROOT / "skills").glob("*/SKILL.md")):\n',
            'shell glob': 'for f in "$ROOT"/skills/*/SKILL.md; do\n',
            'sibling glob': 'for f in "$HERE"/../../*/SKILL.md; do\n',
        }
        for form, text in forms.items():
            with self.subTest(form=form):
                self.assertReads({'skills/alpha/test/test_a.py': text}, changed='skills/beta/x.py')

    def test_reads_are_transitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tree(tmp, {'skills/alpha/test/test_a.py': "RUN = ROOT / 'skills/gamma/run.sh'\n",
                              'skills/gamma/run.sh': 'cat "$(dirname "$0")/../beta/x"\n'})
            self.assertEqual(picked(root, ['skills/beta/x.py']), [*ALWAYS, 'alpha', 'beta', 'gamma'])

    def test_a_skill_joined_by_name_from_a_list_is_found(self):
        forms = {
            'loop': 'for name in ("gamma", "beta"):\n    for p in (root / "skills" / name).rglob("*.md"):\n',
            'join': "for name in NAMES:\n    os.path.join(ROOT, 'skills', name)\nNAMES = ['beta']\n",
            'shell': 'for s in beta gamma; do cat "$ROOT/skills/$s/SKILL.md"; done\nX="beta"\n',
        }
        for form, text in forms.items():
            with self.subTest(form=form):
                self.assertReads({'skills/alpha/test/test_a.py': text})

    def test_a_reader_in_the_check_reads_the_skills(self):
        self.assertReads({'check/test_check.py': "for p in (ROOT / 'skills').iterdir():\n"},
                         reader='check', changed='skills/beta/x.py')

    def test_prose_and_unrelated_strings_are_not_reads(self):
        self.assertReads({'skills/alpha/SKILL.md': 'Run `../beta/scripts/b.py` and skills/beta.\n',
                          'skills/alpha/scripts/a.py': "ACTIONS = ('beta', 'install')\nlabel = 'beta'\n",
                          'skills/alpha/scripts/b.py': "skills/betamax and ../beta-two/x and 'beta-x'\n"},
                         reader=None)

    def test_a_longer_name_is_never_matched_by_its_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tree(tmp, {'skills/alpha/a.py': "ROOT / 'skills/beta/x'\n"})
            (root / 'skills/beta-two').mkdir()
            shards = [*SHARDS, shard('beta-two', 'beta-two')]
            got = [s['name'] for s in select.select(root, shards, ['skills/beta-two/x.py'],
                                                    'pull_request')[0]]
            self.assertEqual(got, [*ALWAYS, 'beta-two'])


class TheRealTree(unittest.TestCase):

    TRACED = {
        'triage': {'launch-fleet', 'to-tickets', 'wayfind'},
    }

    def test_every_traced_read_is_found(self):
        reads = select.reads(HERE.parent, json.loads(subprocess.run(
            [sys.executable, '-I', str(HERE / 'run.py'), '--list'], capture_output=True, text=True,
            check=True).stdout))
        for reader, read in self.TRACED.items():
            with self.subTest(reader=reader):
                self.assertLessEqual(read, reads.get(reader, set()))


class Command(unittest.TestCase):

    def run_select(self, root, *argv, shards=SHARDS):
        return subprocess.run([sys.executable, '-I', str(root / 'check' / 'select.py'), *argv],
                              input=json.dumps(shards), capture_output=True, text=True, cwd=root)

    def repo(self, tmp):
        root = tree(tmp)
        (root / 'check' / 'select.py').write_bytes((HERE / 'select.py').read_bytes())
        git = ['git', '-C', str(root), '-c', 'user.name=synthetic', '-c', 'user.email=synthetic@example.com']
        subprocess.run(['git', 'init', '-q', str(root)], check=True)
        subprocess.run([*git, 'add', '-A'], check=True)
        subprocess.run([*git, 'commit', '-qm', 'base'], check=True)
        return root, git

    def test_it_prints_the_selected_shards_and_names_each_skipped_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, git = self.repo(tmp)
            (root / 'skills/alpha/x.py').write_text('x = 1\n', encoding='utf-8')
            subprocess.run([*git, 'add', '-A'], check=True)
            subprocess.run([*git, 'commit', '-qm', 'head'], check=True)
            p = self.run_select(root, '--event', 'pull_request', '--base', 'HEAD^1')
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads(p.stdout), [s for s in SHARDS if s['name'] in (*ALWAYS, 'alpha')])
            self.assertEqual(p.stderr.splitlines(),
                             ['select: changed: skills/alpha/x.py',
                              *(f"select: {n}: {'run' if n in (*ALWAYS, 'alpha') else 'skipped'}" for n in EVERY)])

    def test_a_rename_selects_both_sides(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, git = self.repo(tmp)
            subprocess.run([*git, 'mv', 'skills/alpha/SKILL.md', 'skills/gamma/moved.md'], check=True)
            subprocess.run([*git, 'commit', '-qm', 'head'], check=True)
            p = self.run_select(root, '--event', 'pull_request', '--base', 'HEAD^1')
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual([s['name'] for s in json.loads(p.stdout)], [*ALWAYS, 'alpha', 'gamma'])

    def test_merge_group_and_push_print_every_shard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, git = self.repo(tmp)
            for event in ('merge_group', 'push'):
                with self.subTest(event=event):
                    p = self.run_select(root, '--event', event, '--base', 'HEAD')
                    self.assertEqual(p.returncode, 0, p.stderr)
                    self.assertEqual(json.loads(p.stdout), SHARDS)
                    self.assertEqual(p.stderr.splitlines(),
                                     [f'select: every shard: event {event}',
                                      *(f'select: {n}: run' for n in EVERY)])

    def test_a_base_git_cannot_read_fails_and_prints_no_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, git = self.repo(tmp)
            p = self.run_select(root, '--event', 'pull_request', '--base', 'no-such-rev')
            self.assertEqual((p.returncode, p.stdout), (1, ''))
            self.assertTrue(p.stderr.splitlines()[-1].startswith('select: cannot diff no-such-rev'),
                            p.stderr)

    def test_bad_arguments_and_bad_input_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, git = self.repo(tmp)
            for argv in ([], ['--event', 'pull_request'], ['--base', 'HEAD'],
                         ['--event', 'push', '--base', 'HEAD', '--more'], ['--base', '--event', 'push']):
                with self.subTest(argv=argv):
                    p = self.run_select(root, *argv)
                    self.assertEqual((p.returncode, p.stdout), (2, ''), p.stderr)
            for bad in ([], {}, [{'name': 'rules'}], [{**SHARDS[0], 'extra': 1}], 'x',
                        [SHARDS[0], SHARDS[0]], [{**SHARDS[2], 'skill': 7}]):
                with self.subTest(bad=bad):
                    p = self.run_select(root, '--event', 'push', '--base', 'HEAD', shards=bad)
                    self.assertEqual((p.returncode, p.stdout), (2, ''), p.stderr)


if __name__ == '__main__':
    unittest.main()
