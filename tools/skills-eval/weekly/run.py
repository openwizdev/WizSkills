"""Durable weekly collection/checkpoint and injected fake-eval core (#2236).

The core has no CLI, scheduler, real tool implementation or eval runner.
#1363's weekly process, real GitHub reader, loop definition and CLI follow it,
below the marked line; they start, merge and pay for nothing.
"""
import copy
import fcntl
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(HERE.parent))
import collect as C
import eval as E1

STATE_KEYS = {'schema', 'successful_week', 'source_checkpoints', 'case_files',
              'incidents', 'provenance', 'pending', 'last_evidence'}


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def loads(text):
    return json.loads(text, object_pairs_hook=strict_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def write_json(path, value):
    """One atomic durable state file contains preparation, publication and receipts."""
    E1.write_json(path, value)


def files_hash(files):
    """E1 cases_hash's sorted filenames and exact UTF-8 bytes, including NULs."""
    h = hashlib.sha256()
    for name, text in sorted(files.items()):
        h.update(name.encode() + b'\0' + text.encode() + b'\0')
    return h.hexdigest()


def case_objects(files, skills):
    result = {}
    for name, text in files.items():
        case = loads(text)
        C.validate_case(case, skills)
        if name != case['id'] + '.json':
            raise ValueError('case filename mismatch')
        result[case['id']] = case
    return result


def provenance_valid(prov, known):
    if (not isinstance(prov, dict) or set(prov) - {'schema', 'cases', 'checkpoints', 'note', 'not_applicable'} or
            not {'schema', 'cases', 'checkpoints'} <= set(prov) or
            prov['schema'] != 'openwiz.skills-eval.provenance.v1' or
            not isinstance(prov['cases'], dict) or set(prov['cases']) != set(known) or
            not isinstance(prov['checkpoints'], list)):
        raise ValueError('incomplete provenance')
    for cid, source in prov['cases'].items():
        if not isinstance(source, dict) or set(source) - {'links', 'rule', 'note'}:
            raise ValueError('invalid provenance source')
        if known[cid]['category'] == 'incident':
            links = source.get('links')
            if (not isinstance(links, list) or not links or any(
                    not isinstance(link, str) or not link.startswith('https://github.com/') for link in links) or
                    len(set(links)) != len(links)):
                raise ValueError('invalid incident links')
        elif not isinstance(source.get('rule'), str) or not source['rule'].strip():
            raise ValueError('missing rule provenance')


def score_valid(score, cases_hash, ids, settings, mode='fake'):
    """Injected E1 scores must cover each case and repeat, without a skipped row."""
    required = {'schema', 'settings_hash', 'cases_hash', 'code_hash', 'schema_hash',
                'revision', 'suite_pass', 'runs', 'passed', 'cost_usd', 'rows'}
    if not isinstance(score, dict) or set(score) != required:
        raise ValueError('invalid fake score')
    if score['schema'] != 'openwiz.skills-eval.score.v1' or score['cases_hash'] != cases_hash:
        raise ValueError('changed cases: take a fresh baseline')
    for key in ('settings_hash', 'cases_hash', 'code_hash', 'schema_hash'):
        if not isinstance(score[key], str) or not re.fullmatch('[a-f0-9]{64}', score[key]):
            raise ValueError('invalid score hash')
    if score['settings_hash'] != E1.sha(settings):
        raise ValueError('settings hash mismatch')
    rev = score['revision']
    if not isinstance(rev, dict) or set(rev) != {'commit', 'tree'} or any(
            not isinstance(v, str) or not re.fullmatch('[a-f0-9]{40}', v) for v in rev.values()):
        raise ValueError('invalid score revision')
    rows = score['rows']
    if not isinstance(rows, list) or not rows or type(score['runs']) is not int or score['runs'] != len(rows):
        raise ValueError('missing case/repeat')
    pairs = []
    for row in rows:
        if (not isinstance(row, dict) or set(row) - {'case', 'repeat', 'pass', 'reasons', 'details', 'cost_usd', 'stop'} or
                not {'case', 'repeat', 'pass', 'reasons', 'details'} <= set(row) or row.get('case') not in ids or
                type(row.get('repeat')) is not int or row['repeat'] < 1 or
                type(row.get('pass')) is not bool or not isinstance(row.get('reasons'), list) or
                not isinstance(row['details'], list) or any(not isinstance(v, str) for v in row['details']) or
                any(reason not in E1.S.REASONS for reason in row['reasons']) or
                not cost_ok(row.get('cost_usd', 0), mode)):
            raise ValueError('invalid case/repeat')
        pairs.append((row['case'], row['repeat']))
        if row['pass'] and (row.get('stop') != 'end_turn' or row['reasons']):
            raise ValueError('incomplete row cannot pass')
    repeats = settings['repeats']
    if len(set(pairs)) != len(pairs) or set(pairs) != {
            (cid, rep) for cid in ids for rep in range(1, repeats + 1)}:
        raise ValueError('missing or duplicate case/repeat')
    passed = sum(row['pass'] for row in rows)
    if (type(score['passed']) is not int or score['passed'] != passed or
            type(score['suite_pass']) is not bool or score['suite_pass'] != (passed == len(rows))):
        raise ValueError('inconsistent fake score')
    # Fixture evidence can never be presented as paid measurement (J29: measured
    # evidence keeps its real finite, non-negative cost and its own label).
    if not cost_ok(score['cost_usd'], mode):
        raise ValueError('only zero-cost fake or finite non-negative measured costs are accepted')


CLASSES = {'fake': 'fixture test', 'measured': 'measured run'}


def cost_ok(cost, mode):
    return type(cost) in (int, float) and cost == cost and cost not in (float('inf'), float('-inf')) and (
        cost == 0 if mode == 'fake' else cost >= 0)


def evidence_valid(evidence, cases_hash, ids):
    if not isinstance(evidence, dict) or set(evidence) != {
            'mode', 'settings', 'baseline', 'result', 'results_set', 'token_report'} or evidence['mode'] not in CLASSES:
        raise ValueError('only explicitly injected fake or measured outcomes are accepted')
    settings = evidence['settings']
    if (not isinstance(settings, dict) or type(settings.get('repeats')) is not int or
            settings['repeats'] < 1):
        raise ValueError('missing frozen repetition count')
    for key in ('results_set', 'token_report'):
        if not isinstance(evidence[key], str) or not evidence[key].strip():
            raise ValueError('missing evidence reference')
    for key in ('baseline', 'result'):
        score_valid(evidence[key], cases_hash, ids, settings, evidence['mode'])
    E1.compare(evidence['baseline'], evidence['result'])
    if not evidence['result']['suite_pass']:
        raise ValueError('fake eval failed; successful checkpoint retained')


def reply(status, week, *, cases_hash=None, case_ids=None, gaps=None, evidence_class='fixture test'):
    return {'status': status, 'week': week, 'cases_hash': cases_hash,
            'case_ids': case_ids or [], 'gaps': gaps or [], 'saving': None,
            'evidence_class': evidence_class}


def load_state(path):
    if not path.exists():
        return {'schema': 'openwiz.skills-eval.weekly-state.v1', 'successful_week': None,
            'source_checkpoints': {}, 'case_files': {}, 'incidents': {},
            'provenance': {'schema': 'openwiz.skills-eval.provenance.v1', 'cases': {}, 'checkpoints': []},
            'pending': None, 'last_evidence': None}
    try:
        state = loads(path.read_text())
    except OSError:
        raise ValueError('unreadable weekly state') from None
    if not isinstance(state, dict) or set(state) != STATE_KEYS or state['schema'] != 'openwiz.skills-eval.weekly-state.v1':
        raise ValueError('invalid weekly state')
    return state


def validate_state(state, skills):
    """A saved success is a receipt, never authority supplied by one status word."""
    known = case_objects(state['case_files'], skills)
    prov = state['provenance']
    provenance_valid(prov, known)
    if not isinstance(state['incidents'], dict) or any(
            not re.fullmatch('[a-z0-9][a-z0-9-]*', k) or v not in known
            for k, v in state['incidents'].items()):
        raise ValueError('invalid incident index')
    weeks = []
    for cp in prov['checkpoints']:
        if not isinstance(cp, dict) or set(cp) != {'week', 'case_ids', 'cases_hash', 'results_set', 'token_report'}:
            raise ValueError('invalid checkpoint')
        C.week_start(cp['week'])
        if (not isinstance(cp['case_ids'], list) or len(set(cp['case_ids'])) != len(cp['case_ids']) or
                any(cid not in known for cid in cp['case_ids']) or
                not isinstance(cp['cases_hash'], str) or not re.fullmatch('[a-f0-9]{64}', cp['cases_hash']) or
                any(not isinstance(cp[k], str) or not cp[k].strip() for k in ('results_set', 'token_report'))):
            raise ValueError('invalid checkpoint')
        weeks.append(cp['week'])
    if weeks != sorted(set(weeks)) or state['successful_week'] != (weeks[-1] if weeks else None):
        raise ValueError('missing success checkpoint')
    if weeks:
        cp = prov['checkpoints'][-1]
        if cp['cases_hash'] != files_hash(state['case_files']):
            raise ValueError('saved case hash mismatch')
        evidence_valid(state['last_evidence'], cp['cases_hash'], set(known))
        if any(cp[k] != state['last_evidence'][k] for k in ('results_set', 'token_report')):
            raise ValueError('missing evidence reference')
        sources = state['source_checkpoints']
        if not isinstance(sources, dict) or set(sources) != set(C.SOURCES):
            raise ValueError('missing source checkpoint')
        for source in sources.values():
            if (not isinstance(source, dict) or set(source) != {'week', 'records'} or source['week'] != weeks[-1] or
                    not isinstance(source['records'], dict) or any(
                        not re.fullmatch('[1-9][0-9]*', k) or not isinstance(v, str) or
                        not re.fullmatch('[a-f0-9]{64}', v) for k, v in source['records'].items())):
                raise ValueError('invalid source checkpoint')
    elif known or state['source_checkpoints'] or state['last_evidence'] is not None:
        raise ValueError('uncommitted success state')
    pending = state['pending']
    if pending is not None:
        if not isinstance(pending, dict) or set(pending) != {
                'week', 'base_hash', 'files', 'collection', 'case_ids', 'provenance', 'result'}:
            raise ValueError('invalid prepared transaction')
        C.week_start(pending['week'])
        if not isinstance(pending['base_hash'], str) or not re.fullmatch('[a-f0-9]{64}', pending['base_hash']):
            raise ValueError('invalid preparation hash')
        prepared_cases = case_objects(pending['files'], skills)
        provenance_valid(pending['provenance'], prepared_cases)
        collection = pending['collection']
        if (not isinstance(collection, dict) or set(collection) != {'cases', 'incidents', 'provenance', 'sources'} or
                not isinstance(collection['cases'], dict) or any(
                    prepared_cases.get(cid) != case for cid, case in collection['cases'].items()) or
                not isinstance(pending['case_ids'], list) or len(set(pending['case_ids'])) != len(pending['case_ids']) or
                any(cid not in prepared_cases for cid in pending['case_ids'])):
            raise ValueError('invalid prepared collection')
        if pending['result'] is not None:
            result = pending['result']
            if (not weeks or pending['week'] != weeks[-1] or not isinstance(result, dict) or
                    result.get('status') not in ('complete', 'unchanged') or
                    result != reply(result['status'], weeks[-1], cases_hash=files_hash(state['case_files']),
                                    case_ids=prov['checkpoints'][-1]['case_ids'],
                                    evidence_class=CLASSES[state['last_evidence']['mode']]) or
                    pending['files'] != state['case_files']):
                raise ValueError('invalid completion receipt')


def tick(directory, week, *, cases_dir=None, provenance=None, skills=None, read_page=None, synthesize=None, evidence=None):
    """Defaults do nothing. Explicit fake-tool injections enable only local state.

    Call once to prepare, then supply matching fake evidence. A crash resumes the
    same prepared collection; no source callback or candidate is repeated. The
    final atomic replacement commits files, provenance and success together.
    """
    if read_page is None or synthesize is None or cases_dir is None or skills is None:
        return reply('not run', week, gaps=['fake tools and case snapshot not supplied'])
    directory = Path(directory)
    try:
        C.week_start(week)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (directory / 'lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return reply('gap', week, gaps=['weekly state is locked'])
            return tick_locked(directory / 'state.json', week, Path(cases_dir), skills,
                               read_page, synthesize, evidence, provenance)
    except (ValueError, KeyError, TypeError, AttributeError):
        return reply('gap', week, gaps=['invalid collection, state or fake evidence; successful checkpoint retained'])


def tick_locked(path, week, cases_dir, skills, read_page, synthesize, evidence, provenance):
    state = load_state(path)
    validate_state(state, skills)
    if not cases_dir.is_dir():
        raise ValueError('missing case snapshot')
    try:
        base = {p.name: p.read_bytes().decode('utf-8') for p in sorted(cases_dir.glob('*.json'))}
    except OSError:
        raise ValueError('unreadable case snapshot') from None
    base_cases = case_objects(base, skills)
    if base_cases:
        provenance_valid(provenance, base_cases)
    base_hash = E1.sha({'cases_hash': files_hash(base), 'provenance': provenance})
    pending = state['pending']
    if pending is not None and pending['week'] == week:
        if pending['base_hash'] != base_hash:
            raise ValueError('case snapshot changed during the week')
        if pending['result'] is not None:
            return pending['result']
    else:
        if pending is not None and pending['result'] is None:
            raise ValueError('resume the prepared week first')
        if state['successful_week'] is not None and week <= state['successful_week']:
            raise ValueError('week already superseded')
        files = dict(state['case_files'], **base)
        known = case_objects(files, skills)
        try:
            collection = C.collect(week, read_page, synthesize, skills,
                                   known_cases=known, incidents=state['incidents'])
        except ValueError as err:
            return reply('gap', week, gaps=[str(err)])
        # The first snapshot is the seed suite; later snapshot additions belong
        # to that week's checkpoint just as collected candidates do.
        added = set(base_cases) - {name[:-5] for name in state['case_files']} if state['successful_week'] else set()
        for cid, case in collection['cases'].items():
            if cid not in known:
                files[cid + '.json'] = json.dumps(case, sort_keys=True, indent=1) + '\n'
                added.add(cid)
        prepared_provenance = copy.deepcopy(state['provenance'])
        if provenance is not None:
            provenance_valid(provenance, base_cases)
            for cid, source in provenance['cases'].items():
                previous_links = prepared_provenance['cases'].get(cid, {}).get('links', [])
                entry = copy.deepcopy(source)
                if 'links' in entry:
                    entry['links'] = list(dict.fromkeys(previous_links + entry['links']))
                prepared_provenance['cases'][cid] = entry
            for key in ('note', 'not_applicable'):
                if key in provenance:
                    prepared_provenance[key] = copy.deepcopy(provenance[key])
        for cid, source in collection['provenance'].items():
            links = prepared_provenance['cases'].setdefault(cid, {'links': []})['links']
            links.extend(link for link in source['links'] if link not in links)
        provenance_valid(prepared_provenance, case_objects(files, skills))
        pending = {'week': week, 'base_hash': base_hash, 'files': files,
                   'collection': collection, 'provenance': prepared_provenance,
                   'case_ids': sorted(added), 'result': None}
        # A crash after this write resumes without fetching or synthesizing twice.
        state['pending'] = pending
        write_json(path, state)
    cases_hash = files_hash(pending['files'])
    previous = state['provenance']['checkpoints']
    unchanged = not pending['case_ids'] and previous and previous[-1]['cases_hash'] == cases_hash
    if evidence is None and not unchanged:
        return reply('prepared', week, cases_hash=cases_hash, case_ids=pending['case_ids'],
                     gaps=['matching fake baseline/result and token-report reference required'])
    if evidence is not None:
        evidence_valid(evidence, cases_hash, set(case_objects(pending['files'], skills)))
        refs = {k: evidence[k] for k in ('results_set', 'token_report')}
        state['last_evidence'] = copy.deepcopy(evidence)
    else:
        refs = {k: previous[-1][k] for k in ('results_set', 'token_report')}
    result = reply('unchanged' if unchanged else 'complete', week, cases_hash=cases_hash,
                   case_ids=pending['case_ids'], evidence_class=CLASSES[state['last_evidence']['mode']])
    state['case_files'] = pending['files']
    state['incidents'] = pending['collection']['incidents']
    state['source_checkpoints'] = pending['collection']['sources']
    state['successful_week'] = week
    state['provenance'] = copy.deepcopy(pending['provenance'])
    state['provenance']['checkpoints'].append({'week': week, 'case_ids': pending['case_ids'],
                                              'cases_hash': cases_hash, **refs})
    pending['result'] = result
    validate_state(state, skills)
    write_json(path, state)
    return result


# ---------------------------------------------------------------------------
# #1363: the one weekly process around the core above. It binds owner stage
# references, routes eval -> fix -> cut work once, honours the credit-aware
# start rule and writes a sanitized report. It starts, merges and pays nothing:
# every effect is an injected callback. The CLI's tick queues each action in the
# durable ledger; `handoff` then posts it once as a marked GitHub comment, after
# reading the issue for an earlier one.

import os
import subprocess
import tempfile
import datetime as dt



def openwiz(rel):
    """A file of the OpenWiz checkout at the pinned commit, passed in as OPENWIZ_CHECKOUT (#1487)."""
    root = os.environ.get('OPENWIZ_CHECKOUT')
    path = Path(root) / rel if root else None
    if path is None or not path.is_file():
        print(f'OPENWIZ_CHECKOUT: {path} is missing' if root else
              f'OPENWIZ_CHECKOUT is not set: pass an OpenWiz checkout at the pinned commit (it reads {rel})',
              file=sys.stderr)
        raise SystemExit(2)
    return path


sys.path.insert(2, str(openwiz('tools/collector/experiment_contract.py').parent))
sys.dont_write_bytecode = True  # leave no cache in the war-room checkout
import experiment_contract as X

STAGE_NAMES = ('research', 'cf4', 'replay', 'live')
PREDECESSORS = {'replay': ('research', 'cf4'), 'live': ('research', 'cf4', 'replay')}
TERMINAL = ('pass', 'fail', 'stopped', 'inconclusive')
GATED = ('fix', 'cut')  # builder work; a stage-ready proposal only informs the orchestrator
LEDGER = 'openwiz.skills-eval.weekly-ledger.v1'
# deferred: waiting for the start gate. unresolved: outcome unknown, never resent.
# queued: kept in the ledger for the loop agent to hand off. routed: handed off.
STATUSES = ('deferred', 'unresolved', 'queued', 'routed')
OUTSTANDING = ('deferred', 'unresolved', 'queued')
RECEIPT = re.compile(r'[1-9][0-9]*')  # the GitHub comment id of a verified handoff
IDENTIFIERS = re.compile(r'thr_|prj_|https?://')


def shown(status):
    return 'unobserved' if status == 'not_run' else status


def summary_valid(summary):
    """An owner's import summary: EB5 stage shapes, sources apart from facts."""
    X.fields(summary, 'tag experiment_hash stages sources', 'experiment summary')
    X.require(isinstance(summary['tag'], str) and re.fullmatch(r'[a-z0-9][a-z0-9-]*', summary['tag']), 'invalid tag')
    X.hex_value(summary['experiment_hash'], 64, 'experiment hash')
    sources = summary['sources']
    X.require(isinstance(sources, dict) and all(
        re.fullmatch(r's[1-9][0-9]*', k) and isinstance(v, str) and v.startswith('https://github.com/')
        for k, v in sources.items()), 'invalid sources')
    X.fields(summary['stages'], ' '.join(STAGE_NAMES), 'stages')
    for stage in summary['stages'].values():
        X.fields(stage, 'status artifact_hash source at', 'stage')
        X.choice(stage['status'], ('not_run', 'partial') + TERMINAL, 'stage status')
        if stage['status'] == 'not_run':
            X.require(stage['artifact_hash'] is None and stage['source'] is None and stage['at'] is None,
                      'unrun stage has result')
        else:
            X.hex_value(stage['artifact_hash'], 64, 'stage artifact')
            X.source(stage['source'], sources)
            X.time(stage['at'])
    stages = summary['stages']
    for target, needs in PREDECESSORS.items():
        if stages[target]['status'] != 'not_run':
            X.require(all(stages[n]['status'] == 'pass' and X.time(stages[n]['at']) <= X.time(stages[target]['at'])
                          for n in needs), f'{target} recorded before its predecessors passed')


def bind_experiments(prior, summaries):
    """Retain every known experiment; a running one is frozen (EB5 transition rules)."""
    bound = copy.deepcopy(prior)
    for summary in summaries:
        summary_valid(summary)
        old = bound.get(summary['tag'])
        if old is not None:
            X.require(old['experiment_hash'] == summary['experiment_hash'],
                      'frozen experiment changed; a new candidate or case set is a new experiment tag')
            for name, stage in old['stages'].items():
                after = summary['stages'][name]
                X.require(stage['status'] not in TERMINAL or after == stage, 'completed stage evidence changed')
                X.require(stage['status'] == 'not_run' or after['status'] != 'not_run', 'stage evidence removed')
            X.require(all(summary['sources'].get(k) == v for k, v in old['sources'].items()), 'source evidence changed')
        bound[summary['tag']] = {k: copy.deepcopy(summary[k]) for k in ('experiment_hash', 'stages', 'sources')}
    return bound


def stage_plan(experiments):
    """Proposals for stages whose predecessors all passed; everything else is blocked."""
    proposals, blocked = [], []
    for tag, e in sorted(experiments.items()):
        for target, needs in PREDECESSORS.items():
            if e['stages'][target]['status'] != 'not_run':
                continue
            missing = [n for n in needs if e['stages'][n]['status'] != 'pass']
            if missing:
                blocked.append(f"{tag}: {target} blocked: {missing[0]} is {shown(e['stages'][missing[0]]['status'])}")
            else:
                proposals.append({'key': f'{tag}:{target}-ready', 'kind': 'stage-ready', 'tag': tag, 'stage': target})
    return proposals, blocked


def failing_skills(score, files, skills):
    cases = case_objects(files, skills)
    return sorted({s for row in score['rows'] if not row['pass'] for s in cases[row['case']]['skills']})


def tally(score):
    return f"{score['passed']}/{score['runs']}"


def new_ledger():
    return {'schema': LEDGER, 'experiments': {}, 'actions': {}, 'weeks': {}}


def load_ledger(path):
    if not path.exists():
        return new_ledger()
    ledger = loads(path.read_text())
    if not isinstance(ledger, dict) or set(ledger) != {'schema', 'experiments', 'actions', 'weeks'} or ledger['schema'] != LEDGER:
        raise ValueError('invalid weekly ledger')
    for tag, e in ledger['experiments'].items():
        summary_valid(dict(e, tag=tag))
    for key, a in ledger['actions'].items():
        if (not isinstance(a, dict) or a.get('key') != key or a.get('status') not in STATUSES or
                a.get('kind') not in GATED + ('stage-ready',) or
                'receipt' in a and not (a['status'] == 'routed' and RECEIPT.fullmatch(str(a['receipt'])))):
            raise ValueError('invalid action ledger')
    return ledger


def weekly(directory, week, *, cases_dir=None, provenance=None, skills=None, read_page=None, synthesize=None,
           evidence=None, baseline=None, cuts=None, experiments=None, start_gate=None, route=None,
           token_report=None):
    """The one weekly process. Defaults do nothing; every effect is injected.

    baseline: {settings, score}, the old skills on this week's prepared cases.
    evidence: the core's fake envelope once the fixed skills pass.
    cuts: {skill: score} for single-skill cut attempts after a passing week.
    experiments: owner import summaries (tag, experiment_hash, stages, sources).
    start_gate() -> 'allowed' for builder work now; anything else defers it.
    route(action) hands one action to the orchestrator, once per key: it returns
    None once handed off, or 'queued' when it stays in the ledger for `handoff`.
    """
    if None in (cases_dir, skills, read_page, synthesize, start_gate, route):
        return report_of('not run', week, gaps=['fake tools, gate and router not supplied'])
    directory = Path(directory)
    try:
        C.week_start(week)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (directory / 'weekly.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return report_of('gap', week, gaps=['weekly process is locked'])
            return weekly_locked(directory, week, cases_dir, provenance, skills, read_page, synthesize, evidence,
                                 baseline, cuts or {}, experiments or [], start_gate, route, token_report)
    except (ValueError, KeyError, TypeError, AttributeError):
        return report_of('gap', week, gaps=['invalid input, ledger or owner record; nothing routed or changed'])


def weekly_locked(directory, week, cases_dir, provenance, skills, read_page, synthesize, evidence,
                  baseline, cuts, experiments, start_gate, route, token_report):
    path = directory / 'weekly.json'
    ledger = load_ledger(path)
    bound = bind_experiments(ledger['experiments'], experiments)
    tokens = token_summary(token_report)
    core = tick(directory, week, cases_dir=cases_dir, provenance=provenance, skills=skills,
                read_page=read_page, synthesize=synthesize, evidence=evidence)
    if core['status'] not in ('prepared', 'complete', 'unchanged'):
        return report_of(core['status'], week, gaps=core['gaps'])
    state = load_state(directory / 'state.json')
    done = core['status'] != 'prepared'
    files = state['case_files'] if done else state['pending']['files']
    ids = set(case_objects(files, skills))
    record = ledger['weeks'].setdefault(week, {'baseline': None, 'result': None, 'cuts': None,
                                               'revisions': None})
    gaps = list(core['gaps'])
    planned = []
    score = settings = None
    label = ''
    if done:
        # An unchanged week carries the last compatible result forward; only a
        # week completed with its own eval can route that eval's fixes.
        last = state['last_evidence']
        settings = last['settings']
        label = ' (measured run)' if last['mode'] == 'measured' else ''
        record['result'] = tally(last['result']) + label
        record['revisions'] = {k: last[k]['revision']['commit'] for k in ('baseline', 'result')}
        if core['status'] == 'complete':
            score = last['baseline']
    elif baseline is not None:
        X.require(isinstance(baseline, dict) and set(baseline) in ({'settings', 'score'}, {'mode', 'settings', 'score'})
                  and baseline.get('mode', 'fake') in ('fake', 'measured'), 'invalid baseline')
        score, settings = baseline['score'], baseline['settings']
        mode = baseline.get('mode', 'fake')
        score_valid(score, core['cases_hash'], ids, settings, mode)
        label = ' (measured run)' if mode == 'measured' else ''
    if score is not None:
        record['baseline'] = tally(score) + label
        planned += [{'key': f'{week}:fix:{s}', 'kind': 'fix', 'skill': s, 'week': week}
                    for s in failing_skills(score, files, skills)]
    if cuts and not done:
        gaps.append('cuts wait for a passing result at this cases hash')
    elif cuts:
        # Every cut is checked before any is recorded: same cases, settings,
        # eval code and record schema as the carried result (E1.compare).
        for skill, cut in sorted(cuts.items()):
            X.require(skill in skills, 'unknown skill')
            score_valid(cut, core['cases_hash'], ids, settings, last['mode'])
            E1.compare(last['result'], cut)
        attempts = copy.deepcopy(record['cuts']) or {}
        for skill, cut in sorted(cuts.items()):
            attempts.setdefault(skill, {})[E1.sha(cut)] = 'pass' if cut['suite_pass'] else 'fail'
            if cut['suite_pass']:
                planned.append({'key': f'{week}:cut:{skill}', 'kind': 'cut', 'skill': skill, 'week': week})
        record['cuts'] = attempts
    if record['baseline'] is not None and not done and planned:
        status = 'needs fixes'
    else:
        status = core['status']
    proposals, blocked = stage_plan(bound)
    planned += proposals
    ledger['experiments'] = bound
    # Retained deferred work is reconsidered every tick, without fresh inputs.
    planned += [a for k, a in sorted(ledger['actions'].items()) if a['status'] == 'deferred']
    gate, touched = [], set()
    for action in planned:
        action = ledger['actions'].get(action['key'], dict(action, status='new'))
        if action['status'] not in ('new', 'deferred') or action['key'] in touched:
            continue
        touched.add(action['key'])
        if action['kind'] in GATED:
            if not gate:
                try:
                    gate.append(start_gate() == 'allowed')
                except Exception:
                    gate.append(False)
            if not gate[0]:
                ledger['actions'][action['key']] = dict(action, status='deferred')
                continue
        # Durable before the effect: a lost reply is never sent twice.
        ledger['actions'][action['key']] = dict(action, status='unresolved')
        write_json(path, ledger)
        try:
            outcome = route({k: v for k, v in action.items() if k != 'status'})
        except Exception:
            continue
        if outcome is None or outcome == 'queued':
            ledger['actions'][action['key']]['status'] = 'routed' if outcome is None else 'queued'
            write_json(path, ledger)
    write_json(path, ledger)
    mine = {k: a['status'] for k, a in sorted(ledger['actions'].items())
            if a.get('week') == week or a['kind'] == 'stage-ready' or k in touched or a['status'] in OUTSTANDING}
    if 'deferred' in mine.values():
        gaps.append('builder work deferred by the credit-aware start rule; kept pending, not done')
    if 'unresolved' in mine.values():
        gaps.append('an action has an unknown outcome: verify on GitHub before resolving; never resent')
    if 'queued' in mine.values():
        gaps.append('actions queued, awaiting handoff: run.py handoff for each key run.py pending lists')
    gaps += ['real paid eval not run: #1362 end gate (route A1, spend, private literals)'] if \
        record['result'] is None else []
    if tokens == 'unobserved':
        gaps.append('required-text token counts unobserved')
    rejected = sorted(s for s, results in (record['cuts'] or {}).items() if 'fail' in results.values())
    stages = {tag: {n: shown(e['stages'][n]['status']) for n in STAGE_NAMES} for tag, e in sorted(bound.items())}
    return report_of(status, week, cases_hash=core['cases_hash'], cases_added=core['case_ids'], gaps=gaps,
                     actions=mine, stages=stages, blocked=blocked, rejected_cuts=rejected, tokens=tokens,
                     eval={k: record[k] or 'unobserved' for k in ('baseline', 'result')},
                     revisions=record['revisions'] or 'unobserved', evidence_class=core['evidence_class'])


def pending(directory):
    """Queued and unresolved actions, for the loop agent's handoff. Reads only."""
    ledger = load_ledger(Path(directory) / 'weekly.json')
    return [dict(a) for k, a in sorted(ledger['actions'].items()) if a['status'] in ('queued', 'unresolved')]


MARK = 'weekly-handoff: '  # then the action's key and the sha256 of its canonical payload


def payload(action):
    """The canonical pending-work payload: the action without its ledger status."""
    fields = {k: v for k, v in action.items() if k not in ('status', 'receipt')}
    return json.dumps(fields, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def payload_hash(action):
    return hashlib.sha256(payload(action).encode()).hexdigest()


def handoff_body(action):
    return (f"{MARK}{action['key']} {payload_hash(action)}\n\n"
            f"Skills-eval weekly action for the orchestrator.\npayload: {payload(action)}\n")


def is_handoff(body, action):
    """The same key and the same payload hash, with the payload itself present.

    Any line may carry them, so a prepended progress note does not hide a real
    handoff. A bare or stale marker, or a copied marker without its payload,
    is not this handoff: new pending work is posted, never dropped.
    """
    lines = body.split('\n')
    return (f"{MARK}{action['key']} {payload_hash(action)}" in lines and
            f"payload: {payload(action)}" in lines)


def handoff(directory, key, read_comments, post):
    """Hand one queued or unresolved action to the orchestrator exactly once.

    read_comments() -> every comment on the target issue as {id, body}, or raise.
    post(body) -> the new comment's id. The source is read first: a comment with
    this key's marker, the same payload hash and the payload itself is the
    earlier handoff, recorded without a post. The action is marked unresolved
    before posting, so a lost reply is settled by the next read, never by a
    second post.
    """
    directory = Path(directory)
    with (directory / 'weekly.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = directory / 'weekly.json'
        ledger = load_ledger(path)
        action = ledger['actions'].get(key)
        if action is None or action['status'] not in ('queued', 'unresolved'):
            raise ValueError('no queued or unresolved action with that key')
        try:
            comments = read_comments()
            X.require(isinstance(comments, list) and all(
                isinstance(c, dict) and type(c.get('id')) is int and c['id'] > 0 and isinstance(c.get('body'), str)
                for c in comments), 'malformed comments')
        except Exception:
            raise ValueError('target issue comments unreadable: handoff uncertain, nothing posted') from None
        earlier = sorted(c['id'] for c in comments if is_handoff(c['body'], action))
        if earlier:
            receipt = str(earlier[0])
        else:
            action['status'] = 'unresolved'
            write_json(path, ledger)
            receipt = post(handoff_body(action))
            if not isinstance(receipt, str) or not RECEIPT.fullmatch(receipt):
                raise ValueError('handoff reply has no comment id; read the issue again before anything else')
        action.update(status='routed', receipt=receipt)
        write_json(path, ledger)
        return receipt


def gh_issue(repo, issue, run):
    """REST reads/posts of one issue's comments through gh, for handoff()."""
    gh_reader(repo, run)  # the same OWNER/NAME check
    X.require(isinstance(issue, str) and re.fullmatch(r'[1-9][0-9]*', issue), 'issue must be a number')
    path = f'repos/{repo}/issues/{issue}/comments'

    def read():
        code, out = run(['gh', 'api', path + '?per_page=100', '--paginate', '--slurp'])
        pages = json.loads(out) if code == 0 else None
        X.require(isinstance(pages, list) and all(isinstance(p, list) and all(isinstance(c, dict) for c in p)
                                                  for p in pages), 'incomplete GitHub read')
        return [{'id': c.get('id'), 'body': c.get('body')} for p in pages for c in p]

    def post(body):
        code, out = run(['gh', 'api', '--method', 'POST', path, '-f', f'body={body}'])
        X.require(code == 0, 'post failed')
        return str(json.loads(out)['id'])
    return read, post


def token_summary(report):
    """Required-text tokens per skill and total, before/after; unknown stays unobserved."""
    if report is None:
        return 'unobserved'
    X.fields(report, 'tokenizer skills', 'token report')
    X.require(isinstance(report['tokenizer'], str) and report['tokenizer'].strip(), 'missing tokenizer')
    rows, total = {}, {'before': 0, 'after': 0}
    for skill, row in sorted(report['skills'].items()):
        X.fields(row, 'before after', 'token row')
        rows[skill] = {}
        for k in ('before', 'after'):
            value = row[k]
            X.require(value is None or type(value) is int and value >= 0, 'invalid token count')
            rows[skill][k] = 'unobserved' if value is None else value
            total[k] = 'unobserved' if value is None or total[k] == 'unobserved' else total[k] + value
    return {'tokenizer': report['tokenizer'], 'skills': rows, 'total': total}


def report_of(status, week, *, cases_hash=None, cases_added=None, gaps=None, actions=None, stages=None,
              blocked=None, rejected_cuts=None, tokens='unobserved', eval=None, revisions='unobserved',
              evidence_class='fixture test'):
    return {'status': status, 'week': week, 'cases_hash': cases_hash, 'cases_added': cases_added or [],
            'gaps': gaps or [], 'actions': actions or {}, 'stages': stages or {}, 'blocked': blocked or [],
            'rejected_cuts': rejected_cuts or [],
            'tokens': tokens, 'eval': eval or {'baseline': 'unobserved', 'result': 'unobserved'},
            'revisions': revisions, 'saving': None, 'evidence_class': evidence_class}


def write_report(out, report):
    """Render (and refuse) before writing; then replace each artifact atomically."""
    text = render(report)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    E1.write_json(out / 'report.json', report)
    tmp = out / 'report.md.tmp'
    with tmp.open('w') as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, out / 'report.md')
    return text


def render(report):
    """The short weekly GitHub result. Refuses links, thread or project ids."""
    text = json.dumps(report)
    if IDENTIFIERS.search(text):
        raise ValueError('report contains a link or operational identifier')
    tokens = report['tokens']
    lines = [f"**Skills-eval weekly result, week of {report['week']}: {report['status']}** "
             f"(evidence class: {report['evidence_class']}; saving: not measured)", '',
             f"- **Cases added:** {len(report['cases_added'])} ({', '.join(report['cases_added']) or 'none'})",
             f"- **Pass/fail:** baseline {report['eval']['baseline']}, result {report['eval']['result']}; "
             f"rejected cuts: {', '.join(report['rejected_cuts']) or 'none'}",
             f"- **Actions:** " + (', '.join(f'{k} {v}' for k, v in report['actions'].items()) or 'none'),
             f"- **Stages:** " + ('; '.join(f"{t}: " + ', '.join(f'{n} {s}' for n, s in st.items())
                                           for t, st in report['stages'].items()) or 'none bound'),
             f"- **Blocked:** {'; '.join(report['blocked']) or 'none'}"]
    if tokens == 'unobserved':
        lines.append('- **Tokens:** unobserved (no required-text token report)')
    else:
        lines.append(f"- **Tokens ({tokens['tokenizer']}):** " + '; '.join(
            f"{s} {r['before']} -> {r['after']}" for s, r in tokens['skills'].items()) +
            f"; total {tokens['total']['before']} -> {tokens['total']['after']}")
    rev = report['revisions']
    lines.append('- **Revisions:** ' + (rev if rev == 'unobserved' else
                                         f"baseline {rev['baseline'][:12]}, result {rev['result'][:12]}"))
    lines.append(f"- **Gaps:** {'; '.join(report['gaps']) or 'none'}")
    return '\n'.join(lines) + '\n'


# The real read_page: GitHub REST through `gh api --paginate --slurp`, which
# follows every Link page or exits nonzero. Any failure refuses the collection.

def gh_reader(repo, run):
    """run(argv) -> (exit code, stdout). One page per source holds every record."""
    if not isinstance(repo, str) or not re.fullmatch(r'[\w.-]+/[\w.-]+', repo) or '..' in repo:
        raise ValueError('repository must be OWNER/NAME')

    def pages(path):
        code, out = run(['gh', 'api', path, '--paginate', '--slurp'])
        data = json.loads(out) if code == 0 else None
        if (not isinstance(data, list) or any(not isinstance(p, list) for p in data) or
                any(not isinstance(i, dict) for p in data for i in p)):
            raise ValueError('incomplete GitHub read')
        return [i for p in data for i in p]

    def item(raw, when):
        return {'id': raw['id'], 'updated_at': raw[when], 'body': raw.get('body') or '', 'url': raw['html_url']}

    def read_page(source, week, page):
        if page != 1:
            raise ValueError('one complete page per source')
        since = C.week_start(week).strftime('%Y-%m-%dT%H:%M:%SZ')
        if source == 'issue_comments':
            raws = pages(f'repos/{repo}/issues/comments?since={since}&sort=updated&direction=asc&per_page=100')
            items = [item(r, 'updated_at') for r in raws]
        elif source == 'review_comments':
            raws = pages(f'repos/{repo}/pulls/comments?since={since}&sort=updated&direction=asc&per_page=100')
            items = [item(r, 'updated_at') for r in raws]
        elif source == 'reviews':
            # A review submitted this week updates its PR, so older PRs hold none.
            pulls = [p for p in pages(f'repos/{repo}/pulls?state=all&sort=updated&direction=desc&per_page=100')
                     if p['updated_at'] >= since]
            items = []
            for pull in sorted(pulls, key=lambda p: p['number']):
                X.integer(pull['number'], 1)
                items += [item(r, 'submitted_at') for r in pages(f"repos/{repo}/pulls/{pull['number']}/reviews?per_page=100")
                          if r.get('submitted_at') is not None]
        else:
            raise ValueError('unknown source')
        return {'items': items, 'next_page': None}
    return read_page


def run_gh(argv):
    done = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    return done.returncode, done.stdout


# The one weekly CloudRoom loop. The orchestrator registers it once, after this
# ticket's verified merge, and reads its schedule back; no id is kept here.
LOOP = {
    'name': 'Skills-eval weekly mistakes (CF4 E3)',
    'cron': '0 15 * * 1',
    'timezone': 'UTC',
    'prompt': (
        'Weekly skills-eval tick for spec #1358 (ticket #1363). Read tools/skills-eval/weekly/README.md, '
        '"Weekly runbook", and follow it for the UTC week that ended at this Monday 00:00. '
        'Until #1362\'s real baseline, cuts and token reports exist, run only the dry-run and the free '
        'collection tick, and report the honest gap: never a paid eval, live action, replay or live start. '
        'Never start a builder or reviewer or merge: hand each routed action to the orchestrator as the '
        'runbook says, and honour the credit-aware start rule, keeping deferred work pending. '
        'Post the short weekly result; if nothing is new, say so and archive this tick. '
        'Keep no watcher, polling loop or sleep. End the turn after room-cli loop report.'),
}


def loop_argv(prompt_file):
    return ['room-cli', 'loop', 'create', '--name', LOOP['name'], '--prompt-file', str(prompt_file),
            '--cron', LOOP['cron'], '--timezone', LOOP['timezone'], '--new-thread', '--secrets', 'none']


# A synthetic dry-run week: the same eval -> fix -> cut path as the first pass,
# with fake sources, outcomes, gate and router only.

def dry_run(out):
    from types import SimpleNamespace
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    week, skills = '2030-01-07', ['build-ticket', 'review-ticket']
    case = {'schema': 'openwiz.skills-eval.case.v1', 'id': 'i9001-weekly-dry-run', 'skills': ['build-ticket'],
            'category': 'incident', 'brief': 'Read skills/build-ticket/SKILL.md. A synthetic check is pending.',
            'world': {}, 'expect': {'actions': [], 'allow': [], 'forbid': [{'run': 'sleep'}], 'end': 'end_turn',
                                    'final': 'Facts: checks are pending. End the turn.'},
            'controls': {'pass': [{'why': 'Ends the turn.', 'events': [],
                                   'judgment': {'verdict': 'pass', 'reason': 'Waits.'}}],
                         'fail': [{'why': 'Waits awake.', 'events': [['read', 'sleep 300']], 'reason': 'forbidden'}]}}
    source = {'items': [{'id': 9001, 'updated_at': '2030-01-08T12:00:00Z', 'body': 'synthetic mistake',
                         'url': 'https://github.com/example/work/issues/4901#issuecomment-9001'}], 'next_page': None}
    settings = {'repeats': 2}

    def score(passing, cases_hash):
        rows = [{'case': case['id'], 'repeat': r, 'pass': passing, 'reasons': [] if passing else ['missing-action'],
                 'details': [], 'cost_usd': 0, 'stop': 'end_turn'} for r in (1, 2)]
        return {'schema': 'openwiz.skills-eval.score.v1', 'settings_hash': E1.sha(settings), 'cases_hash': cases_hash,
                'code_hash': 'b' * 64, 'schema_hash': 'c' * 64, 'revision': {'commit': 'd' * 40, 'tree': 'e' * 40},
                'suite_pass': passing, 'runs': 2, 'passed': 2 if passing else 0, 'cost_usd': 0, 'rows': rows}

    summary = {'tag': 'cf4-dry-run', 'experiment_hash': 'a' * 64,
               'stages': {'research': {'status': 'pass', 'artifact_hash': '1' * 64, 'source': 's1',
                                       'at': '2030-01-05T12:00:00Z'},
                          **{n: {'status': 'not_run', 'artifact_hash': None, 'source': None, 'at': None}
                             for n in ('cf4', 'replay', 'live')}},
               'sources': {'s1': 'https://github.com/example/work/issues/4950'}}
    routed = []
    previous = os.environ.get('OPENWIZ_PRIVACY_LITERALS')
    with tempfile.TemporaryDirectory() as tmp:
        literals = Path(tmp, 'literals.txt')
        literals.write_text('synthetic-dry-run-literal\n')  # E1's offline-control convention
        os.environ['OPENWIZ_PRIVACY_LITERALS'] = str(literals)
        try:
            Path(tmp, 'cases').mkdir()
            kw = SimpleNamespace(cases_dir=Path(tmp, 'cases'), skills=skills, start_gate=lambda: 'allowed',
                                 read_page=lambda s, w, p: copy.deepcopy(source) if s == 'issue_comments'
                                 else {'items': [], 'next_page': None},
                                 synthesize=lambda item: {'incident': 'dry-run-watcher', 'case': copy.deepcopy(case)},
                                 route=routed.append)
            state = Path(tmp, 'state')
            step = lambda **extra: weekly(state, week, experiments=[summary], **vars(kw), **extra)
            h = step()['cases_hash']
            step(baseline={'settings': settings, 'score': score(False, h)})
            step(evidence={'mode': 'fake', 'settings': settings, 'baseline': score(False, h), 'result': score(True, h),
                          'results_set': 'synthetic-results/dry-run', 'token_report': 'synthetic-tokens/dry-run.json'})
            report = step(cuts={'build-ticket': score(True, h), 'review-ticket': score(False, h)})
        finally:
            if previous is None:
                os.environ.pop('OPENWIZ_PRIVACY_LITERALS', None)
            else:
                os.environ['OPENWIZ_PRIVACY_LITERALS'] = previous
    write_report(out, report)
    return report


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description='Weekly skills-eval continuation (#1363). See README.md.')
    sub = p.add_subparsers(dest='cmd', required=True)
    d = sub.add_parser('dry-run', help='synthetic week, fake tools only; writes report.json and report.md')
    d.add_argument('--out', required=True)
    s = sub.add_parser('sources', help="print the week's in-week source records (transient; never saved)")
    s.add_argument('--repo', required=True)
    s.add_argument('--week', required=True)
    t = sub.add_parser('tick', help='the free collection tick with agent-drafted synthetic cases')
    for name in ('--repo', '--week', '--state', '--drafts', '--report'):
        t.add_argument(name, required=True)
    for name in ('--experiments', '--baseline', '--evidence', '--cuts', '--tokens'):
        t.add_argument(name)
    t.add_argument('--starts', choices=('allowed', 'deferred'), default='deferred')
    q = sub.add_parser('pending', help='list queued and unresolved actions to hand off; reads only')
    q.add_argument('--state', required=True)
    h = sub.add_parser('handoff', help='post one pending action once, after reading the issue for an earlier one')
    for name in ('--state', '--repo', '--issue', '--key'):
        h.add_argument(name, required=True)
    l = sub.add_parser('loop-definition', help='print the one registration command; registers nothing')
    l.add_argument('--prompt-file', required=True)
    a = p.parse_args(argv)
    if a.cmd == 'dry-run':
        print(render(dry_run(a.out)), end='')
    elif a.cmd == 'loop-definition':
        Path(a.prompt_file).write_text(LOOP['prompt'] + '\n')
        print(json.dumps(loop_argv(a.prompt_file)))
    elif a.cmd == 'pending':
        for action in pending(a.state):
            print(json.dumps(action, sort_keys=True))
    elif a.cmd == 'handoff':
        print(handoff(a.state, a.key, *gh_issue(a.repo, a.issue, run_gh)))
    elif a.cmd == 'sources':
        read = gh_reader(a.repo, run_gh)
        start = C.week_start(a.week)
        for source in C.SOURCES:
            for it in read(source, a.week, 1)['items']:
                when = dt.datetime.fromisoformat(it['updated_at'].replace('Z', '+00:00'))
                if start <= when < start + dt.timedelta(days=7):
                    print(json.dumps({'source': source, 'url': it['url'], 'body': it['body']}))
    else:
        drafts = loads(Path(a.drafts).read_text())
        if not isinstance(drafts, dict):
            raise SystemExit('drafts must map each in-week source URL to null or {incident, case}')

        def synthesize(item):
            if item['url'] not in drafts:
                raise ValueError('undecided source record')
            return drafts[item['url']]

        opt = lambda v: None if v is None else loads(Path(v).read_text())
        root = HERE.parents[2]
        skills = [Path(x).name for x in loads((root / '.claude-plugin/plugin.json').read_text())['skills']]
        report = weekly(a.state, a.week, cases_dir=root / 'tools/skills-eval/cases',
                        provenance=loads((root / 'tools/skills-eval/provenance.json').read_text()),
                        skills=skills, read_page=gh_reader(a.repo, run_gh), synthesize=synthesize,
                        evidence=opt(a.evidence), baseline=opt(a.baseline), cuts=opt(a.cuts),
                        experiments=opt(a.experiments), token_report=opt(a.tokens),
                        start_gate=lambda: a.starts, route=lambda action: 'queued')
        print(write_report(a.report, report), end='')
    return 0


if __name__ == '__main__':
    sys.exit(main())
