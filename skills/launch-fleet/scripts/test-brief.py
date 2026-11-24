#!/usr/bin/env python3
"""brief.py (WS8, #1181): every brief the fleet sends, printed literally.

python3 -I skills/launch-fleet/scripts/test-brief.py
"""
import ast
from pathlib import Path
import os
import re
import runpy
import shutil
import subprocess
import sys
import unittest

HERE = Path(__file__).resolve().parent
HEAD = '0123456789abcdef0123456789abcdef01234567'
OLD = 'fedcba9876543210fedcba9876543210fedcba98'
TICKET = 'synthetic-owner/synthetic-tracker#12'
PR = 'synthetic-owner/synthetic-code#31'
PASS_REPO = ("Every ticket and pull request above is written as OWNER/NAME#N: pass that OWNER/NAME with `--repo` on "
             "every `gh` command (in `gh api`, as the `repos/OWNER/NAME/` path), never your sandbox's own repository.")


SERVICE = '/synthetic/openwiz/tools/github-app/token-service.py'
EXCLUSIVE = ("The helper is your only App-token route: never run `openwiz github token`, the App-token block in "
             "launch-fleet's `references/identity.md`, or any command with `OPENWIZ_GITHUB_APP_KEY` in its "
             "environment.")
OWNER_LOGIN = ("Approvals, repository settings and pushes that change `.github/workflows/` stay on the owner's "
               "login: run those without the helper.")


def brief(*args, **env):
    base = {k: v for k, v in os.environ.items() if not k.startswith('OPENWIZ_') and k != 'GH_REPO'}
    r = subprocess.run([sys.executable, '-I', str(HERE / 'brief.py'), *map(str, args)],
                       capture_output=True, text=True, timeout=30, env={**base, **env})
    return r.returncode, r.stdout.rstrip('\n')


def lookup(skill):
    return ("Verify .claude-plugin/plugin.json manifest name openwiz and entry ./skills/%s; report missing, "
            "unreadable or ambiguous matches, otherwise read the unique matching file and follow it" % skill)


class Brief(unittest.TestCase):
    def test_each_brief_points_at_its_own_work_and_skill(self):
        cases = [
            (('builder', TICKET), 'You are the builder for %s. Use the build-ticket skill.' % TICKET, 'build-ticket'),
            (('reviewer', PR, HEAD), 'You are the reviewer for pull request %s at %s.' % (PR, HEAD), 'review-ticket'),
            (('re-check', PR, HEAD, OLD, 'R1,R2', 'none'),
             'Re-check pull request %s at %s: use the review-ticket skill.' % (PR, HEAD), 'review-ticket'),
            (('fresh', TICKET, PR, 'room/12-synthetic', HEAD),
             'You are the fresh builder for %s: one fresh round on pull request %s, on its branch '
             'room/12-synthetic, after the report at %s.' % (TICKET, PR, HEAD), 'build-ticket'),
            (('diagnose',), 'Use the diagnose skill.', 'diagnose'),
            (('tick', 'synthetic-owner/synthetic-repo', 'thr_synorch1'),
             'You are a launch-fleet tick for synthetic-owner/synthetic-repo. Use the launch-fleet skill.', 'launch-fleet'),
            (('wakes', 'synthetic-owner/synthetic-repo', 'thr_synorch1'),
             "You are a launch-fleet tick for synthetic-owner/synthetic-repo, woken by GitHub's messages.",
             'launch-fleet'),
            (('wake', 4001, 'synthetic-owner/synthetic-repo'),
             'Fleet wake for spec synthetic-owner/synthetic-repo#4001. Use the launch-fleet skill.', 'launch-fleet'),
            # The fleet thread's first-wake brief, which launch-fleet's own start path sends. Install's onboarding no
            # longer sends one of its own (OpenWiz #1358, review R7), so it is checked here directly.
            (('fleet', 4001, 'synthetic-owner/synthetic-repo'),
             'You are the fleet thread for spec synthetic-owner/synthetic-repo#4001. Use the launch-fleet skill.',
             'launch-fleet'),
        ]
        for args, start, skill in cases:
            with self.subTest(kind=args[0]):
                code, text = brief(*args)
                self.assertEqual(code, 0)
                self.assertTrue(text.startswith(start), text)
                self.assertIn(lookup(skill), text)
        code, text = brief('tick', 'synthetic-owner/synthetic-repo', 'thr_syn-orch')
        self.assertTrue(text.endswith("do its Each wake section for the due lines below. "
                                      "The orchestrator's thread is thr_syn-orch. " + PASS_REPO), text)
        code, text = brief('re-check', PR, HEAD, OLD, 'R1,R2', 'none')
        self.assertIn('Open findings: R1,R2. Changed since %s: git diff %s %s' % (OLD, OLD, HEAD), text)

    def test_same_family_brief_keeps_the_machine_header_first(self):
        code, text = brief('reviewer', PR, HEAD, 'same-family')
        self.assertEqual(code, 0)
        self.assertIn('Put "same-family review" on the line immediately below the VERDICT header.', text)
        self.assertNotIn('same-family review', brief('reviewer', PR, HEAD)[1])

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
                self.assertIn('pull request %s#31 at %s' % (repo, HEAD), body)
                self.assertEqual('same-family review' in body, marking == 'same-family')

    def test_malformed_targets_print_no_brief(self):
        for args in (('builder', '12; rm -rf /'), ('reviewer', PR, 'abc123'), ('fresh', TICKET, PR, 'main branch', HEAD),
                     ('re-check', PR, HEAD, OLD, 'R1', 'thr_syn-x'), ('fleet', 1, 'not a repo'), ('tick', 'synthetic-owner/synthetic-repo', 'me'), ('nope',)):
            with self.subTest(args=args):
                self.assertEqual(brief(*args), (2, ''))


class Repository(unittest.TestCase):
    ALL = [('builder', TICKET), ('reviewer', PR, HEAD), ('reviewer', PR, HEAD, 'same-family'),
           ('re-check', PR, HEAD, OLD, 'R1,R2', 'none'), ('fresh', TICKET, PR, 'room/12-synthetic', HEAD),
           ('diagnose',), ('fleet', 4001, 'synthetic-owner/synthetic-repo'),
           ('wake', 4001, 'synthetic-owner/synthetic-repo'), ('tick', 'synthetic-owner/synthetic-repo', 'thr_syn-orch'),
           ('wakes', 'synthetic-owner/synthetic-repo', 'thr_syn-orch')]

    def test_no_brief_names_a_ticket_or_pull_request_without_its_repository(self):
        for env in ({}, {'OPENWIZ_TOKEN_SERVICE': SERVICE}):
            for args in self.ALL:
                with self.subTest(args=args, env=env):
                    code, text = brief(*args, **env)
                    self.assertEqual(code, 0)
                    self.assertIsNone(re.search(r'(?<![A-Za-z0-9_.-])#[0-9]', text), text)
        self.assertIn('fresh builder for %s: one fresh round on pull request %s,' % (TICKET, PR),
                      brief('fresh', TICKET, PR, 'room/12-synthetic', HEAD)[1])

    def test_every_brief_says_to_pass_the_repository_to_gh(self):
        for args in self.ALL:
            with self.subTest(args=args):
                self.assertIn(PASS_REPO, brief(*args)[1])

    def test_a_bare_or_malformed_number_prints_no_brief(self):
        for args in (('builder', 12), ('builder', '#12'), ('builder', 'synthetic-tracker#12'),
                     ('builder', TICKET + ' x'), ('builder', 'synthetic-owner/synthetic-tracker#0'),
                     ('reviewer', 31, HEAD), ('re-check', 31, HEAD, OLD, 'R1', 'none'),
                     ('fresh', 12, PR, 'room/12-synthetic', HEAD), ('fresh', TICKET, 31, 'room/12-synthetic', HEAD)):
            with self.subTest(args=args):
                self.assertEqual(brief(*args), (2, ''))

    def test_a_bare_reviewer_number_prints_no_brief_even_with_an_inherited_gh_repo(self):
        for repo in ('synthetic-owner/synthetic-private', 'synthetic-owner/synthetic-code'):
            for extra in ((), ('same-family',)):
                for env in ({'GH_REPO': repo}, {'GH_REPO': repo, 'OPENWIZ_TOKEN_SERVICE': SERVICE}):
                    with self.subTest(env=env, extra=extra):
                        self.assertEqual(brief('reviewer', 31, HEAD, *extra, **env), (2, ''))

    def test_a_bare_number_with_no_usable_repository_prints_no_brief(self):
        for repo in (None, '', 'synthetic-code', 'not a repo', 'synthetic-owner/synthetic-code#31',
                     'github.com/synthetic-owner/synthetic-code', 'synthetic-owner/..', 'synthetic-owner/.'):
            for extra in ((), ('same-family',)):
                with self.subTest(repo=repo, extra=extra):
                    env = {} if repo is None else {'GH_REPO': repo}
                    self.assertEqual(brief('reviewer', 31, HEAD, *extra, **env), (2, ''))
        for args in (('builder', 12), ('re-check', 31, HEAD, OLD, 'R1', 'none'),
                     ('fresh', 12, PR, 'room/12-synthetic', HEAD), ('fresh', TICKET, 31, 'room/12-synthetic', HEAD),
                     ('reviewer', '#31', HEAD), ('reviewer', 0, HEAD), ('reviewer', '31 x', HEAD)):
            with self.subTest(args=args):
                self.assertEqual(brief(*args, GH_REPO='synthetic-owner/synthetic-code'), (2, ''))


GH_ALLOWED = sorted(ast.literal_eval(next(
    node.value.args[0] for node in ast.parse((HERE / 'github-app/agent-token.py').read_text()).body
    if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', '') == 'GH_ALLOWED')))


class Token(unittest.TestCase):
    KINDS = [(('builder', TICKET), 'builder-12', 'OWNER/NAME'),
             (('fresh', TICKET, PR, 'room/12-synthetic', HEAD), 'builder-12', 'OWNER/NAME'),
             (('reviewer', PR, HEAD), 'reviewer-31', 'OWNER/NAME'),
             (('re-check', PR, HEAD, OLD, 'R1', 'none'), 'reviewer-31', 'OWNER/NAME'),
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
        expected = ('You are the builder for %s. Use the build-ticket skill. ' % TICKET + LOOKUP_BUILD + '. '
                    + PASS_REPO)
        for env in ({}, {'OPENWIZ_TOKEN_SERVICE': ''}):
            with self.subTest(env=env):
                self.assertEqual(brief('builder', TICKET, **env), (0, expected))
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
