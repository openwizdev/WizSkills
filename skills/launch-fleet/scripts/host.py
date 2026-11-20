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

Exit 0: `host: <name>`, `host: none`, `started #N on <host>`, `woke ...` or
`stopped ...`. Exit 1, one line: `refused: <driver's error>; next: <its next>`
or another refusal (nothing was started or saved); `no run: ...` (use today's
room-cli route); `unknown: ...` (a run may exist: reconcile before any retry).
Exit 2, `host.py: <why>` on stderr: an unreadable setting, driver or runs file, or
unwritable run state; nothing was started.
The driver gets the caller's environment unchanged; this script reads no login.
"""
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
SETTING = Path('docs/agents/host.md')
NAME = re.compile(r'[a-z0-9]+(-[a-z0-9]+)*')     # a driver's name, as driver v1's schema has it
RUN = re.compile(r'[A-Za-z0-9._:-]{1,100}')       # D2
REPO = re.compile(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+')
TICKET = re.compile(r'[1-9][0-9]{0,8}')
TIMEOUT = 300


class Unreadable(Exception):
    """Exit 2."""


class Outcome(Exception):
    """Exit 1 with this line."""


def git(*args):
    try:
        r = subprocess.run(['git', *args], capture_output=True, text=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Unreadable('git %s did not run: %s' % (args[0], type(e).__name__))
    return r.returncode, r.stdout


def setting_text():
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
    if git('cat-file', '-e', '%s:%s' % (tip[1], SETTING))[0] != 0:
        return None
    code, text = git('show', '%s:%s' % (tip[1], SETTING))
    if code != 0:
        raise Unreadable('%s is unreadable on %s' % (SETTING, branch[1]))
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


def call(host, command, given):
    """The driver's run id, or Outcome on a refusal or any answer that isn't exactly v1's."""
    try:
        r = subprocess.run([str(driver(host)), command], input=json.dumps(given), capture_output=True, text=True,
                           timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Outcome('unknown: the %s driver did not answer %s (%s); a run may exist, so reconcile before any '
                      'retry' % (host, command, type(e).__name__))
    answer = strict(r.stdout)
    if r.returncode == 1 and isinstance(answer, dict) and set(answer) == {'error', 'next'} \
            and all(isinstance(v, str) and 0 < len(v) <= 300 and '\n' not in v for v in answer.values()):
        raise Outcome('refused: %s; next: %s' % (answer['error'], answer['next']))
    if r.returncode != 0 or not isinstance(answer, dict) or set(answer) != ANSWERS[command] \
            or not isinstance(answer['run'], str) or not RUN.fullmatch(answer['run']) \
            or any(answer[k] is not True for k in ANSWERS[command] - {'run'}) \
            or (command != 'start' and answer['run'] != given['run']):
        raise Outcome('unknown: the %s driver answered no run; a run may exist, so reconcile before any retry' % host)
    return answer['run']


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
                    and set(v) in ({'host', 'run'}, {'host', 'run', 'stopped'}) and v.get('stopped', True) is True
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
    kind = argv[0] if argv else ''
    if kind == 'which' and len(argv) == 1:
        print('host: %s' % (chosen() or 'none'))
        return 0
    shapes = {'start': 5, 'wake': 3, 'stop': 3}
    if shapes.get(kind) != len(argv) or not REPO.fullmatch(argv[1]) or not TICKET.fullmatch(argv[2]):
        raise Unreadable('usage: which | start OWNER/NAME N HARNESS MODEL | wake OWNER/NAME N | stop OWNER/NAME N')
    repo, n = argv[1], argv[2]
    run = load(repo)['runs'].get(n)
    live = 'refused: #%s already has a run on %s; wake or stop it instead'
    if kind == 'start':
        host = chosen()
        if host is None:
            raise Outcome('refused: no host is chosen in %s' % SETTING)
        driver(host)
        ready(repo)
        if run and not run.get('stopped'):
            raise Outcome(live % (n, run['host']))
        new = call(host, 'start', {'repository': repo, 'ticket': int(n), 'skill': 'build-ticket',
                                   'harness': argv[3], 'model': argv[4]})

        def add(runs):
            if runs.get(n) != run:  # another start saved a run for #N meanwhile
                raise Outcome('unknown: #%s got a second run, %s on %s; stop one of them' % (n, new, host))
            runs[n] = {'host': host, 'run': new}
        if not record(repo, add):
            raise Outcome('unknown: #%s started on %s but its run was not saved; save run %s on host %s for #%s '
                          'privately before anything else' % (n, host, new, host, n))
        print('started #%s on %s' % (n, host))
        return 0
    if not run:
        raise Outcome('no run: #%s was not started through a driver' % n)
    call(run['host'], kind, {'run': run['run']})
    if kind == 'stop' and not run.get('stopped'):
        def stopped(runs):
            if runs.get(n, {}).get('run') == run['run']:
                runs[n]['stopped'] = True
        if not record(repo, stopped):
            raise Outcome('unknown: #%s stopped on %s but that was not saved' % (n, run['host']))
    print('%s #%s on %s' % ({'wake': 'woke', 'stop': 'stopped'}[kind], n, run['host']))
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
