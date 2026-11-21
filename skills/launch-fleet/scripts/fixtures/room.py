#!/usr/bin/env python3
"""Fixture discovery only; any mutation is refused.

FAKE_ROOM_CLI picks which room-cli answers (#2063): `local` (the default), as on
the user's own machine, prints a table unless --json is passed and a bare list
with it; `cloud`, as in a Cloud thread, prints {"children": [...]}.
"""
import json
import os
from pathlib import Path
import sys
assert sys.argv[1:4] == ['thread', 'list', '--include-archived'], sys.argv
threads = json.loads(Path(os.environ['FLEET_THREADS']).read_text())
if os.environ.get('FAKE_ROOM_CLI', 'local') == 'cloud':
    print(json.dumps({'children': threads}))
elif '--json' in sys.argv:
    print(json.dumps(threads))
else:
    print('ID  TITLE  BRANCH')
    for t in threads:
        print('%s  %s  %s' % (t['id'], t['title'], t.get('branch') or '-'))
