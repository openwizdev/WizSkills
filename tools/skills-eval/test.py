#!/usr/bin/env python3
"""Offline proofs for the skills eval's case privacy scan (#1361). No key, no network, synthetic inputs only.

Run: python3 -I tools/skills-eval/test.py
"""
import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cases as C  # noqa: E402


def setUpModule():
    # Offline controls explicitly supply synthetic literals; no private checkout read.
    folder = unittest.enterModuleContext(tempfile.TemporaryDirectory())
    literals = Path(folder) / 'literals.txt'
    literals.write_text('synthetic-private-machine\n', encoding='utf-8')
    unittest.enterModuleContext(mock.patch.dict(os.environ, {
        'OPENWIZ_PRIVACY_LITERALS': str(literals),
    }))


class Contract(unittest.TestCase):
    """Committed eval cases carry no link, operational id or private literal."""

    def test_privacy_scan_catches_planted_identifiers(self):
        base = C.load_all()[0]
        for planted in ('see https://github.com/x/y', 'thread thr_synnegative', 'thread cr_child_synthetic', 'issue #123', 'issue #3999',
                        'key sk-ant-abc', 'mail someone@example.org', 'ask Jake'):
            c = copy.deepcopy(base)
            c['brief'] += ' ' + planted
            self.assertTrue(C.privacy_problems(c), planted)
        self.assertEqual(C.privacy_problems(base), [])

    def test_privacy_private_input_refuses_missing_unreadable_or_empty(self):
        base = C.load_all()[0]
        refusal = ['case privacy: private literals input is missing, unreadable or empty']
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ):
            literals = Path(d) / 'literals.txt'
            os.environ.pop('OPENWIZ_PRIVACY_LITERALS', None)
            with self.subTest(input='unset'):
                self.assertEqual(C.privacy_problems(base), refusal)
            for path in ('', str(literals), d):
                with self.subTest(path=path):
                    os.environ['OPENWIZ_PRIVACY_LITERALS'] = path
                    self.assertEqual(C.privacy_problems(base), refusal)
            os.environ['OPENWIZ_PRIVACY_LITERALS'] = str(literals)
            for data in (b'', b'\n', b'synthetic-private-machine\n\n', b'\xff'):
                with self.subTest(data=data):
                    literals.write_bytes(data)
                    self.assertEqual(C.privacy_problems(base), refusal)
            literals.write_text('synthetic-private-machine\n', encoding='utf-8')
            with self.subTest(input='permission denied'), mock.patch.object(Path, 'read_text', side_effect=PermissionError):
                self.assertEqual(C.privacy_problems(base), refusal)
            self.assertEqual(C.privacy_problems(base), [])


if __name__ == '__main__':
    unittest.main(verbosity=1)
