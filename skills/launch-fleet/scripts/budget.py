#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
import time

FIELDS = ('limit', 'remaining', 'reset', 'resource')
POOL = 'core'
STATUS = re.compile(rb'HTTP/\d(\.\d)? \d{3}( .*)?$')
NUMBER = re.compile(r'(0|[1-9][0-9]{0,17})$')
SAME_WINDOW_SECONDS = 600


class Unknown(Exception):
    pass


def answer(allowed, reason, pool=None, code=None):
    pool = pool or {}
    print(json.dumps({'allowed': allowed, 'remaining': pool.get('remaining'),
                      'limit': pool.get('limit'), 'reset': pool.get('reset'),
                      'reason': reason}))
    return code


def checked(values, where):
    missing = [f for f in FIELDS if f not in values]
    if missing:
        raise Unknown('%s has no %s' % (where, ', '.join(missing)))
    if values['resource'] != POOL:
        resource = values['resource'] if re.fullmatch(r'[a-z_]{1,40}', str(values['resource'])) else 'another'
        raise Unknown("%s counts GitHub's %s allowance, not REST's %s" % (where, resource, POOL))
    pool = {}
    for field in ('limit', 'remaining', 'reset'):
        value = values[field]
        if isinstance(value, str) and NUMBER.match(value):
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
    pools, block = [], None
    for line in lines:
        line = line.rstrip(b'\r')
        if block is None:
            if STATUS.match(line):
                block = {}
            continue
        if not line:
            pools.append(checked(block, where))
            block = None
            continue
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
    if block is not None:
        raise Unknown("%s's headers don't end" % where)
    if not pools:
        raise Unknown('%s has no response headers' % where)
    return pools


def rate_limit():
    where = 'rate_limit'
    try:
        result = subprocess.run(['gh', 'api', 'rate_limit'], capture_output=True,
                                timeout=60, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        raise Unknown("%s can't be read" % where)
    if result.returncode != 0:
        raise Unknown("%s can't be read" % where)
    try:
        values = json.loads(result.stdout)['resources'][POOL]
    except (ValueError, TypeError, KeyError):
        raise Unknown('%s has no %s allowance' % (where, POOL))
    if not isinstance(values, dict):
        raise Unknown('%s has no %s allowance' % (where, POOL))
    return checked(values, where)


def newest(pools):
    reset = max(p['reset'] for p in pools)
    window = [p for p in pools if p['reset'] >= reset - SAME_WINDOW_SECONDS]
    if len({p['limit'] for p in window}) != 1:
        raise Unknown('the newest answers give two limits')
    return min(window, key=lambda p: p['remaining'])


def stamp(unix):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(unix))


def admit(n, paths, now):
    pool = None
    if paths:
        pool = newest([p for i, path in enumerate(paths, 1) for p in from_file(path, i)])
    if pool is None or pool['reset'] <= now:
        pool = rate_limit()
    after, limit = pool['remaining'] - n, pool['limit']
    keep = -(-limit // 4)
    if 4 * after >= limit:
        return answer(True, '%d REST reads leave %d of %d, at or above the %d kept for builders and reviewers'
                      % (n, after, limit, keep), pool, 0)
    return answer(False, '%d REST reads would leave %d of %d, under the %d kept for builders and reviewers, until %s'
                  % (n, after, limit, keep, stamp(pool['reset'])), pool, 1)


def main(argv):
    if len(argv) < 2 or argv[0] != 'admit' or not re.fullmatch(r'[1-9][0-9]{0,8}', argv[1]):
        print('usage: budget.py admit N [HEADERS-FILE...], N a whole number of reads from 1', file=sys.stderr)
        return 2
    try:
        now = int(os.environ.get('LAUNCH_FLEET_NOW') or time.time())
    except ValueError:
        print('budget.py: LAUNCH_FLEET_NOW is not a time', file=sys.stderr)
        return 2
    try:
        return admit(int(argv[1]), argv[2:], now)
    except Unknown as e:
        return answer(False, 'unknown REST allowance: %s' % e, code=2)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
