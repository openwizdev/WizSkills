#!/usr/bin/env python3
"""The install skill's setup doctor (#1449). Python 3.9+, standard library only.

  doctor.py --repo OWNER/NAME --state-dir STATE --build BUILD --openwiz CHECKOUT
            [--root PROJECT] [--driver PROGRAM]

Checks setup against reality, in this order, and prints each problem on its
own line with the command that fixes it:

  1. Labels: each triage role's label exists in the tracker (the setup
     skill's settings.py check, on `gh label list`).
  2. GitHub App: the last setup check verified it for this repository, or
     the user skipped it (the codes `setup.py check` recorded, read the way
     first_fleet.py reads them).
  3. Record author: the acting gh login is one (status.py's author check).
  4. Harness: the last setup check listed it (as for the App).
  5. Driver: PROGRAM answers `version` (the OpenWiz checkout's driver kit,
     kernel/driver-kit/kit.py); skipped without --driver.
  6. Skills: the installed build carries its skills (the build's
     setup.py runtime_pin).

It runs only those existing checks, and only reads: it never signs in, never
reads or mints a token and never writes the setup state. A sign-in problem
prints the command for the person to run. A clean setup prints one all-clear
line. PROJECT (default: the current folder) is the project's checkout.

Exits: 0 all clear; 2 usage; 5 problems printed.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
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
MISSING_LABEL = re.compile(r'triage-labels\.md: [^:]+: label (.+) is not in the tracker')


def labels(args):
    """Check 1: settings.py's triage check, given the tracker's labels."""
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
    """The setup store's value, or the reason it can't be read (first_fleet's rules)."""
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
    """(problem, fix) for one component's recorded setup check, or None when it holds."""
    check = 'python3 -I -B %s --state-dir %s' % (
        shlex.quote(str(Path(args.build) / 'runtime/setup/setup.py')) + ' check', shlex.quote(args.state_dir))
    if value is None:
        return why, check
    project = value.get('project')
    prepare = ('python3 -I -B %s prepare --state-dir %s --repository %s ...'
               % (shlex.quote(str(Path(args.build) / 'runtime/setup/setup.py')), shlex.quote(args.state_dir),
                  shlex.quote(args.repo)))
    if not isinstance(project, dict) or not isinstance(project.get('repository'), str):
        return 'setup has no prepared project', prepare
    if project['repository'].lower() != args.repo.lower():
        return 'setup is prepared for %s' % project['repository'], prepare
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
    if component == 'github_app':
        return ('not verified (%s)' % code,
                "install OpenWiz's GitHub App on %s from the setup page, then %s" % (args.repo, check))
    return 'not verified (%s)' % code, 'sign in to %s in CloudRoom, then %s' % (project.get('harness'), check)


def author(args):
    """Check 3: status.py's R4 check, the acting login against the Record authors row."""
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
    """Check 5: the driver kit's own version check."""
    update = 'git -C %s pull --ff-only, then the doctor again' % shlex.quote(args.openwiz)
    try:
        kit = load('openwiz_driver_kit', Path(args.openwiz) / 'kernel/driver-kit/kit.py')
        verdict, what = kit.Kit(types.SimpleNamespace(driver=args.driver), None).version()
    except Exception as error:  # a kit that can't run is a problem to report, never a crash
        return [('the driver kit could not run (%s)' % type(error).__name__, update)]
    return [] if verdict == 'pass' else [('%s does not answer version: %s' % (args.driver, what), update)]


def skills(args):
    """Check 6: the build's own runtime_pin, which needs its packaged skills."""
    try:
        setup = load('openwiz_build_setup', Path(args.build) / 'runtime/setup/setup.py')
        pinned = setup.runtime_pin(Path(args.build) / 'runtime')
    except Exception:  # a build without a usable setup.py has no usable skills either
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
    # setup.py's own check proves a harness listed, never its sign-in (setup R5); say no more than that.
    print('Doctor: all clear: labels, App, record author, harness listed (its sign-in is not provable yet)%s.'
          % (', driver and skills' if args.driver is not None else ' and skills; no driver given'))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
