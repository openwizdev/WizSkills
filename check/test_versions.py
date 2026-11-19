"""Every skill's SKILL.md front matter carries a valid semver `version:` (WS18, J205).

python3 -I check/test_versions.py
"""
import importlib.util
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('wizskills_run', HERE / 'run.py')
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


def findings(*lines, name='demo'):
    out = run.Findings()
    run.frontmatter(f'skills/{name}/SKILL.md', name, list(lines), out)
    return [message for _, _, _, message in out]


NAME = 'name: demo'
DESCRIPTION = 'description: A synthetic skill.'


class SkillVersion(unittest.TestCase):
    def test_a_valid_version_passes(self):
        # catches: the check refusing the `version:` key every skill now carries
        for version in ('0.2.0', '1.0.0', '0.2.0-rc.1', '2.10.3+build.7', '"0.2.0"'):
            with self.subTest(version=version):
                self.assertEqual(findings(NAME, DESCRIPTION, f'version: {version}'), [])

    def test_a_missing_version_is_refused(self):
        # catches: a skill shipping with no version, so a release cannot bump it
        self.assertEqual(findings(NAME, DESCRIPTION),
                         ['the frontmatter has no valid `version` (semver, such as `0.2.0`)'])

    def test_a_malformed_version_is_refused(self):
        # catches: a version Changesets cannot bump reaching main
        for version in ('v0.2.0', '0.2', '0.2.0.1', '01.2.0', '0.2.x', 'latest', '0.2.0-', '1.0.0+'):
            with self.subTest(version=version):
                self.assertEqual(findings(NAME, DESCRIPTION, f'version: {version}'),
                                 ['`version` is not a semver version such as `0.2.0`'])

    def test_a_repeated_version_is_refused(self):
        # catches: a second `version:` line silently replacing the first
        self.assertEqual(findings(NAME, DESCRIPTION, 'version: 0.2.0', 'version: 0.2.1'),
                         ['`version` appears twice'])


if __name__ == '__main__':
    unittest.main()
