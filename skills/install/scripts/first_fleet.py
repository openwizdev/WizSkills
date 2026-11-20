#!/usr/bin/env python3
"""The install skill's first-fleet checks (#1108, joined to install in #636). Standard library only.

  first_fleet.py where --state FILE --agents local|cloud [--yes]
  first_fleet.py continue --state FILE --setup-state DIR [--explained]
  first_fleet.py decisions --state FILE --setup-state DIR [--yes]
  first_fleet.py create-repo --state FILE --repo OWNER/NAME [--yes]
  first_fleet.py select --state FILE --repo OWNER/NAME
  first_fleet.py mode --state FILE [--mode MODE]
  first_fleet.py setting --state FILE [--yes]
  first_fleet.py grill --state FILE --confirmed URL
  first_fleet.py choose --state FILE --options FILE (--harness P --model M --effort E | --from-setup) [--agents cloud|local]
  first_fleet.py spec --state FILE --spec N --repo OWNER/NAME
  first_fleet.py launch --state FILE --spec N [--yes --confirm DIGEST]
  first_fleet.py progress --state FILE --spec N --openwiz PROGRAM
  first_fleet.py first-merge --state FILE --pr N
  first_fleet.py next --state FILE [--setup-state DIR]

The onboarding road (#1358): `where` records where the agents run, this
machine through OpenWiz's local driver or Cloudroom, only on the user's answer
(--yes), after checking what that needs and printing the teacher's walk-through
for anything missing; it never runs a sign-in. On this machine `mode` lists
the harness's permission modes, each explained, picks none, and records the
one the owner names (J254 A); KN3's driver passes it unchanged. `setting` writes that choice to
the project's host setting, docs/agents/host.md (records v1, section 6), as one
pull request the user merges, only on --yes; Cloudroom needs no file. `grill`
records the private comment URL of the user's yes to the grill in chat; the
plan then approves itself by its checks (to-tickets' machine plan approval),
and no plan approval is asked. `first-merge` reads a merged pull request back
from GitHub and prints the teacher's merged line and closing offer.

It adds no approval, planner or engine. `continue` carries what install and
setup already recorded in the installed OpenWiz state (DIR is its `<state>`):
the one selected repository and CloudRoom project, the acting GitHub identity,
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

`launch` starts the first fleet the way launch-fleet starts every fleet, only
on the user's yes right before it (a preview names the host and that it can
cost money, with a digest of its exact effects; `--yes --confirm DIGEST`
starts only if a fresh read still has exactly those effects), and only from the spec's latest approval when it is the machine plan
approval of this onboarding's confirmed grill, on the host the user chose (a
local host only once its setting is on the default branch). It
reads launch-fleet's own frontier (../../launch-fleet/scripts/fleet.sh
frontier, which checks that to-tickets's approval is current), keeps this
spec's tickets, reads the fleet settings setup wrote (every builder table the
user's choice, each reviewer from the other model family), and starts one
fleet thread for the spec, with launch-fleet's own brief. That thread makes
its own loop, which runs the spec's check (`fleet.sh spec <S>`), records
itself on the spec and starts the frontier's builders. It never calls the engine or
the engine's tick. The launch is saved before the start runs, and is never run
twice: a repeat only reads the spec's fleet record and progress, and an
uncertain start stays uncertain until that record reads back. Every command
checks the checkout is the repository this onboarding recorded.

`choose` records the choice for where the agents run, then reads the fleet's
builder tables back: the agents step is done only once both name exactly that
choice (#1615).

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
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.parse

LAUNCH_FLEET = Path(__file__).resolve().parents[2] / 'launch-fleet'
FLEET_SH = LAUNCH_FLEET / 'scripts/fleet.sh'
HOST_PY = LAUNCH_FLEET / 'scripts/host.py'
OPTIONS = {
    'where': ({'--state', '--agents'}, {'--yes'}, set()),
    'mode': ({'--state'}, set(), {'--mode'}),
    'setting': ({'--state'}, {'--yes'}, set()),
    'grill': ({'--state', '--confirmed'}, set(), set()),
    'first-merge': ({'--state', '--pr'}, set(), set()),
    'continue': ({'--state', '--setup-state'}, {'--explained'}, set()),
    'decisions': ({'--state', '--setup-state'}, {'--yes'}, set()),
    'create-repo': ({'--state', '--repo'}, {'--yes'}, set()),
    'select': ({'--state', '--repo'}, set(), set()),
    'choose': ({'--state', '--options'}, {'--from-setup'}, {'--harness', '--model', '--effort', '--agents'}),
    'spec': ({'--state', '--spec', '--repo'}, set(), set()),
    'launch': ({'--state', '--spec'}, {'--yes'}, {'--confirm'}),
    'progress': ({'--state', '--spec', '--openwiz'}, set(), set()),
    'next': ({'--state'}, set(), {'--setup-state'}),
}
FAMILY = {'claude-code': 'claude', 'codex': 'gpt'}
REVIEWER = {'claude': 'Reviewer for Claude-built', 'gpt': 'Reviewer for GPT-built'}
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
    if '--pr' in got and not re.fullmatch(r'[1-9][0-9]{0,9}', got['--pr']):
        raise Exit(2, 'usage: --pr takes a pull request number')
    if '--confirmed' in got and not re.fullmatch(GRILL, got['--confirmed']):
        raise Exit(2, "usage: --confirmed takes the private comment URL of the user's yes to the grill")
    if '--repo' in got and not re.fullmatch(REPOSITORY, got['--repo']):
        raise Exit(2, 'usage: --repo takes owner/name')
    if '--agents' in got and got['--agents'] not in ('cloud', 'local'):
        raise Exit(2, 'usage: --agents is cloud or local')
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


def run(argv, env=None):
    try:
        return subprocess.run(argv, capture_output=True, timeout=600, env=env)
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
# local_driver() is a thin stub against the interface KN3's open pull request
# defines; swap it when KN3 merges. host_setting() calls KN6's merged reader.

def local_driver(env):
    """Stub until KN3 (#1368, OpenWiz #1455) merges: the local driver's `version` answer, or None.

    The driver is `$OPENWIZ_ADAPTERS/local/driver` (driver v1), as launch-fleet's
    host.py (#1371, WizSkills #64) finds it. Only `version` is called here: it starts nothing."""
    adapters = env.get('OPENWIZ_ADAPTERS', '')
    path = Path(adapters, 'local/driver')
    if not os.path.isabs(adapters) or not path.is_file() or not os.access(path, os.X_OK):
        return None
    result = run([str(path), 'version'], env)
    try:
        assert result is not None and result.returncode == 0
        version = strict(result.stdout.decode('utf-8'))
        assert isinstance(version, dict) and version['driver'] == 'local'
        assert isinstance(version['can'], list) and 'start' in version['can']
        return version
    except (AssertionError, UnicodeDecodeError, ValueError, KeyError, TypeError):
        return None


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


# Stub until KN3 (#1368, OpenWiz #1455) merges: the harness permission mode the owner picks once (J254 A),
# saved where KN3's driver at a00ada1 reads it, the repository's docs/agents/fleet.md, as exactly one row
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


def saved_mode(env):
    """The permission mode the default branch's docs/agents/fleet.md saves, or None for no row; read as
    launch-fleet's host.py reads the host setting, from this checkout's origin, and as KN3's driver reads it."""
    sys.dont_write_bytecode = True  # never write bytecode into launch-fleet's folder
    spec = importlib.util.spec_from_file_location('launch_fleet_host', HOST_PY)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        module.SETTING = Path(MODE_FILE)  # the same default-branch read, for KN3's file
        text = module.setting_text()
    except Exception as error:  # host.py's Unreadable, or a missing git
        raise Exit(1, 'Could not read %s from the default branch: %s; %s' % (MODE_FILE, error, NOTHING))
    values = mode_rows(text)
    if len(values) > 1 or None in values:
        raise Exit(5, '%s needs exactly one `%s `<mode>` |` row; ask the owner to fix it; %s' % (
            MODE_FILE, MODE_ROW, NOTHING))
    return values[0] if values else None


# KN3's host-side approval (security R6, option A), behind the KN3 stub until OpenWiz #1455 merges: the same
# pick saved on the owner's machine, per repository and harness, outside the repository, in KN3's own form at
# 857d107: $OPENWIZ_LOCAL_STATE/approvals.json (default ~/.local/state/openwiz-local), one JSON object
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
    with os.fdopen(fd, encoding='utf-8') as handle:
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


def approve_host(env, repo, program, picked):
    """Save the owner's pick as this machine's approval: add only this entry, never change or widen another."""
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
    path, temp = approval_file(env), None
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix='.approvals.', suffix='.new', dir=path.parent)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
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


def mode_section(picked):
    return ('\n## Harness permission mode\n\nThe mode the owner picked for builders on this machine; the local '
            'driver passes it to the harness unchanged. To change it, ask your agent to edit this one row.\n\n'
            '| Setting | Value |\n| --- | --- |\n%s `%s` |\n' % (MODE_ROW, picked))


# --- Where agents run (#1358) ---------------------------------------------------

def where(got):
    """Check what the chosen place needs, print the walk-through for anything missing, and record it on --yes."""
    state = State(got['--state'])
    agents, env = got['--agents'], gh_env()
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
    elif not shutil.which('room-cli', path=env.get('PATH')):
        missing.append(('the Cloudroom app, signed in', 'https://cloudroom.dev', None))
    if missing:
        for what, link, then in missing:
            print(teach('Where agents run', (what, link), which=1))
            if then:
                print(then)
        raise Exit(5, 'Nothing recorded: run this again once the user says done.')
    if agents == 'local' and local_driver(env) is None:
        raise Exit(5, "This OpenWiz has no local driver to run agents on this machine (set OPENWIZ_ADAPTERS to "
                      "OpenWiz's adapters folder, or update OpenWiz); choose Cloudroom, or stop; nothing recorded.")
    if agents == 'local':
        print('Agents run on this machine through OpenWiz\'s local driver, with %s you are signed into, while this '
              'machine is awake. Their model use is billed by that harness, as it is today.' % ', '.join(harnesses))
    else:
        print('Agents run in Cloudroom, many at once. They use your Cloud Credits: unknown until measured. '
              'Model-provider charges are separate.')
    print('OpenWiz is free now.')
    if not got.get('--yes'):
        print("Nothing recorded. Ask where agents run; on the user's answer, run again with that --agents and --yes.")
        return 12
    if state.value.get('launch'):
        raise Exit(5, 'This onboarding already launched its fleet; ask to change the host setting instead.')
    state.value['host'] = {'agents': agents, 'harnesses': harnesses}
    state.value.pop('setting', None)
    if not state.save():
        raise Exit(10, 'Could not save where agents run; nothing recorded.')
    print('Recorded: agents run %s.' % ('on this machine' if agents == 'local' else 'in Cloudroom'))
    return 0


# --- The continuation from install and setup (#636) ----------------------

def setup_facts(folder):
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
                       for k in ('repository', 'project', 'harness', 'model', 'effort'))
            assert re.fullmatch(REPOSITORY, project['repository'])
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

    needed = ['cloudroom', 'personal_github', 'project'] + ([] if skipped else ['github_app'])
    problems = []
    for component in needed:
        found, why = state(component)
        if found != 'verified':
            problems.append('%s: %s (%s)' % (NAMES[component], found, why))
    harness, why = state('harness')
    if harness == 'verified' or why == 'harness_listed':
        harness_line = 'listed by CloudRoom; its login is not proven by setup'
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
    return {'setup_state': str(folder), 'repository': repository, 'project': project['project'],
            'settings': {k: project[k] for k in ('harness', 'model', 'effort')},
            'identity': {'selected': 'personal_login' if skipped else 'app', 'acting': acting},
            'brain': {'location': brain['location'], 'repository': brain['brain_repository']},
            'harness': harness_line}


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
          'Restart the OpenWiz server afterwards.' % (pair['public']['owner'], pair['public']['name'],
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
    print('Decisions now reads the companion. Restart the OpenWiz server, then run continue.')
    return 0


def withdraw(state):
    """A failed refresh withdraws launch eligibility; the owner's choices and work stay."""
    if 'setup' in state.value:
        del state.value['setup']
        state.save()


def refreshed(state, folder):
    """Setup's current facts, or Exit after withdrawing the carried setup."""
    try:
        return setup_facts(folder)
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
    print('Carried from setup: repository %s, CloudRoom project %s.' % (facts['repository'], facts['project']))
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

def host_text():
    return ('# Where agents run\n\nOpenWiz starts, wakes and stops this project\'s agents through the host named '
            'below: a driver in OpenWiz\'s adapters/ folder. `local` is the machine the agents run on. To change '
            'it, ask your agent to edit this one line.\n\nHost: local\n')


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
        raise Exit(5, 'Only agents on this machine need a permission mode; Cloudroom sets its own. Nothing recorded.')
    if not carried:
        raise Exit(5, 'Connect the repository first (continue): the mode is for the harness it prepares; '
                      'nothing recorded.')
    harness = carried['settings']['harness']
    modes = MODES.get(harness)
    if not modes:
        raise Exit(5, 'No permission modes are known for %s; nothing recorded.' % harness)
    if '--mode' not in got:
        print('%s on this machine runs with the permission mode the owner picks, once. The driver passes it '
              'unchanged and never chooses or widens it:' % harness)
        for name, why in modes:
            print('- %s: %s' % (name, why))
        print("Nothing recorded. Ask the owner which one, in those words, and pick none for them; on their answer, "
              'run again with --mode <their pick>.')
        return 12
    if got['--mode'] not in [name for name, _ in modes]:
        raise Exit(5, '%s is not one of %s\'s permission modes (%s); nothing recorded.' % (
            got['--mode'], harness, ', '.join(name for name, _ in modes)))
    recorded = state.value.get('setting') or {}
    if recorded.get('state') in ('pending', 'opened', 'merged') and recorded.get('mode') != got['--mode']:
        raise Exit(5, 'The host setting already carries %s; ask the owner to change that line instead; '
                      'nothing recorded.' % (recorded.get('mode') or 'no permission mode'))
    approve_host(os.environ, carried['repository'], PROGRAMS[harness], got['--mode'])
    state.value['mode'] = {'harness': harness, 'mode': got['--mode']}
    if not state.save():
        raise Exit(10, 'Could not save the permission mode; nothing recorded.')
    print('Recorded: agents on this machine run %s with the %s permission mode the owner picked, saved as this '
          "machine's host-side approval for %s (outside the repository); the host setting adds the matching %s "
          'row.' % (harness, got['--mode'], carried['repository'], MODE_FILE))
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
    local = host['agents'] == 'local'
    if local and not picked:
        raise Exit(5, 'Ask the owner to pick the harness permission mode first (mode); nothing written.')
    env = repository(repo)
    now = host_setting(env)
    if now is not None and now != ('local' if local else None):
        raise Exit(5, '%s already says Host: %s on the default branch; OpenWiz never overwrites it. Ask the user '
                      'whether to change that line, or answer where agents run again; nothing written.' % (HOST_FILE, now))
    writes = []
    if local:
        fleet = raw(repo, MODE_FILE, env)
        if fleet is None:
            raise Exit(5, '%s is not on the default branch yet: run setup and merge its settings (Agents) first; '
                          'nothing written.' % MODE_FILE)
        values = mode_rows(fleet)
        if values and values != [picked]:
            raise Exit(5, '%s already saves %s; OpenWiz never adds a second row or replaces the owner\'s. Ask the '
                          'owner whether to change that row; nothing written.' % (
                              MODE_FILE, ', '.join('`%s`' % v if v else 'an unreadable row' for v in values)))
        writes = ([HOST_FILE] if now is None else []) + ([MODE_FILE] if not values else [])
    if not writes:
        state.value['setting'] = {'host': 'local' if local else None, 'state': 'merged', 'mode': picked}
        if not state.save():
            raise Exit(10, 'Could not save the host setting; nothing written.')
        print('The host setting already matches: %s.' % (
            'Host: local and the %s permission mode, on the default branch' % picked if local
            else 'no host file, so Cloudroom, the default'))
        return 0
    recorded = state.value.get('setting') or {}
    if recorded.get('state') in ('pending', 'opened'):
        found = host_pull(repo, env)
        if found and found[1] == 'CLOSED':
            raise Exit(5, 'The host setting pull request %s was closed without merging; the user reopens and merges '
                          'it, or answers where agents run again; nothing written.' % found[0])
        if found:
            state.value['setting'] = {'host': 'local', 'state': 'opened', 'pull': found[0], 'mode': picked}
            state.save()
            print('The host setting pull request is open: %s. The user merges it; launch waits for it.' % found[0])
            return 0
    said = {HOST_FILE: 'add %s holding `Host: local`' % HOST_FILE,
            MODE_FILE: 'add one row, %s `%s` |, to %s, changing no other line' % (MODE_ROW, picked, MODE_FILE)}
    print('Effect: on a new branch %s of %s, %s, and open one pull request for you to merge. Nothing else is '
          'written.' % (HOST_BRANCH, repo, ' and '.join(said[w] for w in writes)))
    if not got.get('--yes'):
        print("Nothing written. On the user's yes to exactly this, run again with --yes.")
        return 12
    state.value['setting'] = {'host': 'local', 'state': 'pending', 'mode': picked}
    if not state.save():
        raise Exit(10, 'Could not save the host setting first; nothing written.')
    base = run(['gh', 'api', 'repos/%s' % repo, '--jq', '.default_branch'], env)
    branch = base.stdout.decode('utf-8', 'replace').strip() if base is not None and base.returncode == 0 else ''
    if not branch:
        raise Exit(1, "Could not read the default branch; nothing written.")
    tip = run(['gh', 'api', 'repos/%s/git/ref/heads/%s' % (repo, branch), '--jq', '.object.sha'], env)
    sha = tip.stdout.decode('utf-8', 'replace').strip() if tip is not None and tip.returncode == 0 else ''
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise Exit(1, "Could not read the default branch's tip; nothing written.")
    run(['gh', 'api', '-X', 'POST', 'repos/%s/git/refs' % repo, '-f', 'ref=refs/heads/' + HOST_BRANCH,
         '-f', 'sha=' + sha], env)
    for path in writes:
        have = raw(repo, path, env, HOST_BRANCH)
        if path == HOST_FILE:
            if have == host_text():
                continue
            text, blob = host_text(), None
        else:
            if have is None or mode_rows(have) == [picked]:
                continue  # the branch lost fleet.md (read again on the retry), or the row is already there
            text = have.rstrip('\n') + '\n' + mode_section(picked)
            found = run(['gh', 'api', 'repos/%s/contents/%s?ref=%s' % (repo, path, HOST_BRANCH), '--jq', '.sha'], env)
            blob = found.stdout.decode('utf-8', 'replace').strip() if found is not None and found.returncode == 0 else ''
            if not re.fullmatch(r'[0-9a-f]{40}', blob):
                raise Exit(6, 'Could not read %s on %s; run this again to read it before anything else.' % (
                    path, HOST_BRANCH))
        put = ['gh', 'api', '-X', 'PUT', 'repos/%s/contents/%s' % (repo, path), '-f',
               'message=Where agents run: Host: local, %s' % picked, '-f',
               'content=' + base64.b64encode(text.encode()).decode(), '-f', 'branch=' + HOST_BRANCH]
        run(put + (['-f', 'sha=' + blob] if blob else []), env)
    if host_pull(repo, env) is None:
        run(['gh', 'pr', 'create', '--repo', repo, '--head', HOST_BRANCH, '--base', branch, '--title',
             'Where agents run: this machine', '--body', 'Adds `Host: local` to %s and the owner\'s harness '
             'permission mode as one row of %s: OpenWiz starts this project\'s agents through its local driver, '
             'which passes that mode to the harness unchanged (records v1, section 6). Merge it to start the first '
             'fleet there.' % (HOST_FILE, MODE_FILE)], env)
    found = host_pull(repo, env)
    if found is None:
        raise Exit(6, 'Whether the host setting pull request was opened is uncertain; run this again to read it '
                      'before anything else.')
    state.value['setting'] = {'host': 'local', 'state': 'opened', 'pull': found[0], 'mode': picked}
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
            'on this machine' if host['agents'] == 'local' else 'in Cloudroom'))
    if got.get('--from-setup'):
        carried = state.value.get('setup')
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
    efforts = [e for h in harnesses for m in h['models'] if m['model'] == settings['model'] for e in m['efforts']]
    if len(harnesses) != 1 or settings['effort'] not in efforts:
        raise Exit(5, 'That harness, model and effort are not among the offered options; nothing recorded.')
    if settings['harness'] not in FAMILY:
        raise Exit(5, "The fleet's review rules cover Claude Code and Codex builders only; nothing recorded.")
    if host['agents'] == 'local' and settings['harness'] not in host['harnesses']:
        raise Exit(5, '%s is not on this machine, so its agents cannot run here; nothing recorded.' % settings['harness'])
    choices = dict(settings, agents=host['agents'])
    read = None  # unread: the choice is recorded, its builder tables are not settled (#1615)
    try:
        rules = fleet_rules(repository(state.value.get('repo')), state.value['repo'])
    except Exit:
        rules = None
    if rules is not None:
        try:
            review(choices, rules)  # the launch's own check of the same tables
            read = True
        except Exit:
            read = False
    if read:
        choices['builder_tables'] = 'read'
    state.value['choices'] = choices
    if not state.save():
        raise Exit(10, 'Could not save the choices; nothing recorded.')
    print(chosen_line(choices) + (' (as prepared in setup)' if got.get('--from-setup') else ''))
    if read:
        print("Read back: both of the fleet's builder tables name exactly this choice, with an other-family "
              'reviewer.')
    else:
        print(tables_line(choices, 'could not be read' if read is None else 'do not name this choice yet'))
        return 1 if read is None else 0
    return 0


def chosen_line(choices):
    where = 'in Cloudroom' if choices['agents'] == 'cloud' else 'on this machine'
    return 'Recorded: builders use %s %s %s, and run %s.' % (
        choices['harness'], choices['model'], choices['effort'], where)


def tables_line(choices, why):
    return ("The fleet's builder tables %s: run setup so both name exactly %s %s %s, with the reviewer from the "
            'other family, then run choose again to read them back.' % (
                why, choices['harness'], choices['model'], choices['effort']))


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
    result = run(['gh', 'api', 'repos/%s/contents/docs/agents/fleet.md' % repo,
                  '-H', 'Accept: application/vnd.github.raw+json'], env)
    if result is None or result.returncode != 0:
        raise Exit(1, "Could not read the fleet settings (docs/agents/fleet.md); run setup; " + NOTHING)
    found, name = {}, None
    for line in result.stdout.decode('utf-8', 'replace').split('\n'):
        if line.startswith('## '):
            name = line[3:].strip()
            found.setdefault(name, [])
        elif name is not None:
            found[name].append(line)
    rules = {key: agent(found[title]) if title in found else None for key, title in (
        ('builder', 'Builder'), ('builder_small', 'Builder for small tickets'),
        ('reviewer_claude', REVIEWER['claude']), ('reviewer_gpt', REVIEWER['gpt']))}
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


def brief(spec, repo):
    """launch-fleet's own fleet-thread brief ("Fleet threads", "Starting one"), literally."""
    return ("You are the fleet thread for spec #%d of %s. Use the launch-fleet skill. Read "
            "'skills/launch-fleet/SKILL.md' if present, otherwise find '*/skills/launch-fleet/SKILL.md' only inside "
            "your own harness's configured plugin cache: Codex uses CODEX_HOME/plugins/cache (default "
            "HOME/.codex/plugins/cache); Claude uses CLAUDE_CODE_PLUGIN_CACHE_DIR/cache when set, otherwise "
            "CLAUDE_CONFIG_DIR/plugins/cache (default HOME/.claude/plugins/cache); for another harness use its "
            "installation metadata. Prefer active installation metadata over cache scanning when available. During "
            "cache scans exclude other harness caches, source checkouts, orphaned versions marked .orphaned_at, and "
            "targets outside the selected cache. Follow symlinks and deduplicate real paths. Verify "
            ".claude-plugin/plugin.json manifest name openwiz and entry ./skills/launch-fleet; report missing, "
            "unreadable or ambiguous matches, otherwise read the unique matching file and follow it; do its Fleet "
            "threads section, first wake." % (spec, repo))


def fleet_recorded(spec, env):
    """Only configured record authors settle a start; unread input stays unknown."""
    bodies = record_comments(spec, env)
    if bodies is None:
        return None
    return any(body.split('\n')[0].strip() == FLEET_RECORD + str(spec) for body in bodies)


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
    previous = state.value.get('launch')
    if previous and previous['spec'] == spec and previous['state'] != 'refused':
        recorded = fleet_recorded(spec, env)
        if previous['state'] in ('pending', 'uncertain') and recorded:
            previous['state'] = 'started'
            state.save()
        settled = previous['state'] == 'started'
        print('Spec #%d already started once (%s); not starting again.' % (
            spec, 'its fleet thread was started' if settled else 'uncertain: never a retry'))
        print(record_line(spec, recorded))
        return 0 if settled else 6
    # Review R4: the carried setup must still be what setup verifies now.
    if not isinstance(carried.get('setup_state'), str):
        withdraw(state)
        raise Exit(5, 'The carried setup names no setup state to recheck; run continue again; ' + NOTHING)
    current = refreshed(state, carried['setup_state'])
    if any(current[k] != carried.get(k) for k in current):
        withdraw(state)
        raise Exit(5, 'Setup changed since it was carried; run continue again; ' + NOTHING)
    local = host['agents'] == 'local'
    named = host_setting(env)
    if named != ('local' if local else None):
        raise Exit(5, 'The host setting on the default branch says %s, but the user chose %s: %s; %s' % (
            'Host: ' + named if named else 'no host', 'this machine' if local else 'Cloudroom',
            'merge the host setting pull request first (setting)' if local and named is None else
            'answer where agents run again, or ask to change that line', NOTHING))
    picked = (state.value.get('mode') or {}).get('mode')
    if local and (not picked or saved_mode(env) != picked):
        raise Exit(5, 'No `%s `%s` |` row, the Harness permission mode the owner picked, is in %s on the default '
                      "branch, and the local driver starts no agent without it: run mode, then setting, and merge "
                      'it; %s' % (MODE_ROW, picked or '<mode>', MODE_FILE, NOTHING))
    if local:
        program = PROGRAMS[choices['harness']]
        approved = host_approval(env, state.value['repo'], program)
        if approved != picked:
            raise Exit(5, "This machine's host-side approval for %s with %s is %s, not the `%s` row %s saves, and "
                          "KN3's start refuses unless they match: run mode --mode %s to save the owner's pick here, "
                          'or ask the owner which mode they mean; %s' % (
                              state.value['repo'], program, approved or 'missing', picked, MODE_FILE, picked, NOTHING))
    if local and local_driver(env) is None:
        raise Exit(5, "This OpenWiz's local driver no longer answers, so no agent can run on this machine; " + NOTHING)
    plan_approved(spec, env, confirmed)
    ready = frontier(env)
    title, members = spec_facts(spec, env)
    starts = sorted(n for n in ready if n in members)
    if not starts:
        raise Exit(5, 'No approved ticket of spec #%d is ready to start: the plan changed since its checks passed, '
                      'or is still blocked; %s' % (spec, NOTHING))
    builder, reviewer = review(choices, fleet_rules(env, state.value['repo']))
    where = 'on this machine' if local else 'in Cloudroom'
    effects = {'repo': state.value['repo'], 'spec': spec, 'project': carried['project'], 'title': title,
               'host': host['agents'], 'mode': picked if local else None, 'builder': builder, 'reviewer': reviewer, 'grill': confirmed,
               'tickets': [[n, ready[n]] for n in starts]}
    digest = hashlib.sha256(json.dumps(effects, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if got.get('--yes'):
        shown = state.value.get('preview') or {}
        if got['--confirm'] != digest or shown.get('effects') != digest or shown.get('spec') != spec:
            raise Exit(5, 'The effects changed since the preview the user said yes to (or it was never shown); '
                          'preview again and ask again; ' + NOTHING)
    agents = '%s %s %s' % (builder['harness'], builder['model'], builder['effort'])
    if not got.get('--yes'):
        print('Ready to start the fleet for spec #%d %s, through launch-fleet: 1 fleet thread (%s), whose loop checks '
              'the spec every 10 minutes and starts a builder (%s) for each of:' % (spec, where, agents, agents))
        for ticket in starts:
            print('#%d %s' % (ticket, ready[ticket]))
        print('Each pull request is reviewed by %s %s %s, from the other model family.' % (
            reviewer['harness'], reviewer['model'], reviewer['effort']))
        cost = ('it uses your Cloud Credits, unknown until measured, and model-provider charges are separate'
                if not local else 'every agent uses %s on this machine, whose model use is billed to you as it is '
                'today' % builder['harness'])
        if local:
            print('Its agents run %s with the %s permission mode you picked.' % (builder['harness'], picked))
        print('Start the fleet %s now? It can cost money: %s.' % (where, cost))
        state.value['preview'] = {'spec': spec, 'effects': digest}
        if not state.save():
            raise Exit(10, 'Could not save the preview; ' + NOTHING)
        print('Confirmation: %s' % digest)
        print("Nothing started. Ask exactly that; on the user's yes, run again with --yes --confirm %s." % digest)
        return 12
    state.value['launch'] = {'spec': spec, 'state': 'pending', 'effects': digest, 'tickets': starts}
    if not state.save():
        raise Exit(10, 'Could not save the launch record; ' + NOTHING)
    argv = ['room-cli', 'thread', 'spawn', '--parent-self', '--project', carried['project'],
            '--machine', 'local' if local else 'cloud', '--provider', builder['harness'], '--model', builder['model'],
            '--reasoning-level', builder['effort'], '--title', 'Fleet #%d: %s' % (spec, title),
            '--prompt', brief(spec, state.value['repo'])]
    try:
        result = subprocess.run(argv, capture_output=True, timeout=600, env=env)
    except (FileNotFoundError, PermissionError):
        # Review R2: room-cli never ran, so nothing was dispatched.
        state.value['launch']['state'] = 'refused'
        state.value.pop('preview', None)
        saved = state.save()
        raise Exit(5 if saved else 6, 'room-cli could not be run, so no fleet thread was dispatched; nothing started. '
                   'Fix the Cloudroom installation, then preview again and ask again.' if saved else
                   'room-cli could not be run, but that could not be saved; the start stays pending until read.')
    except (OSError, subprocess.TimeoutExpired):
        result = None
    ended = 'started' if result is not None and result.returncode == 0 else 'uncertain'
    state.value['launch']['state'] = ended
    if not state.save():
        print('Could not save the outcome; the start stays uncertain and is never retried.')
        ended = 'uncertain'
    if ended != 'started':
        print('Whether the fleet thread started is uncertain. Never start it again by hand: run this command again '
              "to read the spec's fleet record, or look for the thread in Cloudroom.")
        return 6
    print("Started spec #%d's fleet thread %s (%s), through launch-fleet; its first wake makes its loop, records "
          'itself and starts the builders.' % (spec, where, agents))
    print(teach('The fleet starting', (str(len(starts)),)))
    return 0


def record_line(spec, recorded):
    if recorded is None:
        return "The spec's fleet record could not be read right now."
    if recorded:
        return 'Spec #%d has its fleet record: the fleet thread made its loop and runs the spec.' % spec
    return 'Spec #%d has no fleet record yet: its fleet thread has not finished its first wake.' % spec


def watch(got):
    state = State(got['--state'])
    spec = int(got['--spec'])
    if state.value.get('spec') != spec:
        raise Exit(5, 'This onboarding planned no spec #%d.' % spec)
    env = repository(state.value.get('repo'))
    print(record_line(spec, fleet_recorded(spec, env)))
    return progress(spec, got['--openwiz'], env)


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
        closes = {issue['number'] for issue in pull['closingIssuesReferences']}
        assert all(type(n) is int for n in closes) and type(pull['number']) is int
        assert pull['number'] == int(got['--pr']) and isinstance(pull['url'], str) and isinstance(pull['title'], str)
        assert pull['state'] in ('OPEN', 'MERGED', 'CLOSED') and (pull['mergedAt'] is None or isinstance(pull['mergedAt'], str))
        merged = pull['state'] == 'MERGED' and isinstance(pull['mergedAt'], str)
    except (KeyError, TypeError, AssertionError):
        raise Exit(1, 'The pull request did not read back completely; no merge counted.')
    if not merged:
        raise Exit(5, '%s has not merged; a merge counts only when GitHub reads it back.' % pull['url'])
    _, members = spec_facts(spec, env)
    if not closes & members:
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
        step = ('where', "Say the teacher's opening lines, then ask where agents run and run where --agents "
                'local|cloud --yes on the answer.')
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
    elif not value.get('setup'):
        step = ('connect', '%sConnect %s with the installed tools, then run continue.' % (
            'Setup already prepared it; ' if candidate == repo else '', repo))
    elif spec and launched.get('spec') == spec and launched.get('state') in ('pending', 'uncertain'):
        step = ('launch', 'The start of spec #%d is uncertain: run launch --spec %d to read its fleet record; '
                'never start it again.' % (spec, spec))
    elif spec and launched.get('spec') == spec and launched.get('state') == 'started' and value.get('merge'):
        step = ('offer', 'Say the closing offer, as first-merge printed it.')
    elif spec and launched.get('spec') == spec and launched.get('state') == 'started':
        step = ('watch', "Run progress --spec %d, say the teacher's line for each moment, and run first-merge "
                '--pr <N> when a pull request merges.' % spec)
    elif not value.get('grill'):
        step = ('grill', "Run the short grill; on the user's yes in chat, run grill --confirmed <its comment URL>.")
    elif not choices:
        step = ('agents', 'Run choose --from-setup.')
    elif choices.get('builder_tables') != 'read':
        step = ('agents', '%s %s' % (chosen_line(choices),
                                     tables_line(choices, 'have not read back this choice yet')))
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
