#!/usr/bin/env python3
import json
import os
import stat
import sys


def null_stdin():
    try:
        mine, null = os.fstat(0), os.stat(os.devnull)
    except OSError:
        return False
    return stat.S_ISCHR(mine.st_mode) and mine.st_rdev == null.st_rdev


def main(argv):
    with open(os.environ['FAKE_DRIVER_LOG'], 'a', encoding='utf-8') as log:
        log.write(json.dumps(argv) + '\n')
    if os.environ.get('FAKE_DRIVER_SEEN'):
        with open(os.environ['FAKE_DRIVER_SEEN'], 'a', encoding='utf-8') as seen:
            seen.write(json.dumps({'name': os.environ.get('FAKE_DRIVER_NAME', 'local'), 'argv': argv,
                                   'env': sorted(os.environ), 'stdin_null': null_stdin()}) + '\n')
    if argv != ['version']:
        sys.stderr.write('fake driver: unexpected call\n')
        return 99
    if os.environ.get('FAKE_DRIVER_FAIL'):
        print(json.dumps({'error': 'synthetic: not signed in', 'next': 'sign in to the synthetic host'}))
        return 1
    if 'FAKE_DRIVER_ANSWER' in os.environ:
        print(os.environ['FAKE_DRIVER_ANSWER'])
        return 0
    print(json.dumps({'driver': os.environ.get('FAKE_DRIVER_NAME', 'local'), 'records': ['openwiz:records v1'],
                      'can': ['start', 'wake', 'stop', 'many-at-once']}))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
