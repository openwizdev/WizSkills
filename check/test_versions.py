import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('wizskills_run', HERE / 'run.py')
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)

DOC_VERSION = re.compile(
    r'(?<![0-9A-Za-z._-])v?('
    r'[0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+)*'
    r'(?:-[0-9A-Za-z-]*(?:\.[0-9A-Za-z-]+)*)?'
    r'(?:\+[0-9A-Za-z-]*(?:\.[0-9A-Za-z-]+)*)?'
    r')(?![0-9A-Za-z_+-]|\.[0-9A-Za-z])'
)
INSTALL_PINS = {
    'README.md': (
        'https://github.com/openwizdev/WizSkills.git#v{version}',
    ),
    'docs/install.md': (
        'https://github.com/openwizdev/WizSkills.git#v{version}',
        '--branch v{version}',
        'cat-file tag v{version}',
        'install.sh --version {version}',
    ),
}
HOST_SKILLS = ('.agents/skills', '.claude/skills')
TOOL_TESTS = (
    'tools/review-rounds/test_bench.py',
    'tools/comment-check/test_ci.py',
    'tools/comment-check/test_commands.py',
)


def findings(*lines, name='demo'):
    out = run.Findings()
    run.frontmatter(f'skills/{name}/SKILL.md', name, list(lines), out)
    return [message for _, _, _, message in out]


def doc_version_findings(root):
    out = run.Findings()
    data = run.json_object(root, run.PLUGIN, out)
    version = data.get('version') if isinstance(data, dict) else None
    if out or not (isinstance(version, str) and run.VERSION.fullmatch(version)):
        return [f'{run.PLUGIN}: missing or invalid version']
    found = []
    for rel, templates in INSTALL_PINS.items():
        text = run.read(root / rel)
        if text is None:
            found.append(f'{rel}: missing or unreadable')
            continue
        for match in DOC_VERSION.finditer(text):
            seen = match.group(1)
            if seen != version:
                found.append(f'{rel}: names version {seen}, expected {version}')
        for template in templates:
            pin = template.format(version=version)
            pattern = re.compile(re.escape(pin) + r'(?![0-9A-Za-z_+-]|\.[0-9A-Za-z])')
            if not pattern.search(text):
                found.append(f'{rel}: missing release pin `{pin}`')
    return found


def make_doc_tree(tmp, plugin_version='0.5.0', readme_version='0.5.0', install_version='0.5.0'):
    root = Path(tmp)
    (root / '.claude-plugin').mkdir(parents=True)
    (root / '.claude-plugin' / 'plugin.json').write_text(
        json.dumps({'name': 'openwiz', 'version': plugin_version}) + '\n',
        encoding='utf-8',
    )
    (root / 'README.md').write_text(
        f'## Install (Claude Code, release v{readme_version})\n\n'
        f'claude plugin marketplace add https://github.com/openwizdev/WizSkills.git#v{readme_version}\n',
        encoding='utf-8',
    )
    (root / 'docs').mkdir()
    (root / 'docs' / 'install.md').write_text(
        f'Every install below names release {install_version}.\n'
        f'claude plugin marketplace add https://github.com/openwizdev/WizSkills.git#v{install_version}\n'
        f'git clone --quiet --depth 1 --branch v{install_version} https://github.com/openwizdev/WizSkills.git wizskills-installer\n'
        f'git -C wizskills-installer cat-file tag v{install_version}\n'
        f'sh wizskills-installer/install.sh --version {install_version} --dest "$HOME/wizskills"\n',
        encoding='utf-8',
    )
    return root


def make_skill_tree(tmp):
    root = Path(tmp)
    (root / 'skills').mkdir()
    (root / 'skills' / 'README.md').write_text('# Skills\n', encoding='utf-8')
    skill = root / 'skills' / 'demo'
    (skill / 'agents').mkdir(parents=True)
    (skill / 'SKILL.md').write_text(
        '---\nname: demo\ndescription: A synthetic skill.\nversion: 0.2.0\n---\n\n'
        'Credit: adapted; see [NOTICE.md](NOTICE.md).\n',
        encoding='utf-8',
    )
    (skill / 'NOTICE.md').write_text(run.MATT_NOTICE + '\n', encoding='utf-8')
    (skill / 'agents' / 'openai.yaml').write_text(
        'interface:\n  display_name: "Demo"\n  short_description: "Synthetic demo."\n',
        encoding='utf-8',
    )
    (root / '.claude-plugin').mkdir()
    (root / '.claude-plugin' / 'plugin.json').write_text(
        json.dumps({
            'name': 'openwiz',
            'version': '0.5.0',
            'description': 'Synthetic skills.',
            'skills': ['./skills/demo'],
        }) + '\n',
        encoding='utf-8',
    )
    (root / '.claude-plugin' / 'marketplace.json').write_text(
        json.dumps({
            'name': 'wizskills',
            'owner': {'name': 'OpenWiz'},
            'plugins': [{'name': 'openwiz', 'source': './', 'description': 'Synthetic.'}],
        }) + '\n',
        encoding='utf-8',
    )
    for rel in HOST_SKILLS:
        host = root / rel
        host.mkdir(parents=True)
        (host / 'demo').symlink_to('../../skills/demo')
    return root


NAME = 'name: demo'
DESCRIPTION = 'description: A synthetic skill.'


class SkillVersion(unittest.TestCase):
    def test_description_length_boundary(self):
        self.assertEqual(findings(NAME, 'description: ' + 'x' * 180, 'version: 0.2.0'), [])
        self.assertEqual(findings(NAME, 'description: ' + 'x' * 181, 'version: 0.2.0'),
                         ['`description` is longer than 180 characters'])

    def test_a_valid_version_passes(self):
        for version in ('0.2.0', '1.0.0', '0.2.0-rc.1', '2.10.3+build.7', '"0.2.0"'):
            with self.subTest(version=version):
                self.assertEqual(findings(NAME, DESCRIPTION, f'version: {version}'), [])

    def test_a_missing_version_is_refused(self):
        self.assertEqual(findings(NAME, DESCRIPTION),
                         ['the frontmatter has no valid `version` (semver, such as `0.2.0`)'])

    def test_a_malformed_version_is_refused(self):
        for version in ('v0.2.0', '0.2', '0.2.0.1', '01.2.0', '0.2.x', 'latest', '0.2.0-', '1.0.0+'):
            with self.subTest(version=version):
                self.assertEqual(findings(NAME, DESCRIPTION, f'version: {version}'),
                                 ['`version` is not a semver version such as `0.2.0`'])

    def test_a_repeated_version_is_refused(self):
        self.assertEqual(findings(NAME, DESCRIPTION, 'version: 0.2.0', 'version: 0.2.1'),
                         ['`version` appears twice'])


class DocVersions(unittest.TestCase):
    def test_readme_and_install_guide_match_plugin_manifest(self):
        self.assertEqual(doc_version_findings(HERE.parent), [])

    def test_matching_docs_pass(self):
        for version in ('0.5.0', '1.2.3-rc.1'):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                root = make_doc_tree(tmp, version, version, version)
                self.assertEqual(doc_version_findings(root), [])

    def test_a_readme_version_that_differs_from_the_plugin_manifest_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_doc_tree(tmp, plugin_version='0.5.0', readme_version='0.4.2', install_version='0.5.0')
            self.assertEqual(
                doc_version_findings(root),
                [
                    'README.md: names version 0.4.2, expected 0.5.0',
                    'README.md: names version 0.4.2, expected 0.5.0',
                    'README.md: missing release pin `https://github.com/openwizdev/WizSkills.git#v0.5.0`',
                ],
            )
        with tempfile.TemporaryDirectory() as tmp:
            root = make_doc_tree(tmp, plugin_version='0.5.0', readme_version='0.5.0', install_version='0.5.0')
            readme = root / 'README.md'
            readme.write_text(
                readme.read_text(encoding='utf-8').replace('release v0.5.0', 'release v0.4.2'),
                encoding='utf-8',
            )
            self.assertEqual(
                doc_version_findings(root),
                ['README.md: names version 0.4.2, expected 0.5.0'],
            )
        with tempfile.TemporaryDirectory() as tmp:
            root = make_doc_tree(tmp, plugin_version='0.5.0', readme_version='0.5.0.1', install_version='0.5.0')
            self.assertEqual(
                doc_version_findings(root),
                [
                    'README.md: names version 0.5.0.1, expected 0.5.0',
                    'README.md: names version 0.5.0.1, expected 0.5.0',
                    'README.md: missing release pin `https://github.com/openwizdev/WizSkills.git#v0.5.0`',
                ],
            )

    def test_an_install_guide_version_that_differs_from_the_plugin_manifest_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_doc_tree(tmp, plugin_version='0.5.0', readme_version='0.5.0', install_version='0.5.0')
            install = root / 'docs' / 'install.md'
            install.write_text(
                install.read_text(encoding='utf-8').replace('--version 0.5.0', '--version 0.4.2'),
                encoding='utf-8',
            )
            self.assertEqual(
                doc_version_findings(root),
                [
                    'docs/install.md: names version 0.4.2, expected 0.5.0',
                    'docs/install.md: missing release pin `install.sh --version 0.5.0`',
                ],
            )

    def test_missing_release_pin_or_unreadable_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_doc_tree(tmp)
            (root / 'README.md').write_text('# WizSkills\n', encoding='utf-8')
            self.assertEqual(
                doc_version_findings(root),
                ['README.md: missing release pin `https://github.com/openwizdev/WizSkills.git#v0.5.0`'],
            )
        with tempfile.TemporaryDirectory() as tmp:
            root = make_doc_tree(tmp)
            (root / 'README.md').unlink()
            self.assertEqual(doc_version_findings(root), ['README.md: missing or unreadable'])
        with tempfile.TemporaryDirectory() as tmp:
            root = make_doc_tree(tmp)
            (root / '.claude-plugin' / 'plugin.json').unlink()
            self.assertEqual(doc_version_findings(root), ['.claude-plugin/plugin.json: missing or invalid version'])


class ToolInventory(unittest.TestCase):
    def test_tool_tests_are_listed_in_suites(self):
        listed = {command[-1] for commands in run.SUITES.values() for command in commands}
        for rel in TOOL_TESTS:
            with self.subTest(rel=rel):
                self.assertIn(rel, listed)
        self.assertEqual(run.unlisted_tests(HERE.parent), [])

    def test_an_unlisted_tool_test_fails_the_inventory_and_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'skills').mkdir()
            (root / 'check').mkdir()
            tool = root / 'tools' / 'demo'
            (tool / 'fixtures').mkdir(parents=True)
            (tool / 'helper.py').write_text('x = 1\n', encoding='utf-8')
            (tool / 'fixtures' / 'test_fixture.py').write_text('', encoding='utf-8')
            (tool / 'test_unlisted.py').write_text('', encoding='utf-8')
            (tool / 'test_shell.sh').write_text('', encoding='utf-8')
            (tool / 'extra.test.mjs').write_text('', encoding='utf-8')
            expected = [
                'tools/demo/extra.test.mjs',
                'tools/demo/test_shell.sh',
                'tools/demo/test_unlisted.py',
            ]
            saved_root, saved_suites = run.ROOT, run.SUITES
            run.ROOT, run.SUITES = root, {}
            try:
                self.assertEqual(run.unlisted_tests(root), expected)
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    ok = run.suites(root)
                self.assertFalse(ok)
                for rel in expected:
                    self.assertIn(f'suite inventory: {rel}: unlisted', out.getvalue())
                list_out, list_err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(list_out), contextlib.redirect_stderr(list_err):
                    code = run.main(['--list'])
                self.assertEqual((code, list_out.getvalue()), (1, ''))
                self.assertEqual(
                    list_err.getvalue().splitlines(),
                    [f'suite inventory: {rel}: unlisted' for rel in expected],
                )
            finally:
                run.ROOT, run.SUITES = saved_root, saved_suites

    def test_a_listed_tool_test_passes_the_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'skills').mkdir()
            (root / 'check').mkdir()
            (root / 'tools' / 'demo').mkdir(parents=True)
            (root / 'tools' / 'demo' / 'test_listed.py').write_text('', encoding='utf-8')
            saved_suites = run.SUITES
            run.SUITES = {'tools': [['python3', '-I', 'tools/demo/test_listed.py']]}
            try:
                self.assertEqual(run.unlisted_tests(root), [])
            finally:
                run.SUITES = saved_suites


class HostSkillLinks(unittest.TestCase):
    def test_both_agent_hosts_list_every_skill(self):
        carried = sorted(
            entry.name for entry in (HERE.parent / 'skills').iterdir()
            if entry.is_dir() and not entry.is_symlink() and (entry / 'SKILL.md').is_file()
        )
        for rel in HOST_SKILLS:
            host = HERE.parent / rel
            with self.subTest(host=rel):
                self.assertTrue(host.is_dir() and not host.is_symlink())
                entries = sorted(entry.name for entry in host.iterdir())
                self.assertEqual(entries, carried)
                for name in carried:
                    link = host / name
                    self.assertTrue(link.is_symlink(), f'{rel}/{name} must be a symlink')
                    self.assertEqual(os.readlink(link), f'../../skills/{name}')
        self.assertEqual(run.rules(HERE.parent), [])

    def test_host_skill_link_parity_refuses_missing_extra_wrong_and_non_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_skill_tree(tmp)
            self.assertEqual(run.rules(root), [])
        for rel in HOST_SKILLS:
            with self.subTest(host=rel, case='missing'), tempfile.TemporaryDirectory() as tmp:
                root = make_skill_tree(tmp)
                (root / rel / 'demo').unlink()
                self.assertEqual(
                    run.rules(root),
                    [('links', f'{rel}/demo', None, 'missing symlink to `../../skills/demo`')],
                )
            with self.subTest(host=rel, case='extra'), tempfile.TemporaryDirectory() as tmp:
                root = make_skill_tree(tmp)
                (root / rel / 'stale').symlink_to('../../skills/demo')
                self.assertEqual(
                    run.rules(root),
                    [('links', f'{rel}/stale', None, '`stale` is not a carried skill folder')],
                )
            with self.subTest(host=rel, case='wrong-target'), tempfile.TemporaryDirectory() as tmp:
                root = make_skill_tree(tmp)
                (root / rel / 'demo').unlink()
                (root / rel / 'demo').symlink_to('../../skills/other')
                self.assertEqual(
                    run.rules(root),
                    [('links', f'{rel}/demo', None, 'symlink must point to `../../skills/demo`')],
                )
            with self.subTest(host=rel, case='not-a-symlink'), tempfile.TemporaryDirectory() as tmp:
                root = make_skill_tree(tmp)
                (root / rel / 'demo').unlink()
                (root / rel / 'demo').mkdir()
                self.assertEqual(
                    run.rules(root),
                    [('links', f'{rel}/demo', None, 'symlink must point to `../../skills/demo`')],
                )
            with self.subTest(host=rel, case='missing-folder'), tempfile.TemporaryDirectory() as tmp:
                root = make_skill_tree(tmp)
                shutil.rmtree(root / rel)
                self.assertEqual(
                    run.rules(root),
                    [('links', rel, None, 'the host skills folder is missing')],
                )
            with self.subTest(host=rel, case='symlinked-folder'), tempfile.TemporaryDirectory() as tmp:
                root = make_skill_tree(tmp)
                real = root / 'other-host'
                shutil.move(str(root / rel), str(real))
                (root / rel).symlink_to(real)
                self.assertEqual(
                    run.rules(root),
                    [('links', rel, None, 'the host skills folder is missing')],
                )
            with self.subTest(host=rel, case='symlinked-parent'), tempfile.TemporaryDirectory() as tmp:
                root = make_skill_tree(tmp)
                parent = (root / rel).parent
                real = root / 'other-parent'
                shutil.move(str(parent), str(real))
                parent.symlink_to(real)
                self.assertEqual(
                    run.rules(root),
                    [('links', rel, None, 'the host skills folder is missing')],
                )


class ReviewTicketNoticePointer(unittest.TestCase):
    def test_notices_points_to_notice_md_for_matt_pocock(self):
        notices = (HERE.parent / 'skills/review-ticket/NOTICES.md').read_text(encoding='utf-8')
        self.assertIn("Matt Pocock's notice is in [NOTICE.md](NOTICE.md).", notices)
        self.assertNotIn('[SKILL.md](SKILL.md)', notices)
        notice = (HERE.parent / 'skills/review-ticket/NOTICE.md').read_text(encoding='utf-8')
        self.assertIn(run.MATT_NOTICE, ' '.join(notice.split()))


if __name__ == '__main__':
    unittest.main()
