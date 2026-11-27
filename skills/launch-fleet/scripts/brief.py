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
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HARNESS_SKILL_PATHS = (
    ('codex', 'Codex',
     'CODEX_HOME/plugins/cache (default HOME/.codex/plugins/cache) or CODEX_HOME/skills (default HOME/.codex/skills)'),
    ('claude', 'Claude',
     'CLAUDE_CODE_PLUGIN_CACHE_DIR/cache when set, otherwise CLAUDE_CONFIG_DIR/plugins/cache '
     '(default HOME/.claude/plugins/cache), or CLAUDE_CONFIG_DIR/skills (default HOME/.claude/skills)'),
    ('agy', 'Antigravity (agy)', 'HOME/.gemini/config/skills'),
    ('gemini', 'Gemini', 'HOME/.gemini/skills'),
    ('cursor', 'Cursor', 'HOME/.cursor/skills'),
    ('opencode', 'OpenCode', 'XDG_CONFIG_HOME/opencode/skills (default HOME/.config/opencode/skills)'),
    ('grok', 'Grok', 'HOME/.grok/skills'),
    ('copilot', 'Copilot', 'COPILOT_HOME/skills (default HOME/.copilot/skills)'),
    ('pi', 'Pi', 'HOME/.pi/agent/skills'),
    ('goose', 'Goose', 'XDG_CONFIG_HOME/goose/skills (default HOME/.config/goose/skills)'),
    ('amp', 'Amp', 'XDG_CONFIG_HOME/agents/skills (default HOME/.config/agents/skills)'),
    ('auggie', 'Auggie', 'HOME/.augment/skills'),
    ('junie', 'Junie', 'HOME/.junie/skills'),
    ('kilo', 'Kilo', 'HOME/.kilo/skills'),
    ('kimi', 'Kimi', 'KIMI_CODE_HOME/skills (default HOME/.kimi-code/skills)'),
    ('qwen', 'Qwen', 'HOME/.qwen/skills'),
    ('oz', 'Oz', 'the shared roots'),
    ('droid', 'Droid', 'HOME/.factory/skills'),
    ('hermes', 'Hermes', 'HOME/.hermes/skills'),
    ('prime', 'Prime', 'HOME/.prime/agent/skills'),
    ('mistral', 'Mistral', 'VIBE_HOME/skills (default HOME/.vibe/skills)'),
    ('devin', 'Devin', 'XDG_CONFIG_HOME/devin/skills (default HOME/.config/devin/skills)'),
)
WIZSKILLS_REPO = 'https://github.com/openwizdev/WizSkills.git'
SEMVER = r'[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?'
WIZSKILLS_VERSION = '0.5.0'
SHARED_SKILL_ROOTS = ("Every harness also reads HOME/.agents/skills, the project's .agents/skills, "
                      'and $HOME/wizskills/skills.')


def wizskills_clone_command():
    if isinstance(WIZSKILLS_VERSION, str) and re.fullmatch(SEMVER, WIZSKILLS_VERSION):
        return 'git clone --depth 1 --branch v%s %s' % (WIZSKILLS_VERSION, WIZSKILLS_REPO)
    return 'git clone --depth 1 %s' % WIZSKILLS_REPO


LOOKUP = ("Read 'skills/{s}/SKILL.md' only when the real path of this checkout's skills/ has a parent folder whose "
          ".claude-plugin/plugin.json has manifest name openwiz and entry ./skills/{s} (never another repository's "
          "skills/); otherwise find '{s}/SKILL.md' or '*/skills/{s}/SKILL.md' inside your own harness's skills folder "
          "or configured plugin cache: "
          + '; '.join('%s uses %s' % (label, path_spec) for _, label, path_spec in HARNESS_SKILL_PATHS)
          + '. ' + SHARED_SKILL_ROOTS + ' Prefer active installation metadata over cache scanning when available. '
          "During scans exclude other harness caches, source checkouts, orphaned versions marked .orphaned_at, and "
          "targets outside the selected root. Follow symlinks and deduplicate real paths. If no installed copy is "
          "found, clone WizSkills ({clone}) and read its skills/{s}/SKILL.md. Verify .claude-plugin/plugin.json "
          "manifest name openwiz and entry ./skills/{s} (or an installed copy's .openwiz-skill marker); report "
          "missing, unreadable or ambiguous matches, otherwise read the unique matching file and follow it")
N = r'[1-9][0-9]{0,8}'
REPO = r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+'
REF = REPO + '#' + N
SHA = r'[0-9a-f]{40}'
FORMS = {
    'builder': ([REF], 'You are the builder for {0}. Use the build-ticket skill. {b}.'),
    'reviewer': ([REF, SHA], 'You are the reviewer for pull request {0} at {1}. Use the review-ticket skill. {r}.'),
    're-check': ([REF, SHA, SHA, r'none|R[0-9]+(,R[0-9]+)*', r'none|https://github\.com/[A-Za-z0-9_./#-]+'],
                 "Re-check pull request {0} at {1}: use the review-ticket skill. {r}, Re-checks. Open findings: {3}. "
                 "Changed since {2}: git diff {2} {1}; the builder's answer: {4}."),
    'fresh': ([REF, REF, r'room/[A-Za-z0-9._/-]+', SHA],
              'You are the fresh builder for {0}: one fresh round on pull request {1}, on its branch {2}, after '
              'the report at {3}. Use the build-ticket skill. {b}, its fresh round.'),
    'diagnose': ([], 'Use the diagnose skill. {d} for the finding.'),
    'fleet': ([N, REPO],
              'You are the fleet thread for spec {1}#{0}. Use the launch-fleet skill. {f}; do its Fleet threads '
              'section, first wake.'),
    'wake': ([N, REPO],
             'Fleet wake for spec {1}#{0}. Use the launch-fleet skill. {f}; do its Fleet threads section, Each wake.'),
    'tick': ([REPO, r'thr_[A-Za-z0-9_-]+'],
             "You are a launch-fleet tick for {0}. Use the launch-fleet skill. {f}; do its Each wake section for the "
             "due lines below. The orchestrator's thread is {1}."),
    'wakes': ([REPO, r'thr_[A-Za-z0-9_-]+'],
              "You are a launch-fleet tick for {0}, woken by GitHub's messages. Use the launch-fleet skill. {f}; do its "
              "Each wake section for the messages below. The orchestrator's thread is {1}."),
}

PASS_REPO = (" Every ticket and pull request above is written as OWNER/NAME#N: pass that OWNER/NAME with `--repo` on "
             "every `gh` command (in `gh api`, as the `repos/OWNER/NAME/` path), never your sandbox's own repository.")

REQUESTERS = {'builder': ('builder-{0}', None), 'fresh': ('builder-{0}', None), 'reviewer': ('reviewer-{0}', None),
              're-check': ('reviewer-{0}', None), 'diagnose': ('diagnose', None), 'fleet': ('fleet-{0}', '{1}'),
              'wake': ('fleet-{0}', '{1}'), 'tick': ('fleet-tick', '{0}'), 'wakes': ('fleet-tick', '{0}')}
TOKEN = (" GitHub token: run every gh or git command that reaches GitHub through the agent helper, the launch-fleet "
         "skill's `scripts/github-app/agent-token.py` (find launch-fleet's SKILL.md as above): first "
         "`env -u OPENWIZ_GITHUB_APP_KEY python3 -I <helper> start --requester {who} --repository {repo}`, then "
         "`env -u OPENWIZ_GITHUB_APP_KEY python3 -I <helper> run --requester {who} --repository {repo} -- <command>` "
         "for each command, with the same "
         "request every time and `--repository` once for each repository you read or write (all of one owner). Inside a run git "
         "reaches GitHub over HTTPS only, never SSH. The helper is your only App-token route: never run "
         "`openwiz github token`, the App-token block in launch-fleet's `references/identity.md`, or any command with "
         "`OPENWIZ_GITHUB_APP_KEY` in its environment. If it gets no token it says so once on stderr and runs the command as the owner's login: go on. "
         "Only these gh commands run through the helper: `gh api`, `gh cache`, `gh issue`, `gh label`, `gh pr`, "
         "`gh release`, `gh repo`, `gh run`, `gh search`, `gh status`, `gh workflow`; it stops any other gh command, "
         "so run that without the helper. Approvals, "
         "repository settings and pushes that change `.github/workflows/` stay on the owner's login: run those "
         "without the helper.")

SNAPSHOT = ("\n\nThe facts below were read from GitHub at {0}, in this wake's snapshot of {1} (a bare #N in them is "
            "{1}#N): read GitHub again only for anything newer.\n\n")
STAMP = r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z'


def snapshot_block(path, ref):
    repo, _, number = ref.partition('#')
    try:
        read_at = json.loads(Path(path).read_text())['read_at']
        r = subprocess.run([sys.executable, '-I', str(Path(__file__).resolve().parent / 'snapshot.py'), 'facts',
                            path, number], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    except (OSError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired):
        return ''
    if r.returncode or not isinstance(read_at, str) or not re.fullmatch(STAMP, read_at) \
            or not r.stdout.startswith('## %s: ' % ref):
        return ''
    return SNAPSHOT.format(read_at, repo) + r.stdout.rstrip('\n')


def token_step(kind, args):
    if not os.environ.get('OPENWIZ_TOKEN_SERVICE'):
        return ''
    who, repo = REQUESTERS[kind]
    args = [a.partition('#')[2] or a for a in args]
    return TOKEN.format(who=who.format(*args), repo=repo.format(*args) if repo else 'OWNER/NAME')


def main(argv):
    snapshot = None
    if len(argv) >= 2 and argv[-2] == '--snapshot':
        argv, snapshot = argv[:-2], argv[-1]
        if argv[:1] not in (['builder'], ['reviewer']) or not snapshot:
            return 2
    same_family = len(argv) == 4 and argv[0] == 'reviewer' and argv[3] == 'same-family'
    if same_family:
        argv = argv[:3]
    form = FORMS.get(argv[0]) if argv else None
    if form is None or len(argv) - 1 != len(form[0]) \
            or not all(re.fullmatch(p, a) for p, a in zip(form[0], argv[1:])):
        return 2
    clone = wizskills_clone_command()
    brief = form[1].format(*argv[1:], **{k: LOOKUP.format(s=s, clone=clone) for k, s in
                                     (('b', 'build-ticket'), ('r', 'review-ticket'), ('d', 'diagnose'),
                                      ('f', 'launch-fleet'))})
    if same_family:
        brief += ' Put "same-family review" on the line immediately below the VERDICT header.'
    brief += PASS_REPO + token_step(argv[0], argv[1:])
    print(brief + (snapshot_block(snapshot, argv[1]) if snapshot else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
