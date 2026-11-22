import json
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
REPO = 'example/fleet'
SPEC = '7'
DUE = 'start #9: synthetic ticket (spec #7)\nreview #10: synthetic review (spec #7)\n'


MANAGER = r"""
import os
from pathlib import Path
import sys

name, *args = sys.argv[1:]
home = Path.home()
log = home / 'manager.log'
with log.open('a') as f:
    f.write(' '.join([name, *args]) + '\n')
if name == 'systemctl' and args == ['--user', 'show-environment']:
    sys.exit(0 if (home / 'systemd').exists() else 1)
if name == 'systemctl' and args[1:3] == ['enable', '--now'] and (home / 'enable-failure').exists():
    sys.exit(4)
if name == 'crontab':
    table = home / 'crontab'
    if args == ['-l']:
        print(table.read_text(), end='')
    elif args == ['-']:
        table.write_text(sys.stdin.read())
    else:
        sys.exit(2)
"""


CHECK = r"""
printf '%s\n' "$GH_REPO $*" >> "$HOME/check.log"
if [ -p "$HOME/entered" ]; then
    printf 'entered\n' > "$HOME/entered"
    read -r release < "$HOME/release"
fi
cat "$HOME/due"
if [ -f "$HOME/check-failure" ]; then exit 2; fi
"""


DRIVER = r"""
import json
from pathlib import Path
import sys

home = Path.home()
action = sys.argv[1]
request = json.load(sys.stdin)
log = home / 'driver.log'
previous = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
with log.open('a') as stream:
    print(json.dumps([action, request]), file=stream)
mode = (home / 'wake-mode').read_text() if (home / 'wake-mode').exists() else ''
if action == 'start':
    number = 1 + sum(kind == 'start' for kind, _ in previous)
    print(json.dumps({'run': f'synthetic-run-{number}'}))
elif mode == 'unknown':
    print(json.dumps({'error': 'no run ' + request['run'], 'next': 'check the saved run'}))
    sys.exit(1)
elif action == 'wake' and mode == 'stopped':
    print(json.dumps({'error': 'run ' + request['run'] + ' is stopped', 'next': 'start a new run'}))
    sys.exit(1)
elif action == 'wake' and mode == 'ambiguous':
    sys.exit(2)
elif action in ('wake', 'stop'):
    print(json.dumps(dict(request, **{'woke' if action == 'wake' else 'stopped': True})))
else:
    sys.exit(2)
"""


def cron_command_of(field):
    command, i = [], 0
    while i < len(field) and field[i] != '%':
        escaped = field.startswith('\\%', i)
        command.append('%' if escaped else field[i])
        i += 2 if escaped else 1
    return ''.join(command)


class Heartbeat(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='heartbeat proof ')
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.bin = self.home / 'bin'
        self.bin.mkdir()
        self.scripts = self.home / "installed 100% it's" / 'scripts'
        self.scripts.mkdir(parents=True)
        shutil.copyfile(HERE / 'heartbeat.py', self.scripts / 'heartbeat.py')
        (self.scripts / 'host.py').symlink_to(HERE / 'host.py')
        (self.scripts / 'fleet.sh').write_text(CHECK)
        (self.home / 'due').touch()
        self.checkout = self.home / 'checkout'
        self.checkout.mkdir()
        self.adapters = self.home / 'adapters'
        self.env = {'HOME': str(self.home), 'PATH': f'{self.bin}{os.pathsep}{os.defpath}',
                    'OPENWIZ_ADAPTERS': str(self.adapters), 'LC_ALL': 'C'}
        self.platform = 'linux'
        for name in ('systemctl', 'crontab', 'launchctl'):
            self.program(self.bin / name,
                         f'exec {shlex.quote(sys.executable)} -I -c {shlex.quote(MANAGER)} {name} "$@"')
        (self.home / 'crontab').write_text('15 3 * * * /bin/true\n')

    def program(self, path, script):
        path.write_text('#!/bin/sh\n' + script + '\n')
        path.chmod(0o700)

    def invoke(self, action, *args):
        entry = str(self.scripts / 'heartbeat.py')
        code = 'import runpy, sys; sys.platform = sys.argv[1]; sys.argv = sys.argv[2:]; runpy.run_path(sys.argv[0], run_name="__main__")'
        return [sys.executable, '-I', '-c', code, self.platform, entry, action, REPO, SPEC, *args]

    def heartbeat(self, action, *args, expected=0, env=None):
        result = subprocess.run(self.invoke(action, *args), cwd=self.checkout, env=env or self.env,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result.stdout

    def files(self, glob):
        return sorted(self.home.glob(glob))

    def preview(self):
        return self.heartbeat('install', 'codex', 'synthetic-model')

    def install(self):
        return self.heartbeat('install', 'codex', 'synthetic-model', '--yes')

    def assert_preview_file(self, path, preview):
        self.assertIn(f'--- {path}\n{path.read_text()}', preview)

    def test_launchd_install_and_remove(self):
        self.platform = 'darwin'
        preview = self.preview()
        self.assertIn('StartInterval', preview)
        self.assertEqual(self.files('Library/LaunchAgents/*.plist'), [])
        self.assertFalse((self.home / 'manager.log').exists())
        self.assertEqual(self.install(), preview)
        plist, = self.files('Library/LaunchAgents/*.plist')
        self.assert_preview_file(plist, preview)
        job = plistlib.loads(plist.read_bytes())
        self.assertEqual(job['StartInterval'], 600)
        self.assertEqual(job['ProgramArguments'], [sys.executable, '-I', str(self.scripts / 'heartbeat.py'),
                                                  'run', REPO, SPEC])
        self.assertIn('active', self.heartbeat('status'))
        self.heartbeat('remove')
        self.assertFalse(plist.exists())
        self.assertIn('not installed', self.heartbeat('status'))
        domain = f'gui/{os.getuid()}'
        self.assertEqual((self.home / 'manager.log').read_text().splitlines(),
                         [f'launchctl bootstrap {domain} {plist}', f'launchctl bootout {domain}/{job["Label"]}'])

    def test_systemd_install_and_remove(self):
        (self.home / 'systemd').touch()
        preview = self.preview()
        self.assertIn('OnCalendar=*:0/10', preview)
        self.assertEqual(self.files('.config/systemd/user/*'), [])
        self.assertEqual(self.install(), preview)
        service, timer = self.files('.config/systemd/user/*')
        self.assert_preview_file(service, preview)
        self.assert_preview_file(timer, preview)
        self.assertIn('Type=oneshot\n', service.read_text())
        self.assertIn('KillMode=process\n', service.read_text())
        self.assertIn("installed 100%% it's", service.read_text())
        self.heartbeat('remove')
        self.assertEqual(self.files('.config/systemd/user/*'), [])
        self.assertEqual((self.home / 'manager.log').read_text().splitlines(),
                         ['systemctl --user show-environment', 'systemctl --user show-environment',
                          'systemctl --user daemon-reload', f'systemctl --user enable --now {timer.name}',
                          f'systemctl --user disable --now {timer.name}', 'systemctl --user daemon-reload'])

    def test_partial_install_rolls_back(self):
        (self.home / 'systemd').touch()
        failure = self.home / 'enable-failure'
        failure.touch()
        self.heartbeat('install', 'codex', 'synthetic-model', '--yes', expected=1)
        self.assertEqual(self.files('.config/systemd/user/*'), [])
        self.assertIn('not installed', self.heartbeat('status'))
        failure.unlink()
        self.install()
        self.assertIn('active', self.heartbeat('status'))

    def test_cron_install_and_remove(self):
        original = (self.home / 'crontab').read_text()
        preview = self.preview()
        self.assertIn('*/10 * * * * ', preview)
        self.assertEqual((self.home / 'crontab').read_text(), original)
        self.assertEqual(self.install(), preview)
        current = (self.home / 'crontab').read_text()
        self.assertTrue(current.startswith(original))
        line, = current[len(original):].splitlines()
        self.assertIn(line + '\n', preview)
        command = cron_command_of(line.split(' ', 5)[5])
        ran = subprocess.run(['/bin/sh', '-c', command], env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
        self.assertEqual((self.home / 'check.log').read_text(), f'{REPO} spec {SPEC}\n')
        self.heartbeat('remove')
        self.assertEqual((self.home / 'crontab').read_text(), original)

    def setup_driver(self):
        real_git = shutil.which('git')
        git_env = dict(self.env, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1',
                       GIT_AUTHOR_NAME='Synthetic', GIT_AUTHOR_EMAIL='tests@example.invalid',
                       GIT_COMMITTER_NAME='Synthetic', GIT_COMMITTER_EMAIL='tests@example.invalid')
        for args in [
            ('init', '-q', '-b', 'main'),
            ('remote', 'add', 'origin', str(self.checkout)),
        ]:
            subprocess.run([real_git, *args], cwd=self.checkout, env=git_env, check=True, capture_output=True)
        settings = self.checkout / 'docs/agents'
        settings.mkdir(parents=True)
        (settings / 'host.md').write_text('Host: local\n')
        for args in [('add', '.'), ('commit', '-qm', 'fixture')]:
            subprocess.run([real_git, *args], cwd=self.checkout, env=git_env, check=True, capture_output=True)
        shutil.copyfile(HERE / 'fixtures/fake_github.py', self.scripts / 'fake_github.py')
        (self.home / 'world.json').write_text(json.dumps({
            'repo': REPO, 'me': 'synthetic-owner', 'next_id': 5000, 'comments': {}, 'writes': [], 'faults': {},
            'fleet_md': '## GitHub identity\n\n| Record authors | `synthetic-owner` |\n',
        }))
        self.program(self.bin / 'gh',
                     f'export FAKE_WORLD="$HOME/world.json"; exec {shlex.quote(sys.executable)} -I '
                     f'{shlex.quote(str(self.scripts / "fake_github.py"))} "$@"')
        driver = self.adapters / 'local' / 'driver'
        driver.parent.mkdir(parents=True)
        self.program(driver, f'exec {shlex.quote(sys.executable)} -I -c {shlex.quote(DRIVER)} "$@"')

    def driver_calls(self):
        return [json.loads(line) for line in (self.home / 'driver.log').read_text().splitlines()]

    def test_due_and_idle_ticks(self):
        self.setup_driver()
        self.install()
        self.heartbeat('run', env={'HOME': str(self.home)})
        self.assertEqual((self.home / 'check.log').read_text().splitlines(), [f'{REPO} spec {SPEC}'])
        self.assertFalse((self.home / 'driver.log').exists())
        (self.home / 'due').write_text(DUE)
        self.heartbeat('run')
        self.heartbeat('run')
        expected = {'repository': REPO, 'ticket': 7, 'skill': 'launch-fleet',
                    'harness': 'codex', 'model': 'synthetic-model'}
        wake = ['wake', {'run': 'synthetic-run-1'}]
        self.assertEqual(self.driver_calls(), [['start', expected], wake])
        (self.home / 'check-failure').touch()
        self.heartbeat('run', expected=2)
        self.assertEqual(self.driver_calls(), [['start', expected], wake])
        log, = self.files('.local/state/openwiz-heartbeat/*/ticks.log')
        self.assertEqual([line.split(' ', 1)[1] for line in log.read_text().splitlines()],
                         ['idle', 'started', 'woke', 'check failed'])
        self.heartbeat('remove')
        self.assertEqual(self.driver_calls(), [['start', expected], wake, ['stop', {'run': 'synthetic-run-1'}]])

    def ticks(self):
        log, = self.files('.local/state/openwiz-heartbeat/*/ticks.log')
        return [line.split(' ', 1)[1] for line in log.read_text().splitlines()]

    def test_status_names_an_unresolved_start_and_each_blocked_tick_logs_it(self):
        self.setup_driver()
        self.install()
        state, = self.files('.local/state/openwiz-heartbeat/*')
        (state / 'starting').mkdir()
        (self.home / 'due').write_text(DUE)
        self.heartbeat('run', expected=1)
        self.heartbeat('run', expected=1)
        self.assertEqual(self.ticks(), ['start unresolved', 'start unresolved'])
        self.assertEqual(self.heartbeat('status').splitlines(),
                         ['heartbeat: active (cron)', f'heartbeat: start unresolved: reconcile {state / "starting"}'])
        self.assertFalse((self.home / 'driver.log').exists())

    def test_a_closed_spec_logs_done_and_status_says_to_remove(self):
        self.setup_driver()
        self.install()
        self.heartbeat('run')
        self.assertEqual(self.heartbeat('status').splitlines(), ['heartbeat: active (cron)'])
        (self.home / 'due').write_text(f"fleet done #{SPEC}: synthetic spec closed; delete this fleet thread's loop\n")
        self.heartbeat('run')
        self.assertEqual(self.ticks(), ['idle', 'done'])
        self.assertEqual(self.heartbeat('status').splitlines(),
                         ['heartbeat: active (cron)',
                          f'heartbeat: spec #{SPEC} is done: run heartbeat.py remove {REPO} {SPEC}'])
        self.assertFalse((self.home / 'driver.log').exists())

    def test_remove_retires_a_run_the_driver_no_longer_knows(self):
        self.setup_driver()
        self.install()
        (self.home / 'due').write_text(DUE)
        self.heartbeat('run')
        (self.home / 'wake-mode').write_text('unknown')
        self.heartbeat('remove')
        self.assertEqual([kind for kind, _ in self.driver_calls()], ['start', 'stop'])
        self.assertEqual(self.files('.local/state/openwiz-heartbeat/openwiz-heartbeat-*'), [])
        retired, = self.files('.local/state/openwiz-heartbeat/retired-runs/*/*.json')
        self.assertEqual(json.loads(retired.read_text())['runs'][SPEC]['run'], 'synthetic-run-1')
        self.assertIn('not installed', self.heartbeat('status'))

    def test_terminal_refusals_replace_the_run_without_losing_ids(self):
        self.setup_driver()
        self.install()
        (self.home / 'due').write_text(DUE)
        self.heartbeat('run')
        mode = self.home / 'wake-mode'
        mode.write_text('stopped')
        self.heartbeat('run')
        mode.write_text('unknown')
        self.heartbeat('run')
        mode.unlink()
        self.heartbeat('run')
        calls = self.driver_calls()
        self.assertEqual([kind for kind, _ in calls],
                         ['start', 'wake', 'wake', 'wake', 'stop', 'start',
                          'wake', 'wake', 'wake', 'stop', 'start', 'wake'])
        self.assertEqual([record['run'] for kind, record in calls if kind != 'start'],
                         ['synthetic-run-1'] * 4 + ['synthetic-run-2'] * 4 + ['synthetic-run-3'])
        saved_ids = {row['run'] for path in self.files('.local/state/openwiz-heartbeat/**/*.json')
                     for row in json.loads(path.read_text()).get('runs', {}).values()}
        self.assertEqual(saved_ids, {'synthetic-run-1', 'synthetic-run-2', 'synthetic-run-3'})

    def test_ambiguous_wake_keeps_the_existing_run(self):
        self.setup_driver()
        self.install()
        (self.home / 'due').write_text(DUE)
        self.heartbeat('run')
        mode = self.home / 'wake-mode'
        mode.write_text('ambiguous')
        self.heartbeat('run', expected=1)
        mode.unlink()
        self.heartbeat('run')
        calls = self.driver_calls()
        self.assertEqual([kind for kind, _ in calls], ['start', 'wake', 'wake'])
        self.assertEqual([record['run'] for kind, record in calls if kind == 'wake'], ['synthetic-run-1'] * 2)

    def test_check_uses_driver_routes_without_cloudroom_probe(self):
        self.program(self.bin / 'room-cli', """printf '%s\n' "$*" >> "$HOME/room-cli.log"
printf '[]\n'""")
        world = {'specs': [], 'singles': [{'number': 9, 'comments': {'nodes': [
            {'createdAt': '2030-01-02T00:00:00Z', 'databaseId': 100, 'body': 'launch-fleet: started'},
        ]}}]}
        records = self.home / 'records.json'
        records.write_text(json.dumps(world))
        runs = self.home / 'runs.json'
        runs.write_text(json.dumps({'repo': REPO, 'runs': {'9': {'host': 'local', 'run': 'synthetic-run'}}}))
        self.env['LAUNCH_FLEET_RUNS'] = str(runs)
        command = [sys.executable, '-I', str(HERE / 'records.py'), REPO, 'false']
        original = subprocess.run(command, input=records.read_text(), env=self.env,
                                  capture_output=True, text=True, check=True, timeout=15)
        probe = self.home / 'room-cli.log'
        self.assertEqual(probe.read_text().splitlines(), ['thread list --include-archived --include-hidden --json'])
        probe.unlink()

        (self.scripts / 'fleet.sh').write_text(
            f'{shlex.quote(sys.executable)} -I {shlex.quote(str(HERE / "records.py"))} "$GH_REPO" false '
            '< "$HOME/records.json" > "$HOME/annotated.json"\n')
        self.install()
        self.heartbeat('run')
        self.assertFalse(probe.exists(), 'the heartbeat invoked the CloudRoom thread probe')
        actual = json.loads((self.home / 'annotated.json').read_text())
        self.assertEqual(actual, json.loads(original.stdout))
        self.assertEqual(actual['singles'][0]['comments']['nodes'][0]['resolvedThread'], 'run:9')

    def test_pause_and_resume_run_now(self):
        crontab = self.home / 'crontab'
        original = crontab.read_text()
        self.install()
        installed = crontab.read_text()
        self.heartbeat('pause')
        self.assertEqual(crontab.read_text(), original)
        self.assertIn('paused', self.heartbeat('status'))
        self.heartbeat('run')
        self.assertFalse((self.home / 'check.log').exists())
        self.heartbeat('resume')
        self.assertEqual(crontab.read_text(), installed)
        self.assertIn('active', self.heartbeat('status'))
        self.heartbeat('run')
        self.assertEqual((self.home / 'check.log').read_text().splitlines(), [f'{REPO} spec {SPEC}'])

    def test_concurrent_tick_refuses(self):
        self.install()
        entered, release = self.home / 'entered', self.home / 'release'
        os.mkfifo(entered)
        os.mkfifo(release)
        release_fd = os.open(release, os.O_RDWR)
        first = subprocess.Popen(self.invoke('run'), cwd=self.checkout, env=self.env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            wait = subprocess.run(['/bin/cat', str(entered)], capture_output=True, text=True, timeout=10)
            self.assertEqual(wait.stdout, 'entered\n')
            self.assertIn('already running', self.heartbeat('run', expected=1))
        finally:
            os.write(release_fd, b'release\n')
            os.close(release_fd)
            try:
                out, err = first.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                first.kill()
                first.communicate()
                raise
        self.assertEqual(first.returncode, 0, out + err)
        self.assertEqual((self.home / 'check.log').read_text().splitlines(), [f'{REPO} spec {SPEC}'])
        log, = self.files('.local/state/openwiz-heartbeat/*/ticks.log')
        self.assertEqual([line.split(' ', 1)[1] for line in log.read_text().splitlines()], ['busy', 'idle'])


if __name__ == '__main__':
    unittest.main()
