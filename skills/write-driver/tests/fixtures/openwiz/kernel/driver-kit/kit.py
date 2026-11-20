#!/usr/bin/env python3
"""A synthetic stand-in for OpenWiz's kernel/driver-kit/kit.py, for write-driver's own tests only.

It writes its arguments, one per line, to the file FAKE_KIT_ARGV names, prints the file FAKE_KIT_OUT names
and exits FAKE_KIT_EXIT. With FAKE_KIT_STARTS set, it first calls the driver's `start` that many times, as
the real kit's start check does, and never stops what it started (the real kit skips its stop check when
start fails). The real kit is OpenWiz's; write-driver's eval (WD3) runs it.
"""
import json, os, subprocess, sys
args = sys.argv[1:]
with open(os.environ['FAKE_KIT_ARGV'], 'w') as f:
    f.write('\n'.join(args) + '\n')
value = lambda name: args[args.index(name) + 1]
for _ in range(int(os.environ.get('FAKE_KIT_STARTS', '0'))):
    subprocess.run([value('--driver'), 'start'], capture_output=True, text=True, input=json.dumps(
        {'repository': value('--repo'), 'ticket': int(value('--ticket')), 'skill': value('--skill'),
         'harness': value('--harness'), 'model': value('--model')}))
with open(os.environ['FAKE_KIT_OUT']) as f:
    sys.stdout.write(f.read())
sys.exit(int(os.environ.get('FAKE_KIT_EXIT', '0')))
