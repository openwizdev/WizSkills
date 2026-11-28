import hashlib
import importlib.util
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
SHA = re.compile(r'[0-9a-f]{40}')
STAGES = ('fix_after_changes', 'builder_question_answer')
UNCERTAIN = {('transport', 'uncertain'), ('completion', 'uncertain')}


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


effects = _load(HERE / 'effects.py', 'ops_effects_inbox')
limits = _load(HERE / 'carried/limits.py', 'factory_limits_inbox')


def _record(value):
    return effects.read_record(json.dumps(value, allow_nan=False))


def _digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _unique(records):
    seen = {}
    for record in map(_record, records):
        identity = (record['repository'], record['id'])
        if identity in seen and seen[identity] != record:
            raise ValueError('conflicting immutable record identity')
        seen[identity] = record
    return list(seen.values())


def _sequences(intents, view):
    numbers = sorted(i['sequence'] for i in intents
                     if (i['repository'], i['ticket'], i['approval']) == (view['repository'], view['ticket'], view['approval']))
    if numbers != list(range(1, len(numbers) + 1)):
        raise ValueError('missing or conflicting sequence allocation')
    return len(numbers)


def _identity(record):
    return (record['subject']['number'], record['action'], record['destination'], record['assignment'],
            record['prior_verdict'], record['head'], json.dumps(record['approval'], sort_keys=True),
            record['evidence'][0]['source'])


def message(view, destination, assignment, prior_verdict, head, evidence, prefix, created_at=None):
    intents = [r for r in _unique(view['intents']) if r['kind'] == 'intent']
    count = _sequences(intents, view)
    subject = {'kind': 'pull_request', 'number': view['pull_request']}
    intent = dict(schema='openwiz.ops-dispatch.v1', kind='intent', repository=view['repository'],
                  spec=view['spec'], ticket=view['ticket'], subject=subject, operation_key='0' * 64,
                  created_at=view['now'] if created_at is None else created_at, approval=view['approval'],
                  rule=view['rule'], evidence=evidence, action='delivery', destination=destination,
                  assignment=assignment, prior_verdict=prior_verdict, head=head, sequence=count + 1)
    for existing in intents:
        if _identity(existing) == _identity(intent):
            return 'duplicate', existing
    intent['id'] = f'{prefix}-{subject["number"]}-{_digest(list(_identity(intent)))[:16]}'
    intent['operation_key'] = effects.operation_key(intent)
    return 'record', _record(intent)


def _authored(items, view):
    authors = view.get('authors', frozenset())
    return [i for i in items if type(i.get('author')) is str and i['author'].lower() in authors]


def spans(records):
    ids = [r['comment'] for r in records]
    if len(ids) != len(set(ids)):
        return None
    span = None
    for r in sorted(records, key=lambda r: r['comment']):
        line = r['line'].removeprefix('launch-fleet: ')
        if 'thr_' in line:
            return None
        match = re.fullmatch(r'(review started|re-check sent|review told again|review given up) ([0-9a-f]{40})(?:: .+)?', line)
        if not match:
            continue
        kind, commit = match.groups()
        if kind == 'review started':
            span = {'start': r['comment'], 'open': True, 'sent': {}}
        elif span is None:
            return None
        elif kind == 'review given up':
            span['open'] = False
        elif kind == 're-check sent':
            span['sent'][commit] = r['comment']
    return span


def _verdict_evidence(view, verdict):
    source = f'https://github.com/{view["repository"]}/pull/{view["pull_request"]}#issuecomment-{verdict["comment"]}'
    return [{'evidence_class': 'observation', 'source': source,
             'digest': _digest({'verdict': verdict, 'ci': view.get('ci'), 'head': view['head']})}]


def recheck(view):
    if not view['complete']:
        return 'refused', 'incomplete read'
    span = spans(_authored(view['records'], view))
    if span is None:
        return 'refused', 'ambiguous reviewer'
    if not span['open']:
        return 'refused', 'reviewer retired'
    verdicts = _authored(view['verdicts'], view)
    if not verdicts:
        return 'none', 'no verdict'
    verdict = max(verdicts, key=lambda v: v['comment'])
    if verdict['comment'] < span['start']:
        return 'none', 'verdict precedes the current reviewer span'
    if verdict['head'] == view['head']:
        return 'none', 'head unchanged since the verdict'
    ci = view['ci']
    if not ci or ci['head'] != view['head'] or ci['state'] != 'success':
        return 'none', 'ci not green at the head'
    if span['sent'].get(view['head'], 0) > verdict['comment']:
        return 'none', 'recheck already sent'
    try:
        return message(view, 'reviewer', f'review-span-{span["start"]}', verdict['comment'], view['head'],
                       _verdict_evidence(view, verdict), 'recheck')
    except ValueError as error:
        return 'refused', str(error)


def findings(view):
    if not view['complete']:
        return 'refused', 'incomplete read'
    verdicts = _authored(view['verdicts'], view)
    if not verdicts:
        return 'none', 'no verdict'
    verdict = max(verdicts, key=lambda v: v['comment'])
    if verdict['verdict'] != 'CHANGES' or verdict['head'] != view['head']:
        return 'none', 'no CHANGES at the head'
    try:
        return message(view, 'builder', view['builder'], verdict['comment'], verdict['head'],
                       _verdict_evidence(view, verdict), 'findings')
    except ValueError as error:
        return 'refused', str(error)


def _result(intent, state, reason):
    return dict(schema='openwiz.ops-dispatch.v1', kind='result', operation_key=intent['operation_key'],
                intent_id=intent['id'], state=state, reason=reason, next='end', effects=[])


def _belongs(record, intent):
    return (record['kind'] != 'intent' and record['operation_key'] == intent['operation_key']
            and record['intent_id'] == intent['id']
            and all(record[k] == intent[k] for k in ('repository', 'spec', 'ticket', 'subject', 'approval')))


def _acked(record, intent, verified):
    return (record['kind'] == 'ack' and record['id'] in verified and _belongs(record, intent)
            and (record['recipient'], record['assignment'], record['sequence'])
            == (intent['destination'], intent['assignment'], intent['sequence'])
            and intent['head'] in (None, record['checked_head']))


def pull(view, recipient, assignment, own):
    stop = {'complete': False, 'cursor': view['cursor'], 'items': [], 'next': 'end'}
    if not view['complete']:
        return stop
    try:
        current_assignments = view['assignments']
        if not isinstance(current_assignments, dict) or any(
                current_assignments[role] is not None
                and (type(current_assignments[role]) is not str
                     or not re.fullmatch(r'[a-z][a-z0-9-]{0,79}', current_assignments[role]))
                for role in ('builder', 'reviewer')):
            return stop
        records = _unique(view['records'])
        if any((r['repository'], r['spec'], r['ticket']) != (view['repository'], view['spec'], view['ticket'])
               for r in records):
            return stop
        intents = [r for r in records if r['kind'] == 'intent']
        _sequences(intents, view)
        latest = max((v['comment'] for v in _authored(view['verdicts'], view)), default=None)
    except (KeyError, TypeError, ValueError):
        return stop
    verified = own | set(view['verified_acks'])
    items, blocked = [], set()
    for intent in sorted(intents, key=lambda i: (i['approval']['revision'], i['sequence'])):
        events = [r for r in records if _belongs(r, intent)]
        states = {(r['kind'], r.get('state')) for r in events}
        stream = json.dumps(intent['approval'], sort_keys=True)
        destination = intent['destination']
        if states & UNCERTAIN:
            state = 'reconcile', 'uncertain_outcome'
        elif any(_acked(r, intent, verified) for r in events):
            state = 'acknowledged', 'record_only'
        elif ('completion', 'completed') in states:
            state = 'complete', 'already_complete'
        elif (('completion', 'superseded') in states or intent['approval'] != view['approval']
              or intent['head'] not in (None, view['head'])
              or (destination in ('builder', 'reviewer')
                  and (current_assignments[destination] is None
                       or intent['assignment'] != current_assignments[destination]
                       or intent['prior_verdict'] not in (None, latest)))):
            state = 'superseded', 'superseded'
        elif stream in blocked:
            state = 'deferred', 'out_of_order'
        else:
            state = 'recorded', 'record_only'
        if state[0] in ('recorded', 'reconcile', 'deferred'):
            blocked.add(stream)
        if (intent['destination'], intent['assignment']) == (recipient, assignment):
            items.append(_record(_result(intent, *state)))
    return {'complete': True, 'cursor': view['read_through'], 'items': items, 'next': 'end'}


def acknowledge(view, recipient, assignment, own, intent_id, ident, created_at, evidence, checks_digest):
    result = pull(view, recipient, assignment, own)
    item = next((i for i in result['items'] if i['intent_id'] == intent_id), None)
    if item is None or item['state'] != 'recorded':
        raise ValueError('not this recipient\'s next pending item')
    intent = next(r for r in _unique(view['records']) if r['kind'] == 'intent' and r['id'] == intent_id)
    ack = {k: intent[k] for k in ('schema', 'repository', 'spec', 'ticket', 'subject', 'operation_key',
                                  'approval', 'rule')}
    ack.update(kind='ack', id=ident, created_at=created_at, evidence=evidence, intent_id=intent_id,
               recipient=recipient, assignment=assignment, sequence=intent['sequence'],
               checked_head=view['head'], checks_digest=checks_digest)
    return _record(ack)


def wake(view, recipient, assignment, own, source):
    result = pull(view, recipient, assignment, own)
    due = [i['intent_id'] for i in result['items'] if i['state'] == 'recorded']
    return dict(result, source=source, due=due, next='end')


def recovery(wakes):
    if any(w['source'] == 'independent' and w['complete'] and w['items'] for w in wakes):
        return 'pull usable (synthetic)'
    return 'unverified'


def _ungated(start, end, held):
    total, cursor = end - start, start
    for on, off in held:
        on, off = max(on, cursor), min(off, end)
        if off > on:
            total -= off - on
            cursor = off
    return round(total / 60000, 3)


def measure(records, own, now, eligible, held):
    try:
        held = [(on, off) for on, off in held]
    except (TypeError, ValueError):
        raise ValueError('malformed held interval') from None
    if any(type(on) is not int or type(off) is not int or on > off for on, off in held):
        raise ValueError('malformed held interval')
    held.sort()

    records = _unique(records)
    intents = [r for r in records if r['kind'] == 'intent']
    delay = {'eligible': 0, 'measured': 0, 'open': 0, 'unknown': 0, 'minutes': []}
    pending = []
    for intent in intents:
        events = [r for r in records if _belongs(r, intent)]
        states = {(r['kind'], r.get('state')) for r in events}
        ack = min((r for r in events if _acked(r, intent, own)), key=lambda r: r['created_at'], default=None)
        settled = ack is not None or bool(states & {('completion', 'completed'), ('completion', 'superseded')})
        if states & UNCERTAIN or not settled:
            pending.append(intent)
        if intent['destination'] != 'reviewer' or intent['prior_verdict'] is None:
            continue
        delay['eligible'] += 1
        if intent['head'] not in eligible:
            delay['unknown'] += 1
        elif ack is not None:
            delay['measured'] += 1
            delay['minutes'].append(_ungated(eligible[intent['head']], ack['created_at'], held))
        else:
            delay['open'] += 1
    oldest = max((_ungated(i['created_at'], now, held) for i in pending), default=None)
    return {'recheck_delay': delay, 'pending': {'count': len(pending), 'oldest_minutes': oldest}}


def due(settings, bench, intents, decisions, context):
    loaded = limits.read(settings)
    if (bench.get('schema') != 'closedwiz.journey.stage-bench.v1' or bench.get('authority') != 'none'
            or bench.get('settings') != loaded):
        raise ValueError('stage bench does not match the loaded settings')
    intents = [r for r in _unique(intents) if r['kind'] == 'intent']
    rows = []
    for wait in bench['waits']:
        if wait['stage'] not in STAGES or wait['result'] != 'missed':
            continue
        if wait['stage'] == 'fix_after_changes':
            pr, head, origin = re.fullmatch(r'fix_after_changes:p(\d+):([0-9a-f]{40}):c(\d+)', wait['key']).groups()
            route, what, subject = 'builder', 'findings', {'kind': 'pull_request', 'number': int(pr)}
            tickets = wait['tickets']
        else:
            ticket, origin = re.fullmatch(r'builder_question_answer:t(\d+):c(\d+)', wait['key']).groups()
            route, what, head = 'orchestrator', 'answer', None
            subject, tickets = {'kind': 'issue', 'number': int(ticket)}, [int(ticket)]
        match = [i for i in intents
                 if i['action'] == 'delivery' and i['destination'] == route and i['ticket'] in tickets
                 and (i['repository'], i['spec'], i['approval']) == (context['repository'], context['spec'],
                                                                     context['approval'])
                 and i['subject'] == subject and i['head'] == head and i['prior_verdict'] == int(origin)
                 and i['assignment'] == context['owners'].get(f'{route}:{i["ticket"]}')]
        keys = sorted({i['operation_key'] for i in match})
        gap = None if len(keys) == 1 else (f'no durable {what} item: record one before routing' if not keys
                                            else f'ambiguous {what} items')
        rows.append({'key': wait['key'], 'stage': wait['stage'], 'route': route,
                     'operation_key': keys[0] if len(keys) == 1 else None,
                     'done': f'evidenced end {wait["end"]}' if wait['end'] else None,
                     'exception': 'needs a new decision from Jake' if int(origin) in decisions else None,
                     'gap': gap, 'wait_minutes': wait['wait_minutes'], 'limit_minutes': wait['limit_minutes']})
    return rows
