#!/usr/bin/env python3
"""A recording fake of OpenWiz's local driver (driver v1, adapters/local/driver, #1368, merged
as OpenWiz 583f2ae; its `version` answer here is that driver's VERSION, byte for byte).

It answers only `version`, as the local driver does: its name, the records it
speaks and what it can do. Every call is logged to $FAKE_DRIVER_LOG as one
JSON line. Any other command exits 99, so a test sees the onboarding start,
wake or stop a run itself (only launch-fleet does that). All values are synthetic.
"""
import json
import os
import sys


def main(argv):
    with open(os.environ['FAKE_DRIVER_LOG'], 'a', encoding='utf-8') as log:
        log.write(json.dumps(argv) + '\n')
    if argv != ['version']:
        sys.stderr.write('fake driver: unexpected call\n')
        return 99
    print(json.dumps({'driver': 'local', 'records': ['openwiz:records v1'],
                      'can': ['start', 'wake', 'stop', 'many-at-once']}))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
