#!/usr/bin/env python3
"""A synthetic driver v1 for test-host.py (#1371): it starts nothing.

Installed as `<adapters>/<host>/driver`, it appends each call (its host, command
and stdin) to $FAKE_DRIVER_LOG as one JSON line and answers as a driver would:
`start` a run id naming its host, `wake` and `stop` that run. With
$FAKE_DRIVER_MODE `refuse` it fails as v1 says (exit 1, `error` and `next`);
with `garbage` it answers something that is no run.
"""
import json
import os
import sys

host = os.path.basename(os.path.dirname(os.path.abspath(sys.argv[0])))
command = sys.argv[1] if len(sys.argv) > 1 else ''
given = sys.stdin.read() if command in ('start', 'wake', 'stop') else ''
with open(os.environ['FAKE_DRIVER_LOG'], 'a') as log:
    log.write(json.dumps({'host': host, 'command': command, 'input': json.loads(given) if given else None}) + '\n')
mode = os.environ.get('FAKE_DRIVER_MODE', '')
if mode == 'refuse':
    print(json.dumps({'error': 'the synthetic harness is not signed in', 'next': 'sign in to the harness, then start again'}))
    sys.exit(1)
if mode == 'garbage':
    print('started, probably')
    sys.exit(0)
if command == 'start':
    print(json.dumps({'run': '%s-run-%d' % (host, json.loads(given)['ticket'])}))
elif command == 'wake':
    print(json.dumps({'run': json.loads(given)['run'], 'woke': True}))
elif command == 'stop':
    print(json.dumps({'run': json.loads(given)['run'], 'stopped': True}))
else:
    print(json.dumps({'error': 'unknown command', 'next': 'run start, wake or stop'}))
    sys.exit(1)
