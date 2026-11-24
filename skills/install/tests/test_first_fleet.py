#!/usr/bin/env python3
"""Portable first-fleet journey from OpenWiz's synthetic onboarding suite.

Replay the conversation against the packaged install skill, its helper and
the real launch-fleet frontier. The fakes record external commands and refuse
anything outside the fixture; setup inputs are synthetic persisted records.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

SKILL_DIR = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / 'fixtures'
SKILL = SKILL_DIR / 'SKILL.md'
HELPER = SKILL_DIR / 'scripts/first_fleet.py'
FAKE_GH = FIXTURES / 'fake_gh.py'
REVISION = SKILL_DIR.parent / 'to-tickets/revision.sh'
JOURNEY = json.loads((FIXTURES / 'first-fleet.json').read_text())
NOW = 1793534400  # 2026-11-01T12:00:00Z, the synthetic clock fleet.sh reads
REPO = JOURNEY['repo']
CODEX = ('codex', 'syn-codex-model-01', 'high')
GRILL = 'https://github.com/synthetic-owner/synthetic-private/issues/1#issuecomment-71'
CLAUDE = ('claude-code', 'syn-claude-model-01', 'high')


def table(title, agent):
    return ('## %s\n\n| Setting | Value | `room-cli thread spawn` flag |\n| --- | --- | --- |\n'
            '| Harness | Synthetic | `--provider %s` |\n| Model | Synthetic | `--model %s` |\n'
            '| Effort | Synthetic | `--reasoning-level %s` |\n\nSource: synthetic.\n\n' % (title, *agent))


def fleet_md(builder=CODEX, small=CODEX, for_gpt=CLAUDE, for_claude=CODEX):
    return ('# Fleet settings\n\nSynthetic settings.\n\n' + table('Builder', builder)
            + table('Builder for small tickets', small) + table('Reviewer for Claude-built', for_claude)
            + table('Reviewer for GPT-built', for_gpt) + '## CI checks\n\n'
            '| Check | Runs | Required on |\n| --- | --- | --- |\n| `build` | 1 | `main` |\n\n'
            'Source: synthetic.\n\n## Standing merge rules\n\n'
            '| Pull request | Review | Merged by, and when |\n| --- | --- | --- |\n| `not-a-check` | none | synthetic |\n\n'
            '## GitHub identity\n\n| Setting | Value |\n| --- | --- |\n| Record authors | `synthetic-factory[bot]` |\n')


def models_md(orchestrator=CODEX, builder=CODEX, reviewer=CLAUDE, small=None, fixer=None):
    def row(role, agent):
        if agent is None:
            return '| %s | follows Builder | | | |\n' % role
        return '| %s | Synthetic | Synthetic | Synthetic | `--provider %s --model %s --reasoning-level %s` |\n' % (
            role, *agent)
    table = ('## Models\n\nSynthetic.\n\n| Role | Harness | Model | Effort | `room-cli thread spawn` flags |\n'
             '| --- | --- | --- | --- | --- |\n' + row('Orchestrator', orchestrator) + row('Builder', builder)
             + row('Reviewer', reviewer) + row('Small builder', small) + row('Fixer', fixer) + '\nSource: synthetic.\n\n')
    text = fleet_md()
    return text[:text.index('## Builder\n')] + table + text[text.index('## CI checks'):]


def connect_md():
    text = fleet_md().replace('## CI checks', '## Test commands\n\n| Command | Runs |\n| --- | --- |\n'
                              '| `make test` | synthetic |\n\nSource: synthetic.\n\n## CI checks', 1)
    rule = '| `not-a-check` | none | synthetic |\n\n'
    return text.replace(rule, rule + 'Source: synthetic.\n\n', 1)


CONNECT_CHECK = 'fleet_settings_usable of openwizdev/openwiz tools/install/setup/setup.py at 9039c57, copied as is'
def connect_sections(text):
    found, name = {}, None
    for line in text.split('\n'):
        if line.startswith('## '):
            name = line[3:].strip()
            found.setdefault(name, [])
        elif name is not None:
            found[name].append(line)
    return found


def connect_table(lines):
    rows = [line.strip() for line in lines if line.strip().startswith('|')]
    if len(rows) < 2 or not re.fullmatch(r'\|(\s*:?-{3,}:?\s*\|)+', rows[1]):
        return []
    split = lambda row: [cell.strip() for cell in row.strip('|').split('|')]
    header = split(rows[0])
    return [dict(zip(header, split(row))) for row in rows[2:] if len(split(row)) == len(header)]


CONNECT_PLACEHOLDER = re.compile(r'<[A-Za-z][^<>\n]*>')
CONNECT_HEADER = ['Role', 'Harness', 'Model', 'Effort', '`room-cli thread spawn` flags']
CONNECT_ID = r'[A-Za-z0-9._-]+'
CONNECT_FLAGS = re.compile(r'`--provider %s --model %s(?:/%s)* --reasoning-level %s`' % ((CONNECT_ID,) * 4))


def connect_models_usable(text, body):
    if sum(line.startswith('## ') and line[3:].strip() == 'Models' for line in text.split('\n')) != 1:
        return False
    rows = []
    for line in body:
        if line.startswith('|'):
            rows.append([cell.strip() for cell in line.strip()[1:-1].split('|')] if line.strip().endswith('|') else None)
        elif rows:
            break
    if len(rows) < 2 or rows[0] != CONNECT_HEADER or rows[1] != ['---'] * 5 or None in rows:
        return False
    names = [row[0] if len(row) == 5 else None for row in rows[2:]]
    if names[:3] != ['Orchestrator', 'Builder', 'Reviewer'] or names[3:] not in (
            [], ['Small builder'], ['Fixer'], ['Small builder', 'Fixer']):
        return False
    for role, harness, model, effort, flags in rows[2:]:
        if harness == 'follows Builder':
            if role not in ('Small builder', 'Fixer') or model or effort or flags:
                return False
            continue
        if not (harness and model and effort) or not CONNECT_FLAGS.fullmatch(flags):
            return False
    return True


def connect_usable(text):
    found = connect_sections(text)
    reviewers = [name for name in found if name.startswith('Reviewer')]
    builders = [name for name in found if name.startswith('Builder')]
    needed = ['Test commands', 'CI checks', 'Standing merge rules']
    if 'Models' in found:
        if not connect_models_usable(text, found['Models']):
            return False
        needed.insert(0, 'Models')
        builders = reviewers = []
    elif not reviewers:
        return False
    else:
        needed.insert(0, 'Builder')
    if not all(name in found for name in needed):
        return False
    for name in needed + builders + reviewers:
        body = found[name]
        if any(CONNECT_PLACEHOLDER.search(line) for line in body):
            return False
        if not any(line.startswith('Source: ') and len(line) > len('Source: ') for line in body):
            return False
    for name in builders + reviewers:
        values = {row.get('Setting'): row.get('Value', '') for row in connect_table(found[name])}
        if not all(values.get(key) for key in ('Harness', 'Model', 'Effort')):
            return False
    if not any(row.get('Command', '').strip('`') for row in connect_table(found['Test commands'])):
        return False
    if not any(row.get('Check', '').strip('`') for row in connect_table(found['CI checks'])):
        return False
    merge = connect_table(found['Standing merge rules'])
    rows = [row for row in merge if all(cell.strip() for cell in row.values())]
    waits = any(line.strip() == 'None yet: every merge waits for the user.' for line in found['Standing merge rules'])
    return bool(rows) or waits


SETTINGS = SKILL_DIR.parent / 'setup/scripts/settings.py'
TICKET_FIELDS = 'number,state,stateReason,closedByPullRequestsReferences,blockedBy,comments'
OPUS = ('claude-code', 'claude-opus-5-5', 'medium')
SOL = ('codex', 'gpt-6.2-sol', 'medium')


def offering(*agents):
    options = json.loads(json.dumps(JOURNEY['options']))
    for provider, model, effort in agents:
        harness = next(h for h in options['harnesses'] if h['provider'] == provider)
        harness['models'].append({'model': model, 'efforts': [effort]})
    return options


FILES = {
    'docs/agents/fleet.md': fleet_md(),
    'docs/agents/triage-labels.md': (
        '# Triage labels\n\n## Labels\n\n| Role | Label here | Meaning |\n| --- | --- | --- |\n'
        '| `needs-triage` | `needs-triage` | Synthetic |\n| `needs-info` | `needs-info` | Synthetic |\n'
        '| `ready-for-agent` | `ready-for-agent` | Synthetic |\n| `ready-for-human` | `ready-for-human` | Synthetic |\n'
        '| `wontfix` | `wontfix` | Synthetic |\n'),
}


def skill_steps():
    """The journey's step names, in order, from the packaged skill's numbered sections."""
    explain, _, branch = SKILL.read_text().partition('## 6. The onboarding road\n')
    names = re.findall(r'^## 5\. (Teach)$', explain, re.M)
    names.extend(re.findall(r'^### [0-9]+\. (.+)$', branch.partition('\n## ')[0], re.M))
    return [name.split()[-1].lower() for name in names]


def answers(turns):
    out = {}
    for turn in turns:
        out.update(turn.get('answers', {}))
    return out


def setup_state(identity='personal_login', brain='in_repository', overrides=None, revision=3, at=None,
                repository=REPO, settings=CODEX):
    """Synthetic setup record with the fields emitted for this selection."""
    at = int(time.time() * 1000) if at is None else at
    value = {'schema': 'openwiz.setup-state.v1', 'revision': revision,
             'checks': {'started': 4, 'committed': 4}, 'app': None, 'operations': []}
    value['project'] = {'repository': repository, 'project': 'prj_synthetic', 'operator': 'synthetic-owner',
                        'service_issue': 7, 'answer_thread': 'thr_synthetic_answer', 'harness': settings[0],
                        'model': settings[1], 'effort': settings[2], 'runtime': None}
    codes = {'cloudroom': 'cloudroom_login_verified', 'harness': 'harness_listed',
             'personal_github': 'identity_verified', 'project': 'project_verified', 'github_app': 'app_missing'}
    if identity == 'personal_login':
        value['identity'] = {'selected': 'personal_login', 'app_choice': 'skip', 'acting_login': 'synthetic-owner',
                             'repository': repository}
    elif identity == 'app':
        value['identity'] = {'selected': 'app', 'app_choice': 'create', 'acting_login': None, 'repository': repository}
        codes['github_app'] = 'app_verified'
    codes.update(overrides or {})
    value['observations'] = {k: {'code': c, 'revision': revision, 'at': at} for k, c in codes.items() if c}
    if brain == 'in_repository':
        value['brain'] = {'location': 'in_repository', 'code_repository': repository, 'code_visibility': 'private',
                          'brain_repository': repository, 'brain_visibility': {'known': 'private'},
                          'visibility_basis': 'github_repository_read', 'folder': '.openwiz/brain',
                          'setting': 'brain_location', 'decision_repositories': None}
    elif brain == 'companion':
        home = repository + '-brain'
        value['brain'] = {'location': 'companion', 'code_repository': repository, 'code_visibility': 'public',
                          'brain_repository': home, 'brain_visibility': {'known': 'private'},
                          'visibility_basis': 'github_repository_read', 'folder': '.openwiz/brain',
                          'setting': 'brain_location',
                          'decision_repositories': {'public': dict(zip(('owner', 'name'), repository.split('/'))),
                                                    'private': dict(zip(('owner', 'name'), home.split('/')))}}
    elif brain == 'other':
        value['brain'] = dict(setup_state(brain='in_repository', repository='synthetic-owner/synthetic-other')['brain'])
    return value


def demo_repository(name=REPO, visibility='private', branches=None):
    """One repository in the synthetic GitHub world."""
    owner, short = name.split('/')
    return {'full_name': name, 'private': visibility == 'private', 'visibility': visibility, 'default_branch': 'main',
            'permissions': {'push': True}, 'owner': {'login': owner, 'type': 'User'}, 'description': None,
            'homepage': None, 'labels': [], 'pulls': [], 'branches': branches or {}}


def github(repos=(), **switches):
    """Synthetic GitHub state for the demo repository."""
    world = {'user': {'login': 'synthetic-owner', 'type': 'User'}, 'faults': [], 'log': [], 'create': 'ok',
             'repos': {r['full_name'].lower(): r for r in repos}}
    world.update(switches)
    return json.dumps(world)


SEEDED = ('PUT', 'repos/%s/contents/tests/test_check.py' % REPO), \
    ('PUT', 'repos/%s/contents/.github/workflows/check.yml' % REPO)


class Journey:
    """One replay: a private folder with its state, fakes and synthetic GitHub."""

    def __init__(self, case):
        self.dir = Path(tempfile.mkdtemp(prefix='onboard-'))
        case.addCleanup(shutil.rmtree, self.dir, True)
        (self.dir / 'bin').mkdir()
        (self.dir / 'private').mkdir(mode=0o700)
        self.state = self.dir / 'private/onboard.json'
        self.options = self.dir / 'private/models.json'
        self.options.write_text(json.dumps(JOURNEY['options']))
        self.setup_dir = self.dir / 'openwiz-state'
        self.world_path = self.dir / 'world.json'
        self.script = self.dir / 'openwiz-script.json'
        self.log = self.dir / 'openwiz.log'
        self.room_script = self.dir / 'room-script.json'
        self.room_log = self.dir / 'room.log'
        self.openwiz = self.dir / 'bin/openwiz'
        self.openwiz.write_text('#!/bin/sh\nexec "%s" -I "%s" "$@"\n' % (sys.executable, FIXTURES / 'fake_openwiz.py'))
        gh = self.dir / 'bin/gh'
        gh.write_text('#!/bin/sh\nexec "%s" -I -S "%s" "$@"\n' % (sys.executable, FAKE_GH))
        room = self.dir / 'bin/room-cli'
        room.write_text('#!/bin/sh\nexec "%s" -I "%s" "$@"\n' % (sys.executable, FIXTURES / 'fake_room_cli.py'))
        self.repos = self.dir / 'repos.json'
        self.repos.write_text(github())
        self.created_log = self.dir / 'gh-create.log'
        for path in (self.openwiz, gh, room):
            path.chmod(0o755)
        self.world = {'repo': JOURNEY['repo'], 'default': 'main', 'files': dict(FILES), 'issues': [], 'pulls': []}
        # The project checkout the helper runs in, and its origin: launch-fleet's host.py reads
        # docs/agents/host.md from origin's default branch (records v1, section 6).
        self.origin = self.dir / 'origin.git'
        self.git('init', '-q', '--bare', '-b', 'main', str(self.origin))
        self.git('init', '-q', '-b', 'main', str(self.dir))
        self.git('-C', str(self.dir), 'remote', 'add', 'origin', str(self.origin))
        self.origin_write({'README.md': '# synthetic\n'})
        self.checkout = self.dir / 'docs/agents/fleet.md'
        self.checkout.parent.mkdir(parents=True)
        self.checkout.write_text(FILES['docs/agents/fleet.md'])
        self.save_world()
        self.room_script.write_text('{}')
        self.approval = None
        self.calls = []
        self.extra_env = {}
        said = answers(JOURNEY['turns'])
        self.settings = {k: said[k] for k in ('harness', 'model', 'effort')}

    def git(self, *args):
        return subprocess.run(['git', '-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid', *args],
                              check=True, capture_output=True, timeout=60)

    def origin_write(self, files):
        """One commit on origin's default branch writing these files, as a merge there would."""
        work = Path(tempfile.mkdtemp(prefix='origin-', dir=self.dir))
        self.git('clone', '-q', str(self.origin), str(work))
        for name, text in files.items():
            (work / name).parent.mkdir(parents=True, exist_ok=True)
            (work / name).write_text(text)
        self.git('-C', str(work), 'add', '-A')
        self.git('-C', str(work), 'commit', '-q', '-m', 'synthetic')
        self.git('-C', str(work), 'push', '-q', 'origin', 'HEAD:main')
        shutil.rmtree(work)

    def env(self):
        env = {k: v for k, v in os.environ.items() if k in ('HOME', 'LANG', 'LC_ALL', 'TMPDIR')}
        env.update(PATH='%s:/usr/bin:/bin' % (self.dir / 'bin'), GH_REPO=self.world['repo'],
                   FAKE_GH_WORLD=str(self.world_path), FAKE_GH_LOG=str(self.dir / 'gh.log'),
                   LAUNCH_FLEET_NOW=str(NOW), LAUNCH_FLEET_CACHE=str(self.dir / 'cache'),
                   FAKE_OPENWIZ_SCRIPT=str(self.script), FAKE_OPENWIZ_LOG=str(self.log),
                   FAKE_ROOM_SCRIPT=str(self.room_script), FAKE_ROOM_LOG=str(self.room_log),
                   FAKE_GH_REPOS=str(self.repos), FAKE_GH_CREATE_LOG=str(self.created_log), **self.extra_env)
        env.update(runpy.run_path(str(SKILL_DIR.parent / 'launch-fleet/scripts/fixtures/git_origin.py'))['env'](self.dir, {self.world['repo']: self.world['files'].get('docs/agents/fleet.md')}))
        return env

    def save_world(self):
        self.world_path.write_text(json.dumps(self.world))

    def write_setup(self, value):
        folder = self.setup_dir / 'setup'
        folder.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.setup_dir.chmod(0o700)
        path = folder / 'state.json'
        path.write_text(json.dumps(value))
        path.chmod(0o600)

    def write_config(self, value):
        """The private service settings (service/config.json) beside the setup store."""
        folder = self.setup_dir / 'service'
        folder.mkdir(parents=True, mode=0o700, exist_ok=True)
        (folder / 'config.json').write_text(json.dumps(value))
        (folder / 'config.json').chmod(0o600)

    def plan(self, plan):
        spec = plan['spec']
        self.spec = spec['number']
        self.tickets = plan['tickets']
        self.world['issues'] = [{'number': spec['number'], 'title': spec['title'], 'state': 'OPEN', 'parent': None,
                                 'labels': [], 'body': spec['body'], 'comments': []}]
        for t in plan['tickets']:
            self.world['issues'].append({
                'number': t['number'], 'title': t['title'], 'state': 'OPEN', 'parent': spec['number'],
                'labels': ['ready-for-agent'], 'blockedBy': t['blockers'],
                'body': '## What to build\n\n%s.\n' % t['title'], 'comments': []})
        self.save_world()

    def approve(self, spec=None, tickets=None, comment=90001, grill=GRILL, human=False):
        """to-tickets's machine plan approval (decisions.v1) of this grill, or an older human approval record,
        with the fingerprint revision.sh gives the plan now."""
        spec, tickets = spec or self.spec, tickets or self.tickets
        out = subprocess.run(['sh', str(REVISION), str(spec)], env=self.env(), capture_output=True, check=True)
        fingerprint = hashlib.sha256(out.stdout).hexdigest()
        rows = '\n'.join('| #%d | %s | %s | ready-for-agent |' % (
            t['number'], t['title'], ' '.join('#%d' % b for b in sorted(t['blockers'])) or 'none')
            for t in sorted(tickets, key=lambda t: t['number']))
        if human:
            body = ('**Plan graph approved by Robin, 2026-11-01, revision 1:** approved the synthetic plan.\n'
                    'Private record: https://github.com/synthetic-owner/synthetic-private/issues/1#issuecomment-1\n\n'
                    '| Ticket | Title | Blocked by | Label |\n| --- | --- | --- | --- |\n%s\n\n'
                    'Fingerprint: `%s`\n' % (rows, fingerprint))
        else:  # to-tickets' approve.py layout, read whole by launch-fleet (#1340)
            n = len(tickets)
            body = ('**Machine plan approval, 2026-11-01, revision 1:** links, relies, sizes, width and owned paths '
                    'passed.\nGrill confirmed: %s\n\nChecks: %d tickets; links 0; relies 0; sizes S %d, M 0, L 0; '
                    'width: chain 1, widest %d; owned paths %d.\n\n| Ticket | Title | Blocked by | Label |\n'
                    '| --- | --- | --- | --- |\n%s\n\nFingerprint: `%s`\n\n<details><summary>Revision text</summary>'
                    '\n\n```text\n%s```\n\n</details>\n' % (grill, n, n, n, n, rows, fingerprint,
                                                         out.stdout.decode()))
        issue = next(i for i in self.world['issues'] if i['number'] == spec)
        issue['comments'].append({'id': comment, 'at': '2026-11-01T10:00:00Z', 'body': body})
        if spec == self.spec:
            self.approval = {'comment': comment, 'revision': 1, 'fingerprint': fingerprint}
        self.save_world()

    def fleet_record(self):
        """The fleet thread's first-wake record on the spec, as launch-fleet writes it."""
        self.world['issues'][0]['comments'].append(
            {'id': 90002, 'at': '2026-11-01T12:05:00Z', 'body': 'launch-fleet: fleet active, loop fleet-%d' % self.spec})
        self.save_world()

    def fleet_view(self, states):
        counts = {k: 0 for k in ('ready', 'building', 'in_review', 'changes_requested', 'merged', 'held', 'blocked')}
        for s in states:
            counts[s] += 1
        counts.update(tickets=len(states), unknown=0)
        return {'schema': 'openwiz.fleet.v1', 'sources': {}, 'reads': [], 'coverage': {}, 'freshness': {},
                'data': {'view': 'fleet', 'repository': 'r0', 'projects': 'r1', 'threads': 'r2',
                         'fleet': {'spec': self.spec, 'issue': 'r3', 'tickets': 'r4', 'progress': {'known': counts}},
                         'tickets': [{'number': t['number'], 'state': {'known': s}} for t, s in zip(self.tickets, states)],
                         'blockers': [], 'needs_you': {'known': []}, 'unplaced': {'known': []}}}

    def queue(self, script):
        """The installed openwiz's next answers (its fleet view)."""
        self.script.write_text(json.dumps(script))

    def rules(self):
        """The builder and reviewer tables of the world's fleet settings, as the launch reads them."""
        text = self.world['files']['docs/agents/fleet.md']
        found = {}
        for title, key in (('Builder', 'builder'), ('Builder for small tickets', 'builder_small'),
                           ('Reviewer for Claude-built', 'reviewer_claude'), ('Reviewer for GPT-built', 'reviewer_gpt')):
            body = text.split('## %s\n' % title, 1)[1].split('\n## ', 1)[0]
            found[key] = {k: re.search(r'`--%s ([^`\s]+)`' % f, body)[1]
                          for k, f in (('harness', 'provider'), ('model', 'model'), ('effort', 'reasoning-level'))}
        return found

    def helper(self, args):
        argv = [sys.executable, '-I', str(HELPER), *args, '--state', str(self.state)]
        if args[0] in ('continue', 'decisions'):
            argv += ['--setup-state', str(self.setup_dir)]
        if args[0] == 'choose':
            argv += ['--options', str(self.options)]
        if args[0] == 'progress':
            argv += ['--openwiz', str(self.openwiz)]
        result = subprocess.run(argv, env=self.env(), capture_output=True, text=True, cwd=self.dir, timeout=120)
        self.calls.append((args, result))
        return result

    def gh_creates(self):
        """The creation and read-back calls, as the fake gh logged them."""
        if not self.created_log.exists():
            return []
        return [json.loads(line)[:2] for line in self.created_log.read_text().splitlines()]

    def logged(self):
        """Every installed openwiz call, as the fake logged it."""
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def spawns(self):
        """Every room-cli call, as the fake logged it."""
        if not self.room_log.exists():
            return []
        return [json.loads(line) for line in self.room_log.read_text().splitlines()]

    def confirmation(self):
        """The confirmation the latest preview printed: what the user said yes to."""
        for args, result in reversed(self.calls):
            found = re.findall(r'^Confirmation: ([0-9a-f]{64})$', result.stdout, re.M)
            if found:
                return found[-1]
        return '0' * 64

    def tool(self, turn):
        """Run one recorded tool step, answering the fakes as the turn records."""
        args = [self.confirmation() if a == '@preview' else a for a in turn['tool']]
        self.queue({'fleet': [{'exit': 0, 'stdout': self.fleet_view(turn['progress'])}]} if 'progress' in turn else {})
        self.room_script.write_text(json.dumps(
            {'spawn': [{'exit': turn['spawn'], 'stdout': ''}]} if 'spawn' in turn else {}))
        return self.helper(args)

    def replay(self, until=None):
        """Every turn of the recorded journey, in order, up to step `until` (exclusive)."""
        results = []
        for turn in JOURNEY['turns']:
            if until is not None and turn['step'] == until:
                break
            if 'plan' in turn:
                self.plan(turn['plan'])
            elif turn.get('approve'):
                self.approve()
            elif turn.get('world') == 'fleet_record':
                self.fleet_record()  # launch-fleet's own start path, read back (R7)
            elif 'setup' in turn:
                self.write_setup(setup_state(turn['setup'], repository=JOURNEY['repo'],
                                             settings=tuple(self.settings[k] for k in ('harness', 'model', 'effort'))))
            elif 'tool' in turn:
                results.append((turn, self.tool(turn)))
        return results


PREVIEW = {'tool': ['launch', '--spec', '900']}
YES = {'tool': ['launch', '--spec', '900', '--yes', '--confirm', '@preview']}


class RecordedJourney(unittest.TestCase):
    def test_the_conversation_follows_the_packaged_skill(self):
        steps = skill_steps()
        self.assertEqual(steps, ['teach', 'run', 'start', 'connect', 'grill', 'agents', 'setting', 'plan', 'launch',
                                 'watch'])
        seen = [turn['step'] for turn in JOURNEY['turns']]
        self.assertEqual(sorted(set(seen), key=steps.index), steps, 'every step, and only the skill\'s')
        self.assertEqual(seen, sorted(seen, key=steps.index), 'in the skill\'s order')

    def test_every_effect_follows_its_yes_and_every_choice_is_the_users_once(self):
        # #636: the harness, model and effort answered during setup are reused,
        # never asked twice; the agent location is its own answer.
        turns = JOURNEY['turns']
        permitted, asked = set(), []
        for i, turn in enumerate(turns):
            permitted |= set(turn.get('permits', []))
            asked += list(turn.get('answers', {}))
            if turn.get('tool', [None])[0] == 'create-repo' and '--yes' in turn['tool']:
                self.assertIn('create_repository', permitted, 'repository created only after a yes')
            if turn.get('tool', [None])[0] == 'where' and '--yes' in turn['tool']:
                self.assertIn('spend_cloud_credits', permitted, 'what Cloudroom spends is answered before it is recorded')
                self.assertEqual(turn['tool'][2], answers(turns[:i])['agents'])
            if turn.get('tool', [None])[:2] == ['launch', '--spec'] and '--yes' in turn['tool']:
                self.assertIn('start_fleet', permitted, 'the fleet starts only after its own yes (ruling 7029073685)')
                self.assertEqual(turns[i - 1].get('permits'), ['start_fleet'], 'the yes comes right before the start')
            if turn.get('tool', [None])[0] == 'choose':
                self.assertEqual(turn['tool'], ['choose', '--from-setup'])
        self.assertEqual(len(asked), len(set(asked)), 'no choice is asked twice')
        self.assertEqual(answers(turns)['agents'], 'cloud')
        self.assertNotIn('engine', json.dumps(turns).lower(), 'no engine question or effect')

    def test_the_plan_is_this_grills_small_first_fleet(self):
        plan = next(t['plan'] for t in JOURNEY['turns'] if 'plan' in t)
        self.assertTrue(4 <= len(plan['tickets']) <= 7)
        start = [t['number'] for t in plan['tickets'] if not t['blockers']]
        self.assertGreaterEqual(len(start), 2, 'several start at once')
        # No prewritten plan ships with the skill: none of this plan's titles,
        # and no ticket table, appear anywhere in the skill's runtime material.
        packaged = ''.join(path.read_text() for path in SKILL_DIR.rglob('*')
                           if path.is_file() and path.suffix in {'.md', '.py', '.yaml'}
                           and path.relative_to(SKILL_DIR).parts[0] not in {'tests', 'evidence'})
        for ticket in plan['tickets']:
            self.assertNotIn(ticket['title'].split(': ', 1)[1], packaged)
        self.assertNotIn('| Ticket |', packaged)


class HostAwareSetup(unittest.TestCase):
    def test_driver_setup_carries_without_cloudroom_and_keeps_github_and_harness_gates(self):
        cases = (
            ('local', 'local', 'harness_listed', 'project_verified', 0, 'agents on local'),
            ('boat', 'boat', 'harness_listed', 'project_verified', 0, 'agents on boat'),
            ('syn-driver-2', 'syn-driver-2', 'harness_listed', 'project_verified', 0, 'agents on syn-driver-2'),
            ('local', 'local', 'harness_not_installed', 'project_verified', 5, 'harness_not_installed'),
            ('local', 'local', 'harness_listed', 'project_no_write', 5, 'project_no_write'),
            ('local', 'boat', 'harness_listed', 'project_verified', 5, 'host boat'),
        )
        for picked, prepared, harness, project, code, message in cases:
            with self.subTest(picked=picked, prepared=prepared, harness=harness, project=project):
                j = Journey(self)
                (j.dir / 'bin/room-cli').unlink()
                repo = 'synthetic-owner/synthetic-repo'
                choice = SOL if prepared == 'boat' else OPUS
                state = setup_state(repository=repo, settings=choice, overrides={
                    'cloudroom': 'cloudroom_not_needed', 'harness': harness, 'project': project})
                state['project'].update(host=prepared, project=None, answer_thread=None, operator='Synthetic Operator')
                j.write_setup(state)
                j.state.write_text(json.dumps({
                    'repo': repo, 'host': {'agents': picked, 'harnesses': []}}))
                j.state.chmod(0o600)
                self.assertIsNone(shutil.which('room-cli', path=j.env()['PATH']))
                result = j.helper(['continue', '--explained'])
                self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                self.assertIn(message, result.stdout)
                self.assertNotIn('CloudRoom project', result.stdout)
                self.assertEqual('setup' in json.loads(j.state.read_text()), code == 0)

    def test_choose_reads_nc1_local_options_and_refuses_cloudroom_fallback(self):
        j = Journey(self)
        (j.dir / 'bin/room-cli').unlink()
        state = setup_state(settings=OPUS, overrides={'cloudroom': 'cloudroom_not_needed'})
        state['project'].update(host='local', project=None, answer_thread=None)
        j.write_setup(state)
        j.state.write_text(json.dumps({
            'repo': REPO, 'host': {'agents': 'local', 'harnesses': ['claude-code']},
            'setup': {'host': 'local', 'settings': dict(zip(('harness', 'model', 'effort'), OPUS))}}))
        j.state.chmod(0o600)
        options = offering(OPUS, SOL)
        j.options.write_text(json.dumps(options))
        refused = j.helper(['choose', '--from-setup'])
        self.assertEqual(refused.returncode, 5, refused.stdout + refused.stderr)
        self.assertIn('models --json --host local', refused.stdout)
        self.assertNotIn('choices', json.loads(j.state.read_text()))
        options['source'] = 'local'
        j.options.write_text(json.dumps(options))
        picked = j.helper(['choose', '--from-setup'])
        self.assertEqual(picked.returncode, 0, picked.stdout + picked.stderr)
        self.assertEqual(json.loads(j.state.read_text())['choices']['model'], OPUS[1])

    def test_a_codex_only_machine_records_its_choice_and_leaves_the_review_same_family(self):
        j = Journey(self)
        j.replay(until='agents')
        state = json.loads(j.state.read_text())
        state['host'] = {'agents': 'local', 'harnesses': ['codex']}
        state['setup']['settings'] = dict(zip(('harness', 'model', 'effort'), SOL))
        j.state.write_text(json.dumps(state))
        options = offering(SOL)
        options['harnesses'] = [h for h in options['harnesses'] if h['provider'] == 'codex']
        options['source'] = 'local'
        j.options.write_text(json.dumps(options))
        j.checkout.write_text(models_md(orchestrator=OPUS, builder=OPUS, reviewer=SOL))
        result = j.helper(['choose', '--from-setup'])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(j.state.read_text())['choices']['model'], SOL[1])
        self.assertEqual(ModelsTable.models(self, j.checkout.read_text())['Reviewer'], OPUS,
                         'the table keeps a valid other-family Reviewer')
        self.assertIn('same-family review', result.stdout)

    def test_install_passes_the_chosen_host_to_models_and_follows_the_driver_handoff(self):
        text = SKILL.read_text()
        for step in ('### 3. Connect', '### 5. Agents'):
            section = text.split(step, 1)[1].split('\n### ', 1)[0]
            self.assertIn('models --json --host <its name>', section)
        launch = text.split('### 8. Launch', 1)[1].split('\n### ', 1)[0]
        self.assertIn('heartbeat', launch)
        self.assertIn('Starting one', launch)


class ConnectIdentity(unittest.TestCase):
    def step(self):
        connect = SKILL.read_text().split('### 3. Connect', 1)[1].split('\n### ', 1)[0]
        found = re.search(r'^3\. .*?(?=^[0-9]+\. )', connect, re.M | re.S)
        self.assertIsNotNone(found, 'Connect has a step 3')
        return found[0]

    def branch(self, step, label):
        found = re.search(r'^   - \*\*%s:\*\* (.+)$' % re.escape(label), step, re.M)
        self.assertIsNotNone(found, 'step 3 has a %r branch' % label)
        return found[1]

    def test_every_host_gets_the_personal_login_and_no_cloudroom_step(self):
        other = self.branch(self.step(), 'On every host, for the first fleet')
        self.assertRegex(other, r'^recommend the personal GitHub login')
        self.assertIn('`github_login.py skip-app`', other)
        for cloudroom_step in ('--agent-for', 'secret', '"The App"', 'runtime/github-app/setup.py'):
            self.assertNotIn(cloudroom_step, other)

    def test_the_app_is_offered_and_only_an_answer_selects_the_skip(self):
        step = self.step()
        offered = self.branch(step, 'The App, offered instead')
        self.assertIn('`--app`', offered)
        self.assertIn('set up with the installed `"$build"/runtime/github-app/setup.py` as the `setup` skill\'s '
                      '"The App" says', offered)
        self.assertIn('the App needs CloudRoom today', offered)
        self.assertNotIn('recommend the App', step)
        self.assertIn("Only the user's answer selects `github_login.py skip-app`; an App failure never becomes a skip.",
                      step)


class Continuation(unittest.TestCase):
    """#636: onboarding continues from install's verified setup and init, never
    from a guess. Catches a fabricated, stale or unselected identity or brain
    being carried into the first fleet."""

    def carried(self, state):
        j = Journey(self)
        if state is not None:
            j.write_setup(state)
        return j, j.helper(['continue', '--explained'])

    def test_only_current_verified_setup_and_a_brain_are_carried(self):
        stale = int(time.time() * 1000) - 2 * 60 * 60 * 1000
        app_unverified = setup_state('app', overrides={'github_app': 'app_missing'})
        old_generation = setup_state()
        old_generation['observations']['personal_github']['revision'] = 2
        cases = {
            'no setup yet': (None, 5, 'Setup has not run'),
            'no project prepared': (dict(setup_state(), project=None, identity=None, brain=None), 5, 'no prepared project'),
            'login not verified': (setup_state(overrides={'personal_github': 'identity_no_push'}), 5,
                                   'Personal GitHub: not verified (identity_no_push)'),
            'login checked for another selection': (old_generation, 5, 'Personal GitHub: unknown'),
            'every check out of date': (setup_state(at=stale), 5, 'CloudRoom: unknown'),
            'App chosen but not verified': (app_unverified, 5, 'OpenWiz GitHub App: not verified (app_missing)'),
            'no identity choice: the App rule': (setup_state(identity=None), 5, 'OpenWiz GitHub App'),
            'no brain': (setup_state(brain=None), 5, 'Private brain: missing (run openwiz init'),
            'a brain for another repository': (setup_state(brain='other'), 5, 'Private brain: missing'),
            'harness refused': (setup_state(overrides={'harness': 'harness_unavailable'}), 5, 'Agent harness'),
            'unreadable store': ('{"schema": "openwiz.setup-state.v1", "revision": 1, "revision": 2}', 10, 'unreadable'),
            'a project without its CloudRoom project': (json.dumps(dict(setup_state(), project=dict(
                setup_state()['project'], project=None))), 10, 'unreadable'),
        }
        for name, (state, code, words) in cases.items():
            with self.subTest(name):
                j = Journey(self)
                if isinstance(state, str):
                    j.write_setup({})
                    (j.setup_dir / 'setup/state.json').write_text(state)
                elif state is not None:
                    j.write_setup(state)
                result = j.helper(['continue'])
                self.assertEqual(result.returncode, code, result.stdout)
                self.assertIn(words, result.stdout)
                self.assertIn('nothing started', result.stdout)
                self.assertFalse(j.state.exists() and 'setup' in json.loads(j.state.read_text()), 'nothing carried')

    def test_both_identities_carry_the_same_repository_brain_and_settings(self):
        for identity, acting in (('personal_login', 'synthetic-owner, your personal GitHub login (the App is skipped)'),
                                 ('app', 'your OpenWiz GitHub App')):
            with self.subTest(identity):
                j, result = self.carried(setup_state(identity))
                self.assertEqual(result.returncode, 0, result.stdout)
                for line in ('repository %s, CloudRoom project prj_synthetic' % REPO, 'Acting identity: %s.' % acting,
                             'Private brain: %s (in repository)' % REPO, 'harness listed by CloudRoom; its login is not proven',
                             'Next: the grill (the explanation is done)'):
                    self.assertIn(line, result.stdout)
                saved = json.loads(j.state.read_text())
                self.assertEqual((saved['repo'], saved['setup']['settings']),
                                 (REPO, {'harness': 'codex', 'model': 'syn-codex-model-01', 'effort': 'high'}))

    def test_the_carried_repository_is_the_only_one(self):
        j, result = self.carried(setup_state())
        self.assertEqual(result.returncode, 0, result.stdout)
        other = 'synthetic-owner/synthetic-other'
        self.assertEqual(j.helper(['create-repo', '--repo', other, '--yes']).returncode, 5)
        self.assertEqual(j.helper(['spec', '--spec', '900', '--repo', other]).returncode, 5)
        self.assertEqual(j.gh_creates(), [], 'no second repository is read or created')
        j.write_setup(setup_state(repository=other))
        moved = j.helper(['continue'])
        self.assertEqual(moved.returncode, 5, moved.stdout)
        self.assertIn('setup selected %s' % other, moved.stdout)

    def test_a_failed_refresh_withdraws_the_carried_setup_but_keeps_the_choices(self):
        # Review R4: catches an old carried setup staying eligible after setup refuses.
        j, result = self.carried(setup_state())
        self.assertEqual(j.helper(['where', '--agents', 'cloud', '--yes']).returncode, 0)
        self.assertEqual(j.helper(['choose', '--from-setup']).returncode, 0)
        j.write_setup(setup_state(overrides={'personal_github': 'identity_no_push'}))
        refused = j.helper(['continue'])
        self.assertEqual(refused.returncode, 5, refused.stdout)
        saved = json.loads(j.state.read_text())
        self.assertNotIn('setup', saved, 'the refused refresh withdraws the carried setup')
        self.assertEqual(saved['choices']['agents'], 'cloud', "the owner's choices stay")

    def test_a_companion_brain_reaches_decisions_only_through_its_configured_pair(self):
        # Review R5: catches a public repository's private companion carried while
        # Decisions' existing repository-pair setting (service/config.json) does not name it.
        pair = setup_state(brain='companion')['brain']['decision_repositories']
        for name, config, code in (('no settings file', None, 5),
                                   ('another pair', {'decision_repositories': {'public': pair['public'],
                                                     'private': {'owner': 'synthetic-owner', 'name': 'elsewhere'}}}, 5),
                                   ('the companion pair', {'decision_repositories': pair}, 0)):
            with self.subTest(name):
                j = Journey(self)
                j.write_setup(setup_state(brain='companion'))
                if config is not None:
                    j.write_config(config)
                result = j.helper(['continue'])
                self.assertEqual(result.returncode, code, result.stdout)
                if code:
                    self.assertIn('Decisions repository pair', result.stdout)
                else:
                    self.assertIn('Private brain: %s-brain (companion)' % REPO, result.stdout)

    def test_the_decisions_pair_is_written_once_and_only_on_yes(self):
        # Review R5 (ruling: option A): catches a writer that changes or drops
        # another settings key, writes on a preview, or rewrites on a second run.
        pair = setup_state(brain='companion')['brain']['decision_repositories']
        for name, existing in (('no settings file', None),
                               ('an existing settings file', {'schema': 'synthetic', 'server': {'port': 7370},
                                                              'decision_repositories': {'public': pair['public'],
                                                              'private': {'owner': 'synthetic-owner', 'name': 'old'}}})):
            with self.subTest(name):
                j = Journey(self)
                j.write_setup(setup_state(brain='companion'))
                path = j.setup_dir / 'service/config.json'
                if existing is not None:
                    j.write_config(existing)
                before = path.read_bytes() if path.exists() else None
                shown = j.helper(['decisions'])
                self.assertEqual(shown.returncode, 12, shown.stdout)
                self.assertIn('public %s, private %s-brain' % (REPO, REPO), shown.stdout)
                self.assertEqual(path.read_bytes() if path.exists() else None, before, 'a preview writes nothing')
                done = j.helper(['decisions', '--yes'])
                self.assertEqual(done.returncode, 0, done.stdout)
                for said in (shown.stdout, done.stdout):
                    self.assertNotIn('server', said.lower())
                self.assertIn('then run continue', done.stdout)
                written = json.loads(path.read_text())
                kept = {k: v for k, v in (existing or {}).items() if k != 'decision_repositories'}
                self.assertEqual(written, dict(kept, decision_repositories=pair), 'only that key changes')
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                first = (path.read_bytes(), path.stat().st_mtime_ns)
                again = j.helper(['decisions', '--yes'])
                self.assertEqual(again.returncode, 0, again.stdout)
                self.assertIn('already reads', again.stdout)
                self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), first, 'a second run changes nothing')
                self.assertEqual(j.helper(['continue']).returncode, 0, 'the companion is then carried')
        private = Journey(self)
        private.write_setup(setup_state())
        self.assertEqual(private.helper(['decisions', '--yes']).returncode, 5, 'no companion, nothing to connect')
        self.assertFalse((private.setup_dir / 'service/config.json').exists())

    def test_a_decisions_write_cut_short_before_its_replace_can_be_confirmed_again(self):
        # Review R6: catches a staging file left by an interrupted write blocking
        # every later confirmation, so the companion could never be connected.
        pair = setup_state(brain='companion')['brain']['decision_repositories']
        for name, existing in (('no settings file', None),
                               ('an existing settings file', {'schema': 'synthetic', 'server': {'port': 7370}})):
            with self.subTest(name):
                j = Journey(self)
                j.write_setup(setup_state(brain='companion'))
                path = j.setup_dir / 'service/config.json'
                if existing is not None:
                    j.write_config(existing)
                before = path.read_bytes() if path.exists() else None
                # The real helper, its process killed (SIGKILL) just before its final replace.
                cut = subprocess.run(
                    [sys.executable, '-I', '-c', 'import os, runpy, signal, sys\n'
                     'os.replace = lambda *a: os.kill(os.getpid(), signal.SIGKILL)\n'
                     'sys.argv = sys.argv[1:]\nrunpy.run_path(sys.argv[0], run_name="__main__")',
                     str(HELPER), 'decisions', '--yes', '--state', str(j.state), '--setup-state', str(j.setup_dir)],
                    env=j.env(), capture_output=True, text=True, cwd=j.dir, timeout=60)
                self.assertEqual(cut.returncode, -9, cut.stdout + cut.stderr)
                self.assertEqual(path.read_bytes() if path.exists() else None, before, 'the cut write changed nothing')
                self.assertEqual(j.helper(['decisions']).returncode, 12)
                done = j.helper(['decisions', '--yes'])
                self.assertEqual(done.returncode, 0, done.stdout)
                self.assertEqual(json.loads(path.read_text()), dict(existing or {}, decision_repositories=pair),
                                 'connected, every other key kept')
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                first = (path.read_bytes(), path.stat().st_mtime_ns)
                self.assertEqual(j.helper(['decisions', '--yes']).returncode, 0)
                self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), first, 'a second run changes nothing')
                self.assertEqual(j.helper(['continue']).returncode, 0, 'the companion is then carried')

    def test_the_prepared_agents_are_reused_only_when_offered(self):
        j = Journey(self)
        self.assertEqual(j.helper(['where', '--agents', 'cloud', '--yes']).returncode, 0)
        self.assertEqual(j.helper(['choose', '--from-setup', '--agents', 'cloud']).returncode, 5, 'nothing carried yet')
        j.write_setup(setup_state(settings=('codex', 'syn-codex-model-01', 'xhigh')))
        self.assertEqual(j.helper(['continue']).returncode, 0)
        unoffered = j.helper(['choose', '--from-setup', '--agents', 'cloud'])
        self.assertEqual(unoffered.returncode, 5, unoffered.stdout)
        both = j.helper(['choose', '--from-setup', '--harness', 'codex', '--model', 'syn-codex-model-01',
                         '--effort', 'high', '--agents', 'cloud'])
        self.assertEqual(both.returncode, 2, 'a carried choice is never overridden in the same call')
        self.assertNotIn('choices', json.loads(j.state.read_text()))


class Launch(unittest.TestCase):
    def test_the_whole_journey_starts_its_fleet_through_launch_fleets_own_path(self):
        # #636 (J87 Q1): the first fleet starts as launch-fleet starts every
        # fleet; catches any engine or tick call, a second start, or a start
        # with other settings, project or brief than the carried ones.
        j = Journey(self)
        results = j.replay()
        for turn, result in results:
            self.assertEqual(result.returncode, turn['exit'], (turn['tool'], result.stdout, result.stderr))
        self.assertEqual([c['form'] for c in j.logged()], ['fleet'], 'the installed openwiz only reads progress')
        self.assertEqual(j.spawns(), [], "the start is launch-fleet's own path, never a one-off thread (R7)")
        yes = next(r for turn, r in results if turn['tool'][0] == 'launch' and '--yes' in turn['tool']).stdout
        for words in ("Nothing is started by this command", "follow launch-fleet's Launch section",
                      'spec #900 of %s' % REPO, 'Starting one', 'launch-fleet: fleet active, loop fleet-900'):
            self.assertIn(words, yes)
        preview = next(r for turn, r in results if turn['tool'] == ['launch', '--spec', '900']).stdout
        for line in ('Ready to start the fleet for spec #900 in Cloudroom, through launch-fleet: 1 fleet thread '
                     '(codex syn-codex-model-01 high)', 'checks the spec every 10 minutes', '#901 S1: the field and its sheep',
                     'reviewed by claude-code syn-claude-model-01 high',
                     'Start the fleet in Cloudroom now? It can cost money: it uses your Cloud Credits'):
            self.assertIn(line, preview)
        self.assertNotIn('#904', preview)
        started = results[-2][1].stdout
        for line in ("Spec #900 has its fleet record: launch-fleet's loop runs the spec.",
                     'The plan passed its checks, so the fleet started: 3 builders'):
            self.assertIn(line, started)
        watch = results[-1][1].stdout
        for line in ('Spec #900 has its fleet record', '#901 building', '#904 blocked',
                     '5 tickets: 3 building, 2 blocked', 'Counts are progress, not a first merge'):
            self.assertIn(line, watch)
        self.assertEqual(stat.S_IMODE(j.state.stat().st_mode), 0o600, 'owner-only state')

    def test_local_progress_reads_github_only_and_never_cloudroom(self):
        j = Journey(self)
        j.replay(until='watch')
        state = json.loads(j.state.read_text())
        state['host'] = {'agents': 'local', 'harnesses': ['claude-code', 'codex']}
        j.state.write_text(json.dumps(state))
        (j.dir / 'bin/room-cli').unlink()
        note = '<!-- openwiz:status v1 -->\nagent: builder\nstate: working\n'
        views = {901: ('CLOSED', 'COMPLETED', [1901], [], []), 902: ('OPEN', None, [1902], [], []),
                 903: ('OPEN', None, [], [], [note]), 904: ('OPEN', None, [], [(901, 'CLOSED'), (903, 'OPEN')], []),
                 905: ('OPEN', None, [], [(901, 'CLOSED')], [])}
        answers = {str(n): {'number': n, 'state': s, 'stateReason': why,
                            'closedByPullRequestsReferences': [{'number': p} for p in pulls],
                            'blockedBy': {'nodes': [{'number': b, 'state': bs} for b, bs in blockers]},
                            'comments': [{'body': body, 'author': {'login': 'synthetic-factory[bot]'}}
                                         for body in bodies]}
                   for n, (s, why, pulls, blockers, bodies) in views.items()}
        (j.dir / 'tickets.json').write_text(json.dumps(answers))
        gh = j.dir / 'bin/gh'
        gh.write_text(
            '#!%s -I\nimport json, os, sys\nfrom pathlib import Path\na = sys.argv[1:]\n'
            "if a[:2] == ['issue', 'view'] and a[3:] == ['--json', '%s']:\n"
            "    print(json.dumps(json.loads(Path(%r).read_text())[a[2]]))\n    sys.exit(0)\n"
            "os.execv(%r, [%r, '-I', '-S', %r, *a])\n" % (
                sys.executable, TICKET_FIELDS, str(j.dir / 'tickets.json'), sys.executable, sys.executable,
                str(FAKE_GH)))
        gh.chmod(0o755)
        before = len(j.logged())
        result = j.helper(['progress', '--spec', '900'])
        self.assertEqual(j.logged()[before:], [], 'a local fleet never runs the CloudRoom-backed openwiz fleet')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for line in ('#901 merged', '#902 in_review', '#903 building', '#904 blocked', '#905 ready',
                     '5 tickets: 1 ready, 1 building, 1 in review, 1 merged, 1 blocked',
                     'Counts are progress, not a first merge'):
            self.assertIn(line, result.stdout)

    def test_repeat_and_reload_never_start_again(self):
        j = Journey(self)
        j.replay()
        again = j.tool(YES)
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertIn('already started', again.stdout)
        self.assertEqual(j.spawns(), [])

    def test_a_start_settles_only_on_launch_fleets_activation_record(self):
        # R7: catches the yes, or anything short of launch-fleet's own record read back, counted as the start
        j = Journey(self)
        j.replay(until='launch')
        self.assertEqual(j.tool(PREVIEW).returncode, 12)
        first = j.tool(YES)
        self.assertEqual(first.returncode, 0, first.stdout)
        self.assertNotIn('so the fleet started', first.stdout)
        second = j.tool(YES)
        self.assertEqual(second.returncode, 6, second.stdout)
        self.assertIn('no fleet record yet', second.stdout)
        j.extra_env = {'FAKE_GH_COMMENTS_FAIL': '1'}
        unread = j.tool(YES)
        self.assertEqual(unread.returncode, 6, 'an unread record settles nothing')
        j.extra_env = {}
        j.fleet_record()
        third = j.tool(YES)
        self.assertEqual(third.returncode, 0, third.stdout)
        self.assertIn('has its fleet record', third.stdout)
        self.assertIn('so the fleet started', third.stdout)
        self.assertEqual(j.spawns(), [], 'never a start of its own')

    def test_uncertain_launch_accepts_only_configured_record_authors(self):
        # Catches #1096 F1: outsider text settling an uncertain launch, or an
        # unread author policy/comment read being treated as a started fleet.
        # Earlier recovery tests supplied only the factory's own comment.
        j = Journey(self)
        j.replay(until='launch')
        self.assertEqual(j.tool(PREVIEW).returncode, 12)
        self.assertEqual(j.tool(YES).returncode, 0)
        j.fleet_record()
        record = j.world['issues'][0]['comments'][-1]
        unresolved = j.state.read_text()
        settings = j.world['files']['docs/agents/fleet.md']
        for author in ('synthetic-outsider', None):
            with self.subTest(author=author):
                j.state.write_text(unresolved)
                record['author'] = author
                j.save_world()
                result = j.tool(YES)
                self.assertEqual(result.returncode, 6, result.stdout)
                self.assertIn('no fleet record yet', result.stdout)
                self.assertEqual(json.loads(j.state.read_text())['launch']['state'], 'authorized')
        record['author'] = 'SYNTHETIC-FACTORY[bot]'
        row = '| Record authors | `synthetic-factory[bot]` |'
        policies = {'unreadable': None, 'missing': settings.replace(row, ''),
                    'duplicate': settings.replace(row, row + '\n' + row),
                    'empty': settings.replace(row, '| Record authors | |'),
                    'malformed login': settings.replace(row, '| Record authors | `synthetic-factory[bot]`, invalid |'),
                    'extra cell': settings.replace(row, row + ' extra |')}
        for name, policy in policies.items():
            with self.subTest(policy=name):
                j.state.write_text(unresolved)
                if policy is None:
                    j.world['files'].pop('docs/agents/fleet.md', None)
                else:
                    j.world['files']['docs/agents/fleet.md'] = policy
                j.save_world()
                result = j.tool(YES)
                self.assertEqual(result.returncode, 6, result.stdout)
                self.assertIn('could not be read', result.stdout)
                self.assertEqual(json.loads(j.state.read_text())['launch']['state'], 'authorized')
        j.world['files']['docs/agents/fleet.md'] = settings
        j.save_world()
        j.state.write_text(unresolved)
        j.extra_env['FAKE_GH_COMMENTS_FAIL'] = '1'
        unread = j.tool(YES)
        self.assertEqual(unread.returncode, 6, unread.stdout)
        self.assertIn('could not be read', unread.stdout)
        self.assertEqual(json.loads(j.state.read_text())['launch']['state'], 'authorized')
        j.extra_env = {}
        # R2 catches an outsider's U+2028 inside JSON blocking a trusted record.
        j.world['issues'][0]['comments'].append(
            {'id': 90003, 'author': 'synthetic-outsider', 'body': 'Thanks!\u2028Looks good.'})
        for author in ('SYNTHETIC-FACTORY[bot]', 'Synthetic-Owner'):
            with self.subTest(trusted=author):
                # Both configured logins, including the fallback user, work
                # case-insensitively on an unresolved start.
                j.state.write_text(unresolved)
                record['author'] = author
                j.world['files']['docs/agents/fleet.md'] = settings.replace(
                    row, '| Record authors | `synthetic-factory[bot]`, `synthetic-owner` |')
                j.save_world()
                settled = j.tool(YES)
                self.assertEqual(settled.returncode, 0, settled.stdout)
                self.assertIn('has its fleet record', settled.stdout)
                self.assertEqual(json.loads(j.state.read_text())['launch']['state'], 'started')
        self.assertEqual(j.spawns(), [], 'reconciliation never dispatches a fleet of its own')

    def test_no_start_once_setup_no_longer_verifies(self):
        # Review R4: catches a fleet started after setup refuses a prerequisite or its checks expire.
        stale = int(time.time() * 1000) - 2 * 60 * 60 * 1000
        for name, state in (('login lost push access', setup_state(overrides={'personal_github': 'identity_no_push'})),
                            ('checks expired', setup_state(at=stale))):
            with self.subTest(name):
                j = Journey(self)
                j.replay(until='launch')
                j.write_setup(state)
                result = j.tool(PREVIEW)
                self.assertEqual(result.returncode, 5, result.stdout)
                self.assertIn('nothing started', result.stdout)
                self.assertEqual(j.spawns(), [])
                self.assertNotIn('setup', json.loads(j.state.read_text()), 'run continue again')

    def test_missing_or_stale_approval_starts_nothing(self):
        for change in ('missing', 'stale'):
            with self.subTest(change):
                j = Journey(self)
                j.replay(until='launch')
                if change == 'missing':
                    j.world['issues'][0]['comments'] = []
                else:
                    j.world['issues'][3]['body'] += 'A changed body.\n'
                j.save_world()
                result = j.tool(PREVIEW)
                self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
                self.assertIn('nothing started', result.stdout)
                self.assertEqual(j.spawns(), [])

    def test_another_specs_frontier_is_not_this_fleets(self):
        # Catches a first fleet that would also start an approved ticket of
        # another spec in the same repository.
        j = Journey(self)
        j.replay(until='launch')
        other = {'number': 951, 'title': 'O1: another ticket', 'blockers': []}
        j.world['issues'] += [{'number': 950, 'title': 'Another spec', 'state': 'OPEN', 'parent': None, 'labels': [],
                               'body': 'Synthetic.\n', 'comments': []},
                              {'number': 951, 'title': other['title'], 'state': 'OPEN', 'parent': 950,
                               'labels': ['ready-for-agent'], 'blockedBy': [], 'body': 'Synthetic.\n', 'comments': []}]
        j.save_world()
        j.approve(spec=950, tickets=[other], comment=90009)
        shown = j.tool(PREVIEW)
        self.assertEqual(shown.returncode, 12, shown.stdout)
        self.assertIn('#903 S3: sheep flee the dog', shown.stdout)
        self.assertNotIn('#951', shown.stdout)

    def test_the_yes_binds_the_preview_the_user_saw(self):
        # The user said yes to two starts; a third ticket becoming ready before
        # the yes runs must not start without a new preview and yes.
        j = Journey(self)
        j.replay(until='launch')
        j.world['issues'][1]['labels'] = ['ready-for-agent', 'held']
        j.save_world()
        shown = j.tool(PREVIEW)
        self.assertEqual(shown.returncode, 12, shown.stdout)
        self.assertNotIn('#901 ', shown.stdout)
        self.assertIn('#902 ', shown.stdout)
        j.world['issues'][1]['labels'] = ['ready-for-agent']
        j.save_world()
        shutil.rmtree(j.dir / 'cache', ignore_errors=True)
        result = j.tool(YES)
        self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
        self.assertIn('preview again', result.stdout)
        self.assertEqual(j.spawns(), [], 'no start of effects the user never saw')
        bare = j.tool(dict(YES, tool=['launch', '--spec', '900', '--yes']))
        self.assertEqual(bare.returncode, 2, 'a yes names the preview it answers')
        self.assertEqual(j.tool(PREVIEW).returncode, 12)
        self.assertEqual(j.tool(YES).returncode, 0)
        self.assertEqual(json.loads(j.state.read_text())['launch']['state'], 'authorized')
        self.assertEqual(j.spawns(), [])

    def test_every_builder_profile_the_fleet_can_use_is_the_users_choice(self):
        # Blocked tickets may later use the small-ticket builder; the reviewer
        # stays in the other model family.
        for name, text in (('small builder differs', fleet_md(small=CLAUDE)),
                           ('reviewer in the same family', fleet_md(for_gpt=CODEX)),
                           ('builder tables missing', fleet_md().replace('## Builder', '## Retired builder'))):
            with self.subTest(name):
                j = Journey(self)
                j.replay(until='launch')
                j.world['files']['docs/agents/fleet.md'] = text
                j.save_world()
                result = j.tool(PREVIEW)
                self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
                self.assertIn('nothing started', result.stdout)
                self.assertEqual(j.spawns(), [])

    def test_without_carried_setup_local_agents_or_another_spec_nothing_starts(self):
        j = Journey(self)
        j.replay(until='launch')
        state = json.loads(j.state.read_text())
        j.state.write_text(json.dumps({k: v for k, v in state.items() if k != 'setup'}))
        uncarried = j.tool(PREVIEW)
        self.assertEqual(uncarried.returncode, 5, uncarried.stdout)
        self.assertIn('run continue first', uncarried.stdout)
        k = Journey(self)
        k.replay(until='launch')
        saved = json.loads(k.state.read_text())
        saved['choices']['agents'] = 'local'  # agents chosen for a place the user never answered
        k.state.write_text(json.dumps(saved))
        local = k.tool(PREVIEW)
        self.assertEqual(local.returncode, 5, local.stdout)
        self.assertIn('not chosen for where agents run', local.stdout)
        other = k.tool({'tool': ['launch', '--spec', '950']})
        self.assertEqual(other.returncode, 5, other.stdout)
        self.assertEqual(j.spawns() + k.spawns() + j.logged() + k.logged(), [], 'not even a read of the engine')

    def test_another_repository_never_runs_this_onboardings_launch(self):
        # The same state and issue numbers, resumed in another repository.
        j = Journey(self)
        j.replay(until='launch')
        j.world['repo'] = 'synthetic-owner/synthetic-other'
        j.save_world()
        for turn in (PREVIEW, YES, {'tool': ['progress', '--spec', '900'], 'progress': ['building'] * 5}):
            result = j.tool(turn)
            self.assertEqual(result.returncode, 5, (turn['tool'], result.stdout + result.stderr))
            self.assertIn(REPO, result.stdout)
        self.assertEqual(j.spawns() + j.logged(), [])

    def test_the_demo_repository_is_created_once_and_read_back(self):
        j = Journey(self)
        j.replay(until='connect')
        self.assertEqual(j.gh_creates(), [['repo', 'view'], ['repo', 'create'], ['repo', 'view']],
                         'checked absent, created once, read back')
        made = json.loads(j.repos.read_text())['repos']
        self.assertEqual((list(made), made[REPO.lower()]['private']), ([REPO.lower()], True))
        preview = next(r for a, r in j.calls if a[0] == 'create-repo' and '--yes' not in a)
        for words in ('private', REPO, 'your gh identity'):
            self.assertIn(words, preview.stdout)
        again = j.helper(['create-repo', '--repo', REPO, '--yes'])
        self.assertEqual(again.returncode, 0, again.stdout)
        self.assertEqual([c[1] for c in j.gh_creates()].count('create'), 1, 'a repeat only reads')

    def test_a_lost_create_is_read_before_any_retry(self):
        for create, fails, first, second, creates in (('lost', 0, 5, 5, 1), ('lost', 2, 6, 6, 1), ('fail', 0, 5, 0, 2)):
            with self.subTest(create, fails=fails):
                j = Journey(self)
                j.repos.write_text(github(create=create, fail_after_create=fails))
                yes = ['create-repo', '--repo', REPO, '--yes']
                if fails:
                    self.assertEqual(j.helper(yes).returncode, 6, j.calls[-1][1].stdout)
                    self.assertIn('uncertain', j.calls[-1][1].stdout)
                    self.assertEqual(j.helper(yes).returncode, 6, 'the next read fails too: still uncertain, no create')
                    self.assertEqual(j.helper(yes).returncode, 5, j.calls[-1][1].stdout)
                    self.assertIn('uncertain', j.calls[-1][1].stdout)
                    self.assertEqual([c[1] for c in j.gh_creates()].count('create'), 1, 'read, never created twice')
                    self.assertNotIn('seeded', json.loads(j.state.read_text())['created'])
                    continue
                self.assertEqual(j.helper(yes).returncode, first, j.calls[-1][1].stdout)
                state = json.loads(j.repos.read_text())
                j.repos.write_text(json.dumps(dict(state, create='ok', view_fails=0)))
                self.assertEqual(j.helper(yes).returncode, second, j.calls[-1][1].stdout)
                self.assertEqual([c[1] for c in j.gh_creates()].count('create'), creates)

    def test_an_existing_or_public_repository_is_never_taken_as_the_demo(self):
        j = Journey(self)
        j.repos.write_text(github([demo_repository(visibility='public')]))
        self.assertEqual(j.helper(['create-repo', '--repo', REPO]).returncode, 12)
        result = j.helper(['create-repo', '--repo', REPO, '--yes'])
        self.assertEqual(result.returncode, 5, result.stdout)
        self.assertIn('already exists', result.stdout)
        self.assertNotIn(['repo', 'create'], j.gh_creates())

    def test_a_busy_state_file_is_refused(self):
        j = Journey(self)
        j.replay(until='launch')
        with open(str(j.state) + '.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            busy = j.tool(YES)
        self.assertEqual(busy.returncode, 7, busy.stdout + busy.stderr)
        self.assertEqual(j.spawns() + j.logged(), [])



YES_DEMO = ['create-repo', '--repo', REPO, '--yes']


class DemoRepository(unittest.TestCase):
    """Read-back and ownership checks for the demo repository."""

    def world(self, j):
        return json.loads(j.repos.read_text())

    def writes(self, j):
        return [call for call in self.world(j)['log'] if call[0] != 'GET']

    def test_signed_out_demo_creation_refuses_with_a_sign_in_pointer(self):
        # Catches #1096 F2: the real demo command reaching repo creation before
        # GitHub sign-in, then failing with no usable onboarding next step.
        # Earlier demo cases always supplied a signed-in synthetic user.
        j = Journey(self)
        j.repos.write_text(github(signed_out=True))
        before = self.world(j)['repos']
        preview = j.helper(['create-repo', '--repo', REPO])
        self.assertEqual(preview.returncode, 12, preview.stdout)
        result = j.helper(YES_DEMO)
        self.assertEqual(result.returncode, 5, result.stdout)
        for words in ('GitHub', 'sign-in', 'github_login.py sign-in', 'nothing created'):
            self.assertIn(words, result.stdout)
        self.assertEqual((self.world(j)['repos'], self.writes(j)), (before, []))
        self.assertNotIn(['repo', 'create'], j.gh_creates(), 'no creation attempted while signed out')
        self.assertFalse(j.state.exists(), 'no pending creation is saved for a refused sign-in')
        # Once sign-in is available, the same demo can be created and read
        # back; the refusal neither creates nor strands an operation.
        world = self.world(j)
        world['signed_out'] = False
        j.repos.write_text(json.dumps(world))
        created = j.helper(YES_DEMO)
        self.assertEqual(created.returncode, 0, created.stdout)
        self.assertIn('Created and read back', created.stdout)
        self.assertEqual(self.writes(j), [['POST', 'user/repos'], *map(list, SEEDED)])

    # Catches: a yes given to a preview that never said the repository gets
    # an initial README commit on its default branch, or a preview that writes.
    def test_the_preview_discloses_the_initial_commit_and_writes_nothing(self):
        j = Journey(self)
        preview = j.helper(['create-repo', '--repo', REPO])
        self.assertEqual(preview.returncode, 12, preview.stdout)
        for words in ('private', REPO, 'README.md', 'initial commit', 'default branch'):
            self.assertIn(words, preview.stdout)
        self.assertEqual((self.world(j)['repos'], self.writes(j)), ({}, []))

    # Catches: a created repository reported complete (and init started) while
    # its default branch or commit could not be read, or a retry that creates
    # a second repository or pushes its own seed commit.
    def test_an_unread_or_missing_default_branch_is_never_created(self):
        ref = 'repos/%s/git/ref/heads/main' % REPO
        for name, faults, first in (('ref read lost', [{'method': 'GET', 'path': ref, 'mode': 'drop', 'times': 1}], 6),
                                    ('ref read refused', [{'method': 'GET', 'path': ref, 'mode': 500, 'times': 1}], 6)):
            with self.subTest(name):
                j = Journey(self)
                j.repos.write_text(github(faults=faults))
                result = j.helper(YES_DEMO)
                self.assertEqual(result.returncode, first, result.stdout)
                self.assertNotIn('Created', result.stdout)
                again = j.helper(YES_DEMO)
                self.assertEqual(again.returncode, 0, again.stdout)
                self.assertIn('Created and read back', again.stdout)
                self.assertEqual(self.writes(j), [['POST', 'user/repos'], *map(list, SEEDED)],
                                 'one create and its disclosed test and check, no other write')

    # Catches: an onboarding whose own repository exists without a default
    # branch (an interrupted or earlier empty create) being reported created,
    # retried, or seeded by a separate push.
    def test_its_own_repository_without_a_default_branch_stays_unresolved(self):
        for state, code in (('pending', 6), ('uncertain', 6), ('created', 5)):
            with self.subTest(state):
                j = Journey(self)
                j.repos.write_text(github([demo_repository()]))
                j.state.write_text(json.dumps({'created': {'repo': REPO, 'state': state}}))
                j.state.chmod(0o600)
                before = self.world(j)['repos']
                for _ in range(2):
                    result = j.helper(YES_DEMO)
                    self.assertEqual(result.returncode, code, result.stdout)
                    self.assertIn('default branch', result.stdout)
                    self.assertNotIn('Created and read back', result.stdout)
                self.assertEqual(self.world(j)['repos'], before, 'nothing created, seeded or pushed')
                self.assertEqual(self.writes(j), [])
                if state != 'created':
                    self.assertNotEqual(json.loads(j.state.read_text())['created']['state'], 'created')

    def test_a_teammates_repository_at_the_name_is_never_seeded_on_resume(self):
        teammate = {'main': {'README.md': '# demo\n'}}
        for state in ('pending', 'uncertain'):
            with self.subTest(state):
                j = Journey(self)
                j.repos.write_text(github([demo_repository(branches=teammate)]))
                j.state.write_text(json.dumps({'created': {'repo': REPO, 'state': state}}))
                j.state.chmod(0o600)
                before = self.world(j)['repos']
                for _ in range(2):
                    result = j.helper(YES_DEMO)
                    self.assertEqual(result.returncode, 5, result.stdout)
                    self.assertIn('uncertain', result.stdout)
                    self.assertIn('Continue with %s as an existing repository: run next' % REPO, result.stdout)
                    self.assertNotIn('another name', result.stdout, 'this onboarding makes no second repository')
                    self.assertNotIn('Created and read back', result.stdout)
                self.assertEqual((self.world(j)['repos'], self.writes(j)), (before, []), 'neither file written')
                self.assertEqual(json.loads(j.state.read_text())['created'], {'repo': REPO, 'state': 'unproven'})
                other = j.helper(['create-repo', '--repo', 'synthetic-owner/second-demo', '--yes'])
                self.assertEqual(other.returncode, 5, other.stdout)
                self.assertEqual(self.writes(j), [], 'still uncertain: no second repository')

    def test_a_lost_reply_or_another_id_writes_neither_file(self):
        for name, switches, saved in (('lost reply', {'create': 'lost'}, None),
                                      ('reply names another id', {'reply_id': 'R_other'}, None),
                                      ('saved id is not the repository read', {}, 'R_other')):
            with self.subTest(name):
                j = Journey(self)
                repos = [demo_repository(branches={'main': {'README.md': '# demo\n'}})] if saved else []
                j.repos.write_text(github(repos, **switches))
                if saved:
                    j.state.write_text(json.dumps({'created': {'repo': REPO, 'state': 'uncertain', 'id': saved}}))
                    j.state.chmod(0o600)
                result = j.helper(YES_DEMO)
                self.assertEqual(result.returncode, 5, result.stdout)
                self.assertIn('uncertain', result.stdout)
                self.assertEqual(self.writes(j), [] if saved else [['POST', 'user/repos']], 'neither file written')
                self.assertEqual(j.helper(YES_DEMO).returncode, 5, 'a rerun neither creates nor seeds')
                self.assertEqual(self.writes(j), [] if saved else [['POST', 'user/repos']])
                self.assertNotIn('seeded', json.loads(j.state.read_text())['created'])

    def test_a_verified_create_read_back_later_is_seeded_once(self):
        empty = [{'method': 'GET', 'path': 'repos/%s/git/ref/heads/main' % REPO, 'mode': 409, 'times': 2}]
        for name, switches, unread in (('read fails once', {'fail_after_create': 1}, 1),
                                       ('read empty twice', {'faults': empty}, 2)):
            with self.subTest(name):
                j = Journey(self)
                j.repos.write_text(github(**switches))
                for _ in range(unread):
                    self.assertEqual(j.helper(YES_DEMO).returncode, 6, j.calls[-1][1].stdout)
                    self.assertEqual(self.writes(j), [['POST', 'user/repos']], 'unread: nothing seeded yet')
                done = j.helper(YES_DEMO)
                self.assertEqual(done.returncode, 0, done.stdout)
                self.assertIn('Created and read back', done.stdout)
                self.assertEqual(j.helper(YES_DEMO).returncode, 0)
                self.assertEqual(self.writes(j), [['POST', 'user/repos'], *map(list, SEEDED)], 'both files, once')

    def test_a_retry_keeps_a_verified_id_and_the_one_repository_guard_when_the_name_stops_resolving(self):
        made = demo_repository(branches={'main': {'README.md': '# demo\n'}})
        made['node_id'] = 'R_made'
        renamed = dict(made, full_name='synthetic-owner/renamed')
        for name, repos, record, code in (
                ('verified, then renamed', [renamed], {'state': 'uncertain', 'id': 'R_made'}, 6),
                ('verified, then hidden', [dict(made, hidden=True)], {'state': 'uncertain', 'id': 'R_made'}, 6),
                ('unproven, then hidden', [dict(made, hidden=True)], {'state': 'unproven'}, 6),
                ('pending, then hidden', [dict(made, hidden=True)], {'state': 'pending'}, 6)):
            with self.subTest(name):
                j = Journey(self)
                j.repos.write_text(github(repos))
                j.state.write_text(json.dumps({'created': {'repo': REPO, **record}}))
                j.state.chmod(0o600)
                for _ in range(2):
                    result = j.helper(YES_DEMO)
                    self.assertEqual(result.returncode, code, result.stdout)
                    self.assertNotIn('Created and read back', result.stdout)
                self.assertEqual(self.writes(j), [], 'no second create, nothing seeded')
                kept = json.loads(j.state.read_text())['created']
                self.assertEqual((kept['repo'], kept['state'] != 'absent', kept.get('id')),
                                 (REPO, True, record.get('id')), 'the id and the guard are kept')
                other = j.helper(['create-repo', '--repo', 'synthetic-owner/second-demo', '--yes'])
                self.assertEqual(other.returncode, 5, other.stdout)
                self.assertEqual(self.writes(j), [], 'no second repository under another name')

    def test_a_repository_replaced_before_a_seed_write_gets_neither_file(self):
        j = Journey(self)
        j.repos.write_text(github(replace_before_write=True))
        for _ in range(2):
            result = j.helper(YES_DEMO)
            found = self.world(j)['repos'][REPO.lower()]
            self.assertEqual(found['node_id'], 'R_replacement', 'the fake replaced it before the first write')
            self.assertEqual(found['branches'], {'main': {'README.md': '# synthetic-sheep\n'}},
                             'nothing written into the replacement')
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertNotIn('Created and read back', result.stdout)
        self.assertEqual(self.writes(j), [['POST', 'user/repos']])

    def test_the_create_reply_is_matched_by_node_id_never_its_numeric_id(self):
        for name, switches, code, writes in (('numeric id differs, node_id matches', {}, 0, SEEDED),
                                             ('node_id differs from the read-back', {'reply_id': 'R_other'}, 5, ())):
            with self.subTest(name):
                j = Journey(self)
                j.repos.write_text(github(**switches))
                result = j.helper(YES_DEMO)
                self.assertEqual(result.returncode, code, result.stdout)
                self.assertEqual(j.helper(YES_DEMO).returncode, code)
                self.assertEqual(self.writes(j), [['POST', 'user/repos'], *map(list, writes)], 'seeded once or never')

    # Catches: someone else's repository, private or public, taken as the demo
    # or written to, and a repeat that rewrites the owner's later work.
    def test_existing_repositories_and_owner_work_are_never_written(self):
        owned = {'main': {'README.md': 'Owner work.\n', 'game.py': 'print(1)\n'}}
        for visibility in ('private', 'public'):
            with self.subTest(visibility):
                j = Journey(self)
                j.repos.write_text(github([demo_repository(visibility=visibility, branches=owned)]))
                before = self.world(j)['repos']
                result = j.helper(YES_DEMO)
                self.assertEqual(result.returncode, 5, result.stdout)
                self.assertIn('already exists', result.stdout)
                self.assertEqual((self.world(j)['repos'], self.writes(j)), (before, []))
        j = Journey(self)
        self.assertEqual(j.helper(YES_DEMO).returncode, 0, j.calls[-1][1].stdout)
        world = self.world(j)
        world['repos'][REPO.lower()]['branches'].setdefault('main', {})['game.py'] = 'print(1)\n'  # the owner's later commit
        j.repos.write_text(json.dumps(world))
        again = j.helper(YES_DEMO)
        self.assertEqual(again.returncode, 0, again.stdout)
        self.assertEqual(self.world(j)['repos'], world['repos'], 'a repeat only reads')
        self.assertEqual(self.writes(j), [['POST', 'user/repos'], *map(list, SEEDED)])

    def test_the_new_repository_gets_the_disclosed_passing_test_and_check_workflow(self):
        j = Journey(self)
        preview = j.helper(['create-repo', '--repo', REPO])
        self.assertEqual(preview.returncode, 12, preview.stdout)
        for words in ('tests/test_check.py', '.github/workflows/check.yml', 'job named check',
                      'python3 -m unittest discover -s tests'):
            self.assertIn(words, preview.stdout)
        self.assertEqual(self.writes(j), [], 'the preview writes nothing')
        world = self.world(j)
        world['seed_lost'] = 1
        j.repos.write_text(json.dumps(world))
        done = j.helper(YES_DEMO)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn('passing test', done.stdout)
        self.assertEqual(self.writes(j), [['POST', 'user/repos'], *map(list, SEEDED)], 'a lost reply is read back')
        self.assertTrue(json.loads(j.state.read_text())['created']['seeded'])
        main = self.world(j)['repos'][REPO.lower()]['branches']['main']
        project = j.dir / 'seeded'
        for name, text in main.items():
            (project / name).parent.mkdir(parents=True, exist_ok=True)
            (project / name).write_text(text)
        ran = subprocess.run([sys.executable, '-I', '-m', 'unittest', 'discover', '-s', 'tests'], cwd=project,
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
        self.assertIn('Ran 1 test', ran.stderr)
        workflow = main['.github/workflows/check.yml']
        self.assertRegex(workflow, r'\njobs:\n  check:\n')
        self.assertIn('run: python3 -m unittest discover -s tests\n', workflow)
        self.assertEqual(j.helper(YES_DEMO).returncode, 0)
        self.assertEqual(len(self.writes(j)), 3, 'a repeat writes nothing')


class ModelsTable(unittest.TestCase):

    def models(self, text):
        sys.dont_write_bytecode = True
        spec = __import__('importlib.util').util.spec_from_file_location('settings', SETTINGS)
        module = __import__('importlib.util').util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.models(text)

    def chosen(self, j, local, options=None):
        j.replay(until='agents')
        j.checkout.write_text(local)
        if options is not None:
            j.options.write_text(json.dumps(options))
        return j.helper(['choose', '--from-setup', '--agents', 'cloud'])

    def test_a_cloud_choice_writes_the_models_table_before_the_older_tables(self):
        j = Journey(self)
        result = self.chosen(j, fleet_md())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        written = j.checkout.read_text()
        self.assertEqual(self.models(written), {'Orchestrator': CODEX, 'Builder': CODEX, 'Reviewer': CLAUDE,
                                                'Small builder': None, 'Fixer': None},
                         'the choice, with the older GPT-built reviewer kept as the other-family Reviewer')
        start, end = written.index('## Models\n'), written.index('## Builder\n')
        self.assertEqual(written[:start] + written[end:], fleet_md(), 'nothing outside the inserted table changes')
        self.assertIn('| Builder | Codex | syn-codex-model-01 | High |', written, 'the names set writes')
        self.assertIn('docs/agents/fleet.md', result.stdout)
        self.assertEqual(json.loads(j.state.read_text())['choices'], dict(j.settings, agents='cloud'),
                         'older tables on the default branch never read back a Models table write')
        again = j.helper(['choose', '--from-setup', '--agents', 'cloud'])
        self.assertEqual((again.returncode, j.checkout.read_text()), (0, written), 'a repeat writes nothing new')

    def test_a_models_table_gets_the_choice_and_keeps_an_other_family_reviewer(self):
        j = Journey(self)
        local = models_md(orchestrator=CLAUDE, builder=CLAUDE, reviewer=CLAUDE[:2] + ('xhigh',), small=CLAUDE,
                          fixer=CODEX)
        result = self.chosen(j, local)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        written = j.checkout.read_text()
        self.assertEqual(self.models(written), {'Orchestrator': CODEX, 'Builder': CODEX, 'Reviewer': CLAUDE[:2] + ('xhigh',),
                                                'Small builder': None, 'Fixer': None})
        reviewer = next(line for line in local.splitlines() if line.startswith('| Reviewer |'))
        self.assertIn(reviewer + '\n', written, 'the kept Reviewer row as written')
        self.assertEqual(written.replace(written[written.index('| Role |'):written.index('\nSource')], ''),
                         local.replace(local[local.index('| Role |'):local.index('\nSource')], ''))

    def test_a_same_family_reviewer_becomes_the_offered_recommendation_or_nothing_is_recorded(self):
        local = models_md(reviewer=SOL)
        j = Journey(self)
        refused = self.chosen(j, local)
        self.assertEqual(refused.returncode, 5, refused.stdout)
        self.assertIn('claude-code claude-opus-5-5 medium', refused.stdout)
        self.assertEqual(j.checkout.read_text(), local)
        self.assertNotIn('choices', json.loads(j.state.read_text()), 'nothing recorded')
        k = Journey(self)
        result = self.chosen(k, local, offering(OPUS))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        written = k.checkout.read_text()
        self.assertEqual(self.models(written)['Reviewer'], OPUS)
        self.assertIn('| Reviewer | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 '
                      '--reasoning-level medium` |', written)

    def test_a_broken_or_missing_settings_file_is_never_written(self):
        broken = models_md().replace('| Effort |', '| Level |')
        for name, local in (('broken', broken), ('missing', None)):
            with self.subTest(name):
                j = Journey(self)
                j.replay(until='agents')
                if local is None:
                    j.checkout.unlink()
                else:
                    j.checkout.write_text(local)
                result = j.helper(['choose', '--from-setup', '--agents', 'cloud'])
                self.assertEqual(result.returncode, 5, result.stdout)
                self.assertEqual(j.checkout.read_text() if j.checkout.exists() else None, local)
                self.assertNotIn('choices', json.loads(j.state.read_text()))

    def test_only_the_written_models_table_on_the_default_branch_reads_back(self):
        j = Journey(self)
        j.replay(until='agents')
        for name, remote in (('older tables', fleet_md()), ('other orchestrator', models_md(orchestrator=CLAUDE)),
                             ('other reviewer', models_md(reviewer=CLAUDE[:2] + ('xhigh',))),
                             ('own small builder', models_md(small=CODEX))):
            with self.subTest(name):
                j.world['files']['docs/agents/fleet.md'] = remote
                j.save_world()
                result = j.helper(['choose', '--from-setup', '--agents', 'cloud'])
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn('builder_tables', json.loads(j.state.read_text())['choices'], result.stdout)
                said = j.helper(['next']).stdout
                self.assertEqual(said.splitlines()[0], 'Next: agents.', said)
        j.world['files']['docs/agents/fleet.md'] = models_md()
        j.save_world()
        result = j.helper(['choose', '--from-setup', '--agents', 'cloud'])
        self.assertEqual(json.loads(j.state.read_text())['choices'].get('builder_tables'), 'read', result.stdout)
        self.assertNotEqual(j.helper(['next']).stdout.splitlines()[0], 'Next: agents.', 'the agents step is done')

    def test_a_linked_settings_folder_is_never_written(self):
        for link in ('docs', 'docs/agents'):
            with self.subTest(link):
                j = Journey(self)
                j.replay(until='agents')
                outside = Path(tempfile.mkdtemp(prefix='outside-'))
                self.addCleanup(shutil.rmtree, outside, True)
                target = outside / ('agents' if link == 'docs' else '') / 'fleet.md'
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(fleet_md())
                shutil.rmtree(j.dir / 'docs')
                if link == 'docs':
                    os.symlink(outside, j.dir / 'docs')
                else:
                    (j.dir / 'docs').mkdir()
                    os.symlink(outside, j.dir / 'docs/agents')
                result = j.helper(['choose', '--from-setup', '--agents', 'cloud'])
                self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
                self.assertEqual(target.read_text(), fleet_md(), 'the file outside the checkout is unchanged')
                self.assertEqual(sorted(p.name for p in target.parent.iterdir()), ['fleet.md'], 'nothing staged outside')
                self.assertNotIn('choices', json.loads(j.state.read_text()))

    def test_the_launch_reads_the_models_table(self):
        j = Journey(self)
        j.replay(until='launch')
        j.world['files']['docs/agents/fleet.md'] = models_md(orchestrator=CLAUDE)
        j.save_world()
        preview = j.tool(PREVIEW)
        self.assertEqual(preview.returncode, 12, preview.stdout + preview.stderr)
        for line in ('1 fleet thread (claude-code syn-claude-model-01 high)', 'builder (codex syn-codex-model-01 high)',
                     'reviewed by claude-code syn-claude-model-01 high'):
            self.assertIn(line, preview.stdout)
        j.world['files']['docs/agents/fleet.md'] = models_md(orchestrator=CODEX)
        j.save_world()
        moved = j.tool(YES)
        self.assertEqual(moved.returncode, 5, 'a yes to one Orchestrator never covers another\n' + moved.stdout)
        self.assertEqual(j.spawns(), [], 'the launch starts nothing itself')

    def test_the_launch_refuses_a_models_table_its_choice_or_family_rule_breaks(self):
        for name, text in (('broken', models_md().replace('| Effort |', '| Level |')),
                           ('small builder differs', models_md(small=CLAUDE)),
                           ('reviews wait', models_md(reviewer=SOL)),
                           ('two headings', models_md() + '## Models\n')):
            with self.subTest(name):
                j = Journey(self)
                j.replay(until='launch')
                j.world['files']['docs/agents/fleet.md'] = text
                j.save_world()
                result = j.tool(PREVIEW)
                self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
                self.assertNotIn('Confirmation:', result.stdout)

    def test_a_migrated_models_section_still_passes_connects_settings_check(self):
        old = connect_md()
        self.assertTrue(connect_usable(old), 'the old file passes ' + CONNECT_CHECK)
        self.assertFalse(connect_usable(old.replace('## Test commands', '## Commands')), 'the check refuses a gap')
        hosts = (('local', {'agents': 'local', 'harnesses': ['codex']}, 'the older `Reviewer for GPT-built` table'),
                 ('driver', {'agents': 'synthetic-driver', 'harnesses': [], 'adapters': '/synthetic/adapters'},
                  'the older `Reviewer for GPT-built` table'),
                 ('local, recommended reviewer', {'agents': 'local', 'harnesses': ['codex']},
                  'the recommended other-family choice'))
        for name, host, reviewer in hosts:
            with self.subTest(name):
                j = Journey(self)
                j.replay(until='agents')
                state = json.loads(j.state.read_text())
                state['host'] = host
                j.state.write_text(json.dumps(state))
                local = old if 'recommended' not in name else old.replace(
                    table('Reviewer for GPT-built', CLAUDE), table('Reviewer for GPT-built', SOL))
                options = offering(OPUS) if 'recommended' in name else None
                if options is not None:
                    j.options.write_text(json.dumps(options))
                j.checkout.write_text(local)
                self.assertTrue(connect_usable(local), 'the old file passes Connect')
                result = j.helper(['choose', '--from-setup'])
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                written = j.checkout.read_text()
                self.assertIn('## Models\n', written)
                self.assertTrue(connect_usable(written), CONNECT_CHECK + ' accepts the file choose wrote:\n' + written)
                section = written[written.index('## Models\n'):written.index('## Builder\n')]
                self.assertEqual([line for line in section.split('\n') if line.startswith('Source: ')], [
                    "Source: install's `choose`, from the owner's choice of harness, model and effort for the "
                    'Orchestrator and Builder; the Reviewer is %s.' % reviewer])
                self.assertEqual(written[:written.index('## Models\n')] + written[written.index('## Builder\n'):],
                                 local, 'nothing outside the inserted section changes')

    def test_a_models_change_before_activation_needs_a_fresh_preview_and_yes(self):
        j = Journey(self)
        j.replay(until='launch')
        j.world['files']['docs/agents/fleet.md'] = models_md(orchestrator=CODEX)
        j.save_world()
        self.assertEqual(j.tool(PREVIEW).returncode, 12)
        said_yes = j.tool(YES)
        self.assertEqual(said_yes.returncode, 0, said_yes.stdout)
        handoff = "follow launch-fleet's Launch section"
        self.assertIn(handoff, said_yes.stdout)
        same = j.tool(YES)
        self.assertEqual(same.returncode, 6, 'an unchanged Orchestrator still repeats the handoff\n' + same.stdout)
        self.assertIn(handoff, same.stdout)
        j.world['files'].pop('docs/agents/fleet.md')
        j.save_world()
        unknown = j.tool(YES)
        self.assertEqual(unknown.returncode, 6, 'unread settings keep the yes uncertain\n' + unknown.stdout)
        self.assertNotIn(handoff, unknown.stdout)
        self.assertEqual(json.loads(j.state.read_text())['launch']['state'], 'authorized', 'never withdrawn unread')
        j.world['files']['docs/agents/fleet.md'] = models_md(orchestrator=CLAUDE)
        j.save_world()
        j.extra_env = {'FAKE_GH_COMMENTS_FAIL': '1'}
        unread = j.tool(YES)
        self.assertEqual(unread.returncode, 6, 'an unread record keeps the yes uncertain\n' + unread.stdout)
        self.assertNotIn(handoff, unread.stdout)
        self.assertEqual(json.loads(j.state.read_text())['launch']['state'], 'authorized', 'never withdrawn unread')
        j.extra_env = {}
        moved = j.tool(YES)
        self.assertEqual(moved.returncode, 5, moved.stdout + moved.stderr)
        self.assertNotIn(handoff, moved.stdout)
        self.assertIn('claude-code syn-claude-model-01 high', moved.stdout)
        self.assertIn('preview again and ask again', moved.stdout)
        old = j.tool(YES)
        self.assertEqual(old.returncode, 5, 'the old yes covers nothing now\n' + old.stdout)
        self.assertNotIn(handoff, old.stdout)
        self.assertNotIn('launch', json.loads(j.state.read_text()), 'the yes is withdrawn')
        self.assertNotIn('The user said yes', j.helper(['next']).stdout, 'a resumed session never finishes the old yes')
        fresh = j.tool(PREVIEW)
        self.assertEqual(fresh.returncode, 12, fresh.stdout + fresh.stderr)
        self.assertIn('1 fleet thread (claude-code syn-claude-model-01 high)', fresh.stdout)
        again = j.tool(YES)
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertIn(handoff, again.stdout)
        j.fleet_record()
        j.world['files']['docs/agents/fleet.md'] = models_md(orchestrator=CODEX)
        j.save_world()
        started = j.tool(YES)
        self.assertEqual(started.returncode, 0, 'after activation the read stays reconciliation\n' + started.stdout)
        self.assertIn('so the fleet started', started.stdout)
        saved = j.state.read_bytes()
        repeat = j.tool(YES)
        self.assertEqual(repeat.returncode, 0, repeat.stdout)
        self.assertIn('already started', repeat.stdout)
        self.assertEqual(j.state.read_bytes(), saved, 'read-only after activation')
        self.assertEqual(j.spawns(), [], 'the launch starts nothing itself')

    def authorized(self):
        j = Journey(self)
        j.replay(until='launch')
        j.world['files']['docs/agents/fleet.md'] = models_md(orchestrator=CODEX)
        j.save_world()
        self.assertEqual(j.tool(PREVIEW).returncode, 12)
        said_yes = j.tool(YES)
        self.assertEqual(said_yes.returncode, 0, said_yes.stdout)
        return j, said_yes

    def test_an_unknown_record_or_orchestrator_never_repeats_the_handoff(self):
        handoff = "follow launch-fleet's Launch section"
        for name in ('record unread, orchestrator unchanged', 'no orchestrator in the settings'):
            with self.subTest(name):
                j, _ = self.authorized()
                if name.startswith('record'):
                    j.extra_env = {'FAKE_GH_COMMENTS_FAIL': '1'}
                else:
                    text = models_md(orchestrator=CODEX)
                    j.world['files']['docs/agents/fleet.md'] = (
                        text[:text.index('## Models\n')] + text[text.index('## CI checks'):])
                    j.save_world()
                saved = j.state.read_bytes()
                retry = j.tool(YES)
                self.assertEqual(retry.returncode, 6, retry.stdout + retry.stderr)
                self.assertNotIn(handoff, retry.stdout)
                self.assertNotIn('Traceback', retry.stderr)
                self.assertEqual(j.state.read_bytes(), saved, 'nothing withdrawn or saved while unknown')

    def test_the_start_path_is_bound_to_the_orchestrator_the_user_said_yes_to(self):
        j, said_yes = self.authorized()
        approved = '--provider %s --model %s --reasoning-level %s' % CODEX
        gate = 'ops-starts.py flags --repo %s fleet_thread' % REPO
        retry = j.tool(YES)
        self.assertEqual(retry.returncode, 6, retry.stdout)
        for said in (said_yes.stdout, retry.stdout):
            self.assertIn('`%s`' % approved, said, 'the handoff names the approved Orchestrator')
            self.assertIn(gate, said, "the handoff checks launch-fleet's own start reader first")
            self.assertIn('--provider codex --model syn-codex-model-01 --reasoning high', said)
        resumed = j.helper(['next']).stdout
        self.assertIn('run launch --spec 900 first', resumed, 'a resumed start goes through the same check')
        reader = [sys.executable, '-I', str(SKILL_DIR.parent / 'launch-fleet/scripts/ops-starts.py'), 'flags', '--repo',
                  REPO, 'fleet_thread']
        now = subprocess.run(reader, env=j.env(), cwd=j.dir, capture_output=True, text=True, timeout=60)
        self.assertEqual((now.returncode, now.stdout.strip()), (0, approved), 'the check passes while unchanged')
        j.world['files']['docs/agents/fleet.md'] = models_md(orchestrator=CLAUDE)
        j.save_world()
        moved = subprocess.run(reader, env=j.env(), cwd=j.dir, capture_output=True, text=True, timeout=60)
        self.assertEqual(moved.returncode, 0, moved.stderr)
        self.assertNotEqual(moved.stdout.strip(), approved, 'the check the handoff names catches the change')
        again = j.tool(YES)
        self.assertEqual(again.returncode, 5, again.stdout)
        self.assertIn('preview again and ask again', again.stdout)


class Resume(unittest.TestCase):
    """#1183: a fresh session resumes the first fleet from the private state alone.
    `next` reads only that state and names the first unfinished step."""

    def next(self, j, *more):
        before = j.state.read_bytes() if j.state.exists() else None
        lock = Path(str(j.state) + '.lock')
        locked = lock.exists()
        calls = (j.gh_creates(), j.logged(), j.spawns())
        result = j.helper(['next', *more])
        self.assertEqual(lock.exists(), locked, 'next opens nothing for writing, not even a lock')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(j.state.read_bytes() if j.state.exists() else None, before, 'next never writes the state')
        self.assertEqual((j.gh_creates(), j.logged(), j.spawns()), calls, 'next runs no gh, openwiz or room-cli')
        return result.stdout

    def test_a_fresh_session_resumes_at_the_first_unfinished_step(self):
        j = Journey(self)
        j.world['files']['docs/agents/fleet.md'] = models_md()
        j.save_world()
        seen = []
        for turn in JOURNEY['turns']:
            if not seen or seen[-1] != turn['step']:
                seen.append(turn['step'])
                expected = {'teach': 'where', 'run': 'where', 'start': 'project'}.get(turn['step'], turn['step'])
                self.assertEqual(self.next(j).splitlines()[0], 'Next: %s.' % expected, turn['step'])
            if 'plan' in turn:
                j.plan(turn['plan'])
            elif turn.get('approve'):
                j.approve()
            elif turn.get('world') == 'fleet_record':
                j.fleet_record()
            elif 'setup' in turn:
                j.write_setup(setup_state(turn['setup'], repository=REPO,
                                          settings=tuple(j.settings[k] for k in ('harness', 'model', 'effort'))))
            elif 'tool' in turn:
                j.tool(turn)
        self.assertIn('progress --spec 900', self.next(j))

    def test_an_interrupted_or_withdrawn_step_is_resumed_not_skipped(self):
        j = Journey(self)
        self.assertEqual(j.helper(['where', '--agents', 'cloud', '--yes']).returncode, 0)
        j.repos.write_text(github(create='lost', fail_after_create=2))
        self.assertEqual(j.helper(['create-repo', '--repo', REPO, '--yes']).returncode, 6)
        said = self.next(j)
        self.assertEqual(said.splitlines()[0], 'Next: project.')
        self.assertIn('create-repo --repo %s' % REPO, said)
        self.assertIn('reads before it creates', said)

        j = Journey(self)
        j.replay(until='launch')
        self.assertEqual(j.tool(PREVIEW).returncode, 12)
        self.assertEqual(j.tool(YES).returncode, 0)
        said = self.next(j)
        self.assertEqual(said.splitlines()[0], 'Next: launch.')
        self.assertIn("finish launch-fleet's start path", said)
        self.assertIn('never start it a second way', said)

        j.write_setup(setup_state(overrides={'personal_github': 'identity_no_push'}))
        self.assertEqual(j.helper(['continue']).returncode, 5)
        self.assertEqual(self.next(j).splitlines()[0], 'Next: connect.', 'a withdrawn setup is connected again')


    def test_an_existing_repository_prepared_before_continue_resumes_at_connect(self):
        j = Journey(self)
        self.assertEqual(j.helper(['where', '--agents', 'cloud', '--yes']).returncode, 0)
        other = 'synthetic-owner/synthetic-existing'
        bound = j.helper(['select', '--repo', other])
        self.assertEqual(bound.returncode, 0, bound.stdout)
        j.write_setup(setup_state(repository=other))
        for more in ((), ('--setup-state', str(j.setup_dir))):
            said = self.next(j, *more)
            self.assertEqual(said.splitlines()[0], 'Next: connect.', said)
            self.assertIn('Repository: %s.' % other, said)
            self.assertIn('run continue', said)
        self.assertEqual(j.helper(['select', '--repo', REPO]).returncode, 5, 'one repository per onboarding')
        self.assertEqual(j.helper(['create-repo', '--repo', REPO, '--yes']).returncode, 5, 'and no demo beside it')
        self.assertEqual(j.gh_creates(), [], 'nothing created')

    def test_a_prepared_repository_is_never_taken_as_this_onboardings_selection(self):
        j = Journey(self)
        self.assertEqual(j.helper(['where', '--agents', 'cloud', '--yes']).returncode, 0)
        previous = 'synthetic-owner/previous-project'
        j.write_setup(setup_state(repository=previous))
        said = self.next(j, '--setup-state', str(j.setup_dir))
        self.assertEqual(said.splitlines()[0], 'Next: project.', said)
        self.assertNotIn('Repository:', said)
        self.assertIn(previous, said, 'the candidate is named for the owner to confirm')
        self.assertIn('select --repo %s' % previous, said)
        (j.setup_dir / 'setup/state.json').chmod(0o644)
        self.assertNotIn(previous, self.next(j, '--setup-state', str(j.setup_dir)),
                         'a setup store others can read or replace is never trusted')

    def test_a_local_choice_resumes_at_choose_the_agents_until_its_builder_tables_read_back(self):
        j = Journey(self)
        j.replay(until='agents')
        state = json.loads(j.state.read_text())
        state['host'] = {'agents': 'local', 'harnesses': ['codex']}  # where --agents local --yes, recorded
        state['mode'] = {'harness': 'codex', 'mode': 'workspace-write'}  # mode --mode, the owner's pick
        j.state.write_text(json.dumps(state))
        j.world['files']['docs/agents/fleet.md'] = fleet_md(builder=CLAUDE, small=CLAUDE)
        j.save_world()
        self.assertEqual(j.helper(['choose', '--from-setup']).returncode, 0)
        said = self.next(j)
        self.assertEqual(said.splitlines()[0], 'Next: agents.', said)
        self.assertIn('on this machine', said)
        self.assertIn("fleet's settings on the default branch", said)
        self.assertEqual(json.loads(j.state.read_text())['choices'], dict(j.settings, agents='local'),
                         'the recorded answer survives the restart')
        j.world['files']['docs/agents/fleet.md'] = models_md()
        j.save_world()
        self.assertEqual(j.helper(['choose', '--from-setup']).returncode, 0)
        self.assertEqual(self.next(j).splitlines()[0], 'Next: setting.', 'the host setting follows the agents (#1358)')

    def test_a_cloud_choice_resumes_at_choose_the_agents_until_its_builder_tables_read_back(self):
        j = Journey(self)
        j.replay(until='agents')
        j.world['files']['docs/agents/fleet.md'] = fleet_md(builder=CLAUDE, small=CLAUDE)
        j.save_world()
        chosen = j.helper(['choose', '--from-setup', '--agents', 'cloud'])
        self.assertEqual(chosen.returncode, 0, chosen.stdout)
        said = self.next(j)
        self.assertEqual(said.splitlines()[0], 'Next: agents.', said)
        self.assertIn("fleet's settings on the default branch", said)
        self.assertEqual(json.loads(j.state.read_text())['choices'], dict(j.settings, agents='cloud'),
                         'the recorded choice survives the restart')
        j.world['files']['docs/agents/fleet.md'] = models_md()
        j.save_world()
        self.assertEqual(self.next(j).splitlines()[0], 'Next: agents.', 'only a read-back settles the tables')
        again = j.helper(['choose', '--from-setup', '--agents', 'cloud'])
        self.assertEqual(again.returncode, 0, again.stdout)
        self.assertEqual(self.next(j).splitlines()[0], 'Next: setting.', 'the host setting follows the agents (#1358)')
        self.assertEqual({k: v for k, v in json.loads(j.state.read_text())['choices'].items() if k in j.settings},
                         j.settings, 'the read-back keeps the recorded choice')


    def test_a_recorded_launch_resumes_before_the_agent_checks(self):
        def older(j):
            state = json.loads(j.state.read_text())
            state['choices'].pop('builder_tables', None)
            j.state.write_text(json.dumps(state))
        j = Journey(self)
        j.replay()
        older(j)
        self.assertEqual(self.next(j).splitlines()[0], 'Next: watch.')
        k = Journey(self)
        k.replay(until='launch')
        self.assertEqual(k.tool(PREVIEW).returncode, 12)
        self.assertEqual(k.tool(YES).returncode, 0)
        older(k)
        said = self.next(k)
        self.assertEqual(said.splitlines()[0], 'Next: launch.', said)
        self.assertIn('never start it a second way', said)

    def test_a_connected_repository_outlives_a_withdrawn_setup_after_an_absent_demo(self):
        j = Journey(self)
        self.assertEqual(j.helper(['where', '--agents', 'cloud', '--yes']).returncode, 0)
        other = 'synthetic-owner/synthetic-existing'
        j.repos.write_text(github(create='fail'))
        self.assertEqual(j.helper(['create-repo', '--repo', REPO, '--yes']).returncode, 5)
        j.write_setup(setup_state(repository=other))
        self.assertEqual(j.helper(['continue']).returncode, 0, j.calls[-1][1].stdout)
        j.write_setup(setup_state(repository=other, overrides={'personal_github': 'identity_no_push'}))
        self.assertEqual(j.helper(['continue']).returncode, 5)
        said = self.next(j)
        self.assertEqual(said.splitlines()[0], 'Next: connect.', said)
        self.assertIn(other, said)
        creates = [c[1] for c in j.gh_creates()].count('create')
        second = j.helper(['create-repo', '--repo', 'synthetic-owner/second-demo', '--yes'])
        self.assertEqual(second.returncode, 5, second.stdout)
        self.assertIn(other, second.stdout)
        self.assertEqual([c[1] for c in j.gh_creates()].count('create'), creates, 'no second repository')


BRAIN_BRANCH = 'openwiz/brain'
BRAIN_PULL = 'https://github.com/%s/pull/940' % REPO
BRAIN_FILES = {'.openwiz/brain/README.md': '# Brain\n\nSynthetic.\n',
               '.openwiz/brain/settings.json': '{"brain_location": "in_repository"}\n'}
FAKE_INIT = ('import json\nFOLDER = ".openwiz/brain"\n\n\ndef files(brain):\n'
             '    return {FOLDER + "/README.md": "# Brain\\n\\nSynthetic.\\n",\n'
             '            FOLDER + "/settings.json": json.dumps({"brain_location": brain["location"]}) + "\\n"}\n')
INIT_OPERATION = 'a' * 32
SETUP_FILES = ('docs/agents/fleet.md', 'docs/agents/issue-tracker.md', 'docs/agents/triage-labels.md',
               'docs/agents/domain.md')


ISSUES_GH = r"""
import json, os, re, sys
path, fake, lose, argv = sys.argv[1], sys.argv[2], sys.argv[3] == '1', sys.argv[4:]
repo = 'synthetic-owner/synthetic-sheep'
issues = json.loads(open(path).read())
if argv[:1] == ['api'] and len(argv) == 2 and re.fullmatch(
        r'repos/%s/issues\?state=open&creator=synthetic-owner&per_page=100' % re.escape(repo), argv[1]):
    print(json.dumps([{'number': i['number'], 'title': i['title'], 'state': 'open',
                       'user': {'login': 'synthetic-owner'}} for i in issues]))
    sys.exit(0)
if argv[:4] == ['api', '-X', 'POST', 'repos/%s/issues' % repo]:
    fields = dict(value.split('=', 1) for value in argv[5::2])
    issues.append({'number': 31 + len(issues), 'title': fields['title']})
    open(path, 'w').write(json.dumps(issues))
    if lose:
        sys.stderr.write('gh: synthetic lost reply (HTTP 502)\n')
        sys.exit(1)
    print(json.dumps({'number': issues[-1]['number'], 'title': fields['title'], 'state': 'open'}))
    sys.exit(0)
os.execv(sys.executable, [sys.executable, '-I', '-S', fake] + argv)
"""


class OneSetupPullRequest(unittest.TestCase):
    def road(self, files=None, brain='in_repository', pull='open', setup=True):
        j = Journey(self)
        (j.dir / 'bin/room-cli').unlink()
        j.extra_env['OPENWIZ_LOCAL_STATE'] = str(j.dir / 'host-state')
        value = {'repo': REPO, 'host': {'agents': 'local', 'harnesses': ['claude-code', 'codex']}}
        if setup:
            value['service'] = {'repo': REPO, 'state': 'opened', 'number': 7}
        j.state.write_text(json.dumps(value))
        j.state.chmod(0o600)
        options = offering(OPUS, SOL)
        options['source'] = 'local'
        j.options.write_text(json.dumps(options))
        j.build = j.dir / 'build'
        (j.build / 'runtime/setup').mkdir(parents=True)
        (j.build / 'runtime/setup/init.py').write_text(FAKE_INIT)
        if files is not None:
            j.world['files'] = files
        if brain == 'in_repository':
            j.world['branches'] = {BRAIN_BRANCH: dict(j.world['files'], **BRAIN_FILES)}
            j.world['host_pulls'] = [{'head': BRAIN_BRANCH, 'state': 'OPEN', 'url': BRAIN_PULL}]
            j.world['onboard_pulls'] = [{'number': 940, 'url': BRAIN_PULL, 'state': 'OPEN',
                                         'headRefName': BRAIN_BRANCH, 'baseRefName': 'main',
                                         'isCrossRepository': False}]
        j.save_world()
        if setup:
            self.applied(j, brain=brain, pull=pull)
        self.assertIsNone(shutil.which('room-cli', path=j.env()['PATH']))
        return j

    def applied(self, j, brain='in_repository', pull='open', identity='personal_login'):
        state = setup_state(settings=OPUS, identity=identity, brain=brain, overrides={'cloudroom': 'cloudroom_not_needed'})
        state['project'].update(host='local', project=None, answer_thread=None)
        if brain:
            state['operations'] = [{'operation_id': INIT_OPERATION, 'kind': 'prepare_project', 'phase': 'applied',
                                    'fingerprint': 'b' * 64, 'effects': ['Synthetic.'],
                                    'reason': 'Brain proposed. Merge its pull request to accept it.'}]
            number = 940 if brain == 'in_repository' else 3
            journal = {'schema': 'openwiz.init-journal.v1', 'operations': {INIT_OPERATION: {
                'rows': [], 'pull': {'number': number, 'state': pull}, 'wrote': True}}}
            path = j.setup_dir / 'setup/init.json'
        j.write_setup(state)
        if brain:
            path.write_text(json.dumps(journal))
            path.chmod(0o600)
        return state

    def issues(self, j, existing=(), lose_reply=False):
        j.issues_path = j.dir / 'service-issues.json'
        j.issues_path.write_text(json.dumps(list(existing)))
        script = j.dir / 'issues_gh.py'
        script.write_text(ISSUES_GH)
        (j.dir / 'bin/gh').write_text('#!/bin/sh\nexec "%s" -I -S "%s" "%s" "%s" %s "$@"\n' % (
            sys.executable, script, j.issues_path, FAKE_GH, '1' if lose_reply else '0'))

    def opened(self, j):
        return [i for i in json.loads(j.issues_path.read_text()) if i['title'] == 'OpenWiz service records']

    def saved(self, j):
        return json.loads(j.state.read_text())

    def world(self, j):
        return json.loads(j.world_path.read_text())

    def yes(self, j, *flags):
        shown = j.helper(['defaults', '--options', str(j.options), *flags])
        self.assertEqual(shown.returncode, 12, shown.stdout + shown.stderr)
        digest = re.search(r'--confirm ([0-9a-f]{64})\b', shown.stdout)
        self.assertIsNotNone(digest, shown.stdout)
        said = j.helper(['defaults', '--options', str(j.options), *flags, '--yes', '--confirm', digest[1]])
        self.assertEqual(said.returncode, 0, said.stdout + said.stderr)
        return said

    def setting(self, j, *more):
        return j.helper(['setting', '--setup-state', str(j.setup_dir), '--build', str(j.build), *more])

    def test_the_defaults_are_one_block_and_one_yes_records_all_of_them(self):
        j = self.road()
        shown = j.helper(['defaults', '--options', str(j.options)])
        self.assertEqual(shown.returncode, 12, shown.stdout + shown.stderr)
        lines = shown.stdout.splitlines()
        block = [line for line in lines if line.startswith('- ')]
        self.assertEqual(block, [
            '- Operator: synthetic-owner, your GitHub login',
            '- Service issue: a new issue in %s, "OpenWiz service records"' % REPO,
            '- Builder: claude-code claude-opus-5-5 medium',
            '- Reviewer: codex syn-codex-model-01 high',
            '- Acting identity: your own GitHub login, synthetic-owner, instead of the OpenWiz GitHub App, for the '
            'first fleet'], shown.stdout)
        self.assertEqual(sum('?' in line for line in lines), 1, 'one question for the whole block')
        self.assertNotIn('defaults', self.saved(j), 'the preview records nothing')
        self.assertNotRegex(shown.stdout, r'(?i)permission mode', 'the mode is never in the block')
        self.yes(j)
        self.assertEqual(self.saved(j)['defaults'], {
            'operator': 'synthetic-owner', 'service_issue': 'new', 'harness': OPUS[0], 'model': OPUS[1],
            'effort': OPUS[2], 'reviewer': list(CODEX), 'identity': 'personal_login'},
            "the project's own other-family Reviewer stays, as choose keeps it")
        self.yes(j, '--operator', 'synthetic-other', '--service-issue', '7', '--app', '--harness', SOL[0], '--model',
                 SOL[1], '--effort', SOL[2])
        self.assertEqual(self.saved(j)['defaults'], {
            'operator': 'synthetic-other', 'service_issue': 7, 'harness': SOL[0], 'model': SOL[1], 'effort': SOL[2],
            'reviewer': list(CLAUDE), 'identity': 'app'}, 'any line the user changes, and the reviewer follows')

    def test_the_first_fleet_recommends_the_own_login_on_every_host(self):
        j = self.road()
        value = self.saved(j)
        value['host'] = {'agents': 'cloud'}
        j.state.write_text(json.dumps(value))
        cloud = j.helper(['defaults', '--options', str(j.options)])
        self.assertEqual(cloud.returncode, 12, cloud.stdout + cloud.stderr)
        self.assertIn('- Acting identity: your own GitHub login, synthetic-owner, instead of the OpenWiz GitHub App, '
                      'for the first fleet', cloud.stdout)
        self.yes(j)
        self.assertEqual(self.saved(j)['defaults']['identity'], 'personal_login', 'CloudRoom too: own login')
        self.yes(j, '--app')
        self.assertEqual(self.saved(j)['defaults']['identity'], 'app', '--app picks the App')
        self.assertEqual(j.helper(['defaults', '--options', str(j.options), '--login']).returncode, 2,
                         'no flag for what is already the default')
        local = self.road()
        self.yes(local)
        self.assertEqual(self.saved(local)['defaults']['identity'], 'personal_login')

    def test_the_block_discloses_every_effect_its_one_yes_covers(self):
        j = self.road()
        shown = j.helper(['defaults', '--options', str(j.options)])
        self.assertEqual(shown.returncode, 12, shown.stdout + shown.stderr)
        effects = [line for line in shown.stdout.splitlines() if re.match(r'[0-9]\. ', line)]
        self.assertEqual(len(effects), 5, shown.stdout)
        for words in ('"OpenWiz service records"', 'setup.py prepare', 'github_login.py skip-app', 'openwiz init',
                      'labels', "brain's pull request", 'docs/agents/host.md', 'Models table'):
            self.assertIn(words, '\n'.join(effects), shown.stdout)

    def test_the_permission_mode_is_asked_once_before_the_merge_with_no_recommendation(self):
        j = self.road()
        self.yes(j)
        asked = j.helper(['mode'])
        self.assertEqual(asked.returncode, 12, asked.stdout + asked.stderr)
        self.assertNotRegex(asked.stdout, r'(?i)recommend')
        for name in ('default', 'acceptEdits', 'bypassPermissions', 'read-only', 'workspace-write'):
            self.assertIn('- %s: ' % name, asked.stdout)
        picked = j.helper(['mode', '--claude-mode', 'acceptEdits', '--codex-mode', 'workspace-write'])
        self.assertEqual(picked.returncode, 0, picked.stdout + picked.stderr)
        self.assertEqual(self.saved(j)['mode']['modes'], {'claude': 'acceptEdits', 'codex': 'workspace-write'})

    def test_setup_opens_exactly_one_pull_request_with_the_brain_models_host_and_mode(self):
        j = self.road()
        said = [self.yes(j), j.helper(['mode', '--claude-mode', 'acceptEdits', '--codex-mode', 'workspace-write'])]
        preview = self.setting(j)
        self.assertEqual(preview.returncode, 12, preview.stdout + preview.stderr)
        self.assertIn(BRAIN_BRANCH, preview.stdout)
        opened = self.setting(j, '--yes')
        self.assertEqual(opened.returncode, 0, opened.stdout + opened.stderr)
        self.assertIn(BRAIN_PULL, opened.stdout)
        world = self.world(j)
        self.assertEqual(world['host_pulls'], [{'head': BRAIN_BRANCH, 'state': 'OPEN', 'url': BRAIN_PULL}],
                         'exactly one pull request: the brain\'s')
        self.assertEqual(sorted(world['branches']), [BRAIN_BRANCH], 'no second setup branch')
        branch = world['branches'][BRAIN_BRANCH]
        self.assertEqual({k: branch[k] for k in BRAIN_FILES}, BRAIN_FILES, 'the brain stays as init proposed it')
        self.assertIn('\nHost: local\n', branch['docs/agents/host.md'])
        fleet = branch['docs/agents/fleet.md']
        self.assertEqual(ModelsTable.models(self, fleet), {'Orchestrator': OPUS, 'Builder': OPUS, 'Reviewer': CODEX,
                                                           'Small builder': None, 'Fixer': None})
        self.assertIn('| Harness permission mode (claude) | `acceptEdits` |', fleet)
        self.assertIn('| Harness permission mode (codex) | `workspace-write` |', fleet)
        self.assertEqual(sorted(set(branch) - set(FILES) - set(BRAIN_FILES)), ['docs/agents/host.md'])
        self.assertEqual(sorted(k for k in FILES if branch[k] != FILES[k]), ['docs/agents/fleet.md'])
        self.assertEqual(self.saved(j)['setting']['pull'], BRAIN_PULL)
        for result in said:
            self.assertNotRegex(result.stdout, r'(?i)\bmerge', 'only the one setup pull request asks for a merge')
        merged = {k: branch[k] for k in ('docs/agents/host.md', 'docs/agents/fleet.md')}
        j.origin_write(merged)
        world['files'].update(branch)
        world['host_pulls'][0]['state'] = 'MERGED'
        world['onboard_pulls'][0]['state'] = 'MERGED'
        j.world = world
        j.save_world()
        carried = j.helper(['continue', '--explained'])
        self.assertEqual(carried.returncode, 0, carried.stdout + carried.stderr)
        self.assertEqual(j.helper(['grill', '--confirmed', GRILL]).returncode, 0)
        read = j.helper(['choose', '--from-setup'])
        self.assertEqual(read.returncode, 0, read.stdout + read.stderr)
        self.assertIn('Read back', read.stdout)
        self.assertNotRegex(read.stdout, r'(?i)\bcommit|\bmerge it')
        self.assertEqual(self.saved(j)['choices']['builder_tables'], 'read')
        again = self.setting(j)
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertEqual(self.world(j)['host_pulls'], world['host_pulls'], 'nothing reopened')
        self.assertEqual(j.helper(['next']).stdout.splitlines()[0], 'Next: plan.')

    def test_a_readme_only_repository_gets_its_setup_files_in_the_one_setup_pull_request(self):
        j = self.road(files={'README.md': '# synthetic\n'})
        made = j.helper(['create-repo', '--repo', REPO, '--yes'])
        self.assertEqual(made.returncode, 0, made.stdout)
        seeded = json.loads(j.repos.read_text())['repos'][REPO.lower()]['branches']['main']
        world = self.world(j)
        world['files'] = dict(seeded)
        for name in world['branches']:
            world['branches'][name] = dict(seeded, **BRAIN_FILES)
        j.world = world
        j.save_world()
        self.yes(j)
        self.assertEqual(j.helper(['mode', '--claude-mode', 'acceptEdits', '--codex-mode', 'workspace-write'])
                         .returncode, 0)
        opened = self.setting(j, '--yes')
        self.assertEqual(opened.returncode, 0, opened.stdout + opened.stderr)
        world = self.world(j)
        self.assertEqual(world['host_pulls'], [{'head': BRAIN_BRANCH, 'state': 'OPEN', 'url': BRAIN_PULL}])
        branch = world['branches'][BRAIN_BRANCH]
        self.assertEqual(sorted(set(branch) - set(seeded) - set(BRAIN_FILES)),
                         sorted(SETUP_FILES + ('docs/agents/host.md',)))
        project = j.dir / 'merged'
        for name in SETUP_FILES:
            (project / name).parent.mkdir(parents=True, exist_ok=True)
            (project / name).write_text(branch[name])
        check = subprocess.run([sys.executable, '-I', str(SETTINGS), 'check', '--root', str(project)],
                               capture_output=True, text=True, timeout=60)
        self.assertEqual(check.returncode, 0, check.stdout)
        fleet = branch['docs/agents/fleet.md']
        self.assertEqual(ModelsTable.models(self, fleet), {'Orchestrator': OPUS, 'Builder': OPUS, 'Reviewer': SOL,
                                                           'Small builder': None, 'Fixer': None})
        self.assertIn('| Harness permission mode (claude) | `acceptEdits` |', fleet)
        self.assertIn('| Record authors | `synthetic-owner` |', fleet)
        self.assertTrue(connect_usable(fleet), "setup.py check's fleet_settings_usable reads the new fleet.md")
        self.assertIn('| 1 | root | `python3 -m unittest discover -s tests` | `check` |', fleet)
        self.assertIn('| `check` | 1 |', fleet)
        self.assertNotRegex(''.join(branch[n] for n in SETUP_FILES), r'<[^>\n]*>', 'no template placeholder left')
        self.assertIn('\nHost: local\n', branch['docs/agents/host.md'])

    def test_an_existing_repository_without_tests_or_ci_is_named_never_seeded(self):
        j = self.road(files={'README.md': '# synthetic\n'})
        before = self.world(j)
        shown = j.helper(['defaults', '--options', str(j.options)])
        self.assertEqual(shown.returncode, 5, shown.stdout)
        for words in ('no test command or CI check', 'one passing test and a CI workflow with a job named check',
                      'setup skill', 'Nothing recorded'):
            self.assertIn(words, shown.stdout)
        self.assertNotIn('defaults', self.saved(j))
        self.assertEqual(self.world(j), before, 'nothing written to the repository')
        self.assertEqual(json.loads(j.repos.read_text())['log'], [], 'no test or workflow added')

    def test_a_companion_brain_merged_by_init_leaves_one_setup_pull_request(self):
        for pull, said in (('merged', 'already merged'), ('open', 'https://github.com/%s-brain/pull/3' % REPO)):
            j = self.road(brain='companion', pull=pull)
            self.yes(j)
            self.assertEqual(j.helper(['mode', '--claude-mode', 'acceptEdits', '--codex-mode', 'workspace-write'])
                             .returncode, 0)
            opened = self.setting(j, '--yes')
            self.assertEqual(opened.returncode, 0, opened.stdout + opened.stderr)
            self.assertEqual([p['head'] for p in self.world(j)['host_pulls']], ['openwiz/host-setting'])
            self.assertIn(said, opened.stdout)
            if pull == 'merged':
                self.assertNotIn('pull/3', opened.stdout, 'a merged brain pull request is done, never asked for')

    def test_a_write_cut_short_on_the_brains_branch_is_completed_on_the_retry(self):
        j = self.road()
        self.yes(j)
        self.assertEqual(j.helper(['mode', '--claude-mode', 'acceptEdits', '--codex-mode', 'workspace-write'])
                         .returncode, 0)
        mark = j.dir / 'fail-fleet-put'
        mark.write_text('')
        (j.dir / 'bin/gh').write_text(
            '#!/bin/sh\ncase "$*" in *"-X PUT repos/%s/contents/docs/agents/fleet.md"*)\n'
            '  if [ -e "%s" ]; then rm "%s"; echo "gh: synthetic server error (HTTP 502)" >&2; exit 1; fi;;\n'
            'esac\nexec "%s" -I -S "%s" "$@"\n' % (REPO, mark, mark, sys.executable, FAKE_GH))
        cut = self.setting(j, '--yes')
        self.assertEqual(cut.returncode, 6, cut.stdout + cut.stderr)
        branch = self.world(j)['branches'][BRAIN_BRANCH]
        self.assertIn('docs/agents/host.md', branch)
        self.assertEqual(branch['docs/agents/fleet.md'], FILES['docs/agents/fleet.md'])
        again = self.setting(j, '--yes')
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertIn(BRAIN_PULL, again.stdout)
        fleet = self.world(j)['branches'][BRAIN_BRANCH]['docs/agents/fleet.md']
        self.assertIn('| Harness permission mode (codex) | `workspace-write` |', fleet)
        self.assertEqual(self.world(j)['host_pulls'], [{'head': BRAIN_BRANCH, 'state': 'OPEN', 'url': BRAIN_PULL}])

    def test_resume_after_the_blocks_yes_runs_its_unapplied_operations_first(self):
        j = self.road(setup=False)
        self.yes(j)
        first = j.helper(['next', '--setup-state', str(j.setup_dir)])
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(first.stdout.splitlines()[0], 'Next: connect.', first.stdout)
        self.assertIn('service-issue --yes', first.stdout)
        refused = self.setting(j, '--yes')
        self.assertEqual(refused.returncode, 5, refused.stdout + refused.stderr)
        self.issues(j, existing=[{'number': 7, 'title': 'OpenWiz service records'}])
        self.assertEqual(j.helper(['service-issue', '--yes']).returncode, 0)
        second = j.helper(['next', '--setup-state', str(j.setup_dir)]).stdout
        self.assertIn('setup.py prepare', second)
        self.assertIn('--service-issue 7 ', second)
        state = self.applied(j, brain=None)
        resumed = j.helper(['next', '--setup-state', str(j.setup_dir)]).stdout
        self.assertEqual(resumed.splitlines()[0], 'Next: connect.', resumed)
        self.assertIn('openwiz init', resumed)
        self.assertEqual(self.setting(j, '--yes').returncode, 5)
        self.assertEqual(self.world(j)['host_pulls'], [{'head': BRAIN_BRANCH, 'state': 'OPEN', 'url': BRAIN_PULL}],
                         'no pull request before init ran')
        self.assertEqual(self.world(j)['branches'][BRAIN_BRANCH], dict(FILES, **BRAIN_FILES), 'nothing written')
        self.applied(j)
        self.assertEqual(j.helper(['next', '--setup-state', str(j.setup_dir)]).stdout.splitlines()[0], 'Next: mode.')
        self.assertTrue(state)

    def test_a_resumed_connect_reuses_the_service_issue_it_already_opened(self):
        j = self.road(setup=False)
        self.issues(j)
        self.yes(j)
        opened = j.helper(['service-issue', '--yes'])
        self.assertEqual(opened.returncode, 0, opened.stdout + opened.stderr)
        self.assertEqual([i['number'] for i in self.opened(j)], [31])
        resumed = j.helper(['next', '--setup-state', str(j.setup_dir)])
        self.assertEqual(resumed.stdout.splitlines()[0], 'Next: connect.', resumed.stdout)
        self.assertIn('--service-issue 31', resumed.stdout, 'resume names the issue already opened')
        self.applied(j)
        earlier = j.helper(['next', '--setup-state', str(j.setup_dir)]).stdout
        self.assertIn('setup.py prepare', earlier, 'an earlier prepare for issue 7 is not taken as issue 31')
        self.assertIn('--service-issue 31', earlier)
        again = j.helper(['service-issue', '--yes'])
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertEqual([i['number'] for i in self.opened(j)], [31], 'a resumed step 1 opens no second issue')
        j = self.road(setup=False)
        self.issues(j, existing=[{'number': 12, 'title': 'OpenWiz service records'}])
        self.yes(j)
        found = j.helper(['service-issue', '--yes'])
        self.assertEqual(found.returncode, 0, found.stdout + found.stderr)
        self.assertEqual([i['number'] for i in self.opened(j)], [12], 'an issue opened before is reused')
        self.assertIn('--service-issue 12', j.helper(['next', '--setup-state', str(j.setup_dir)]).stdout)
        j = self.road(setup=False)
        self.issues(j, lose_reply=True)
        self.yes(j)
        lost = j.helper(['service-issue', '--yes'])
        self.assertEqual(lost.returncode, 6, lost.stdout + lost.stderr)
        self.issues(j, existing=self.opened(j))
        settled = j.helper(['service-issue', '--yes'])
        self.assertEqual(settled.returncode, 0, settled.stdout + settled.stderr)
        self.assertEqual([i['number'] for i in self.opened(j)], [31], 'a lost reply is read back, never sent again')

    def test_the_yes_binds_the_block_the_user_saw(self):
        j = self.road()
        shown = j.helper(['defaults', '--options', str(j.options)])
        self.assertIn('- Builder: claude-code claude-opus-5-5 medium', shown.stdout)
        digest = re.search(r'--confirm ([0-9a-f]{64})\b', shown.stdout)
        options = offering(SOL)
        options['source'] = 'local'
        options['harnesses'] = [h for h in options['harnesses'] if h['provider'] == 'codex']
        j.options.write_text(json.dumps(options))
        bare = j.helper(['defaults', '--options', str(j.options), '--yes'])
        self.assertNotEqual(bare.returncode, 0, bare.stdout)
        self.assertNotIn('defaults', self.saved(j), 'a yes without the preview it answers records nothing')
        self.assertIsNotNone(digest, shown.stdout)
        stale = j.helper(['defaults', '--options', str(j.options), '--yes', '--confirm', digest[1]])
        self.assertEqual(stale.returncode, 5, stale.stdout + stale.stderr)
        self.assertIn('- Builder: codex gpt-6.2-sol medium', stale.stdout, 'the new block is shown to ask again')
        self.assertNotIn('defaults', self.saved(j), 'a changed block needs a fresh yes')

    def test_the_reviewer_line_takes_its_own_change(self):
        j = self.road()
        flags = ('--reviewer-harness', SOL[0], '--reviewer-model', SOL[1], '--reviewer-effort', SOL[2])
        shown = j.helper(['defaults', '--options', str(j.options), *flags])
        self.assertEqual(shown.returncode, 12, shown.stdout + shown.stderr)
        self.assertIn('- Reviewer: codex gpt-6.2-sol medium', shown.stdout)
        same = j.helper(['defaults', '--options', str(j.options), '--reviewer-harness', OPUS[0], '--reviewer-model',
                         OPUS[1], '--reviewer-effort', OPUS[2]])
        self.assertEqual(same.returncode, 5, 'a reviewer from the builder\'s family is refused')
        absent = j.helper(['defaults', '--options', str(j.options), '--reviewer-harness', 'codex', '--reviewer-model',
                           'gpt-6.2-sol', '--reviewer-effort', 'xhigh'])
        self.assertEqual(absent.returncode, 5, 'a reviewer the saved options do not offer is refused')
        self.yes(j, *flags)
        self.assertEqual(self.saved(j)['defaults']['reviewer'], list(SOL))
        self.assertEqual(j.helper(['mode', '--claude-mode', 'acceptEdits', '--codex-mode', 'workspace-write'])
                         .returncode, 0)
        self.assertEqual(self.setting(j, '--yes').returncode, 0)
        fleet = self.world(j)['branches'][BRAIN_BRANCH]['docs/agents/fleet.md']
        self.assertEqual(ModelsTable.models(self, fleet)['Reviewer'], SOL)

    def test_a_brain_proposal_holding_anything_else_is_never_written_to(self):
        for extra in ({'.openwiz/brain/decisions/note.md': 'An unrelated note.\n'},
                      {'.openwiz/brain/README.md': '# Brain\n\nChanged by hand.\n'}):
            j = self.road()
            j.world['branches'][BRAIN_BRANCH].update(extra)
            j.save_world()
            before = self.world(j)['branches'][BRAIN_BRANCH]
            self.yes(j)
            self.assertEqual(j.helper(['mode', '--claude-mode', 'acceptEdits', '--codex-mode', 'workspace-write'])
                             .returncode, 0)
            refused = self.setting(j, '--yes')
            self.assertEqual(refused.returncode, 5, refused.stdout + refused.stderr)
            self.assertIn(next(iter(extra)), refused.stdout + refused.stderr)
            self.assertEqual(self.world(j)['branches'][BRAIN_BRANCH], before, 'nothing written to the proposal')
        j = self.road()
        j.world['onboard_pulls'][0]['baseRefName'] = 'elsewhere'
        j.save_world()
        self.yes(j)
        self.assertEqual(j.helper(['mode', '--claude-mode', 'acceptEdits', '--codex-mode', 'workspace-write'])
                         .returncode, 0)
        self.assertEqual(self.setting(j, '--yes').returncode, 5, 'a brain pull request onto another base')
        self.assertNotIn('docs/agents/host.md', self.world(j)['branches'][BRAIN_BRANCH])

    def test_a_driver_host_puts_its_models_table_and_host_in_the_brains_pull_request(self):
        j = self.road()
        state = self.saved(j)
        state['host'] = {'agents': 'boat', 'harnesses': []}
        j.state.write_text(json.dumps(state))
        setup = json.loads((j.setup_dir / 'setup/state.json').read_text())
        setup['project']['host'] = 'boat'
        j.write_setup(setup)
        self.yes(j)
        self.assertEqual(j.helper(['mode']).returncode, 5, 'a permission mode is for this machine only')
        opened = self.setting(j, '--yes')
        self.assertEqual(opened.returncode, 0, opened.stdout + opened.stderr)
        world = self.world(j)
        self.assertEqual(world['host_pulls'], [{'head': BRAIN_BRANCH, 'state': 'OPEN', 'url': BRAIN_PULL}])
        branch = world['branches'][BRAIN_BRANCH]
        self.assertIn('\nHost: boat\n', branch['docs/agents/host.md'])
        self.assertEqual(ModelsTable.models(self, branch['docs/agents/fleet.md'])['Builder'], OPUS)
        self.assertNotIn('Harness permission mode', branch['docs/agents/fleet.md'])


if __name__ == '__main__':
    unittest.main()
