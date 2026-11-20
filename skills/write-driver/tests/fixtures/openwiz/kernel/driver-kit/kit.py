#!/usr/bin/env python3
"""A synthetic stand-in for OpenWiz's kernel/driver-kit/kit.py, for write-driver's own tests only.

It writes its arguments, one per line, to the file FAKE_KIT_ARGV names, prints the file FAKE_KIT_OUT names
and exits FAKE_KIT_EXIT. With FAKE_KIT_STARTS set, it first calls the driver's `start` that many times, as
the real kit's start check does, and never stops what it started (the real kit skips its stop check when
start fails). The real kit is OpenWiz's; write-driver's eval (WD3) runs it.

Its credential and schema checks, from SHAPES to holds_credential, are the real kit's, copied byte for byte
from OpenWiz's kernel/driver-kit/kit.py, with its schema.json beside them: write-driver's proxy imports them.
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Known credential shapes: the pinned status contract's credential rules, as its writer
# (skills/launch-fleet/scripts/status.py at that commit) recognises them, then the kit's earlier shapes; and any
# value of the kit's own environment whose name says it is a secret.
SHAPES = re.compile(r'\b(?:[a-z_]*token|[a-z_]*key|secret|password|passwd|pwd|sig|signature|auth|credentials?)\s*='
                    r'|\b(?:password|passwd|secret|token)\s*:\s*\S|\bbearer\s+\S'
                    r'|\bgh[pousr]_[A-Za-z0-9]{8,}|\bgithub_pat_|\bAKIA[0-9A-Z]{16}\b'
                    r'|\bxox[abprs]-|\bsk-[A-Za-z0-9_-]{16,}'
                    r'|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}'
                    r'|xox[abposr]-[A-Za-z0-9-]{10,}|sk-[A-Za-z0-9_-]{20,}', re.I)
SECRETS = [v for k, v in os.environ.items()
           if re.search(r'TOKEN|SECRET|PASSWORD|CREDENTIAL|_KEY$|^KEY', k.upper()) and len(v) >= 8]
KEYWORDS = {'$schema', 'type', 'required', 'additionalProperties', 'properties', 'pattern', 'minLength',
            'maxLength', 'minimum', 'items', 'minItems', 'uniqueItems', 'enum', 'const', 'allOf', 'contains'}
TYPES = {'object': dict, 'array': list, 'string': str, 'boolean': bool}


class Unusable(Exception):
    pass


def _unique(pairs):
    if len({k for k, _ in pairs}) != len(pairs):
        raise ValueError('a key is repeated')
    return dict(pairs)


def parse(text):
    """One JSON object or value, refusing a repeated key (ValueError)."""
    return json.loads(text, object_pairs_hook=_unique)


def _known(s):
    if not isinstance(s, dict) or set(s) - KEYWORDS:
        raise Unusable('schema.json uses a keyword the kit does not check')
    for sub in list(s.get('properties', {}).values()) + s.get('allOf', []) + \
            [s[k] for k in ('items', 'contains') if k in s]:
        _known(sub)


def load_schema():
    with open(os.path.join(HERE, 'schema.json')) as f:
        schema = parse(f.read())
    for c in schema['commands'].values():
        for s in (c['input'], c['output']):
            if s is not None:
                _known(s)
    _known(schema['error'])
    return schema


def _same(a, b):
    return a == b and type(a) is type(b)


def invalid(value, s, at='the answer'):
    """Why value breaks the JSON Schema s, or None. It reads only KEYWORDS, as JSON Schema means them."""
    if 'const' in s and not _same(value, s['const']):
        return '%s is not %s' % (at, json.dumps(s['const']))
    if 'enum' in s and not any(_same(value, e) for e in s['enum']):
        return '%s is not one of %s' % (at, ', '.join(map(json.dumps, s['enum'])))
    t = s.get('type')
    if t and not (type(value) is int if t == 'integer' else type(value) is TYPES[t]):
        return '%s is not a%s %s' % (at, 'n' if t[0] in 'aeiou' else '', t)
    if isinstance(value, str):
        if not s.get('minLength', 0) <= len(value) <= s.get('maxLength', len(value)):
            return '%s has the wrong length' % at
        p = s.get('pattern')
        if p and not re.search(p[:-1] + r'\Z' if p.endswith('$') else p, value):
            return '%s does not match %s' % (at, p)
    if t == 'integer' and value < s.get('minimum', value):
        return '%s is below %s' % (at, s['minimum'])
    if isinstance(value, list):
        if len(value) < s.get('minItems', 0):
            return '%s has too few items' % at
        if s.get('uniqueItems') and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            return '%s repeats an item' % at
        for v in value if 'items' in s else []:
            why = invalid(v, s['items'], 'an item of ' + at)
            if why:
                return why
        if 'contains' in s and not any(invalid(v, s['contains']) is None for v in value):
            return '%s lacks %s' % (at, json.dumps(s['contains'].get('const', s['contains'])))
    if isinstance(value, dict):
        for k in s.get('required', []):
            if k not in value:
                return '%s lacks %s' % (at, k)
        if s.get('additionalProperties') is False and set(value) - set(s.get('properties', {})):
            return '%s has an unknown field %s' % (at, sorted(set(value) - set(s['properties']))[0])
        for k, sub in s.get('properties', {}).items():
            why = k in value and invalid(value[k], sub, k)
            if why:
                return why
    for sub in s.get('allOf', []):
        why = invalid(value, sub, at)
        if why:
            return why
    return None


def records_version():
    """The records version this kernel implements, from records.v1.md's title."""
    with open(os.path.join(HERE, '..', 'records.v1.md')) as f:
        m = re.search(r'\(`(openwiz:records v[0-9]+)`\)', f.readline())
    if not m:
        raise Unusable('records.v1.md names no records version')
    return m.group(1)


def texts(value):
    """Every string and object key inside a decoded JSON value."""
    stack = [value]
    while stack:
        v = stack.pop()
        if isinstance(v, str):
            yield v
        elif isinstance(v, dict):
            yield from v
            stack += v.values()
        elif isinstance(v, list):
            stack += v


def holds_credential(text):
    return bool(SHAPES.search(text)) or any(v in text for v in SECRETS)


def main():
    args = sys.argv[1:]
    with open(os.environ['FAKE_KIT_ARGV'], 'w') as f:
        f.write('\n'.join(args) + '\n')
    value = lambda name: args[args.index(name) + 1]
    for _ in range(int(os.environ.get('FAKE_KIT_STARTS', '0'))):
        subprocess.run([value('--driver'), 'start'], capture_output=True, text=True, input=json.dumps(
            {'repository': value('--repo'), 'ticket': int(value('--ticket')), 'skill': value('--skill'),
             'harness': value('--harness'), 'model': value('--model')}))
    with open(os.environ['FAKE_KIT_OUT']) as f:
        sys.stdout.write(f.read())
    sys.exit(int(os.environ.get('FAKE_KIT_EXIT', '0')))


if __name__ == '__main__':
    main()
