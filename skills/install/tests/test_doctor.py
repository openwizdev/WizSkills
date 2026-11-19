#!/usr/bin/env python3
"""The setup doctor (#1449) on a synthetic setup: each planted problem prints
its own line and fixing command, in the doctor's order; a clean setup prints
one all-clear line; no login or token passes through it.

The fakes stand in only for what lives outside WizSkills: gh, the installed
build's setup.py (its runtime_pin) and the OpenWiz checkout's driver kit (its
Kit.version). The doctor's own reuse of settings.py, status.py and the setup
store's codes runs for real.
"""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import unittest

DOCTOR = Path(__file__).resolve().parents[1] / 'scripts/doctor.py'
REPO = 'synthetic-owner/synthetic-repo'
LOGIN = 'synthetic-factory[bot]'
SECRET = 'ghs_' + 'S' * 36
LABELS = ('needs-triage', 'needs-info', 'ready-for-agent', 'ready-for-human', 'wontfix')
FLEET = ('# Fleet settings\n\n## GitHub identity\n\n| Setting | Value |\n| --- | --- |\n'
         '| Record authors | `synthetic-factory[bot]`, `synthetic-owner` |\n')
TRIAGE = ('# Triage labels\n\n## Labels\n\n| Role | Label here | Meaning |\n| --- | --- | --- |\n'
          + ''.join('| `%s` | `%s` | Synthetic |\n' % (l, l) for l in LABELS))

# gh: answers the doctor's three reads from files in $FAKE_DIR, logs each argv.
FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
d = os.environ['FAKE_DIR']
with open(os.path.join(d, 'gh.log'), 'a') as log:
    log.write(json.dumps(sys.argv[1:]) + '\n')
def answer(name):
    path = os.path.join(d, name)
    if not os.path.exists(path):
        sys.stderr.write('synthetic gh: not signed in\n'); sys.exit(4)
    sys.stdout.write(open(path).read()); sys.exit(0)
a = sys.argv[1:]
if a[:2] == ['label', 'list']:
    answer('labels.json')
if a[:1] == ['api'] and any(x.endswith('/contents/docs/agents/fleet.md') for x in a):
    answer('fleet.md')
if a[:1] == ['api'] and 'graphql' in a:
    sys.stdin.read(); answer('viewer.json')
sys.stderr.write('synthetic gh: refused %r\n' % a); sys.exit(9)
'''

# The build's setup.py: the real runtime_pin's shape (openwiz-build.txt and the packaged skills).
FAKE_SETUP = r'''from pathlib import Path
SKILLS = ('setup', 'grill', 'plan-graph', 'launch-fleet')
def runtime_pin(runtime):
    if runtime is None:
        return None
    try:
        parts = (Path(runtime) / 'openwiz-build.txt').read_text().split('\n')
    except OSError:
        return None
    if len(parts) != 5 or parts[0] != 'openwiz.package.v1':
        return None
    if not all((Path(runtime) / 'skills' / n / 'SKILL.md').is_file() for n in SKILLS):
        return None
    return parts[1] + ' ' + parts[2]
'''

# The checkout's driver kit: Kit(args, ticket).version() -> ('pass'|'fail', what), as kit.py's.
FAKE_KIT = r'''import json, subprocess
class Kit:
    def __init__(self, args, ticket):
        self.args = args
    def version(self):
        try:
            p = subprocess.run([self.args.driver, 'version'], capture_output=True, text=True, timeout=30)
            v = json.loads(p.stdout)
        except (OSError, ValueError) as e:
            return 'fail', 'version printed no single JSON value'
        if p.returncode != 0:
            return 'fail', v.get('error', 'refused')
        if 'openwiz:records v1' not in v.get('records', []):
            return 'fail', 'it names no openwiz:records v1'
        return 'pass', 'openwiz:records v1, and the schema is driver v1'
'''
GOOD_DRIVER = ('#!/bin/sh\necho \'{"driver": "synthetic", "records": ["openwiz:records v1"], '
               '"can": ["start", "wake", "stop"]}\'\n')
BAD_DRIVER = '#!/bin/sh\necho \'{"error": "synthetic driver refuses version"}\'\nexit 1\n'


def write(path, text, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)


class Setup:
    """One clean synthetic setup; each test plants one problem in it."""

    def __init__(self, root):
        self.root = root
        self.fake, self.checkout = root / 'fake', root / 'project'
        self.state, self.build, self.openwiz = root / 'state', root / 'build', root / 'openwiz'
        self.driver = root / 'driver'
        write(self.fake / 'bin/gh', FAKE_GH, 0o755)
        write(self.fake / 'labels.json', json.dumps([{'name': l} for l in LABELS + ('polish',)]))
        write(self.fake / 'fleet.md', FLEET)
        write(self.fake / 'viewer.json', json.dumps({'data': {'viewer': {'login': LOGIN}}}))
        write(self.checkout / 'docs/agents/triage-labels.md', TRIAGE)
        write(self.build / 'runtime/setup/setup.py', FAKE_SETUP)
        write(self.build / 'runtime/openwiz-build.txt', 'openwiz.package.v1\n0.1.0\n%s\nsynthetic\n' % ('a' * 40))
        for name in ('setup', 'grill', 'plan-graph', 'launch-fleet'):
            write(self.build / 'runtime/skills' / name / 'SKILL.md', '# synthetic\n')
        write(self.openwiz / 'kernel/driver-kit/kit.py', FAKE_KIT)
        write(self.driver, GOOD_DRIVER, 0o755)
        self.observations = {'github_app': 'app_verified', 'harness': 'harness_listed'}
        self.project = {'repository': REPO, 'project': 'syn-project', 'harness': 'syn-harness',
                        'model': 'syn-model', 'effort': 'high'}
        self.identity = None
        self.save()

    def save(self, at=None):
        at = int(time.time() * 1000) if at is None else at
        value = {'schema': 'openwiz.setup-state.v1', 'revision': 3, 'project': self.project,
                 'identity': self.identity, 'brain': None,
                 'observations': {k: {'code': v, 'revision': 3, 'at': at} for k, v in self.observations.items()}}
        (self.state / 'setup').mkdir(parents=True, exist_ok=True, mode=0o700)
        write(self.state / 'setup/state.json', json.dumps(value), 0o600)

    def run(self, *extra, driver=True):
        env = {'PATH': '%s:%s' % (self.fake / 'bin', os.environ.get('PATH', '/usr/bin:/bin')),
               'FAKE_DIR': str(self.fake), 'HOME': str(self.root), 'GH_TOKEN': SECRET}
        argv = [sys.executable, '-I', str(DOCTOR), '--repo', REPO, '--root', str(self.checkout),
                '--state-dir', str(self.state), '--build', str(self.build), '--openwiz', str(self.openwiz)]
        argv += ['--driver', str(self.driver)] if driver else []
        return subprocess.run(argv + list(extra), capture_output=True, text=True, env=env, timeout=60)

    def gh_calls(self):
        log = self.fake / 'gh.log'
        return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []


class Doctor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = Setup(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def lines(self, result, code=5):
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        return result.stdout.splitlines()

    def only(self, result):
        """The one problem line of a run with one planted problem."""
        lines = self.lines(result)
        self.assertEqual(lines[-1], 'Doctor: 1 problem.', result.stdout)
        self.assertEqual(len(lines), 2, result.stdout)
        return lines[0]

    # catches: a clean setup that still prints noise, or no single all-clear line.
    def test_clean_setup_prints_one_all_clear_line(self):
        self.assertEqual(self.lines(self.s.run(), 0),
                         ['Doctor: all clear: labels, App, record author, harness listed (its sign-in is not provable yet), '
                          'driver and skills.'])

    # catches: a clean setup that reads as clear without saying the driver went unchecked.
    def test_no_driver_is_said_on_the_all_clear_line(self):
        self.assertEqual(self.lines(self.s.run(driver=False), 0),
                         ['Doctor: all clear: labels, App, record author, harness listed (its sign-in is not provable yet) '
                          'and skills; no driver given.'])

    # catches: a missing tracker label passing, or a fix that isn't the exact gh command.
    def test_missing_label(self):
        write(self.s.fake / 'labels.json', json.dumps([{'name': l} for l in LABELS if l != 'needs-info']))
        self.assertEqual(self.only(self.s.run()),
                         '1. Labels: needs-info is not in the tracker. Fix: gh label create needs-info --repo %s'
                         % REPO)

    # catches: a printed fix a shell splits or expands: run it through sh and read the argv gh gets.
    def test_printed_label_fix_runs_as_printed(self):
        odd = "needs info $HOME 'x'"
        write(self.s.checkout / 'docs/agents/triage-labels.md', TRIAGE.replace('| `needs-info` | `needs-info` |',
                                                                              '| `needs-info` | `%s` |' % odd))
        line = self.only(self.s.run())
        self.assertTrue(line.startswith('1. Labels: '), line)
        fix = line.split('. Fix: ', 1)[1]
        env = {'PATH': '%s:/usr/bin:/bin' % (self.s.fake / 'bin'), 'FAKE_DIR': str(self.s.fake), 'HOME': 'expanded'}
        subprocess.run(['sh', '-c', fix], env=env, capture_output=True)
        self.assertEqual(self.s.gh_calls()[-1], ['label', 'create', odd, '--repo', REPO])

    # catches: an unmapped triage role (settings.py's own check) going unreported.
    def test_unmapped_label_role(self):
        write(self.s.checkout / 'docs/agents/triage-labels.md', TRIAGE.replace('| `wontfix` | `wontfix` | Synthetic |\n', ''))
        self.assertEqual(self.only(self.s.run()),
                         '1. Labels: triage-labels.md: wontfix: mapped 0 times. '
                         'Fix: run the setup skill for %s, then the doctor again' % REPO)

    # catches: an unreadable label list read as "no problem", or a sign-in it tries itself.
    def test_labels_unreadable_prints_the_sign_in_command(self):
        (self.s.fake / 'labels.json').unlink()
        self.assertEqual(self.only(self.s.run()),
                         '1. Labels: gh could not list the labels of %s. Fix: gh auth login' % REPO)

    # catches: an App setup's check found missing passing as installed.
    def test_app_not_installed(self):
        self.s.observations['github_app'] = 'app_missing'
        self.s.save()
        self.assertEqual(self.only(self.s.run()),
                         '2. GitHub App: not verified (app_missing). Fix: install OpenWiz\'s GitHub App on %s '
                         'from the setup page, then python3 -I -B %s/runtime/setup/setup.py check --state-dir %s'
                         % (REPO, self.s.build, self.s.state))

    # catches: an old App check counted as current.
    def test_app_check_out_of_date(self):
        self.s.save(at=int(time.time() * 1000) - 2 * 60 * 60 * 1000)
        lines = self.lines(self.s.run())
        fix = 'Fix: python3 -I -B %s/runtime/setup/setup.py check --state-dir %s' % (self.s.build, self.s.state)
        self.assertEqual(lines, ['2. GitHub App: its last check is out of date. ' + fix,
                                 '4. Harness: its last check is out of date. ' + fix, 'Doctor: 2 problems.'])

    # catches: an explicit App skip reported as a missing App (first_fleet's rule).
    def test_app_skip_is_not_a_problem(self):
        self.s.observations['github_app'] = 'app_missing'
        self.s.identity = {'selected': 'personal_login', 'app_choice': 'skip', 'acting_login': 'synthetic-owner',
                           'repository': REPO}
        self.s.save()
        self.assertEqual(self.s.run().returncode, 0)

    # catches: setup prepared for another repository read as this one's evidence.
    def test_setup_for_another_repository(self):
        self.s.project['repository'] = 'synthetic-owner/other'
        self.s.save()
        lines = self.lines(self.s.run())
        fix = ('Fix: python3 -I -B %s/runtime/setup/setup.py prepare --state-dir %s --repository %s ...'
               % (self.s.build, self.s.state, REPO))
        self.assertEqual(lines, ['2. GitHub App: setup is prepared for synthetic-owner/other. ' + fix,
                                 '4. Harness: setup is prepared for synthetic-owner/other. ' + fix,
                                 'Doctor: 2 problems.'])

    # catches: a writer who isn't a record author passing (status.py's R4 check).
    def test_acting_login_not_a_record_author(self):
        write(self.s.fake / 'viewer.json', json.dumps({'data': {'viewer': {'login': 'synthetic-stranger'}}}))
        self.assertEqual(self.only(self.s.run()),
                         '3. Record author: synthetic-stranger is not a record author (synthetic-factory[bot], '
                         'synthetic-owner). Fix: gh auth login, as one of them')

    # catches: an unnamed acting login read as an author.
    def test_acting_login_unreadable(self):
        (self.s.fake / 'viewer.json').unlink()
        self.assertEqual(self.only(self.s.run()),
                         '3. Record author: gh could not name the acting login. Fix: gh auth login')

    # catches: a harness the setup check refused passing as signed in.
    def test_harness_not_signed_in(self):
        self.s.observations['harness'] = 'harness_unavailable'
        self.s.save()
        self.assertEqual(self.only(self.s.run()),
                         '4. Harness: not verified (harness_unavailable). Fix: sign in to syn-harness in CloudRoom, '
                         'then python3 -I -B %s/runtime/setup/setup.py check --state-dir %s'
                         % (self.s.build, self.s.state))

    # catches: a driver that refuses version passing (the driver kit's version check).
    def test_driver_does_not_answer_version(self):
        write(self.s.driver, BAD_DRIVER, 0o755)
        self.assertEqual(self.only(self.s.run()),
                         '5. Driver: %s does not answer version: synthetic driver refuses version. '
                         'Fix: git -C %s pull --ff-only, then the doctor again' % (self.s.driver, self.s.openwiz))

    # catches: a build whose packaged skills are gone passing (setup.py's runtime_pin).
    def test_skills_not_installed(self):
        (self.s.build / 'runtime/skills/grill/SKILL.md').unlink()
        self.assertEqual(self.only(self.s.run()),
                         '6. Skills: the build at %s is missing its skills. Fix: python3 -I %s/tools/install/'
                         'install install --assets <download folder> --target <target> --root <root>'
                         % (self.s.build, self.s.openwiz))

    # catches: problems printed out of order, or the first one hiding the rest.
    def test_every_problem_in_order(self):
        write(self.s.fake / 'labels.json', json.dumps([{'name': l} for l in LABELS if l != 'needs-info']))
        self.s.observations = {'github_app': 'app_missing', 'harness': 'harness_unavailable'}
        self.s.save()
        write(self.s.fake / 'viewer.json', json.dumps({'data': {'viewer': {'login': 'synthetic-stranger'}}}))
        write(self.s.driver, BAD_DRIVER, 0o755)
        (self.s.build / 'runtime/skills/grill/SKILL.md').unlink()
        lines = self.lines(self.s.run())
        self.assertEqual([l.split('.')[0] for l in lines], ['1', '2', '3', '4', '5', '6', 'Doctor: 6 problems'])

    # catches: the doctor signing in, minting a token or writing anything through gh.
    def test_gh_is_only_read(self):
        write(self.s.fake / 'viewer.json', json.dumps({'data': {'viewer': {'login': 'synthetic-stranger'}}}))
        self.s.run()
        calls = self.s.gh_calls()
        self.assertTrue(calls)
        for argv in calls:
            self.assertNotIn('auth', argv)
            self.assertNotIn('token', ' '.join(argv))
            if argv[0] == 'api':
                self.assertEqual(argv[argv.index('--method') + 1], 'POST' if 'graphql' in argv else 'GET', argv)
            else:
                self.assertEqual(argv[:2], ['label', 'list'])

    # catches: a doctor run that changes the setup store it reads.
    def test_setup_store_is_unchanged(self):
        before = (self.s.state / 'setup/state.json').read_bytes()
        self.s.run()
        self.assertEqual((self.s.state / 'setup/state.json').read_bytes(), before)
        self.assertEqual(sorted(p.name for p in (self.s.state / 'setup').iterdir()), ['state.json'])


if __name__ == '__main__':
    unittest.main()
