#!/usr/bin/env python3
"""C8 (#2315): one installation-authenticated, shared, cached and paced GitHub read.

  read.py rest REPO ENDPOINT [--accept MEDIA] [--single-page] OPTIONS
  read.py graphql REPO [--variables JSON] OPTIONS          (the query on stdin)
  OPTIONS: --purpose display|authority --max-age SECONDS [--challenge UNIX]
           [--state-dir DIR] [--api-base URL]

Implements contracts/agent-github-reads.v1.md. stdout carries the complete
response bodies (one per REST page) only on success; stderr carries one line,
`<outcome>: <reason>[ until=<unix>]`. Exit 0 fresh/display, 1 refused or
deferred, 2 invalid invocation. Tokens, keys, URLs and provider bodies are
never printed. Only GET under repos/<REPO>/ and GraphQL queries are accepted.
"""
import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.dont_write_bytecode = True
TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS / 'github-app'))
import app  # noqa: E402  the established App guards (state path, owner-only files)

MINT = TOOLS / 'github-app' / 'mint-token.py'
HOST = 'api.github.com'
API_VERSION = '2022-11-28'
ACCEPT = ('application/vnd.github+json', 'application/vnd.github.raw+json')
NAMESPACE = 'github-reads'
MAX_PAGES = 100
PAGE_BYTES = 8 * 1024 * 1024
WAIT_S = 60          # longest wait on another process's identical read
SHORT_WAIT_S = 1.0   # pacing waits up to this inside one read; longer ones defer
LOW_BUDGET = 0.1     # pace reads once a pool falls below this fraction
BACKOFF_MIN_S, BACKOFF_MAX_S = 60, 3600
REPO = re.compile(r'[a-z0-9-]+/[a-z0-9_.-]+')
SEGMENT = re.compile(r'[A-Za-z0-9_.,@:+=-]+')
QUERY = re.compile(r'[A-Za-z0-9_.,%:+=&@/*-]*')
NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')


class Outcome(Exception):
    def __init__(self, state, reason, until=None):
        super().__init__(state)
        self.state, self.reason, self.until = state, reason, until

    def line(self):
        return f'{self.state}: {self.reason}' + (f' until={int(self.until)}' if self.until else '')


def refuse(reason):
    raise Outcome('refused', reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


# ---- The complete, allowlisted request -----------------------------------

def rest_request(repo, endpoint, accept, single_page):
    """GET repos/<REPO>/... only: no host, scheme, credentials or traversal."""
    path, _, query = endpoint.partition('?')
    parts = path.split('/')
    if (accept not in ACCEPT or len(parts) < 3 or parts[0] != 'repos' or
            any(not SEGMENT.fullmatch(p) or p in ('.', '..') for p in parts) or
            QUERY.fullmatch(query) is None):
        refuse('shape')
    if f'{parts[1]}/{parts[2]}'.lower() != repo:
        refuse('binding')
    pairs = urllib.parse.parse_qsl(query, keep_blank_values=True)
    return {'host': HOST, 'repository': repo, 'api': 'rest', 'method': 'GET',
            'path': '/' + path, 'query': [list(p) for p in pairs], 'raw_query': query,
            'accept': accept, 'api_version': API_VERSION,
            'pagination': {'follow': not single_page, 'max_pages': MAX_PAGES}}


def graphql_operations(document):
    """The one read operation in DOCUMENT, or refuse: no mutation, subscription or literal."""
    if '"' in document or len(document) > 64 * 1024:
        refuse('shape')  # values travel only as variables, so they are bound and hashed
    tokens = re.findall(r'[A-Za-z_][A-Za-z0-9_]*|[{}()]|[^\s,A-Za-z_{}()]+',
                        re.sub(r'#[^\n]*', ' ', document))
    depth, expecting, queries = 0, True, 0
    for token in tokens:
        if token in '{(':
            if depth == 0 and expecting and token == '{':
                queries, expecting = queries + 1, False  # an anonymous query
            depth += 1
        elif token in '})':
            depth -= 1
            if depth < 0:
                refuse('shape')
            if depth == 0 and token == '}':
                expecting = True
        elif depth == 0 and expecting:
            if token not in ('query', 'fragment'):
                refuse('shape')
            queries += token == 'query'
            expecting = False
    if depth != 0 or queries != 1:
        refuse('shape')


# A bounded selection grammar: unknown composite fields, fragments, directives,
# input objects and defaults refuse. Single-object fields are explicit; every
# other composite must be a bounded connection with both pagination flags.
SINGLE_OBJECTS = frozenset(('repository', 'viewer', 'user', 'organization', 'node',
                           'issue', 'pullRequest', 'commit', 'author', 'committer',
                           'actor', 'milestone', 'rateLimit'))


def graphql_selections(document, variables):
    source = re.sub(r'#[^\n]*', ' ', document)
    tokens = re.findall(r'\$[A-Za-z_][A-Za-z0-9_]*|[A-Za-z_][A-Za-z0-9_]*|[0-9]+|[{}():!\[\]]', source)
    if ''.join(tokens) != re.sub(r'[\s,]', '', source):
        refuse('incomplete')
    pos = 0

    def take(expected=None):
        nonlocal pos
        if pos >= len(tokens) or (expected is not None and tokens[pos] != expected):
            refuse('incomplete')
        value = tokens[pos]
        pos += 1
        return value

    def name():
        value = take()
        if not NAME.fullmatch(value):
            refuse('incomplete')
        return value

    def selections(depth=0):
        if depth > 32:
            refuse('incomplete')
        take('{')
        fields, keys = [], set()
        while pos < len(tokens) and tokens[pos] != '}':
            field = response = name()
            if pos < len(tokens) and tokens[pos] == ':':
                take(':')
                field = name()
            if response in keys:
                refuse('incomplete')
            keys.add(response)
            args = {}
            if pos < len(tokens) and tokens[pos] == '(':
                take('(')
                while pos < len(tokens) and tokens[pos] != ')':
                    key = name()
                    take(':')
                    value = take()
                    if key in args:
                        refuse('incomplete')
                    if value.startswith('$'):
                        if value[1:] not in variables:
                            refuse('incomplete')
                        value = variables[value[1:]]
                    elif value.isdigit():
                        value = int(value)
                    elif not NAME.fullmatch(value):
                        refuse('incomplete')
                    args[key] = value
                take(')')
            children = selections(depth + 1) if pos < len(tokens) and tokens[pos] == '{' else []
            fields.append({'field': field, 'response': response, 'args': args, 'children': children})
        take('}')
        if not fields:
            refuse('incomplete')
        return fields

    if tokens and tokens[0] == 'query':
        take('query')
        if pos < len(tokens) and NAME.fullmatch(tokens[pos]):
            name()
        if pos < len(tokens) and tokens[pos] == '(':
            take('(')
            while pos < len(tokens) and tokens[pos] != ')':
                variable = take()
                if not variable.startswith('$'):
                    refuse('incomplete')
                take(':')
                # Type declarations only; defaults and directives are unsupported.
                while pos < len(tokens) and not tokens[pos].startswith('$') and tokens[pos] != ')':
                    token = take()
                    if token not in ('[', ']', '!') and not NAME.fullmatch(token):
                        refuse('incomplete')
            take(')')
    fields = selections()
    if pos != len(tokens):
        refuse('incomplete')

    def bound(fields, multiplicity=1, context='object', size=None):
        cost = 0
        for item in fields:
            field, args, children = item['field'], item['args'], item['children']
            item['kind'] = 'scalar'
            if not children:
                if args:
                    refuse('incomplete')
                continue
            if context == 'connection':
                if field in ('nodes', 'edges') and not args:
                    item.update(kind='list', size=size)
                    cost += bound(children, multiplicity, 'edge' if field == 'edges' else 'object')
                elif field == 'pageInfo' and not args:
                    item['kind'] = 'pageInfo'
                    flags = {f['field'] for f in children}
                    if not {'hasNextPage', 'hasPreviousPage'} <= flags:
                        refuse('incomplete')
                    cost += bound(children, multiplicity, 'pageInfo')
                else:
                    refuse('incomplete')
            elif 'first' in args or 'last' in args:
                limits = [args[k] for k in ('first', 'last') if k in args]
                if len(limits) != 1 or type(limits[0]) is not int or not 1 <= limits[0] <= 100:
                    refuse('incomplete')
                if not any(f['field'] == 'pageInfo' for f in children):
                    refuse('incomplete')
                item['kind'] = 'connection'
                count = multiplicity * limits[0]
                cost += count + bound(children, count, 'connection', limits[0])
            elif field in SINGLE_OBJECTS and context in ('object', 'edge'):
                item['kind'] = 'object'
                cost += bound(children, multiplicity)
            else:
                refuse('incomplete')
        if cost > 500000:
            refuse('incomplete')
        return cost

    # Deliberately over-reserve: one plus every possible connection node,
    # without GitHub's /100 normalization or deduplication. No guessed cost
    # for unsupported syntax; missing headers debit this entire bound.
    cost = 1 + bound(fields)
    return fields, cost


def graphql_request(repo, document, variables):
    graphql_operations(document)
    try:
        values = json.loads(variables, object_pairs_hook=app.object_once)
    except ValueError:
        refuse('shape')
    if not isinstance(values, dict) or any(not NAME.fullmatch(k) for k in values):
        refuse('shape')
    owner, name = repo.split('/')
    if (('owner' in values or 'name' in values) and
            (str(values.get('owner', '')).lower(), str(values.get('name', '')).lower()) != (owner, name)):
        refuse('binding')
    selections, cost = graphql_selections(document, values)
    return {'host': HOST, 'repository': repo, 'api': 'graphql', 'method': 'POST',
            'selections': selections, 'cost': cost,
            'path': '/graphql', 'document': document, 'variables': values,
            'accept': ACCEPT[0], 'api_version': API_VERSION,
            'pagination': {'follow': False, 'complete': 'required'}}


# ---- Shared owner-only state ---------------------------------------------

def open_dir(name, parent):
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    try:
        return app.checked(fd, directory=True)
    except Exception:
        os.close(fd)
        raise


class Shared:
    """<state>/service/github-reads: owner-only, one installation lock, atomic files."""

    def __init__(self, state_dir):
        top = os.open(state_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            app.checked(top, directory=True)
            service = open_dir('service', top)
            try:
                self.fd = open_dir(NAMESPACE, service)
            finally:
                os.close(service)
        finally:
            os.close(top)
        self.lock_fd = None

    def config(self):
        try:
            value = app.parse_json(app.read_file(self.fd, 'installation.json', 64 * 1024))
        except FileNotFoundError:
            refuse('credential')
        repos = value.get('repositories')
        installation = value.get('installation_id')
        if (set(value) != {'installation_id', 'repositories'} or type(installation) is not int or
                installation < 1 or not isinstance(repos, list) or not 0 < len(repos) <= 100 or
                any(not isinstance(r, str) or not REPO.fullmatch(r) for r in repos) or
                len(set(repos)) != len(repos) or len({r.split('/')[0] for r in repos}) != 1):
            refuse('credential')
        self.installation, self.repositories = installation, sorted(repos)
        self.state_name = f'installation-{installation}.json'
        return self

    def __enter__(self):
        fd = os.open(f'installation-{self.installation}.lock',
                     os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
        try:
            app.checked(fd)
            fcntl.flock(fd, fcntl.LOCK_EX)
        except Exception:
            os.close(fd)
            refuse('sharing')
        self.lock_fd = fd
        return self

    def __exit__(self, *_exc):
        os.close(self.lock_fd)  # closing releases the lock
        self.lock_fd = None

    def read_json(self, name, limit):
        try:
            return app.parse_json(app.read_file(self.fd, name, limit))
        except FileNotFoundError:
            return None

    def write_json(self, name, value):
        temporary = f'.{name}.{os.getpid()}.tmp'
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=self.fd)
        try:
            with os.fdopen(fd, 'w') as file:
                file.write(canonical(value))
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, name, src_dir_fd=self.fd, dst_dir_fd=self.fd)
            os.fsync(self.fd)
        except Exception:
            try:
                os.unlink(temporary, dir_fd=self.fd)
            except FileNotFoundError:
                pass
            raise

    def load(self):
        try:
            value = self.read_json(self.state_name, 4 * 1024 * 1024) or {}
        except (ValueError, OSError):
            refuse('sharing')
        state = {'auth': None, 'generation': 0, 'pools': {'rest': None, 'graphql': None},
                 'reservations': {}, 'inflight': {}, 'secondary_not_before': 0,
                 'backoff_s': 0, 'pace_not_before': 0, 'probe_not_before': 0, 'probe_attempts': 0}
        if set(value) - set(state):
            refuse('sharing')
        state.update(value)
        # A vanished process may already have spent its reservation upstream.
        for pid in list(state['reservations']):
            if not alive(int(pid)):
                abandon(state, pid)
        state['inflight'] = {k: v for k, v in state['inflight'].items() if alive(v['pid'])}
        return state

    def save(self, state):
        self.write_json(self.state_name, state)


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


# ---- Authorization: the existing mint, a generation per grant ------------

def mint(args, shared):
    """The existing mint, downscoped to the selection; the token stays in memory."""
    command = [sys.executable, '-E', '-s', str(MINT), '--state-dir', str(args.state_dir),
               '--api-base', args.api_base, '--installation-id', str(shared.installation)]
    for repo in shared.repositories:
        command += ['--repository', repo]
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
        lines = result.stdout.decode().split('\n')
        if result.returncode != 0 or len(lines) != 3 or lines[2] != '':
            return None
        return lines[0], int(lines[1])
    except (subprocess.SubprocessError, OSError, ValueError):
        return None


def grant(shared):
    return {'installation_id': shared.installation, 'repositories': shared.repositories,
            'permissions': app.PERMISSIONS}


def record_mint(state, shared, minted, now):
    scope = grant(shared)
    auth = state['auth']
    scope_changed = auth is not None and any(auth[k] != v for k, v in scope.items())
    if minted is None:
        # Every uncertain observation supersedes all mints already in flight.
        state['generation'] += 1
        state['auth'] = dict(scope, state='unknown', generation=state['generation'],
                             verified_at=now, expires_at=0)
        return
    # Initial activation/recovery already uses the current invalidation epoch.
    # Parallel successful mints of the same grant must not invalidate each other.
    if scope_changed:
        state['generation'] += 1
    state['auth'] = dict(scope, state='active', generation=state['generation'],
                         verified_at=now, expires_at=minted[1])


def authorized(state, shared, now):
    auth = state['auth']
    return (auth is not None and auth['state'] == 'active' and auth['expires_at'] > now and
            all(auth[k] == v for k, v in grant(shared).items()))


# ---- Budget: one installation, two pools ---------------------------------

def reserved(state, api):
    return sum(r.get(api, 0) for r in state['reservations'].values())


def reserve(state, api, delta):
    mine = state['reservations'].setdefault(str(os.getpid()), {})
    mine[api] = max(0, mine.get(api, 0) + delta)


def abandon(state, pid):
    """Debit uncertain spend before releasing a dead/failed caller's reservation."""
    for api, cost in state['reservations'].pop(str(pid), {}).items():
        pool = state['pools'][api]
        if pool is not None:
            debit_uncertain(pool, cost)


def debit_uncertain(pool, cost):
    # Keep distinct unconfirmed spends outside the provider's header floor.
    # An older response may already include some of them, but cannot prove which.
    pool['unconfirmed_spent'] = pool.get('unconfirmed_spent', 0) + cost
    pool['remaining'] = max(0, pool['remaining'] - cost)


def observed_pool(previous, limit, remaining, reset, now):
    # Admission/reset times do not locate an unsettled request's provider spend.
    # Keep its debit even when a delayed header or probe names a new window.
    uncertain = previous.get('unconfirmed_spent', 0) if previous is not None else 0
    if previous is not None and previous['reset_at'] == reset:
        floor = min(previous.get('observed_remaining', previous['remaining'] + uncertain),
                    previous['remaining'] + uncertain)
        remaining = min(remaining, floor)
    return {'limit': limit, 'remaining': max(0, remaining - uncertain),
            'observed_remaining': remaining, 'unconfirmed_spent': uncertain,
            'reset_at': reset, 'observed_at': now}


def pool_usable(pool, now, max_age=float('inf')):
    return (pool is not None and 0 < pool['observed_at'] <= now < pool['reset_at'] and
            0 <= now - pool['observed_at'] <= max_age and
            0 <= pool['remaining'] <= pool['limit'])


def admit(state, shared, api, now, max_age, cost):
    """Reserve only against current authorization and the conservative cost."""
    if not authorized(state, shared, now):
        refuse('credential')
    if not 0 <= now - state['auth']['verified_at'] <= max_age:
        refuse('freshness')
    for deadline in (state['secondary_not_before'], state['pace_not_before']):
        if deadline > now:
            raise Outcome('deferred', 'backoff', deadline)
    pool = state['pools'][api]
    if not pool_usable(pool, now, max_age):
        return False  # the caller probes, under the lock
    spare = pool['remaining'] - reserved(state, api)
    if spare < cost:
        raise Outcome('deferred', 'primary-budget', pool['reset_at'])
    reserve(state, api, cost)
    if pool['remaining'] < pool['limit'] * LOW_BUDGET:
        state['pace_not_before'] = now + (pool['reset_at'] - now) / max(spare - cost, 1)
    return True


def observe(state, headers, now):
    """Reconcile with GitHub's own rate headers; a missing answer stays conservative."""
    resource = {'core': 'rest', 'graphql': 'graphql'}.get(headers.get('x-ratelimit-resource', ''))
    try:
        limit, remaining, reset = (int(headers[k]) for k in (
            'x-ratelimit-limit', 'x-ratelimit-remaining', 'x-ratelimit-reset'))
    except (KeyError, ValueError):
        return False
    if resource is None:
        return False
    pool = state['pools'][resource]
    if not (0 <= remaining <= limit and reset > now):
        # Invalidate only the observation. Nulling the pool would also discard
        # unresolved debits before the next successful header/probe replaces it.
        if pool is not None:
            pool['observed_at'] = 0
        return False  # this response's own cost is also unconfirmed
    state['pools'][resource] = observed_pool(pool, limit, remaining, reset, now)
    return True


def settle(state, api, status, headers, body, now, cost=1):
    """Release this request's reservation and apply any rate-limit answer."""
    reserve(state, api, -cost)
    if not observe(state, headers, now) or headers.get('x-ratelimit-resource') != (
            'core' if api == 'rest' else 'graphql'):
        pool = state['pools'][api]
        if pool is not None:
            debit_uncertain(pool, cost)
    limited = status in (403, 429) and (
        'retry-after' in headers or headers.get('x-ratelimit-remaining') == '0' or
        status == 429 or b'rate limit' in body.lower())
    if api == 'graphql' and status == 200:
        try:
            errors = json.loads(body).get('errors') or []
            if any(isinstance(e, dict) and e.get('type') in ('RATE_LIMITED', 'RATE_LIMIT') for e in errors):
                pool = state['pools']['graphql']
                if pool is not None:
                    pool['remaining'] = 0
                limited = True
        except (ValueError, AttributeError):
            pass
    if not limited:
        if status in (200, 304):
            state['backoff_s'] = 0
        return None
    if 'retry-after' in headers and headers['retry-after'].isdigit():
        state['secondary_not_before'] = max(state['secondary_not_before'],
                                            now + int(headers['retry-after']))
        return Outcome('deferred', 'backoff', state['secondary_not_before'])
    pool = state['pools'][api]
    if pool is not None and pool['remaining'] == 0:
        return Outcome('deferred', 'primary-budget', pool['reset_at'])
    # A secondary limit without a usable answer: GitHub's minimum, then longer, bounded.
    state['backoff_s'] = min(BACKOFF_MAX_S, max(BACKOFF_MIN_S, state['backoff_s'] * 2))
    state['secondary_not_before'] = max(state['secondary_not_before'], now + state['backoff_s'])
    return Outcome('deferred', 'backoff', state['secondary_not_before'])


# ---- HTTP ------------------------------------------------------------------

def http(base, method, path, token, accept, extra=None, data=None):
    headers = {'Accept': accept, 'User-Agent': 'OpenWiz-agent-reads',
               'X-GitHub-Api-Version': API_VERSION, 'Authorization': 'Bearer ' + token}
    headers.update(extra or {})
    request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.build_opener(app.NoRedirect()).open(request, timeout=15) as response:
            status, got, body = response.status, response.headers, response.read(PAGE_BYTES + 1)
    except urllib.error.HTTPError as error:
        status, got = error.code, error.headers
        body = error.read(PAGE_BYTES + 1)
    except (urllib.error.URLError, OSError, ValueError):
        refuse('incomplete')
    if len(body) > PAGE_BYTES:
        refuse('incomplete')
    return status, {k.lower(): v for k, v in got.items()}, body


def probe(args, shared, token, state, now):
    """One persisted, paced probe attempt, even if its response never arrives."""
    if state['probe_not_before'] > now:
        raise Outcome('deferred', 'budget-unknown', state['probe_not_before'])
    state['probe_not_before'] = now + BACKOFF_MIN_S
    state['probe_attempts'] += 1
    shared.save(state)  # crash-safe admission before touching the provider
    try:
        status, headers, body = http(args.api_base, 'GET', '/rate_limit', token, ACCEPT[0])
        now = time.time()
        if status != 200:
            limited = settle(state, 'rest', status, headers, body, now, cost=0)
            if status in (401, 403) and limited is None:
                record_mint(state, shared, None, now)
                refuse('credential')
            if limited:
                raise limited
            raise ValueError
        resources = json.loads(body)['resources']
        pools = {}
        for api, name in (('rest', 'core'), ('graphql', 'graphql')):
            item = resources[name]
            limit, remaining, reset = (item[k] for k in ('limit', 'remaining', 'reset'))
            if any(type(v) is not int for v in (limit, remaining, reset)):
                raise ValueError
            pool = {'limit': limit, 'remaining': remaining, 'reset_at': reset, 'observed_at': now}
            if not pool_usable(pool, now):
                raise ValueError
            pools[api] = observed_pool(state['pools'][api], limit, remaining, reset, now)
        state['pools'].update(pools)
    except (ValueError, KeyError, TypeError):
        raise Outcome('deferred', 'budget-unknown', state['probe_not_before'])
    except Outcome as outcome:
        if outcome.state == 'refused' and outcome.reason == 'incomplete':
            raise Outcome('deferred', 'budget-unknown', state['probe_not_before'])
        raise


# ---- One read ----------------------------------------------------------------

def next_link(headers, base, request, seen):
    links = [part.strip() for part in headers.get('link', '').split(',') if 'rel="next"' in part]
    if not links:
        return None
    match = re.fullmatch(r'<([^>]*)>;\s*rel="next"', links[0]) if len(links) == 1 else None
    if match is None or not match.group(1).startswith(base + '/'):
        refuse('incomplete')
    target = match.group(1)[len(base):]
    path, _, query = target.partition('?')
    # Pagination may change only explicitly supported cursor/page parameters.
    # Resource, page size, ordering, filters and repeated inputs stay bound to
    # the original complete request on both 200 and 304 responses.
    pagination = {'page', 'before', 'after'}
    parts = path.split('/')
    if (path != request['path'] or '..' in parts or '' in parts[1:] or
            any(not SEGMENT.fullmatch(p) for p in parts[1:]) or
            QUERY.fullmatch(query) is None or target in seen):
        refuse('incomplete')
    pairs = urllib.parse.parse_qsl(query, keep_blank_values=True)
    original = [(k, v) for k, v in request['query'] if k not in pagination]
    current = [(k, v) for k, v in pairs if k not in pagination]
    if current != original:
        refuse('incomplete')
    return target


def complete_graphql(value, fields):
    """Validate every selected connection, including aliased pagination flags."""
    if not isinstance(value, dict) or set(value) != {f['response'] for f in fields}:
        return False
    for field in fields:
        got, kind = value[field['response']], field['kind']
        if kind == 'scalar':
            if isinstance(got, (dict, list)):
                return False
        elif kind == 'list':
            if (not isinstance(got, list) or len(got) > field['size'] or
                    not all(complete_graphql(v, field['children']) for v in got)):
                return False
        elif got is None and kind == 'object':
            continue
        elif not complete_graphql(got, field['children']):
            return False
        if kind == 'pageInfo':
            for flag in field['children']:
                if flag['field'] in ('hasNextPage', 'hasPreviousPage') and got[flag['response']] is not False:
                    return False
    return True


def fetch(args, shared, token, request, old):
    """Every page, budgeted page by page; 304 only for a cached page we validated."""
    cached = {p['url']: p for p in old['pages']} if old else {}
    pages, seen, revalidated = [], set(), True
    if request['api'] == 'rest':
        url = request['path'] + ('?' + request['raw_query'] if request['raw_query'] else '')
    else:
        url = '/graphql'
    while url is not None:
        if len(pages) >= MAX_PAGES:
            refuse('incomplete')
        seen.add(url)
        page_budget(args, shared, token, request['api'], request.get('cost', 1))
        extra = {}
        if request['api'] == 'rest' and url in cached and cached[url]['etag']:
            extra['If-None-Match'] = cached[url]['etag']
        if request['api'] == 'rest':
            status, headers, body = http(args.api_base, 'GET', url, token, request['accept'], extra)
        else:
            data = json.dumps({'query': request['document'], 'variables': request['variables']}).encode()
            status, headers, body = http(args.api_base, 'POST', url, token, request['accept'],
                                         {'Content-Type': 'application/json'}, data)
        with shared:
            state = shared.load()
            limited = settle(state, request['api'], status, headers, body, time.time(), request.get('cost', 1))
            if status == 401 or (status == 403 and limited is None):
                record_mint(state, shared, None, time.time())
            shared.save(state)
        if limited:
            raise limited
        if status == 401 or status == 403:
            refuse('credential')
        if status == 304 and 'If-None-Match' in extra:
            page = dict(cached[url])
            if 'etag' in headers and headers['etag'] != extra['If-None-Match']:
                refuse('conditional')
            if 'link' in headers:
                page['next'] = next_link(headers, args.api_base, request, seen) if (
                    request['pagination']['follow']) else None
            page['etag'] = headers.get('etag', page['etag'])
        elif status == 200:
            revalidated = False
            if request['api'] == 'graphql':
                try:
                    value = json.loads(body)
                except ValueError:
                    refuse('incomplete')
                if (not isinstance(value, dict) or value.get('errors') or
                        not isinstance(value.get('data'), dict) or not complete_graphql(value['data'], request['selections'])):
                    refuse('incomplete')
            nxt = next_link(headers, args.api_base, request, seen) if (
                request['api'] == 'rest' and request['pagination']['follow']) else None
            page = {'url': url, 'etag': headers.get('etag'), 'next': nxt,
                    'body': base64.b64encode(body).decode()}
        else:
            refuse('incomplete')
        pages.append(page)
        url = page['next']
        if url is not None and url in seen:
            refuse('incomplete')
    return pages, revalidated


def page_budget(args, shared, token, api, cost):
    """Admit one request against the shared installation pool, probing if unknown."""
    while True:
        with shared:
            state = shared.load()
            now = time.time()
            try:
                admitted = admit(state, shared, api, now, args.max_age, cost)
                if not admitted:
                    probe(args, shared, token, state, now)
                    now = time.time()
                    admitted = admit(state, shared, api, now, args.max_age, cost)
                    if not admitted:
                        raise Outcome('deferred', 'budget-unknown')
                shared.save(state)
                return
            except Outcome as outcome:
                shared.save(state)
                wait = (outcome.until or 0) - now
                if not (outcome.reason == 'backoff' and 0 < wait <= SHORT_WAIT_S):
                    raise
        time.sleep(wait)


def credential_available(args):
    """Reuse the existing protected-file guards immediately before returning data."""
    try:
        directory = app.app_directory(args.state_dir)
        try:
            app.read_file(directory, 'app.json', 1024)
            return bool(app.read_file(directory, 'private-key.pem', 64 * 1024))
        finally:
            os.close(directory)
    except Exception:
        return False


def fresh_evidence(state, shared, api, max_age, now):
    return (authorized(state, shared, now) and
            0 <= now - state['auth']['verified_at'] <= max_age and
            pool_usable(state['pools'][api], now, max_age))


def usable(entry, state, shared, args, request, challenge, now, joined):
    """An ordinary completed entry is display-only; fresh reuse must join a leader."""
    if (entry is None or not fresh_evidence(state, shared, request['api'], args.max_age, now) or
            entry['generation'] != state['auth']['generation'] or
            not 0 <= now - entry['validated_at'] <= args.max_age):
        return None
    if (joined is not None and entry.get('claim') == joined and
            entry['read_started_at'] >= challenge and state['auth']['verified_at'] >= challenge):
        return 'fresh', 'current'
    return ('display', 'cache') if args.purpose == 'display' else None


def run(args, request):
    start = time.time()
    challenge = start if args.challenge is None else args.challenge
    if not 0 < challenge <= start:
        refuse('freshness')
    try:
        args.state_dir = app.state_path(args.state_dir)
        shared = Shared(args.state_dir)
    except Exception:
        refuse('sharing')
    shared.config()
    if request['repository'] not in shared.repositories:
        refuse('binding')
    request_sha256 = sha({k: v for k, v in request.items() if k != 'raw_query'})
    # A fresh observation for every invocation, including private display hits.
    # No token persists in the cache; neither missing keys nor revoked grants
    # can be bypassed by an old entry. The shared pool survives token renewal.
    with shared:
        state = shared.load()
        mint_generation = state['generation']
        shared.save(state)
    # Timestamp conservatively before minting, so neither subprocess scheduling
    # nor a later publication-lock wait can erase elapsed observation age.
    observed_at = time.time()
    minted = mint(args, shared)
    with shared:
        state = shared.load()
        if minted is not None and state['generation'] != mint_generation:
            # A denial/uncertainty or changed grant observed since this mint
            # began invalidates it. Only a subsequent mint may restore access.
            refuse('credential')
        record_mint(state, shared, minted, observed_at)
        shared.save(state)
    if minted is None:
        refuse('credential')
    token, deadline, joined = minted[0], start + WAIT_S, None
    while True:
        claimed = None
        with shared:
            state = shared.load()
            now = time.time()
            if not credential_available(args):
                record_mint(state, shared, None, now)
                shared.save(state)
                refuse('credential')
            if not authorized(state, shared, now):
                refuse('credential')
            auth = state['auth']
            key = sha(dict(grant(shared), host=HOST, repository=request['repository'],
                           generation=auth['generation'], request_sha256=request_sha256))
            entry_name = f'entry-{key}.json'
            entry = shared.read_json(entry_name, MAX_PAGES * PAGE_BYTES * 2)
            now = time.time()  # include the cost of reading a large private entry
            found = usable(entry, state, shared, args, request, challenge, now, joined)
            if found:
                return found, entry
            leader = state['inflight'].get(key)
            # Even an ineligible leader keeps its ownership. A newer challenge
            # waits for it to finish, then performs its own validation.
            waiting = leader is not None
            if waiting:
                joined = leader if leader['read_started_at'] >= challenge else None
            else:
                if not 0 <= now - auth['verified_at'] <= args.max_age:
                    refuse('freshness')
                claimed = {'pid': os.getpid(), 'read_started_at': now, 'generation': auth['generation']}
                state['inflight'][key] = claimed
            shared.save(state)
        if claimed is not None:
            return lead(args, shared, token, request, key, entry_name, claimed, entry, challenge)
        if time.time() > deadline:
            refuse('incomplete')
        time.sleep(0.05)


def lead(args, shared, token, request, key, entry_name, claimed, old, challenge):
    try:
        if old is not None and old['generation'] != claimed['generation']:
            old = None
        pages, revalidated = fetch(args, shared, token, request, old)
        with shared:
            state = shared.load()
            now = time.time()
            if not credential_available(args):
                record_mint(state, shared, None, now)
                shared.save(state)
            now = time.time()
            if (state['inflight'].get(key) != claimed or not authorized(state, shared, now) or
                    state['auth']['generation'] != claimed['generation']):
                refuse('credential')
            if (not fresh_evidence(state, shared, request['api'], args.max_age, now) or
                    (args.purpose == 'authority' and state['auth']['verified_at'] < challenge)):
                refuse('freshness')
            entry = {'generation': claimed['generation'], 'read_started_at': claimed['read_started_at'],
                     'claim': claimed, 'fetched_at': old['fetched_at'] if revalidated else now,
                     'validated_at': now, 'pages': pages}
            shared.write_json(entry_name, entry)
            del state['inflight'][key]
            shared.save(state)
        return ('fresh', 'current'), entry
    finally:
        with shared:
            state = shared.load()
            if state['inflight'].get(key) == claimed:
                del state['inflight'][key]
            abandon(state, os.getpid())  # exceptions can leave uncertain upstream spend
            shared.save(state)


def parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--purpose', choices=('display', 'authority'), required=True)
    common.add_argument('--max-age', type=int, required=True)
    common.add_argument('--challenge', type=int)
    common.add_argument('--state-dir', type=Path)
    common.add_argument('--api-base', default='https://api.github.com')
    top = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = top.add_subparsers(dest='api', required=True)
    rest = commands.add_parser('rest', parents=[common])
    rest.add_argument('repo')
    rest.add_argument('endpoint')
    rest.add_argument('--accept', default=ACCEPT[0])
    rest.add_argument('--single-page', action='store_true')
    graphql = commands.add_parser('graphql', parents=[common])
    graphql.add_argument('repo')
    graphql.add_argument('--variables', default='{}')
    return top


def main():
    args = parser().parse_args()
    if args.max_age < 0:
        print('read.py: --max-age must be zero or more', file=sys.stderr)
        return 2
    try:
        try:
            app.api_base(args.api_base)
        except ValueError:
            refuse('shape')
        repo = args.repo.lower()
        if not REPO.fullmatch(repo) or repo.split('/')[1] in ('.', '..'):
            refuse('shape')
        if args.api == 'rest':
            request = rest_request(repo, args.endpoint, args.accept, args.single_page)
        else:
            request = graphql_request(repo, sys.stdin.read(64 * 1024 + 1), args.variables)
        (state, reason), entry = run(args, request)
    except Outcome as outcome:
        print(outcome.line(), file=sys.stderr)
        return 1
    except Exception:
        print('refused: incomplete', file=sys.stderr)
        return 1
    out = sys.stdout.buffer
    for page in entry['pages']:
        body = base64.b64decode(page['body'])
        out.write(body if body.endswith(b'\n') else body + b'\n')
    out.flush()
    print(f'{state}: {reason}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
