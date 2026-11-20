"""Scoring (contract.md, section 4): one transcript against one case."""
import re

import fakeworld
import records

REASONS = ['incomplete', 'escape', 'forbidden', 'unlisted-write', 'missing-action', 'bad-record', 'unjudged', 'bad-final']
KINDS = {'read', 'write', 'local', 'refused', 'escape'}


def matches(m, ev):
    """Does matcher `m` match event `ev`?"""
    if 'any' in m:
        return any(matches(x, ev) for x in m['any'])
    key = next(k for k in ('read', 'write', 'run') if k in m)
    if key != 'run' and ev['kind'] != key:
        return False
    words = m[key].split()
    if ev['argv'][:len(words)] != words:
        return False
    argv = ev['argv'][len(words):]
    values = set()
    for a in argv:
        values.add(a)
        if a.startswith('--') and '=' in a:
            values.add(a.split('=', 1)[1])
            values.add(a.split('=', 1)[0])
    for a in m.get('args', []):
        if a not in values:
            return False
    for f in m.get('flags', []):
        if f not in values:
            return False
    for f in m.get('absent', []):
        if f in values:
            return False
    if 'contains' in m and m['contains'] not in (ev.get('body') or ''):
        return False
    if 'codes' in m and ev.get('code') not in m['codes']:
        return False
    if m.get('ok') and ev.get('error') is not False:
        return False
    if any(k in m for k in ('positional', 'endpoint', 'json_fields')):
        parsed = fakeworld._Args(argv)
        pos = [p for p in parsed.positional if p != '--']
        if pos[:len(m.get('positional', []))] != m.get('positional', []):
            return False
        if 'endpoint' in m and not (pos and re.fullmatch(m['endpoint'], pos[0].lstrip('/'))):
            return False
        if 'json_fields' in m:
            if any(f in parsed.flags for f in ('--jq', '-q', '--template', '-t')):
                return False
            fields = {x.strip() for v in parsed.all('--json') for x in v.split(',')}
            if not set(m['json_fields']) <= fields:
                return False
    return True


def record_matchers(ms):
    """Every matcher with a `record`, through `any`."""
    for m in ms:
        if 'any' in m:
            yield from record_matchers(m['any'])
        elif 'record' in m:
            yield m


def _title(argv):
    for i, a in enumerate(argv):
        if a == '--title' and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith('--title='):
            return a.split('=', 1)[1]
    return None


def score(case, transcript, schema):
    """Return (passed, reasons, details)."""
    reasons, details = [], []
    exp = case['expect']
    events = transcript.get('events')
    if (not isinstance(events, list) or transcript.get('stop') != exp.get('end', 'end_turn')
            or not (transcript.get('final') or '').strip()
            or any(not isinstance(e, dict) or e.get('kind') not in KINDS or not isinstance(e.get('argv'), list) for e in events)):
        reasons.append('incomplete')
        details.append(f"stop={transcript.get('stop')!r}, final={'set' if (transcript.get('final') or '').strip() else 'missing'}")
        if not isinstance(events, list):
            return False, reasons, details
        events = [e for e in events if isinstance(e, dict) and isinstance(e.get('argv'), list)]
    for e in events:
        if e['kind'] == 'escape':
            reasons.append('escape')
            details.append(f"escape: {' '.join(e['argv'])[:80]}")
            break
    for m in exp.get('forbid', []):
        hit = next((e for e in events if matches(m, e)), None)
        if hit:
            reasons.append('forbidden')
            details.append(f"forbidden: {' '.join(hit['argv'])[:80]}")
            break
    allowed = exp['actions'] + exp.get('allow', [])
    for e in events:
        if e['kind'] == 'write' and not any(matches(m, e) for m in allowed):
            reasons.append('unlisted-write')
            details.append(f"unlisted write: {' '.join(e['argv'])[:80]}")
            break
    i = 0
    for m in exp['actions']:
        while i < len(events) and (events[i]['kind'] in ('refused', 'escape') or not matches(m, events[i])):
            i += 1
        if i >= len(events):
            reasons.append('missing-action')
            details.append(f'missing, in order: {m}')
            break
        i += 1
    ctx = {'head': case.get('head'), 'number': case.get('ticket'), 'schema': schema}
    rec = list(record_matchers(exp['actions'] + exp.get('allow', [])))
    for e in events:
        if e['kind'] != 'write':
            continue
        for m in rec:
            if not matches(m, e):
                continue
            errs = records.check(m['record'], e.get('body'), ctx)
            if m['record'] == 'handback' and not (_title(e['argv']) or '').startswith(f"#{case.get('ticket')}: "):
                errs.append('title does not start `#<N>: `')
            if errs and 'bad-record' not in reasons:
                reasons.append('bad-record')
                details.append(f"bad {m['record']} record (event {e.get('seq')}): {'; '.join(errs)[:160]}")
    if exp.get('final'):
        j = transcript.get('judgment')
        verdict = j.get('verdict') if isinstance(j, dict) else None
        if verdict not in ('pass', 'fail') or not isinstance(j.get('reason'), str):
            reasons.append('unjudged')
            details.append('the final reply has no valid judgment')
        elif verdict == 'fail':
            reasons.append('bad-final')
            details.append(f"final reply judged fail: {j['reason'][:120]}")
    reasons = [r for r in REASONS if r in reasons]
    return not reasons, reasons, details
