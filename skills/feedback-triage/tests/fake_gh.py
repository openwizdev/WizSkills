#!/usr/bin/env python3
"""A recording GitHub for the feedback-triage proofs: synthetic answers only.

Every call is appended to $CALLS as {"args": [...], "stdin": "..."}. Answers
come from $ANSWERS, keyed "<METHOD> <endpoint>". An answer is one of:
  {"json": value}                      a 200 with that body
  {"status": 4xx|5xx, "json": value}   a complete error response
  {"exit": n}                          no response at all (dropped connection)
  {"hang": true}                       writes $HANGING, then never answers
A list of answers is used in order, one per call; the last one repeats.
An unknown call exits 91, so the proofs see any unexpected request.
"""
import json
import os
import sys
import time
from pathlib import Path

args = sys.argv[1:]
stdin = sys.stdin.read() if '--input' in args else ''
with open(os.environ['CALLS'], 'a', encoding='utf-8') as out:
    out.write(json.dumps({'args': args, 'stdin': stdin}) + '\n')

if len(args) < 4 or args[0] != 'api' or args[1] != '--method':
    sys.exit(91)
method, endpoint = args[2], args[-1]
key = f'{method} {endpoint}'
answers = json.loads(Path(os.environ['ANSWERS']).read_text(encoding='utf-8'))
if key not in answers:
    print(f'fake gh: no answer for {key}', file=sys.stderr)
    sys.exit(91)
answer = answers[key]
if isinstance(answer, list):
    counter = Path(os.environ['CALLS'] + '.count')
    counts = json.loads(counter.read_text()) if counter.exists() else {}
    used = counts.get(key, 0)
    counts[key] = used + 1
    counter.write_text(json.dumps(counts))
    answer = answer[min(used, len(answer) - 1)]

if answer.get('hang'):
    Path(os.environ['HANGING']).write_text('hanging')
    time.sleep(3600)
if 'exit' in answer:
    print('fake gh: connection reset', file=sys.stderr)
    sys.exit(answer['exit'])
status = answer.get('status', 200)
body = json.dumps(answer['json'])
if '--include' in args:
    reason = {200: 'OK', 201: 'Created'}.get(status, 'Error')
    sys.stdout.write(f'HTTP/2.0 {status} {reason}\r\nContent-Type: application/json\r\n\r\n')
sys.stdout.write(body + '\n')
if status >= 400:
    print(f'gh: synthetic failure (HTTP {status})', file=sys.stderr)
    sys.exit(1)
