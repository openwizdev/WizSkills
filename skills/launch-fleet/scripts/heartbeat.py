#!/usr/bin/env python3
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import shutil
import subprocess
import sys


HERE = Path(__file__).resolve().parent
REPO = re.compile(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+')
NUMBER = re.compile(r'[1-9][0-9]{0,8}')
WORD = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,119}')
INTERVAL = 10
TOOLS_ENV = (
    'PATH', 'OPENWIZ_ADAPTERS', 'OPENWIZ_LOCAL_STATE', 'LAUNCH_FLEET_RUNS', 'GH_CONFIG_DIR',
    'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_STATE_HOME',
)


class Refused(Exception):
    pass


class Busy(Refused):
    pass


def command(args, *, text=None):
    result = subprocess.run(args, input=text, capture_output=True, text=True, timeout=30,
                            env=dict(os.environ, LC_ALL='C'))
    if result.returncode:
        raise Refused(f'{args[0]} {args[1]} failed (exit {result.returncode})')
    return result.stdout


def systemd_argument(value):
    escaped = value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%').replace('$', '$$')
    return '"' + escaped + '"'


class Job:
    def __init__(self, name, argv, backend, folder):
        self.name = name
        self.argv = argv
        self.backend = backend
        self.folder = Path(folder)
        self.timer = name + '.timer'
        self.domain = f'gui/{os.getuid()}'
        self.marker = f' # {name}'
        self.cron = (f'*/{INTERVAL} * * * * ' + shlex.join(argv).replace('%', r'\%')
                     + ' >/dev/null 2>&1' + self.marker)

    def files(self):
        if self.backend == 'launchd':
            return {self.folder / (self.name + '.plist'): plistlib.dumps({
                'Label': self.name, 'ProgramArguments': self.argv, 'StartInterval': INTERVAL * 60,
            }).decode()}
        if self.backend == 'systemd':
            execute = ' '.join(map(systemd_argument, self.argv))
            service = f'[Service]\nType=oneshot\nKillMode=process\nExecStart={execute}\n'
            timer = f'[Timer]\nOnCalendar=*:0/{INTERVAL}\n\n[Install]\nWantedBy=timers.target\n'
            return {self.folder / (self.name + '.service'): service, self.folder / self.timer: timer}
        return {}

    def preview(self):
        if self.backend == 'cron':
            print(f'--- crontab\n{self.cron}')
        for path, text in self.files().items():
            print(f'--- {path}\n{text}', end='')

    def crontab(self):
        result = subprocess.run(['crontab', '-l'], stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, timeout=30, env=dict(os.environ, LC_ALL='C'))
        if result.returncode == 0:
            return result.stdout
        if result.returncode == 1 and result.stderr.startswith('no crontab for '):
            return ''
        raise Refused('could not read the current crontab')

    def available(self):
        if self.backend == 'cron':
            if any(line.endswith(self.marker) for line in self.crontab().splitlines()):
                raise Refused('the heartbeat line already exists in crontab')
        elif any(path.exists() or path.is_symlink() for path in self.files()):
            raise Refused('a heartbeat scheduler file already exists')

    def install(self):
        if self.backend == 'cron':
            current = self.crontab()
            separator = '\n' if current and not current.endswith('\n') else ''
            command(['crontab', '-'], text=current + separator + self.cron + '\n')
            return
        for path, text in self.files().items():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('x') as stream:
                stream.write(text)
        if self.backend == 'launchd':
            command(['launchctl', 'bootstrap', self.domain, str(next(iter(self.files())))])
        else:
            command(['systemctl', '--user', 'daemon-reload'])
            command(['systemctl', '--user', 'enable', '--now', self.timer])

    def remove(self):
        if self.backend == 'cron':
            current = self.crontab()
            remaining = ''.join(line for line in current.splitlines(keepends=True)
                                if not line.rstrip('\n').endswith(self.marker))
            if current != remaining:
                command(['crontab', '-'], text=remaining)
            return
        if self.backend == 'launchd':
            target = f'{self.domain}/{self.name}'
            result = subprocess.run(['launchctl', 'bootout', target], capture_output=True, text=True, timeout=30)
            if result.returncode and 'Could not find service' not in result.stderr:
                raise Refused(f'launchctl bootout failed (exit {result.returncode})')
        elif (self.folder / self.timer).exists():
            command(['systemctl', '--user', 'disable', '--now', self.timer])
        for path in self.files():
            path.unlink(missing_ok=True)
        if self.backend == 'systemd':
            command(['systemctl', '--user', 'daemon-reload'])


def scheduler():
    if sys.platform == 'darwin':
        return 'launchd', Path.home() / 'Library/LaunchAgents'
    if sys.platform.startswith('linux'):
        if shutil.which('systemctl') and subprocess.run(
            ['systemctl', '--user', 'show-environment'], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
        ).returncode == 0:
            config = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
            return 'systemd', (config / 'systemd/user').resolve()
        if shutil.which('crontab'):
            return 'cron', Path.home()
        raise Refused('neither a systemd user manager nor crontab is available')
    raise Refused('the heartbeat requires macOS or Linux')


def arguments():
    parser = argparse.ArgumentParser(description='Manage a local fleet heartbeat.')
    sub = parser.add_subparsers(dest='action', required=True)
    for action in ('install', 'status', 'pause', 'resume', 'remove', 'run'):
        entry = sub.add_parser(action)
        entry.add_argument('repo', metavar='OWNER/NAME')
        entry.add_argument('spec', metavar='SPEC')
        if action == 'install':
            entry.add_argument('harness')
            entry.add_argument('model')
            entry.add_argument('--yes', action='store_true')
    args = parser.parse_args()
    if (not REPO.fullmatch(args.repo) or args.repo.split('/')[1] in ('.', '..')
            or not NUMBER.fullmatch(args.spec)):
        parser.error('expected OWNER/NAME and a positive spec number')
    if args.action == 'install' and not (WORD.fullmatch(args.harness) and WORD.fullmatch(args.model)):
        parser.error('harness and model must be driver identifiers')
    return args


@contextmanager
def locked(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Busy('a heartbeat operation is already running') from None
        if not os.path.samestat(os.fstat(fd), directory.stat()):
            raise Refused('the heartbeat installation changed')
        yield
    finally:
        os.close(fd)


def install(args, name, state):
    backend, folder = scheduler()
    argv = [sys.executable, '-I', str(HERE / 'heartbeat.py'), 'run', args.repo, args.spec]
    if any(ord(char) < 32 for item in [*argv, str(folder)] for char in item):
        raise Refused('scheduler paths cannot contain control characters')
    job = Job(name, argv, backend, folder)
    job.preview()
    if not args.yes:
        return
    job.available()
    settings = {key: os.environ[key] for key in TOOLS_ENV if key in os.environ}
    settings.setdefault('PATH', os.defpath)
    state.mkdir(mode=0o700, parents=True)
    with locked(state):
        config = {'backend': backend, 'folder': str(folder), 'argv': argv, 'cwd': str(Path.cwd()),
                  'harness': args.harness, 'model': args.model, 'environment': settings}
        (state / 'config.json').write_text(json.dumps(config) + '\n')
        job.install()


def tick(state, config, paused):
    outcome = 'check failed'
    try:
        if paused:
            outcome = 'paused'
            return 0
        _, _, _, _, repo, spec = config['argv']
        inherited = ('HOME', 'USER', 'LOGNAME', 'TMPDIR', 'SSH_AUTH_SOCK', 'XDG_RUNTIME_DIR',
                     'DBUS_SESSION_BUS_ADDRESS')
        env = {key: os.environ[key] for key in inherited if key in os.environ}
        env.update(config['environment'], GH_REPO=repo, GH_PROMPT_DISABLED='1', GIT_TERMINAL_PROMPT='0')
        repo_key = hashlib.sha256(repo.lower().encode()).hexdigest()[:20]
        env.setdefault('LAUNCH_FLEET_RUNS', str(state.parent / f'runs-{repo_key}.json'))
        result = subprocess.run(['sh', str(HERE / 'fleet.sh'), 'spec', spec], cwd=config['cwd'], env=env,
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)
        if result.returncode:
            print(f'heartbeat: check failed (exit {result.returncode})', file=sys.stderr)
            return 2
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        if not lines or lines[0].startswith(f'fleet done #{spec}:'):
            outcome = 'idle'
            return 0

        outcome = 'start unresolved'
        attempt = state / 'starting'
        if attempt.exists():
            print(f'heartbeat: reconcile the previous start in {attempt}', file=sys.stderr)
            return 1
        attempt.mkdir(mode=0o700)
        env['LAUNCH_FLEET_HEARTBEAT_RUNS'] = env['LAUNCH_FLEET_RUNS']
        env['LAUNCH_FLEET_RUNS'] = str(attempt / 'runs.json')
        result = subprocess.run(
            [sys.executable, '-I', str(HERE / 'host.py'), 'start', repo, spec,
             config['harness'], config['model'], 'launch-fleet'],
            cwd=config['cwd'], env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=1000,
        )
        if result.returncode:
            if result.stdout.startswith(('refused:', 'stopped (driver start failed):')) or result.returncode == 2:
                outcome = 'start refused'
                shutil.rmtree(attempt)
            print(f'heartbeat: {outcome} (exit {result.returncode})', file=sys.stderr)
            return result.returncode
        last = state / 'last-wake'
        if last.exists():
            shutil.rmtree(last)
        attempt.rename(last)
        outcome = 'started'
        return 0
    finally:
        log_tick(state, outcome)


def log_tick(state, outcome):
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    with (state / 'ticks.log').open('a') as log:
        log.write(f'{stamp} {outcome}\n')

def main():
    args = arguments()
    key = hashlib.sha256(f'{args.repo.lower()}#{args.spec}'.encode()).hexdigest()[:20]
    name = 'openwiz-heartbeat-' + key
    state = Path.home() / '.local/state/openwiz-heartbeat' / name
    if args.action == 'install':
        install(args, name, state)
        return 0
    config_path = state / 'config.json'
    if not config_path.is_file():
        if args.action in ('status', 'remove'):
            print('heartbeat: not installed')
            return 0
        raise Refused('heartbeat is not installed')
    status = state / 'paused'
    if args.action == 'status':
        config = json.loads(config_path.read_text())
        phase = 'paused' if status.exists() else 'active'
        print(f'heartbeat: {phase} ({config["backend"]})')
        return 0
    if args.action == 'run':
        try:
            with locked(state):
                return tick(state, json.loads(config_path.read_text()), status.exists())
        except Busy:
            log_tick(state, 'busy')
            raise
    with locked(state):
        config = json.loads(config_path.read_text())
        if args.action == 'remove':
            Job(name, config['argv'], config['backend'], config['folder']).remove()
            shutil.rmtree(state)
        elif args.action == 'pause':
            status.touch()
        elif args.action == 'resume':
            status.unlink(missing_ok=True)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Refused as exc:
        print(f'heartbeat: {exc}')
        sys.exit(1)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f'heartbeat: {exc}', file=sys.stderr)
        sys.exit(2)
