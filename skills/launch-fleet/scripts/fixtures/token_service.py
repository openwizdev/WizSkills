#!/usr/bin/env python3
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
