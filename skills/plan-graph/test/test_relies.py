#!/usr/bin/env python3
"""TV12: the public Relies-on validator, moved from OpenWiz skills.rs.

Catches declarations that hide a dependency, bypass path validation or depend
on Python at runtime. Synthetic inputs; the checker gets only sh and jq.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'check-relies.sh'

CASES = [('nothing', '**Relies on:** nothing\n', None, True),
 ('embedded-cr-duplicate',
  '**Relies \ron:** `contracts/widget.v1.md`\n**Relies on:** `contracts/widget.v1.schema.json`\n',
  None,
  False),
 ('crlf', '**Relies on:** `contracts/widget.v1.md`\r\n', None, True),
 ('bare-cr-boundary', 'Synthetic title\r**Relies on:** `contracts/widget.v1.md`\n', None, False),
 ('unicode-boundary',
  'Synthetic title\u2028**Relies on:** `contracts/widget.v1.md`\n',
  None,
  False),
 ('one', '**Relies on:** `contracts/widget.v1.md`\n', None, True),
 ('two',
  '**Relies on:** `contracts/widget.v1.md`, `contracts/widget.v1.schema.json`\n',
  None,
  True),
 ('root-file', '**Relies on:** `GLOSSARY.md`\n', None, True),
 ('rules-file', '**Relies on:** `skills/launch-fleet/SKILL.md`\n', None, True),
 ('planned', '**Relies on:** `contracts/future.v1.md`\n', 'contracts/future.v1.md', True),
 ('historical-118',
  "**Relies on:** `contracts/fleet-tick.v1.*` (B1); 0.0.5's `launch-fleet` rules (#102)\n",
  None,
  False),
 ('prose', '**Relies on:** the review report format (0.0.5 #101)\n', None, False),
 ('partial-name', '**Relies on:** `launch-fleet`\n', None, False),
 ('partial-file', '**Relies on:** `widget.v1.md`\n', None, False),
 ('mixed', '**Relies on:** `contracts/widget.v1.md`; review rules\n', None, False),
 ('annotation', '**Relies on:** `contracts/widget.v1.md` (#110)\n', None, False),
 ('folder', '**Relies on:** `contracts/`\n', None, False),
 ('glob', '**Relies on:** `contracts/widget.v1.*`\n', None, False),
 ('triple-star-duplicate',
  '***Relies on: `contracts/widget.v1.md`\n**Relies on:** `contracts/widget.v1.schema.json`\n',
  None,
  False),
 ('planned-file-parent',
  '**Relies on:** `contracts/widget.v1.md/future.md`\n',
  'contracts/widget.v1.md/future.md',
  False),
 ('directory', '**Relies on:** `contracts`\n', None, False),
 ('symlink', '**Relies on:** `contracts/alias.md`\n', None, False),
 ('symlink-parent', '**Relies on:** `contracts/alias-dir/GLOSSARY.md`\n', None, False),
 ('planned-symlink',
  '**Relies on:** `contracts/alias-dir/future.md`\n',
  'contracts/alias-dir/future.md',
  False),
 ('missing', '**Owned paths:** `contracts/widget.v1.md`\n', None, False),
 ('empty', '**Relies on:**\n', None, False),
 ('section', '## Relies on\n\n`contracts/widget.v1.md`\n', None, False),
 ('multiline',
  '**Relies on:** `contracts/widget.v1.md`\n`contracts/widget.v1.schema.json`\n',
  None,
  False),
 ('duplicate', '**Relies on:** nothing\n**Relies on:** `contracts/widget.v1.md`\n', None, False),
 ('duplicate-heading',
  '**Relies on:** nothing\n## Relies on\n\n`contracts/widget.v1.md`\n',
  None,
  False),
 ('empty-ticks', '**Relies on:** ``\n', None, False),
 ('unclosed', '**Relies on:** `contracts/widget.v1.md\n', None, False),
 ('double-ticks', '**Relies on:** ``contracts/widget.v1.md``\n', None, False),
 ('nothing-and-file', '**Relies on:** nothing, `contracts/widget.v1.md`\n', None, False),
 ('quoted-nothing', '**Relies on:** `nothing`\n', None, False),
 ('wrong-case', '**Relies on:** Nothing\n', None, False),
 ('absolute', '**Relies on:** `/contracts/widget.v1.md`\n', None, False),
 ('parent', '**Relies on:** `../contracts/widget.v1.md`\n', None, False),
 ('dot', '**Relies on:** `./contracts/widget.v1.md`\n', None, False),
 ('double-slash', '**Relies on:** `contracts//widget.v1.md`\n', None, False),
 ('non-ascii', '**Relies on:** `contracts/widgét.md`\n', None, False),
 ('unknown-file', '**Relies on:** `contracts/missing.md`\n', None, False),
 ('wrong-planned', '**Relies on:** `contracts/other.md`\n', 'contracts/future.v1.md', False),
 ('fenced', '```md\n**Relies on:** nothing\n```\n', None, False),
 ('commented', '<!--\n**Relies on:** nothing\n-->\n', None, False)]


class ReliesTest(unittest.TestCase):
    def test_relies_on_form(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for file, text in {
                'contracts/widget.v1.md': 'Synthetic contract.\n',
                'contracts/widget.v1.schema.json': '{}\n',
                'skills/launch-fleet/SKILL.md': 'Synthetic rules.\n',
                'GLOSSARY.md': 'Synthetic words.\n',
            }.items():
                path = root / file
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            (root / 'contracts/alias.md').symlink_to(root / 'GLOSSARY.md')
            (root / 'contracts/alias-dir').symlink_to(root, target_is_directory=True)
            tools = root / 'checker-tools'
            tools.mkdir()
            for name in ('sh', 'jq'):
                program = shutil.which(name)
                self.assertIsNotNone(program, name)
                (tools / name).symlink_to(program)
            for name, body, planned, valid in CASES:
                with self.subTest(case=name):
                    args = [str(tools / 'sh'), str(SCRIPT), '--root', str(root)]
                    if planned is not None:
                        args += ['--planned', planned]
                    ticket = f'# Synthetic ticket\n\n{body}\n## Acceptance criteria\n\n- [ ] Synthetic proof.\n'
                    result = subprocess.run(args, input=ticket.encode(), capture_output=True,
                                            env={'PATH': str(tools)})
                    self.assertEqual(result.returncode, 0 if valid else 1, result.stderr)
                    self.assertEqual(result.stdout, b'')
                    if not valid:
                        self.assertTrue(result.stderr.startswith(b'Relies on: '), result.stderr)


if __name__ == '__main__':
    unittest.main()
