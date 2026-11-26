#!/usr/bin/env python3
"""The setup doctor (#1449) on a synthetic setup: each planted problem prints
its own line and fixing command, in the doctor's order; a clean setup prints
one all-clear line; no login or token passes through it.

The fakes stand in only for what lives outside WizSkills: gh, the installed
build's setup.py (its runtime_pin) and the OpenWiz checkout's driver kit (its
Kit.version). The doctor's own reuse of settings.py, status.py and the setup
store's codes runs for real.
"""
import argparse
import json
import os
from pathlib import Path
import shlex
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
if __name__ == '__main__':  # a printed command's argv, as setup.py would get it
    import json, os, sys
    open(os.path.join(os.environ['FAKE_DIR'], 'setup.log'), 'w').write(json.dumps(sys.argv[1:]))
'''

# The checkout's driver kit: Kit(args, ticket).version() -> ('pass'|'fail', what), as kit.py's.
# Like kit.py's call(), it adds to Kit.leaks when the driver's output holds a credential shape.
# Like kit.py, it runs the driver with Kit.env, which starts as a copy of the kit's whole environment.
FAKE_KIT = r'''import json, os, re, subprocess
class Kit:
    def __init__(self, args, ticket):
        self.args, self.leaks = args, []
        self.env = dict(os.environ, OPENWIZ_KIT_RUN='synthetic')
    def version(self):
        try:
            p = subprocess.run([self.args.driver, 'version'], capture_output=True, text=True, timeout=30,
                               env=self.env)
            if re.search(r'gh[pousr]_[A-Za-z0-9]{20,}', p.stdout + p.stderr):
                self.leaks.append('the driver printed a credential')
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
LEAK = 'ghp_' + 'L' * 36  # a credential shape only the driver knows, never the doctor's environment
LEAKY_DRIVER = '#!/bin/sh\necho \'{"error": "synthetic refusal %s"}\'\nexit 1\n' % LEAK
V2_DRIVER = ('#!/bin/sh\necho \'{"driver": "synthetic", "records": ["openwiz:records v2"], '
             '"can": ["start", "wake", "stop"]}\'\n')


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
                        'model': 'syn-model', 'effort': 'high', 'operator': 'synthetic-owner',
                        'service_issue': 7, 'answer_thread': 'syn-thread', 'runtime': None}
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


def prepare_step(setup):
    """The fix that sends the person to the install skill's Prepare step."""
    return ("Fix: prepare setup for %s with the install skill's Prepare step (2. Connect; it asks for the CloudRoom "
            'project, operator, service issue, answer thread, harness, model and effort), then python3 -I -B '
            '%s/runtime/setup/setup.py check --state-dir %s' % (REPO, setup.build, setup.state))


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
                         '2. GitHub App: not verified (app_missing). Fix: set up OpenWiz\'s GitHub App for %s with '
                         '%s/runtime/github-app/setup.py, as the setup skill\'s "The App" says, then '
                         'python3 -I -B %s/runtime/setup/setup.py check --state-dir %s'
                         % (REPO, self.s.build, self.s.build, self.s.state))

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

    # catches: setup prepared for another repository read as this one's evidence, or a prepare fix
    # missing a flag setup.py prepare requires (it exits 2 as printed; #1578 item 4).
    def test_setup_for_another_repository(self):
        self.s.project['repository'] = 'synthetic-owner/other'
        self.s.save()
        lines = self.lines(self.s.run())
        fix = ('Fix: python3 -I -B %s/runtime/setup/setup.py prepare --state-dir=%s --repository=%s '
               '--project=syn-project --operator=synthetic-owner --service-issue=7 --answer-thread=syn-thread '
               '--harness=syn-harness --model=syn-model --effort=high (a preview: change what differs for %s, '
               'confirm it with --yes --operation, then python3 -I -B %s/runtime/setup/setup.py check --state-dir %s)'
               % (self.s.build, self.s.state, REPO, REPO, self.s.build, self.s.state))
        self.assertEqual(lines, ['2. GitHub App: setup is prepared for synthetic-owner/other. ' + fix,
                                 '4. Harness: setup is prepared for synthetic-owner/other. ' + fix,
                                 'Doctor: 2 problems.'])

    # catches: a saved prepare value a shell splits or expands: run the fix through sh, read setup.py's argv.
    def test_printed_prepare_fix_runs_as_printed(self):
        self.s.project.update(repository='synthetic-owner/other', operator="Syn Owner $HOME 'x'")
        self.s.save()
        fix = self.lines(self.s.run())[0].split('. Fix: ', 1)[1].split(' (a preview', 1)[0]
        env = {'PATH': '/usr/bin:/bin', 'FAKE_DIR': str(self.s.fake), 'HOME': 'expanded'}
        subprocess.run(['sh', '-c', fix.replace('python3', sys.executable, 1)], env=env, capture_output=True)
        self.assertEqual(json.loads((self.s.fake / 'setup.log').read_text()),
                         ['prepare', '--state-dir=%s' % self.s.state, '--repository=' + REPO, '--project=syn-project',
                          "--operator=Syn Owner $HOME 'x'", '--service-issue=7', '--answer-thread=syn-thread',
                          '--harness=syn-harness', '--model=syn-model', '--effort=high'])

    # catches: a saved value starting with a dash read by argparse as an option, so the printed preview
    # exits 2 (#65 R2). The parser has setup.py prepare's required flags.
    def test_dash_leading_saved_value_stays_bound_to_its_flag(self):
        self.s.project.update(repository='synthetic-owner/other', operator='-alex')
        self.s.save()
        fix = self.lines(self.s.run())[0].split('. Fix: ', 1)[1].split(' (a preview', 1)[0]
        parser = argparse.ArgumentParser()
        for flag in ('--state-dir', '--repository', '--project', '--operator', '--answer-thread', '--harness',
                     '--model', '--effort'):
            parser.add_argument(flag, required=True)
        parser.add_argument('--service-issue', type=int, required=True)
        self.assertEqual(parser.parse_args(shlex.split(fix)[5:]).operator, '-alex')

    # catches: a credential-shaped saved value repeated in the printed preview (#65 R3).
    def test_credential_shaped_saved_value_is_never_printed(self):
        fix = prepare_step(self.s)
        for value in (LEAK, 'synthetic token=abcdefgh12', 'Q7x' * 10):
            self.s.project.update(repository='synthetic-owner/other', operator=value)
            self.s.save()
            result = self.s.run()
            self.assertNotIn(value, result.stdout + result.stderr)
            self.assertEqual(self.lines(result),
                             ['2. GitHub App: setup is prepared for synthetic-owner/other. ' + fix,
                              '4. Harness: setup is prepared for synthetic-owner/other. ' + fix, 'Doctor: 2 problems.'])

    # catches: a prepare fix with "..." for the values setup asks the person (it exits 2 as printed; #1578 item 4).
    def test_no_prepared_project_names_the_prepare_step(self):
        self.s.project = None
        self.s.save()
        lines = self.lines(self.s.run())
        fix = prepare_step(self.s)
        self.assertEqual(lines, ['2. GitHub App: setup has no prepared project. ' + fix,
                                 '4. Harness: setup has no prepared project. ' + fix, 'Doctor: 2 problems.'])

    # catches: the credential guard refusing an ordinary long setting, so a normal project loses its preview.
    def test_long_ordinary_setting_still_gets_the_preview(self):
        self.s.project.update(repository='synthetic-owner/other', model='syn-model-2026-11-20-long-name',
                              project='SYNPROJECT0123456789ABCDEFGH')
        self.s.save()
        self.assertIn(' --model=syn-model-2026-11-20-long-name ', self.lines(self.s.run())[0])

    # catches: a credential-shaped saved setting repeated on the harness line (#65 R3, same cause).
    def test_credential_shaped_setting_is_not_named_on_the_harness_line(self):
        self.s.project['model'] = LEAK
        self.s.observations['harness'] = 'harness_unavailable'
        self.s.save()
        line = self.only(self.s.run())
        self.assertNotIn(LEAK, line)
        self.assertTrue(line.startswith('4. Harness: the saved harness, model or effort is not offered '
                                        '(harness_unavailable). Fix: '), line)

    # catches: a first run with no state file told only to check, which can't select a project (#65 R1).
    def test_setup_not_run_yet_names_the_prepare_step(self):
        (self.s.state / 'setup/state.json').unlink()
        lines = self.lines(self.s.run())
        fix = prepare_step(self.s)
        self.assertEqual(lines, ['2. GitHub App: setup has not run yet. ' + fix,
                                 '4. Harness: setup has not run yet. ' + fix, 'Doctor: 2 problems.'])

    # catches: an App installed on all repositories told to install the App (#1578 item 2).
    def test_app_on_all_repositories_is_told_to_select_repositories(self):
        self.s.observations['github_app'] = 'app_all_repositories'
        self.s.save()
        self.assertEqual(self.only(self.s.run()),
                         "2. GitHub App: not verified (app_all_repositories). Fix: switch OpenWiz's GitHub App "
                         'installation on synthetic-owner to Only select repositories, including %s (Settings > '
                         'Applications > Installed GitHub Apps > Configure, or the organization\'s Settings > GitHub '
                         'Apps), then python3 -I -B %s/runtime/setup/setup.py check --state-dir %s'
                         % (REPO, self.s.build, self.s.state))

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

    # catches: a saved harness, model or effort that isn't offered passing, or told to sign in,
    # which leaves the selection in place (#1578 item 3).
    def test_harness_selection_not_offered(self):
        self.s.observations['harness'] = 'harness_unavailable'
        self.s.save()
        self.assertEqual(self.only(self.s.run()),
                         '4. Harness: syn-harness, syn-model, high effort is not offered (harness_unavailable). '
                         'Fix: choose a harness, model and effort that openwiz models --json offers and prepare setup '
                         "again with them (the install skill's Prepare step, 2. Connect), then python3 -I -B "
                         '%s/runtime/setup/setup.py check --state-dir %s' % (self.s.build, self.s.state))

    # catches: a driver that refuses version passing, or an unflagged refusal withheld (the driver
    # kit's version check); a separate driver is updated or replaced, not the checkout (#1578 item 5).
    def test_driver_does_not_answer_version(self):
        write(self.s.driver, BAD_DRIVER, 0o755)
        self.assertEqual(self.only(self.s.run()),
                         '5. Driver: %s does not answer version: synthetic driver refuses version. '
                         'Fix: update or replace the driver at %s so it answers version for this OpenWiz, '
                         'then the doctor again' % (self.s.driver, self.s.driver))

    # catches: the doctor's tokens reaching the driver it probes (#65 R4): this driver answers only when
    # neither the doctor's GH_TOKEN nor its FAKE_DIR is in its environment.
    def test_driver_gets_no_doctor_environment(self):
        write(self.s.driver, '#!/bin/sh\nif [ -n "$GH_TOKEN$FAKE_DIR" ]; then echo \'{"error": "synthetic: '
              'inherited"}\'; exit 1; fi\n' + GOOD_DRIVER.split('\n', 1)[1], 0o755)
        self.assertEqual(self.lines(self.s.run(), 0)[0][:19], 'Doctor: all clear: ')

    # catches: a separate driver advertising only openwiz:records v2 told to pull OpenWiz (#1578 item 5).
    def test_separate_incompatible_driver_is_told_to_update_that_driver(self):
        write(self.s.driver, V2_DRIVER, 0o755)
        self.assertEqual(self.only(self.s.run()),
                         '5. Driver: %s does not answer version: it names no openwiz:records v1. '
                         'Fix: update or replace the driver at %s so it answers version for this OpenWiz, '
                         'then the doctor again' % (self.s.driver, self.s.driver))

    # catches: the checkout's own driver told to do anything but update the checkout.
    def test_checkout_driver_is_told_to_pull_openwiz(self):
        self.s.driver = self.s.openwiz / 'adapters/driver'
        write(self.s.driver, V2_DRIVER, 0o755)
        self.assertEqual(self.only(self.s.run()),
                         '5. Driver: %s does not answer version: it names no openwiz:records v1. '
                         'Fix: git -C %s pull --ff-only, then the doctor again' % (self.s.driver, self.s.openwiz))

    # catches: a driver that answers version but prints a credential passing as clear (#1578 item 1).
    def test_flagged_driver_answer_is_reported_and_withheld(self):
        write(self.s.driver, GOOD_DRIVER.replace("echo '", "echo %s >&2\necho '" % LEAK, 1), 0o755)
        result = self.s.run()
        self.assertNotIn(LEAK, result.stdout + result.stderr)
        self.assertEqual(self.only(result),
                         "5. Driver: %s's version answer may hold a credential (the driver kit flags it), so the "
                         'doctor withholds it. Fix: run %s version in your own terminal, not through an agent, to '
                         'read it; then update or replace the driver at %s so it answers version for this OpenWiz, '
                         'then the doctor again' % (self.s.driver, self.s.driver, self.s.driver))

    # catches: a driver refusal the kit flags as holding a credential printed for the agent to relay
    # (#1578 item 1).
    def test_flagged_driver_refusal_is_withheld(self):
        write(self.s.driver, LEAKY_DRIVER, 0o755)
        result = self.s.run()
        self.assertNotIn(LEAK, result.stdout + result.stderr)
        self.assertEqual(self.only(result),
                         "5. Driver: %s's version answer may hold a credential (the driver kit flags it), so the "
                         'doctor withholds it. Fix: run %s version in your own terminal, not '
                         'through an agent, to read it; then update or replace the driver at %s so it answers version '
                         'for this OpenWiz, then the doctor again' % (self.s.driver, self.s.driver, self.s.driver))

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


SKILL = DOCTOR.parents[1] / 'SKILL.md'

# The install skill's commands (#2139): every packaged tool the skill names, with its subcommand and long
# flags, against what OpenWiz 0.1.0's own --help prints. PACKAGE_TEXT is that published inventory, the
# same bytes as fixtures/openwiz-0.1.0-commands.json, read from the published package. A step naming a
# command the package lacks stops a stranger's install there.
PINNED_COMMIT = '350887bbc00ca8e11ee6f084e4936b4fabf852fa'  # pinned WizSkills commit for 0.1.0 installs
PINNED_TREE = '66899e4ffd5c7ca78d53115cbdbcdc69671a655f'  # expected HEAD:skills/install tree OID
PACKAGE_TEXT = '''{
 "about": "Every command and flag OpenWiz 0.1.0 ships for the install skill, read from each tool's --help in the published package (releases/download/v0.1.0/openwiz-0.1.0-x86_64-unknown-linux-gnu.tar.gz, sha256 47bd514066b409783dc8ecb56f0f1f9f9afc5715fa293c2be536e53c624a7228, source 2abcd5f532c5c2a080a1b876e27dec2b9e7d29ab) and the v0.1.0 tag's tools/install/install. Keys are tool paths, then subcommands ('' for none), then their long flags, --help left out. openwiz's flags come from `openwiz help`; --build-identity from running it. Update only by reading a new release's --help. cloudroom_codes: every code runtime/cloudroom/cloudroom.py prints, from its source. skills: the 18 skills `install skills` copied, from its output. installed_install_skill_version: the `version:` of runtime/skills/install/SKILL.md, the copy `install skills` puts in each agent.",
 "version": "0.1.0",
 "tools": {
  "tools/install/install": {
   "preflight": [],
   "download": [
    "--dir",
    "--target"
   ],
   "install": [
    "--assets",
    "--root",
    "--state-root",
    "--target"
   ],
   "status": [
    "--root",
    "--state-root"
   ],
   "skills": [
    "--root",
    "--state-root"
   ]
  },
  "runtime/setup/setup.py": {
   "prepare": [
    "--answer-thread",
    "--effort",
    "--harness",
    "--model",
    "--operation",
    "--operator",
    "--project",
    "--repository",
    "--runtime",
    "--service-issue",
    "--state-dir",
    "--yes"
   ],
   "check": [
    "--api-base",
    "--openwiz",
    "--runtime",
    "--state-dir"
   ]
  },
  "runtime/setup/github_login.py": {
   "status": [
    "--repository",
    "--state-dir"
   ],
   "sign-in": [
    "--repository",
    "--state-dir",
    "--yes"
   ],
   "skip-app": [
    "--operation",
    "--state-dir",
    "--yes"
   ]
  },
  "runtime/cloudroom/cloudroom.py": {
   "status": [
    "--state-dir"
   ],
   "install": [
    "--no",
    "--operation",
    "--state-dir",
    "--yes"
   ],
   "sign-in": [
    "--state-dir"
   ]
  },
  "runtime/access/access.py": {
   "configure": [
    "--operation",
    "--plan",
    "--secrets",
    "--state-dir",
    "--yes"
   ],
   "reconcile": [
    "--operation",
    "--plan",
    "--revision",
    "--secrets",
    "--state-dir",
    "--yes"
   ],
   "status": [
    "--operation",
    "--state-dir"
   ]
  },
  "runtime/github-app/setup.py": {
   "": [
    "--after-uncertain",
    "--agent-for",
    "--api-base",
    "--capability",
    "--factory",
    "--operation",
    "--organization",
    "--port",
    "--repo",
    "--secret-store",
    "--state-dir",
    "--yes"
   ]
  },
  "openwiz": {
   "": [
    "--build-identity"
   ],
   "ls": [
    "--hidden",
    "--json",
    "--limit",
    "--offset"
   ],
   "show": [
    "--json"
   ],
   "models": [
    "--json"
   ],
   "fleets": [
    "--json"
   ],
   "fleet": [
    "--dry-run",
    "--github-only",
    "--json"
   ],
   "loop": [
    "--adopt",
    "--catalog",
    "--from",
    "--json",
    "--out",
    "--project"
   ],
   "init": [
    "--json",
    "--operation",
    "--repository",
    "--state-dir",
    "--yes"
   ],
   "github": [
    "--read",
    "--repository"
   ],
   "help": [
    "--agent"
   ]
  }
 },
 "cloudroom_codes": [
  "cloudroom_checksum_mismatch",
  "cloudroom_destination_blocked",
  "cloudroom_install_declined",
  "cloudroom_install_failed",
  "cloudroom_install_uncertain",
  "cloudroom_installed",
  "cloudroom_installing",
  "cloudroom_login_missing",
  "cloudroom_login_unknown",
  "cloudroom_login_verified",
  "cloudroom_not_installed",
  "cloudroom_reused",
  "cloudroom_source_unchecked",
  "cloudroom_unsupported"
 ],
 "skills": [
  "ask-wiz",
  "build-ticket",
  "diagnose",
  "grill",
  "handoff",
  "hill-climb",
  "huntr",
  "image",
  "install",
  "launch-fleet",
  "research",
  "review-ticket",
  "setup",
  "to-spec",
  "to-tickets",
  "triage",
  "wayfind",
  "where-are-we"
 ],
 "installed_install_skill_version": "0.2.0"
}
'''
# The bare names the skill's prose uses, by the tool each one means.
BARE = {'install': 'tools/install/install', 'setup.py': 'runtime/setup/setup.py',
        'github_login.py': 'runtime/setup/github_login.py', 'cloudroom.py': 'runtime/cloudroom/cloudroom.py',
        'access.py': 'runtime/access/access.py', 'openwiz': 'openwiz'}


def skill_commands(text):
    """(tool, subcommand, long flags, the command's text) for each command in the skill's code: each
    fenced line and inline span whose first word, after `python3` and its options, names a packaged tool."""
    import re
    spans = []
    for match in re.finditer(r'```[a-z]*\n(.*?)```|`([^`\n]+)`', text, re.S):
        spans += match[1].split('\n') if match[1] is not None else [match[2]]
    found = []
    for span in spans:
        words = [w.strip('"\'[]') for w in span.split()]
        while words and (words[0] == 'python3' or words[0].startswith('-') or '=' in words[0]):
            words.pop(0)
        if not words or words[0].startswith('$') and '/' not in words[0]:
            continue
        head = words[0].replace('"$openwiz"', '').replace('$openwiz', '')
        tool = next((t for t in BARE.values() if t != 'openwiz' and head.endswith(t)), None)
        if tool is None and (head in BARE or head.endswith('/openwiz')):
            tool = BARE.get(head, 'openwiz')
        if tool is None:
            continue
        rest = words[1:]
        sub = rest[0] if rest and not rest[0].startswith('-') and not rest[0].startswith('<') else ''
        flags = sorted({w.split('=')[0].rstrip('.,;:)') for w in rest if w.startswith('--')} - {'--help'})
        if sub or flags:  # a bare tool name is a mention, not a command
            found.append((tool, sub, flags, span))
    return found


class SkillCommandsMatchPackage(unittest.TestCase):
    """Each command the install skill names exists in OpenWiz 0.1.0, with flags its --help lists."""

    @classmethod
    def setUpClass(cls):
        cls.package = json.loads(PACKAGE_TEXT)['tools']
        cls.commands = skill_commands(SKILL.read_text())

    # catches: a step naming a subcommand 0.1.0 removed (`install open`), or a flag it never had.
    def test_every_named_command_is_in_the_package(self):
        wrong = []
        for tool, sub, flags, span in self.commands:
            subs = self.package[tool]
            if sub not in subs:
                wrong.append('%s: no `%s` in 0.1.0 (%s)' % (span, sub, ', '.join(s or '(none)' for s in subs)))
                continue
            wrong += ['%s: 0.1.0 has no %s' % (span, f) for f in flags if f not in subs[sub]]
        self.assertEqual(wrong, [])

    # catches: an install that never puts the skills in the user's agent, never proves its build, or
    # never reads setup and CloudRoom: the steps a stranger's install stalled without.
    def test_the_install_path_names_its_steps(self):
        named = {(tool, sub) for tool, sub, _, _ in self.commands}
        for step in [('tools/install/install', 'preflight'), ('tools/install/install', 'download'),
                     ('tools/install/install', 'install'), ('tools/install/install', 'skills'),
                     ('tools/install/install', 'status'), ('runtime/setup/setup.py', 'check'),
                     ('runtime/setup/setup.py', 'prepare'), ('runtime/cloudroom/cloudroom.py', 'status'),
                     ('runtime/cloudroom/cloudroom.py', 'install'), ('runtime/cloudroom/cloudroom.py', 'sign-in'),
                     ('runtime/setup/github_login.py', 'sign-in'), ('openwiz', '')]:
            self.assertIn(step, named)
        self.assertTrue(any(t == 'openwiz' and s == '' and '--build-identity' in f
                            for t, s, f, _ in self.commands), 'no `<root>/current/openwiz --build-identity`')

    # catches: the skills copied, and the restart that loads them, before the logins and setup's check
    # (#2139): the restarted agent then loads the 0.1.0 package's older install skill mid-install.
    def test_skills_and_the_restart_come_after_setup_and_the_logins(self):
        order = [(tool, sub) for tool, sub, _, _ in self.commands]
        skills = order.index(('tools/install/install', 'skills'))
        for step in [('runtime/setup/setup.py', 'check'), ('runtime/cloudroom/cloudroom.py', 'sign-in'),
                     ('runtime/setup/github_login.py', 'sign-in')]:
            self.assertLess(order.index(step), skills, step)
        text = SKILL.read_text()
        self.assertIn('is older than this one; if you are told to install again, follow this skill', text)
        self.assertIn('https://github.com/openwizdev/WizSkills/blob/%s/skills/install/SKILL.md' % PINNED_COMMIT, text)

    # catches: a CloudRoom code 0.1.0 prints with no row, so the agent improvises its next step.
    def test_every_cloudroom_code_has_a_row(self):
        rows = {code for line in SKILL.read_text().split('\n') if line.startswith('| `cloudroom_')
                for code in __import__('re').findall(r'`(cloudroom_[a-z_]+)`', line.split(' | ')[0])}
        self.assertEqual(sorted(set(json.loads(PACKAGE_TEXT)['cloudroom_codes']) - rows), [])

    # catches: a removal that deletes <root> or <state> whole (the user's own files go with it), or
    # leaves the agent guessing which skill folders are OpenWiz's.
    def test_removal_names_each_entry_and_never_deletes_a_folder_whole(self):
        text = SKILL.read_text()
        removal = text[text.index('## Recovery and removal'):]
        for name in json.loads(PACKAGE_TEXT)['skills']:
            self.assertIn('`%s`' % name, removal)
        for entry in ('`current`', '`channel.json`', '`install.lock`', '`skills/`', '/setup/`', '/cloudroom/`',
                      '`config.json`', '`app/`', '`state.json`', '`loops/`', '`clone/`', 'ls -A', 'rmdir'):
            self.assertIn(entry, removal)
        self.assertNotRegex(removal, r'(?i)\bdelete `<root>`|rm -rf')

    # catches: a restart, whatever the user says, loading the package's older install skill (#2139,
    # rehearsal 3): step 4 must overwrite each installed copy with this skill and check it by content,
    # and this skill's version must differ from the package's, so the check can tell them apart.
    def test_step_4_overwrites_the_installed_copy_and_checks_it_by_content(self):
        import re
        text = SKILL.read_text()
        mine = re.search(r'^version: (\S+)$', text, re.M)[1]
        self.assertNotEqual(mine, json.loads(PACKAGE_TEXT)['installed_install_skill_version'])
        step4 = text[text.index('## 4. '):text.index('## 5. ')]
        self.assertNotIn('maint/0.2', text)
        for pinned in ('expected_commit=%s' % PINNED_COMMIT,
                       'expected_tree=%s' % PINNED_TREE,
                       'git -C "$wizskills" fetch -q --depth 1 https://github.com/openwizdev/WizSkills "$expected_commit"',
                       'git -C "$wizskills" rev-parse HEAD',
                       'git -C "$wizskills" rev-parse HEAD:skills/install',
                       'SOURCE MISMATCH'):
            self.assertIn(pinned, step4)
        self.assertLess(step4.index('SOURCE MISMATCH'), step4.index('cp -R "$src"/. "$d/install/"'))
        for home in ('.claude/skills', '.codex/skills', 'CODEX_HOME'):
            self.assertIn(home, step4)
        for words in ("'install ope[n] '", "'from the setup pag[e]'", "'Restart the OpenWiz serve[r]'",
                      'cp -R "$src"/. "$d/install/"', 'cmp -s', 'version: %s' % mine):
            self.assertIn(words, step4)
        self.assertIn('"continue the OpenWiz install"', step4)
        self.assertNotIn('any words do', text)

    # catches: a resumed session reaching for the temporary clone, which the restart lost, or a fixed
    # resume point that skips an unfinished sign-in (#2139, rehearsal 3).
    def test_a_new_session_resumes_from_installed_files_at_the_first_unfinished_step(self):
        text = SKILL.read_text()
        self.assertIn('\n## Resume', text)
        resume = text[text.index('## Resume'):text.index('## 1. ')]
        for words in ('first unfinished step', 'readlink <root>/current', '--build-identity', 'setup.py check',
                      'version: ', 'OPENWIZ_STATE_DIR="$state"', 'identity_unreadable'):
            self.assertIn(words, resume)
        self.assertIn('operation_id', text)
        after = text[text.index('## 5. '):text.index('## Recovery and removal')]
        self.assertNotIn('$openwiz', resume + after)
        self.assertNotRegex(text, r'\]\(\.\./\.\./contracts/')

    def parts(self):
        text = SKILL.read_text()
        return (text, text[text.index('## 4. '):text.index('## 5. ')], text[text.index('## Resume'):text.index('## 1. ')],
                text[text.index('## Recovery and removal'):])

    # catches: review R1 at ac29982: with CODEX_HOME set, 0.1.0 copies Codex's skills to
    # $CODEX_HOME/skills, so a check of ~/.codex/skills looks in an unused folder.
    def test_the_codex_folder_follows_codex_home(self):
        text, step4, resume, removal = self.parts()
        for part in (step4, resume, removal):
            self.assertIn('${CODEX_HOME:-$HOME/.codex}/skills', part)
        self.assertNotIn('never `$CODEX_HOME`', text)

    # catches: review R2 at c4bd867: a removal that deletes a skill folder itself, even one whose
    # ownership marker the real installer refuses as invalid. Removal only lists the folders, and the
    # person removes the ones they recognise as OpenWiz's.
    def test_removal_lists_skill_folders_and_deletes_none(self):
        import re
        removal = self.parts()[3]
        blocks = re.findall(r'```sh\n(.*?)```', '\n'.join(l[3:] if l.startswith('   ') else l
                                                          for l in removal.split('\n')), re.S)
        self.assertTrue(blocks)
        with tempfile.TemporaryDirectory() as home:
            for skills in ('.claude/skills', 'codex-home/skills'):
                for name in ('install', 'research'):
                    folder = Path(home) / skills / name
                    folder.mkdir(parents=True)
                    (folder / 'SKILL.md').write_text('# synthetic\n')
                (Path(home) / skills / 'install/.openwiz-skill').write_text('not a valid receipt\n')
            before = sorted(str(q.relative_to(home)) for q in Path(home).rglob('*'))
            env = {'HOME': home, 'PATH': '/usr/bin:/bin', 'CODEX_HOME': str(Path(home) / 'codex-home')}
            listed = ''.join(subprocess.run(['sh', '-c', b], env=env, capture_output=True, text=True).stdout
                             for b in blocks)
            self.assertEqual(sorted(str(q.relative_to(home)) for q in Path(home).rglob('*')), before)
        for skills in ('.claude/skills', 'codex-home/skills'):
            for name in ('install', 'research'):
                self.assertIn('%s/%s/%s' % (home, skills, name), listed)
        self.assertIn('recognise as OpenWiz', removal)

    # catches: review R3 at ac29982: a plain `install` never reconciles an uncertain CloudRoom install.
    def test_an_uncertain_cloudroom_install_is_retried_with_its_operation(self):
        row = next(l for l in self.parts()[0].split('\n') if l.startswith('| `cloudroom_install_uncertain`'))
        self.assertIn('cloudroom.py install --yes --operation <operation_id> --state-dir <state>', row)

    # catches: review R4 at ac29982: preflight passes with gh missing, then sign-in says login_gh_missing.
    def test_a_missing_gh_gets_its_install_step(self):
        text = self.parts()[0]
        for words in ('login_gh_missing', 'https://cli.github.com', 'gh --version'):
            self.assertIn(words, text)
        self.assertIn('even on exit 0', text[text.index('## 1. '):text.index('## 2. ')])

    # catches: a parser that finds nothing passing the check above vacuously.
    def test_the_reader_finds_a_synthetic_skill_s_commands(self):
        text = ('Run `install open --root <root> --browser` and\n\n```sh\n'
                'python3 -I "$openwiz"/tools/install/install skills --root <root>\n```\n'
                'then `<root>/current/openwiz --build-identity` and `git clone x "$openwiz"`.\n')
        self.assertEqual([c[:3] for c in skill_commands(text)],
                         [('tools/install/install', 'open', ['--browser', '--root']),
                          ('tools/install/install', 'skills', ['--root']),
                          ('openwiz', '', ['--build-identity'])])




CLASH = SKILL.parent / 'scripts/skill_clash.py'


def operation_of(clashes):
    return __import__('hashlib').sha256(json.dumps(clashes, sort_keys=True).encode()).hexdigest()[:16]


QUESTION = ('You already have your own skills named grill, handoff and research. handoff-mine is already taken, '
            'so yours becomes handoff-mine-2. Rename yours to grill-mine, handoff-mine-2 and research-mine '
            '(and their name lines) so OpenWiz can install? They keep working under the new names. (yes/no)')


class SkillNameClash(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        self.home, self.build = root / 'home', root / 'build'
        for name in ('grill', 'handoff', 'install', 'research'):
            write(self.build / 'runtime/skills' / name / 'SKILL.md', '---\nname: %s\n---\n' % name)
        for skills, name in (('.claude/skills', 'grill'), ('.codex/skills', 'handoff'),
                             ('.codex/skills', 'research'), ('.codex/skills', 'handoff-mine')):
            write(self.home / skills / name / 'SKILL.md',
                  '---\nname: %s\ndescription: synthetic user skill\n---\n# Mine\n' % name)
            write(self.home / skills / name / 'notes.txt', 'synthetic\n')
        ours = self.home / '.codex/skills/install'
        write(ours / 'SKILL.md', '---\nname: install\n---\n')
        write(ours / '.openwiz-skill', 'openwiz.skill-copy.v1\n%s\n' % ('a' * 40))

    def tearDown(self):
        self.dir.cleanup()

    def run_clash(self, *args):
        env = {'HOME': str(self.home), 'PATH': '/usr/bin:/bin'}
        self.assertTrue(CLASH.is_file(), 'missing skill_clash.py')
        return subprocess.run([sys.executable, '-I', str(CLASH), *args, '--build', str(self.build),
                               '--root', str(self.home / '.local/lib/openwiz')],
                              env=env, capture_output=True, text=True)

    def tree(self):
        return sorted((str(p.relative_to(self.home)), p.read_text() if p.is_file() else '')
                      for p in self.home.rglob('*'))

    def test_list_names_every_clash_asks_the_one_question_and_moves_nothing(self):
        before = self.tree()
        done = self.run_clash('list')
        self.assertEqual(done.returncode, 0, done.stderr)
        out = json.loads(done.stdout)
        self.assertEqual([(c['path'][len(str(self.home)) + 1:], c['rename_to']) for c in out['clashes']],
                         [('.claude/skills/grill', 'grill-mine'), ('.codex/skills/handoff', 'handoff-mine-2'),
                          ('.codex/skills/research', 'research-mine')])
        self.assertEqual(out['question'], QUESTION)
        self.assertEqual(self.tree(), before)

    def test_no_yes_or_another_plan_moves_nothing(self):
        before = self.tree()
        self.assertEqual(self.run_clash('rename').returncode, 2)
        self.assertEqual(self.run_clash('rename', '--yes', '--operation', '0' * 16).returncode, 5)
        self.assertEqual(self.tree(), before)

    def test_yes_moves_each_folder_and_its_name_line_and_checks_it(self):
        op = json.loads(self.run_clash('list').stdout)['operation']
        done = self.run_clash('rename', '--yes', '--operation', op)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual([r['result'] for r in json.loads(done.stdout)['renamed']], ['moved'] * 3)
        for skills, old, new in (('.claude/skills', 'grill', 'grill-mine'),
                                 ('.codex/skills', 'handoff', 'handoff-mine-2'),
                                 ('.codex/skills', 'research', 'research-mine')):
            self.assertFalse((self.home / skills / old).exists())
            self.assertEqual((self.home / skills / new / 'SKILL.md').read_text(),
                             '---\nname: %s\ndescription: synthetic user skill\n---\n# Mine\n' % new)
            self.assertEqual((self.home / skills / new / 'notes.txt').read_text(), 'synthetic\n')
        self.assertEqual((self.home / '.codex/skills/handoff-mine/SKILL.md').read_text().split('\n')[1],
                         'name: handoff-mine')
        self.assertEqual((self.home / '.codex/skills/install/SKILL.md').read_text(), '---\nname: install\n---\n')
        out = json.loads(self.run_clash('list').stdout)
        self.assertEqual((out['clashes'], out['question']), ([], None))

    def blocked_and_unmoved(self, why):
        before = self.tree()
        out = json.loads(self.run_clash('list').stdout)
        self.assertEqual((out['question'], out['operation']), (None, None))
        self.assertTrue(any(why in b['why'] for b in out['blocked']), out['blocked'])
        self.assertEqual(self.run_clash('rename', '--yes', '--operation', operation_of(out['clashes'])).returncode, 5)
        self.assertEqual(self.tree(), before)
        return out

    def test_a_folder_the_installer_still_refuses_blocks_every_move(self):
        dotfiles = self.home / 'dotfiles/config'
        write(dotfiles / 'opencode/skills/handoff/SKILL.md', '---\nname: handoff\n---\n')
        (self.home / '.config').symlink_to(dotfiles)
        self.blocked_and_unmoved('%s is a link or not a folder' % (self.home / '.config'))
        self.assertTrue((dotfiles / 'opencode/skills/handoff/SKILL.md').is_file())

    def test_a_linked_skill_md_is_refused_and_left_alone(self):
        target = self.home / 'dotfiles/handoff.md'
        write(target, '---\nname: handoff\n---\n')
        skill = self.home / '.codex/skills/research/SKILL.md'
        skill.unlink()
        skill.symlink_to(target)
        self.blocked_and_unmoved('SKILL.md is a link')
        self.assertTrue(skill.is_symlink())
        self.assertEqual(target.read_text(), '---\nname: handoff\n---\n')

    def test_step_4_asks_once_and_says_what_no_means(self):
        step4 = SKILL.read_text()[SKILL.read_text().index('## 4. '):SKILL.read_text().index('## 5. ')]
        for words in ('scripts/skill_clash.py list --build "$build" --root <root>',
                      'scripts/skill_clash.py rename --build "$build" --root <root> --yes --operation <operation>',
                      'there is no `question` and nothing may move',
                      'ask exactly its `question`, word for word', 'run `install skills` again',
                      "OpenWiz's skills were not installed", 'and stop', '<name>-mine-2',
                      'Never move, rename or delete a user\'s skill without that yes'):
            self.assertIn(words, step4)
        self.assertNotIn('refuses the whole step: report it.', step4)


HOST_QUESTION = ("Where should your agents run? This computer (Claude Code or Codex you're signed in to), "
                 "boat.dev, or CloudRoom.")
FINISH = ("Installed. Without CloudRoom today you can plan (grill, spec, tickets) and start a builder on this "
          "computer or on boat.dev by hand. The automatic fleet without CloudRoom arrives in 0.1.1. "
          "Want CloudRoom now instead? It's optional.")
DRIVER_START = {'repository', 'ticket', 'skill', 'harness', 'model'}


def ticket_start_record():
    """build-ticket's own pattern for the start record a builder needs before it claims (ticket.py START)."""
    import importlib.util
    path = SKILL.parents[1] / 'build-ticket/scripts/ticket.py'
    spec = importlib.util.spec_from_file_location('ticket_2221', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.START


class NoCloudRoomRequired(unittest.TestCase):
    """OpenWiz 0.1.0's install finishes with no CloudRoom; CloudRoom's steps run only when the user picks it."""

    def setUp(self):
        self.text = SKILL.read_text()

    def between(self, start, end):
        self.assertIn(start, self.text)
        self.assertIn(end, self.text)
        return self.text[self.text.index(start):self.text.index(end)]

    def test_setup_uses_the_installed_check_without_the_removed_open_command(self):
        setup = self.between('## 3. ', '## 4. ')
        self.assertNotIn('/tools/install/install open ', self.text)
        self.assertIn('/runtime/setup/setup.py check --state-dir <state>', setup)

    def test_overwrite_requires_a_ported_install_on_this_maintenance_line(self):
        step = self.between('## 4. ', '## 5. ')
        self.assertIn('git clone --depth 1 --branch maint/0.3 ', step)
        self.assertIn('fixed() ', step)
        self.assertIn('\nif fixed ', step)
        fixed = step[step.index('fixed() '):step.index('\nif fixed ')]
        with tempfile.TemporaryDirectory() as directory:
            stale = Path(directory) / 'install'
            write(stale / 'SKILL.md', '---\nversion: 0.3.0\n---\n')
            write(stale / 'scripts/doctor.py', '')
            for folder, expected in ((stale, 1), (SKILL.parent, 0)):
                with self.subTest(folder=folder):
                    done = subprocess.run(['sh', '-c', fixed + '\nfixed "$1"', 'sh', str(folder)],
                                          capture_output=True, text=True)
                    self.assertEqual(done.returncode, expected, done.stderr)

    def test_cloudroom_is_no_requirement_done_condition_or_resume_gate(self):
        self.assertFalse('needs CloudRoom.' in self.text, 'needs CloudRoom.')
        self.assertFalse('install cannot be completed here' in self.text, 'install cannot be completed here')
        step3 = self.between('## 3. ', '## 4. ')
        done = [l for l in step3.split('\n') if l.startswith('Done when')]
        self.assertEqual(len(done), 1)
        self.assertNotRegex(done[0], r'^Done when CloudRoom')
        for line in self.between('## Resume', '## 1. ').split('\n') + done:
            if 'cloudroom_' in line:
                self.assertTrue('chose CloudRoom' in line, line)
        intel = next(s for s in self.between('## 1. ', '## 2. ').split('. ') if 'Intel Mac' in s and 'stop' in s)
        self.assertTrue('chose CloudRoom' in intel, intel)

    def test_the_host_question_comes_first_and_cloudroom_runs_only_when_chosen(self):
        self.assertTrue(HOST_QUESTION in self.text, 'missing: ' + HOST_QUESTION)
        at = self.text.index(HOST_QUESTION)
        self.assertLess(at, self.text.index('cloudroom.py', self.text.index('## Resume')))
        self.assertLess(at, self.text.index('## 1. Preflight'))
        paragraph = self.text[self.text.rindex('\n\n', 0, at):self.text.index('\n\n', at)]
        self.assertFalse('recommend' in paragraph.lower(), 'the host question recommends one host')
        step3 = self.between('## 3. ', '## 4. ')
        self.assertTrue('ignore every `cloudroom_*` code' in step3, 'ignore every `cloudroom_*` code')
        self.assertLess(step3.index('ignore every `cloudroom_*` code'), step3.index('| Code | Next |'))

    def test_without_cloudroom_the_finish_says_what_works_and_gives_real_hand_starts(self):
        import re
        self.assertTrue(FINISH in self.text, 'missing: ' + FINISH)
        hand = self.between('## Without CloudRoom', '## 6. ')
        starts = [l for l in hand.split('\n') if 'driver start' in l]
        self.assertEqual(len(starts), 2, starts)
        self.assertTrue(any('"$build"/runtime/adapters/local/driver start' in l for l in starts))
        self.assertTrue(any('"$ow"/adapters/boat/driver start' in l for l in starts))
        self.assertFalse('runtime/adapters/boat/driver' in self.text, 'runtime/adapters/boat/driver')
        self.assertTrue('git clone --depth 1 --branch v0.1.0 https://github.com/openwizdev/OpenWiz "$ow"' in hand, 'git clone --depth 1 --branch v0.1.0 https://github.com/openwizdev/OpenWiz "$ow"')
        for line in starts:
            given = re.search(r"echo '(\{.*\})'", line)[1]
            given = json.loads(re.sub(r'<N>', '7', re.sub(r'"<[^>]*>"', '"x"', given)))
            self.assertEqual(set(given), DRIVER_START)
            self.assertEqual(given['skill'], 'build-ticket')
            self.assertIsInstance(given['ticket'], int)
        for words in ('approvals.json', '| Harness permission mode | `<mode>` |', 'chmod 600', 'wake', 'stop'):
            self.assertTrue(words in hand, words)
        record = re.findall(r'--body "([^"]*)"', hand)
        self.assertTrue(record and all(ticket_start_record().match(r) for r in record), record)

    def test_the_automatic_first_fleet_on_0_1_0_says_it_runs_in_cloudroom(self):
        step6 = self.between('## 6. ', '### 1. ')
        self.assertTrue('even with builders on boat.dev' in step6, 'even with builders on boat.dev')
        self.assertTrue('0.1.1' in step6, '0.1.1')
        self.assertTrue('"Without CloudRoom" above' in step6, 'no pointer to "Without CloudRoom"')


    def test_manual_plan_ends_at_the_ready_label_readback(self):
        plan = self.between('- **Plan:**', '- **Start one ticket')
        self.assertIn('read the ready labels back', plan, 'manual planning has no stopping point')
        self.assertIn('Skip the `launch-fleet` handoff and the steering video', plan)
        self.assertIn('return to the hand-start steps below', plan)

    def test_manual_plan_checks_approval_tools_before_writing(self):
        plan = self.between('- **Plan:**', '- **Start one ticket')
        preflight, _, _ = plan.partition('run `setup`')
        self.assertIn('`jq --version`', preflight, 'planning can write tickets before checking jq')
        self.assertIn('`gh --version`', preflight)
        self.assertIn('2.94 or newer', preflight)
        self.assertIn('install jq', preflight)
        self.assertIn('install or upgrade GitHub CLI', preflight)
        self.assertIn('Recheck both before continuing', preflight)

    def test_manual_start_checks_builder_readiness_on_both_sides_of_the_record(self):
        hand = self.between('- **Start one ticket', '- **Review and merge**')
        before, command, after = hand.partition('gh issue comment')
        self.assertIn('/build-ticket/scripts/ticket.py read', before,
                      'a start record can be posted for an ineligible ticket')
        self.assertIn('proceed only on exit 1 with', before)
        self.assertIn('ready: no: no launch-fleet start record from a record author', before)
        self.assertLess(before.index('gh api user --jq .login'), before.index('Post from'))
        self.assertIn('`Record authors`', before)
        self.assertTrue(command)
        gate, start, _ = after.partition('driver start')
        self.assertIn('run the same ticket read again', gate)
        self.assertIn('Only exit 0 with `ready: yes`', gate)
        self.assertTrue(start)

    def test_local_approval_updates_only_the_selected_entry(self):
        local = self.between('  - **This computer**', '  - **boat.dev**')
        approval, _, _ = local.partition('driver start')
        self.assertIn('Read the existing owner-only JSON object', approval,
                      'writing a second approval can erase the first')
        self.assertIn('Preserve every other repository and harness entry', approval)
        self.assertIn('Preview the selected repository, harness and old and new modes', approval)
        self.assertIn('If the file changed since the preview', approval)
        self.assertIn('read the saved JSON back', approval)
        self.assertNotIn('then write `{"<owner>/<name>":', approval)


if __name__ == '__main__':
    unittest.main()
