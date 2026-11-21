#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys
assert sys.argv[1:4] == ['thread', 'list', '--include-archived'], sys.argv
threads = json.loads(Path(os.environ['FLEET_THREADS']).read_text())
if os.environ.get('FAKE_ROOM_CLI', 'local') == 'cloud':
    if '--include-hidden' in sys.argv:
        print('Unknown option --include-hidden.', file=sys.stderr)
        sys.exit(2)
    print(json.dumps({'children': threads}))
elif '--json' in sys.argv:
    print(json.dumps(threads))
else:
    print('ID  TITLE  BRANCH')
    for t in threads:
        print('%s  %s  %s' % (t['id'], t['title'], t.get('branch') or '-'))
