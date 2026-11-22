#!/usr/bin/env python3
import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('launch_fleet_host', HERE / 'host.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)
TIMEOUT = host.TIMEOUT + 30


def code_and_last_line(name, *args):
    try:
        r = subprocess.run([sys.executable, '-I', str(HERE / name), *args], capture_output=True, text=True,
                           timeout=TIMEOUT, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, '%s did not answer (%s)' % (name, type(e).__name__)
    lines = (r.stdout + r.stderr).strip().splitlines()
    return r.returncode, lines[-1] if lines else '%s exit %d' % (name, r.returncode)


def pause_heartbeat(repo, spec_n, dry_run):
    code, line = code_and_last_line('heartbeat.py', 'status', repo, spec_n)
    if code == 0 and line == 'heartbeat: not installed':
        return line, True
    if code != 0:
        return 'heartbeat: not paused (%s)' % line, False
    if dry_run:
        return 'heartbeat: would pause', True
    code, line = code_and_last_line('heartbeat.py', 'pause', repo, spec_n)
    return ('heartbeat: paused', True) if code == 0 else ('heartbeat: not paused (%s)' % line, False)


def stop_run(repo, n, run):
    try:
        host.driver(run['host'])
    except host.Unreadable:
        return 'not stopped: the driver is missing', False
    code, line = code_and_last_line('host.py', 'stop', repo, n)
    if code == 0:
        return 'stopped', True
    kind = 'refused' if code == 1 and line.startswith('refused: ') else 'failed'
    return 'not stopped: the driver %s stop (%s)' % (kind, line), False


def main(argv):
    parser = argparse.ArgumentParser(
        description="Pause spec SPEC's heartbeat, then stop every live run in host.py's runs file "
                    "($LAUNCH_FLEET_RUNS) through its own driver's stop, one at a time.",
        epilog='Each run prints `#N on <driver>: <result>`. Exit 0: all stopped and the heartbeat paused or not '
               'installed. Exit 1: a driver missing, refusing or failing stop, or a heartbeat that did not pause; '
               'the other runs are still stopped. Exit 2: bad usage or an unreadable runs file; nothing done.')
    parser.add_argument('repo', metavar='OWNER/NAME')
    parser.add_argument('spec', metavar='SPEC')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    if not host.REPO.fullmatch(args.repo) or not host.TICKET.fullmatch(args.spec):
        parser.error('expected OWNER/NAME and a positive spec number')
    runs = host.load(args.repo)['runs']
    live = sorted(((n, r) for n, r in runs.items() if not r.get('stopped')), key=lambda item: int(item[0]))
    line, ok = pause_heartbeat(args.repo, args.spec, args.dry_run)
    print(line, flush=True)
    stopped = failed = 0
    for n, run in live:
        if args.dry_run:
            result = 'would stop'
        else:
            result, done = stop_run(args.repo, n, run)
            stopped, failed = stopped + done, failed + (not done)
        print('#%s on %s: %s' % (n, run['host'], result), flush=True)
    if not live:
        print('stop-all: no live runs')
    elif args.dry_run:
        print('stop-all: dry run, %d live runs, nothing stopped' % len(live))
    else:
        print('stop-all: %d stopped, %d not stopped' % (stopped, failed))
    return 0 if ok and not failed else 1


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except host.Unreadable as e:
        print('stop-all.py: %s' % e, file=sys.stderr)
        sys.exit(2)
