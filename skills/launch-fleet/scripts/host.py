#!/usr/bin/env python3
"""Start, wake and stop builders through the project's chosen host driver (#1371).

  host.py which                              the host docs/agents/host.md chooses, or `host: none`
  host.py start OWNER/NAME N HARNESS MODEL   start #N's builder through that host's driver
  host.py wake OWNER/NAME N                  wake #N's run, on the host that started it
  host.py stop OWNER/NAME N                  stop #N's run, on the host that started it

Run from the project checkout. The setting is the one `Host: <name>` line of
`docs/agents/host.md` (records v1, section 6); the driver is
`$OPENWIZ_ADAPTERS/<name>/driver` (driver v1). Each run is saved privately in
$LAUNCH_FLEET_RUNS, {"repo": "owner/name", "runs": {"N": {"host", "run"}}},
before success is printed, so a wake or stop always reaches the driver that
started the run, even after the setting changes. A ticket has one live run: a
new start replaces only a run its driver stopped (`"stopped": true`).

Exit 0: `host: <name>`, `host: none`, `started #N on <host>`, `woke ...` or
`stopped ...`. Exit 1, one line: `refused: <driver's error>; next: <its next>`
or another refusal (nothing was started or saved); `no run: ...` (use today's
room-cli route); `unknown: ...` (a run may exist: reconcile before any retry).
Exit 2, `host.py: <why>` on stderr: an unreadable setting, driver or runs file.
The driver gets the caller's environment unchanged; this script reads no login.
"""
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


def chosen():
    """The setting's host name, or None when the project has no setting file."""
    if not SETTING.exists():
        return None
    try:
        lines = re.findall(r'(?m)^Host:[ \t]*(.*?)[ \t]*$', SETTING.read_text())
    except (OSError, UnicodeDecodeError) as e:
        raise Unreadable('%s is unreadable: %s' % (SETTING, e))
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


def call(host, command, given):
    """The driver's answer object, or Outcome on a refusal or an unreadable answer."""
    try:
        r = subprocess.run([str(driver(host)), command], input=json.dumps(given), capture_output=True, text=True,
                           timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Outcome('unknown: the %s driver did not answer %s (%s); a run may exist, so reconcile before any '
                      'retry' % (host, command, type(e).__name__))
    try:
        answer = json.loads(r.stdout)
    except ValueError:
        answer = None
    if r.returncode == 1 and isinstance(answer, dict) and set(answer) == {'error', 'next'} \
            and all(isinstance(v, str) and '\n' not in v for v in answer.values()):
        raise Outcome('refused: %s; next: %s' % (answer['error'], answer['next']))
    if r.returncode != 0 or not isinstance(answer, dict) or not isinstance(answer.get('run'), str) \
            or not RUN.fullmatch(answer['run']):
        raise Outcome('unknown: the %s driver answered no run; a run may exist, so reconcile before any retry' % host)
    return answer


def load(repo):
    path = os.environ.get('LAUNCH_FLEET_RUNS', '')
    if not path or not os.path.isabs(path):
        raise Unreadable('set LAUNCH_FLEET_RUNS to an absolute private JSON file, outside the checkout')
    try:
        value = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return Path(path), {'repo': repo, 'runs': {}}
    except (OSError, ValueError) as e:
        raise Unreadable('%s is unreadable: %s' % (path, e))
    if not (isinstance(value, dict) and set(value) == {'repo', 'runs'} and value['repo'] == repo
            and isinstance(value['runs'], dict)
            and all(TICKET.fullmatch(k) and isinstance(v, dict)
                    and set(v) in ({'host', 'run'}, {'host', 'run', 'stopped'}) and v.get('stopped', True) is True
                    and isinstance(v['host'], str) and NAME.fullmatch(v['host'])
                    and isinstance(v['run'], str) and RUN.fullmatch(v['run']) for k, v in value['runs'].items())):
        raise Unreadable('%s is not a runs file for %s' % (path, repo))
    return Path(path), value


def save(path, value):
    """Write the runs file owner-only, atomically, and read it back."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.runs-')
    with os.fdopen(fd, 'w') as f:
        json.dump(value, f, sort_keys=True)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return json.loads(path.read_text()) == value


def main(argv):
    kind = argv[0] if argv else ''
    if kind == 'which' and len(argv) == 1:
        print('host: %s' % (chosen() or 'none'))
        return 0
    shapes = {'start': 5, 'wake': 3, 'stop': 3}
    if shapes.get(kind) != len(argv) or not REPO.fullmatch(argv[1]) or not TICKET.fullmatch(argv[2]):
        raise Unreadable('usage: which | start OWNER/NAME N HARNESS MODEL | wake OWNER/NAME N | stop OWNER/NAME N')
    repo, n = argv[1], argv[2]
    path, value = load(repo)
    run = value['runs'].get(n)
    if kind == 'start':
        host = chosen()
        if host is None:
            raise Outcome('refused: no host is chosen in %s' % SETTING)
        driver(host)
        if run and not run.get('stopped'):
            raise Outcome('refused: #%s already has a run on %s; wake or stop it instead' % (n, run['host']))
        answer = call(host, 'start', {'repository': repo, 'ticket': int(n), 'skill': 'build-ticket',
                                      'harness': argv[3], 'model': argv[4]})
        value['runs'][n] = {'host': host, 'run': answer['run']}
        try:
            saved = save(path, value)
        except (OSError, ValueError):
            saved = False
        if not saved:
            raise Outcome('unknown: #%s started on %s but its run was not saved; save run %s for #%s privately '
                          'before anything else' % (n, host, answer['run'], n))
        print('started #%s on %s' % (n, host))
        return 0
    if not run:
        raise Outcome('no run: #%s was not started through a driver' % n)
    answer = call(run['host'], kind, {'run': run['run']})
    if answer.get('run') != run['run']:
        raise Outcome('unknown: the %s driver answered another run' % run['host'])
    if kind == 'stop' and not run.get('stopped'):
        run['stopped'] = True
        try:
            saved = save(path, value)
        except (OSError, ValueError):
            saved = False
        if not saved:
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
