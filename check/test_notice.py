"""The adapted-skill notice rule: Matt Pocock's notice lives word for word in
the skill's sibling NOTICE.md, and SKILL.md links it without carrying it."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run  # noqa: E402

FRONT = '---\nname: demo\ndescription: A synthetic skill.\n---\n\n# Demo\n\nDo one thing.\n'
CREDIT = "Credit: adapted from Matt Pocock's skills; the notice is in [NOTICE.md](NOTICE.md).\n"
NOTICE = 'Adapted from a synthetic upstream skill.\n\n' + run.MATT_NOTICE + '\n'


def notice_findings(skill_md, notice_md=None):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        folder = root / 'skills' / 'demo'
        folder.mkdir(parents=True)
        (folder / 'SKILL.md').write_text(skill_md, encoding='utf-8')
        if notice_md is not None:
            (folder / 'NOTICE.md').write_text(notice_md, encoding='utf-8')
        out = run.Findings()
        run.skill(root, 'demo', out)
        return [(file, message) for rule, file, _, message in out if rule == 'notice']


class NoticeRule(unittest.TestCase):
    def test_notice_in_notice_md_with_credit_link_passes(self):
        self.assertEqual(notice_findings(FRONT + '\n' + CREDIT, NOTICE), [])

    def test_lost_notice_file_is_refused(self):
        found = notice_findings(FRONT + '\n' + CREDIT)
        self.assertEqual([f for f, _ in found], ['skills/demo/NOTICE.md'])

    def test_altered_notice_is_refused(self):
        altered = NOTICE.replace('free of charge', 'for a fee')
        found = notice_findings(FRONT + '\n' + CREDIT, altered)
        self.assertEqual([f for f, _ in found], ['skills/demo/NOTICE.md'])

    def test_notice_embedded_again_in_skill_md_is_refused(self):
        found = notice_findings(FRONT + '\n' + NOTICE + '\n' + CREDIT, NOTICE)
        self.assertEqual([f for f, _ in found], ['skills/demo/SKILL.md'])

    def test_missing_credit_link_is_refused(self):
        found = notice_findings(FRONT, NOTICE)
        self.assertEqual([f for f, _ in found], ['skills/demo/SKILL.md'])
        self.assertIn('NOTICE.md', found[0][1])

    def test_credit_link_only_mid_body_is_refused(self):
        found = notice_findings(FRONT + '\n' + CREDIT + '\n## Later\n\nMore steps.\n', NOTICE)
        self.assertEqual([f for f, _ in found], ['skills/demo/SKILL.md'])


if __name__ == '__main__':
    unittest.main()
