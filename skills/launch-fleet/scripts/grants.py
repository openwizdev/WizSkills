import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('ops_protocol', ROOT / 'skills/launch-fleet/test/ops-protocol/protocol.py')
protocol = importlib.util.module_from_spec(spec)
spec.loader.exec_module(protocol)
BINDING = ('repository', 'spec', 'ticket', 'approval')
TERMINAL = {'revoked', 'completed', 'replaced', 'refused', 'uncertain'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def load_json(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, 'duplicate persisted key')
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=unique)


def digest(value):
    return hashlib.sha256(wire(value).encode()).hexdigest()


def material(sources):
    require(type(sources) is dict and set(sources) == {'intent', 'evidence', 'ownership', 'purposes', 'rule'},
            'incomplete material sources')
    return {f'{"purpose" if k == "purposes" else k}_digest': digest(v) for k, v in sources.items()}


def evidence_matches(record, sources):
    require(type(sources['evidence']) is list and sources['evidence'], 'unread source evidence')
    entries = []
    for source in sources['evidence']:
        require(type(source) is dict and set(source) == {'evidence_class', 'source', 'value'}, 'incomplete evidence source')
        entries.append(dict(evidence_class=source['evidence_class'], source=source['source'], digest=digest(source['value'])))
    require(record['evidence'] == entries, 'evidence source content or identity changed')


def checked(record, kind=None):
    value = protocol.read_record(wire(record))
    require(kind is None or value['kind'] == kind, 'wrong record kind')
    return value


def bound(left, right):
    return all(left[k] == right[k] for k in BINDING)


def canonical(path):
    return (type(path) is str and re.fullmatch(r'[A-Za-z0-9_./-]+', path) is not None
            and all(p not in ('', '.', '..') for p in path.split('/')))


def current_diff(paths, snapshot, assessment, changes):
    require(type(changes) is list and changes, 'missing complete diff')
    require(type(snapshot['head']) is str and re.fullmatch(r'[0-9a-f]{40}', snapshot['head']) is not None,
            'identified implementation commit required')
    require(assessment['head'] == snapshot['head'] and assessment['diff_digest'] == digest(changes),
            'fresh exact-head assessment required')
    require(type(assessment['findings']) is list and not assessment['findings'], 'scope assessment refused')
    require(not snapshot['paused'] and not snapshot['revoked'] and not snapshot['holds'] and not snapshot['gates'],
            'an independent gate remains')
    allowed = {p['path']: p for p in paths}
    require(len(allowed) == len(paths), 'ambiguous effective paths')
    seen = set()
    for change in changes:
        require(type(change) is dict and set(change) == {
            'path', 'previous_path', 'resolved_path', 'owner_ticket', 'shared_section', 'patch'}, 'incomplete change')
        require(type(change['patch']) is str and change['patch'], 'unread actual change')
        require(change['path'] not in seen, 'duplicate diff path')
        seen.add(change['path'])
        require(canonical(change['path']) and change['resolved_path'] == change['path'], 'path alias or symlink')
        for path in [change['path']] + ([] if change['previous_path'] is None else [change['previous_path']]):
            require(canonical(path) and path in allowed, 'uncovered rename or change')
            entry = allowed[path]
            require(type(change['owner_ticket']) is int and entry['owner_ticket'] == change['owner_ticket'] == snapshot['ticket']
                    and entry['shared_section'] == change['shared_section'], 'ownership or shared section changed')
    return True


def check_envelope(envelope, snapshot, sources, assessment, changes):
    result = dict(purpose_current=False, diff_current=False, next='end', effects=[])
    try:
        checked(envelope, 'envelope')
        checked(snapshot, 'snapshot')
        require(snapshot['complete'] and bound(envelope, snapshot), 'stale or unread approval')
        require(envelope['subject'] == {'kind': 'issue', 'number': snapshot['ticket']} and
                envelope['operation_key'] == '0' * 64, 'wrong envelope subject or operation')
        require(envelope['rule']['name'] == 'approved-envelope' and envelope['rule'] == snapshot['rule']
                and envelope['rule']['revision'] == envelope['material']['rule_digest'], 'wrong operative rule')
        evidence_matches(envelope, sources)
        paths = envelope['paths'] + envelope['supporting']
        require(envelope['material'] == snapshot['material'] == material(sources)
                and sources['purposes'] == paths, 'changed envelope material')
        require(type(sources['ownership']) is list and sorted(sources['ownership'], key=wire) ==
                sorted([{k: p[k] for k in ('path', 'owner_ticket', 'shared_section')} for p in paths], key=wire),
                'changed envelope ownership')
        require(type(assessment) is dict and set(assessment) == {
            'role', 'operation_key', 'approval', 'material', 'head', 'diff_digest', 'paths', 'findings'}, 'incomplete assessment')
        require(assessment['role'] in {'builder', 'reviewer'} and assessment['operation_key'] == '0' * 64
                and assessment['approval'] == envelope['approval'] and assessment['material'] == envelope['material']
                and assessment['paths'] == paths, 'unbound supporting-edit assessment')
        result['purpose_current'] = True
        result['diff_current'] = current_diff(paths, snapshot, assessment, changes)
    except (ValueError, KeyError, TypeError):
        pass
    return result


def check_grant(grant, envelope, intent, snapshot, sources, assessment, changes, history):
    result = dict(purpose_current=False, diff_current=False, next='end', effects=[])
    try:
        for record, kind in [(grant, 'grant'), (envelope, 'envelope'), (intent, 'intent'), (snapshot, 'snapshot')]:
            checked(record, kind)
        require(protocol.grant_current(grant, snapshot), 'stale grant material or approval')
        require(snapshot['intents'].count(intent) == 1, 'missing or ambiguous durable intent read-back')
        evidence_matches(grant, sources)
        require(bound(envelope, snapshot) and bound(intent, snapshot), 'wrong approval or subject')
        require(envelope['subject'] == grant['subject'] == intent['subject'] == {'kind': 'issue', 'number': grant['ticket']},
                'grant must be recorded on its work ticket')
        require(envelope['rule']['name'] == 'approved-envelope' and envelope['operation_key'] == '0' * 64,
                'wrong envelope rule')
        require(grant['envelope_id'] == envelope['id'], 'wrong envelope')
        require(intent['action'] == 'grant' and intent['destination'] == 'ops'
                and intent['operation_key'] == grant['operation_key'] and intent['created_at'] <= grant['created_at'],
                'wrong grant operation')
        require(grant['material'] == material(sources) and grant['paths'] == sources['purposes'], 'changed source material')
        require(type(assessment) is dict and set(assessment) == {
            'role', 'operation_key', 'approval', 'material', 'head', 'diff_digest', 'paths', 'findings'}, 'incomplete assessment')
        require(assessment['role'] == 'ops' and assessment['operation_key'] == grant['operation_key']
                and assessment['approval'] == grant['approval'] and assessment['material'] == grant['material']
                and assessment['paths'] == grant['paths'], 'independent ops assessment required')
        require(type(sources['ownership']) is list, 'unread owners')
        owners = {p['path']: p for p in sources['ownership']}
        require(len(owners) == len(sources['ownership']), 'ambiguous ownership')
        for path in grant['paths']:
            require(owners.get(path['path']) == {k: path[k] for k in ('path', 'owner_ticket', 'shared_section')}
                    and path['owner_ticket'] == snapshot['ticket'], 'another owner')
        require(type(history) is list, 'unread history')
        ids = {grant['id']}
        for event in history:
            checked(event, 'grant')
            require(event['id'] not in ids, 'duplicate immutable record identity')
            ids.add(event['id'])
            if event['grant_id'] == grant['grant_id']:
                require(bound(event, grant) and event['operation_key'] == grant['operation_key'], 'conflicting grant identity')
                require(event['status'] not in TERMINAL and event['supersedes'] is None, 'ended or replaced grant')
                require(event == grant, 'contradictory grant decision')
        result['purpose_current'] = True
        result['diff_current'] = current_diff(envelope['paths'] + envelope['supporting'] + grant['paths'],
                                               snapshot, assessment, changes)
    except (ValueError, KeyError, TypeError):
        pass
    return result


LOGIN = r'`[A-Za-z0-9](?:-?[A-Za-z0-9])*(?:\[bot\])?`'
CELL = re.compile(rf'\s*{LOGIN}(?:\s*,\s*{LOGIN})*\s*')


def record_authors(fleet_md):
    section, rows = None, []
    for line in fleet_md.splitlines():
        if line.startswith('## '):
            section = line
        elif section == '## GitHub identity' and re.match(r'\| *Record authors *\|', line):
            rows.append(line)
    cells = rows[0].split('|') if len(rows) == 1 else []
    require(len(cells) == 4 and not cells[3].strip() and CELL.fullmatch(cells[2]),
            'docs/agents/fleet.md names no record authors')
    logins = re.findall(r'`([^`]*)`', cells[2])
    return frozenset(x.lower() for x in logins)


def authored(author, authors):
    return type(author) is str and author.lower() in authors


def read_sources(rows, repository, subject=None, authors=frozenset()):
    require(type(rows) is list, 'partial comment page')
    result, comments, ids, sequences = [], set(), set(), set()
    for row in rows:
        require(type(row) is dict
                and set(row) == {'id', 'created_at', 'updated_at', 'repository', 'subject', 'author', 'body'},
                'incomplete comment metadata')
        require(type(row['id']) is int and row['id'] > 0 and row['id'] not in comments, 'duplicate source comment')
        comments.add(row['id'])
        require(row['repository'] == repository and (subject is None or row['subject'] == dict(zip(('kind', 'number'), subject))),
                'wrong source repository or container')
        require(type(row['body']) is str, 'unread comment')
        if 'openwiz.ops-dispatch.' not in row['body'] or not authored(row['author'], authors):
            continue
        record = protocol.read_comment(row['body'], (repository, row['subject']['kind'], row['subject']['number']))
        require(type(row['created_at']) is int and type(row['updated_at']) is int
                and row['created_at'] == row['updated_at'] == record['created_at'], 'edited or misdated immutable record')
        require(record['id'] not in ids, 'duplicate immutable identity')
        ids.add(record['id'])
        if record['kind'] == 'intent':
            sequence = (record['spec'], record['ticket'], wire(record['approval']), record['sequence'])
            require(sequence not in sequences, 'duplicate ticket/revision sequence')
            sequences.add(sequence)
        result.append((row, record))
    return sorted(result, key=lambda pair: (pair[0]['created_at'], pair[0]['id']))


def collect(fetch_page, repository, subject, page_budget=100, authors=frozenset()):
    require(type(page_budget) is int and page_budget > 0, 'invalid page budget')
    rows = []
    for page in range(1, page_budget + 1):
        batch, more = fetch_page(page)
        require(type(batch) is list and type(more) is bool, 'unread pagination')
        rows.extend(batch)
        if not more:
            read_sources(rows, repository, subject, authors)
            return rows
    raise ValueError('page budget exhausted; retain cursor and reconcile')


def position(cursor):
    require(type(cursor) is dict and set(cursor) == {'created_at', 'comment'}
            and all(type(x) is int and 0 <= x <= 9007199254740991 for x in cursor.values()), 'invalid cursor')
    return cursor['created_at'], cursor['comment']


def audit(template, records, assessments, authors=frozenset()):
    checked(template, 'audit')
    start, end = position(template['start']), position(template['end'])
    require(start <= end and template['rule']['name'] == 'audit', 'backwards cursor or wrong audit rule')
    parsed = read_sources(records, template['repository'], authors=authors)
    require(type(assessments) is dict, 'unread assessments')
    intents, decisions, entries = {}, set(), []
    complete = template['complete']
    for row, record in parsed:
        if record['kind'] == 'intent' and record['action'] == 'grant':
            key = record['operation_key']
            require(key not in intents, 'conflicting intent identity')
            intents[key] = record
    uncertain = {record['operation_key'] for row, record in parsed
                 if (row['created_at'], row['id']) <= end and
                 ((record['kind'] == 'transport' and record['state'] in {'accepted', 'uncertain'})
                  or (record['kind'] == 'completion' and record['state'] in {'completed', 'uncertain', 'reconciled_not_executed'}))}
    for row, record in parsed:
        if record['kind'] not in {'grant', 'transport', 'completion'} or not start < (row['created_at'], row['id']) <= end:
            continue
        key = record['operation_key']
        intent = intents.get(key)
        if record['kind'] != 'grant' and intent is None:
            continue
        require(intent is not None and bound(record, intent) and record['subject'] == intent['subject']
                and intent['destination'] == 'ops' and intent['created_at'] <= record['created_at'], 'unbound grant decision')
        require(record.get('intent_id', intent['id']) == intent['id'], 'wrong event intent')
        decisions.add(key)
        decision = assessments.get(row['id'])
        if decision is None:
            complete = False
            decision = dict(valid=None, final_diff_digest=None)
        require(type(decision) is dict and set(decision) == {'valid', 'final_diff_digest'}
                and (decision['valid'] is None or type(decision['valid']) is bool), 'invalid audit assessment')
        status = record.get('status')
        if record['kind'] != 'grant':
            state = record['state']
            status = ('uncertain' if key in uncertain else
                      'refused' if state in {'refused', 'disabled', 'not_attempted'} else
                      'replaced' if state == 'superseded' else 'uncertain')
        remediation = ('escalate' if decision['valid'] is None or status == 'uncertain' else
                       'revoke_and_hold' if status == 'granted' and not decision['valid'] else 'none')
        entries.append(dict(operation_key=key, decision=status, grant_id=record.get('grant_id'),
                            final_diff_digest=decision['final_diff_digest'], remediation=remediation))
    for row, intent in parsed:
        if (intent['kind'] == 'intent' and intent['action'] == 'grant' and intent['operation_key'] not in decisions
                and start < (row['created_at'], row['id']) <= end):
            entries.append(dict(operation_key=intent['operation_key'], decision='uncertain', grant_id=None,
                                final_diff_digest=None, remediation='escalate'))
    return checked(dict(template, entries=entries, complete=complete), 'audit')


def fsync_directory(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def durable_file(path, value, immutable=False):
    fd, name = tempfile.mkstemp(prefix='.audit-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(wire(value) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        if immutable:
            try:
                os.link(name, path)
            except FileExistsError:
                require(path.read_text() == wire(value) + '\n', 'audit identity has different content')
        else:
            os.replace(name, path)
        fsync_directory(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save_audit(directory, report):
    checked(report, 'audit')
    require(report['complete'], 'incomplete audit retains old cursor')
    protocol.audit_cursor(report)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    reports = directory / 'reports'
    reports.mkdir(exist_ok=True, mode=0o700)
    with (directory / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        cursor_path = directory / 'cursor.json'
        if not cursor_path.exists():
            require(position(report['start']) == (0, 0), 'missing cursor; reconcile history before bootstrap')
        cursor = load_json(cursor_path.read_text()) if cursor_path.exists() else report['start']
        require(position(cursor) in (position(report['start']), position(report['end'])), 'audit cursor changed')
        target = reports / f'{report["id"]}.json'
        durable_file(target, report, immutable=True)
        require(checked(load_json(target.read_text()), 'audit') == report, 'audit read-back differs')
        if cursor != report['end']:
            durable_file(cursor_path, report['end'])
