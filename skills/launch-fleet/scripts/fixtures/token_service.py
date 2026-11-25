#!/usr/bin/env python3
import base64
import json
import os
import subprocess
import sys
import time

TOKEN = 'synthetic-ga4-token-0123456789'
SCHEMA = 'openwiz.token-service.v1'
OAEP = ('-pkeyopt', 'rsa_padding_mode:oaep', '-pkeyopt', 'rsa_oaep_md:sha256', '-pkeyopt', 'rsa_mgf1_md:sha256')


def seal(token, answer_key):
    reader, writer = os.pipe()
    try:
        with os.fdopen(writer, 'wb') as pipe:
            pipe.write(answer_key.encode('ascii'))
        result = subprocess.run(
            ['/usr/bin/openssl', 'pkeyutl', '-encrypt', '-pubin', '-inkey', f'/dev/fd/{reader}', *OAEP],
            input=token.encode('ascii'), capture_output=True, timeout=10, env={}, pass_fds=(reader,))
    finally:
        os.close(reader)
    if result.returncode != 0:
        raise RuntimeError('openssl encrypt failed')
    return base64.b64encode(result.stdout).decode('ascii')


request = json.loads(sys.stdin.read())
with open(os.environ['FAKE_SERVICE_LOG'], 'a') as log:
    log.write(json.dumps({'argv': sys.argv[1:], 'request': request,
                          'legacy_key': 'OPENWIZ_GITHUB_APP_KEY' in os.environ}) + '\n')
if os.environ.get('FAKE_SERVICE_REFUSE'):
    print(json.dumps({'schema': SCHEMA, 'kind': 'refusal', 'refusal': 'unavailable',
                      'message': 'Token refused: the service cannot read its App state or reach GitHub.'}))
    sys.exit(1)
print(json.dumps({'schema': SCHEMA, 'kind': 'answer', 'sealed_token': seal(TOKEN, request['answer_key']),
                  'expires_at': int(time.time()) + 3600,
                  'repositories': request['repositories'], 'permissions': request['permissions']}))
