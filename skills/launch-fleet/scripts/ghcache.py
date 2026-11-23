#!/usr/bin/env python3
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
from urllib.parse import urlsplit

ETAG = re.compile(r'(W/)?"[!#-~]{1,250}"')
NEXT = re.compile(r'<([^>]+)>\s*;\s*rel="next"')
MEDIA = 'application/vnd.github+json'
UNSAFE = re.compile(r'[^A-Za-z0-9/._~%+,=@:-]')


class Error(Exception):
    pass


def cache_dir():
    base = os.environ.get('XDG_CACHE_HOME')
    if not base or not os.path.isabs(base):
        base = os.path.join(os.path.expanduser('~'), '.cache')
    return Path(base) / 'launch-fleet' / 'rest'


def _label(endpoint):
    try:
        path = urlsplit(endpoint).path
    except ValueError:
        return '(an endpoint that cannot be parsed)'
    return UNSAFE.sub('?', path)[:200] or '(no path)'


def _owned(info):
    return info.st_uid == os.getuid()


def _trusted(info, own):
    if not stat.S_ISDIR(info.st_mode):
        return False
    if own:
        return _owned(info) and not info.st_mode & 0o022
    return info.st_uid in (0, os.getuid()) and (not info.st_mode & 0o022 or info.st_mode & stat.S_ISVTX)


def _step(fd, name, own):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        child = os.open(name, flags, dir_fd=fd)
    except FileNotFoundError:
        try:
            os.mkdir(name, 0o700, dir_fd=fd)
        except FileExistsError:
            pass
        child = os.open(name, flags, dir_fd=fd)
    if not _trusted(os.fstat(child), own):
        os.close(child)
        raise Error('ghcache: unsafe cache folder, refused')
    if fd is not None:
        os.close(fd)
    return child


def _root():
    base = cache_dir().parent.parent
    if not base.is_absolute():
        raise Error('ghcache: unsafe cache folder, refused')
    names, fd, links = list(base.parts), None, 0
    try:
        while names:
            name = names.pop(0)
            try:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                info = None
            if info and stat.S_ISLNK(info.st_mode):
                links += 1
                if links > 40 or info.st_uid not in (0, os.getuid()) or os.fstat(fd).st_mode & 0o022:
                    raise Error('ghcache: unsafe cache folder, refused')
                names[:0] = Path(os.readlink(name, dir_fd=fd)).parts
                continue
            fd = _step(fd, name, False)
        for name in ('launch-fleet', 'rest'):
            fd = _step(fd, name, True)
        if stat.S_IMODE(os.fstat(fd).st_mode) != 0o700:
            os.fchmod(fd, 0o700)
    except BaseException as error:
        if fd is not None:
            os.close(fd)
        if isinstance(error, OSError):
            raise Error('ghcache: cannot use the cache folder') from None
        raise
    return fd


def _digest(request, etag, link, body):
    return hashlib.sha256(json.dumps([request, etag, link, body]).encode()).hexdigest()


def _entry(request, etag, link, body):
    return {'request': request, 'etag': etag, 'link': link, 'body': body,
            'sha256': _digest(request, etag, link, body)}


def _request(endpoint, accept):
    key = '\n'.join(['ghcache REST v1', os.environ.get('GH_HOST', 'github.com'), endpoint, accept])
    return hashlib.sha256(key.encode()).hexdigest()


def _once(pairs):
    if len({key for key, _ in pairs}) != len(pairs):
        raise ValueError
    return dict(pairs)


def _load(root, name, request, label):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
    except FileNotFoundError:
        return None
    except OSError:
        raise Error('ghcache: unsafe cache entry for %s, refused' % label) from None
    with os.fdopen(fd, 'rb') as handle:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not _owned(info) or info.st_mode & 0o077:
            raise Error('ghcache: unsafe cache entry for %s, refused' % label)
        try:
            raw = handle.read()
        except OSError:
            raw = b''
    if not raw:
        return None
    try:
        entry = json.loads(raw.decode('utf-8'), object_pairs_hook=_once)
        if (not isinstance(entry, dict) or set(entry) != {'request', 'etag', 'link', 'body', 'sha256'}
                or entry['request'] != request or not isinstance(entry['etag'], str)
                or not ETAG.fullmatch(entry['etag']) or not isinstance(entry['link'], str)
                or not isinstance(entry['body'], str)
                or _digest(request, entry['etag'], entry['link'], entry['body']) != entry['sha256']):
            raise ValueError
        return entry
    except (ValueError, UnicodeError):
        _drop(root, name)
        raise Error('ghcache: damaged cache entry for %s, removed; read again' % label) from None


def _drop(root, name):
    try:
        os.unlink(name, dir_fd=root)
        return
    except FileNotFoundError:
        return
    except OSError:
        pass
    try:
        fd = os.open(name, os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
    except OSError:
        return
    try:
        info = os.fstat(fd)
        if stat.S_ISREG(info.st_mode) and _owned(info):
            os.ftruncate(fd, 0)
    except OSError:
        pass
    finally:
        os.close(fd)


def _save(root, name, entry):
    pending = '.rest.%s' % secrets.token_hex(16)
    try:
        fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=root)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as out:
                json.dump(entry, out)
            os.replace(pending, name, src_dir_fd=root, dst_dir_fd=root)
        except BaseException:
            os.unlink(pending, dir_fd=root)
            raise
    except OSError:
        return False
    return True


def _parse(raw, label):
    head, sep, body = raw.partition(b'\r\n\r\n')
    if not sep:
        head, sep, body = raw.partition(b'\n\n')
    lines = head.decode('latin-1').replace('\r', '').split('\n')
    status = re.fullmatch(r'HTTP/[0-9.]+ ([0-9]{3})(?: .*)?', lines[0])
    if not status or not sep:
        raise Error('ghcache: no complete HTTP answer for %s' % label)
    headers = {}
    for line in lines[1:]:
        name, colon, value = line.partition(':')
        if colon:
            headers.setdefault(name.strip().lower(), value.strip())
    return int(status.group(1)), headers, body


def _read(endpoint, accept=None):
    if not isinstance(endpoint, str) or not endpoint or endpoint.startswith('-') or '\n' in endpoint:
        raise Error('ghcache: not an endpoint')
    label = _label(endpoint)
    accept = accept or MEDIA
    request = _request(endpoint, accept)
    root = _root()
    try:
        return _cached(root, endpoint, accept, label, request)
    finally:
        os.close(root)


def _cached(root, endpoint, accept, label, request):
    name = '%s.json' % request
    entry = _load(root, name, request, label)
    command = ['gh', 'api', '--include', '--method', 'GET', '-H', 'Accept: %s' % accept]
    if entry:
        command += ['-H', 'If-None-Match: %s' % entry['etag']]
    try:
        run = subprocess.run(command + [endpoint], stdin=subprocess.DEVNULL, capture_output=True)
    except OSError:
        raise Error('ghcache: could not run gh for %s' % label) from None
    status, headers, body = _parse(run.stdout, label)
    if status == 304:
        if not entry:
            raise Error('ghcache: 304 for %s with no saved answer' % label)
        link = headers.get('link', entry['link'])
        if link != entry['link'] and not _save(root, name, _entry(request, entry['etag'], link, entry['body'])):
            _drop(root, name)
            raise Error('ghcache: cannot save the new Link for %s in the cache; read again' % label)
        return entry['body'], link
    if status != 200:
        raise Error('ghcache: HTTP %d for %s' % (status, label))
    if run.returncode != 0:
        raise Error('ghcache: gh failed after a 200 for %s' % label)
    try:
        text = body.decode('utf-8')
    except UnicodeError:
        raise Error('ghcache: an answer for %s that is not UTF-8' % label) from None
    link, etag = headers.get('link', ''), headers.get('etag', '')
    if ETAG.fullmatch(etag):
        _save(root, name, _entry(request, etag, link, text))
    return text, link


def _json(text, endpoint):
    try:
        return json.loads(text)
    except ValueError:
        raise Error('ghcache: an answer for %s that is not JSON' % _label(endpoint)) from None


def get(endpoint, accept=None):
    return _json(_read(endpoint, accept)[0], endpoint)


def pages(endpoint):
    items, seen = [], set()
    while endpoint:
        if endpoint in seen:
            raise Error('ghcache: a page loop at %s' % _label(endpoint))
        seen.add(endpoint)
        text, link = _read(endpoint)
        page = _json(text, endpoint)
        if not isinstance(page, list):
            raise Error('ghcache: a page of %s that is not a list' % _label(endpoint))
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
