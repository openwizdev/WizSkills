#!/usr/bin/env python3
"""Start, wake and stop builders through the project's chosen host driver (#1371).

  host.py which                              the host docs/agents/host.md chooses, or `host: none`
  host.py start OWNER/NAME N HARNESS MODEL   start #N's builder through that host's driver
  host.py wake OWNER/NAME N                  wake #N's run, on the host that started it
  host.py stop OWNER/NAME N                  stop #N's run, on the host that started it

Run from the project checkout. The setting is the one `Host: <name>` line of
`docs/agents/host.md` on origin's default branch, read at its current tip and
never from the checkout's copy (records v1, section 6); the driver is
`$OPENWIZ_ADAPTERS/<name>/driver` (driver v1). Each run is saved privately in
$LAUNCH_FLEET_RUNS, {"repo": "owner/name", "runs": {"N": {"host", "run"}}},
before success is printed, so a wake or stop always reaches the driver that
started the run, even after the setting changes. A start first checks that the
runs file's folder is writable. A ticket has one live run: a
new start replaces only a run its driver stopped (`"stopped": true`). Each
save re-reads the file under the lock file beside it, so starts at once keep
every run. A driver answer is taken only in exactly its v1 shape.

A refused start or wake (#1446) is tried twice more, 1 then 2 seconds later. If
the third try is refused too, the fleet's status note on #N says
`stopped (driver start failed)` and #N gets one `launch-fleet: driver start
failed` comment; a refusal while both are there writes neither again. The
comment never carries the driver's own words: it gives a fixed reason, the exit
category (`exit 1: refused`) and a pointer to an entry of the owner-only (0600)
log `driver-failures.log` beside $LAUNCH_FLEET_RUNS, which alone keeps the
driver's raw `error` and `next` (the orchestrator's decision on R3, as KN3's
driver did for its R5). The next start or wake that succeeds marks that comment
cleared and posts a `done` fleet note. The fleet note is written as the fleet
agent: $LAUNCH_FLEET_HARNESS, $LAUNCH_FLEET_MODEL and $LAUNCH_FLEET_SKILLS, as
status.py's --harness, --model and --skills; with any unset, only the fleet
note is skipped, with a warning on stderr naming them. On stdout the driver's
text appears only when it holds no credential, private id or machine path
(status.py's and post.py's rules, any URL with user info, with or without a
scheme, and any value of an environment variable named as a secret, as the
driver kit checks); otherwise it is withheld whole.
A stop or an unknown answer is never retried: a run may exist.

Exit 0: `host: <name>`, `host: none`, `started #N on <host>`, `woke ...` or
`stopped ...`; after a start or wake, a second line `unknown: ...` when #N's
failure report could not be cleared (the next success clears it). Exit 1, one
line: `stopped (driver start failed): the <host> driver refused #N's <start|wake>
3 times; next: <its next>`, ending `; unknown: the ticket's report is incomplete (<why>)`
when the note or the comment failed (each is tried; the next refusal writes what
is missing); `refused: <driver's
error>; next: <its next>` for a stop, or another refusal (nothing was started
or saved); `no run: ...` (use today's room-cli route); `unknown: ...` (a run
may exist: reconcile before any retry).
Exit 2, `host.py: <why>` on stderr: an unreadable setting, driver or runs file,
or unwritable run state; nothing was started.
The driver gets the caller's environment unchanged; this script reads no login.
"""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def sibling(name):
    spec = importlib.util.spec_from_file_location('launch_fleet_' + name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


status, post, ops = sibling('status'), sibling('post'), sibling('ops-starts')
SETTING = Path('docs/agents/host.md')
FLEET_SETTINGS = Path('docs/agents/fleet.md')
NAME = re.compile(r'[a-z0-9]+(-[a-z0-9]+)*')     # a driver's name, as driver v1's schema has it
RUN = re.compile(r'[A-Za-z0-9._:-]{1,100}')       # D2
REPO = re.compile(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+')
TICKET = re.compile(r'[1-9][0-9]{0,8}')
TIMEOUT = 300
BACKOFF = (1, 2)                                  # #1446: seconds before the second and third tries
RETRIED = ('start', 'wake')
FAILED = 'driver start failed'                    # the fleet note's stopped reason
MARK = 'launch-fleet: driver start failed'        # the failure comment's first line
CLEARED = MARK + ', cleared'
FLEET = ('LAUNCH_FLEET_HARNESS', 'LAUNCH_FLEET_MODEL', 'LAUNCH_FLEET_SKILLS')
WITHHELD = 'withheld, as it held a credential, a private id or a machine path; run the driver by hand'
SECRET_NAME = re.compile(r'TOKEN|SECRET|PASSWORD|CREDENTIAL|_KEY$|^KEY')  # the driver kit's rule
# R3: any URL with user info (`user@` or `user:password@` before its host), with or without a scheme;
# stdout only, as the ticket never carries the driver's words (the decision on R3 at 90aed73).
USERINFO = re.compile(r'(?:[a-z][a-z0-9+.-]*:)?//[^\s/?#@]*@|(?<![\w.%+-])[^\s/?#@:]+:[^\s/?#@]*@[a-z0-9]', re.I)
LOG = 'driver-failures.log'                       # owner-only, beside LAUNCH_FLEET_RUNS: the driver's own words
ROSTER_HEADER = ['Name', 'Kind', 'Driver', 'Roles', 'Writes as']
KINDS = ('harness', 'host', 'bot')
ROLES = ('orchestrator', 'builder', 'reviewer', 'helper')
SKILL_ROLES = {'build-ticket': 'builder', 'review-ticket': 'reviewer', 'launch-fleet': 'orchestrator'}
HARNESS_NAMES = {'claude-code': 'Claude Code', 'codex': 'Codex'}
ENTRY = re.compile(r'(?=.{1,40}$)[A-Za-z0-9](?:[A-Za-z0-9._-]| (?! ))*(?<=[A-Za-z0-9])')
LOGIN = re.compile(r'[A-Za-z0-9]+(-[A-Za-z0-9]+)*')
DRIVER_HARNESS = re.compile(r'[a-z0-9][a-z0-9._-]{0,59}')
DRIVER_MODEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9 ._:@+-]{0,59}')
WHICH_ROSTER = "roster: each start goes to its picked entry's driver"


class Unreadable(Exception):
    """Exit 2."""


class Outcome(Exception):
    """Exit 1 with this line."""


class Refused(Outcome):
    """The driver refused, in v1's shape. Its raw words go only to the owner-only driver log; the line is public()."""

    def __init__(self, error, next_):
        super().__init__('refused: %s; next: %s' % (public(error), public(next_)))
        self.error, self.next = error, next_


def public(text):
    """The driver's own text, or WITHHELD when any part of it could be private (#1446)."""
    secrets = [v for k, v in os.environ.items() if SECRET_NAME.search(k.upper()) and len(v) >= 8]
    if any(p.search(text) for _, p in status.PRIVATE) or post.PRIVATE.search(text) or USERINFO.search(text) \
            or any(v in text for v in secrets):
        return WITHHELD
    return text


def git(*args):
    try:
        r = subprocess.run(['git', *args], capture_output=True, text=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Unreadable('git %s did not run: %s' % (args[0], type(e).__name__))
    return r.returncode, r.stdout


def setting_text(setting=SETTING):
    """The setting file on origin's default branch at its current tip, or None when that tip has no file.

    Never the checkout's copy: a fleet's checkout can be older than the default branch (records v1, section 6)."""
    code, out = git('ls-remote', '--symref', 'origin', 'HEAD')
    branch = re.search(r'(?m)^ref: refs/heads/(\S+)\tHEAD$', out) if code == 0 else None
    tip = re.search(r'(?m)^([0-9a-f]{40})\tHEAD$', out) if code == 0 else None
    if not (branch and tip):
        raise Unreadable("origin's default branch is unreadable: run from the project checkout, with origin reachable")
    code, _ = git('fetch', '--quiet', '--no-tags', '--no-write-fetch-head', 'origin', 'refs/heads/' + branch[1])
    if code != 0 or git('cat-file', '-e', tip[1] + '^{commit}')[0] != 0:
        raise Unreadable("origin's default branch %s could not be fetched at %s" % (branch[1], tip[1]))
    if git('cat-file', '-e', '%s:%s' % (tip[1], setting))[0] != 0:
        return None
    code, text = git('show', '%s:%s' % (tip[1], setting))
    if code != 0:
        raise Unreadable('%s is unreadable on %s' % (setting, branch[1]))
    return text


def chosen():
    """The default branch's setting's host name, or None when the project has no setting file."""
    text = setting_text()
    if text is None:
        return None
    lines = re.findall(r'(?m)^Host:[ \t]*(.*?)[ \t]*$', text)
    if len(lines) != 1 or not NAME.fullmatch(lines[0]) or len(lines[0]) > 40:
        raise Unreadable('%s needs exactly one `Host: <name>` line, the name in lowercase letters, digits and '
                         'hyphens' % SETTING)
    return lines[0]


def driver(host):
    adapters = os.environ.get('OPENWIZ_ADAPTERS', '')
    if not adapters or not os.path.isabs(adapters):
        raise Unreadable('set OPENWIZ_ADAPTERS to the absolute path of an OpenWiz adapters/ folder')
    path = Path(adapters, host, 'driver')
    if not (path.is_file() and os.access(path, os.X_OK)):
        raise Unreadable('no driver for host %s: %s is not an executable file' % (host, path))
    return path


def roster_cells(line):
    line = line.strip()
    if len(line) < 2 or line[0] != '|' or line[-1] != '|':
        return None
    return [c.strip() for c in line[1:-1].split('|')]


def names_roster(line):
    line = line.strip()
    level = len(line) - len(line.lstrip('#'))
    rest = line[level:]
    word = rest.strip().rstrip('#').strip()
    return 1 <= level <= 6 and (rest == '' or rest[0] in ' \t') and word.isascii() and word.lower() == 'roster'


def roster(text):
    lines = [line.rstrip() for line in text.split('\n')]
    if lines and lines[-1] == '':
        lines.pop()

    def underlined(i):
        below = lines[i + 1].strip() if i + 1 < len(lines) else ''
        word = lines[i].strip()
        return word.isascii() and word.lower() == 'roster' and below != '' and set(below) in ({'='}, {'-'})
    odd = next((line for i, line in enumerate(lines) if (line != '## Roster' and names_roster(line)) or underlined(i)),
               None)
    if odd is not None:
        raise Outcome('Roster refused: the Roster heading must be exactly ## Roster: %s' % odd)
    at = [i for i, line in enumerate(lines) if line == '## Roster']
    if len(at) > 1:
        raise Outcome('Roster refused: more than one ## Roster heading')
    if not at:
        return None
    section = []
    for line in lines[at[0] + 1:]:
        if line.startswith('# ') or line.startswith('## '):
            break
        section.append(line)
    first = next((i for i, line in enumerate(section) if line.lstrip().startswith('|')), None)
    if first is None:
        raise Outcome('Roster refused: the Roster section has no table')
    table = []
    for line in section[first:]:
        if not line.lstrip().startswith('|'):
            break
        table.append(line)
    rule = roster_cells(table[1]) if len(table) > 1 else None
    if roster_cells(table[0]) != ROSTER_HEADER or not rule or len(rule) != 5 or not all(
            len(c) >= 3 and set(c) == {'-'} for c in rule):
        raise Outcome('Roster refused: the header is not Name, Kind, Driver, Roles, Writes as')
    if len(table) == 2:
        raise Outcome('Roster refused: the table has no entries')
    entries = []
    for n, line in enumerate(table[2:], 1):
        row = roster_cells(line) or []
        if len(row) != 5:
            raise Outcome('Roster refused: row %d has %d cells, not 5' % (n, len(row)))
        name, kind, host, roles, writes = row
        if not ENTRY.fullmatch(name):
            raise Outcome('Roster refused: row %d: bad name: %s' % (n, name))
        if any(e['name'].lower() == name.lower() for e in entries):
            raise Outcome('Roster refused: row %d: %s is already an entry' % (n, name))
        at = 'Roster refused: row %d (%s)' % (n, name)
        if kind not in KINDS:
            raise Outcome('%s: unknown kind: %s' % (at, kind))
        if not (len(host) <= 40 and NAME.fullmatch(host)):
            raise Outcome('%s: bad driver: %s' % (at, host))
        if roles == '':
            raise Outcome('%s: no roles' % at)
        taken = []
        for role in (r.strip() for r in roles.split(',')):
            if role not in ROLES:
                raise Outcome('%s: unknown role: %s' % (at, role))
            if role in taken:
                raise Outcome('%s: role listed twice: %s' % (at, role))
            taken.append(role)
        person = writes[:-len("'s App")] if writes.endswith("'s App") else ''
        if not (len(person) <= 39 and LOGIN.fullmatch(person)):
            raise Outcome("%s: writes as %s, not <person>'s App" % (at, writes))
        if entries and entries[0]['writes_as'] != writes:
            raise Outcome("%s: writes as %s, not %s like row 1" % (at, writes, entries[0]['writes_as']))
        label = '%s via %s' % (name, person)
        if len(label) > 60:
            raise Outcome('%s: %s is longer than 60 characters' % (at, label))
        entries.append({'name': name, 'kind': kind, 'driver': host, 'roles': taken, 'writes_as': writes,
                        'label': label})
    return entries


def note_model(name):
    return '%s default effort' % (name[:42].rstrip() + '...' if len(name) > 45 else name)


def pick(entries, repo, ticket, role, choice):
    if choice is None:
        return {'pick': None, 'waits': 'models', 'look': None}
    provider, model = choice['provider'], choice['model']
    harness = 'claude' if provider == 'claude-code' else provider
    if not (DRIVER_HARNESS.fullmatch(harness) and DRIVER_MODEL.fullmatch(model)):
        return {'pick': None, 'waits': 'driver',
                'look': "roster: driver v1 can't start %s %s; choose another model in the Models table" % (harness, model)}
    named = HARNESS_NAMES.get(provider, provider)
    entry = next((e for e in entries if role in e['roles'] and (e['kind'] != 'harness' or e['name'] == named)), None)
    if entry is None:
        return {'pick': None, 'waits': 'roster', 'look': 'roster: no entry may take the %s role with %s' % (role, named)}
    person = entry['writes_as'][:-len("'s App")]
    return {'pick': {'name': entry['name'], 'kind': entry['kind'], 'driver': entry['driver'],
                     'start': {'harness': harness, 'model': model},
                     'note': {'harness': entry['label'], 'model': note_model(choice['model_name'])},
                     'writes_as': entry['writes_as'],
                     'token': {'service': person, 'requester': '%s-%s' % (role, ticket), 'repositories': [repo]}},
            'waits': None, 'look': None}


def model_name(text, provider, model):
    for line in ops._section(text, 'Models') or []:
        row = roster_cells(line)
        if row and len(row) == 5:
            try:
                flags = ops._flags(row[4])
            except ValueError:
                continue
            if flags[:2] == [provider, model]:
                return row[2]
    return None


def roster_start(text, repo, n, harness, model, skill):
    entries = roster(text)
    role = SKILL_ROLES.get(skill)
    if role is None:
        raise Outcome('refused: the Roster gives no role to the %s skill' % skill)
    provider = 'claude-code' if harness == 'claude' else harness
    name = model_name(text, provider, model)
    chosen = pick(entries, repo, int(n), role, {'provider': provider, 'model': model, 'model_name': name or model})
    if chosen['look']:
        raise Outcome(chosen['look'])
    if name is None:
        raise Outcome('refused: no Models table row starts %s %s' % (provider, model))
    return role, chosen['pick']


ANSWERS = {'start': {'run'}, 'wake': {'run', 'woke'}, 'stop': {'run', 'stopped'}}


def strict(text):
    """JSON with each key once; None for anything else."""
    def once(pairs):
        if len({k for k, _ in pairs}) != len(pairs):
            raise ValueError('repeated key')
        return dict(pairs)
    try:
        return json.loads(text, object_pairs_hook=once)
    except ValueError:
        return None


def token_step(repo, n, requester):
    if not configured():
        return
    try:
        r = subprocess.run([sys.executable, '-I', str(HERE / 'github-app/agent-token.py'), 'start', '--requester',
                            requester, '--repository', repo], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        print('host.py: the agent helper did not run (%s); #%s starts as the owner\'s login' % (type(e).__name__, n),
              file=sys.stderr)
        return
    if r.stderr:
        sys.stderr.write(r.stderr)


LEGACY_KEY = 'OPENWIZ_GITHUB_APP_KEY'
SHIM = """#!/bin/sh
set -f
rest=
IFS=:
for part in $PATH; do [ "$part" = {folder} ] || rest=${{rest:+$rest:}}$part; done
unset IFS
PATH=$rest
export PATH
command -v {name} > /dev/null || {{ echo "openwiz: no {name} on PATH" >&2; exit 127; }}
unset {key}
exec {python} -I {helper} run --requester {requester} --repository {repo} -- {name} "$@"
"""
DRIVER_ENV = None


def configured():
    return bool(os.environ.get('OPENWIZ_TOKEN_SERVICE'))


def builder_env(repo, n, requester):
    folder = runs_path().parent / 'agent-token-bin' / ('%s-%s' % (repo.replace('/', '--'), n))
    try:
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(folder.parent, 0o700)
        os.chmod(folder, 0o700)
        for name in ('gh', 'git'):
            fd, tmp = tempfile.mkstemp(dir=folder, prefix='.shim-')
            with os.fdopen(fd, 'w') as f:
                f.write(SHIM.format(requester=requester, name=name, folder=shlex.quote(str(folder)), key=LEGACY_KEY, repo=repo,
                                    python=shlex.quote(sys.executable),
                                    helper=shlex.quote(str(HERE / 'github-app/agent-token.py'))))
            os.chmod(tmp, 0o700)
            os.replace(tmp, folder / name)
    except OSError as e:
        raise Unreadable("can't write #%s's gh and git shims in %s (%s)" % (n, folder, type(e).__name__))
    env = dict(os.environ)
    env['PATH'] = '%s%s%s' % (folder, os.pathsep, env.get('PATH', os.defpath))
    return env


def call(host, command, given):
    """The driver's run id, or Outcome on a refusal or any answer that isn't exactly v1's."""
    try:
        r = subprocess.run([str(driver(host)), command], input=json.dumps(given), capture_output=True, text=True,
                           timeout=TIMEOUT, env=DRIVER_ENV)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Outcome('unknown: the %s driver did not answer %s (%s); a run may exist, so reconcile before any '
                      'retry' % (host, command, type(e).__name__))
    answer = strict(r.stdout)
    if r.returncode == 1 and isinstance(answer, dict) and set(answer) == {'error', 'next'} \
            and all(isinstance(v, str) and 0 < len(v) <= 300 and '\n' not in v for v in answer.values()):
        raise Refused(answer['error'], answer['next'])
    if r.returncode != 0 or not isinstance(answer, dict) or set(answer) != ANSWERS[command] \
            or not isinstance(answer['run'], str) or not RUN.fullmatch(answer['run']) \
            or any(answer[k] is not True for k in ANSWERS[command] - {'run'}) \
            or (command != 'start' and answer['run'] != given['run']):
        raise Outcome('unknown: the %s driver answered no run; a run may exist, so reconcile before any retry' % host)
    return answer['run']


def tried(host, command, given):
    """call(), with a refused start or wake tried twice more after BACKOFF (#1446)."""
    for wait in BACKOFF if command in RETRIED else ():
        try:
            return call(host, command, given)
        except Refused:
            time.sleep(wait)
    return call(host, command, given)


def fleet():
    """The fleet agent's harness, model and skills for its status note, or None, with a warning on stderr, when
    any is unset: then only the fleet note is skipped (the J87 planner's ruling; requiring them waits for 0.1.1)."""
    values = [os.environ.get(name, '') for name in FLEET]
    missing = [name for name, value in zip(FLEET, values) if not value]
    if missing:
        print('host.py: warning: %s unset, so the fleet status note was not written' % ', '.join(missing),
              file=sys.stderr)
        return None
    return values


def reports(repo, n):
    """#N's newest record-author fleet note is stopped by a failed start, and its uncleared failure comments."""
    authors = post.authors(repo)
    items = post.thread(repo, int(n))
    if items is None:
        raise post.Stop('#%s could not be read' % n)
    ours = [c for c in items if post.ours(c, authors) and isinstance(c.get('body'), str)]
    notes = [f for f in (status.parse(c['body']) for c in sorted(ours, key=lambda c: c.get('id', 0)))
             if f and f['agent'] == 'fleet']
    stopped = bool(notes) and notes[-1]['state'] == 'stopped (%s)' % FAILED
    return stopped, [c for c in ours if c['body'].split('\n', 1)[0] == MARK]


def note(repo, n, state, step):
    identity = fleet()
    if identity is None:
        return
    harness, model, skills = identity
    why = ['--why', FAILED] if state == 'stopped' else []
    r = subprocess.run([sys.executable, '-I', str(HERE / 'status.py'), 'write', '--repo', repo, '--ticket', n,
                        '--agent', 'fleet', '--state', state, *why, '--harness', harness, '--model', model,
                        '--skills', skills, '--step', step], capture_output=True, text=True, timeout=TIMEOUT)
    if r.returncode != 0:
        raise post.Stop('the fleet note was not written: %s' % (r.stderr.strip() or 'status.py exit %d' % r.returncode))


def logged(repo, n, host, command, refusal):
    """Append the driver's raw refusal to the owner-only log beside the runs file; its entry's time, or None."""
    stamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    entry = {'time': stamp, 'repo': repo, 'ticket': int(n), 'host': host, 'command': command, 'exit': 1,
             'error': refusal.error, 'next': refusal.next}
    try:
        fd = os.open(str(runs_path().with_name(LOG)), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, (json.dumps(entry, sort_keys=True) + '\n').encode())
        finally:
            os.close(fd)
    except (OSError, Unreadable):
        return None
    return stamp


def report(repo, n, host, command, entry):
    """After the third refusal: the fleet note and one comment on #N, each only when #N lacks it.

    The comment never carries the driver's words (the orchestrator's decision on R3 at 90aed73): a fixed
    reason, the exit category and a pointer to the owner-only log's entry. Each write is tried even when the
    other failed (R1 of the review at 1f9c7f6); post.Stop names every failure."""
    stopped, comments = reports(repo, n)
    failed = [] if entry else ['the driver log %s could not be written' % LOG]
    if not stopped:
        try:
            note(repo, n, 'stopped', "the %s driver refused this builder's %s 3 times; the reason is in a comment "
                                     "here" % (host, command))
        except Exception as e:
            failed.append(why(e))
    if not comments:
        where = ("the fleet's owner can read them in the private driver log, `%s` beside `LAUNCH_FLEET_RUNS`, entry "
                 "%s for #%s." % (LOG, entry, n)) if entry else \
            "they could not be saved to the fleet owner's private driver log, so run the driver by hand to read them."
        try:
            post.comment(repo, int(n), "%s\n\nThe %s driver refused to %s this ticket's builder 3 times (exit 1: "
                                       "refused). Its own words are kept off this public ticket: %s"
                                       % (MARK, host, command, where))
        except Exception as e:
            failed.append(why(e))
    if failed:
        raise post.Stop('; '.join(failed))


def clear(repo, n, host, done):
    """After a success: mark #N's failure comments cleared and follow a stopped fleet note with a done one.

    Each write is tried even when another failed, as report()'s are; post.Stop names every failure."""
    stopped, comments = reports(repo, n)
    failed = []
    for c in comments:
        try:
            post.edit(repo, c['id'], CLEARED + c['body'][len(MARK):] + '\n\nCleared: the %s driver %s it later.'
                      % (host, done))
        except Exception as e:
            failed.append(why(e))
    if stopped:
        try:
            note(repo, n, 'done', 'the %s driver %s this builder on a later try' % (host, done))
        except Exception as e:
            failed.append(why(e))
    if failed:
        raise post.Stop('; '.join(failed))


def attempt(repo, n, host, command, given):
    """tried(); after its last refusal, the Outcome line, with #N told (#1446). The driver's run id."""
    try:
        return tried(host, command, given)
    except Refused as refusal:
        line = "stopped (%s): the %s driver refused #%s's %s 3 times; next: %s" % (FAILED, host, n, command,
                                                                                public(refusal.next))
        try:
            report(repo, n, host, command, logged(repo, n, host, command, refusal))
        except Exception as e:  # nothing started: the next refusal writes what is missing
            line += "; unknown: the ticket's report is incomplete (%s)" % why(e)
        raise Outcome(line)


def cleared(repo, n, host, done):
    """clear() after a success is saved: an `unknown: ...` line when it could not, or None."""
    try:
        clear(repo, n, host, done)
    except Exception as e:  # the run is saved: any failure here only delays the clearing
        return 'unknown: the failure report on #%s was not cleared (%s); the next success clears it' % (n, why(e))
    return None


def why(e):
    """A GitHub step's failure, for a line: its reason without post.py's outcome word, or only the error's kind."""
    return re.sub(r'^(?:unknown|refused): ', '', str(e)) if isinstance(e, post.Stop) else type(e).__name__


def runs_path():
    path = os.environ.get('LAUNCH_FLEET_RUNS', '')
    if not path or not os.path.isabs(path):
        raise Unreadable('set LAUNCH_FLEET_RUNS to an absolute private JSON file, outside the checkout')
    return Path(path)


def load(repo):
    path = runs_path()
    try:
        value = strict(path.read_text())
    except FileNotFoundError:
        return {'repo': repo, 'runs': {}}
    except (OSError, UnicodeDecodeError) as e:
        raise Unreadable('%s is unreadable: %s' % (path, e))
    if not (isinstance(value, dict) and set(value) == {'repo', 'runs'} and value['repo'] == repo
            and isinstance(value['runs'], dict)
            and all(TICKET.fullmatch(k) and isinstance(v, dict)
                    and {'host', 'run'} <= set(v) <= {'host', 'role', 'run', 'stopped'} and v.get('stopped', True) is True
                    and v.get('role', 'builder') in ROLES
                    and isinstance(v['host'], str) and NAME.fullmatch(v['host'])
                    and isinstance(v['run'], str) and RUN.fullmatch(v['run']) for k, v in value['runs'].items())):
        raise Unreadable('%s is not a runs file for %s' % (path, repo))
    return value


def ready(repo):
    """Before a driver runs: the runs file's folder is writable and its lock opens, so a start can be saved."""
    path = runs_path()
    if not (path.parent.is_dir() and os.access(path.parent, os.W_OK | os.X_OK)):
        raise Unreadable('%s is not a writable folder: create it, owner-only, before a start' % path.parent)
    try:
        with open(str(path) + '.lock', 'a'):
            pass
    except OSError as e:
        raise Unreadable('the lock beside %s does not open: %s' % (path, e))
    load(repo)


def record(repo, change):
    """Under the runs file's lock, re-read it, apply change(runs) and save it owner-only, read back.

    False when the save or its read-back failed. Starts at once each keep their run."""
    path = runs_path()
    try:
        with open(str(path) + '.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            value = load(repo)
            change(value['runs'])
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.runs-')
            with os.fdopen(fd, 'w') as f:
                json.dump(value, f, sort_keys=True)
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
            return load(repo) == value
    except (OSError, Unreadable):
        return False


def main(argv):
    global DRIVER_ENV
    if configured():
        os.environ.pop(LEGACY_KEY, None)
    kind = argv[0] if argv else ''
    if kind == 'which' and len(argv) == 1:
        text = setting_text(FLEET_SETTINGS)
        print(WHICH_ROSTER if text is not None and roster(text) is not None else 'host: %s' % (chosen() or 'none'))
        return 0
    shapes = {'start': (5, 6), 'wake': (3,), 'stop': (3,)}
    skill = argv[5] if kind == 'start' and len(argv) == 6 else 'build-ticket'
    if (len(argv) not in shapes.get(kind, ()) or not REPO.fullmatch(argv[1]) or not TICKET.fullmatch(argv[2])
            or not NAME.fullmatch(skill) or len(skill) > 60):
        raise Unreadable('usage: which | start OWNER/NAME N HARNESS MODEL [SKILL] | wake OWNER/NAME N | '
                         'stop OWNER/NAME N')
    repo, n = argv[1], argv[2]
    run = load(repo)['runs'].get(n)
    role = picked = None
    if kind == 'start':
        text = setting_text(FLEET_SETTINGS)
        if text is not None and roster(text) is not None:
            role, picked = roster_start(text, repo, n, argv[3], argv[4], skill)
    elif run:
        role = run.get('role')
    requester = '%s-%s' % (role or 'builder', n)
    if configured():
        DRIVER_ENV = builder_env(repo, n, requester)
    live = 'refused: #%s already has a run on %s; wake or stop it instead'
    if kind == 'start':
        host = picked['driver'] if picked else chosen()
        if host is None:
            raise Outcome('refused: no host is chosen in %s' % SETTING)
        driver(host)
        ready(repo)
        if run and not run.get('stopped'):
            raise Outcome(live % (n, run['host']))
        token_step(repo, n, requester)
        new = attempt(repo, n, host, 'start', {'repository': repo, 'ticket': int(n), 'skill': skill,
                                                'harness': argv[3], 'model': argv[4]})

        def add(runs):
            if runs.get(n) != run:  # another start saved a run for #N meanwhile
                raise Outcome('unknown: #%s got a second run, %s on %s; stop one of them' % (n, new, host))
            runs[n] = dict({'host': host, 'run': new}, **({'role': role} if picked else {}))
        if not record(repo, add):
            raise Outcome('unknown: #%s started on %s but its run was not saved; save run %s on host %s for #%s '
                          'privately before anything else' % (n, host, new, host, n))
        print('started #%s on %s%s' % (n, host, ' as %s, %s' % (picked['note']['harness'], picked['note']['model'])
                                          if picked else ''))
        unclear = cleared(repo, n, host, 'started')
        if unclear:
            print(unclear)
        return 0
    if not run:
        raise Outcome('no run: #%s was not started through a driver' % n)
    unclear = None
    if kind == 'wake':
        token_step(repo, n, requester)
        attempt(repo, n, run['host'], kind, {'run': run['run']})
        unclear = cleared(repo, n, run['host'], 'woke')
    else:
        call(run['host'], kind, {'run': run['run']})
    if kind == 'stop' and not run.get('stopped'):
        def stopped(runs):
            if runs.get(n, {}).get('run') == run['run']:
                runs[n]['stopped'] = True
        if not record(repo, stopped):
            raise Outcome('unknown: #%s stopped on %s but that was not saved' % (n, run['host']))
    print('%s #%s on %s' % ({'wake': 'woke', 'stop': 'stopped'}[kind], n, run['host']))
    if unclear:
        print(unclear)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except Outcome as e:
        print(e)
        sys.exit(1)
    except Unreadable as e:
        print('host.py: %s' % e, file=sys.stderr)
        sys.exit(2)
