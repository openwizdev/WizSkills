#!/usr/bin/env python3
from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys

USAGE = """A `gh` meter: who spends the GitHub allowance (OpenWiz#2621, FR5 of #2428).

gh-meter.py install DIR    write DIR/gh, a shim that runs the real `gh`
gh-meter.py report LOG...  calls and REST units per role and per endpoint,
                           and the top five endpoints by REST units

Put DIR first on PATH. The shim runs the next `gh` on PATH after DIR (or
GH_METER_REAL) with the caller's arguments, input, output and exit status;
a `gh` before DIR (a caller's own wrapper that runs the shim) is never it.
It exits 127, running nothing, when DIR is not on PATH, when no `gh` follows
it, or when it is entered again from its own real `gh`'s run.
When GH_METER_LOG is set, it appends one JSON line per call:

  time, role (GH_METER_ROLE: fleet, builder, reviewer, orchestrator,
  heartbeat, other; anything else is other), method, endpoint template
  (query string dropped, numbers as :n, commit SHAs as :sha), kind (rest,
  graphql, or none for a local command such as `gh auth`), exit, rest_units,
  rest_used_before and rest_used_after, and status for an --include read.

rest_used_* is REST's `used` from `gh api rate_limit`, which costs no
allowance, read just before and after the call; null when unreadable, or
when GH_METER_RATE=0 (fixture runs, where the fake has no allowance).
On a shared account other agents' calls land between the two reads, so
their difference is a measured upper bound, not this call's own cost.

rest_units is this call's own REST requests, counted, not measured: one for
a REST call; with --include, one per HTTP status line that is not 304 (a
paged read's pages; a conditional read's 304 costs nothing); none for
GraphQL, `rate_limit` and local commands. A --paginate read without
--include counts one, a lower bound.

The log never holds a token, a body, an argument value or any response
header: only the fields above. Exit 2 on bad arguments or an unreadable log.
"""
FIELDS = ('time', 'role', 'method', 'endpoint', 'kind', 'exit', 'rest_units', 'rest_used_before',
          'rest_used_after')
ROLES = ('fleet', 'builder', 'reviewer', 'orchestrator', 'heartbeat', 'other')
LOCAL = {'auth', 'config', 'alias', 'help', 'version', 'completion', 'extension', '--version', '--help'}
GRAPHQL = {'issue', 'pr', 'repo', 'project'}
VALUE_FLAGS = {'-X', '--method', '-H', '--header', '-f', '--raw-field', '-F', '--field', '--input', '-q', '--jq',
               '-t', '--template', '--cache', '--hostname', '-p', '--preview'}
BODY_FLAGS = {'-f', '--raw-field', '-F', '--field', '--input'}
NUMBER = re.compile(r'[0-9]+')
SHA = re.compile(r'[0-9a-f]{7,40}')
STATUS = re.compile(r'HTTP/[0-9.]+ ([0-9]{3})')


def fail(message):
    print('gh-meter: %s' % message, file=sys.stderr)
    sys.exit(2)


def template(path):
    parts = []
    for part in path.split('?', 1)[0].strip('/').split('/'):
        if NUMBER.fullmatch(part):
            part = ':n'
        elif SHA.fullmatch(part) and re.search('[0-9]', part) and re.search('[a-f]', part):
            part = ':sha'
        parts.append(part)
    return '/'.join(parts)


def parse_api(args):
    method, endpoint, body, include = None, None, False, False
    i = 0
    while i < len(args):
        a = args[i]
        name = a.split('=', 1)[0] if a.startswith('--') else a
        value = a.split('=', 1)[1] if a.startswith('--') and '=' in a else None
        if name in VALUE_FLAGS:
            if value is None:
                i += 1
                value = args[i] if i < len(args) else ''
            if name in ('-X', '--method'):
                method = value.upper()
            body = body or name in BODY_FLAGS
        elif name in ('-i', '--include'):
            include = True
        elif not a.startswith('-') and endpoint is None:
            endpoint = a
        i += 1
    endpoint = template(endpoint or '')
    if endpoint == 'graphql':
        return method or 'POST', endpoint, 'graphql', include
    return method or ('POST' if body else 'GET'), endpoint, 'rest', include


def parse(args):
    if args[:1] == ['api']:
        return parse_api(args[1:])
    words, skip = [], False
    for a in args:
        if skip or a.startswith('-'):
            skip = a in ('-R', '--repo')
            continue
        words.append(a)
    words = words[:2]
    command = words[0] if words else (args[0] if args else '')
    verb = words[1] if len(words) > 1 else ''
    kind = 'none' if command in LOCAL or not args else 'graphql' if command in GRAPHQL else 'rest'
    return verb, ' '.join(words), kind, False


def real_gh():
    if os.environ.get('GH_METER_ACTIVE'):
        refuse('the shim called itself: a gh after it on PATH runs the shim again')
    os.environ['GH_METER_ACTIVE'] = '1'
    if os.environ.get('GH_METER_REAL'):
        return os.environ['GH_METER_REAL']
    shim = os.path.realpath(os.environ.get('GH_METER_SHIM_DIR', ''))
    dirs = os.environ.get('PATH', '').split(os.pathsep)
    at = [i for i, d in enumerate(dirs) if d and os.path.realpath(d) == shim]
    if not at:
        refuse("the shim's directory is not on PATH")
    for d in dirs[at[-1] + 1:]:
        candidate = os.path.join(d, 'gh')
        if d and os.path.realpath(d) != shim and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    refuse('no real gh on PATH after the shim')


def refuse(message):
    print('gh-meter: %s' % message, file=sys.stderr)
    sys.exit(127)


def rest_used(gh):
    if os.environ.get('GH_METER_RATE') == '0':
        return None
    try:
        run = subprocess.run([gh, 'api', 'rate_limit'], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        used = json.loads(run.stdout)['resources']['core']['used'] if run.returncode == 0 else None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return used if isinstance(used, int) and not isinstance(used, bool) else None


def shim(args):
    gh = real_gh()
    log = os.environ.get('GH_METER_LOG')
    if not log:
        os.execv(gh, [gh, *args])
    method, endpoint, kind, include = parse(args)
    free = kind != 'rest' or endpoint == 'rate_limit'
    before = None if kind == 'none' else rest_used(gh)
    statuses = []
    if include:
        run = subprocess.run([gh, *args], stdout=subprocess.PIPE)
        sys.stdout.buffer.write(run.stdout)
        sys.stdout.buffer.flush()
        statuses = [int(m.group(1)) for m in STATUS.finditer(run.stdout.decode('utf-8', 'replace'))
                    if m.start() == 0 or run.stdout[m.start() - 1:m.start()] == b'\n']
    else:
        run = subprocess.run([gh, *args])
    after = None if kind == 'none' else rest_used(gh)
    role = os.environ.get('GH_METER_ROLE', 'other')
    line = {'time': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'role': role if role in ROLES else 'other', 'method': method, 'endpoint': endpoint, 'kind': kind,
            'exit': run.returncode,
            'rest_units': 0 if free else sum(s != 304 for s in statuses) if statuses else 1,
            'rest_used_before': before, 'rest_used_after': after}
    if statuses:
        line['status'] = statuses[-1]
    fd = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, (json.dumps(line) + '\n').encode())
    finally:
        os.close(fd)
    sys.exit(run.returncode)


def install(d):
    d = Path(d).resolve()
    paths = (str(d), sys.executable, str(Path(__file__).resolve()))
    if any("'" in p for p in paths):
        fail("a path with a ' can't be quoted in the shim")
    d.mkdir(parents=True, exist_ok=True)
    (d / 'gh').write_text("#!/bin/sh\nGH_METER_SHIM_DIR='%s' exec '%s' -I '%s' exec \"$@\"\n" % paths)
    (d / 'gh').chmod(0o755)


def unique(pairs):
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError('a repeated key')
    return dict(pairs)


def whole(value, nullable=False):
    if value is None:
        return nullable
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def meter_line(call):
    if not isinstance(call, dict) or not set(FIELDS) <= set(call) <= set(FIELDS) | {'status'}:
        return False
    return (call['role'] in ROLES and call['kind'] in ('rest', 'graphql', 'none')
            and all(isinstance(call[k], str) for k in ('time', 'method', 'endpoint'))
            and isinstance(call['exit'], int) and not isinstance(call['exit'], bool) and whole(call['rest_units'])
            and whole(call['rest_used_before'], True) and whole(call['rest_used_after'], True)
            and whole(call.get('status'), 'status' not in call))


def read(paths):
    calls = []
    for path in paths:
        try:
            with open(path) as f:
                for n, text in enumerate(f, 1):
                    call = json.loads(text, object_pairs_hook=unique)
                    if not meter_line(call):
                        raise ValueError('line %d is not a meter line' % n)
                    calls.append(call)
        except (OSError, ValueError) as e:
            fail('%s: %s' % (path, e))
    return calls


def delta(call):
    a, b = call.get('rest_used_before'), call.get('rest_used_after')
    return b - a if isinstance(a, int) and isinstance(b, int) else None


def report(paths):
    calls = read(paths)
    roles = defaultdict(lambda: [0, 0, 0, 0, None])
    endpoints = defaultdict(lambda: [0, 0])
    for c in calls:
        r = roles[c['role']]
        r[0] += 1
        r[1] += c['kind'] == 'rest'
        r[2] += c['kind'] == 'graphql'
        r[3] += c.get('rest_units', 0)
        d = delta(c)
        if d is not None:
            r[4] = (r[4] or 0) + d
        e = endpoints[(c['method'], c['endpoint'], c['kind'])]
        e[0] += 1
        e[1] += c.get('rest_units', 0)
    out = ['Total: %d calls, %d REST units, %d GraphQL calls, from %d logs'
           % (len(calls), sum(r[3] for r in roles.values()), sum(r[2] for r in roles.values()), len(paths)),
           '', 'Per role (REST units counted; used delta measured, null-free calls only):', '',
           '| Role | Calls | REST calls | GraphQL calls | REST units | Used delta |', '| --- | --- | --- | --- | --- | --- |']
    order = sorted(roles, key=lambda r: ROLES.index(r) if r in ROLES else len(ROLES))
    out += ['| %s | %d | %d | %d | %d | %s |' % (r, *roles[r][:4], '-' if roles[r][4] is None else roles[r][4])
            for r in order]
    out += ['', 'Per endpoint:', '', '| Method | Endpoint | Kind | Calls | REST units |', '| --- | --- | --- | --- | --- |']
    ranked = sorted(endpoints.items(), key=lambda kv: (-kv[1][1], -kv[1][0], kv[0][1], kv[0][0]))
    out += ['| %s | %s | %s | %d | %d |' % (*k, *v) for k, v in ranked]
    out += ['', 'Top five endpoints by REST units:']
    out += ['%d. %s %s: %d units, %d calls' % (i, k[0], k[1], v[1], v[0])
            for i, (k, v) in enumerate([kv for kv in ranked if kv[1][1] > 0][:5], 1)]
    print('\n'.join(out))


def main(argv):
    if argv[:1] == ['exec']:
        shim(argv[1:])
    elif argv[:1] == ['install'] and len(argv) == 2:
        install(argv[1])
    elif argv[:1] == ['report'] and len(argv) > 1:
        report(argv[1:])
    else:
        fail(USAGE.strip())


if __name__ == '__main__':
    main(sys.argv[1:])
