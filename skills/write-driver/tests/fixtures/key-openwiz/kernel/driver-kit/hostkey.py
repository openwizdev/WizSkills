#!/usr/bin/env python3
"""A synthetic stand-in for OpenWiz's kernel/driver-kit/hostkey.py, for write-driver's own tests only.

It reads one request (host, method, path and an optional body) on stdin and works only under the kit's loopback
override, OPENWIZ_HOSTKEY_TEST_ORIGIN: it asks that fake host for its test key, sends the request there with the
key in an Authorization: Bearer header, and prints exactly status and body. Without the override it refuses and
reads no key at all. The real helper is OpenWiz's.
"""
import http.client
import json
import os
import sys


def main():
    origin = os.environ.get('OPENWIZ_HOSTKEY_TEST_ORIGIN', '')
    request = json.loads(sys.stdin.read())
    hosts = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hosts.json')))
    if not origin.startswith('http://127.0.0.1:') or request.get('host') not in hosts:
        print(json.dumps({'error': 'the synthetic helper runs only against a fake host', 'next': 'run its tests'}))
        return 1
    host, port = origin[len('http://'):].split(':')
    conn = http.client.HTTPConnection(host, int(port), timeout=60)
    conn.request('GET', '/.openwiz/hostkey-test-key')
    key = json.loads(conn.getresponse().read())['key']
    conn.close()
    conn = http.client.HTTPConnection(host, int(port), timeout=60)
    body = json.dumps(request['body']).encode() if 'body' in request else None
    conn.request(request['method'], request['path'], body=body, headers={'Authorization': 'Bearer ' + key})
    answer = conn.getresponse()
    status, raw = answer.status, answer.read()
    conn.close()
    print(json.dumps({'status': status, 'body': json.loads(raw) if raw else None}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
