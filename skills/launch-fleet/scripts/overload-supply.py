#!/usr/bin/env python3
import argparse
import base64
import binascii
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote

sys.dont_write_bytecode = True

DESCRIPTION = 'Default overload observation supplier for fleet.sh overload.'
PAGE = 100
API_LIMIT = 1000
RULE_PAGES = 10
TIME = re.compile(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ')
PROGRESSION = ('requested', 'waiting', 'pending', 'queued', 'in_progress')
WAITING = ('queued', 'waiting', 'pending', 'requested')
POOLS = {'core': 'rest', 'graphql': 'graphql'}
RATE_QUERY = 'query{rateLimit{remaining}}'
SECONDARY_WAIT = 60
WINDOW = 60
STATUS_LINE = re.compile(r'HTTP/[0-9.]+ ([0-9]{3})(?: .*)?')
HEADER = re.compile(r'([A-Za-z0-9-]+): ?(.*)')
NEXT_LINK = re.compile(r'<[^>]+>\s*;\s*rel="next"')
CHECK_ROW = re.compile(r'\| *`([^`]+)` *\|')
SECONDS = re.compile(r'[0-9]{1,6}')
EPOCH = re.compile(r'[0-9]{1,12}')
SECONDARY = re.compile(r'secondary rate limit', re.I)


class Fail(Exception):
    pass


class NotFound(Fail):
    pass


class Backoff(Exception):
    def __init__(self, pool, deadline, headers):
        super().__init__(pool)
        self.pool, self.deadline, self.budget = pool, deadline, None
        found = [headers.get('x-ratelimit-' + k, '') for k in ('remaining', 'limit', 'reset')]
        if all(EPOCH.fullmatch(v) for v in found):
            remaining, limit, reset = map(int, found)
            if 0 < limit and remaining <= limit:
                self.budget = {'remaining': remaining, 'limit': limit, 'reset_at': reset, 'retry_after': 0}


class Stale(Exception):
    pass


def strict_json(text, where):
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise Fail(f'{where}: repeated key')
            out[k] = v
        return out

    def constant(name):
        raise ValueError(name)

    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except ValueError:
        raise Fail(f'{where}: not JSON')


def need(obj, key, where):
    if key not in obj:
        raise Fail(f'{where}: missing {key!r}')
    return obj[key]


def as_obj(v, where):
    if type(v) is not dict:
        raise Fail(f'{where}: not an object')
    return v


def as_list(v, where):
    if type(v) is not list:
        raise Fail(f'{where}: not a list')
    return v


def as_int(obj, key, where):
    v = need(obj, key, where)
    if type(v) is not int:
        raise Fail(f'{where}: {key!r} is not an integer')
    return v


def as_str(obj, key, where):
    v = need(obj, key, where)
    if type(v) is not str:
        raise Fail(f'{where}: {key!r} is not a string')
    return v


def as_seconds(obj, key, where, null=False):
    v = need(obj, key, where)
    if v is None and null:
        return None
    if type(v) is not str or not TIME.fullmatch(v):
        raise Fail(f'{where}: {key!r} is not a UTC time')
    try:
        return int(datetime.strptime(v, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        raise Fail(f'{where}: {key!r} is not a UTC time')


def response(out):
    status_line, newline, rest = out.partition('\n')
    found = STATUS_LINE.fullmatch(status_line.rstrip('\r'))
    if not newline or not found:
        return None
    headers = {}
    while True:
        line, crlf, rest = rest.partition('\r\n')
        if not crlf:
            return None
        if not line:
            return int(found.group(1)), headers, rest
        header = HEADER.fullmatch(line)
        if not header or headers.setdefault(header.group(1).lower(), header.group(2)) != header.group(2):
            return None


class Reader:
    def __init__(self, clock, window=None):
        self.clock, self.unknown = clock, False
        self.window = WINDOW if window is None else window
        self.start = clock()
        self.mono_start = time.monotonic()
        self.deadline = self.mono_start + self.window

    def __call__(self, path):
        return self.get(path)[0]

    def get(self, path):
        return self.run_with_headers(['gh', 'api', '--include', path], f'gh api {path}', 'rest')

    def graphql(self, query):
        data, _ = self.run_with_headers(['gh', 'api', '--include', 'graphql', '-f', 'query=' + query],
                                        'gh api graphql', 'graphql')
        if type(data) is not dict or 'errors' in data:
            raise Fail('gh api graphql: errors')
        limit = as_obj(need(as_obj(need(data, 'data', 'graphql'), 'graphql data'), 'rateLimit', 'graphql'),
                       'rateLimit')
        if as_int(limit, 'remaining', 'rateLimit') < 0:
            raise Fail('rateLimit: negative remaining')
        return data

    def remaining(self, where):
        clock_left = self.window - (self.clock() - self.start)
        mono_left = self.deadline - time.monotonic()
        left = min(clock_left, mono_left)
        if left <= 0:
            raise Stale(where)
        return left

    def run_with_headers(self, args, where, pool):
        left = self.remaining(where)
        try:
            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    stdin=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            raise Fail(f'{where}: gh could not start or wrote no text')
        try:
            stdout, _ = proc.communicate(timeout=left)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
            for pipe in (proc.stdout, proc.stderr):
                if pipe is not None:
                    pipe.close()
            proc.wait()
            raise Stale(where)
        try:
            out = stdout.decode('utf-8')
        except UnicodeError:
            raise Fail(f'{where}: gh could not start or wrote no text')
        got = response(out)
        if got is None:
            if proc.returncode != 0:
                raise Fail(f'{where} failed (exit {proc.returncode})')
            self.unknown = True
            return strict_json(out, where), None
        status, headers, body = got
        pool = POOLS.get(headers.get('x-ratelimit-resource'), pool)
        self.signal(pool, status, headers, body)
        try:
            data = strict_json(body, where)
        except Fail:
            data = None
        if pool == 'graphql' and type(data) is dict and type(data.get('errors')) is list and any(
                type(e) is dict and e.get('type') == 'RATE_LIMITED' for e in data['errors']):
            raise Backoff(pool, self.wait(headers), headers)
        if status == 404:
            raise NotFound(f'{where} failed (HTTP 404)')
        if proc.returncode != 0 or not 200 <= status < 300:
            raise Fail(f'{where} failed (HTTP {status})')
        return strict_json(body, where), headers

    def signal(self, pool, status, headers, body):
        retry = headers.get('retry-after')
        if retry is not None:
            raise Backoff(pool, self.clock() + int(retry) if SECONDS.fullmatch(retry) else None, headers)
        if status == 429 or (status == 403 and (headers.get('x-ratelimit-remaining') == '0' or SECONDARY.search(body))):
            raise Backoff(pool, self.wait(headers), headers)

    def wait(self, headers):
        reset = headers.get('x-ratelimit-reset', '')
        if headers.get('x-ratelimit-remaining') == '0' and EPOCH.fullmatch(reset):
            return int(reset)
        return self.clock() + SECONDARY_WAIT


def parse_fleet_checks(text):
    checks, on = set(), False
    for row in text.splitlines():
        if row.startswith('## '):
            on = row == '## CI checks'
        elif on:
            cell = CHECK_ROW.match(row)
            if cell and cell.group(1).strip():
                checks.add(cell.group(1))
    return checks


def branch_rules(repo, branch, read):
    checks = set()
    encoded = quote(branch, safe='')
    for page in range(1, RULE_PAGES + 1):
        path = f'repos/{repo}/rules/branches/{encoded}?per_page={PAGE}&page={page}'
        where = f'gh api {path}'
        data, headers = read.get(path)
        if headers is None:
            raise Fail(f'{where}: missing response headers')
        for rule in as_list(data, where):
            rule = as_obj(rule, where)
            if rule.get('type') != 'required_status_checks':
                continue
            params = as_obj(need(rule, 'parameters', where), where + ' parameters')
            for entry in as_list(need(params, 'required_status_checks', where), where + ' required_status_checks'):
                ctx = as_str(as_obj(entry, where), 'context', where)
                if not ctx:
                    raise Fail(f'{where}: empty check context')
                checks.add(ctx)
        if not NEXT_LINK.search(headers.get('link', '')):
            return checks
    raise Fail(f'repos/{repo}/rules/branches/{encoded}: too many pages')


def fleet_checks(repo, read):
    path = f'repos/{repo}/contents/docs/agents/fleet.md'
    where = f'gh api {path}'
    try:
        data = as_obj(read(path), where)
    except NotFound:
        return None
    if data.get('type') != 'file' or data.get('encoding') != 'base64':
        raise Fail(f'{where}: unexpected content shape')
    raw_b64 = as_str(data, 'content', where)
    try:
        text = base64.b64decode(''.join(raw_b64.split()), validate=True).decode('utf-8')
    except (binascii.Error, UnicodeError, ValueError):
        raise Fail(f'{where}: invalid base64 content')
    return parse_fleet_checks(text)


def classic_checks(repo, branch, read):
    encoded = quote(branch, safe='')
    path = f'repos/{repo}/branches/{encoded}/protection/required_status_checks'
    where = f'gh api {path}'
    try:
        data = as_obj(read(path), where)
    except NotFound:
        return set()
    found = set()
    if 'checks' in data:
        for entry in as_list(data['checks'], where + ' checks'):
            ctx = as_str(as_obj(entry, where), 'context', where)
            if not ctx:
                raise Fail(f'{where}: empty check context')
            found.add(ctx)
    if 'contexts' in data:
        for ctx in as_list(data['contexts'], where + ' contexts'):
            if type(ctx) is not str or not ctx:
                raise Fail(f'{where}: invalid context')
            found.add(ctx)
    if 'checks' not in data and 'contexts' not in data:
        raise Fail(f'{where}: missing checks')
    return found


def required_checks(repo, read):
    checks = set()
    branch = None
    rules_ok = False
    try:
        info = as_obj(read(f'repos/{repo}'), f'gh api repos/{repo}')
        branch = as_str(info, 'default_branch', f'gh api repos/{repo}')
        if not branch:
            raise Fail(f'gh api repos/{repo}: empty default_branch')
        checks.update(branch_rules(repo, branch, read))
        rules_ok = True
    except Fail:
        rules_ok = False

    fleet_ok = False
    try:
        from_fleet = fleet_checks(repo, read)
        if from_fleet is not None:
            checks.update(from_fleet)
        fleet_ok = True
    except Fail:
        fleet_ok = False

    classic_ok = True
    if rules_ok and not checks:
        try:
            checks.update(classic_checks(repo, branch, read))
        except Fail:
            classic_ok = False

    return checks, rules_ok and fleet_ok and classic_ok and bool(checks)


def pages(path, key, read):
    items, total, page = [], None, 1
    while total is None or len(items) < total:
        where = f'gh api {path}&page={page}'
        ans = as_obj(read(f'{path}&page={page}'), where)
        count, got = as_int(ans, 'total_count', where), as_list(need(ans, key, where), where)
        if total is None:
            total = count
            if total > API_LIMIT:
                raise Fail(f'{where}: more than {API_LIMIT} items')
        elif count != total:
            raise Fail(f'{where}: total_count changed between pages')
        if not got and len(items) < total:
            raise Fail(f'{where}: fewer items than total_count')
        items += [(item, where) for item in got]
        page += 1
    if len(items) > total:
        raise Fail(f'gh api {path}: more items than total_count')
    return items


def active_runs(base, read):
    runs, unique = {}, True
    for status in PROGRESSION:
        listed = set()
        for value, where in pages(f'{base}/runs?status={status}&per_page={PAGE}', 'workflow_runs', read):
            rid = as_int(as_obj(value, where), 'id', where)
            attempt = as_int(value, 'run_attempt', where)
            unique = unique and rid not in listed
            listed.add(rid)
            if runs.setdefault(rid, attempt) != attempt:
                raise Fail('a run listed twice, as two different runs')
    return runs, unique


def budget(resources, pool):
    item = as_obj(need(resources, pool, 'rate_limit'), 'rate_limit ' + pool)
    return {'remaining': as_int(item, 'remaining', pool), 'limit': as_int(item, 'limit', pool),
            'reset_at': as_int(item, 'reset', pool), 'retry_after': 0}


def budgets_now(read):
    limits = as_obj(need(as_obj(read('rate_limit'), 'rate_limit'), 'resources', 'rate_limit'), 'resources')
    return {'rest': budget(limits, 'core'), 'graphql': budget(limits, 'graphql')}


def apply_backoff(budgets, stop):
    prev_retry = budgets[stop.pool]['retry_after']
    if stop.budget is not None:
        budgets[stop.pool] = dict(stop.budget)
    budgets[stop.pool]['retry_after'] = max(prev_retry, stop.deadline or 0)


def refresh_budgets(read, previous):
    fresh = budgets_now(read)
    for pool, prev in previous.items():
        if prev['retry_after'] > 0:
            if prev['reset_at'] > fresh[pool]['reset_at']:
                fresh[pool] = dict(prev)
            else:
                fresh[pool]['retry_after'] = max(fresh[pool]['retry_after'], prev['retry_after'])
    return fresh


def observe(repo, clock):
    read = Reader(clock)
    base = f'repos/{repo}/actions'
    complete, queue_complete, jobs = True, False, []
    try:
        budgets = budgets_now(read)
    except (Backoff, Stale):
        raise Fail('the rate-limit read is backed off or late')
    try:
        try:
            read.graphql(RATE_QUERY)
        except Fail:
            complete = False
        except Backoff as stop:
            complete = False
            apply_backoff(budgets, stop)
        checks, classified = required_checks(repo, read)
        q_ok = classified
        runs, unique = active_runs(base, read)
        q_ok = q_ok and unique
        for rid, attempt in sorted(runs.items()):
            job_path = f'{base}/runs/{rid}/jobs?per_page={PAGE}'
            try:
                page = pages(job_path, 'jobs', read)
            except Fail:
                q_ok = False
                continue
            seen = set()
            for value, where in page:
                jid, status = as_int(as_obj(value, where), 'id', where), as_str(value, 'status', where)
                if jid in seen:
                    q_ok = False
                    continue
                seen.add(jid)
                name = value.get('name')
                if type(name) is not str or not name:
                    q_ok = False
                    name = None
                current = value.get('run_attempt') == attempt and value.get('run_id') == rid
                created = as_seconds(value, 'created_at', where)
                begun = as_seconds(value, 'started_at', where, null=True)
                if status in WAITING:
                    status, begun = 'queued', None
                elif status not in ('in_progress', 'completed'):
                    q_ok, status, begun = False, 'queued', None
                if (not current or (status == 'in_progress' and begun is None)
                        or (begun is not None and begun < created)):
                    q_ok = False
                jobs.append({'id': f'job-{jid}',
                             'required': bool(current and name is not None and name in checks),
                             'status': status, 'queued_at': created, 'started_at': begun})
        queue_complete = q_ok
        if not queue_complete:
            complete = False
        try:
            budgets = refresh_budgets(read, budgets)
        except Fail:
            complete = False
    except Stale:
        complete = False
        queue_complete = False
    except Backoff as stop:
        complete = False
        apply_backoff(budgets, stop)
    complete = complete and not read.unknown
    stamp = clock()
    if stamp - read.start > read.window or time.monotonic() - read.mono_start > read.window:
        complete = False
        queue_complete = False
    if any(j['queued_at'] > stamp or (j['started_at'] or 0) > stamp for j in jobs):
        complete = False
        queue_complete = False
    return {'repository': repo, 'observed_at': stamp, 'complete': complete,
            'queue': {'complete': queue_complete, 'jobs': jobs}, 'budgets': budgets}


def write(path, data):
    fd, pending = tempfile.mkstemp(prefix='.observation-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, path)
    finally:
        if os.path.exists(pending):
            os.unlink(pending)


def default_clock():
    fixed = os.environ.get('LAUNCH_FLEET_NOW', '')
    if EPOCH.fullmatch(fixed):
        return lambda: int(fixed)
    return lambda: int(datetime.now(timezone.utc).timestamp())


def main(argv=None):
    parser = argparse.ArgumentParser(prog='overload-supply.py', description=DESCRIPTION)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repository) or not args.output.is_absolute():
        parser.error('invalid repository or a relative output path')
    try:
        args.output.unlink(missing_ok=True)
    except OSError:
        print('overload-supply: the previous observation could not be removed', file=sys.stderr)
        return 1
    try:
        observation = observe(args.repository, default_clock())
    except (Fail, OSError, ValueError, TypeError, KeyError, ArithmeticError):
        print('overload-supply: the queue read failed', file=sys.stderr)
        return 1
    try:
        write(args.output, json.dumps(observation, sort_keys=True, separators=(',', ':')).encode())
    except OSError:
        print('overload-supply: the observation could not be written', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
