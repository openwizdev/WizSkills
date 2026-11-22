#!/usr/bin/env python3
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
LEAK = 'ghp_' + 'L' * 36
LEAKY_DRIVER = '#!/bin/sh\necho \'{"error": "synthetic refusal %s"}\'\nexit 1\n' % LEAK
V2_DRIVER = ('#!/bin/sh\necho \'{"driver": "synthetic", "records": ["openwiz:records v2"], '
             '"can": ["start", "wake", "stop"]}\'\n')


def write(path, text, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)


class Setup:

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
        lines = self.lines(result)
        self.assertEqual(lines[-1], 'Doctor: 1 problem.', result.stdout)
        self.assertEqual(len(lines), 2, result.stdout)
        return lines[0]

    def test_clean_setup_prints_one_all_clear_line(self):
        self.assertEqual(self.lines(self.s.run(), 0),
                         ['Doctor: all clear: labels, App, record author, harness listed (its sign-in is not provable yet), '
                          'driver and skills.'])

    def test_no_driver_is_said_on_the_all_clear_line(self):
        self.assertEqual(self.lines(self.s.run(driver=False), 0),
                         ['Doctor: all clear: labels, App, record author, harness listed (its sign-in is not provable yet) '
                          'and skills; no driver given.'])

    def test_missing_label(self):
        write(self.s.fake / 'labels.json', json.dumps([{'name': l} for l in LABELS if l != 'needs-info']))
        self.assertEqual(self.only(self.s.run()),
                         '1. Labels: needs-info is not in the tracker. Fix: gh label create needs-info --repo %s'
                         % REPO)

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

    def test_unmapped_label_role(self):
        write(self.s.checkout / 'docs/agents/triage-labels.md', TRIAGE.replace('| `wontfix` | `wontfix` | Synthetic |\n', ''))
        self.assertEqual(self.only(self.s.run()),
                         '1. Labels: triage-labels.md: wontfix: mapped 0 times. '
                         'Fix: run the setup skill for %s, then the doctor again' % REPO)

    def test_labels_unreadable_prints_the_sign_in_command(self):
        (self.s.fake / 'labels.json').unlink()
        self.assertEqual(self.only(self.s.run()),
                         '1. Labels: gh could not list the labels of %s. Fix: gh auth login' % REPO)

    def test_app_not_installed(self):
        self.s.observations['github_app'] = 'app_missing'
        self.s.save()
        self.assertEqual(self.only(self.s.run()),
                         '2. GitHub App: not verified (app_missing). Fix: set up OpenWiz\'s GitHub App for %s with '
                         '%s/runtime/github-app/setup.py, as the setup skill\'s "The App" says, then '
                         'python3 -I -B %s/runtime/setup/setup.py check --state-dir %s'
                         % (REPO, self.s.build, self.s.build, self.s.state))

    def test_app_check_out_of_date(self):
        self.s.save(at=int(time.time() * 1000) - 2 * 60 * 60 * 1000)
        lines = self.lines(self.s.run())
        fix = 'Fix: python3 -I -B %s/runtime/setup/setup.py check --state-dir %s' % (self.s.build, self.s.state)
        self.assertEqual(lines, ['2. GitHub App: its last check is out of date. ' + fix,
                                 '4. Harness: its last check is out of date. ' + fix, 'Doctor: 2 problems.'])

    def test_app_skip_is_not_a_problem(self):
        self.s.observations['github_app'] = 'app_missing'
        self.s.identity = {'selected': 'personal_login', 'app_choice': 'skip', 'acting_login': 'synthetic-owner',
                           'repository': REPO}
        self.s.save()
        self.assertEqual(self.s.run().returncode, 0)

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

    def test_no_prepared_project_names_the_prepare_step(self):
        self.s.project = None
        self.s.save()
        lines = self.lines(self.s.run())
        fix = prepare_step(self.s)
        self.assertEqual(lines, ['2. GitHub App: setup has no prepared project. ' + fix,
                                 '4. Harness: setup has no prepared project. ' + fix, 'Doctor: 2 problems.'])

    def test_long_ordinary_setting_still_gets_the_preview(self):
        self.s.project.update(repository='synthetic-owner/other', model='syn-model-2026-11-20-long-name',
                              project='SYNPROJECT0123456789ABCDEFGH')
        self.s.save()
        self.assertIn(' --model=syn-model-2026-11-20-long-name ', self.lines(self.s.run())[0])

    def test_credential_shaped_setting_is_not_named_on_the_harness_line(self):
        self.s.project['model'] = LEAK
        self.s.observations['harness'] = 'harness_unavailable'
        self.s.save()
        line = self.only(self.s.run())
        self.assertNotIn(LEAK, line)
        self.assertTrue(line.startswith('4. Harness: the saved harness, model or effort is not offered '
                                        '(harness_unavailable). Fix: '), line)

    def test_setup_not_run_yet_names_the_prepare_step(self):
        (self.s.state / 'setup/state.json').unlink()
        lines = self.lines(self.s.run())
        fix = prepare_step(self.s)
        self.assertEqual(lines, ['2. GitHub App: setup has not run yet. ' + fix,
                                 '4. Harness: setup has not run yet. ' + fix, 'Doctor: 2 problems.'])

    def test_app_on_all_repositories_is_told_to_select_repositories(self):
        self.s.observations['github_app'] = 'app_all_repositories'
        self.s.save()
        self.assertEqual(self.only(self.s.run()),
                         "2. GitHub App: not verified (app_all_repositories). Fix: switch OpenWiz's GitHub App "
                         'installation on synthetic-owner to Only select repositories, including %s (Settings > '
                         'Applications > Installed GitHub Apps > Configure, or the organization\'s Settings > GitHub '
                         'Apps), then python3 -I -B %s/runtime/setup/setup.py check --state-dir %s'
                         % (REPO, self.s.build, self.s.state))

    def test_acting_login_not_a_record_author(self):
        write(self.s.fake / 'viewer.json', json.dumps({'data': {'viewer': {'login': 'synthetic-stranger'}}}))
        self.assertEqual(self.only(self.s.run()),
                         '3. Record author: synthetic-stranger is not a record author (synthetic-factory[bot], '
                         'synthetic-owner). Fix: gh auth login, as one of them')

    def test_acting_login_unreadable(self):
        (self.s.fake / 'viewer.json').unlink()
        self.assertEqual(self.only(self.s.run()),
                         '3. Record author: gh could not name the acting login. Fix: gh auth login')

    def test_harness_selection_not_offered(self):
        self.s.observations['harness'] = 'harness_unavailable'
        self.s.save()
        self.assertEqual(self.only(self.s.run()),
                         '4. Harness: syn-harness, syn-model, high effort is not offered (harness_unavailable). '
                         'Fix: choose a harness, model and effort that openwiz models --json offers and prepare setup '
                         "again with them (the install skill's Prepare step, 2. Connect), then python3 -I -B "
                         '%s/runtime/setup/setup.py check --state-dir %s' % (self.s.build, self.s.state))

    def test_driver_does_not_answer_version(self):
        write(self.s.driver, BAD_DRIVER, 0o755)
        self.assertEqual(self.only(self.s.run()),
                         '5. Driver: %s does not answer version: synthetic driver refuses version. '
                         'Fix: update or replace the driver at %s so it answers version for this OpenWiz, '
                         'then the doctor again' % (self.s.driver, self.s.driver))

    def test_driver_gets_no_doctor_environment(self):
        write(self.s.driver, '#!/bin/sh\nif [ -n "$GH_TOKEN$FAKE_DIR" ]; then echo \'{"error": "synthetic: '
              'inherited"}\'; exit 1; fi\n' + GOOD_DRIVER.split('\n', 1)[1], 0o755)
        self.assertEqual(self.lines(self.s.run(), 0)[0][:19], 'Doctor: all clear: ')

    def test_separate_incompatible_driver_is_told_to_update_that_driver(self):
        write(self.s.driver, V2_DRIVER, 0o755)
        self.assertEqual(self.only(self.s.run()),
                         '5. Driver: %s does not answer version: it names no openwiz:records v1. '
                         'Fix: update or replace the driver at %s so it answers version for this OpenWiz, '
                         'then the doctor again' % (self.s.driver, self.s.driver))

    def test_checkout_driver_is_told_to_pull_openwiz(self):
        self.s.driver = self.s.openwiz / 'adapters/driver'
        write(self.s.driver, V2_DRIVER, 0o755)
        self.assertEqual(self.only(self.s.run()),
                         '5. Driver: %s does not answer version: it names no openwiz:records v1. '
                         'Fix: git -C %s pull --ff-only, then the doctor again' % (self.s.driver, self.s.openwiz))

    def test_flagged_driver_answer_is_reported_and_withheld(self):
        write(self.s.driver, GOOD_DRIVER.replace("echo '", "echo %s >&2\necho '" % LEAK, 1), 0o755)
        result = self.s.run()
        self.assertNotIn(LEAK, result.stdout + result.stderr)
        self.assertEqual(self.only(result),
                         "5. Driver: %s's version answer may hold a credential (the driver kit flags it), so the "
                         'doctor withholds it. Fix: run %s version in your own terminal, not through an agent, to '
                         'read it; then update or replace the driver at %s so it answers version for this OpenWiz, '
                         'then the doctor again' % (self.s.driver, self.s.driver, self.s.driver))

    def test_flagged_driver_refusal_is_withheld(self):
        write(self.s.driver, LEAKY_DRIVER, 0o755)
        result = self.s.run()
        self.assertNotIn(LEAK, result.stdout + result.stderr)
        self.assertEqual(self.only(result),
                         "5. Driver: %s's version answer may hold a credential (the driver kit flags it), so the "
                         'doctor withholds it. Fix: run %s version in your own terminal, not '
                         'through an agent, to read it; then update or replace the driver at %s so it answers version '
                         'for this OpenWiz, then the doctor again' % (self.s.driver, self.s.driver, self.s.driver))

    def test_skills_not_installed(self):
        (self.s.build / 'runtime/skills/grill/SKILL.md').unlink()
        self.assertEqual(self.only(self.s.run()),
                         '6. Skills: the build at %s is missing its skills. Fix: python3 -I %s/tools/install/'
                         'install install --assets <download folder> --target <target> --root <root>'
                         % (self.s.build, self.s.openwiz))

    def test_every_problem_in_order(self):
        write(self.s.fake / 'labels.json', json.dumps([{'name': l} for l in LABELS if l != 'needs-info']))
        self.s.observations = {'github_app': 'app_missing', 'harness': 'harness_unavailable'}
        self.s.save()
        write(self.s.fake / 'viewer.json', json.dumps({'data': {'viewer': {'login': 'synthetic-stranger'}}}))
        write(self.s.driver, BAD_DRIVER, 0o755)
        (self.s.build / 'runtime/skills/grill/SKILL.md').unlink()
        lines = self.lines(self.s.run())
        self.assertEqual([l.split('.')[0] for l in lines], ['1', '2', '3', '4', '5', '6', 'Doctor: 6 problems'])

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

    def test_setup_store_is_unchanged(self):
        before = (self.s.state / 'setup/state.json').read_bytes()
        self.s.run()
        self.assertEqual((self.s.state / 'setup/state.json').read_bytes(), before)
        self.assertEqual(sorted(p.name for p in (self.s.state / 'setup').iterdir()), ['state.json'])


SKILL = Path(__file__).resolve().parents[1] / 'SKILL.md'
LINE = 'main'
PACKAGE = Path(__file__).resolve().parent / 'fixtures/openwiz-0.1.0-commands.json'
BARE = {'install': 'tools/install/install', 'setup.py': 'runtime/setup/setup.py',
        'github_login.py': 'runtime/setup/github_login.py', 'cloudroom.py': 'runtime/cloudroom/cloudroom.py',
        'access.py': 'runtime/access/access.py', 'openwiz': 'openwiz'}


def skill_commands(text):
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
        if sub or flags:
            found.append((tool, sub, flags, span))
    return found


class SkillCommandsMatchPackage(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.package = dict(json.loads(PACKAGE.read_text())['tools'], **{'tools/install/install': INSTALLER_0_1_1})
        cls.commands = skill_commands(SKILL.read_text())

    def test_every_named_command_is_in_the_package(self):
        wrong = []
        for tool, sub, flags, span in self.commands:
            subs = self.package[tool]
            if sub not in subs:
                wrong.append('%s: no `%s` in 0.1.0 (%s)' % (span, sub, ', '.join(s or '(none)' for s in subs)))
                continue
            allowed = set(subs[sub])
            if (tool, sub) == ('openwiz', 'models'):
                args = span.split(' models', 1)[1].split()
                if not args or args[0].startswith('--') or args[0] in ('set', 'show'):
                    allowed.add('--host')
            wrong += ['%s: command inventory has no %s' % (span, f) for f in flags if f not in allowed]
        self.assertEqual(wrong, [])

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

    def test_skills_and_the_restart_come_after_setup_and_the_logins(self):
        order = [(tool, sub) for tool, sub, _, _ in self.commands]
        skills = order.index(('tools/install/install', 'skills'))
        for step in [('runtime/setup/setup.py', 'check'), ('runtime/cloudroom/cloudroom.py', 'sign-in'),
                     ('runtime/setup/github_login.py', 'sign-in')]:
            self.assertLess(order.index(step), skills, step)
        text = SKILL.read_text()
        self.assertIn('is older than this one; if you are told to install again, follow this skill', text)
        self.assertIn('https://github.com/openwizdev/WizSkills/blob/%s/skills/install/SKILL.md' % LINE, text)

    def test_every_cloudroom_code_has_a_row(self):
        rows = {code for line in SKILL.read_text().split('\n') if line.startswith('| `cloudroom_')
                for code in __import__('re').findall(r'`(cloudroom_[a-z_]+)`', line.split(' | ')[0])}
        self.assertEqual(sorted(set(json.loads(PACKAGE.read_text())['cloudroom_codes']) - rows), [])

    def test_removal_names_each_entry_and_never_deletes_a_folder_whole(self):
        text = SKILL.read_text()
        removal = text[text.index('## Recovery and removal'):]
        for name in json.loads(PACKAGE.read_text())['skills']:
            self.assertIn('`%s`' % name, removal)
        for entry in ('`current`', '`channel.json`', '`install.lock`', '`skills/`', '/setup/`', '/cloudroom/`',
                      '`config.json`', '`app/`', '`state.json`', '`loops/`', '`clone/`', 'ls -A', 'rmdir'):
            self.assertIn(entry, removal)
        self.assertNotRegex(removal, r'(?i)\bdelete `<root>`|rm -rf')

    def test_step_4_overwrites_the_installed_copy_and_checks_it_by_content(self):
        import re
        text = SKILL.read_text()
        mine = re.search(r'^version: (\S+)$', text, re.M)[1]
        self.assertNotEqual(mine, json.loads(PACKAGE.read_text())['installed_install_skill_version'])
        step4 = text[text.index('## 4. '):text.index('## 5. ')]
        self.assertIn('git clone --depth 1 --branch %s https://github.com/openwizdev/WizSkills' % LINE, step4)
        for home in ('.claude/skills', '.codex/skills', 'CODEX_HOME'):
            self.assertIn(home, step4)
        for words in ("'install ope[n] '", "'from the setup pag[e]'", "'Restart the OpenWiz serve[r]'",
                      'cp -R "$src"/. "$d/install/"', 'cmp -s', "want='version: <version of this skill>'"):
            self.assertIn(words, step4)
        self.assertIn('"continue the OpenWiz install"', step4)
        self.assertNotIn('any words do', text)

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

    def test_the_codex_folder_follows_codex_home(self):
        text, step4, resume, removal = self.parts()
        for part in (step4, resume, removal):
            self.assertIn('${CODEX_HOME:-$HOME/.codex}/skills', part)
        self.assertNotIn('never `$CODEX_HOME`', text)

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

    def test_an_uncertain_cloudroom_install_is_retried_with_its_operation(self):
        row = next(l for l in self.parts()[0].split('\n') if l.startswith('| `cloudroom_install_uncertain`'))
        self.assertIn('cloudroom.py install --yes --operation <operation_id> --state-dir <state>', row)

    def test_a_missing_gh_gets_its_install_step(self):
        text = self.parts()[0]
        for words in ('login_gh_missing', 'https://cli.github.com', 'gh --version'):
            self.assertIn(words, text)
        self.assertIn('even on exit 0', text[text.index('## 1. '):text.index('## 2. ')])

    def test_the_reader_finds_a_synthetic_skill_s_commands(self):
        text = ('Run `install open --root <root> --browser` and\n\n```sh\n'
                'python3 -I "$openwiz"/tools/install/install skills --root <root>\n```\n'
                'then `<root>/current/openwiz --build-identity` and `git clone x "$openwiz"`.\n')
        self.assertEqual([c[:3] for c in skill_commands(text)],
                         [('tools/install/install', 'open', ['--browser', '--root']),
                          ('tools/install/install', 'skills', ['--root']),
                          ('openwiz', '', ['--build-identity'])])


SYNTHETIC_TAG = 'v0.1.1'
SYNTHETIC_SOURCE = 'b' * 40
RECEIPT = 'openwiz.skill-copy.v1\n' + 'c' * 40 + '\n'
INSTALLER_0_1_1 = {'preflight': [], 'download': ['--dir', '--target', '--version'],
                   'install': ['--assets', '--root', '--state-root', '--target'],
                   'link': ['--root', '--state-root', '--yes'], 'remove': ['--root', '--state-root', '--yes'],
                   'status': ['--root', '--state-root'], 'skills': ['--root', '--state-root']}
FAKE_CURL = r"""#!/usr/bin/env python3
import json, os, re, sys
url = next(a for a in sys.argv[1:] if a.startswith('https://'))
with open(os.environ['FAKE_LOG'], 'a') as log:
    log.write('curl %s\n' % url)
out = sys.argv[sys.argv.index('-o') + 1] if '-o' in sys.argv else None
if url.endswith('/releases/latest') and '-w' in sys.argv:
    print('https://github.com/openwizdev/OpenWiz/releases/tag/' + open(os.environ['FAKE_LATEST']).read())
elif out and out != '/dev/null':
    tag = re.search(r'/releases/download/v([^/]+)/', url)
    open(out, 'w').write(json.dumps({'version': tag[1]}) if tag and url.endswith('.manifest.json') else 'synthetic\n')
"""
FAKE_GIT = r"""#!/usr/bin/env python3
import os, sys
with open(os.environ['FAKE_LOG'], 'a') as log:
    log.write('git %s\n' % ' '.join(sys.argv[1:]))
if sys.argv[1] == 'clone':
    tool = os.path.join(sys.argv[-1], 'tools/install/install')
    os.makedirs(os.path.dirname(tool))
    open(tool, 'w').write(open(os.environ['FAKE_INSTALLER']).read())
"""
FAKE_INSTALLER = r"""import json, os, sys
package = json.load(open(os.environ['FAKE_PACKAGE']))
sub, args = sys.argv[1], sys.argv[2:]
helps = package['tools']['tools/install/install']
if sub not in helps or any(a.startswith('--') and a not in helps[sub] for a in args):
    print(json.dumps({'outcome': 'usage'}))
    sys.exit(2)
with open(os.environ['FAKE_LOG'], 'a') as log:
    log.write('install %s\n' % ' '.join(sys.argv[1:]))
value = lambda flag: args[args.index(flag) + 1]
if sub == 'preflight':
    print(json.dumps({'outcome': 'ready', 'target': 'x86_64-unknown-linux-gnu'}))
elif sub == 'download':
    version = value('--version').lstrip('v') if '--version' in args else open(os.environ['FAKE_LATEST']).read()[1:]
    os.makedirs(value('--dir'))
    with open(os.path.join(value('--dir'), 'openwiz-%s.manifest.json' % value('--target')), 'w') as manifest:
        manifest.write(json.dumps({'version': version}))
    print(json.dumps({'outcome': 'downloaded', 'version': version}))
elif sub == 'install':
    version = json.load(open(os.path.join(value('--assets'), 'openwiz-%s.manifest.json' % value('--target'))))['version']
    build = os.path.join(value('--root'), 'service/builds/synthetic')
    os.makedirs(build)
    binary = os.path.join(build, 'openwiz')
    identity = json.dumps({'version': version, 'source': os.environ['FAKE_SOURCE']}, separators=(',', ':'))
    open(binary, 'w').write('#!/bin/sh\necho %s\n' % repr(identity))
    os.chmod(binary, 0o755)
    os.symlink(build, os.path.join(value('--root'), 'current'))
    print(json.dumps({'outcome': 'installed', 'activated': True, 'version': version}))
"""


class InstallsTheReleaseItFetches(unittest.TestCase):

    def run_steps(self, installer=INSTALLER_0_1_1, latest_after_preflight=SYNTHETIC_TAG):
        import re
        text = SKILL.read_text()
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(__import__('shutil').rmtree, tmp)
        package = json.loads(PACKAGE.read_text())
        package['version'] = SYNTHETIC_TAG[1:]
        package['tools']['tools/install/install'] = installer
        (tmp / 'package.json').write_text(json.dumps(package))
        (tmp / 'installer.py').write_text(FAKE_INSTALLER)
        (tmp / 'latest').write_text(SYNTHETIC_TAG)
        bin_dir = tmp / 'bin'
        bin_dir.mkdir()
        for name, body in (('curl', FAKE_CURL), ('git', FAKE_GIT)):
            write(bin_dir / name, body, 0o755)
        env = {'HOME': str(tmp), 'PATH': '%s:/usr/bin:/bin' % bin_dir, 'FAKE_LOG': str(tmp / 'log'),
               'FAKE_LATEST': str(tmp / 'latest'), 'FAKE_PACKAGE': str(tmp / 'package.json'),
               'FAKE_INSTALLER': str(tmp / 'installer.py'), 'FAKE_SOURCE': SYNTHETIC_SOURCE}
        found = {'<private temporary folder>': str(tmp / 'work'), '<root>': str(tmp / 'root'),
                 '"$openwiz"': str(tmp / 'work/openwiz'), '<private download folder>': str(tmp / 'download')}
        (tmp / 'work').mkdir()
        runs = []
        steps = text[text.index('## 1. '):text.index('## 3. ')]
        for block in re.findall(r'```sh\n(.*?)```', steps, re.S):
            fallback = '/releases/download/' in block
            if fallback and runs and runs[-1][1] == 0 and ' download ' in runs[-1][0]:
                continue
            for key, value in found.items():
                block = block.replace(key, value)
            done = subprocess.run(['sh', '-c', block], env=env, capture_output=True, text=True)
            runs.append((block, done.returncode, done.stdout))
            tag = re.search(r'/releases/tag/(\S+)', done.stdout)
            if tag:
                found.update({'<tag>': tag[1], '<version>': tag[1].lstrip('v')})
            target = re.search(r'"target": "([^"]+)"', done.stdout)
            if target:
                found['<target>'] = target[1]
            if 'git clone' in block:
                (tmp / 'latest').write_text(latest_after_preflight)
        log = (tmp / 'log').read_text() if (tmp / 'log').exists() else ''
        for key, value in found.items():
            steps = steps.replace(key, value)
        return steps, log, runs

    def identity(self, runs):
        return [out for block, code, out in runs if '--build-identity' in block][-1]

    def test_preflight_clones_the_tag_of_the_release_it_installs(self):
        steps, log, runs = self.run_steps()
        clones = [l for l in log.split('\n') if l.startswith('git clone')]
        self.assertEqual(clones, ['git clone --depth 1 --branch %s https://github.com/openwizdev/OpenWiz %s'
                                  % (SYNTHETIC_TAG, clones[0].split()[-1])] if clones else ['a clone'])

    def test_a_release_promoted_after_preflight_is_not_installed(self):
        steps, log, runs = self.run_steps(latest_after_preflight='v0.1.2')
        self.assertEqual(self.identity(runs), '{"version":"0.1.1","source":"%s"}\n' % SYNTHETIC_SOURCE)
        self.assertEqual([code for block, code, out in runs], [0] * len(runs))

    def test_an_installer_without_version_takes_the_pinned_tag_fallback(self):
        older = dict(INSTALLER_0_1_1, download=['--dir', '--target'])
        steps, log, runs = self.run_steps(installer=older, latest_after_preflight='v0.1.2')
        fetched = sorted(l.split()[1] for l in log.split('\n') if l.startswith('curl ') and '/releases/download/' in l)
        base = 'https://github.com/openwizdev/OpenWiz/releases/download/%s/' % SYNTHETIC_TAG
        self.assertEqual(fetched, [base + f for f in ('openwiz-0.1.1-x86_64-unknown-linux-gnu.tar.gz',
                                                      'openwiz-x86_64-unknown-linux-gnu.manifest.json',
                                                      'openwiz-x86_64-unknown-linux-gnu.sha256')])
        self.assertEqual(self.identity(runs), '{"version":"0.1.1","source":"%s"}\n' % SYNTHETIC_SOURCE)

    def test_the_done_check_expects_the_installed_release_s_build_identity(self):
        steps, log, runs = self.run_steps()
        self.assertIn('{"version":"0.1.1","source":"%s"}' % SYNTHETIC_SOURCE, self.identity(runs))
        step2 = steps[steps.index('## 2. '):]
        self.assertIn('`"version":"0.1.1"`', step2)
        self.assertNotIn('0.1.0', step2)

    def test_only_the_explicit_line_names_0_1_0(self):
        text = SKILL.read_text()
        named = [l for l in text[text.index('## Resume'):text.index('## 5. ')].split('\n') if '0.1.0' in l]
        self.assertEqual(len(named), 1, named)
        self.assertIn('To install 0.1.0, stop this skill and follow the [0.1.0 install instructions]'
                      '(https://github.com/openwizdev/WizSkills/blob/maint/0.2/skills/install/SKILL.md)', named[0])
        self.assertIn('hand-started fleets', named[0])
        self.assertIn('always take its pinned `v0.1.0` fetch, never its `download`', named[0])
        self.assertNotIn('version: 0.2.0', text)

    def test_the_restart_message_carries_the_chosen_release(self):
        text = SKILL.read_text()
        resume = text[text.index('## Resume'):text.index('## 1. ')]
        step4 = text[text.index('## 4. '):text.index('## 5. ')]
        for host in ('local', 'boat', 'cloud'):
            self.assertIn('`continue the OpenWiz install with host %s and release <tag>`' % host, step4)
        self.assertIn('`release <tag>` names the release step 1 chose', resume)
        self.assertIn("never GitHub's Latest again", resume)


class RestartReadsTheSkillsOwnVersion(unittest.TestCase):

    def synthetic_release(self, version):
        import re, shutil
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        copy = tmp / 'release/skills/install'
        shutil.copytree(SKILL.parent, copy, ignore=shutil.ignore_patterns('tests', '__pycache__'))
        text = re.sub(r'^version: \S+$', 'version: ' + version, SKILL.read_text(), count=1, flags=re.M)
        (copy / 'SKILL.md').write_text(text)
        return tmp, copy, text

    def agent_copy(self, folder, receipt, body):
        (folder / 'scripts').mkdir(parents=True)
        (folder / '.openwiz-skill').write_text(receipt)
        (folder / 'SKILL.md').write_text(body)

    def overwrite(self, version='0.4.0', folders=None):
        import re
        tmp, copy, text = self.synthetic_release(version)
        home = tmp / 'home'
        bin_dir = tmp / 'bin'
        bin_dir.mkdir()
        write(bin_dir / 'git', '#!/bin/sh\nmkdir -p "$7" && cp -R %s/. "$7/"\n'
              % shlex.quote(str(tmp / 'release')), 0o755)
        step4 = text[text.index('## 4. '):text.index('## 5. ')]
        block = re.findall(r'```sh\n(.*?)```', step4, re.S)[1]
        mine = re.search(r'^version: (\S+)$', text, re.M)[1]
        every = ('"$HOME/.claude/skills" "${CODEX_HOME:-$HOME/.codex}/skills" "$HOME/.cursor/skills" '
                 '"$HOME/.config/opencode/skills" "$HOME/.grok/skills"')
        block = (block.replace('<private temporary folder>', str(tmp / 'work'))
                      .replace('<version of this skill>', mine).replace('<installed agent folders>', folders or every))
        (tmp / 'work').mkdir()
        env = {'HOME': str(home), 'PATH': '%s:/usr/bin:/bin' % bin_dir}
        return home, lambda: subprocess.run(['sh', '-c', block], env=env, capture_output=True, text=True).stdout

    def test_a_release_at_0_4_0_passes_its_own_restart_check(self):
        home, run = self.overwrite()
        old = home / '.claude/skills/install'
        self.agent_copy(old, RECEIPT, '---\nname: install\nversion: 0.2.0\n---\n')
        self.assertEqual(run().split('\n'), ['source ok', 'ok: %s' % old, ''])
        self.assertIn('version: 0.4.0\n', (old / 'SKILL.md').read_text())

    def test_a_user_owned_copy_with_an_invalid_receipt_is_never_overwritten(self):
        home, run = self.overwrite()
        ours, theirs = home / '.claude/skills/install', home / '.codex/skills/install'
        self.agent_copy(ours, RECEIPT, '---\nname: install\nversion: 0.2.0\n---\n')
        self.agent_copy(theirs, 'not a valid receipt\n', '# the user\'s own install skill\n')
        out = run()
        self.assertEqual((theirs / 'SKILL.md').read_text(), '# the user\'s own install skill\n')
        self.assertEqual(sorted((theirs).iterdir()), [theirs / '.openwiz-skill', theirs / 'SKILL.md', theirs / 'scripts'])
        self.assertIn('ok: %s' % ours, out.split('\n'))
        self.assertNotIn(str(theirs), ' '.join(l for l in out.split('\n') if l.startswith(('ok:', 'STILL OLD'))))

    def test_a_parent_link_the_installer_refused_is_never_followed(self):
        home, run = self.overwrite(folders='"$HOME/.claude/skills" "$HOME/.codex/skills"')
        ours = home / '.claude/skills/install'
        self.agent_copy(ours, RECEIPT, '---\nname: install\nversion: 0.2.0\n---\n')
        dotfiles = home.parent / 'dotfiles/codex'
        self.agent_copy(dotfiles / 'skills/install', RECEIPT, '# kept in the user\'s dotfiles\n')
        (home / '.codex').symlink_to(dotfiles)
        out = run()
        self.assertEqual((dotfiles / 'skills/install/SKILL.md').read_text(), '# kept in the user\'s dotfiles\n')
        self.assertIn('ok: %s' % ours, out.split('\n'))
        self.assertEqual([l for l in out.split('\n') if '.codex' in l and l.startswith(('ok:', 'STILL OLD'))], [])

    def test_a_resume_without_installer_results_never_guesses_destinations(self):
        text = SKILL.read_text()
        step4 = text[text.index('## 4. '):text.index('## 5. ')]
        self.assertNotIn('without that output, the five agent folders', step4)
        self.assertIn('Without this session\'s `install skills` output (a resumed session), run `install skills` '
                      'again from a fresh clone of the chosen `<tag>` and use its rows; if you can\'t, copy '
                      'nothing and tell the user', step4)

    def test_resume_and_the_restart_name_no_fixed_skill_version(self):
        import re
        text = SKILL.read_text()
        body = text[text.index('\n---\n') + 5:]
        self.assertEqual(re.findall(r'version: \d+\.\d+\.\d+', body), [])


class RemovalStopsTheHeartbeatThenUsesTheInstaller(unittest.TestCase):

    def test_removal_removes_the_heartbeat_then_previews_and_confirms_install_remove(self):
        text = SKILL.read_text()
        removal = text[text.index('## Recovery and removal'):]
        beat = removal.find('heartbeat.py remove "<owner>/<repo>" "<S>"')
        preview = removal.find('tools/install/install remove --root <root>`')
        confirm = removal.find('the same command with `--yes`')
        self.assertTrue(0 < beat < preview < confirm, (beat, preview, confirm))
        self.assertIn('~/.local/state/openwiz-heartbeat/', removal[:preview])
        self.assertNotIn('there is no remove command', removal)
        self.assertIn('Only for 0.1.0\'s installer, which has no `remove`', removal)


HOST_QUESTION = ("Where should your agents run? This computer (Claude Code or Codex you're signed in to), "
                 "boat.dev, or CloudRoom.")


class NoCloudRoomRequired(unittest.TestCase):

    def setUp(self):
        self.text = SKILL.read_text()

    def between(self, start, end):
        return self.text[self.text.index(start):self.text.index(end)]

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
        self.assertTrue('ignore every `cloudroom_*` code' in step3, 'cloudroom_* codes are not ignored')
        self.assertLess(step3.index('ignore every `cloudroom_*` code'), step3.index('| Code | Next |'))

    def test_restart_passes_the_host_to_where_before_confirmation(self):
        step4 = self.between('## 4. ', '## 5. ')
        for host in ('local', 'boat', 'cloud'):
            self.assertIn(f'continue the OpenWiz install with host {host}', step4,
                          f'the restart message loses the {host} choice')
        resume = self.between('## Resume', '## 1. ')
        self.assertIn('Read the host from the continuation message', resume)
        self.assertLess(resume.index('Read the host from the continuation message'), resume.index('setup.py check'))
        where = self.between('### 1. Where agents run', '### 2. Choose a start')
        self.assertIn('use the host from Resume', where)
        self.assertIn('run `where --agents <its name> --build "$build"` without asking again', where)
        self.assertIn("the user’s yes to the previewed effects and cost", where)
        self.assertIn('run it again with `--yes`', where)

    def test_this_computer_leads_into_the_first_fleet_with_no_cloudroom_ids(self):
        road = self.between('## 6. ', '## Doctor')
        opening = road[:road.index('### 1. ')]
        self.assertFalse('CloudRoom' in opening or 'Cloudroom' in opening, opening)
        where = road[road.index('### 1. '):road.index('### 2. ')]
        self.assertTrue('where --agents' in where, 'where --agents')
        self.assertFalse('suggesting this machine' in where, 'step 6.1 suggests one host')
        self.assertTrue('the host question' in where, 'step 6.1 does not take the host question answer')
        connect = road[road.index('### 3. '):road.index('### 4. ')]
        for flag in ('`--project`', '`--answer-thread`'):
            line = next(l for l in connect.split('\n') if l.strip().startswith('- ' + flag))
            self.assertTrue('only with CloudRoom' in line, line)
        self.assertTrue('no `--project` or `--answer-thread`' in connect, 'prepare still asks CloudRoom ids')
        self.assertFalse('every flag required' in connect, 'every flag required')
        for words in ('`--host local`', '`--host boat`', '`--host <its name>`', 'refuses them'):
            self.assertTrue(words in connect, words)


if __name__ == '__main__':
    unittest.main()
