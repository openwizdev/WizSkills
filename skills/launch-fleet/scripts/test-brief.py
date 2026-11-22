#!/usr/bin/env python3
"""brief.py (WS8, #1181): every brief the fleet sends, printed literally.

python3 -I skills/launch-fleet/scripts/test-brief.py
"""
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import unittest

HERE = Path(__file__).resolve().parent
HEAD = '0123456789abcdef0123456789abcdef01234567'
OLD = 'fedcba9876543210fedcba9876543210fedcba98'


def brief(*args):
    r = subprocess.run([sys.executable, '-I', str(HERE / 'brief.py'), *map(str, args)],
                       capture_output=True, text=True, timeout=30)
    return r.returncode, r.stdout.rstrip('\n')


def lookup(skill):
    return ("Verify .claude-plugin/plugin.json manifest name openwiz and entry ./skills/%s; report missing, "
            "unreadable or ambiguous matches, otherwise read the unique matching file and follow it" % skill)


class Brief(unittest.TestCase):
    def test_each_brief_points_at_its_own_work_and_skill(self):
        cases = [
            (('builder', 12), 'You are the builder for #12. Use the build-ticket skill.', 'build-ticket'),
            (('reviewer', 31, HEAD), 'You are the reviewer for pull request #31 at %s.' % HEAD, 'review-ticket'),
            (('re-check', 31, HEAD, OLD, 'R1,R2', 'none'),
             'Re-check pull request #31 at %s: use the review-ticket skill.' % HEAD, 'review-ticket'),
            (('fresh', 12, 31, 'room/12-synthetic', HEAD),
             'You are the fresh builder for #12: one fresh round on pull request #31, on its branch '
             'room/12-synthetic, after the report at %s.' % HEAD, 'build-ticket'),
            (('diagnose',), 'Use the diagnose skill.', 'diagnose'),
            (('tick', 'synthetic-owner/synthetic-repo', 'thr_synorch1'),
             'You are a launch-fleet tick for synthetic-owner/synthetic-repo. Use the launch-fleet skill.', 'launch-fleet'),
            (('wakes', 'synthetic-owner/synthetic-repo', 'thr_synorch1'),
             "You are a launch-fleet tick for synthetic-owner/synthetic-repo, woken by GitHub's messages.",
             'launch-fleet'),
            (('wake', 4001, 'synthetic-owner/synthetic-repo'),
             'Fleet wake for synthetic-owner/synthetic-repo spec #4001. Use the launch-fleet skill.', 'launch-fleet'),
            # The fleet thread's first-wake brief, which launch-fleet's own start path sends. Install's onboarding no
            # longer sends one of its own (OpenWiz #1358, review R7), so it is checked here directly.
            (('fleet', 4001, 'synthetic-owner/synthetic-repo'),
             'You are the fleet thread for spec #4001 of synthetic-owner/synthetic-repo. Use the launch-fleet skill.',
             'launch-fleet'),
        ]
        for args, start, skill in cases:
            with self.subTest(kind=args[0]):
                code, text = brief(*args)
                self.assertEqual(code, 0)
                self.assertTrue(text.startswith(start), text)
                self.assertIn(lookup(skill), text)
        code, text = brief('tick', 'synthetic-owner/synthetic-repo', 'thr_synorch1')
        self.assertTrue(text.endswith("do its Each wake section for the due lines below. "
                                      "The orchestrator's thread is thr_synorch1."), text)
        code, text = brief('re-check', 31, HEAD, OLD, 'R1,R2', 'none')
        self.assertIn('Open findings: R1,R2. Changed since %s: git diff %s %s' % (OLD, OLD, HEAD), text)

    def test_same_family_brief_keeps_the_machine_header_first(self):
        code, text = brief('reviewer', 31, HEAD, 'same-family')
        self.assertEqual(code, 0)
        self.assertIn('Put "same-family review" on the line immediately below the VERDICT header.', text)
        self.assertNotIn('same-family review', brief('reviewer', 31, HEAD)[1])

    def test_non_cloudroom_review_start_uses_the_installed_harnesses(self):
        fixture = runpy.run_path(str(HERE / 'test-host.py'))
        section = (HERE.parent / 'references/reviews.md').read_text().partition(
            '### Starting a review through a host driver\n')[2]
        script = section.partition('```sh\n')[2].partition('\n```')[0]
        self.assertTrue(script, 'the non-CloudRoom review has no runnable driver start')
        for builder, installed, reviewer, model, marking in (
            ('claude', ('claude', 'codex'), 'codex', 'reviewer-model', 'other-family'),
            ('codex', ('claude', 'codex'), 'claude', 'reviewer-model', 'other-family'),
            ('claude', ('claude',), 'claude', 'builder-model', 'same-family'),
            ('codex', ('codex',), 'codex', 'builder-model', 'same-family'),
        ):
            with self.subTest(builder=builder, installed=installed):
                project = fixture['Project'](self, hosts=('local',))
                bin_dir = project.dir / 'bin'
                for program in ('git', 'python3'):
                    (bin_dir / program).symlink_to(shutil.which(program))
                for harness in installed:
                    executable = bin_dir / harness
                    executable.write_text('#!/bin/sh\nexit 0\n')
                    executable.chmod(0o755)
                repo = fixture['REPO']
                env = dict(project.env, PATH=str(bin_dir))
                env.pop('CDPATH', None)
                claim = subprocess.run([sys.executable, '-I', str(HERE / 'post.py'), 'comment',
                                        repo, '31', 'launch-fleet: review starting ' + HEAD],
                                       env=env, capture_output=True, text=True, check=True, timeout=30)
                claim_id = claim.stdout.split()[1]
                start = subprocess.run(['/bin/sh', '-c', script, 'review-start', str(HERE), repo, '31', HEAD,
                                        claim_id, builder, 'builder-model', 'reviewer-model'],
                                       cwd=project.dir / 'repo', env=env, capture_output=True, text=True,
                                       timeout=30)
                self.assertEqual((start.returncode, start.stdout.strip(), start.stderr),
                                 (0, f'edited {claim_id}\nstarted #31 on local', ''))
                self.assertEqual(project.calls(), [{'host': 'local', 'command': 'start', 'input': {
                    'repository': repo, 'ticket': 31, 'skill': 'review-ticket', 'harness': reviewer, 'model': model}}])
                [(record, body)] = project.ticket(31)
                self.assertEqual(record, 'launch-fleet: review starting ' + HEAD)
                self.assertTrue(body.startswith('Driver review: ' + marking + '\n\n'), body)
                self.assertIn('pull request #31 at ' + HEAD, body)
                self.assertEqual('same-family review' in body, marking == 'same-family')

    def test_malformed_targets_print_no_brief(self):
        for args in (('builder', '12; rm -rf /'), ('reviewer', 31, 'abc123'), ('fresh', 12, 31, 'main branch', HEAD),
                     ('re-check', 31, HEAD, OLD, 'R1', 'thr_synthetic'), ('fleet', 1, 'not a repo'), ('tick', 'synthetic-owner/synthetic-repo', 'me'), ('nope',)):
            with self.subTest(args=args):
                self.assertEqual(brief(*args), (2, ''))


if __name__ == '__main__':
    unittest.main()
