#!/usr/bin/env python3
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ETAG = re.compile(r'(W/)?"[!#-~]{1,250}"')
NEXT = re.compile(r'<([^>]+)>\s*;\s*rel="next"')
MEDIA = 'application/vnd.github+json'


class Error(Exception):
    pass


def cache_dir():
    base = os.environ.get('XDG_CACHE_HOME') or os.path.join(os.path.expanduser('~'), '.cache')
    return Path(base) / 'launch-fleet' / 'rest'


def _request(endpoint, accept):
    key = '\n'.join(['ghcache REST v1', os.environ.get('GH_HOST', 'github.com'), endpoint, accept])
    return hashlib.sha256(key.encode()).hexdigest()


def _load(path, request, endpoint):
    if not os.path.lexists(path):
        return None
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError
        entry = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(entry, dict) or set(entry) != {'request', 'etag', 'link', 'body', 'sha256'}
                or entry['request'] != request or not isinstance(entry['etag'], str)
                or not ETAG.fullmatch(entry['etag']) or not isinstance(entry['link'], str)
                or not isinstance(entry['body'], str)
                or hashlib.sha256(entry['body'].encode()).hexdigest() != entry['sha256']):
            raise ValueError
        return entry
    except (OSError, ValueError, UnicodeError):
        try:
            path.unlink()
        except OSError:
            pass
        raise Error('ghcache: damaged cache entry for %s, removed; read again' % endpoint) from None


def _save(path, entry):
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, pending = tempfile.mkstemp(dir=path.parent, prefix='.rest.')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as out:
                json.dump(entry, out)
            os.replace(pending, path)
        except BaseException:
            os.unlink(pending)
            raise
    except OSError:
        pass


def _parse(raw, endpoint):
    head, sep, body = raw.partition(b'\r\n\r\n')
    if not sep:
        head, sep, body = raw.partition(b'\n\n')
    lines = head.decode('latin-1').replace('\r', '').split('\n')
    status = re.fullmatch(r'HTTP/[0-9.]+ ([0-9]{3})(?: .*)?', lines[0])
    if not status:
        raise Error('ghcache: no HTTP answer for %s' % endpoint)
    headers = {}
    for line in lines[1:]:
        name, colon, value = line.partition(':')
        if colon:
            headers.setdefault(name.strip().lower(), value.strip())
    return int(status.group(1)), headers, body


def _read(endpoint, accept=None):
    if not isinstance(endpoint, str) or not endpoint or endpoint.startswith('-') or '\n' in endpoint:
        raise Error('ghcache: not an endpoint: %r' % (endpoint,))
    accept = accept or MEDIA
    request = _request(endpoint, accept)
    path = cache_dir() / ('%s.json' % request)
    entry = _load(path, request, endpoint)
    command = ['gh', 'api', '--include', '--method', 'GET', '-H', 'Accept: %s' % accept]
    if entry:
        command += ['-H', 'If-None-Match: %s' % entry['etag']]
    try:
        raw = subprocess.run(command + [endpoint], stdin=subprocess.DEVNULL, capture_output=True).stdout
    except OSError:
        raise Error('ghcache: could not run gh for %s' % endpoint) from None
    status, headers, body = _parse(raw, endpoint)
    if status == 304:
        if not entry:
            raise Error('ghcache: 304 for %s with no saved answer' % endpoint)
        return entry['body'], headers.get('link', entry['link'])
    if status != 200:
        raise Error('ghcache: HTTP %d for %s' % (status, endpoint))
    try:
        text = body.decode('utf-8')
    except UnicodeError:
        raise Error('ghcache: an answer for %s that is not UTF-8' % endpoint) from None
    link, etag = headers.get('link', ''), headers.get('etag', '')
    if ETAG.fullmatch(etag):
        _save(path, {'request': request, 'etag': etag, 'link': link, 'body': text,
                     'sha256': hashlib.sha256(text.encode()).hexdigest()})
    return text, link


def _json(text, endpoint):
    try:
        return json.loads(text)
    except ValueError:
        raise Error('ghcache: an answer for %s that is not JSON' % endpoint) from None


def get(endpoint, accept=None):
    return _json(_read(endpoint, accept)[0], endpoint)


def pages(endpoint):
    items, seen = [], set()
    while endpoint:
        if endpoint in seen:
            raise Error('ghcache: a page loop at %s' % endpoint)
        seen.add(endpoint)
        text, link = _read(endpoint)
        page = _json(text, endpoint)
        if not isinstance(page, list):
            raise Error('ghcache: a page of %s that is not a list' % endpoint)
        items += page
        found = NEXT.search(link)
        endpoint = found.group(1) if found else None
    return items


def main(argv):
    args = argv[1:]
    accept = None
    if len(args) == 4 and args[2] == '--accept':
        accept, args = args[3], args[:2]
    if len(args) != 2 or args[0] != 'get':
        print('usage: ghcache.py get ENDPOINT [--accept MEDIA]', file=sys.stderr)
        return 2
    try:
        text = _read(args[1], accept)[0]
    except Error as error:
        print(error, file=sys.stderr)
        return 1
    sys.stdout.write(text if text.endswith('\n') or not text else text + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
