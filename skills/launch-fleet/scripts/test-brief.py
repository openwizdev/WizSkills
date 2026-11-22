#!/usr/bin/env python3
"""brief.py (WS8, #1181): every brief the fleet sends, printed literally.

python3 -I skills/launch-fleet/scripts/test-brief.py
"""
import ast
from pathlib import Path
import os
import subprocess
import sys
import unittest

HERE = Path(__file__).resolve().parent
HEAD = '0123456789abcdef0123456789abcdef01234567'
OLD = 'fedcba9876543210fedcba9876543210fedcba98'


SERVICE = '/synthetic/openwiz/tools/github-app/token-service.py'
EXCLUSIVE = ("The helper is your only App-token route: never run `openwiz github token`, the App-token block in "
             "launch-fleet's `references/identity.md`, or any command with `OPENWIZ_GITHUB_APP_KEY` in its "
             "environment.")
OWNER_LOGIN = ("Approvals, repository settings and pushes that change `.github/workflows/` stay on the owner's "
               "login: run those without the helper.")


def brief(*args, **env):
    base = {k: v for k, v in os.environ.items() if not k.startswith('OPENWIZ_')}
    r = subprocess.run([sys.executable, '-I', str(HERE / 'brief.py'), *map(str, args)],
                       capture_output=True, text=True, timeout=30, env={**base, **env})
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

    def test_malformed_targets_print_no_brief(self):
        for args in (('builder', '12; rm -rf /'), ('reviewer', 31, 'abc123'), ('fresh', 12, 31, 'main branch', HEAD),
                     ('re-check', 31, HEAD, OLD, 'R1', 'thr_synthetic'), ('fleet', 1, 'not a repo'), ('tick', 'synthetic-owner/synthetic-repo', 'me'), ('nope',)):
            with self.subTest(args=args):
                self.assertEqual(brief(*args), (2, ''))


GH_ALLOWED = sorted(ast.literal_eval(next(
    node.value.args[0] for node in ast.parse((HERE / 'github-app/agent-token.py').read_text()).body
    if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', '') == 'GH_ALLOWED')))


class Token(unittest.TestCase):
    KINDS = [(('builder', 12), 'builder-12', 'OWNER/NAME'),
             (('fresh', 12, 31, 'room/12-synthetic', HEAD), 'builder-12', 'OWNER/NAME'),
             (('reviewer', 31, HEAD), 'reviewer-31', 'OWNER/NAME'),
             (('re-check', 31, HEAD, OLD, 'R1', 'none'), 'reviewer-31', 'OWNER/NAME'),
             (('diagnose',), 'diagnose', 'OWNER/NAME'),
             (('fleet', 4001, 'synthetic-owner/synthetic-repo'), 'fleet-4001', 'synthetic-owner/synthetic-repo'),
             (('wake', 4001, 'synthetic-owner/synthetic-repo'), 'fleet-4001', 'synthetic-owner/synthetic-repo'),
             (('tick', 'synthetic-owner/synthetic-repo', 'thr_syn-orch'), 'fleet-tick', 'synthetic-owner/synthetic-repo'),
             (('wakes', 'synthetic-owner/synthetic-repo', 'thr_syn-orch'), 'fleet-tick',
              'synthetic-owner/synthetic-repo')]

    def test_with_a_service_every_brief_starts_and_runs_through_the_helper(self):
        for args, requester, repo in self.KINDS:
            with self.subTest(kind=args[0]):
                code, text = brief(*args, OPENWIZ_TOKEN_SERVICE=SERVICE)
                self.assertEqual(code, 0)
                self.assertIn("the launch-fleet skill's `scripts/github-app/agent-token.py`", text)
                self.assertIn('`env -u OPENWIZ_GITHUB_APP_KEY python3 -I <helper> start --requester %s --repository %s`'
                              % (requester, repo), text)
                self.assertIn('`env -u OPENWIZ_GITHUB_APP_KEY python3 -I <helper> run --requester %s --repository %s '
                              '-- <command>`' % (requester, repo), text)
                self.assertIn(EXCLUSIVE, text)
                self.assertIn(OWNER_LOGIN, text)
                self.assertNotIn(SERVICE, text)
                self.assertIn('Only these gh commands run through the helper: %s; it stops any other gh command, '
                              'so run that without the helper.' % ', '.join('`gh %s`' % c for c in GH_ALLOWED), text)

    def test_with_no_service_every_brief_is_exactly_as_today(self):
        expected = ('You are the builder for #12. Use the build-ticket skill. ' + LOOKUP_BUILD + '.')
        for env in ({}, {'OPENWIZ_TOKEN_SERVICE': ''}):
            with self.subTest(env=env):
                self.assertEqual(brief('builder', 12, **env), (0, expected))
                for args, _, _ in self.KINDS:
                    code, text = brief(*args, **env)
                    self.assertNotIn('agent-token', text)
                    self.assertNotIn(OWNER_LOGIN, text)
                    self.assertNotIn(EXCLUSIVE, text)


LOOKUP_BUILD = (
    "Read 'skills/build-ticket/SKILL.md' if present, otherwise find '*/skills/build-ticket/SKILL.md' only inside your "
    "own harness's configured plugin cache: Codex uses CODEX_HOME/plugins/cache (default HOME/.codex/plugins/cache); "
    "Claude uses CLAUDE_CODE_PLUGIN_CACHE_DIR/cache when set, otherwise CLAUDE_CONFIG_DIR/plugins/cache (default "
    "HOME/.claude/plugins/cache); for another harness use its installation metadata. Prefer active installation "
    "metadata over cache scanning when available. During cache scans exclude other harness caches, source "
    "checkouts, orphaned versions marked .orphaned_at, and targets outside the selected cache. Follow symlinks "
    "and deduplicate real paths. Verify .claude-plugin/plugin.json manifest name openwiz and entry "
    "./skills/build-ticket; report missing, unreadable or ambiguous matches, otherwise read the unique matching "
    "file and follow it")


if __name__ == '__main__':
    unittest.main()
