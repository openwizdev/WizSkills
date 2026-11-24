#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys

NEXT = ("this host can't set effort: remove the effort for this harness in your Models table or Roster to run it at "
        "the host's default")
host, mode = os.environ['FAKE_DRIVER_HOST'], os.environ['FAKE_EFFORT_MODE']
command = sys.argv[1] if len(sys.argv) > 1 else ''
raw = sys.stdin.read() if command in ('start', 'wake', 'stop') else ''
given = json.loads(raw) if raw else None


def log():
    with open(os.environ['FAKE_DRIVER_LOG'], 'a') as out:
        out.write(json.dumps({'host': host, 'command': command, 'input': given}) + '\n')


if command == 'version':
    log()
    answer = {'driver': host, 'records': ['openwiz:records v1'],
              'can': ['start', 'wake', 'stop'] + ([] if mode == 'cant' else ['effort'])}
    print(os.environ.get('FAKE_VERSION', json.dumps(dict(answer, effort='medium'))) if mode == 'odd'
          else json.dumps(answer))
    sys.exit(0)
if command == 'start' and 'effort' in given and mode in ('cant', 'refuses'):
    log()
    print(json.dumps({'error': 'unknown field: effort', 'next': 'send only the fields driver v1 lists'} if mode == 'cant'
                     else {'error': "the synthetic host can't run %s at %s effort" % (given['harness'], given['effort']),
                           'next': NEXT}))
    sys.exit(1)
r = subprocess.run([sys.executable, '-I', str(Path(__file__).resolve().parents[2] / 'driver.py'), command], input=raw,
                   capture_output=True, text=True)
sys.stdout.write(r.stdout)
sys.exit(r.returncode)
