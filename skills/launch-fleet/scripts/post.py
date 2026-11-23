#!/usr/bin/env python3
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('launch_fleet_grants', HERE / 'grants.py')
grants = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(grants)
_spec = importlib.util.spec_from_file_location('launch_fleet_gitread', HERE / 'gitread.py')
gitread = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gitread)

REPO = re.compile(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+')
PRIVATE = re.compile(r'\b(?:thr|loop)_[A-Za-z0-9]|\b(?:gh[opsur]_|github_pat_)[A-Za-z0-9_]')
FIRST = ('launch-fleet: ', '**Needs you:**')


class Stop(Exception):
    pass


def gh(*args):
    try:
        r = subprocess.run(['gh', *args], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


PER_MINUTE, PER_HOUR, IN_FLIGHT = 60, 400, 20
SLOT_WAIT_SECONDS = 30
IN_FLIGHT_STALE_SECONDS = 90
SECONDARY_WAIT_DEFAULT_SECONDS = 60
LATEST_TIME = 32503680000
PID_LIMIT = 2 ** 31
SHARED = 'shared'


def stamp(at):
    return datetime.fromtimestamp(at, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def paced(at):
    return Stop(f'refused: write paced, retry after {stamp(at)}')


def state_path():
    base = os.environ.get('XDG_STATE_HOME') or os.path.join(os.path.expanduser('~'), '.local', 'state')
    return Path(base) / 'launch-fleet' / 'writes.json'


def number(value):
    return type(value) in (int, float) and 0 <= value <= LATEST_TIME


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate key')
        value[key] = item
    return value


def valid(value):
    return (isinstance(value, dict) and set(value) == {'accounts', 'inflight', 'until'}
            and isinstance(value['accounts'], dict)
            and all(isinstance(v, list) and all(number(t) for t in v) for v in value['accounts'].values())
            and isinstance(value['inflight'], list)
            and all(isinstance(e, list) and len(e) == 2 and type(e[0]) is int and 0 < e[0] < PID_LIMIT
                    and number(e[1]) for e in value['inflight'])
            and number(value['until']))


def save(path, value, hold=False):
    try:
        fd, temp = tempfile.mkstemp(prefix=f'{path.name}.hold.' if hold else f'.{path.name}.', suffix='.tmp',
                                    dir=path.parent)
    except OSError:
        raise Stop('refused: the write pacer\'s state file cannot be saved; nothing was written')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(json.dumps(value))
        os.replace(temp, temp[:-len('.tmp')] if hold else path)
    except OSError:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise Stop('refused: the write pacer\'s state file cannot be saved; nothing was written')


def holds(path):
    return sorted(p for p in path.parent.glob(path.name + '.hold.*') if not p.name.endswith('.tmp'))


def decode(text):
    try:
        return json.loads(text, object_pairs_hook=unique)
    except (ValueError, RecursionError, MemoryError):
        return None


@contextmanager
def pacer_state(deadline):
    path = state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = open(path.with_name(path.name + '.lock'), 'a')
    except OSError:
        raise Stop('refused: the write pacer\'s state folder cannot be used; nothing was written')
    with lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise paced(time.time())
                time.sleep(0.05)
        waits = []
        try:
            value = decode(path.read_text()) if path.exists() else {'accounts': {}, 'inflight': [], 'until': 0}
            held = holds(path)
            waits = [decode(p.read_text()) for p in held]
        except OSError:
            value = None
        if not valid(value) or not all(number(t) for t in waits):
            raise Stop('refused: the write pacer\'s state file is unreadable; nothing was written')
        value['until'] = max([value['until'], *waits])
        yield value
        save(path, value)
        for p in held:
            try:
                p.unlink()
            except OSError:
                pass


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (OSError, OverflowError):
        return True
    return True


def credential():
    token = (os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN') or '').strip()
    if not token:
        return SHARED
    return 'sha256:' + hashlib.sha256(token.encode()).hexdigest()[:16]


def take(paced_write):
    key = credential() if paced_write else None
    deadline = time.monotonic() + SLOT_WAIT_SECONDS
    while True:
        with pacer_state(deadline) as s:
            now = time.time()
            s['inflight'] = [e for e in s['inflight'] if now - e[1] < IN_FLIGHT_STALE_SECONDS and alive(e[0])]
            s['accounts'] = {k: kept for k, v in s['accounts'].items() if (kept := [t for t in v if now - t < 3600])}
            free = s['until']
            times = sorted(s['accounts'].get(key, [])) if paced_write else []
            recent = [t for t in times if now - t < 60]
            if len(recent) >= PER_MINUTE:
                free = max(free, recent[-PER_MINUTE] + 60)
            if len(times) >= PER_HOUR:
                free = max(free, times[-PER_HOUR] + 3600)
            busy = len(s['inflight']) >= IN_FLIGHT
            if busy:
                free = max(free, sorted(e[1] for e in s['inflight'])[-IN_FLIGHT] + IN_FLIGHT_STALE_SECONDS)
            left = deadline - time.monotonic()
            if left <= 0 or (free > now + left and not busy):
                raise paced(max(free, now))
            if free <= now and not busy:
                if paced_write:
                    s['accounts'][key] = times + [now]
                entry = [os.getpid(), now]
                s['inflight'].append(entry)
                return entry
        time.sleep(max(0.05, min(0.5 if busy else free - now, left)))


def settle(entry, until=None):
    try:
        with pacer_state(time.monotonic() + SLOT_WAIT_SECONDS) as s:
            if until is not None:
                s['until'] = max(s['until'], until)
            if entry in s['inflight']:
                s['inflight'].remove(entry)
        return True
    except Stop:
        if until is None:
            return False
    try:
        save(state_path(), until, hold=True)
        return True
    except Stop:
        return False


def answer(text):
    head = re.match(r'HTTP/\S+ (\d{3})[^\n]*\n((?:[^\r\n][^\n]*\n)*)\r?\n', text)
    if head is None:
        return None, {}, text
    headers = {}
    for line in head.group(2).splitlines():
        name, sep, value = line.partition(':')
        if sep:
            headers[name.strip().lower()] = value.strip()
    return int(head.group(1)), headers, text[head.end():]


def secondary_wait(status, headers, said):
    after = headers.get('retry-after', '')
    named = 'secondary rate limit' in said.lower()
    if status not in (403, 429) or not (after or named):
        return None
    if re.fullmatch(r'[0-9]{1,9}', after):
        return int(after)
    if after:
        try:
            return max(0, parsedate_to_datetime(after).timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            return SECONDARY_WAIT_DEFAULT_SECONDS
    reset = headers.get('x-ratelimit-reset', '')
    if headers.get('x-ratelimit-remaining') == '0' and re.fullmatch(r'[0-9]{1,10}', reset):
        return max(0, int(reset) - time.time())
    return SECONDARY_WAIT_DEFAULT_SECONDS


def write(where, *args, paced=True):
    entry = take(paced)
    try:
        r = subprocess.run(['gh', 'api', '--include', *args], capture_output=True, text=True, timeout=60,
                           stdin=subprocess.DEVNULL)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        settle(entry)
        return None
    status, headers, body = answer(r.stdout)
    wait = secondary_wait(status, headers, body + r.stderr)
    if wait is None:
        settle(entry)
        return body if r.returncode == 0 else None
    until = min(time.time() + wait, LATEST_TIME)
    held = '' if settle(entry, until) else ', but the wait could not be recorded'
    raise Stop(f'unknown: GitHub refused the write on {where} under its secondary rate limit{held}; '
               f'no write should leave this machine before {stamp(until)}; reconcile {where} before any retry')


def read_json(*args):
    text = gh(*args)
    try:
        return None if text is None else json.loads(text)
    except ValueError:
        return None


def authors(repo):
    try:
        text = gitread.show(repo, 'docs/agents/fleet.md')
    except gitread.Error:
        text = None
    try:
        return grants.record_authors(text or '')
    except ValueError:
        raise Stop('refused: docs/agents/fleet.md names no record authors, so no record can be read back')


def check(body):
    first = next((line for line in body.splitlines() if line.strip()), '')
    if not first.startswith(FIRST):
        raise Stop("refused: not a fleet record (its first line starts 'launch-fleet: ' or '**Needs you:**')")
    if PRIVATE.search(body):
        raise Stop('refused: the body carries a private identity; name the public ticket, pull request or commit')


def ours(item, auth):
    return isinstance(item, dict) and grants.authored((item.get('user') or {}).get('login'), auth)


def thread(repo, number):
    pages = read_json('api', '--paginate', '--slurp', f'repos/{repo}/issues/{number}/comments?per_page=100')
    if not isinstance(pages, list) or not all(isinstance(p, list) for p in pages):
        return None
    return [c for p in pages for c in p]


def comment(repo, number, body):
    check(body)
    auth = authors(repo)
    before = thread(repo, number)
    if before is None:
        raise Stop(f'unknown: #{number} could not be read before writing; nothing was written')
    seen = {c.get('id') for c in before}
    text = write(f'#{number}', '--method', 'POST', f'repos/{repo}/issues/{number}/comments', '-f', f'body={body}')
    try:
        made = None if text is None else json.loads(text)
    except ValueError:
        made = None
    if not isinstance(made, dict) or type(made.get('id')) is not int:
        raise Stop(f'unknown: the write on #{number} returned no receipt, so no record is adopted; '
                   f'reconcile #{number} before any retry')
    after = thread(repo, number) or []
    found = [c for c in after if c.get('id') == made['id'] and c.get('id') not in seen
             and c.get('body') == body and ours(c, auth)]
    if len(found) != 1:
        raise Stop(f'unknown: the record on #{number} could not be read back; read #{number} before any retry')
    return f"posted {found[0]['id']}"


def edit(repo, comment_id, body):
    check(body)
    auth = authors(repo)
    path = f'repos/{repo}/issues/comments/{comment_id}'
    current = read_json('api', path)
    if not isinstance(current, dict):
        raise Stop(f'unknown: comment {comment_id} could not be read; nothing was written')
    if not ours(current, auth):
        raise Stop(f'refused: comment {comment_id} is not a record author\'s')
    write(f'comment {comment_id}', '--method', 'PATCH', path, '-f', f'body={body}', paced=False)
    back = read_json('api', path)
    if not (ours(back, auth) and back.get('body') == body):
        raise Stop(f'unknown: comment {comment_id} does not read back as the edit; read it before any retry')
    return f'edited {comment_id}'


USAGE = (
    '  post.py comment OWNER/NAME NUMBER BODY   a new comment on an issue or pull request\n'
    "  post.py edit OWNER/NAME COMMENT_ID BODY  an edit of a record author's comment"
)


def main(argv):
    if len(argv) != 4 or argv[0] not in ('comment', 'edit') or not REPO.fullmatch(argv[1]) \
            or not re.fullmatch(r'[1-9][0-9]{0,11}', argv[2]):
        print(USAGE, file=sys.stderr)
        return 2
    try:
        print((comment if argv[0] == 'comment' else edit)(argv[1], int(argv[2]), argv[3]))
    except Stop as outcome:
        print(outcome)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
