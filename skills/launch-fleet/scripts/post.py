#!/usr/bin/env python3
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import fcntl
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('launch_fleet_grants', HERE / 'grants.py')
grants = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(grants)

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


# The write pacer (FR10): every content-creating write takes a slot from its account's bucket, below GitHub's
# secondary limits (about 80 a minute, 500 an hour, 100 concurrent); edits only count toward the in-flight cap.
PER_MINUTE, PER_HOUR, IN_FLIGHT = 60, 400, 20
WINDOW = 30      # seconds a write waits for a slot before it refuses
STALE = 90       # seconds after which an in-flight entry is over (gh's own timeout is 60)
SECONDARY_WAIT = 60  # GitHub's advice when a secondary limit names no time


def stamp(at):
    return datetime.fromtimestamp(at, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def state_path():
    base = os.environ.get('XDG_STATE_HOME') or os.path.join(os.path.expanduser('~'), '.local', 'state')
    return Path(base) / 'launch-fleet' / 'writes.json'


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def valid(value):
    return (isinstance(value, dict) and set(value) == {'accounts', 'inflight', 'until'}
            and isinstance(value['accounts'], dict)
            and all(isinstance(k, str) and isinstance(v, list) and all(number(t) for t in v)
                    for k, v in value['accounts'].items())
            and isinstance(value['inflight'], list)
            and all(isinstance(e, list) and len(e) == 2 and type(e[0]) is int and e[0] > 0 and number(e[1])
                    for e in value['inflight'])
            and number(value['until']))


@contextmanager
def pacer_state():
    """The machine's write state under its lock; saved (atomically) only when the block ends without an error."""
    path = state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = open(path.with_name(path.name + '.lock'), 'a')
    except OSError:
        raise Stop('refused: the write pacer\'s state folder cannot be used; nothing was written')
    with lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            value = json.loads(path.read_text()) if path.exists() else {'accounts': {}, 'inflight': [], 'until': 0}
        except (OSError, ValueError):
            value = None
        if not valid(value):
            raise Stop('refused: the write pacer\'s state file is unreadable; nothing was written')
        yield value
        temp = path.with_name(f'{path.name}.{os.getpid()}.tmp')
        try:
            temp.write_text(json.dumps(value))
            os.replace(temp, path)
        except OSError:
            raise Stop('refused: the write pacer\'s state file cannot be saved; nothing was written')


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def account():
    """The signed-in github.com login from gh's own hosts file (no API call), else one shared 'unknown' bucket."""
    base = os.environ.get('GH_CONFIG_DIR') or os.path.join(
        os.environ.get('XDG_CONFIG_HOME') or os.path.join(os.path.expanduser('~'), '.config'), 'gh')
    try:
        text = Path(base, 'hosts.yml').read_text()
    except (OSError, UnicodeError):
        return 'unknown'
    block = re.search(r'^github\.com:[ \t]*\n((?:[ \t]+.*\n?|\n)*)', text, re.M)
    login = re.search(r'^[ \t]+user:[ \t]*([A-Za-z0-9-]+)[ \t]*$', block.group(1), re.M) if block else None
    return login.group(1) if login else 'unknown'


def take(paced):
    """Take a write slot (and, when paced, a bucket token), waiting up to WINDOW seconds; refuse with no slot."""
    key = account() if paced else None
    deadline = time.time() + WINDOW
    while True:
        with pacer_state() as s:
            now = time.time()
            s['inflight'] = [e for e in s['inflight'] if now - e[1] < STALE and alive(e[0])]
            s['accounts'] = {k: kept for k, v in s['accounts'].items() if (kept := [t for t in v if now - t < 3600])}
            free = s['until']
            times = sorted(s['accounts'].get(key, [])) if paced else []
            recent = [t for t in times if now - t < 60]
            if len(recent) >= PER_MINUTE:
                free = max(free, recent[-PER_MINUTE] + 60)
            if len(times) >= PER_HOUR:
                free = max(free, times[-PER_HOUR] + 3600)
            busy = len(s['inflight']) >= IN_FLIGHT
            if free <= now and not busy:
                if paced:
                    s['accounts'][key] = times + [now]
                entry = [os.getpid(), now]
                s['inflight'].append(entry)
                return entry
            if busy:
                free = max(free, sorted(e[1] for e in s['inflight'])[-IN_FLIGHT] + STALE)
            if free > deadline and (not busy or now >= deadline):
                raise Stop(f'refused: write paced, retry after {stamp(free)}')
        time.sleep(max(0.05, min(0.5 if busy else free - now, deadline - now)))


def release(entry):
    try:
        with pacer_state() as s:
            if entry in s['inflight']:
                s['inflight'].remove(entry)
    except Stop:
        pass  # the entry goes stale and is dropped then


def answer(text):
    """gh api --include output as (status, lowercased headers, body); status None when no head came."""
    head = re.match(r'HTTP/\S+ (\d{3})[^\n]*\n(.*?)\r?\n\r?\n', text, re.S)
    if head is None:
        return None, {}, text
    headers = {}
    for line in head.group(2).splitlines():
        name, sep, value = line.partition(':')
        if sep:
            headers[name.strip().lower()] = value.strip()
    return int(head.group(1)), headers, text[head.end():]


def secondary_wait(status, headers, said):
    """Seconds GitHub asks every writer to wait, or None when this answer is no secondary limit."""
    after = headers.get('retry-after', '')
    named = 'secondary rate limit' in said.lower()
    if status not in (403, 429) or not (after or named):
        return None
    if re.fullmatch(r'[0-9]{1,9}', after):
        return int(after)
    if after:
        try:
            return max(0, parsedate_to_datetime(after).timestamp() - time.time())
        except (TypeError, ValueError):
            return SECONDARY_WAIT
    reset = headers.get('x-ratelimit-reset', '')
    if headers.get('x-ratelimit-remaining') == '0' and re.fullmatch(r'[0-9]{1,12}', reset):
        return max(0, int(reset) - time.time())
    return SECONDARY_WAIT


def write(where, *args, paced=True):
    """One GitHub write through the pacer: its answer's body, or None when it failed.

    A secondary-limit answer records its wait for every writer on this machine and stops, never retried."""
    entry = take(paced)
    try:
        r = subprocess.run(['gh', 'api', '--include', *args], capture_output=True, text=True, timeout=60,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    finally:
        release(entry)
    status, headers, body = answer(r.stdout)
    wait = secondary_wait(status, headers, body + r.stderr)
    if wait is not None:
        until = time.time() + wait
        with pacer_state() as s:
            s['until'] = max(s['until'], until)
        raise Stop(f'unknown: GitHub refused the write on {where} under its secondary rate limit; '
                   f'no write leaves this machine before {stamp(until)}; reconcile {where} before any retry')
    return body if r.returncode == 0 else None


def read_json(*args):
    text = gh(*args)
    try:
        return None if text is None else json.loads(text)
    except ValueError:
        return None


def authors(repo):
    text = gh('api', f'repos/{repo}/contents/docs/agents/fleet.md', '-H', 'Accept: application/vnd.github.raw+json')
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
