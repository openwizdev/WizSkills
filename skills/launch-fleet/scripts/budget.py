#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
import time

FIELDS = ('limit', 'remaining', 'reset', 'resource')
POOLS = ('core', 'graphql')
FLOOR = 1500
COUNT = re.compile(r'0|[1-9][0-9]{0,8}')
STATUS = re.compile(rb'HTTP/\d(\.\d)? \d{3}( .*)?$')
NUMBER = re.compile(r'0|[1-9][0-9]{0,17}')
SAME_WINDOW_SECONDS = 600


class Unknown(Exception):
    pass


def answer(allowed, reason, pool, code):
    print(json.dumps({'allowed': allowed, 'remaining': pool.get('remaining'),
                      'limit': pool.get('limit'), 'reset': pool.get('reset'),
                      'resource': pool.get('resource'), 'reason': reason}))
    return code


def checked(values, where, text):
    missing = [f for f in FIELDS if f not in values]
    if missing:
        raise Unknown('%s has no %s' % (where, ', '.join(missing)))
    if values['resource'] not in POOLS:
        raise Unknown('%s counts an allowance that is neither core nor graphql' % where)
    pool = {'resource': values['resource']}
    for field in ('limit', 'remaining', 'reset'):
        value = values[field]
        if text and isinstance(value, str) and NUMBER.fullmatch(value):
            value = int(value)
        if type(value) is not int or value < 0:
            raise Unknown('%s has an unreadable %s' % (where, field))
        pool[field] = value
    if pool['limit'] == 0 or pool['reset'] == 0 or pool['remaining'] > pool['limit']:
        raise Unknown('%s contradicts itself' % where)
    return pool


def from_file(path, n):
    where = 'answer %d' % n
    try:
        with open(path, 'rb') as f:
            lines = f.read().split(b'\n')
    except OSError:
        raise Unknown("%s can't be read" % where)
    if not STATUS.match(lines[0].rstrip(b'\r')):
        raise Unknown('%s does not start with its status line' % where)
    block = {}
    for line in lines[1:]:
        line = line.rstrip(b'\r')
        if not line:
            return checked(block, where, text=True)
        name, colon, value = line.partition(b':')
        name = name.strip().lower().decode('latin-1')
        if not colon or not name.startswith('x-ratelimit-'):
            continue
        field = name[len('x-ratelimit-'):]
        if field not in FIELDS:
            continue
        value = value.strip().decode('latin-1')
        if block.get(field, value) != value:
            raise Unknown('%s gives two %s headers' % (where, field))
        block[field] = value
    raise Unknown("%s's headers don't end" % where)


def rate_limit(resource):
    where = 'rate_limit'
    try:
        result = subprocess.run(['gh', 'api', 'rate_limit'], capture_output=True,
                                timeout=60, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        raise Unknown("%s can't be read" % where)
    if result.returncode != 0:
        raise Unknown("%s can't be read" % where)
    try:
        values = json.loads(result.stdout)['resources'][resource]
    except (ValueError, TypeError, KeyError):
        raise Unknown('%s has no %s allowance' % (where, resource))
    if not isinstance(values, dict) or values.get('resource', resource) != resource:
        raise Unknown('%s has no %s allowance' % (where, resource))
    return checked({**values, 'resource': resource}, where, text=False)


def newest(pools):
    reset = max(p['reset'] for p in pools)
    window = [p for p in pools if p['reset'] >= reset - SAME_WINDOW_SECONDS]
    if len({p['limit'] for p in window}) != 1:
        raise Unknown('the newest answers give two limits')
    return min(window, key=lambda p: p['remaining'])


def stamp(unix):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(unix))


def admit(n, paths, resource, floor, now):
    pool = None
    if paths:
        pools = [from_file(path, i) for i, path in enumerate(paths, 1)]
        if len({p['resource'] for p in pools} | ({resource} if resource else set())) != 1:
            raise Unknown('the answers count more than one allowance')
        pool = newest(pools)
        resource = pool['resource']
    if pool is None or pool['reset'] <= now:
        pool = rate_limit(resource or 'core')
    after, limit = pool['remaining'] - n, pool['limit']
    keep = max(-(-limit // 4), floor)
    if after >= keep:
        return answer(True, '%d %s reads leave %d of %d, at or above the %d kept for builders and reviewers'
                      % (n, pool['resource'], after, limit, keep), pool, 0)
    return answer(False, '%d %s reads would leave %d of %d, under the %d kept for builders and reviewers, until %s'
                  % (n, pool['resource'], after, limit, keep, stamp(pool['reset'])), pool, 1)


def options(argv):
    if len(argv) < 2 or argv[0] != 'admit' or not COUNT.fullmatch(argv[1]) or argv[1] == '0':
        return None
    paths, resource, floor, rest = [], None, FLOOR, argv[2:]
    while rest:
        word = rest.pop(0)
        if word in ('--floor', '--resource'):
            if not rest:
                return None
            value = rest.pop(0)
            if word == '--floor' and COUNT.fullmatch(value):
                floor = int(value)
            elif word == '--resource' and value in POOLS:
                resource = value
            else:
                return None
        else:
            paths.append(word)
    return int(argv[1]), paths, resource, floor


def main(argv):
    chosen = options(argv)
    if chosen is None:
        print('usage: budget.py admit N [--floor N] [--resource core|graphql] [HEADERS-FILE...],'
              ' N a whole number of reads from 1', file=sys.stderr)
        return 2
    n, paths, resource, floor = chosen
    try:
        now = int(os.environ.get('LAUNCH_FLEET_NOW') or time.time())
    except ValueError:
        print('budget.py: LAUNCH_FLEET_NOW is not a time', file=sys.stderr)
        return 2
    try:
        return admit(n, paths, resource, floor, now)
    except Unknown as e:
        return answer(False, 'unknown allowance: %s' % e, {'resource': resource}, 2)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
