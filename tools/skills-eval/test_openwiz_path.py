#!/usr/bin/env python3
"""The OpenWiz loads (#1487): only from OPENWIZ_CHECKOUT, refused clearly without it.

In WizSkills, skills-eval reads OpenWiz's collector contract and two of its
fixtures from an OpenWiz checkout at a pinned commit, passed in by the
OPENWIZ_CHECKOUT environment variable, never from a sibling folder. Free and
offline: it runs the two loaders as subprocesses in a throwaway copy.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
CONTRACT = 'tools/collector/experiment_contract.py'
# The two entry points that load OpenWiz: the precheck suite and the weekly loop.
LOADERS = ('precheck/test_contract.py', 'weekly/run.py')


class OpenWizPath(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        # The copy sits where the old sibling path would find a collector: a
        # loader that still looked there would import this planted module.
        shutil.copytree(HERE, self.root / 'tools/skills-eval',
                        ignore=shutil.ignore_patterns('__pycache__'))
        planted = self.root / CONTRACT
        planted.parent.mkdir(parents=True)
        planted.write_text("raise SystemExit('planted sibling collector loaded')\n")

    def run_loader(self, rel, checkout):
        env = {k: v for k, v in os.environ.items() if k != 'OPENWIZ_CHECKOUT'}
        if checkout is not None:
            env['OPENWIZ_CHECKOUT'] = str(checkout)
        return subprocess.run([sys.executable, '-I', str(self.root / 'tools/skills-eval' / rel)],
                              cwd=self.root, env=env, capture_output=True, text=True, timeout=120)

    def test_no_path_is_refused_by_name(self):
        for rel in LOADERS:
            with self.subTest(rel):
                p = self.run_loader(rel, None)
                self.assertEqual(p.returncode, 2, p.stderr)
                self.assertIn('OPENWIZ_CHECKOUT is not set', p.stderr)
                self.assertIn(CONTRACT, p.stderr)
                self.assertNotIn('planted sibling', p.stderr)
                self.assertNotIn('Traceback', p.stderr)

    def test_checkout_without_the_file_names_the_missing_path(self):
        empty = self.root / 'not-openwiz'
        empty.mkdir()
        for rel in LOADERS:
            with self.subTest(rel):
                p = self.run_loader(rel, empty)
                self.assertEqual(p.returncode, 2, p.stderr)
                self.assertIn(f'OPENWIZ_CHECKOUT: {empty / CONTRACT} is missing', p.stderr)
                self.assertNotIn('Traceback', p.stderr)


if __name__ == '__main__':
    unittest.main()
