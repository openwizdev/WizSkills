#!/usr/bin/env python3
"""The install skill's first-fleet checks (#1108, joined to install in #636). Standard library only.

  first_fleet.py where --state FILE [--agents HOST] [--build DIR] [--yes]
  first_fleet.py continue --state FILE --setup-state DIR [--explained]
  first_fleet.py decisions --state FILE --setup-state DIR [--yes]
  first_fleet.py create-repo --state FILE --repo OWNER/NAME [--yes]
  first_fleet.py select --state FILE --repo OWNER/NAME
  first_fleet.py mode --state FILE [--mode MODE]
  first_fleet.py setting --state FILE [--yes]
  first_fleet.py grill --state FILE --confirmed URL
  first_fleet.py choose --state FILE --options FILE (--harness P --model M --effort E | --from-setup) [--agents HOST]
  first_fleet.py spec --state FILE --spec N --repo OWNER/NAME
  first_fleet.py launch --state FILE --spec N [--heartbeat] [--yes --confirm DIGEST]
  first_fleet.py progress --state FILE --spec N --openwiz PROGRAM
  first_fleet.py first-merge --state FILE --pr N
  first_fleet.py next --state FILE [--setup-state DIR]

The onboarding road (#1358): `where` offers every host this OpenWiz can run
agents on (DW9, #2006): Cloudroom, and each driver the installed build carries
that answers `version` (driver v1), this machine's local driver and boat.dev's
included; a driver whose `version` fails is not offered, and it says why. It
records the user's pick (--agents HOST: `cloud`, or a driver's name) only on
their answer (--yes), after checking what that needs and printing the
teacher's walk-through for anything missing; it never runs a sign-in. On this machine `mode` lists
the harness's permission modes, each explained, picks none, and records the
one the owner names (J254 A); KN3's driver passes it unchanged. `setting` writes that choice to
the project's host setting, docs/agents/host.md (records v1, section 6), as one
pull request the user merges, only on --yes: its `Host: <driver>` line is the
one launch-fleet reads; Cloudroom needs no file. `grill`
records the private comment URL of the user's yes to the grill in chat; the
plan then approves itself by its checks (to-tickets' machine plan approval),
and no plan approval is asked. `first-merge` reads a merged pull request back
from GitHub and prints the teacher's merged line and closing offer.

It adds no approval, planner or engine. `continue` carries what install and
setup already recorded in the installed OpenWiz state (DIR is its `<state>`):
the private brain `openwiz init` made, the prepared harness, model and effort,
and whether install already gave the explanation. It reads current setup
evidence only and refuses, naming each one, when a prerequisite is missing,
refused, unknown or out of date; it never fills one in. `create-repo` makes the
one disposable demo repository, private, with the user's own gh identity, only
on --yes: it saves the name first, creates it with its disclosed initial README
commit in that one create (#1074: init proposes the brain on its default
branch), reads back the repository, default branch and commit, and reads before
any retry of a create whose answer was lost. It never pushes into a repository.

`select` records the existing repository the owner confirmed, before Connect,
as this onboarding's one repository; it reads and changes nothing else.

`next` reads only the state file and prints the first unfinished step and
what to run there, so a fresh session resumes without repeating an effect.
With --setup-state it also reads, never writes, the repository setup
prepared: for the selected repository that is Connect's progress; with no
selection it is only a candidate for the owner to confirm with `select`, since
setup may have prepared it for an earlier project (#1571).

The state file is private and owner-only; keep it outside the checkout. It
holds the user's choices, the carried setup facts, this onboarding's spec and
its one launch record.

Exits: 0 done; 1 a read failed; 2 usage; 5 refused, nothing started;
6 uncertain, never retried; 7 busy; 10 state unavailable; 12 preview, awaiting --yes.
"""
import base64
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import urllib.parse

LAUNCH_FLEET = Path(__file__).resolve().parents[2] / 'launch-fleet'
FLEET_SH = LAUNCH_FLEET / 'scripts/fleet.sh'
HOST_PY = LAUNCH_FLEET / 'scripts/host.py'
HEARTBEAT = LAUNCH_FLEET / 'scripts/heartbeat.py'
OPTIONS = {
    'where': ({'--state'}, {'--yes'}, {'--build', '--agents'}),
    'mode': ({'--state'}, set(), {'--mode', '--claude-mode', '--codex-mode'}),
    'setting': ({'--state'}, {'--yes'}, set()),
    'grill': ({'--state', '--confirmed'}, set(), set()),
    'first-merge': ({'--state', '--pr'}, set(), set()),
    'continue': ({'--state', '--setup-state'}, {'--explained'}, set()),
    'decisions': ({'--state', '--setup-state'}, {'--yes'}, set()),
    'create-repo': ({'--state', '--repo'}, {'--yes'}, set()),
    'select': ({'--state', '--repo'}, set(), set()),
    'choose': ({'--state', '--options'}, {'--from-setup'}, {'--harness', '--model', '--effort', '--agents'}),
    'spec': ({'--state', '--spec', '--repo'}, set(), set()),
    'launch': ({'--state', '--spec'}, {'--yes', '--heartbeat'}, {'--confirm'}),
    'progress': ({'--state', '--spec', '--openwiz'}, set(), set()),
    'next': ({'--state'}, set(), {'--setup-state'}),
}
FAMILY = {'claude-code': 'claude', 'codex': 'gpt'}
REVIEWER = {'claude': 'Reviewer for Claude-built', 'gpt': 'Reviewer for GPT-built'}
SETTINGS = Path(__file__).resolve().parents[2] / 'setup/scripts/settings.py'
FLEET_MD = Path('docs/agents/fleet.md')
OLDER = ('Builder', 'Builder for small tickets', REVIEWER['claude'], REVIEWER['gpt'], 'Fixer')
RECOMMENDED = {'claude': ('claude-code', 'claude-opus-5-5', 'medium'), 'gpt': ('codex', 'gpt-6.2-sol', 'medium')}
WRITTEN_NAMES = {'claude-code': 'Claude Code', 'codex': 'Codex', 'claude-opus-5-5': 'Opus 5.5',
                 'claude-sonnet-5-5': 'Sonnet 5.5', 'gpt-6.2-sol': 'Sol 6.2'}
STATES = ('ready', 'building', 'in_review', 'changes_requested', 'merged', 'held', 'blocked')
NOTHING = 'nothing started.'
# setup.v1's current-evidence window and its codes that establish `verified`.
CURRENT_MS = 60 * 60 * 1000
DRIFT_MS = 5 * 60 * 1000
VERIFIED = {'cloudroom': 'cloudroom_login_verified', 'personal_github': 'identity_verified',
            'github_app': 'app_verified', 'project': 'project_verified'}
NAMES = {'cloudroom': 'CloudRoom', 'harness': 'Agent harness', 'personal_github': 'Personal GitHub',
         'github_app': 'OpenWiz GitHub App', 'project': 'Project'}
REPOSITORY = r'[A-Za-z0-9][-A-Za-z0-9]*/[-A-Za-z0-9_.]+'
FLEET_RECORD = 'launch-fleet: fleet active, loop fleet-'
GRILL = r'https://github\.com/[A-Za-z0-9-]+/[A-Za-z0-9_.-]+/(issues|pull)/[1-9][0-9]*#issuecomment-[1-9][0-9]*'
TEACH = Path(__file__).resolve().parents[1] / 'teach.md'
# Harnesses this machine can run, by setup's provider name: the local driver's harness program (#1368).
PROGRAMS = {'claude-code': 'claude', 'codex': 'codex'}
HOST_FILE = 'docs/agents/host.md'
DRIVER_NAME = r'[a-z0-9]+(?:-[a-z0-9]+)*'
VERSION_WAIT = 60
PROBE_ENV = ('PATH', 'HOME', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TMPDIR')
RECORDS = r'openwiz:records v[1-9][0-9]{0,2}'
CAN = ('start', 'wake', 'stop', 'many-at-once', 'own-sandbox')
LOGIN_LINE = 'https://github.com/openwizdev/OpenWiz/blob/main/adapters/%s/README.md'
HOSTS = {
    'local': {'label': 'this machine', 'where': 'on this machine'},
    'boat': {'label': 'boat.dev, each agent in its own cloud sandbox', 'where': 'on boat.dev',
             'program': 'boat', 'link': 'https://boat.dev',
             'then': 'Then sign in to boat yourself, and connect GitHub and your harness in its dashboard.',
             'login': 'Login: held by boat.dev. Sign in to boat yourself, then connect GitHub and the key or '
                      "subscription for your harness in boat.dev's dashboard (Agents & Proxying); OpenWiz never "
                      'touches that login.',
             'ask': 'Have you signed in to boat.dev and connected GitHub and your harness in its dashboard?',
             'run': 'Agents run on boat.dev, many at once, each in its own sandbox, through the boat CLI you are '
                    'signed into.',
             'cost': 'boat.dev bills per second while each sandbox runs, against your boat plan, and model-provider '
                     'charges are separate'},
}
NOT_HOSTS = ('cloud', 'cloudroom', 'template')
HOST_BRANCH = 'openwiz/host-setting'


class Exit(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def strict(text):
    """One JSON value; a repeated key anywhere is refused."""
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('duplicate key')
            value[key] = item
        return value
    return json.loads(text, object_pairs_hook=pairs)


def parse(argv):
    if not argv or argv[0] not in OPTIONS:
        raise Exit(2, 'usage: first_fleet.py where|continue|decisions|create-repo|select|mode|setting|grill|choose|spec|launch|'
                      'progress|first-merge|next ... (see its header)')
    values, switches, optional = OPTIONS[argv[0]]
    got, rest = {}, argv[1:]
    while rest:
        name = rest.pop(0)
        if name in got or (name not in values | optional and name not in switches):
            raise Exit(2, 'usage: unknown or repeated option %s' % name)
        if name in switches:
            got[name] = True
            continue
        if not rest:
            raise Exit(2, 'usage: %s needs a value' % name)
        got[name] = rest.pop(0)
    missing = sorted(values - set(got))
    if missing:
        raise Exit(2, 'usage: missing %s' % ', '.join(missing))
    if argv[0] == 'choose':
        named = {'--harness', '--model', '--effort'} & set(got)
        if got.get('--from-setup') and named or not got.get('--from-setup') and len(named) != 3:
            raise Exit(2, 'usage: choose takes --harness, --model and --effort, or --from-setup for the ones '
                          'setup already recorded')
    if '--spec' in got and not re.fullmatch(r'[1-9][0-9]{0,9}', got['--spec']):
        raise Exit(2, 'usage: --spec takes an issue number')
    if argv[0] == 'launch' and ('--confirm' in got) != bool(got.get('--yes')) or not re.fullmatch(r'[0-9a-f]{64}', got.get('--confirm', '0' * 64)):
        raise Exit(2, 'usage: --yes takes --confirm with the digest of the preview the user said yes to')
    if '--build' in got and not os.path.isabs(got['--build']):
        raise Exit(2, 'usage: --build takes the verified install\'s build folder by absolute path')
    if '--pr' in got and not re.fullmatch(r'[1-9][0-9]{0,9}', got['--pr']):
        raise Exit(2, 'usage: --pr takes a pull request number')
    if '--confirmed' in got and not re.fullmatch(GRILL, got['--confirmed']):
        raise Exit(2, "usage: --confirmed takes the private comment URL of the user's yes to the grill")
    if '--repo' in got and not re.fullmatch(REPOSITORY, got['--repo']):
        raise Exit(2, 'usage: --repo takes owner/name')
    if '--agents' in got and (not re.fullmatch(DRIVER_NAME, got['--agents']) or len(got['--agents']) > 40):
        raise Exit(2, 'usage: --agents is cloud or a driver\'s name, as where lists them')
    if argv[0] == 'where' and got.get('--yes') and '--agents' not in got:
        raise Exit(2, 'usage: where --yes takes the --agents the user picked')
    if '--setup-state' in got and not os.path.isabs(got['--setup-state']):
        raise Exit(2, 'usage: --setup-state takes the installed state folder by absolute path')
    if '--openwiz' in got:
        program = got['--openwiz']
        if not os.path.isabs(program) or not os.path.isfile(program) or not os.access(program, os.X_OK):
            raise Exit(2, 'usage: --openwiz takes the installed program by absolute path')
    return argv[0], got


class State:
    """The private state file, held under its lock for the whole command."""

    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_absolute():
            raise Exit(2, 'usage: --state takes an absolute path')
        try:
            self.lock = os.open(str(self.path) + '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        except OSError:
            raise Exit(10, 'The onboarding state is unavailable; ' + NOTHING)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Exit(7, 'Another onboarding command is using this state; ' + NOTHING)
        self.value = self.read()

    def read(self):
        try:
            info = os.lstat(self.path)
        except FileNotFoundError:
            return {}
        except OSError:
            raise Exit(10, 'The onboarding state is unreadable; ' + NOTHING)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise Exit(10, 'The onboarding state must be an owner-only regular file; ' + NOTHING)
        try:
            value = strict(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            raise Exit(10, 'The onboarding state is unreadable; ' + NOTHING)
        known = {'created', 'choices', 'repo', 'spec', 'launch', 'setup', 'host', 'setting', 'grill', 'merge', 'preview', 'mode'}
        if not isinstance(value, dict) or set(value) - known:
            raise Exit(10, 'The onboarding state has an unknown shape; ' + NOTHING)
        return value

    def save(self):
        temp = self.path.with_name(self.path.name + '.new')
        try:
            fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(self.value, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
            return True
        except OSError:
            try:
                os.unlink(temp)
            except OSError:
                pass
            return False


def run(argv, env=None, timeout=600, stdin=None):
    try:
        return subprocess.run(argv, capture_output=True, timeout=timeout, env=env, stdin=stdin)
    except (OSError, subprocess.TimeoutExpired):
        return None


# --- The teacher (teach.md, #1359) -------------------------------------------

def teach(heading, fill=(), which=0):
    """teach.md's line under `## heading`, each `<...>` filled in order and the rest of its words kept."""
    try:
        section = TEACH.read_text(encoding='utf-8').split('\n## ' + heading + '\n', 1)[1].split('\n## ', 1)[0]
        line = [text[2:] for text in section.split('\n') if text.startswith('> ')][which]
    except (OSError, IndexError):
        raise Exit(1, "The teacher's lines (teach.md) are unreadable; " + NOTHING)
    holes = re.findall(r'`?<[^>]+>`?', line)
    if len(holes) != len(fill):
        raise Exit(1, "teach.md's %s line has %d blanks, not %d; %s" % (heading, len(holes), len(fill), NOTHING))
    fill = list(fill)
    return re.sub(r'`?<[^>]+>`?', lambda _: fill.pop(0), line)


# --- Other tickets' interfaces (#1358) ------------------------------------------
# KN3's local driver (#1368, OpenWiz #1455, merged as 583f2ae) and KN6's host
# setting reader (#1371, WizSkills #64), both merged; nothing here is a stub.

def adapters_of(got, env):
    """The host drivers' folder: the verified build's `runtime/adapters` (install.v1), else OPENWIZ_ADAPTERS."""
    if got.get('--build'):
        return str(Path(got['--build']) / 'runtime/adapters')
    return env.get('OPENWIZ_ADAPTERS') or None


def driver_answer(env, adapters, name):
    """A driver's `version` answer (driver v1, D1), or the reason it has none, as (answer, None) or (None, why).

    The driver is `<adapters>/<name>/driver`: the verified build's `runtime/adapters`, which launch-fleet's
    host.py finds through OPENWIZ_ADAPTERS. Only `version` is called here: it starts nothing. The reason never
    quotes the driver's own words, which may name a private path or account."""
    adapters = adapters or ''
    path = Path(adapters, name, 'driver')
    if not os.path.isabs(adapters) or not path.is_file() or not os.access(path, os.X_OK):
        return None, 'there is no runnable driver'
    probe = {k: env[k] for k in PROBE_ENV if k in env}
    result = run([str(path), 'version'], probe, timeout=VERSION_WAIT, stdin=subprocess.DEVNULL)
    if result is None:
        return None, 'its `version` did not answer'
    if result.returncode != 0:
        return None, 'its `version` failed (exit %d); run it by hand to see why' % result.returncode
    try:
        version = strict(result.stdout.decode('utf-8'))
        assert isinstance(version, dict) and set(version) == {'driver', 'records', 'can'}
        assert isinstance(version['driver'], str) and re.fullmatch(DRIVER_NAME, version['driver'])
        assert len(version['driver']) <= 40
        records, can = version['records'], version['can']
        assert isinstance(records, list) and records and len(set(map(str, records))) == len(records)
        assert all(isinstance(r, str) and re.fullmatch(RECORDS, r) for r in records)
        assert 'openwiz:records v1' in records
        assert isinstance(can, list) and len(set(map(str, can))) == len(can)
        assert all(isinstance(c, str) and c in CAN for c in can) and {'start', 'wake', 'stop'} <= set(can)
    except (AssertionError, UnicodeDecodeError, ValueError, TypeError):
        return None, "its `version` answer is not driver v1's"
    if version['driver'] != name:
        return None, 'its `version` names another driver'
    return version, None


def local_driver(env, adapters):
    """KN3's local driver (#1368, OpenWiz 583f2ae): its `version` answer, or None."""
    return driver_answer(env, adapters, 'local')[0]


def installed_drivers(env, adapters):
    """Every driver in the build's adapters folder, by name, each its `version` answer or why not (DW9, #2006).

    Cloudroom is offered as `cloud`, launch-fleet's own route with no host file, so its driver and the name
    `cloud` are not listed; `template` is the copyable example driver, not a host."""
    try:
        names = sorted(p.name for p in Path(adapters).iterdir() if p.name not in NOT_HOSTS
                       and re.fullmatch(DRIVER_NAME, p.name) and len(p.name) <= 40 and Path(p, 'driver').exists()) \
            if adapters and os.path.isabs(adapters) else []
    except OSError:
        names = []
    return {name: driver_answer(env, adapters, name) for name in names}


def host_label(agents):
    return 'Cloudroom' if agents == 'cloud' else HOSTS.get(agents, {}).get('label', agents)


def where_of(agents):
    return 'in Cloudroom' if agents == 'cloud' else HOSTS.get(agents, {}).get('where', 'on ' + agents)


def host_cost(agents):
    if agents == 'cloud':
        return 'it uses your Cloud Credits, unknown until measured, and model-provider charges are separate'
    return HOSTS.get(agents, {}).get('cost', '%s charges as its own plan says, unknown until measured, and '
                                             'model-provider charges are separate' % agents)


def host_setting(env):
    """KN6 (#1371): the host docs/agents/host.md names on the default branch, or None when it names none.

    Read by launch-fleet's own reader, `host.py which` (records v1, section 6), from this checkout's origin,
    so the onboarding and the fleet read the same setting the same way."""
    result = run([sys.executable, '-I', str(HOST_PY), 'which'], env)
    if result is None:
        raise Exit(1, 'Could not read the host setting (%s); %s' % (HOST_FILE, NOTHING))
    out = result.stdout.decode('utf-8', 'replace').strip()
    why = result.stderr.decode('utf-8', 'replace').strip().removeprefix('host.py: ')
    if result.returncode == 2 and 'needs exactly one' in why:
        raise Exit(5, '%s; fix it, or ask to change that line; %s' % (why, NOTHING))
    named = re.fullmatch(r'host: ([a-z0-9]+(?:-[a-z0-9]+)*)', out) if result.returncode == 0 else None
    if not named:
        raise Exit(1, 'Could not read the host setting (%s): %s; %s' % (HOST_FILE, why or 'no answer', NOTHING))
    return None if named[1] == 'none' else named[1]


# The harness permission mode the owner picks once (J254 A), saved where KN3's merged driver (OpenWiz
# 583f2ae, adapters/local) reads it, the repository's docs/agents/fleet.md, as exactly one row
# `| Harness permission mode | `<mode>` |` whose value is one plain word; the driver passes it to the
# harness unchanged (`claude --permission-mode`, `codex --sandbox`) and starts nothing without it.
MODE_FILE = 'docs/agents/fleet.md'
MODE_ROW = '| Harness permission mode |'
MODE_VALUE = r'[A-Za-z][A-Za-z0-9_-]{0,39}'
MODES = {
    'claude-code': [
        ('default', 'it stops and waits for a person before each edit or command, so an unattended builder stalls'),
        ('acceptEdits', 'it edits files on its own and still asks before running a command'),
        ('bypassPermissions', 'it edits files and runs any command without asking anyone')],
    'codex': [
        ('read-only', 'it reads files and can change nothing, so a builder cannot write its code'),
        ('workspace-write', 'it edits files and runs commands inside its own working folder only'),
        ('danger-full-access', 'it edits any file and runs any command on this machine, with no sandbox')],
}


def mode_rows(text):
    """KN3's permission-mode rows in a fleet.md text, each as its value, or None for one it can't read."""
    rows = [line for line in (text or '').splitlines() if line.startswith(MODE_ROW)]
    values = [re.findall(r'`([^`]*)`', row) for row in rows]
    return [v[0] if len(v) == 1 and re.fullmatch(MODE_VALUE, v[0]) else None for v in values]


def saved_rows(env):
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location('launch_fleet_host', HOST_PY)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        module.SETTING = Path(MODE_FILE)
        text = module.setting_text()
    except Exception as error:
        raise Exit(1, 'Could not read %s from the default branch: %s; %s' % (MODE_FILE, error, NOTHING))
    return [line.rstrip() for line in (text or '').splitlines() if line.startswith(MODE_ROWS)]


MODE_ROWS = '| Harness permission mode'
MODE_FLAGS = {'claude': '--claude-mode', 'codex': '--codex-mode'}
HARNESS_OF = {program: harness for harness, program in PROGRAMS.items()}


def routed(host, harness):
    both = host.get('agents') == 'local' and {'claude-code', 'codex'} <= set(host.get('harnesses') or ())
    return ['claude-code', 'codex'] if both else [harness]


def picked_modes(state):
    saved = state.value.get('mode') or {}
    if isinstance(saved.get('modes'), dict):
        return dict(saved['modes'])
    return {PROGRAMS[saved['harness']]: saved['mode']} if saved.get('mode') else {}


def kept(modes):
    return {'modes': modes} if len(modes) > 1 else {}


def mode_lines(modes):
    if len(modes) == 1:
        return ['%s `%s` |' % (MODE_ROW, mode) for mode in modes.values()]
    return ['%s (%s) | `%s` |' % (MODE_ROWS, program, modes[program]) for program in sorted(modes)]


# KN3's host-side approval (security R6, option A): the same pick saved on the owner's machine, per
# repository and harness, outside the repository, in the merged driver's form (OpenWiz 583f2ae):
# $OPENWIZ_LOCAL_STATE/approvals.json (default ~/.local/state/openwiz-local), one JSON object
# {"owner/name": {"claude"|"codex": "<mode>"}}, the user's own, mode 600. KN3's start refuses unless the
# fleet.md row matches it, or if others can change the file.
def approval_file(env):
    folder = env.get('OPENWIZ_LOCAL_STATE') or os.path.expanduser('~/.local/state/openwiz-local')
    return Path(folder) / 'approvals.json'


def read_approvals(env):
    """The approvals file's text and value, (None, {}) when there is none; Exit when KN3 would refuse it."""
    path = approval_file(env)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None, {}
    except OSError:
        raise Exit(5, "This machine's approvals file (%s) is unreadable; fix it as the local driver's README shows, "
                      'then run this again; %s' % (path, NOTHING))
    with os.fdopen(fd, encoding='utf-8', newline='') as handle:  # every byte as it is, line endings too
        info, text = os.fstat(handle.fileno()), handle.read()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise Exit(5, "Others can change this machine's approvals file (%s), so the local driver won't trust it. "
                      'The owner makes it theirs and owner-only (chmod 600) themselves and checks what it approves, '
                      'then runs this again; OpenWiz never changes its mode; %s' % (path, NOTHING))
    try:
        value = strict(text)
        assert isinstance(value, dict)
    except (ValueError, AssertionError):
        raise Exit(5, "This machine's approvals file (%s) is not one JSON object with each key once; fix it as the "
                      "local driver's README shows, then run this again; %s" % (path, NOTHING))
    return text, value


def host_approval(env, repo, program):
    """The mode this machine approves for this repository and harness, or None."""
    entry = read_approvals(env)[1].get(repo)
    mode = entry.get(program) if isinstance(entry, dict) else None
    return mode if isinstance(mode, str) and re.fullmatch(MODE_VALUE, mode) else None


def splice(text, repo, program, picked):
    """text with only "repo": {"program": "picked"} added; every other byte kept."""
    decoder, space = json.JSONDecoder(), re.compile(r'[ \t\n\r]*')
    at = space.match(text, 0).end()
    if text[at] != '{':
        raise ValueError('not an object')
    top = at
    at = space.match(text, at + 1).end()
    empty, target = text[at] == '}', None
    while not empty:
        if text[at] != '"':
            raise ValueError('not a key')
        key, at = json.decoder.scanstring(text, at + 1)
        at = space.match(text, at).end()
        if text[at] != ':':
            raise ValueError('no colon')
        at = space.match(text, at + 1).end()
        if key == repo:
            target = at
        at = decoder.raw_decode(text, at)[1]
        at = space.match(text, at).end()
        if text[at] == ',':
            at = space.match(text, at + 1).end()
        elif text[at] == '}':
            break
        else:
            raise ValueError('no comma')
    pair = '%s: %s' % (json.dumps(program), json.dumps(picked))
    if target is not None:
        if text[target] != '{':
            raise ValueError('not an object entry')
        inner = space.match(text, target + 1).end()
        return text[:target + 1] + pair + ('' if text[inner] == '}' else ', ') + text[target + 1:]
    return text[:top + 1] + '%s: {%s}' % (json.dumps(repo), pair) + ('' if empty else ', ') + text[top + 1:]


APPROVALS_WAIT = 120  # seconds another onboarding session may hold the approvals lock


def approve_host(env, repo, program, picked):
    """Save the owner's pick as this machine's approval: add only this entry, never change or widen another.

    The whole read, splice and rename runs under one lock beside the file (approvals.json.lock), which every
    onboarding session takes, so two sessions never lose each other's entry; the result is read back."""
    path = approval_file(env)
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock = os.open(str(path) + '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    except OSError:
        raise Exit(10, "Could not open this machine's approvals lock; nothing recorded.")
    try:
        waited = 0.0
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if waited >= APPROVALS_WAIT:
                    raise Exit(7, "Another onboarding session is still saving this machine's approvals; run this "
                                  'again; nothing recorded.')
                time.sleep(0.2)
                waited += 0.2
        approve_locked(env, path, repo, program, picked)
    finally:
        os.close(lock)


def approve_locked(env, path, repo, program, picked):
    text, approvals = read_approvals(env)
    entry = approvals.get(repo)
    if entry is not None and not isinstance(entry, dict):
        raise Exit(5, "This machine's approvals file has an entry for %s in another form; ask the owner to fix it; "
                      'nothing recorded.' % repo)
    have = (entry or {}).get(program)
    if have == picked:
        return
    if have is not None:
        raise Exit(5, 'This machine already approves %s for %s with %s; OpenWiz never changes or widens it. Ask the '
                      'owner which mode they mean; nothing recorded.' % (have, repo, program))
    want = json.loads(json.dumps(approvals))
    want.setdefault(repo, {})[program] = picked
    try:
        new = splice(text, repo, program, picked) if text is not None else json.dumps(want, indent=2) + '\n'
        assert strict(new) == want
    except (ValueError, IndexError, AssertionError):
        raise Exit(5, "This machine's approvals file can't take one more entry without changing others; ask the "
                      'owner to add %s: {%s: %s} themselves; nothing recorded.' % (
                          json.dumps(repo), json.dumps(program), json.dumps(picked)))
    temp = None
    try:
        fd, temp = tempfile.mkstemp(prefix='.approvals.', suffix='.new', dir=path.parent)
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as handle:  # write the bytes exactly
            os.fchmod(handle.fileno(), 0o600)
            handle.write(new)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except OSError:
        if temp is not None:
            try:
                os.unlink(temp)
            except OSError:
                pass
        raise Exit(10, "Could not save this machine's host-side approval; nothing recorded.")
    if read_approvals(env) != (new, want):
        raise Exit(6, "This machine's approvals file did not read back as written; check it before running this "
                      'again.')


def mode_section(modes):
    return ('\n## Harness permission mode\n\nThe mode the owner picked for agents on this machine; the local '
            'driver passes it to the harness unchanged. To change it, ask your agent to edit %s.\n\n'
            '| Setting | Value |\n| --- | --- |\n%s\n' % (
                'this one row' if len(modes) == 1 else 'that harness\'s row', '\n'.join(mode_lines(modes))))


# --- Where agents run (#1358) ---------------------------------------------------

def where(got):
    """Offer every host this OpenWiz can run agents on (DW9), check what the pick needs, print the walk-through for
    anything missing, and record the pick on --yes."""
    state = State(got['--state'])
    agents, env = got.get('--agents'), gh_env()
    adapters = adapters_of(got, env)
    found = installed_drivers(env, adapters)
    offered = [name for name in ['local'] + sorted(n for n in found if n != 'local')
               if name in found and found[name][0] is not None]
    print("Where agents can run, from this OpenWiz's drivers:")
    if 'local' in offered:
        print('- local: %s' % host_label('local'))
    print('- cloud: Cloudroom, many at once, on your Cloud Credits')
    for name in offered:
        if name != 'local':
            print('- %s: %s' % (name, host_label(name)))
    for name, (_, why) in sorted(found.items()):
        if why:
            print('Not offered: %s: %s.' % (name, why))
    if agents is None:
        print("Nothing recorded. Reuse the user's host choice if known and offered here. With no choice, offer "
              'the listed hosts. Then run again with --agents <its name>.')
        return 12
    missing = []
    login = run(['gh', 'api', 'user', '--jq', '.login'], env)
    if login is None or login.returncode != 0 or not login.stdout.strip():
        missing.append(('a GitHub sign-in', 'https://github.com/login',
                        'Then run `gh auth login` yourself in a terminal on this machine.'))
    harnesses = []
    if agents == 'local':
        harnesses = sorted(h for h, program in PROGRAMS.items() if shutil.which(program, path=env.get('PATH')))
        if not harnesses:
            missing.append(('Claude Code or Codex installed and signed in on this machine',
                            'https://docs.anthropic.com/en/docs/claude-code/setup', None))
    elif agents == 'cloud':
        if not shutil.which('room-cli', path=env.get('PATH')):
            missing.append(('the Cloudroom app, signed in', 'https://cloudroom.dev', None))
    elif HOSTS.get(agents, {}).get('program') and not shutil.which(HOSTS[agents]['program'], path=env.get('PATH')):
        known = HOSTS[agents]
        missing.append(('the %s CLI, signed in' % known['program'], known['link'], known['then']))
    if missing:
        for what, link, then in missing:
            print(teach('Where agents run', (what, link), which=1))
            if then:
                print(then)
        raise Exit(5, 'Nothing recorded: run this again once the user says done.')
    if agents == 'local' and 'local' not in offered:
        raise Exit(5, "This OpenWiz has no local driver to run agents on this machine (pass the verified install's "
                      "--build, or update OpenWiz); choose another host, or stop; nothing recorded.")
    if agents != 'cloud' and agents not in offered:
        raise Exit(5, 'This OpenWiz offers no %s driver that answers (see above); choose a host it offers, or stop; '
                      'nothing recorded.' % agents)
    if agents == 'local':
        print('Agents run on this machine through OpenWiz\'s local driver, with %s you are signed into, while this '
              'machine is awake. Their model use is billed by that harness, as it is today.' % ', '.join(harnesses))
    elif agents == 'cloud':
        print('Agents run in Cloudroom, many at once. They use your Cloud Credits: unknown until measured. '
              'Model-provider charges are separate.')
    else:
        known = HOSTS.get(agents, {})
        print(known.get('run', "Agents run through OpenWiz's %s driver." % agents))
        print('Cost: %s.' % host_cost(agents))
        print(known.get('login', "Login: where %s's driver says, in the Login line of %s. Sign in there yourself; "
                                 'OpenWiz never touches that login.' % (agents, LOGIN_LINE % agents)))
        print(known.get('ask', 'Have you signed in to %s as that Login line says?' % agents))
    print('OpenWiz is free now.')
    if not got.get('--yes'):
        if agents == 'cloud':
            print("Nothing recorded. Ask where agents run; on the user's yes, run again with that --agents and --yes.")
        else:
            print("Nothing recorded. On the user's yes to the effects and cost above, run again with the same "
                  '--agents and --yes.')
        return 12
    if state.value.get('launch'):
        raise Exit(5, 'This onboarding already launched its fleet; ask to change the host setting instead.')
    state.value['host'] = {'agents': agents, 'harnesses': harnesses}
    if agents != 'cloud':
        state.value['host']['adapters'] = adapters
    state.value.pop('setting', None)
    if not state.save():
        raise Exit(10, 'Could not save where agents run; nothing recorded.')
    print('Recorded: agents run %s.' % where_of(agents))
    return 0


# --- The continuation from install and setup (#636) ----------------------

def setup_facts(folder, chosen_host):
    """What the installed setup recorded and currently verifies, or Exit naming
    each prerequisite that is not verified now. Reads the setup store only."""
    path = Path(folder) / 'setup/state.json'
    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise Exit(10, "OpenWiz's setup state must be an owner-only file; " + NOTHING)
        value = strict(path.read_text(encoding='utf-8'))
        assert value['schema'] == 'openwiz.setup-state.v1' and type(value['revision']) is int
        observations, project = value['observations'], value['project']
        assert isinstance(observations, dict) and (project is None or isinstance(project, dict))
        if project is not None:
            assert all(isinstance(project[k], str) and project[k]
                       for k in ('repository', 'harness', 'model', 'effort'))
            assert re.fullmatch(REPOSITORY, project['repository'])
            host = project.get('host', 'cloud')
            assert isinstance(host, str) and len(host) <= 40 and re.fullmatch(DRIVER_NAME, host) and host != 'cloudroom'
            if host == 'cloud':
                assert isinstance(project['project'], str) and project['project']
            else:
                assert project['project'] is None and project['answer_thread'] is None
        identity, brain = value.get('identity'), value.get('brain')
        assert identity is None or (isinstance(identity, dict) and isinstance(identity['selected'], str)
                                    and (identity['acting_login'] is None or isinstance(identity['acting_login'], str)))
        assert brain is None or (isinstance(brain, dict) and all(
            isinstance(brain[k], str) for k in ('location', 'code_repository', 'brain_repository'))
            and (brain['decision_repositories'] is None or isinstance(brain['decision_repositories'], dict)))
    except FileNotFoundError:
        raise Exit(5, 'Setup has not run in this OpenWiz state yet; run the setup check first; ' + NOTHING)
    except (OSError, ValueError, KeyError, TypeError, AssertionError):
        raise Exit(10, "OpenWiz's setup state is unreadable; " + NOTHING)
    if project is None:
        raise Exit(5, 'Setup has no prepared project: prepare it (setup.py prepare) and check again; ' + NOTHING)
    if host != chosen_host:
        raise Exit(5, 'Setup prepared host %s, but this fleet chose %s; run setup.py prepare --host %s and check '
                   'again; %s' % (host, chosen_host, chosen_host, NOTHING))
    repository = project['repository']
    if not (identity and identity.get('repository') == repository):
        identity = None
    skipped = bool(identity and identity['selected'] == 'personal_login' and identity.get('app_choice') == 'skip'
                   and identity['acting_login'])
    now = int(time.time() * 1000)

    def state(component):
        seen = observations.get(component)
        if not isinstance(seen, dict) or not isinstance(seen.get('code'), str):
            return 'missing', 'not checked yet'
        current = (seen.get('revision') == value['revision'] and type(seen.get('at')) is int
                   and seen['at'] <= now + DRIFT_MS and now - seen['at'] <= CURRENT_MS)
        if not current:
            return 'unknown', 'its last check is out of date or for another selection'
        if seen['code'] == VERIFIED.get(component):
            return 'verified', None
        return ('unknown' if seen['code'].endswith('_unreadable') else 'not verified'), seen['code']

    needed = (['cloudroom'] if host == 'cloud' else []) + ['personal_github', 'project']
    if not skipped:
        needed.append('github_app')
    problems = []
    for component in needed:
        found, why = state(component)
        if found != 'verified':
            problems.append('%s: %s (%s)' % (NAMES[component], found, why))
    harness, why = state('harness')
    if harness == 'verified' or why == 'harness_listed':
        harness_line = ('listed by CloudRoom' if host == 'cloud' else 'installed on this computer')
        harness_line += '; its login is not proven by setup'
    else:
        problems.append('%s: %s (%s)' % (NAMES['harness'], harness, why))
    if brain is None or brain['code_repository'].lower() != repository.lower():
        problems.append('Private brain: missing (run openwiz init for %s, then the setup check)' % repository)
    elif brain['location'] == 'companion' and not decisions_pair(folder, brain['decision_repositories']):
        problems.append("Decisions repository pair: not configured (the private settings' decision_repositories "
                        'must name %s as public and %s as private, so Decisions reads the companion)'
                        % (repository, brain['brain_repository']))
    if problems:
        raise Exit(5, 'Setup is not ready for the first fleet: %s; %s' % ('; '.join(problems), NOTHING))
    acting = ('%s, your personal GitHub login (the App is skipped)' % identity['acting_login'] if skipped
              else 'your OpenWiz GitHub App')
    facts = {'setup_state': str(folder), 'repository': repository, 'project': project['project'],
            'settings': {k: project[k] for k in ('harness', 'model', 'effort')},
            'identity': {'selected': 'personal_login' if skipped else 'app', 'acting': acting},
            'brain': {'location': brain['location'], 'repository': brain['brain_repository']},
            'harness': harness_line}
    if host != 'cloud':
        facts['host'] = host
    return facts


def decisions_pair(folder, pair):
    """Whether the existing private settings (service/config.json, decisions.v1's
    repository roles) name exactly the brain's public/private pair. Read only."""
    try:
        settings = strict((Path(folder) / 'service/config.json').read_text(encoding='utf-8'))
        configured = settings['decision_repositories']
        name = lambda roles, role: '%s/%s' % (roles[role]['owner'], roles[role]['name'])
        return all(name(configured, r).lower() == name(pair, r).lower() for r in ('public', 'private'))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def connect_decisions(got):
    """A public repository's companion brain, connected to Decisions through the
    existing private settings: decisions.v1's `decision_repositories` pair in
    <state>/service/config.json. Only that key is written; every other byte of an
    existing settings file stays. Preview first; --yes writes it once."""
    folder = Path(got['--setup-state'])
    try:
        value = strict((folder / 'setup/state.json').read_text(encoding='utf-8'))
        brain = value['brain']
        assert isinstance(brain, dict) and brain['location'] == 'companion'
        pair = brain['decision_repositories']
        assert set(pair) == {'public', 'private'}
    except (OSError, ValueError, KeyError, TypeError, AssertionError):
        raise Exit(5, 'Setup records no companion brain to connect; nothing changed.')
    if decisions_pair(folder, pair):
        print('Decisions already reads %s/%s with its companion.' % (pair['public']['owner'], pair['public']['name']))
        return 0
    path = folder / 'service/config.json'
    try:
        settings = strict(path.read_text(encoding='utf-8'))
        assert isinstance(settings, dict)
    except FileNotFoundError:
        settings = {}
    except (OSError, ValueError, AssertionError):
        raise Exit(10, 'The private settings file is unreadable; nothing changed.')
    print('Effect: set Decisions\' repository pair in the private settings: public %s/%s, private %s/%s. '
          'Nothing else changes.' % (pair['public']['owner'], pair['public']['name'],
                                     pair['private']['owner'], pair['private']['name']))
    if not got.get('--yes'):
        print("Nothing changed. On the user's yes to exactly this, run again with --yes.")
        return 12
    settings['decision_repositories'] = pair
    temp = None
    try:
        path.parent.mkdir(mode=0o700, exist_ok=True)
        # Review R6: a staging file of its own for each attempt (owner-only,
        # created exclusively), so one left by an interrupted attempt never
        # blocks this one; nothing else in the folder is touched.
        fd, temp = tempfile.mkstemp(prefix='config.json.', suffix='.new', dir=path.parent)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(settings, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except OSError:
        if temp is not None:
            try:
                os.unlink(temp)
            except OSError:
                pass
        raise Exit(10, 'Could not write the private settings; nothing changed.')
    print('Decisions now reads the companion. Run the setup check, then run continue.')
    return 0


def withdraw(state):
    """A failed refresh withdraws launch eligibility; the owner's choices and work stay."""
    if 'setup' in state.value:
        del state.value['setup']
        state.save()


def refreshed(state, folder):
    """Setup's current facts, or Exit after withdrawing the carried setup."""
    try:
        return setup_facts(folder, (state.value.get('host') or {}).get('agents', 'cloud'))
    except Exit:
        withdraw(state)
        raise


def carry_on(got):
    state = State(got['--state'])
    facts = refreshed(state, got['--setup-state'])
    if state.value.get('repo') not in (None, facts['repository']):
        raise Exit(5, 'This onboarding is for %s, but setup selected %s; %s' % (
            state.value['repo'], facts['repository'], NOTHING))
    created = state.value.get('created')
    if created and created['state'] == 'created' and created['repo'] != facts['repository']:
        raise Exit(5, 'This onboarding created %s, but setup selected %s; %s' % (
            created['repo'], facts['repository'], NOTHING))
    earlier = state.value.get('setup') or {}
    facts['explained'] = bool(got.get('--explained') or earlier.get('explained'))
    state.value['setup'] = facts
    state.value['repo'] = facts['repository']
    if not state.save():
        raise Exit(10, 'Could not save the carried setup; ' + NOTHING)
    connection = 'agents on ' + facts['host'] if 'host' in facts else 'CloudRoom project ' + facts['project']
    print('Carried from setup: repository %s, %s.' % (facts['repository'], connection))
    print('Acting identity: %s.' % facts['identity']['acting'])
    print('Private brain: %s (%s).' % (facts['brain']['repository'], facts['brain']['location'].replace('_', ' ')))
    print('Prepared agents: %s %s %s; harness %s.' % (
        facts['settings']['harness'], facts['settings']['model'], facts['settings']['effort'], facts['harness']))
    print('Next: %s.' % ('the grill (the explanation is done)' if facts['explained'] else 'the explanation'))
    return 0


# --- The demo repository --------------------------------------------------

def gh_env():
    env = dict(os.environ)
    env.pop('GH_REPO', None)
    return env


def look(name):
    """The repository as GitHub shows it now, from reads only: 'absent', 'public',
    'empty' (private, but no default branch and commit read back) or
    {'branch', 'commit'} (private, its default branch at that commit). None when
    a read failed or answered something else: unknown, never success."""
    result = run(['gh', 'repo', 'view', name, '--json', 'nameWithOwner,isPrivate,defaultBranchRef'], gh_env())
    if result is None:
        return None
    if result.returncode != 0:
        return 'absent' if b'Could not resolve to a Repository' in result.stderr else None
    try:
        found = strict(result.stdout.decode('utf-8'))
        assert found['nameWithOwner'] == name and type(found['isPrivate']) is bool
        branch = (found['defaultBranchRef'] or {}).get('name') or ''
        assert isinstance(branch, str)
    except (UnicodeDecodeError, ValueError, KeyError, TypeError, AttributeError, AssertionError):
        return None
    if not found['isPrivate']:
        return 'public'
    if not branch:
        return 'empty'
    result = run(['gh', 'api', '--include', '-X', 'GET',
                  'repos/%s/git/ref/heads/%s' % (name, urllib.parse.quote(branch, safe='/'))], gh_env())
    if result is None:
        return None
    head, _, body = result.stdout.replace(b'\r\n', b'\n').partition(b'\n\n')
    status = re.match(rb'HTTP/[0-9.]+ ([0-9]{3})', head)
    if status is None:
        return None
    if status.group(1) in (b'404', b'409'):  # no such ref; 409 is GitHub's empty repository
        return 'empty'
    try:
        assert status.group(1) == b'200'
        commit = strict(body.decode('utf-8'))['object']['sha']
        assert isinstance(commit, str) and re.fullmatch('[0-9a-f]{40}', commit)
    except (UnicodeDecodeError, ValueError, KeyError, TypeError, AssertionError):
        return None
    return {'branch': branch, 'commit': commit}


def created_line(name, seen):
    return 'Created and read back: %s, private, default branch %s at commit %s.' % (
        name, seen['branch'], seen['commit'])


def create_repo(got):
    name = got['--repo']
    print('Effect: create one new private GitHub repository, %s, with your gh identity, in one GitHub create with '
          'its initial commit: a README.md holding only the title "# %s" on its default branch, which OpenWiz '
          'init needs to propose the brain. Nothing else is created or pushed; its CloudRoom project stays yours '
          'to make or pick.' % (name, name.split('/')[1]))
    if not got.get('--yes'):
        print("Nothing created. On the user's yes to exactly this, run again with --yes.")
        return 12
    state = State(got['--state'])
    if state.value.get('setup') and state.value['setup']['repository'] != name:
        raise Exit(5, 'Setup already selected %s for this onboarding; it makes no second repository.'
                   % state.value['setup']['repository'])
    if state.value.get('repo') not in (None, name):
        raise Exit(5, 'This onboarding is for %s; it makes no second repository.' % state.value['repo'])
    record = state.value.get('created')
    if record and record['repo'] != name and record['state'] != 'absent':
        raise Exit(5, 'This onboarding already made %s; it makes one demo repository.' % record['repo'])
    login = run(['gh', 'api', 'user', '--jq', '.login'], gh_env())
    if (login is None or login.returncode != 0
            or not re.fullmatch(rb'[A-Za-z0-9](-?[A-Za-z0-9])*', login.stdout.strip())):
        raise Exit(5, 'GitHub sign-in could not be verified. Complete the GitHub sign-in step first '
                      '(github_login.py sign-in), then run create-repo again; nothing created.')
    seen = look(name)
    if seen is None:
        raise Exit(1 if not record else 6, 'Could not read whether %s exists; nothing created.' % name)
    if record and record['repo'] == name and record['state'] in ('pending', 'uncertain', 'created'):
        if isinstance(seen, dict):
            state.value['created'] = {'repo': name, 'state': 'created', **seen}
            if not state.save():
                raise Exit(6, 'Could not save the created repository; it exists, so never create it again.')
            print(created_line(name, seen))
            return 0
        if seen == 'public':
            raise Exit(5, '%s is not the private repository this onboarding created; nothing created.' % name)
        if seen == 'empty':
            if record['state'] == 'created':
                raise Exit(5, '%s has no default branch and initial commit, which init needs; OpenWiz never pushes '
                              'one into an existing repository. Add a first commit yourself, or choose a new '
                              'name; nothing created.' % name)
            state.value['created'] = {'repo': name, 'state': 'uncertain'}
            state.save()
            raise Exit(6, '%s exists, but its default branch and initial commit did not read back; nothing more '
                          'was created or pushed. Run this again to read it back.' % name)
        if record['state'] == 'created':
            raise Exit(5, '%s is not the private repository this onboarding created; nothing created.' % name)
    elif seen != 'absent':
        raise Exit(5, '%s already exists; choose another name, or use it as an existing repository; '
                      'nothing created.' % name)
    state.value['created'] = {'repo': name, 'state': 'pending'}
    if not state.save():
        raise Exit(10, 'Could not save the repository name first; nothing created.')
    run(['gh', 'repo', 'create', name, '--private', '--add-readme'])
    seen = look(name)
    ended = 'created' if isinstance(seen, dict) else 'absent' if seen == 'absent' else 'uncertain'
    state.value['created'] = {'repo': name, 'state': ended, **(seen if ended == 'created' else {})}
    saved = state.save()
    if ended == 'created' and saved:
        print(created_line(name, seen))
        return 0
    if ended == 'absent' and saved:
        raise Exit(5, 'GitHub did not create %s; nothing created. Try again only after the user says yes again.' % name)
    raise Exit(6, 'Whether %s was created with its default branch and initial commit is uncertain; read it back '
                  'before any retry (run this again).' % name)


# --- The host setting (records v1, section 6) --------------------------------

def host_text(name='local'):
    what = ('`local` is the machine the agents run on' if name == 'local'
            else "`%s` is OpenWiz's %s driver" % (name, host_label(name).split(',')[0]))
    return ('# Where agents run\n\nOpenWiz starts, wakes and stops this project\'s agents through the host named '
            'below: a driver in OpenWiz\'s adapters/ folder. %s. To change it, ask your agent to edit this one '
            'line.\n\nHost: %s\n' % (what, name))


def raw(repo, path, env, ref=None):
    """A file's text on the default branch (or ref), None when it isn't there; Exit when unreadable."""
    target = 'repos/%s/contents/%s%s' % (repo, path, '?ref=' + ref if ref else '')
    result = run(['gh', 'api', '--include', target, '-H', 'Accept: application/vnd.github.raw+json'], env)
    text = result.stdout.decode('utf-8', 'replace').replace('\r\n', '\n') if result is not None else ''
    head, _, body = text.partition('\n\n')
    status = re.match(r'HTTP/[0-9.]+ ([0-9]{3})', head)
    if status and status[1] == '404':
        return None
    if result is None or result.returncode != 0 or not status or status[1] != '200':
        raise Exit(1, 'Could not read %s; nothing written.' % path)
    return body


def blob(repo, path, env, ref):
    """A file's text on ref and its blob SHA, from one read (None, None when it isn't there); Exit when unreadable."""
    result = run(['gh', 'api', '--include', 'repos/%s/contents/%s?ref=%s' % (repo, path, ref)], env)
    text = result.stdout.decode('utf-8', 'replace').replace('\r\n', '\n') if result is not None else ''
    head, _, body = text.partition('\n\n')
    status = re.match(r'HTTP/[0-9.]+ ([0-9]{3})', head)
    if status and status[1] == '404':
        return None, None
    try:
        assert result is not None and result.returncode == 0 and status and status[1] == '200'
        found = strict(body)
        assert found['type'] == 'file' and found['encoding'] == 'base64'
        assert re.fullmatch(r'[0-9a-f]{40}', found['sha'])
        data = base64.b64decode(found['content'], validate=False)
        return data.decode('utf-8', 'replace').replace('\r\n', '\n'), found['sha']
    except (AssertionError, ValueError, KeyError, TypeError):
        raise Exit(1, 'Could not read %s on %s; nothing written.' % (path, ref))


def pull_diff(repo, env, want):
    """R4: the host-setting branch's whole diff against the default branch must be exactly the approved changes
    (each file in want added or changed to its approved text, and nothing else); Exit 5 naming a file that differs."""
    base = run(['gh', 'api', 'repos/%s' % repo, '--jq', '.default_branch'], env)
    branch = base.stdout.decode('utf-8', 'replace').strip() if base is not None and base.returncode == 0 else ''
    result = run(['gh', 'api', 'repos/%s/compare/%s...%s' % (repo, branch, HOST_BRANCH)], env) if branch else None
    try:
        assert result is not None and result.returncode == 0
        files = strict(result.stdout.decode('utf-8'))['files']
        assert isinstance(files, list) and len(files) < 300  # GitHub lists at most 300 files
        changed = {f['filename']: f['status'] for f in files}
        assert len(changed) == len(files) and all(isinstance(k, str) for k in changed)
    except (AssertionError, UnicodeDecodeError, ValueError, KeyError, TypeError):
        raise Exit(6, "Could not read the host setting pull request's changes; it is not ready. Run this again to "
                      'read them before anything else.')
    approved = {HOST_FILE: ('added',), MODE_FILE: ('modified',)}
    for path in sorted(set(changed) | set(want)):
        if (changed.get(path) not in approved.get(path, ()) or path not in want
                or raw(repo, path, env, HOST_BRANCH) != want[path]):
            raise Exit(5, 'Branch %s changes %s beyond the approved host setting, so its pull request is not '
                          'ready and OpenWiz opens or reports nothing. The owner deletes that branch (closing its '
                          'pull request), then run this again.' % (HOST_BRANCH, path))


def host_pull(repo, env):
    """The host setting pull request's URL and state, or None when there is none; Exit when unreadable."""
    result = run(['gh', 'pr', 'list', '--repo', repo, '--head', HOST_BRANCH, '--state', 'all',
                  '--json', 'url,state'], env)
    try:
        assert result is not None and result.returncode == 0
        pulls = strict(result.stdout.decode('utf-8'))
        assert isinstance(pulls, list) and len(pulls) <= 1
        assert all(isinstance(p, dict) and set(p) == {'url', 'state'} and isinstance(p['url'], str)
                   and p['state'] in ('OPEN', 'MERGED', 'CLOSED') for p in pulls)
        return (pulls[0]['url'], pulls[0]['state']) if pulls else None
    except (AssertionError, UnicodeDecodeError, ValueError, KeyError, TypeError):
        raise Exit(6, 'Could not read whether the host setting pull request exists; run this again to read it.')


def mode(got):
    """This machine's harness permission mode: each one explained, none picked, the owner's recorded (J254 A)."""
    state = State(got['--state'])
    host, carried = state.value.get('host'), state.value.get('setup')
    if not host or host['agents'] != 'local':
        raise Exit(5, 'Only agents on this machine need a permission mode; every other host sets its own. Nothing '
                      'recorded.')
    if not carried:
        raise Exit(5, 'Connect the repository first (continue): the mode is for the harness it prepares; '
                      'nothing recorded.')
    harness = carried['settings']['harness']
    harnesses = routed(host, harness)
    if any(not MODES.get(h) for h in harnesses):
        raise Exit(5, 'No permission modes are known for %s; nothing recorded.' % harness)
    flags = [MODE_FLAGS[PROGRAMS[h]] for h in harnesses] if len(harnesses) > 1 else ['--mode']
    given = [f for f in ('--mode',) + tuple(MODE_FLAGS.values()) if f in got]
    if not given:
        for h in harnesses:
            print('%s on this machine runs with the permission mode the owner picks, once. The driver passes it '
                  'unchanged and never chooses or widens it:' % h)
            for name, why in MODES[h]:
                print('- %s: %s' % (name, why))
        if len(harnesses) > 1:
            print('Both harnesses run here: builders use %s and each review uses the other one, so each needs its '
                  'own mode.' % harness)
        print("Nothing recorded. Ask the owner which one%s, in those words, and pick none for them; on their answer, "
              'run again with %s.' % (' for each harness' if len(harnesses) > 1 else '',
                                      ' '.join('%s <their pick>' % f for f in flags)))
        return 12
    if sorted(given) != sorted(flags):
        raise Exit(5, 'Pick with exactly %s here%s; nothing recorded.' % (' and '.join(flags), (
            ': builders and reviewers use both harnesses on this machine' if len(harnesses) > 1 else '')))
    picks = {h: got[f] for h, f in zip(harnesses, flags)}
    for h, pick in picks.items():
        if pick not in [name for name, _ in MODES[h]]:
            raise Exit(5, '%s is not one of %s\'s permission modes (%s); nothing recorded.' % (
                pick, h, ', '.join(name for name, _ in MODES[h])))
    wanted = {PROGRAMS[h]: pick for h, pick in picks.items()}
    recorded = state.value.get('setting') or {}
    had = recorded.get('modes') or ({PROGRAMS[harness]: recorded['mode']} if recorded.get('mode') else {})
    if recorded.get('state') in ('pending', 'opened', 'merged') and had != wanted:
        raise Exit(5, 'The host setting already carries %s; ask the owner to change that line instead; '
                      'nothing recorded.' % (', '.join(sorted(had.values())) or 'no permission mode'))
    for h, pick in picks.items():
        approve_host(os.environ, carried['repository'], PROGRAMS[h], pick)
    state.value['mode'] = {'harness': harness, 'mode': picks[harness]}
    if len(picks) > 1:
        state.value['mode']['modes'] = wanted
    if not state.save():
        raise Exit(10, 'Could not save the permission mode; nothing recorded.')
    print('Recorded: agents on this machine run %s, the mode%s the owner picked, saved as this machine\'s host-side '
          'approval for %s (outside the repository); the host setting adds the matching %s row%s.' % (
              ' and '.join('%s with the %s permission mode' % (h, pick) for h, pick in picks.items()),
              's' if len(picks) > 1 else '', carried['repository'], MODE_FILE, 's' if len(picks) > 1 else ''))
    return 0


def setting(got):
    """Write where agents run (docs/agents/host.md) and, on this machine, the owner's permission mode (KN3's one
    docs/agents/fleet.md row) as one pull request the user merges, only on --yes."""
    state = State(got['--state'])
    host = state.value.get('host')
    repo = (state.value.get('setup') or {}).get('repository')
    if not host or not repo:
        raise Exit(5, 'Ask where agents run (where) and connect the repository (continue) first; nothing written.')
    picked = (state.value.get('mode') or {}).get('mode')
    modes = picked_modes(state)
    name = None if host['agents'] == 'cloud' else host['agents']
    local = name == 'local'
    if local and not picked:
        raise Exit(5, 'Ask the owner to pick the harness permission mode first (mode); nothing written.')
    env = repository(repo)
    now = host_setting(env)
    if now is not None and now != name:
        raise Exit(5, '%s already says Host: %s on the default branch; OpenWiz never overwrites it. Ask the user '
                      'whether to change that line, or answer where agents run again; nothing written.' % (HOST_FILE, now))
    writes = []
    if local:
        fleet = raw(repo, MODE_FILE, env)
        if fleet is None:
            raise Exit(5, '%s is not on the default branch yet: run setup and merge its settings (Agents) first; '
                          'nothing written.' % MODE_FILE)
        values = [line.rstrip() for line in fleet.splitlines() if line.startswith(MODE_ROWS)]
        if values and values != mode_lines(modes):
            raise Exit(5, '%s already saves %s; OpenWiz never adds a second row or replaces the owner\'s. Ask the '
                          'owner whether to change that row; nothing written.' % (
                              MODE_FILE, ', '.join('`%s`' % v for v in mode_rows(fleet) if v) or
                              ', '.join(values)))
        writes = ([HOST_FILE] if now is None else []) + ([MODE_FILE] if not values else [])
    elif name and now is None:
        writes = [HOST_FILE]
    if not writes:
        state.value['setting'] = dict({'host': name, 'state': 'merged', 'mode': picked}, **kept(modes))
        if not state.save():
            raise Exit(10, 'Could not save the host setting; nothing written.')
        print('The host setting already matches: %s.' % (
            'Host: local and the %s permission mode, on the default branch' % picked if local
            else 'Host: %s, on the default branch' % name if name else 'no host file, so Cloudroom, the default'))
        return 0
    # R4: the exact files the pull request carries, from the default branch as it is now.
    want = {}
    if HOST_FILE in writes:
        want[HOST_FILE] = host_text(name)
    if MODE_FILE in writes:
        want[MODE_FILE] = fleet.rstrip('\n') + '\n' + mode_section(modes)
    recorded = state.value.get('setting') or {}
    if recorded.get('state') in ('pending', 'opened'):
        found = host_pull(repo, env)
        if found and found[1] == 'CLOSED':
            raise Exit(5, 'The host setting pull request %s was closed without merging; the user reopens and merges '
                          'it, or answers where agents run again; nothing written.' % found[0])
        if found:
            pull_diff(repo, env, want)
            state.value['setting'] = dict({'host': name, 'state': 'opened', 'pull': found[0], 'mode': picked},
                                          **kept(modes))
            state.save()
            print('The host setting pull request is open: %s. The user merges it; launch waits for it.' % found[0])
            return 0
    said = {HOST_FILE: 'add %s holding `Host: %s`' % (HOST_FILE, name),
            MODE_FILE: 'add %s, %s, to %s, changing no other line' % (
                'one row' if len(modes) == 1 else '%d rows' % len(modes), ' and '.join(mode_lines(modes)), MODE_FILE)}
    print('Effect: on a new branch %s of %s, %s, and open one pull request for you to merge. Nothing else is '
          'written.' % (HOST_BRANCH, repo, ' and '.join(said[w] for w in writes)))
    if not got.get('--yes'):
        print("Nothing written. On the user's yes to exactly this, run again with --yes.")
        return 12
    based = {HOST_FILE: None, MODE_FILE: fleet if local else None}
    state.value['setting'] = dict({'host': name, 'state': 'pending', 'mode': picked}, **kept(modes))
    if not state.save():
        raise Exit(10, 'Could not save the host setting first; nothing written.')
    base = run(['gh', 'api', 'repos/%s' % repo, '--jq', '.default_branch'], env)
    branch = base.stdout.decode('utf-8', 'replace').strip() if base is not None and base.returncode == 0 else ''
    if not branch:
        raise Exit(1, "Could not read the default branch; nothing written.")

    def tip_of(name):
        read = run(['gh', 'api', 'repos/%s/git/ref/heads/%s' % (repo, name), '--jq', '.object.sha'], env)
        value = read.stdout.decode('utf-8', 'replace').strip() if read is not None and read.returncode == 0 else ''
        return value if re.fullmatch(r'[0-9a-f]{40}', value) else None
    sha = tip_of(branch)
    if sha is None:
        raise Exit(1, "Could not read the default branch's tip; nothing written.")
    if tip_of(HOST_BRANCH) is None:
        run(['gh', 'api', '-X', 'POST', 'repos/%s/git/refs' % repo, '-f', 'ref=refs/heads/' + HOST_BRANCH,
             '-f', 'sha=' + sha], env)
        if tip_of(HOST_BRANCH) is None:
            raise Exit(6, 'Whether branch %s was made is uncertain; run this again to read it before anything else.'
                       % HOST_BRANCH)
    # R4: each file and its blob SHA from one read; the write names exactly that blob, so GitHub refuses it when
    # anyone changed the file after this check.
    read = {path: blob(repo, path, env, HOST_BRANCH) for path in writes}
    have = {path: read[path][0] for path in writes}
    for path in writes:
        if have[path] not in (want[path], based[path]):
            raise Exit(5, 'Branch %s already holds another %s; OpenWiz never writes over it. The owner deletes that '
                          'branch, or merges it if it is what they want, then run this again; nothing written.' % (
                              HOST_BRANCH, path))
    for path in writes:
        if have[path] == want[path]:
            continue
        checked = read[path][1]
        put = ['gh', 'api', '-X', 'PUT', 'repos/%s/contents/%s' % (repo, path), '-f',
               'message=Where agents run: Host: %s%s' % (name, ', ' + picked if local else ''), '-f',
               'content=' + base64.b64encode(want[path].encode()).decode(), '-f', 'branch=' + HOST_BRANCH]
        wrote = run(put + (['-f', 'sha=' + checked] if checked else []), env)
        if wrote is None or wrote.returncode != 0:
            try:
                now = blob(repo, path, env, HOST_BRANCH)
            except Exit:
                now = read[path]  # unreadable: the uncertain write below says to read the branch first
            if now != read[path] and now[0] != want[path]:
                raise Exit(5, '%s on %s changed while OpenWiz was writing it, so GitHub refused the write and the '
                              'other change was kept; no pull request was opened. Read the branch, then run this '
                              'again.' % (path, HOST_BRANCH))
            raise Exit(6, 'Writing %s on %s failed or is uncertain; run this again to read the branch before '
                          'anything else.' % (path, HOST_BRANCH))
    for path in writes:
        if raw(repo, path, env, HOST_BRANCH) != want[path]:
            raise Exit(6, '%s on %s did not read back as written; run this again to read it before anything else.'
                       % (path, HOST_BRANCH))
    pull_diff(repo, env, want)
    if host_pull(repo, env) is None:
        body = ('Adds `Host: local` to %s and the owner\'s harness permission mode as %s of %s: OpenWiz '
                'starts this project\'s agents through its local driver, which passes that mode to the harness '
                'unchanged (records v1, section 6). Merge it to start the first fleet there.' % (
                    HOST_FILE, 'one row' if len(modes) == 1 else 'one row per harness', MODE_FILE)
                if local else 'Adds `Host: %s` to %s: OpenWiz starts this project\'s agents through its %s driver '
                '(records v1, section 6). Merge it to start the first fleet there.' % (name, HOST_FILE, name))
        run(['gh', 'pr', 'create', '--repo', repo, '--head', HOST_BRANCH, '--base', branch, '--title',
             'Where agents run: %s' % host_label(name).split(',')[0], '--body', body], env)
    found = host_pull(repo, env)
    if found is None:
        raise Exit(6, 'Whether the host setting pull request was opened is uncertain; run this again to read it '
                      'before anything else.')
    state.value['setting'] = dict({'host': name, 'state': 'opened', 'pull': found[0], 'mode': picked}, **kept(modes))
    if not state.save():
        raise Exit(6, 'The host setting pull request is open (%s), but that could not be saved.' % found[0])
    print('Opened %s. The user merges it; launch waits for it on the default branch.' % found[0])
    return 0


def grill(got):
    """Record the user's yes to the grill, given in this chat and saved privately as a comment."""
    state = State(got['--state'])
    if state.value.get('launch') and state.value.get('grill') != got['--confirmed']:
        raise Exit(5, 'This onboarding already launched from its grill; it plans one first fleet.')
    state.value['grill'] = got['--confirmed']
    if not state.save():
        raise Exit(10, "Could not save the grill's confirmation; nothing recorded.")
    print("Recorded: the user confirmed the grill in chat. Next: to-spec, which runs to-tickets; the plan approves "
          'itself by its checks, and no plan approval is asked.')


def select(got):
    """The existing repository the owner confirmed, bound to this onboarding before Connect."""
    state = State(got['--state'])
    name = got['--repo']
    if state.value.get('repo') not in (None, name):
        raise Exit(5, 'This onboarding is for %s; it takes no second repository; nothing recorded.'
                   % state.value['repo'])
    record = state.value.get('created')
    if record and record['repo'] != name and record['state'] != 'absent':
        raise Exit(5, 'This onboarding already made %s; it takes no second repository; nothing recorded.'
                   % record['repo'])
    state.value['repo'] = name
    if not state.save():
        raise Exit(10, 'Could not save the repository; nothing recorded.')
    print('Recorded: this onboarding is for %s. Connect it next.' % name)
    return 0


# --- Choices ----------------------------------------------------------------

def choose(got):
    state = State(got['--state'])
    host = state.value.get('host')
    if not host:
        raise Exit(5, 'Ask where agents run first (where); nothing recorded.')
    if got.get('--agents', host['agents']) != host['agents']:
        raise Exit(5, 'The user said agents run %s; answer where again to change it; nothing recorded.' % (
            where_of(host['agents'])))
    carried = state.value.get('setup')
    if got.get('--from-setup'):
        if not carried:
            raise Exit(5, 'No setup was carried into this onboarding (run continue first); nothing recorded.')
        settings = carried['settings']
    else:
        settings = {'harness': got['--harness'], 'model': got['--model'], 'effort': got['--effort']}
    try:
        offered = strict(Path(got['--options']).read_text(encoding='utf-8'))
        assert offered['schema'] == 'openwiz.cloud-options.v1' and offered['state'] == {'kind': 'offered'}
        harnesses = [h for h in offered['harnesses'] if h['provider'] == settings['harness']]
    except (OSError, ValueError, KeyError, TypeError, AssertionError):
        raise Exit(1, 'The saved `openwiz models --json` output is unreadable; nothing recorded.')
    local_source = host['agents'] != 'cloud' and (not carried or 'host' in carried)
    if local_source and offered.get('source') != 'local':
        raise Exit(5, 'Read the local options with `openwiz models --json --host %s`; nothing recorded.'
                   % host['agents'])
    efforts = [e for h in harnesses for m in h['models'] if m['model'] == settings['model'] for e in m['efforts']]
    if len(harnesses) != 1 or settings['effort'] not in efforts:
        raise Exit(5, 'That harness, model and effort are not among the offered options; nothing recorded.')
    if settings['harness'] not in FAMILY:
        raise Exit(5, "The fleet's review rules cover Claude Code and Codex builders only; nothing recorded.")
    if host['agents'] == 'local' and settings['harness'] not in host['harnesses']:
        raise Exit(5, '%s is not on this machine, so its agents cannot run here; nothing recorded.' % settings['harness'])
    choices = dict(settings, agents=host['agents'])
    read = None
    try:
        env = repository(state.value.get('repo'))
    except Exit:
        env = None
    wrote, intended = (None, None) if env is None else write_models(settings, offered, host['agents'] != 'cloud')
    try:
        remote = None if env is None else fleet_text(env, state.value['repo'])
    except Exit:
        remote = None
    if remote is not None:
        try:
            read = models_table(remote) == intended
        except ValueError:
            read = False
    if read:
        choices['builder_tables'] = 'read'
    state.value['choices'] = choices
    if not state.save():
        raise Exit(10, 'Could not save the choices; nothing recorded.')
    print(chosen_line(choices) + (' (as prepared in setup)' if got.get('--from-setup') else ''))
    if wrote is not None:
        print(wrote)
    if read:
        print("Read back: the default branch's Models table has exactly the rows choose wrote.")
    else:
        print(tables_line(choices, 'could not be read' if read is None else 'do not name this choice yet'))
        return 1 if read is None else 0
    return 0


def chosen_line(choices):
    return 'Recorded: builders use %s %s %s, and run %s.' % (
        choices['harness'], choices['model'], choices['effort'], where_of(choices['agents']))


def tables_line(choices, why):
    return ("The fleet's settings on the default branch %s: commit docs/agents/fleet.md, which choose writes, "
            'and merge it so its builders are exactly %s %s %s with the reviewer from the other family, then run '
            'choose again to read it back.' % (
                why, choices['harness'], choices['model'], choices['effort']))


def models_table(text):
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location('openwiz_setup_settings', SETTINGS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.models(text)


def offers(offered, agent):
    return any(h['provider'] == agent[0] and m['model'] == agent[1] and agent[2] in m['efforts']
               for h in offered['harnesses'] for m in h['models'])


def model_row(role, agent):
    provider, model, effort = agent
    return '| %s | %s | %s | %s | `--provider %s --model %s --reasoning-level %s` |' % (
        role, WRITTEN_NAMES.get(provider, provider), WRITTEN_NAMES.get(model, model), effort[:1].upper() + effort[1:],
        provider, model, effort)


def write_models(settings, offered, driver=False):
    choice = (settings['harness'], settings['model'], settings['effort'])
    try:
        folder = settings_folder()
    except OSError:
        raise Exit(5, 'This checkout has no docs/agents/ folder of its own (a missing or linked folder); run setup '
                      'first; nothing recorded.')
    try:
        return write_in(folder, choice, offered, driver)
    finally:
        os.close(folder)


def settings_folder():
    folder = os.open('.', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in FLEET_MD.parent.parts:
            inner = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=folder)
            os.close(folder)
            folder = inner
    except OSError:
        os.close(folder)
        raise
    return folder


def write_in(folder, choice, offered, driver=False):
    name = FLEET_MD.name
    try:
        handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=folder)
        try:
            info = os.fstat(handle)
            assert stat.S_ISREG(info.st_mode)
            with os.fdopen(os.dup(handle), 'rb') as source:
                text = source.read().decode('utf-8')
        finally:
            os.close(handle)
    except (OSError, UnicodeError, AssertionError):
        raise Exit(5, 'This checkout has no readable docs/agents/fleet.md; run setup first; nothing recorded.')
    try:
        table = models_table(text)
    except ValueError as error:
        raise Exit(5, "docs/agents/fleet.md's Models table breaks the models contract (%s); fix it or run setup "
                      'again; nothing recorded.' % '; '.join(error.args[0]))
    lines = text.split('\n')
    if table:
        heading = next(n for n, line in enumerate(lines) if line.startswith('## ') and line[3:].strip() == 'Models')
        start = next(n for n in range(heading, len(lines)) if lines[n].startswith('|'))
        end = next((n for n in range(start, len(lines)) if not lines[n].startswith('|')), len(lines))
        reviewer, kept = table['Reviewer'], lines[start + 4]
    else:
        older = [n for n, line in enumerate(lines) if line.startswith('## ') and line[3:].strip() in OLDER]
        if not older:
            raise Exit(5, 'docs/agents/fleet.md has no Models table and no older model tables; run setup first; '
                          'nothing recorded.')
        start = end = older[0]
        found = older_rules(text)['reviewer_' + FAMILY[choice[0]]]
        reviewer, kept = (found and (found['harness'], found['model'], found['effort'])), None
        source = 'the older `%s` table' % REVIEWER[FAMILY[choice[0]]]
    family = FAMILY[choice[0]]
    alone = None
    if not reviewer or FAMILY.get(reviewer[0]) in (None, family):
        reviewer = RECOMMENDED['gpt' if family == 'claude' else 'claude']
        kept, source = None, 'the recommended other-family choice'
        if driver and not any(h['provider'] == reviewer[0] for h in offered['harnesses']):
            alone = reviewer[0]
        elif not offers(offered, reviewer):
            raise Exit(5, 'The Reviewer must be from the other model family; its recommended choice, %s, is not '
                          'offered now; nothing recorded.' % ' '.join(reviewer))
    rows = ['| Role | Harness | Model | Effort | `room-cli thread spawn` flags |', '| --- | --- | --- | --- | --- |',
            model_row('Orchestrator', choice), model_row('Builder', choice), kept or model_row('Reviewer', reviewer),
            '| Small builder | follows Builder | | | |', '| Fixer | follows Builder | | | |']
    if not table:
        rows = ['## Models', ''] + rows + ['', "Source: install's `choose`, from the owner's choice of harness, model "
                                           'and effort for the Orchestrator and Builder; the Reviewer is %s.' % source, '']
    written = '\n'.join(lines[:start] + rows + lines[end:])
    try:
        assert models_table(written) == {'Orchestrator': choice, 'Builder': choice, 'Reviewer': reviewer,
                                         'Small builder': None, 'Fixer': None}
    except (ValueError, AssertionError):
        raise Exit(5, 'cannot be written to the Models table: %s; nothing recorded.' % ' '.join(choice))
    intended = {'Orchestrator': choice, 'Builder': choice, 'Reviewer': reviewer, 'Small builder': None, 'Fixer': None}
    said = ('docs/agents/fleet.md: the Models table names %s for the Orchestrator and Builder, with %s as the '
            'Reviewer' % (' '.join(choice), ' '.join(reviewer)))
    if alone:
        said += ('. %s is not installed here, so each review runs with the builder\'s harness, marked '
                 'same-family review' % alone)
    if written == text:
        return said + '; already written.', intended
    temporary = '.fleet-%s' % os.urandom(8).hex()
    try:
        out = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                      stat.S_IMODE(info.st_mode), dir_fd=folder)
        with os.fdopen(out, 'wb') as target:
            target.write(written.encode('utf-8'))
        os.replace(temporary, name, src_dir_fd=folder, dst_dir_fd=folder)
    except OSError:
        try:
            os.unlink(temporary, dir_fd=folder)
        except OSError:
            pass
        raise Exit(5, 'Could not write docs/agents/fleet.md; nothing recorded.')
    return 'Wrote %s; commit it and merge it to the default branch.' % said, intended




def repository(recorded):
    """The environment for every read and run, once the checkout is the recorded repository."""
    if not recorded:
        raise Exit(5, 'This onboarding recorded no repository; record its spec first; ' + NOTHING)
    env = dict(os.environ)
    named = env.pop('GH_REPO', None)
    if named is not None and named != recorded:
        raise Exit(5, 'GH_REPO names %s, but this onboarding is for %s; %s' % (named, recorded, NOTHING))
    result = run(['gh', 'repo', 'view', '--json', 'nameWithOwner', '--jq', '.nameWithOwner'], env)
    if result is None or result.returncode != 0:
        raise Exit(1, 'Could not read which repository this checkout is; ' + NOTHING)
    here = result.stdout.decode('utf-8', 'replace').strip()
    if here != recorded:
        raise Exit(5, 'This checkout is %s, but this onboarding is for %s; %s' % (here, recorded, NOTHING))
    env['GH_REPO'] = recorded
    return env


def record_spec(got):
    state = State(got['--state'])
    spec = int(got['--spec'])
    carried = state.value.get('setup')
    if carried and carried['repository'] != got['--repo']:
        raise Exit(5, 'Setup selected %s for this onboarding; it plans no spec in %s; nothing recorded.' % (
            carried['repository'], got['--repo']))
    repository(got['--repo'])
    if state.value.get('launch') and state.value.get('repo') not in (None, got['--repo']):
        raise Exit(5, 'This onboarding already launched in %s; nothing recorded.' % state.value['repo'])
    launch = state.value.get('launch')
    if launch and launch['spec'] != spec and launch['state'] != 'refused':
        raise Exit(5, 'This onboarding already launched spec #%d; it plans one first fleet.' % launch['spec'])
    state.value['spec'] = spec
    state.value['repo'] = got['--repo']
    if not state.save():
        raise Exit(10, 'Could not save the spec; nothing recorded.')
    print('Recorded: this onboarding planned spec #%d in %s.' % (spec, got['--repo']))
    return 0


# --- The launch, through launch-fleet ----------------------------------------

def frontier(env):
    result = run(['sh', str(FLEET_SH), 'frontier'], env)
    if result is None or result.returncode != 0:
        raise Exit(1, 'Could not read the approved frontier; ' + NOTHING)
    tickets = {}
    for line in result.stdout.decode('utf-8', 'replace').splitlines():
        match = re.fullmatch(r'#([1-9][0-9]*) (.+)', line)
        if not match or int(match[1]) in tickets:
            raise Exit(1, 'The frontier read was not in its form; ' + NOTHING)
        tickets[int(match[1])] = match[2]
    return tickets


def gh_json(argv, env, what):
    result = run(['gh', *argv], env)
    try:
        assert result is not None and result.returncode == 0
        return strict(result.stdout.decode('utf-8'))
    except (AssertionError, UnicodeDecodeError, ValueError):
        raise Exit(1, 'Could not read %s; %s' % (what, NOTHING))


def spec_facts(spec, env):
    """The spec's title and its sub-issue numbers, read from GitHub."""
    subs = gh_json(['issue', 'view', str(spec), '--json', 'subIssues', '--jq', '.subIssues'], env, "the spec's tickets")
    head = gh_json(['issue', 'view', str(spec), '--json', 'number,title,blockedBy', '--jq', '{number, title}'],
                   env, 'the spec')
    try:
        numbers = [node['number'] for node in subs['nodes']]
        assert subs['totalCount'] == len(numbers) == len(set(numbers)) and all(type(n) is int for n in numbers)
        assert head['number'] == spec and isinstance(head['title'], str) and head['title'].strip()
    except (KeyError, TypeError, AssertionError):
        raise Exit(1, "The spec's tickets were not read completely; " + NOTHING)
    return ' '.join(head['title'].split()), set(numbers)


def agent(lines):
    """harness, model and effort from one settings table's `room-cli thread spawn` flags."""
    text = '\n'.join(lines)
    found = {}
    for key, flag in (('harness', 'provider'), ('model', 'model'), ('effort', 'reasoning-level')):
        values = re.findall(r'`--%s ([^`\s]+)`' % flag, text)
        if len(values) != 1:
            return None
        found[key] = values[0]
    return found


def fleet_rules(env, repo):
    """The builder and reviewer tables of docs/agents/fleet.md on the default branch."""
    return settings_rules(fleet_text(env, repo))


def fleet_text(env, repo):
    result = run(['gh', 'api', 'repos/%s/contents/docs/agents/fleet.md' % repo,
                  '-H', 'Accept: application/vnd.github.raw+json'], env)
    if result is None or result.returncode != 0:
        raise Exit(1, "Could not read the fleet settings (docs/agents/fleet.md); run setup; " + NOTHING)
    return result.stdout.decode('utf-8', 'replace')


def settings_rules(text):
    try:
        table = models_table(text)
    except ValueError as error:
        raise Exit(5, "The fleet settings' Models table breaks the models contract (%s); %s" % (
            '; '.join(error.args[0]), NOTHING))
    if table is None:
        return older_rules(text)
    def named(role):
        return dict(zip(('harness', 'model', 'effort'), table.get(role) or table['Builder']))
    rules = {'orchestrator': named('Orchestrator'), 'builder': named('Builder'), 'builder_small': named('Small builder')}
    for family in REVIEWER:
        rules['reviewer_' + family] = next((named(role) for role in ('Reviewer', 'Builder')
                                            if FAMILY.get(table[role][0]) not in (None, family)), None)
    return rules


def older_rules(text):
    found, name = {}, None
    for line in text.split('\n'):
        if line.startswith('## '):
            name = line[3:].strip()
            found.setdefault(name, [])
        elif name is not None:
            found[name].append(line)
    rules = {key: agent(found[title]) if title in found else None for key, title in (
        ('builder', 'Builder'), ('builder_small', 'Builder for small tickets'),
        ('reviewer_claude', REVIEWER['claude']), ('reviewer_gpt', REVIEWER['gpt']))}
    rules['orchestrator'] = rules['builder']
    return rules


def review(choices, rules):
    """Refuse unless every builder table is the user's choice and its reviewer is the other family."""
    want = {k: choices[k] for k in ('harness', 'model', 'effort')}
    if rules['builder'] != want or rules['builder_small'] != want:
        raise Exit(5, "The fleet's builder tables (builder and small-ticket builder) are not exactly the user's "
                      'choice; run setup so both match, then preview again; ' + NOTHING)
    family = FAMILY[want['harness']]
    reviewer = rules['reviewer_' + family]
    if reviewer is None or FAMILY.get(reviewer['harness']) in (None, family):
        raise Exit(5, "The fleet's reviewer for these builders is not from the other model family; " + NOTHING)
    return want, reviewer


def fleet_recorded(spec, env):
    """Only configured record authors settle a start; unread input stays unknown."""
    bodies = record_comments(spec, env)
    if bodies is None:
        return None
    return any(body.split('\n')[0].strip() == FLEET_RECORD + str(spec) for body in bodies)


# This machine's first fleet runs in the open chat through launch-fleet's session runner (#2329); the heartbeat
# is the opt-in after it, for keeping the fleet going once the chat closes.
SESSION = LAUNCH_FLEET / 'scripts/session.py'
OPT_IN = ('To keep the fleet going after this chat closes, the opt-in is a local heartbeat: ask the user, and only '
          'on their yes run launch --spec %d --heartbeat to preview it.')


def activation(spec, host, env):
    if host == 'cloud':
        return fleet_recorded(spec, env)
    result = run([sys.executable, '-I', str(HEARTBEAT), 'status', env['GH_REPO'], str(spec)], env, timeout=30)
    if result is None or result.returncode:
        return None
    status = result.stdout.strip()
    if status == b'heartbeat: not installed':
        return False
    if re.fullmatch(rb'heartbeat: active [(](launchd|systemd|cron)[)]', status):
        return True
    return None


def plan_approved(spec, env, confirmed):
    """Exit unless the spec's latest plan approval is to-tickets' machine plan approval of this grill.

    Read from record authors only; launch-fleet's frontier then checks it is current."""
    bodies = record_comments(spec, env)
    if bodies is None:
        raise Exit(1, "Could not read the spec's plan approval; " + NOTHING)
    latest = None
    for body in bodies:
        lines = [line.strip() for line in body.split('\n') if line.strip()]
        if lines and (lines[0].startswith('**Plan graph approved by') or lines[0].startswith('**Machine plan approval, ')):
            latest = lines
    if latest is None or not re.fullmatch(r'\*\*Machine plan approval, [0-9]{4}-[0-9]{2}-[0-9]{2}, revision '
                                          r'[1-9][0-9]*:\*\* links, relies, sizes, width and owned paths passed\.',
                                          latest[0]):
        raise Exit(5, "Spec #%d's latest plan approval is not to-tickets' machine plan approval: run to-tickets on "
                      'it; no plan approval is asked; %s' % (spec, NOTHING))
    if len(latest) < 2 or latest[1] != 'Grill confirmed: ' + confirmed:
        raise Exit(5, "Spec #%d's machine plan approval is not for the grill the user confirmed in this chat; %s"
                   % (spec, NOTHING))


def record_comments(spec, env):
    """The spec's comment bodies by configured record authors, or None when unread."""
    settings = run(['gh', 'api', 'repos/%s/contents/docs/agents/fleet.md' % env['GH_REPO'],
                    '-H', 'Accept: application/vnd.github.raw+json'], env)
    if settings is None or settings.returncode != 0:
        return None
    try:
        # The same Record authors policy as fleet.sh settings(): exactly one
        # row in GitHub identity, only comma-separated backticked logins, no
        # extra cells or malformed entries, compared case-insensitively.
        rows, identity = [], False
        for line in settings.stdout.decode('utf-8').splitlines():
            if line.startswith('## '):
                identity = line == '## GitHub identity'
            if identity and re.match(r'^\| *Record authors *\|', line):
                rows.append(line)
        if len(rows) != 1:
            return None
        row = re.fullmatch(r'\| *Record authors *\|([^|]*)\|\s*', rows[0])
        login = r'`[A-Za-z0-9](-?[A-Za-z0-9])*(\[bot\])?`'
        if row is None or not re.fullmatch(r'\s*' + login + r'(\s*,\s*' + login + r')*\s*', row[1]):
            return None
        authors = {value.lower() for value in re.findall(r'`([^`]*)`', row[1])}
    except UnicodeDecodeError:
        return None
    result = run(['gh', 'api', '--paginate', 'repos/%s/issues/%d/comments?per_page=100' % (env['GH_REPO'], spec),
                  '--jq', '.[] | {author: .user.login, body} | @json'], env)
    if result is None or result.returncode != 0:
        return None
    try:
        lines = result.stdout.decode('utf-8').split('\n')
        if lines[-1] == '':
            lines.pop()
        comments = [strict(line) for line in lines]
        if any(not isinstance(c, dict) or set(c) != {'author', 'body'} or not isinstance(c['body'], str)
               or c['author'] is not None and not isinstance(c['author'], str) for c in comments):
            return None
    except (UnicodeDecodeError, ValueError):
        return None
    return [c['body'] for c in comments if c['author'] is not None and c['author'].lower() in authors]


def launch(got):
    state = State(got['--state'])
    spec = int(got['--spec'])
    if state.value.get('spec') != spec:
        raise Exit(5, 'This onboarding planned no spec #%d; it launches only the spec its own grill planned; %s'
                   % (spec, NOTHING))
    carried = state.value.get('setup')
    if not carried:
        raise Exit(5, 'No verified setup was carried into this onboarding (run continue first); ' + NOTHING)
    host, confirmed = state.value.get('host'), state.value.get('grill')
    if not host:
        raise Exit(5, 'The user has not said where agents run (where); ' + NOTHING)
    if not confirmed:
        raise Exit(5, 'The user has not confirmed the grill in this chat (grill --confirmed); ' + NOTHING)
    choices = state.value.get('choices')
    if not choices or choices.get('agents') != host['agents']:
        raise Exit(5, 'The harness, model and effort are not chosen for where agents run yet (choose); ' + NOTHING)
    env = repository(state.value.get('repo'))
    agents_host = host['agents']
    driver = agents_host != 'cloud'
    local = agents_host == 'local'
    previous = state.value.get('launch')
    if got.get('--heartbeat'):
        return opt_in(state, spec, env, host, got)
    if local and previous and previous['spec'] == spec and previous['state'] == 'started':
        print('Spec #%d already started once; not starting again.' % spec)
        if previous.get('session'):
            print(session_line(spec, previous['session']))
        print(record_line(spec, activation(spec, agents_host, env), agents_host))
        return 0
    if local and previous and previous['spec'] == spec and previous['state'] != 'refused':
        del state.value['launch']
        state.value.pop('preview', None)
        if not state.save():
            raise Exit(10, 'Could not withdraw the yes; run this again; ' + NOTHING)
        raise Exit(5, 'The saved yes was for the heartbeat handoff; the fleet now runs in this chat: preview again '
                      'and ask again; ' + NOTHING)
    if previous and previous['spec'] == spec and previous['state'] != 'refused':
        recorded = activation(spec, agents_host, env)
        if previous['state'] != 'started' and recorded:
            previous['state'] = 'started'
            if not state.save():
                raise Exit(10, "Could not save the fleet's start; run this again to read it.")
            print(record_line(spec, recorded, agents_host))
            if not driver:
                print(teach('The fleet starting', (str(len(previous.get('tickets') or [])),)))
            return 0
        if previous['state'] == 'started':
            print('Spec #%d already started once; not starting again.' % spec)
            print(record_line(spec, recorded, agents_host))
            return 0
        print(record_line(spec, recorded, agents_host))
        if recorded is None:
            raise Exit(6, "Whether launch-fleet's start already ran is unknown, so its start path is not named "
                          'again; run this again; ' + NOTHING)
        try:
            orchestrator = fleet_rules(env, state.value['repo'])['orchestrator']
        except Exit:
            orchestrator = None
        if not orchestrator:
            raise Exit(6, "The fleet settings name no readable Orchestrator, so the user's yes cannot be matched to "
                          'it; fix the Models table, then run this again; ' + NOTHING)
        if orchestrator != previous.get('orchestrator'):
            del state.value['launch']
            state.value.pop('preview', None)
            if not state.save():
                raise Exit(10, 'Could not withdraw the yes; run this again; ' + NOTHING)
            raise Exit(5, "The fleet settings' Orchestrator is now %s, not the one the user said yes to: preview "
                          'again and ask again; %s' % (agent_words(orchestrator), NOTHING))
        adapters = previous.get('adapters') if driver else None
        if driver and not adapters:
            del state.value['launch']
            state.value.pop('preview', None)
            if not state.save():
                raise Exit(10, 'Could not withdraw the yes; run this again; ' + NOTHING)
            raise Exit(5, 'The saved yes predates the heartbeat handoff. Run continue, then preview again; ' + NOTHING)
        print(handoff(spec, state.value['repo'], adapters, orchestrator))
        return 6
    # Review R4: the carried setup must still be what setup verifies now.
    if not isinstance(carried.get('setup_state'), str):
        withdraw(state)
        raise Exit(5, 'The carried setup names no setup state to recheck; run continue again; ' + NOTHING)
    current = refreshed(state, carried['setup_state'])
    if any(current[k] != carried.get(k) for k in current):
        withdraw(state)
        raise Exit(5, 'Setup changed since it was carried; run continue again; ' + NOTHING)
    name = None if host['agents'] == 'cloud' else host['agents']
    named = host_setting(env)
    if named != name:
        raise Exit(5, 'The host setting on the default branch says %s, but the user chose %s: %s; %s' % (
            'Host: ' + named if named else 'no host', host_label(host['agents']).split(',')[0],
            'merge the host setting pull request first (setting)' if name and named is None else
            'answer where agents run again, or ask to change that line', NOTHING))
    picked = (state.value.get('mode') or {}).get('mode')
    modes = picked_modes(state)
    if local and modes and set(modes) != {PROGRAMS[h] for h in routed(host, choices['harness'])}:
        raise Exit(5, 'The permission modes saved here are not for every harness this fleet starts on this machine: '
                      'run mode again, then setting, and merge it; ' + NOTHING)
    if local and (not picked or saved_rows(env) != mode_lines(modes)):
        raise Exit(5, 'No %s row, the Harness permission mode the owner picked, is in %s on the default '
                      "branch, and the local driver starts no agent without it: run mode, then setting, and merge "
                      'it; %s' % (' and '.join('`%s`' % line for line in mode_lines(modes or {'': '<mode>'})),
                                  MODE_FILE, NOTHING))
    if local:
        again = ' '.join('%s %s' % (MODE_FLAGS[p] if len(modes) > 1 else '--mode', modes[p]) for p in sorted(modes))
        for program in sorted(modes):
            approved = host_approval(env, state.value['repo'], program)
            if approved != modes[program]:
                raise Exit(5, "This machine's host-side approval for %s with %s is %s, not the `%s` row %s saves, "
                              "and KN3's start refuses unless they match: run mode %s to save the owner's pick here, "
                              'or ask the owner which mode they mean; %s' % (
                                  state.value['repo'], program, approved or 'missing', modes[program], MODE_FILE,
                                  again, NOTHING))
    adapters = None
    if driver:
        adapters = host.get('adapters') or env.get('OPENWIZ_ADAPTERS')
        if driver_answer(env, adapters, name)[0] is None:
            raise Exit(5, "This OpenWiz's %s driver no longer answers, so no agent can run %s; %s" % (
                name, where_of(name), NOTHING))
        env.update(OPENWIZ_ADAPTERS=adapters, LAUNCH_FLEET_GITHUB_ONLY='1')
    plan_approved(spec, env, confirmed)
    ready = frontier(env)
    title, members = spec_facts(spec, env)
    starts = sorted(n for n in ready if n in members)
    if not starts:
        raise Exit(5, 'No approved ticket of spec #%d is ready to start: the plan changed since its checks passed, '
                      'or is still blocked; %s' % (spec, NOTHING))
    rules = fleet_rules(env, state.value['repo'])
    builder, reviewer = review(choices, rules)
    orchestrator = rules['orchestrator']
    where = where_of(agents_host)
    if local and not shutil.which(PROGRAMS[builder['harness']], path=env.get('PATH')):
        raise Exit(5, "The session starts builders with %s, which is not installed here; " % builder['harness'] + NOTHING)
    if driver and not local and (orchestrator is None or orchestrator['harness'] not in PROGRAMS or
                                 not shutil.which(PROGRAMS[orchestrator['harness']], path=env.get('PATH'))):
        raise Exit(5, 'The orchestrator needs an installed Claude Code or Codex harness for the heartbeat; ' + NOTHING)
    same_family = driver and not shutil.which(PROGRAMS[reviewer['harness']], path=env.get('PATH'))
    if same_family:
        reviewer = builder
    effects = {'fleet_thread': orchestrator, 'repo': state.value['repo'], 'spec': spec, 'project': carried['project'], 'title': title,
               'host': host['agents'], 'mode': (picked if len(modes) == 1 else modes) if local else None, 'builder': builder, 'reviewer': reviewer, 'grill': confirmed,
               'tickets': [[n, ready[n]] for n in starts]}
    if driver:
        effects['session' if local else 'heartbeat'] = adapters
    digest = hashlib.sha256(json.dumps(effects, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if got.get('--yes'):
        shown = state.value.get('preview') or {}
        if got['--confirm'] != digest or shown.get('effects') != digest or shown.get('spec') != spec:
            raise Exit(5, 'The effects changed since the preview the user said yes to (or it was never shown); '
                          'preview again and ask again; ' + NOTHING)
    agents = '%s %s %s' % (builder['harness'], builder['model'], builder['effort'])
    fleet_thread = '%s %s %s' % (orchestrator['harness'], orchestrator['model'], orchestrator['effort'])
    if not got.get('--yes'):
        if local:
            print("Ready to start the fleet for spec #%d %s through launch-fleet's session runner, in this chat: it "
                  'starts a builder (%s) for each of these tickets, up to 3 at once, and starts each next step the '
                  'moment a run ends, with no timer:' % (spec, where, agents))
        elif driver:
            print('Ready to start the fleet for spec #%d %s through launch-fleet. A local heartbeat checks GitHub '
                  'every 10 minutes and starts an orchestrator wake (%s) when work is due. '
                  'Ready for a builder (%s):' % (spec, where, fleet_thread, agents))
        else:
            print('Ready to start the fleet for spec #%d %s, through launch-fleet: 1 fleet thread (%s), whose loop '
                  'checks the spec every 10 minutes and starts a builder (%s) for each of:' %
                  (spec, where, fleet_thread, agents))
        for ticket in starts:
            print('#%d %s' % (ticket, ready[ticket]))
        family = 'marked same-family review' if same_family else 'from the other model family'
        print('Each pull request is reviewed by %s, %s.' % (agent_words(reviewer), family))
        cost = (host_cost(host['agents']) if not local else 'every agent uses %s on this machine, whose model '
                'use is billed to you as it is today' % builder['harness'])
        if local:
            print('Its agents run %s you picked.' % ' and '.join(
                '%s with the %s permission mode' % (HARNESS_OF[p], modes[p]) for p in sorted(modes)))
            print('The fleet moves while the session runs here; keeping it going after the chat closes is the '
                  'heartbeat, offered afterwards as its own opt-in.')
        print('Start the fleet %s now? It can cost money: %s.' % (where, cost))
        state.value['preview'] = {'spec': spec, 'effects': digest}
        if not state.save():
            raise Exit(10, 'Could not save the preview; ' + NOTHING)
        print('Confirmation: %s' % digest)
        print("Nothing started. Ask exactly that; on the user's yes, run again with --yes --confirm %s." % digest)
        return 12
    starting = teach('The fleet starting', (str(len(starts)),), which=1) if local else None
    state.value['launch'] = {'spec': spec, 'state': 'started' if local else 'authorized', 'effects': digest,
                             'tickets': starts, 'orchestrator': orchestrator}
    if driver:
        state.value['launch']['adapters'] = adapters
    if not state.save():
        raise Exit(10, 'Could not save the start the user said yes to; ' + NOTHING)
    if local:
        print("The user said yes to starting spec #%d's fleet %s: launch-fleet's session runner runs it in this chat "
              'now.' % (spec, where))
        print(starting)
        return hand_over(state, spec, env, builder)
    if driver:
        print("The user said yes to starting spec #%d's fleet %s. Follow the heartbeat handoff for the scheduled job."
              % (spec, where))
    else:
        print("The user said yes to starting spec #%d's fleet %s. Nothing is started by this command: the fleet starts "
              "through launch-fleet's own start path, and is said started only once its activation record reads back."
              % (spec, where))
    print(handoff(spec, state.value['repo'], adapters, orchestrator))
    return 0


def agent_words(agent):
    return ' '.join(agent[k] for k in ('harness', 'model', 'effort'))


def hand_over(state, spec, env, builder):
    """Run launch-fleet's session runner in the foreground, its lines shown as they come, then save where it stopped."""
    argv = [str(SESSION), 'run', state.value['repo'], '--spec', str(spec), '--harness', PROGRAMS[builder['harness']],
            '--model', builder['model']]
    sys.stdout.flush()
    lines, quiet = [], {s: signal.signal(s, lambda *_: None) for s in (signal.SIGINT, signal.SIGTERM)}
    try:  # an interrupt is the session's to answer (it stops cleanly and says so); this command waits for that
        child = subprocess.Popen([sys.executable, '-I', *argv], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, env=env)
        for raw in child.stdout:
            sys.stdout.buffer.write(raw)
            sys.stdout.flush()
            lines.append(raw.decode('utf-8', 'replace').rstrip('\n'))
        code = child.wait()
    except OSError:
        code = None
    finally:
        for s, handler in quiet.items():
            signal.signal(s, handler)
    stop = next((line for line in reversed(lines) if line.startswith(('session: ', 'session.py: '))), '')
    if code is None or code == 1 and stop.startswith('session: refused: '):
        del state.value['launch']
        state.value.pop('preview', None)
        saved = state.save()
        raise Exit(5 if saved else 10, 'The session %s, so this launch started nothing; the yes is withdrawn: preview '
                   'again and ask again; %s' % ('did not run' if code is None else 'was refused: '
                                                + stop[len('session: refused: '):], NOTHING))
    carry = next((line[len('carry on: '):] for line in reversed(lines) if line.startswith('carry on: ')),
                 shlex.join(['python3', '-I', *argv]))
    session = {'exit': code, 'stop': stop, 'carry_on': carry}
    state.value['launch']['session'] = session
    if not state.save():
        raise Exit(10, "Could not save where the session stopped; run progress --spec %d to read the fleet." % spec)
    print(session_line(spec, session))
    if code:
        print(OPT_IN % spec)
    return 0 if code in (0, 3, 130) else 1


def session_line(spec, session):
    """Where this chat's session last stopped, by session.py's exit codes, and its own command to carry on."""
    code, stop = session['exit'], session['stop']
    if code == 0:
        return "Spec #%d's session in this chat ended: the session finished spec #%d." % (spec, spec)
    if code == 3 and 'needs you: ' in stop:
        said = 'stopped: needs you: %s. Handle that with launch-fleet, then carry on' % stop.split('needs you: ', 1)[1]
    elif code == 130:
        said = 'stopped on interrupt; the runs it started keep going'
    elif code == 2:
        said = 'stopped: a read failed (%s)' % (stop.split(': ', 1)[-1] or 'no message')
    else:
        said = 'stopped (exit %d: %s)' % (code, stop or 'no message')
    return "Spec #%d's session in this chat %s.\ncarry on: %s" % (spec, said, session['carry_on'])


def opt_in(state, spec, env, host, got):
    """The heartbeat, the opt-in after this chat's session: its own preview, then its own yes."""
    launched = state.value.get('launch') or {}
    if host['agents'] != 'local' or launched.get('spec') != spec or not launched.get('session'):
        raise Exit(5, "The heartbeat is the opt-in after this machine's session: start the fleet in this chat first "
                      '(launch --spec %d); nothing installed.' % spec)
    orchestrator, adapters = launched.get('orchestrator') or {}, launched.get('adapters')
    program = PROGRAMS.get(orchestrator.get('harness'))
    if not program or not adapters or not shutil.which(program, path=env.get('PATH')):
        raise Exit(5, 'The heartbeat wakes an orchestrator, and no installed Claude Code or Codex harness is saved for '
                      'it; nothing installed.')
    env.update(OPENWIZ_ADAPTERS=adapters, LAUNCH_FLEET_GITHUB_ONLY='1')
    argv = [sys.executable, '-I', str(HEARTBEAT), 'install', state.value['repo'], str(spec), program,
            orchestrator['model']]
    digest = hashlib.sha256(json.dumps({'heartbeat': argv[3:], 'adapters': adapters, 'launch': launched['effects']},
                                       sort_keys=True).encode()).hexdigest()
    if not got.get('--yes'):
        shown = run(argv, env, timeout=60)
        if shown is None or shown.returncode:
            raise Exit(1, 'The heartbeat preview did not read: %s; nothing installed.' % (
                shown.stdout.decode('utf-8', 'replace').strip() if shown else 'it did not run'))
        print(shown.stdout.decode('utf-8', 'replace').rstrip('\n'))
        launched['heartbeat'] = digest
        if not state.save():
            raise Exit(10, 'Could not save the heartbeat preview; nothing installed.')
        print('This is the opt-in to keep the fleet going after this chat closes: a local heartbeat checks GitHub '
              'every 10 minutes and wakes an orchestrator (%s) when work is due. Install it?' % agent_words(orchestrator))
        print('Confirmation: %s' % digest)
        print("Nothing installed. Ask exactly that; on the user's yes, run again with --heartbeat --yes --confirm %s."
              % digest)
        return 12
    if got['--confirm'] != digest or launched.get('heartbeat') != digest:
        raise Exit(5, 'This is not the heartbeat preview the user said yes to: run launch --spec %d --heartbeat and '
                      'ask again; nothing installed.' % spec)
    done = run([*argv, '--yes'], env, timeout=120)
    if done is None or done.returncode:
        raise Exit(1, 'The heartbeat did not install: %s' % (
            done.stdout.decode('utf-8', 'replace').strip() if done else 'it did not run'))
    launched.pop('heartbeat')
    if not state.save():
        raise Exit(10, 'The heartbeat installed, but its yes could not be cleared; run progress --spec %d.' % spec)
    print(record_line(spec, activation(spec, 'local', env), 'local'))
    return 0


def handoff(spec, repo, adapters, orchestrator):
    """launch-fleet's own start path, named for the orchestrator to follow; never a second copy of it (R7)."""
    if adapters:
        return ("Next, as this project's orchestrator, follow launch-fleet's Launch section "
                "(references/launch.md#hosts-without-cloudroom) for the local heartbeat for spec #%d of %s. "
                "Use OPENWIZ_ADAPTERS=%s, driver harness `%s` and model `%s`. Show the scheduled job preview "
                "and apply it on the user's yes. Then run launch --spec %d again to read back its status." % (
                    spec, repo, shlex.quote(adapters), PROGRAMS[orchestrator['harness']], orchestrator['model'], spec))
    approved = '--provider %s --model %s --reasoning-level %s' % (
        orchestrator['harness'], orchestrator['model'], orchestrator['effort'])
    return ("Next, as this project's orchestrator, follow launch-fleet's Launch section (references/launch.md) for "
            'spec #%d of %s: its two project loops and the GitHub messages question, then "Starting one": the spec\'s '
            "loop, its entry in the private loop map, read back, and the record `%s%d`, read back. The user said "
            'yes to the fleet thread `%s`: right before creating that loop, run launch-fleet\'s `ops-starts.py flags '
            '--repo %s fleet_thread`, and only if it prints exactly that, create the loop with `--provider %s --model '
            '%s --reasoning %s`. If it prints anything else, create nothing and run launch --spec %d again: it asks '
            'for a fresh preview and yes. Then run launch --spec %d again: it says the fleet started only once that '
            'record reads back. Never start it a second way.' % (
                spec, repo, FLEET_RECORD, spec, approved, repo, orchestrator['harness'], orchestrator['model'],
                orchestrator['effort'], spec, spec))


def record_line(spec, recorded, host):
    if host != 'cloud':
        if recorded is None:
            return "Spec #%d's active local heartbeat could not be confirmed." % spec
        if recorded:
            return "Spec #%d's local heartbeat is active. It checks GitHub every 10 minutes." % spec
        if host == 'local':
            return 'No heartbeat is installed: the fleet moves only while a session runs in a chat.'
        return "Spec #%d has no local heartbeat installed yet." % spec
    if recorded is None:
        return "The spec's fleet record could not be read right now."
    if recorded:
        return "Spec #%d has its fleet record: launch-fleet's loop runs the spec." % spec
    return "Spec #%d has no fleet record yet: launch-fleet's start has not read back." % spec


def watch(got):
    state = State(got['--state'])
    spec = int(got['--spec'])
    if state.value.get('spec') != spec:
        raise Exit(5, 'This onboarding planned no spec #%d.' % spec)
    env = repository(state.value.get('repo'))
    host = (state.value.get('host') or {}).get('agents', 'cloud')
    if host == 'local':
        launched = state.value.get('launch') or {}
        print(session_line(spec, launched['session']) if launched.get('spec') == spec and launched.get('session')
              else 'Spec #%d has no session in this chat yet: run launch --spec %d.' % (spec, spec))
    print(record_line(spec, activation(spec, host, env), host))
    if host != 'cloud':
        return github_progress(spec, env)
    return progress(spec, got['--openwiz'], env)


TICKET_FIELDS = 'number,state,stateReason,closedByPullRequestsReferences,blockedBy,comments'


def ticket_state(view):
    pulls = view['closedByPullRequestsReferences']
    if view['state'] == 'CLOSED':
        return 'merged' if view['stateReason'] == 'COMPLETED' and pulls else 'unknown'
    if pulls:
        return 'in_review'
    if any(b['state'] == 'OPEN' for b in view['blockedBy']['nodes']):
        return 'blocked'
    for comment in view['comments']:
        lines = comment['body'].splitlines()
        if lines[:1] == ['<!-- openwiz:status v1 -->'] and 'agent: builder' in lines and (
                'state: working' in lines or 'state: asking' in lines):
            return 'building'
    return 'ready'


def github_progress(spec, env):
    try:
        _, members = spec_facts(spec, env)
        states = []
        for number in sorted(members):
            view = gh_json(['issue', 'view', str(number), '--json', TICKET_FIELDS], env, 'ticket #%d' % number)
            assert view['number'] == number
            states.append((number, ticket_state(view)))
    except (Exit, AssertionError, KeyError, TypeError, AttributeError):
        print('Progress for spec #%d is unreadable right now.' % spec)
        return 1
    for number, known in states:
        print('#%d %s' % (number, known))
    found = [known for _, known in states]
    parts = ['%d %s' % (found.count(s), s.replace('_', ' ')) for s in STATES + ('unknown',) if found.count(s)]
    print('%d tickets: %s' % (len(found), ', '.join(parts) or 'none yet'))
    print('Counts are progress, not a first merge: a merge counts only when GitHub reads it back.')
    return 0


def progress(spec, program, env):
    result = run([program, 'fleet', str(spec), '--json'], env)
    try:
        assert result is not None and result.returncode == 0
        view = strict(result.stdout.decode('utf-8'))
        assert view['schema'] == 'openwiz.fleet.v1' and view['data']['view'] == 'fleet'
        assert view['data']['fleet']['spec'] == spec
        tickets, counts = view['data']['tickets'], view['data']['fleet']['progress']
    except (AssertionError, UnicodeDecodeError, ValueError, KeyError, TypeError):
        print('Progress for spec #%d is unreadable right now.' % spec)
        return 1
    for ticket in tickets:
        known = ticket['state'].get('known') if isinstance(ticket.get('state'), dict) else None
        print('#%d %s' % (ticket['number'], known if known in STATES else 'unknown'))
    known = counts.get('known') if isinstance(counts, dict) else None
    if isinstance(known, dict):
        parts = ['%d %s' % (known[s], s.replace('_', ' ')) for s in STATES + ('unknown',) if known.get(s)]
        print('%d tickets: %s' % (known.get('tickets', 0), ', '.join(parts) or 'none yet'))
    else:
        print('Counts unknown: some reads are incomplete.')
    print('Counts are progress, not a first merge: a merge counts only when GitHub reads it back.')
    return 0


def first_merge(got):
    """The first merge, read back from GitHub: the teacher's merged line, then the closing offer."""
    state = State(got['--state'])
    spec, launched = state.value.get('spec'), state.value.get('launch') or {}
    if not spec or launched.get('spec') != spec or launched.get('state') != 'started':
        raise Exit(5, "This onboarding's fleet has not started; there is no first merge to read.")
    env = repository(state.value.get('repo'))
    pull = gh_json(['pr', 'view', got['--pr'], '--repo', state.value['repo'], '--json',
                    'number,url,title,state,mergedAt,closingIssuesReferences'], env, 'the pull request')
    try:
        assert isinstance(pull, dict) and isinstance(pull['closingIssuesReferences'], list)
        closes = {(('%s/%s' % (issue['repository']['owner']['login'], issue['repository']['name'])).lower(),
                   issue['number']) for issue in pull['closingIssuesReferences']}
        assert all(type(n) is int and isinstance(r, str) for r, n in closes) and type(pull['number']) is int
        assert pull['number'] == int(got['--pr']) and isinstance(pull['url'], str) and isinstance(pull['title'], str)
        assert pull['state'] in ('OPEN', 'MERGED', 'CLOSED') and (pull['mergedAt'] is None or isinstance(pull['mergedAt'], str))
        merged = pull['state'] == 'MERGED' and isinstance(pull['mergedAt'], str)
    except (KeyError, TypeError, AssertionError):
        raise Exit(1, 'The pull request did not read back completely; no merge counted.')
    if not merged:
        raise Exit(5, '%s has not merged; a merge counts only when GitHub reads it back.' % pull['url'])
    _, members = spec_facts(spec, env)
    if not closes & {(state.value['repo'].lower(), n) for n in members}:
        raise Exit(5, "%s closes no ticket of spec #%d, so it is not this fleet's merge." % (pull['url'], spec))
    state.value['merge'] = pull['url']
    if not state.save():
        raise Exit(10, 'Could not save the first merge.')
    repo = state.value['repo']
    print(teach('Merged', (pull['url'], ' '.join(pull['title'].split()), repo)))
    print(teach('The closing offer', (repo.split('/')[1],)))
    return 0


def prepared(folder):
    """The repository setup selected for this onboarding (its prepared project, or
    else its sign-in), read only; None when there is none or it is unreadable."""
    path = Path(folder) / 'setup/state.json'
    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            return None
        value = strict(path.read_text(encoding='utf-8'))
        assert value['schema'] == 'openwiz.setup-state.v1'
        for record in (value.get('project'), value.get('identity')):
            if isinstance(record, dict) and isinstance(record.get('repository'), str):
                return record['repository'] if re.fullmatch(REPOSITORY, record['repository']) else None
    except (OSError, ValueError, KeyError, TypeError, AssertionError):
        pass
    return None


def resume(got):
    """The first unfinished first-fleet step, from the saved state alone."""
    state = State.__new__(State)  # read only: no lock, nothing opened for writing
    state.path = Path(got['--state'])
    if not state.path.is_absolute():
        raise Exit(2, 'usage: --state takes an absolute path')
    value = state.read()
    created, launched = value.get('created') or {}, value.get('launch') or {}
    demo = created.get('repo') if created.get('state') != 'absent' else None  # an absent create made nothing
    repo, spec = value.get('repo') or demo, value.get('spec')
    host, setting_ = value.get('host'), value.get('setting') or {}
    folder = got.get('--setup-state')
    candidate = prepared(folder) if folder else None
    choices = value.get('choices') or {}
    if not host:
        step = ('where', "Say the teacher's opening lines, then run where --build <build> to list the hosts this "
                'OpenWiz offers. Reuse the choice from this chat or the install continuation. Ask where agents run '
                'when no offered host is known. Then run where --agents <the pick> --build '
                "<build> and say what it prints: the cost and, for a driver host, where its login lives. Only on the "
                "user's yes to that, run it again with --yes.")
    elif created.get('state') in ('pending', 'uncertain'):
        step = ('project', 'Creating %s is %s: run create-repo --repo %s --yes again; it reads before it creates.'
                % (created['repo'], created['state'], created['repo']))
    elif not repo and candidate:
        step = ('project', 'This onboarding has no repository yet. Setup prepared %s, perhaps for an earlier '
                'project: ask the owner whether this first fleet is for it. On their yes, run select --repo %s; '
                'otherwise offer the ideas, then choose or create its one repository.' % (candidate, candidate))
    elif not repo:
        step = ('project', 'Offer the three choices, with ideas.md for anyone without an idea, then choose or '
                'create its one repository.')
    elif not value.get('setup') and host['agents'] != 'cloud':
        step = ('connect', 'Prepare %s with setup.py prepare --host %s and omit CloudRoom IDs. '
                'Run setup.py check, then continue.' % (repo, host['agents']))
    elif not value.get('setup'):
        step = ('connect', '%sConnect %s with the installed tools, then run continue.' % (
            'Setup already prepared it; ' if candidate == repo else '', repo))
    elif spec and launched.get('spec') == spec and launched.get('state') in ('authorized', 'pending', 'uncertain') \
            and host['agents'] != 'cloud':
        step = ('launch', 'Run launch --spec %d to read back the heartbeat status and follow the handoff it prints.'
                % spec)
    elif spec and launched.get('spec') == spec and launched.get('state') in ('authorized', 'pending', 'uncertain'):
        step = ('launch', "The user said yes to starting spec #%d: run launch --spec %d first, which checks the "
                "Orchestrator is still the one the user said yes to and names the start path; finish launch-fleet's "
                'start path (references/launch.md, "Starting one") exactly as it says, then run launch --spec %d to '
                'read its fleet record back; never start it a second way.' % (spec, spec, spec))
    elif spec and launched.get('spec') == spec and launched.get('state') == 'started' and value.get('merge'):
        step = ('offer', 'Say the closing offer, as first-merge printed it.')
    elif spec and launched.get('spec') == spec and launched.get('state') == 'started':
        step = ('watch', "Run progress --spec %d, say the teacher's line for each moment, and run first-merge "
                '--pr <N> when a pull request merges.' % spec)
    elif not value.get('grill'):
        step = ('grill', "Run the short grill; on the user's yes in chat, run grill --confirmed <its comment URL>.")
    elif not choices:
        if host['agents'] == 'cloud':
            step = ('agents', 'Run choose --from-setup.')
        else:
            step = ('agents', 'Save openwiz models --json --host %s, then run choose --options <saved file> '
                    '--from-setup.' % host['agents'])
    elif choices.get('builder_tables') != 'read':
        step = ('agents', '%s %s' % (chosen_line(choices),
                                     tables_line(choices, 'have not been read back with this choice yet')))
    elif host['agents'] == 'local' and not value.get('mode'):
        step = ('mode', 'Run mode, explain each permission mode as it prints, pick none for the owner, then run '
                'mode --mode <their pick>.')
    elif setting_.get('state') not in ('opened', 'merged'):
        step = ('setting', 'Run setting%s.' % (' again: its pull request is uncertain' if setting_ else ''))
    elif not spec:
        step = ('plan', 'Run to-spec, which runs to-tickets; no plan approval is asked. Then run spec --spec <N> '
                '--repo %s.' % repo)
    else:
        step = ('launch', 'Preview with launch --spec %d and ask for a yes to exactly that.' % spec)
    print('Next: %s.' % step[0])
    if repo:
        print('Repository: %s.' % repo)
    print(step[1])
    return 0


def main(argv):
    try:
        command, got = parse(argv)
        if command == 'where':
            return where(got)
        if command == 'mode':
            return mode(got)
        if command == 'setting':
            return setting(got)
        if command == 'grill':
            return grill(got)
        if command == 'first-merge':
            return first_merge(got)
        if command == 'continue':
            return carry_on(got)
        if command == 'decisions':
            return connect_decisions(got)
        if command == 'create-repo':
            return create_repo(got)
        if command == 'select':
            return select(got)
        if command == 'choose':
            return choose(got)
        if command == 'spec':
            return record_spec(got)
        if command == 'launch':
            return launch(got)
        if command == 'next':
            return resume(got)
        return watch(got)
    except Exit as stop:
        print(stop.args[0])
        return stop.code


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
