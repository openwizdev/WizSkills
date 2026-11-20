#!/usr/bin/env python3
"""Print one brief the fleet sends, literally (WS8, #1181). Send its output unchanged.

  brief.py builder N
  brief.py reviewer P COMMIT
  brief.py re-check P COMMIT OLD_HEAD IDS ANSWER     IDS: R1,R2 or none; ANSWER: the builder's comment link or none
  brief.py fresh N P BRANCH COMMIT
  brief.py diagnose
  brief.py fleet S OWNER/NAME                       the fleet thread's first wake
  brief.py wake S OWNER/NAME                        a spec's fleet loop
  brief.py tick OWNER/NAME ORCHESTRATOR_THREAD      the project's safety-net loop
  brief.py wakes OWNER/NAME ORCHESTRATOR_THREAD     the project's webhook loop

A loop prompt is private routing: it may name the orchestrator's thread, which
never goes into a public record.

Exit 2 and print nothing for an unknown kind or a malformed target. The
skill-file lookup belongs to the recipient, so it is printed unexpanded.

With a token service configured (OPENWIZ_TOKEN_SERVICE set and non-empty, as
the agent helper reads it), each brief ends with the token step (GA4, OpenWiz
#1846; contracts/token-service.v1.md): the agent runs its GitHub commands
through the agent helper as a requester named for its role, and keeps
approvals, settings and workflow pushes on the owner's login. With none, every
brief is exactly as before.
"""
import os
import re
import sys

LOOKUP = ("Read 'skills/{s}/SKILL.md' if present, otherwise find '*/skills/{s}/SKILL.md' only inside your own "
          "harness's configured plugin cache: Codex uses CODEX_HOME/plugins/cache (default HOME/.codex/plugins/cache); "
          "Claude uses CLAUDE_CODE_PLUGIN_CACHE_DIR/cache when set, otherwise CLAUDE_CONFIG_DIR/plugins/cache (default "
          "HOME/.claude/plugins/cache); for another harness use its installation metadata. Prefer active installation "
          "metadata over cache scanning when available. During cache scans exclude other harness caches, source "
          "checkouts, orphaned versions marked .orphaned_at, and targets outside the selected cache. Follow symlinks "
          "and deduplicate real paths. Verify .claude-plugin/plugin.json manifest name openwiz and entry "
          "./skills/{s}; report missing, unreadable or ambiguous matches, otherwise read the unique matching file and "
          "follow it")
N = r'[1-9][0-9]{0,8}'
SHA = r'[0-9a-f]{40}'
FORMS = {
    'builder': ([N], 'You are the builder for #{0}. Use the build-ticket skill. {b}.'),
    'reviewer': ([N, SHA], 'You are the reviewer for pull request #{0} at {1}. Use the review-ticket skill. {r}.'),
    're-check': ([N, SHA, SHA, r'none|R[0-9]+(,R[0-9]+)*', r'none|https://github\.com/[A-Za-z0-9_./#-]+'],
                 "Re-check pull request #{0} at {1}: use the review-ticket skill. {r}, Re-checks. Open findings: {3}. "
                 "Changed since {2}: git diff {2} {1}; the builder's answer: {4}."),
    'fresh': ([N, N, r'room/[A-Za-z0-9._/-]+', SHA],
              'You are the fresh builder for #{0}: one fresh round on pull request #{1}, on its branch {2}, after '
              'the report at {3}. Use the build-ticket skill. {b}, its fresh round.'),
    'diagnose': ([], 'Use the diagnose skill. {d} for the finding.'),
    'fleet': ([N, r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+'],
              'You are the fleet thread for spec #{0} of {1}. Use the launch-fleet skill. {f}; do its Fleet threads '
              'section, first wake.'),
    'wake': ([N, r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+'],
             'Fleet wake for {1} spec #{0}. Use the launch-fleet skill. {f}; do its Fleet threads section, Each wake.'),
    'tick': ([r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+', r'thr_[A-Za-z0-9_-]+'],
             "You are a launch-fleet tick for {0}. Use the launch-fleet skill. {f}; do its Each wake section for the "
             "due lines below. The orchestrator's thread is {1}."),
    'wakes': ([r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+', r'thr_[A-Za-z0-9_-]+'],
              "You are a launch-fleet tick for {0}, woken by GitHub's messages. Use the launch-fleet skill. {f}; do its "
              "Each wake section for the messages below. The orchestrator's thread is {1}."),
}

# Who asks, and for which repository, per brief (the contract's synthetic `requester` label).
REQUESTERS = {'builder': ('builder-{0}', None), 'fresh': ('builder-{0}', None), 'reviewer': ('reviewer-{0}', None),
              're-check': ('reviewer-{0}', None), 'diagnose': ('diagnose', None), 'fleet': ('fleet-{0}', '{1}'),
              'wake': ('fleet-{0}', '{1}'), 'tick': ('fleet-tick', '{0}'), 'wakes': ('fleet-tick', '{0}')}
TOKEN = (" GitHub token: run every gh or git command that reaches GitHub through the agent helper, the launch-fleet "
         "skill's `scripts/github-app/agent-token.py` (find launch-fleet's SKILL.md as above): first "
         "`python3 -I <helper> start --requester {who} --repository {repo}`, then "
         "`python3 -I <helper> run --requester {who} --repository {repo} -- <command>` for each command, with the same "
         "request every time and `--repository` once for each repository you read or write (all of one owner). Inside a run git "
         "reaches GitHub over HTTPS only, never SSH. If it gets no token it says so once on stderr and runs the command as the owner's login: go on. Approvals, "
         "repository settings and pushes that change `.github/workflows/` stay on the owner's login: run those "
         "without the helper.")


def token_step(kind, args):
    """The brief's token sentence when a token service is configured, else nothing (exactly as today)."""
    if not os.environ.get('OPENWIZ_TOKEN_SERVICE'):
        return ''
    who, repo = REQUESTERS[kind]
    return TOKEN.format(who=who.format(*args), repo=repo.format(*args) if repo else 'OWNER/NAME')


def main(argv):
    form = FORMS.get(argv[0]) if argv else None
    if form is None or len(argv) - 1 != len(form[0]) \
            or not all(re.fullmatch(p, a) for p, a in zip(form[0], argv[1:])):
        return 2
    print(form[1].format(*argv[1:], **{k: LOOKUP.format(s=s) for k, s in
                                       (('b', 'build-ticket'), ('r', 'review-ticket'), ('d', 'diagnose'),
                                        ('f', 'launch-fleet'))}) + token_step(argv[0], argv[1:]))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
