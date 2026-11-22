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


class Heartbeat(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='heartbeat proof ')
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.bin = self.home / 'bin'
        self.bin.mkdir()
        self.scripts = self.home / "installed 100% it's" / 'scripts'
        self.scripts.mkdir(parents=True)
        for name in ('heartbeat', 'host', 'status', 'post'):
            shutil.copyfile(HERE / (name + '.py'), self.scripts / (name + '.py'))
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
        self.assertIn("installed 100%% it's", service.read_text())
        self.heartbeat('remove')
        self.assertEqual(self.files('.config/systemd/user/*'), [])
        self.assertEqual((self.home / 'manager.log').read_text().splitlines(),
                         ['systemctl --user show-environment', 'systemctl --user show-environment',
                          'systemctl --user daemon-reload', f'systemctl --user enable --now {timer.name}',
                          f'systemctl --user disable --now {timer.name}', 'systemctl --user daemon-reload'])

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
        self.heartbeat('remove')
        self.assertEqual((self.home / 'crontab').read_text(), original)

if __name__ == '__main__':
    unittest.main()
