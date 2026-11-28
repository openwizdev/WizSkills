#!/usr/bin/env python3
import argparse
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
from pathlib import Path
import sys

APP = """def greeting():
    return "Hello, OpenWiz!"


if __name__ == "__main__":
    print(greeting())
"""

TEST = """import unittest

from app import greeting


class Check(unittest.TestCase):
    def test_greeting(self):
        self.assertEqual(greeting(), "Hello, OpenWiz!")
"""

WORKFLOW = '.github/workflows/check.yml'


def main():
    parser = argparse.ArgumentParser(description='Preview and seed the guided first-fleet demo with your GitHub login.')
    parser.add_argument('--state', required=True, type=Path)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--yes', action='store_true')
    parser.add_argument('--confirm')
    args = parser.parse_args()
    if not args.state.is_absolute():
        parser.error('--state takes an absolute path')

    spec = importlib.util.spec_from_file_location('first_fleet', Path(__file__).with_name('first_fleet.py'))
    fleet = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fleet)
    try:
        _, options = fleet.parse(['create-repo', '--state', str(args.state), '--repo', args.repo])
    except fleet.Exit as stop:
        print(stop.args[0])
        return stop.code

    owner, name = args.repo.split('/')
    files = {'tests/test_check.py': TEST, 'app.py': APP, WORKFLOW: fleet.SEED[WORKFLOW]}
    preview = (f'Create one new private GitHub repository, {args.repo}, with your gh login. Its initial commit '
               f'adds README.md with the title "# {name}". Add {", ".join(files)}, one commit per file. '
               f'The check job runs {fleet.SEED_COMMAND} on pushes and pull requests. '
               'GitHub writes go to the new repository. If using CloudRoom, you make or pick its project.')
    digest = hashlib.sha256(repr((args.state, preview, files)).encode()).hexdigest()
    if not args.yes and args.confirm is None:
        print(preview)
        print(f'Confirmation: {digest}')
        print('On a yes to this preview, run again with --yes --confirm and the confirmation above.')
        return 12
    if not args.yes or args.confirm != digest:
        print('Confirmation does not match. Show a fresh preview before any GitHub write.')
        return 5

    fleet.SEED = files
    output = io.StringIO()
    with redirect_stdout(output):
        try:
            code = fleet.create_repo({**options, '--yes': True})
        except fleet.Exit as stop:
            print(stop.args[0])
            code = stop.code
    _, _, result_after_legacy_preview = output.getvalue().partition('\n')
    if code != 0:
        print(result_after_legacy_preview, end='')
        return code

    state = fleet.State.__new__(fleet.State)
    state.path = args.state
    try:
        record = state.read()['created']
    except (fleet.Exit, KeyError):
        print('Could not read the demo repository record. Repeat the approved command to read it back.')
        return 6
    for path, expected in files.items():
        actual = fleet.tree(fleet.BY_NAME, owner=owner, name=name, path=path)
        if actual is None:
            print('Could not read the demo starter files. Repeat the approved command to read them back.')
            return 6
        if actual['repo'] != record.get('id') or actual['branch'] != record.get('branch') or actual['text'] != expected:
            print('The demo starter files did not match. Use the repository as an existing project if intended.')
            return 5
    print(result_after_legacy_preview, end='')
    print('Run first_fleet.py select with the same repository and state file to continue.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
