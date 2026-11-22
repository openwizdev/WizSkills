#!/usr/bin/env python3
import json
import subprocess
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKER = HERE.parent / 'check-links.sh'
LINKS = HERE / 'links'

EXIT = {
    'clean-wide': 0,
    'comment-and-fence-markers': 1,
    'closed-blocker': 0,
    'external-blockers': 0,
    'low-stock': 0,
    'own-long-form': 1,
    'real-and-file': 0,
    'refuse-duplicate': 1,
    'refuse-file-without-file': 1,
    'refuse-malformed': 1,
    'refuse-no-reason': 1,
    'refuse-not-a-blocker': 1,
    'refuse-real-without-behaviour': 1,
    'this-spec': 0,
    'unapproved-proposal': 0,
}


def check(case, *flags):
    graph = (LINKS / case / 'graph.json').read_bytes()
    return subprocess.run(['sh', str(CHECKER), *flags, '--graph', '-'], input=graph, capture_output=True,
                          timeout=120)


class Fixtures(unittest.TestCase):
    def test_every_case_folder_is_in_the_table(self):
        self.assertEqual(sorted(p.parent.name for p in LINKS.glob('*/graph.json')), sorted(EXIT))

    def test_each_case_gives_its_report_its_standard_error_and_its_exit(self):
        for case, code in EXIT.items():
            with self.subTest(case):
                expected_err = (LINKS / case / 'stderr.txt').read_bytes()
                text = check(case)
                self.assertEqual(text.stdout, (LINKS / case / 'report.txt').read_bytes())
                self.assertEqual(text.stderr, expected_err)
                self.assertEqual(text.returncode, code)
                report = check(case, '--json')
                self.assertEqual(json.loads(report.stdout), json.loads((LINKS / case / 'report.json').read_bytes()))
                self.assertEqual(report.stderr, expected_err)
                self.assertEqual(report.returncode, code)


if __name__ == '__main__':
    unittest.main(verbosity=2)
