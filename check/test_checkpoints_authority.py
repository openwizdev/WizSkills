import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / 'contracts' / 'checkpoints.v1.md'
EXPECTED = (
    'Authority: Jake, 2026-11-20: planning writes two checkpoint answers, '
    'one-way door and user-visible; an early say covers a one-way door, a late '
    'look at a preview, screenshots or a short video covers what users see and '
    'every release, answering no to both leaves the spec to the agents\' checks, '
    'and no section means early only ([private record](https://github.com/jparker2006/'
    'ClosedWiz/issues/3065#issuecomment-7035053757)). It relies on the '
    '[open development contract](open-development.v1.md) for the decider, the '
    'pointer and the public record forms.'
)


class CheckpointsAuthority(unittest.TestCase):
    def test_authority_line_is_the_public_source_form(self):
        lines = [
            line for line in CONTRACT.read_text(encoding='utf-8').splitlines()
            if line.startswith('Authority:')
        ]
        self.assertEqual(lines, [EXPECTED])


if __name__ == '__main__':
    unittest.main()
