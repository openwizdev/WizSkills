#!/usr/bin/env python3
"""A synthetic token service (token-service v1) for launch-fleet's token-step tests (GA4, OpenWiz #1846).

The agent helper runs it as `python3 -I <this file> mint` (the local route). It
reads one request on stdin, appends the request and its own argument list to
$FAKE_SERVICE_LOG as one JSON line (with whether the legacy key variable reached it,
never its value), and answers as the contract says: a
synthetic token for exactly the requested scope, or with $FAKE_SERVICE_REFUSE
set, the `unavailable` refusal (exit 1). It holds no key and reaches nothing.
"""
import json
import os
import sys
import time

TOKEN = 'synthetic-ga4-token-0123456789'
SCHEMA = 'openwiz.token-service.v1'

request = json.loads(sys.stdin.read())
with open(os.environ['FAKE_SERVICE_LOG'], 'a') as log:
    log.write(json.dumps({'argv': sys.argv[1:], 'request': request,
                          'legacy_key': 'OPENWIZ_GITHUB_APP_KEY' in os.environ}) + '\n')
if os.environ.get('FAKE_SERVICE_REFUSE'):
    print(json.dumps({'schema': SCHEMA, 'kind': 'refusal', 'refusal': 'unavailable',
                      'message': 'Token refused: the service cannot read its App state or reach GitHub.'}))
    sys.exit(1)
print(json.dumps({'schema': SCHEMA, 'kind': 'answer', 'token': TOKEN, 'expires_at': int(time.time()) + 3600,
                  'repositories': request['repositories'], 'permissions': request['permissions']}))
