#!/usr/bin/env python3
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
import types

sys.dont_write_bytecode = True
SKILLS = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


first_fleet = load('openwiz_first_fleet', SKILLS / 'install/scripts/first_fleet.py')
settings = load('openwiz_settings', SKILLS / 'setup/scripts/settings.py')
status = load('openwiz_status', SKILLS / 'launch-fleet/scripts/status.py')
CREDENTIAL = [pattern for what, pattern in status.PRIVATE if what == 'a credential']
TOKEN_LIKE = re.compile(r'[A-Za-z0-9_+/=-]{20,}')


def unsafe(text, free=False):
    return any(p.search(text) for p in CREDENTIAL) or bool(free and TOKEN_LIKE.search(text))

MISSING_LABEL = re.compile(r'triage-labels\.md: [^:]+: label (.+) is not in the tracker')


def labels(args):
    problems, found = [], []
    try:
        listed = subprocess.run(['gh', 'label', 'list', '--repo', args.repo, '--limit', '500', '--json', 'name'],
                                capture_output=True, text=True, timeout=60)
        names = [item['name'] for item in json.loads(listed.stdout)] if listed.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, KeyError):
        names = None
    if names is None:
        found.append(('gh could not list the labels of %s' % args.repo, 'gh auth login'))
    text = settings.read(Path(args.root) / 'docs/agents/triage-labels.md', problems)
    if text is not None:
        settings.triage(text, names, problems)
    for line in problems:
        missing = MISSING_LABEL.fullmatch(line)
        found.append(('%s is not in the tracker' % missing.group(1),
                      'gh label create %s --repo %s' % (shlex.quote(missing.group(1)), shlex.quote(args.repo)))
                     if missing else
                     (line, 'run the setup skill for %s, then the doctor again' % args.repo))
    return found


def setup_state(folder):
    path = Path(folder) / 'setup/state.json'
    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            return None, 'its setup state is not an owner-only file'
        value = first_fleet.strict(path.read_text(encoding='utf-8'))
        assert value['schema'] == 'openwiz.setup-state.v1' and type(value['revision']) is int
        assert isinstance(value['observations'], dict)
        return value, None
    except FileNotFoundError:
        return None, 'setup has not run yet'
    except (OSError, ValueError, KeyError, TypeError, AssertionError):
        return None, 'its setup state is unreadable'


def recorded(args, value, why, component):
    check = 'python3 -I -B %s --state-dir %s' % (
        shlex.quote(str(Path(args.build) / 'runtime/setup/setup.py')) + ' check', shlex.quote(args.state_dir))
    guided = ("prepare setup for %s with the install skill's Prepare step (2. Connect; it asks for the CloudRoom "
              'project, operator, service issue, answer thread, harness, model and effort), then %s'
              % (args.repo, check))
    if value is None:
        return why, guided if why == 'setup has not run yet' else check
    project = value.get('project')
    step = "the install skill's Prepare step, 2. Connect"
    if not isinstance(project, dict) or not isinstance(project.get('repository'), str):
        return 'setup has no prepared project', guided
    if project['repository'].lower() != args.repo.lower():
        flags = [('--state-dir', args.state_dir), ('--repository', args.repo)] + [
            (flag, str(project.get(key))) for flag, key in (
                ('--project', 'project'), ('--operator', 'operator'), ('--service-issue', 'service_issue'),
                ('--answer-thread', 'answer_thread'), ('--harness', 'harness'), ('--model', 'model'),
                ('--effort', 'effort'))]
        if any(unsafe(text, flag == '--operator') for flag, text in flags[2:]):
            return 'setup is prepared for %s' % project['repository'], guided
        prepare = 'python3 -I -B %s prepare %s' % (shlex.quote(str(Path(args.build) / 'runtime/setup/setup.py')),
                                                   ' '.join(shlex.quote('%s=%s' % pair) for pair in flags))
        return 'setup is prepared for %s' % project['repository'], (
            '%s (a preview: change what differs for %s, confirm it with --yes --operation, then %s)'
            % (prepare, args.repo, check))
    identity = value.get('identity')
    if (component == 'github_app' and isinstance(identity, dict) and identity.get('repository') == project['repository']
            and identity.get('selected') == 'personal_login' and identity.get('app_choice') == 'skip'
            and identity.get('acting_login')):
        return None
    seen = value['observations'].get(component)
    if not isinstance(seen, dict) or not isinstance(seen.get('code'), str):
        return 'not checked yet', check
    now = int(time.time() * 1000)
    if not (seen.get('revision') == value['revision'] and type(seen.get('at')) is int
            and seen['at'] <= now + first_fleet.DRIFT_MS and now - seen['at'] <= first_fleet.CURRENT_MS):
        return 'its last check is out of date', check
    code = seen['code']
    if code == {'github_app': first_fleet.VERIFIED['github_app'], 'harness': 'harness_listed'}[component]:
        return None
    if code.endswith('_unreadable'):
        return 'could not be read (%s)' % code, check
    if code == 'app_all_repositories':
        return ('not verified (%s)' % code,
                "switch OpenWiz's GitHub App installation on %s to Only select repositories, including %s "
                "(Settings > Applications > Installed GitHub Apps > Configure, or the organization's Settings > "
                'GitHub Apps), then %s' % (args.repo.split('/')[0], args.repo, check))
    app_repairs = {
        'app_wrong_repository': 'add %s to the selected repositories' % args.repo,
        'app_suspended': 'unsuspend the installation',
        'app_read_only': 'grant the required write permissions by approving the permission request',
        'app_permissions_mismatch': 'accept the updated permissions requested by the App',
    }
    if component == 'github_app' and code in app_repairs:
        return ('not verified (%s)' % code,
                'in GitHub, go to Settings > Applications > Installed GitHub Apps > Configure '
                "(or the organization's Settings > GitHub Apps), select OpenWiz, %s, then %s"
                % (app_repairs[code], check))
    if component == 'github_app':
        return ('not verified (%s)' % code,
                "set up OpenWiz's GitHub App for %s with %s, as the setup skill's \"The App\" says, then %s" % (
                    args.repo, shlex.quote(str(Path(args.build) / 'runtime/github-app/setup.py')), check))
    if code == 'harness_unavailable':
        chosen = '%s, %s, %s effort' % (project.get('harness'), project.get('model'), project.get('effort'))
        return ('%s is not offered (%s)' % ('the saved harness, model or effort' if unsafe(chosen) else chosen, code),
                'choose a harness, model and effort that openwiz models --json offers and prepare setup again '
                'with them (%s), then %s' % (step, check))
    return 'not verified (%s)' % code, 'sign in to %s in CloudRoom, then %s' % (project.get('harness'), check)


def author(args):
    login = status.viewer()
    if login is None:
        return [('gh could not name the acting login', 'gh auth login')]
    try:
        authors = status.record_authors(args.repo)
    except status.Failed as error:
        return [(str(error), 'run the setup skill for %s, then the doctor again' % args.repo)]
    if login.lower() in authors:
        return []
    return [('%s is not a record author (%s)' % (login, ', '.join(sorted(authors))), 'gh auth login, as one of them')]


def driver(args):
    pull = 'git -C %s pull --ff-only, then the doctor again' % shlex.quote(args.openwiz)
    try:
        kit = load('openwiz_driver_kit', Path(args.openwiz) / 'kernel/driver-kit/kit.py')
        checker = kit.Kit(types.SimpleNamespace(driver=args.driver), None)
        if not isinstance(getattr(checker, 'env', None), dict):
            raise TypeError('Kit.env')
        checker.env = dict({k: os.environ[k] for k in ('PATH', 'HOME', 'LANG') if k in os.environ},
                           **{k: v for k, v in checker.env.items() if k == 'OPENWIZ_KIT_RUN'})
        verdict, what = checker.version()
    except Exception as error:
        return [('the driver kit could not run (%s)' % type(error).__name__, pull)]
    leaks = getattr(checker, 'leaks', None)
    if verdict == 'pass' and leaks == []:
        return []
    found = shutil.which(args.driver) or args.driver
    inside = Path(args.openwiz).resolve() in Path(found).resolve().parents
    update = pull if inside else ('update or replace the driver at %s so it answers version for this OpenWiz, '
                                  'then the doctor again' % shlex.quote(args.driver))
    if leaks != []:
        return [("%s's version answer may hold a credential (%s), so the doctor withholds it"
                 % (args.driver, 'the driver kit flags it' if leaks else 'this driver kit cannot check it'), 'run %s version in your own terminal, not through an agent, to read it; then %s'
                 % (shlex.quote(args.driver), update))]
    return [('%s does not answer version: %s' % (args.driver, what), update)]


def skills(args):
    try:
        setup = load('openwiz_build_setup', Path(args.build) / 'runtime/setup/setup.py')
        pinned = setup.runtime_pin(Path(args.build) / 'runtime')
    except Exception:
        pinned = None
    if pinned:
        return []
    return [('the build at %s is missing its skills' % args.build,
             'python3 -I %s install --assets <download folder> --target <target> --root <root>'
             % shlex.quote(str(Path(args.openwiz) / 'tools/install/install')))]


def main(argv):
    parser = argparse.ArgumentParser(prog='doctor.py')
    for flag in ('--repo', '--state-dir', '--build', '--openwiz'):
        parser.add_argument(flag, required=True)
    parser.add_argument('--root', default='.')
    parser.add_argument('--driver')
    args = parser.parse_args(argv)
    if not re.fullmatch(first_fleet.REPOSITORY, args.repo):
        parser.error('--repo: not OWNER/NAME')
    value, why = setup_state(args.state_dir)
    checks = [(1, 'Labels', lambda: labels(args)),
              (2, 'GitHub App', lambda: [x for x in [recorded(args, value, why, 'github_app')] if x]),
              (3, 'Record author', lambda: author(args)),
              (4, 'Harness', lambda: [x for x in [recorded(args, value, why, 'harness')] if x])]
    if args.driver is not None:
        checks.append((5, 'Driver', lambda: driver(args)))
    checks.append((6, 'Skills', lambda: skills(args)))
    count = 0
    for number, name, run in checks:
        for problem, fix in run():
            count += 1
            print('%d. %s: %s. Fix: %s' % (number, name, problem, fix), flush=True)
    if count:
        print('Doctor: %d problem%s.' % (count, '' if count == 1 else 's'))
        return 5
    print('Doctor: all clear: labels, App, record author, harness listed (its sign-in is not provable yet)%s.'
          % (', driver and skills' if args.driver is not None else ' and skills; no driver given'))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
