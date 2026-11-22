#!/usr/bin/env python3
import argparse
import contextlib
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import os
import re
import signal
import subprocess
import sys
import time
from urllib.parse import quote

sys.dont_write_bytecode = True

MARKER = '<!-- openwiz:status v1 -->'
LEASE = timedelta(minutes=30)
EVERY = 600
EVERY_MOST = 900
RETRY = 60
MARGIN = 120
GRACE = 10
KINDS = ('builder', 'reviewer', 'fleet')
STATES = ('working', 'asking', 'done', 'stopped')
CLAIMING = ('working', 'asking')
ASKING_LABEL = 'needs-info'
ASKED_WITHIN = timedelta(minutes=2)
KEYS = (('agent', 300, True), ('state', 300, True), ('harness', 60, True), ('model', 60, True),
        ('skills', 300, True), ('step', 300, True), ('time', 300, True), ('pr', 300, False), ('preview', 300, False))
REPO = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')
TIME = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z')
STATE = re.compile(r'(working|asking|done|stopped)( \(([^()]{1,100})\))?')
SKILL = r'[a-z0-9]+(?:-[a-z0-9]+)*@[0-9]+\.[0-9]+\.[0-9]+'
SKILLS = re.compile(rf'{SKILL}(?:, {SKILL})*')
PR = re.compile(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[1-9][0-9]*')
PREVIEW = re.compile(r'https://(?![^/:]*\.(?:local|internal|lan|localhost)(?:[:/]|$))'
                     r'(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}(?::[0-9]{1,5})?(?:/[^\s"<>?#@\\]*)?')
CONTROL = re.compile(r'[\x00-\x1f\x7f]')
QUOTE = re.compile('["“”]')
LINK = re.compile(r'\bhttps?://[A-Za-z0-9.-]+(?::[0-9]{1,5})?(?:/[^\s"\'<>?#]*)?', re.I)
PART = r'(?:[\w.~+-]|\\.)(?:[\w.~+-]|\\.| (?=[\w.~+-]))*'


class OffLinks:

    def __init__(self, pattern, flags=0):
        self.pattern = re.compile(pattern, flags)

    def search(self, text):
        return self.pattern.search(LINK.sub('link', text))


PRIVATE = (
    ('a thread id', re.compile(r'(?<![A-Za-z0-9])thr_', re.I)),
    ('a CloudRoom id', re.compile(r'(?<![A-Za-z0-9])(?:proj|prj|mch|usr|acct|auto|cr)_[A-Za-z0-9]', re.I)),
    ('a machine path', re.compile(
        r'(?<![\w.:/~-])(?:~/|/(?:Users|home|root|tmp|var|private|mnt|Volumes|opt|srv|code)(?:/|\b))', re.I)),
    ('a machine path', re.compile(r'(?<![A-Za-z0-9])[A-Za-z]:\\')),
    ('a machine path', OffLinks(r'[\w.-]:[\'"]?~?/(?!/)')),
    ('a machine path', re.compile(rf'(?<![\w.:/~@%$}}\\-])/{PART}/[\w.~+-]')),
    ('a machine path', re.compile(r'\$\{?HOME\b|%(?:USERPROFILE|HOMEPATH|HOMEDRIVE|APPDATA|LOCALAPPDATA)%', re.I)),
    ('a machine path', re.compile(r'\\\\[\w.$-]+\\')),
    ('a machine path', re.compile(r'\bfile:', re.I)),
    ('a credential', re.compile(
        r'\b(?:[a-z0-9_]*token|[a-z0-9_]*key|secret|password|passwd|pwd|sig|signature|auth|credentials?)\s*=', re.I)),
    ('a credential', re.compile(r'\b(?:password|passwd|secret|token)\s*:\s*\S|\bbearer\s+\S', re.I)),
    ('a credential', OffLinks(r'\b(?:[a-z0-9_]*token|[a-z0-9_]*key|auth)\s*:\s*\S', re.I)),
    ('a credential', re.compile(r'\bgh[pousr]_[A-Za-z0-9]{8,}|\bgithub_pat_|\bAKIA[0-9A-Z]{16}\b'
                                r'|\bxox[abprs]-|\bsk-[A-Za-z0-9_-]{16,}')),
)
MANIFEST = Path(__file__).resolve().parents[3] / '.claude-plugin' / 'plugin.json'


class Refused(Exception):
    pass


class Failed(Exception):
    pass


class Stop(Exception):
    pass


def refuse(field, why):
    raise Refused(f'{field}: {why}')


def plain(field, value, longest):
    if not value:
        refuse(field, 'empty')
    if CONTROL.search(value):
        refuse(field, 'not one line of plain text')
    if len(value) > longest:
        refuse(field, f'longer than {longest} characters')
    for what, pattern in PRIVATE:
        if pattern.search(value):
            refuse(field, f'holds {what}')
    if QUOTE.search(value) or value.startswith('>'):
        refuse(field, 'holds quoted words')


def shaped(fields):
    for key, longest, required in KEYS:
        if key in fields:
            plain(key, fields[key], longest)
        elif required:
            refuse(key, 'missing')
    if fields['agent'] not in KINDS:
        refuse('agent', 'not builder, reviewer or fleet')
    if not STATE.fullmatch(fields['state']) or (fields['state'].startswith(('working', 'asking', 'done'))
                                                 and fields['state'] not in STATES):
        refuse('state', 'not working, asking, done, stopped or stopped (<why>)')
    if not SKILLS.fullmatch(fields['skills']):
        refuse('skills', 'not <skill>@<major>.<minor>.<patch>, joined by a comma and a space')
    if not TIME.fullmatch(fields['time']):
        refuse('time', 'not YYYY-MM-DDTHH:MM:SSZ')
    if 'pr' in fields and not PR.fullmatch(fields['pr']):
        refuse('pr', 'not a GitHub pull request link')
    if 'preview' in fields and not PREVIEW.fullmatch(fields['preview']):
        refuse('preview', 'not an https link')


def bound(skills):
    try:
        listed = json.loads(MANIFEST.read_text())['skills']
        if not (isinstance(listed, list) and all(isinstance(x, str) for x in listed)):
            raise ValueError('malformed')
    except (OSError, ValueError, KeyError, TypeError):
        refuse('skills', 'the installed package has no readable manifest')
    names = {x[len('./skills/'):] for x in listed if x.startswith('./skills/')}
    for item in skills.split(', '):
        name, _, at = item.partition('@')
        if name not in names or at != installed(name):
            refuse('skills', 'a skill or version the installed package does not have')


def installed(name):
    try:
        lines = (MANIFEST.parents[1] / 'skills' / name / 'SKILL.md').read_text().split('\n')
    except (OSError, UnicodeDecodeError):
        return None
    if lines[0] != '---' or '---' not in lines[1:]:
        return None
    front = lines[1:lines.index('---', 1)]
    found = [line[len('version:'):].strip() for line in front if line.startswith('version:')]
    if len(found) != 1:
        return None
    value = found[0]
    if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
        value = value[1:-1]
    return value if re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', value) else None


def body(fields):
    return '\n'.join([MARKER] + [f'{key}: {fields[key]}' for key, _, _ in KEYS if key in fields])


def parse(text):
    lines = (text or '').replace('\r\n', '\n').split('\n')
    if lines[0] != MARKER:
        return None
    fields = {}
    for line in lines[1:]:
        key, sep, value = line.partition(': ')
        if not sep or key in fields or key not in dict((k, 0) for k, _, _ in KEYS):
            return None
        fields[key] = value
    try:
        shaped(fields)
    except Refused:
        return None
    return fields


def gh(method, path, payload=None, accept=None, raw=False):
    command = ['gh', 'api', '--method', method, path]
    if accept:
        command += ['-H', accept]
    if payload is not None:
        command += ['--input', '-']
    try:
        result = subprocess.run(command, input=None if payload is None else json.dumps(payload),
                                capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Failed(f'{method} {path}: {error}')
    if result.returncode != 0:
        raise Failed(f'{method} {path}: {result.stderr.strip()[:300]}')
    if raw:
        return result.stdout
    try:
        return json.loads(result.stdout) if result.stdout.strip() else None
    except ValueError:
        raise Failed(f'{method} {path}: not JSON')


def pages(path):
    items, page = [], 1
    while True:
        chunk = gh('GET', f'{path}?per_page=100&page={page}')
        if not isinstance(chunk, list):
            raise Failed(f'GET {path}: not a list')
        if not chunk:
            return items
        items += chunk
        page += 1


def record_authors(repo):
    spec = importlib.util.spec_from_file_location('grants', Path(__file__).resolve().parent / 'grants.py')
    grants = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(grants)
    try:
        text = gh('GET', f'repos/{repo}/contents/docs/agents/fleet.md',
                  accept='Accept: application/vnd.github.raw', raw=True)
        return grants.record_authors(text)
    except (Failed, ValueError) as error:
        raise Failed(f'no record authors in docs/agents/fleet.md: {error}')


def when(stamp):
    return datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)


def notes(comments, authors):
    found = []
    for item in comments:
        login = item['user']['login'] if isinstance(item.get('user'), dict) else None
        fields = parse(item.get('body'))
        if isinstance(login, str) and login.lower() in authors and fields:
            found.append((int(item['id']), fields, when(item['updated_at']), login.lower()))
    return sorted(found, key=lambda n: n[0])


def live(note, now):
    return note[1]['state'] in CLAIMING and now - note[2] < LEASE


def holder(found, kind, now):
    return next((n for n in found if n[1]['agent'] == kind and live(n, now)), None)


def viewer():
    try:
        login = gh('POST', 'graphql', {'query': 'query { viewer { login } }'})['data']['viewer']['login']
    except (Failed, KeyError, TypeError):
        return None
    return login if isinstance(login, str) and login else None


EDITS = '''query($id: ID!, $n: Int!) {
  node(id: $id) { ... on IssueComment { userContentEdits(first: $n) { nodes { diff editedAt } } } }
}'''
HISTORY = 20


def replaced(made, fields, floor=None):
    try:
        found = gh('POST', 'graphql', {'query': EDITS, 'variables': {'id': made['node_id'], 'n': HISTORY}})
        nodes = found['data']['node']['userContentEdits']['nodes']
        texts = [x['diff'] for x in nodes]
        stamps = [x['editedAt'] for x in nodes]
    except (KeyError, TypeError, ValueError) as error:
        raise Failed(f'note {made.get("id")} was edited but its edit history was not read: {error!r}')
    if not all(isinstance(x, str) for x in texts + stamps):
        raise Failed(f'note {made.get("id")} was edited but its edit history was not read')
    versions = [parse(x) for x in texts]
    k = next((j for j, v in enumerate(versions) if v == fields), None)
    if k is None:
        raise Failed(f'note {made.get("id")} was edited but its edit history does not hold the edit')
    same = {key: value for key, value in fields.items() if key != 'time'}
    first = k = k + 1
    while (k < len(versions) and versions[k] and dict(versions[k], time=None) == dict(same, time=None)
           and not (floor is not None and versions[k]['time'] <= floor)):
        k += 1
    if k < len(versions):
        if k > first and versions[k] and versions[k]['state'] not in CLAIMING:
            try:
                unread = when(stamps[k].replace('.000', '')[:19] + 'Z') >= when(versions[k - 1]['time'])
            except ValueError:
                raise Failed(f'note {made.get("id")} was edited but its edit history has no readable time')
            if not unread:
                return texts[k - 1]
        return texts[k]
    if len(texts) >= HISTORY:
        raise Failed(f'note {made.get("id")} was edited but its edit history is too long to read past it')
    return None


def step_down(found, note_id, kind, fields, repo):
    other = next((x for x in found if x[0] != note_id and x[1]['agent'] == kind
                  and live(x, datetime.now(timezone.utc))), None)
    if other:
        gh('PATCH', f'repos/{repo}/issues/comments/{note_id}',
           {'body': body(dict(fields, state='stopped (lost claim)'))})
        raise Stop(f'note {other[0]} holds the {kind} claim; note {note_id} is stopped (lost claim)')


def next_beat(now, ok_at, every, failed):
    deadline = ok_at + LEASE.total_seconds() - MARGIN
    if now >= deadline:
        return None
    due = now + min(RETRY, every) if failed else ok_at + every
    return max(0, min(due, deadline) - now)


def stop_group(proc):
    def alive():
        proc.poll()
        try:
            os.killpg(proc.pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
    if not alive():
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    end = time.monotonic() + GRACE
    while time.monotonic() < end and alive():
        time.sleep(0.1)
    if alive():
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    proc.wait()


def proof(repo, n):
    home = Path(os.environ.get('XDG_STATE_HOME') or '.')
    home = home if home.is_absolute() else Path.home() / '.local' / 'state'
    return home / 'openwiz' / 'needs-info' / f'{quote(repo.lower(), safe="")}-{n}.json'


@contextlib.contextmanager
def settling(repo, n):
    lock = None
    try:
        import fcntl
        proof(repo, n).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock = open(proof(repo, n).with_suffix('.lock'), 'a')
        fcntl.flock(lock, fcntl.LOCK_EX)
    except (ImportError, OSError):
        if lock is not None:
            lock.close()
            lock = None
    try:
        yield lock is not None
    finally:
        if lock is not None:
            lock.close()


def forget(repo, n):
    try:
        proof(repo, n).unlink()
    except OSError:
        pass


def add_own(repo, n, login, locked):
    forget(repo, n)
    try:
        before = len(label_events(repo, n))
    except Failed:
        before = None
    gh('POST', f'repos/{repo}/issues/{n}/labels', {'labels': [ASKING_LABEL]})
    if before is None or not app(login) or not locked:
        return
    try:
        new = label_events(repo, n)[before:]
    except Failed:
        return
    if len(new) == 1 and new[0]['event'] == 'labeled' and by(new[0], login):
        keep(repo, n, login, before)


def keep(repo, n, login, event):
    path = proof(repo, n)
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.with_suffix('.tmp').write_text(json.dumps({'login': login.lower(), 'event': event}))
        os.replace(path.with_suffix('.tmp'), path)
        return True
    except OSError:
        return False


def left_on(n):
    return [f'#{n}: {ASKING_LABEL} left on: no note asks, and this writer can\'t show its own write '
            'added it; a person takes it off']


def held(repo, n, comments, authors):
    now = datetime.now(timezone.utc)
    if any(x[1]['state'] == 'asking' and live(x, now) for x in notes(pages(comments), authors)):
        return []
    labels = [label['name'] for label in gh('GET', f'repos/{repo}/issues/{n}')['labels']]
    return left_on(n) if ASKING_LABEL in labels else []


def asked_label(repo, n, made, fields, author):
    try:
        found = gh('POST', 'graphql', {'query': EDITS, 'variables': {'id': made['node_id'], 'n': HISTORY}})
        nodes = found['data']['node']['userContentEdits']['nodes']
        versions = [(parse(x['diff']), x['editedAt']) for x in nodes]
        k = next(j for j, (v, _) in enumerate(versions) if v == fields) + 1
        start = None
        while k < len(versions) and versions[k][0] and versions[k][0]['state'] == 'asking':
            start, k = versions[k][1], k + 1
        if start is None or k >= HISTORY:
            return None
        asked = when(start.replace('.000', '')[:19] + 'Z')
        events = label_events(repo, n)
        stamps = [when(e['created_at']) if TIME.fullmatch(e.get('created_at') or '') else None for e in events]
        first = next((j for j, t in enumerate(stamps) if t is None or t >= asked), None)
        if (first is None or stamps[first] is None or events[first]['event'] != 'labeled'
                or not by(events[first], author)):
            return None
        return first if stamps[first] <= asked + ASKED_WITHIN else None
    except (Failed, StopIteration, KeyError, TypeError, AttributeError, ValueError):
        return None


def take_own(repo, n, login, labels, asked=None, locked=False):
    def labelled():
        return ASKING_LABEL in [label['name'] for label in gh('GET', f'repos/{repo}/issues/{n}')['labels']]
    def once(pairs):
        if len({k for k, _ in pairs}) != len(pairs):
            raise ValueError('a repeated key')
        return dict(pairs)
    try:
        own = json.loads(proof(repo, n).read_text(), object_pairs_hook=once)
    except (OSError, ValueError):
        own = None
    exact = isinstance(own, dict) and set(own) == {'login', 'event'} and own['login'] == login.lower()
    mine = own['event'] if exact and type(own['event']) is int and own['event'] >= 0 else None
    left = left_on(n)
    if mine is None and asked is not None and not app(asked[2]) and ASKING_LABEL in labels:
        found = asked_label(repo, n, *asked)
        mine = found if found is not None and locked and keep(repo, n, login, found) else None
    if mine is None:
        forget(repo, n)
        return left if ASKING_LABEL in labels else []
    report = cleanup(repo, n, login, mine, labelled, 'this write')
    report = report or (left if labelled() else [])
    forget(repo, n)
    return report


def write(args, now, beat=False, out=sys.stdout, retried=False):
    if not beat:
        state = args.state if args.why is None else f'{args.state} ({args.why})'
        if args.why is not None and args.state != 'stopped':
            refuse('state', 'only stopped carries a reason')
        fields = {'agent': args.agent, 'state': state, 'harness': args.harness, 'model': args.model,
                  'step': args.step, 'time': args.time or now.strftime('%Y-%m-%dT%H:%M:%SZ')}
        for key in ('skills', 'pr', 'preview'):
            if getattr(args, key) is not None:
                fields[key] = getattr(args, key)
        shaped(fields)
        bound(fields['skills'])
    if args.note is not None and not re.fullmatch(r'[1-9][0-9]*', args.note):
        refuse('note', 'not a comment id')
    repo, n, kind = args.repo, args.ticket, args.agent
    authors = record_authors(repo)
    login = viewer()
    if login is not None and login.lower() not in authors:
        raise Failed(f'the acting login {login} is not a record author in docs/agents/fleet.md')
    comments = f'repos/{repo}/issues/{n}/comments'
    found = notes(pages(comments), authors)
    if args.note is not None:
        own = next((x for x in found if x[0] == int(args.note)), None)
        if own is None:
            raise Stop(f'note {args.note} is not a record author\'s status note on #{n}')
        if own[1]['agent'] != kind:
            raise Stop(f'note {args.note} is a {own[1]["agent"]} note')
        if own[1]['state'].startswith('stopped'):
            raise Stop(f'note {args.note} is {"stopped: a heartbeat never reopens it" if beat else "stopped"}')
        if beat:
            if own[1]['state'] not in CLAIMING:
                raise Stop(f'note {args.note} is {own[1]["state"]}: a heartbeat never reopens it')
            fields = dict(own[1], time=now.strftime('%Y-%m-%dT%H:%M:%SZ'))
            if fields == own[1]:
                if retried:
                    raise Failed(f'note {args.note} already holds this second; nothing to beat')
                time.sleep(1)
                return write(args, datetime.now(timezone.utc), beat, out, retried=True)
            if args.floor is None:
                args.floor = own[1]['time']
            state = args.state = fields['state']
        first = holder(found, kind, now)
        if first and first[0] != own[0]:
            raise Stop(f'note {first[0]} holds the {kind} claim')
        made = gh('PATCH', f'repos/{repo}/issues/comments/{own[0]}', {'body': body(fields)})
        note_id, verb = own[0], 'edited'
    else:
        first = holder(found, kind, now)
        if args.state in CLAIMING and first:
            raise Stop(f'note {first[0]} holds the {kind} claim')
        made = gh('POST', comments, {'body': body(fields)})
        note_id, verb = int(made['id']), 'posted'
    author = made['user']['login'] if isinstance(made.get('user'), dict) else None
    if not (isinstance(author, str) and author.lower() in authors):
        if verb == 'posted':
            gh('DELETE', f'repos/{repo}/issues/comments/{note_id}')
        raise Failed(f'note {note_id} was written by {author}, not a record author; it was deleted')
    login = login or author
    found = notes(pages(comments), authors)
    mine = next((x for x in found if x[0] == note_id), None)
    if verb == 'edited' and args.state in CLAIMING:
        try:
            prior = parse(replaced(made, fields, args.floor if beat else None))
        except Failed:
            step_down(found, note_id, kind, fields, repo)
            if not beat and own[1]['state'] == 'asking':
                with contextlib.suppress(Failed, KeyError, TypeError, IndexError, ValueError):
                    for line in held(repo, n, comments, authors):
                        print(line, file=out)
            raise
        if prior and prior['state'] not in CLAIMING and prior != own[1]:
            if mine is None:
                raise Failed(f'note {note_id} was edited over a release but not read back')
            if mine[1]['state'] in CLAIMING:
                gh('PATCH', f'repos/{repo}/issues/comments/{note_id}', {'body': body(prior)})
            raise Stop(f'note {note_id} was {prior["state"].split(" ")[0]} before this edit landed; '
                       'the release is put back')
    if mine is None or mine[1] != fields:
        raise Failed(f'note {note_id} was {verb} but not read back')
    if verb == 'posted' and args.state in CLAIMING:
        first = holder(found, kind, datetime.now(timezone.utc))
        if first and first[0] < note_id:
            gh('PATCH', f'repos/{repo}/issues/comments/{note_id}',
               {'body': body(dict(fields, state='stopped (lost claim)'))})
            raise Stop(f'note {first[0]} holds the {kind} claim; note {note_id} is stopped (lost claim)')
    if verb == 'edited' and args.state in CLAIMING:
        step_down(found, note_id, kind, fields, repo)
    report = []
    with settling(repo, n) as locked:
        found = notes(pages(comments), authors)
        labels = [label['name'] for label in gh('GET', f'repos/{repo}/issues/{n}')['labels']]
        asking = any(x[1]['state'] == 'asking' and live(x, datetime.now(timezone.utc)) for x in found)
        if asking and ASKING_LABEL not in labels:
            add_own(repo, n, login, locked)
        elif not beat and not asking:
            asked = (made, fields, author) if (verb == 'edited' and own[1]['state'] == 'asking'
                                               and args.state in ('working', 'done')) else None
            report = take_own(repo, n, login, labels, asked, locked)
    print(f'#{n}: {kind} {state}, status note {note_id} {verb}', file=out)
    for line in report:
        print(line, file=out)
    return fields


def run(args):
    command = args.cmd[1:] if args.cmd[:1] == ['--'] else args.cmd
    if not command:
        refuse('command', 'missing: run --note ID -- COMMAND...')
    if not re.fullmatch(r'[1-9][0-9]*', args.every) or int(args.every) > EVERY_MOST:
        refuse('every', f'not a whole number of seconds from 1 to {EVERY_MOST}')
    if args.note is None or not re.fullmatch(r'[1-9][0-9]*', args.note):
        refuse('note', 'not a comment id')
    every = int(args.every)
    args.floor = None
    ok_at = time.monotonic()
    try:
        args.floor = write(args, datetime.now(timezone.utc), beat=True, out=sys.stderr)['time']
    except Stop as error:
        raise Stop(f'{error}; the command was not started')
    try:
        proc = subprocess.Popen(command, start_new_session=True)
    except OSError as error:
        raise Failed(f'command: could not start: {error.strerror}')
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda number, _: sys.exit(128 + number))
    failed, finished = False, False
    try:
        while True:
            wait = next_beat(time.monotonic(), ok_at, every, failed)
            if wait is None:
                raise Stop(f'note {args.note} could not be kept live inside the lease; the command is stopped')
            try:
                code = proc.wait(timeout=wait)
                finished = True
                return code if code >= 0 else 128 - code
            except subprocess.TimeoutExpired:
                pass
            started = time.monotonic()
            try:
                args.floor = write(args, datetime.now(timezone.utc), beat=True, out=sys.stderr)['time']
                ok_at, failed = started, False
            except Stop as error:
                raise Stop(f'{error}; the command is stopped')
            except (Failed, KeyError, TypeError, IndexError, ValueError) as error:
                failed = True
                print(f'status.py: heartbeat failed, trying again in {min(RETRY, every)}s: {error}',
                      file=sys.stderr)
    finally:
        if not finished:
            stop_group(proc)

QUERY = '''query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    issues(states: OPEN, first: 50, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number
        labels(first: 100) { nodes { name } }
        comments(first: 100) { pageInfo { hasNextPage } nodes { databaseId author { login } body updatedAt } }
        closedByPullRequestsReferences(first: 50, includeClosedPrs: true) { nodes { number state url } }
      }
    }
  }
}'''


def mismatches(number, labels, found, prs, now):
    lines = []
    merged = [pr['url'] for pr in prs if pr['state'] == 'MERGED']
    for note in found:
        nid, fields, updated = note[:3]
        state, kind = fields['state'], fields['agent']
        if state not in CLAIMING:
            continue
        head = f'#{number} note {nid} {kind} {state}'
        first = holder(found, kind, now)
        if merged:
            lines.append(f'{head}: pull request {merged[0]} merged')
        elif not live(note, now):
            lines.append(f'{head}: lapsed, no edit for 30 minutes')
        elif state == 'asking' and ASKING_LABEL not in labels:
            lines.append(f'{head}: no {ASKING_LABEL} label')
        elif first[0] != nid:
            lines.append(f'{head}: note {first[0]} holds the {kind} claim')
    return lines


def scan(repo, authors, now):
    owner, name = repo.split('/')
    cursor, found = None, []
    while True:
        page = gh('POST', 'graphql', {'query': QUERY,
                                      'variables': {'owner': owner, 'name': name, 'cursor': cursor}})
        issues = page['data']['repository']['issues']
        for issue in issues['nodes']:
            if issue['comments']['pageInfo']['hasNextPage']:
                comments = pages(f'repos/{repo}/issues/{issue["number"]}/comments')
            else:
                comments = [{'id': c['databaseId'], 'user': c['author'], 'body': c['body'],
                             'updated_at': c['updatedAt']} for c in issue['comments']['nodes']]
            own = notes(comments, authors)
            found.append((issue['number'], own, mismatches(
                issue['number'], [label['name'] for label in issue['labels']['nodes']],
                own, issue['closedByPullRequestsReferences']['nodes'], now)))
        if not issues['pageInfo']['hasNextPage']:
            break
        cursor = issues['pageInfo']['endCursor']
    return found


def check(args, now):
    found = [line for _, _, lines in scan(args.repo, record_authors(args.repo), now) for line in lines]
    for line in found:
        print(line)
    return 1 if found else 0


REPAIRING = 'adding needs-info for an asking note'
REPAIRED = 'settled needs-info'


def stamp():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def record(repo, n, base, state, step, note_id=None):
    fields = dict(base, state=state, step=step, time=stamp())
    if note_id is None:
        made = gh('POST', f'repos/{repo}/issues/{n}/comments', {'body': body(fields)})
    else:
        made = gh('PATCH', f'repos/{repo}/issues/comments/{note_id}', {'body': body(fields)})
    if not (isinstance(made.get('updated_at'), str) and TIME.fullmatch(made['updated_at'])):
        raise Failed(f'the repair note on #{n} was written but GitHub gave no time for it')
    return int(made['id']), made['updated_at']


def label_events(repo, n):
    return [e for e in pages(f'repos/{repo}/issues/{n}/events')
            if e.get('event') in ('labeled', 'unlabeled') and (e.get('label') or {}).get('name') == ASKING_LABEL]


def by(event, login):
    actor = (event.get('actor') or {}).get('login')
    return isinstance(actor, str) and actor.lower() == login.lower()


def cleanup(repo, n, login, mine, labelled, taker='the repair'):
    events = label_events(repo, n)
    if labelled():
        last = max((k for k, e in enumerate(events) if e['event'] == 'labeled'), default=None)
        if last != mine:
            return []
        gh('DELETE', f'repos/{repo}/issues/{n}/labels/{ASKING_LABEL}')
        events = label_events(repo, n)
    after = events[mine + 1:]
    off = [k for k, e in enumerate(after) if e['event'] == 'unlabeled' and by(e, login)]
    if not off:
        return []
    people = [e for e in after[:off[-1]] if e['event'] == 'labeled' and not by(e, login)]
    if not people or labelled():
        return []
    gh('POST', f'repos/{repo}/issues/{n}/labels', {'labels': [ASKING_LABEL]})
    who = people[-1]['actor']['login']
    return [f'#{n}: {ASKING_LABEL} put back: {who} applied it as {taker} took it off; check whose it is']


def app(login):
    return login.endswith('[bot]')


def left(repo, n, login, labelled):
    if not labelled():
        return []
    applied = [e for e in label_events(repo, n) if e['event'] == 'labeled']
    if applied and not by(applied[-1], login):
        return []
    return [f'#{n}: {ASKING_LABEL} left on: no note asks, and the repair can\'t tell whether it or a person '
            'added it; check whose it is']


def settle(repo, n, authors, login, base, pending):
    comments = f'repos/{repo}/issues/{n}/comments'

    def asking():
        now = datetime.now(timezone.utc)
        return next((x for x in notes(pages(comments), authors) if x[1]['state'] == 'asking' and live(x, now)), None)

    def labelled():
        return ASKING_LABEL in [label['name'] for label in gh('GET', f'repos/{repo}/issues/{n}')['labels']]

    still = asking()
    if pending is None:
        if still is None or labelled():
            return []
        fleet = [x for x in notes(pages(comments), authors) if x[1]['agent'] == 'fleet' and x[3] == login.lower()]
        note_id = record(repo, n, base, 'working', REPAIRING, fleet[-1][0] if fleet else None)[0]
    else:
        note_id = pending[0]
    report, mine = [], None
    if still is not None and not labelled():
        before = len(label_events(repo, n))
        gh('POST', f'repos/{repo}/issues/{n}/labels', {'labels': [ASKING_LABEL]})
        new = label_events(repo, n)[before:]
        if app(login) and len(new) == 1 and new[0]['event'] == 'labeled' and by(new[0], login):
            mine = before
        still = asking()
        if still is not None:
            report.append(f'#{n} note {still[0]} {still[1]["agent"]} asking: {ASKING_LABEL} added')
    if still is None:
        report += left(repo, n, login, labelled) if mine is None else cleanup(repo, n, login, mine, labelled)
    record(repo, n, base, 'done', REPAIRED, note_id)
    return report


def guarded(what, act):
    try:
        return act()
    except Failed as error:
        raise Failed(f'{what}: {error}')
    except (KeyError, TypeError, IndexError, ValueError) as error:
        raise Failed(f'{what}: unexpected GitHub answer: {error!r}')


def repair(args, now):
    base = {'agent': 'fleet', 'harness': args.harness, 'model': args.model, 'skills': args.skills}
    try:
        shaped(dict(base, state='working', step=REPAIRING, time=stamp()))
        bound(args.skills)
    except Refused as error:
        raise Failed(f'refused: {error}')

    def read():
        authors = record_authors(args.repo)
        return authors, scan(args.repo, authors, now)

    authors, found = guarded('could not read', read)
    login = viewer()
    reported = 0
    for n, own, lines in found:
        pending = None if login is None else next(
            (x for x in reversed(own) if x[1]['agent'] == 'fleet' and x[3] == login.lower()
             and x[1]['state'] == 'working' and x[1]['step'] == REPAIRING), None)
        asks = any(line.endswith(f': no {ASKING_LABEL} label') for line in lines)
        if login is not None and (asks or pending):
            settled = guarded(f'could not repair #{n}', lambda: settle(args.repo, n, authors, login, base, pending))
            lines = [line for line in lines if not line.endswith(f': no {ASKING_LABEL} label')
                     and not (pending and line.startswith(f'#{n} note {pending[0]} '))] + settled
        for line in lines:
            print(line, flush=True)
            reported += 1
    return 1 if reported else 0


def main(argv):
    parser = argparse.ArgumentParser(prog='status.py')
    sub = parser.add_subparsers(dest='command', required=True)
    w = sub.add_parser('write')
    for flag in ('--repo', '--ticket', '--agent', '--state', '--harness', '--model', '--step'):
        w.add_argument(flag, required=True)
    for flag in ('--skills', '--why', '--pr', '--preview', '--time', '--note'):
        w.add_argument(flag)
    r = sub.add_parser('run')
    for flag in ('--repo', '--ticket', '--agent', '--note'):
        r.add_argument(flag, required=True)
    r.add_argument('--every', default=str(EVERY))
    r.add_argument('cmd', nargs=argparse.REMAINDER, metavar='COMMAND')
    c = sub.add_parser('check')
    c.add_argument('--repo', required=True)
    r = sub.add_parser('repair')
    for flag in ('--repo', '--harness', '--model', '--skills'):
        r.add_argument(flag, required=True)
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    try:
        if not REPO.fullmatch(args.repo):
            raise Refused('repo: not OWNER/NAME')
        if args.command == 'check':
            try:
                return check(args, now)
            except Failed as error:
                raise Failed(f'could not read: {error}')
            except (KeyError, TypeError, IndexError, ValueError) as error:
                raise Failed(f'could not read: unexpected GitHub answer: {error!r}')
        if args.command == 'repair':
            try:
                return repair(args, now)
            except Failed as error:
                print(f'status check failed: {error}')
                return 2
        if not re.fullmatch(r'[1-9][0-9]*', args.ticket):
            raise Refused('ticket: not an issue number')
        if args.command == 'run':
            if args.agent not in KINDS:
                raise Refused('agent: not builder, reviewer or fleet')
            try:
                return run(args)
            except (KeyError, TypeError, IndexError, ValueError) as error:
                raise Failed(f'unexpected GitHub answer: {error!r}')
        try:
            write(args, now)
        except (KeyError, TypeError, IndexError, ValueError) as error:
            raise Failed(f'unexpected GitHub answer: {error!r}')
        return 0
    except Refused as error:
        print(f'status.py: refused: {error}', file=sys.stderr)
        return 2
    except Stop as error:
        print(f'status.py: stop: {error}', file=sys.stderr)
        return 3
    except Failed as error:
        print(f'status.py: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
