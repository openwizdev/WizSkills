"""Loading and checking cases (contract.md, sections 1 and 8)."""
import hashlib
import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
CATEGORIES = {'incident', 'workflow', 'approval', 'privacy', 'failure'}
CASE_KEYS = {'schema', 'id', 'skills', 'category', 'brief', 'world', 'expect', 'controls',
             'ticket', 'head'}
EXPECT_KEYS = {'actions', 'allow', 'forbid', 'end'}
MATCH_KEYS = {'read', 'write', 'run', 'args', 'flags', 'absent', 'record', 'contains', 'any', 'codes', 'ok', 'positional', 'endpoint', 'json_fields'}
RECORDS = {'decisions.v1', 'verdict', 'launch-fleet', 'handback', 'text'}
REASONS = {'incomplete', 'escape', 'forbidden', 'unlisted-write', 'missing-action', 'bad-record', 'unjudged', 'bad-final'}

# Synthetic-only scan: patterns no case input may hold.
PRIVATE = [
    (re.compile(r'https?://(?!127\.0\.0\.1[:/]|localhost[:/])'), 'a URL'),
    (re.compile(r'\bthr_(?!synth)[a-z0-9]{6,}'), 'a real-looking thread id'),
    (re.compile(r'\bcr_child_'), 'a child thread id'),
    (re.compile(r'issuecomment-\d'), 'a comment link'),
    (re.compile(r'(?<![\w.])#(?:[1-9]\d{0,2}|[1-3]\d{3})\b'), 'an issue number below 4000'),
    (re.compile(r'\b(?:sk-ant-|ghp_|gho_|github_pat_)'), 'a credential'),
    (re.compile(r'[\w.+-]+@[\w-]+\.[\w.]+'), 'an email address'),
    (re.compile(r'(?i)\bjake\b|jparker|closedwiz'), 'a real person or project name'),
]


def load_all(folder=HERE / 'cases'):
    out = []
    for p in sorted(Path(folder).glob('*.json')):
        out.append(json.loads(p.read_text()))
    return out


def cases_hash(folder=HERE / 'cases'):
    h = hashlib.sha256()
    for p in sorted(Path(folder).glob('*.json')):
        h.update(p.name.encode() + b'\0' + p.read_bytes() + b'\0')
    return h.hexdigest()


def _has_write(m):
    """Does the matcher require more than a read (a write, a script or a local change)?"""
    return 'write' in m or 'run' in m or any(_has_write(x) for x in m.get('any', []))


def _matcher_problems(m, where):
    errs = []
    if not isinstance(m, dict) or set(m) - MATCH_KEYS:
        return [f'{where}: bad matcher keys']
    if 'any' in m:
        if set(m) != {'any'} or not m['any']:
            return [f'{where}: `any` stands alone and is non-empty']
        return [e for j, x in enumerate(m['any']) for e in _matcher_problems(x, f'{where}.any[{j}]')]
    if sum(k in m for k in ('read', 'write', 'run')) != 1:
        errs.append(f'{where}: needs exactly one of read, write, run')
    if 'record' in m and m['record'] not in RECORDS:
        errs.append(f'{where}: unknown record {m["record"]}')
    if 'record' in m and 'write' not in m:
        errs.append(f'{where}: a record needs a write')
    if 'codes' in m and not (isinstance(m['codes'], list) and all(isinstance(x, int) for x in m['codes'])):
        errs.append(f'{where}: codes are exit codes')
    return errs


def _strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for k, v in x.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from _strings(v)


def privacy_problems(case):
    # Explicit O3 input only: never infer a private checkout or continue without coverage.
    path = os.environ.get('OPENWIZ_PRIVACY_LITERALS')
    try:
        if not path:
            raise ValueError
        literals = Path(path).read_text(encoding='utf-8').splitlines()
        if not literals or any(not value.strip() for value in literals):
            raise ValueError
    except (OSError, ValueError):
        return ['case privacy: private literals input is missing, unreadable or empty']
    private_literals = [re.compile(re.escape(value), re.I) for value in literals]
    errs = []
    inputs = {k: case[k] for k in ('brief', 'world', 'controls', 'expect') if k in case}
    for s in _strings(inputs):
        if any(rx.search(s) for rx in private_literals):
            errs.append('case privacy: a private literal')
            continue  # Generic identifier diagnostics must not echo a supplied literal.
        for rx, what in PRIVATE:
            if rx.search(s):
                errs.append(f"{case.get('id')}: {what}: {rx.search(s).group(0)!r}")
    return errs


def problems(case, skills, path_name=None):
    """Structural, coverage and privacy problems with one case."""
    cid = case.get('id', '?')
    errs = []
    if set(case) - CASE_KEYS or not {'schema', 'id', 'skills', 'category', 'brief', 'world', 'expect', 'controls'} <= set(case):
        errs.append(f'{cid}: keys {sorted(case)}')
        return errs
    if case['schema'] != 'openwiz.skills-eval.case.v1':
        errs.append(f'{cid}: schema')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', cid):
        errs.append(f'{cid}: id')
    if path_name and path_name != f'{cid}.json':
        errs.append(f'{cid}: file name {path_name}')
    if case['category'] not in CATEGORIES:
        errs.append(f'{cid}: category')
    if (case['category'] == 'incident') != bool(re.match(r'i\d+-', cid)):
        errs.append(f'{cid}: incident ids start i<k>- and only incidents do')
    if not case['skills'] or any(s not in skills for s in case['skills']):
        errs.append(f'{cid}: skills {case["skills"]}')
    if not isinstance(case['brief'], str) or not case['brief'].strip():
        errs.append(f'{cid}: brief')
    exp = case['expect']
    if set(exp) - {'final'} != EXPECT_KEYS:
        errs.append(f'{cid}: expect keys')
        return errs
    if 'final' in exp and not (isinstance(exp['final'], str) and exp['final'].strip()):
        errs.append(f'{cid}: expect.final must be a rule for the judge')
    if not any(_has_write(m) for m in exp['actions']) and 'final' not in exp:
        errs.append(f'{cid}: a case that requires only reads decides in its reply, so it needs expect.final')
    if exp['end'] != 'end_turn':
        errs.append(f'{cid}: end')
    for k in ('actions', 'allow', 'forbid'):
        for j, m in enumerate(exp[k]):
            errs += _matcher_problems(m, f'{cid}.{k}[{j}]')
    if any('record' in m for m in exp['actions']) and not case.get('ticket'):
        errs.append(f'{cid}: a record check needs `ticket`')
    c = case['controls']
    if set(c) != {'pass', 'fail'} or not c['pass'] or not c['fail']:
        errs.append(f'{cid}: controls need at least one pass and one fail')
        return errs
    for kind in ('pass', 'fail'):
        for j, ctl in enumerate(c[kind]):
            want = {'why', 'events'} | ({'reason'} if kind == 'fail' else set())
            if set(ctl) - {'stop', 'final', 'judgment'} != want:
                errs.append(f'{cid}.controls.{kind}[{j}]: keys')
            elif kind == 'fail' and ctl['reason'] not in REASONS:
                errs.append(f'{cid}.controls.fail[{j}]: reason')
    return errs + privacy_problems(case)


def control_transcript(case, ctl):
    """Expand a control's compact events into a transcript."""
    events = []
    for k, e in enumerate(ctl['events'], 1):
        kind, cmd = e[0], e[1]
        events.append({'seq': k, 'kind': kind, 'argv': cmd.split() if isinstance(cmd, str) else cmd,
                       'body': e[2] if len(e) > 2 else None, 'code': e[3] if len(e) > 3 else 0,
                       'error': e[4] if len(e) > 4 else kind in ('refused', 'escape')})
    return {'case': case['id'], 'repeat': 0, 'stop': ctl.get('stop', 'end_turn'),
            'final': ctl.get('final', 'Done.'), 'events': events, 'usage': {}, 'judgment': ctl.get('judgment')}
