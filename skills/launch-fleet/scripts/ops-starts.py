#!/usr/bin/env python3
"""OB5 (#1480): approved builder starts and initial green-head reviews in one finite ops pass.

The ops agent reads GitHub and CloudRoom completely and supplies the facts per
candidate (see ../test/ops-starts/README.md). This module checks every start
gate, selects the configured settings and the other-family reviewer from
docs/agents/fleet.md, builds or reuses the one durable `intent` for each
eligible start, and runs it through #1456's ops pass and OB3's boundary. Under
OB-A1 every start stays disabled: `effect_boundary` is never called, and the
result is recorded and the pass ends. Nothing here waits, polls or retries.
"""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # never leave caches in an installed skill


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


effects = _load(HERE / 'effects.py', 'ops_effects')
records = _load(HERE / 'records.py', 'fleet_records')
gitread = _load(HERE / 'gitread.py', 'launch_fleet_gitread')

SMALL = {'polish', 'huntr', 'proposal'}
NOT_READY = {'needs-info', 'needs-triage', 'ready-for-human', 'wontfix', 'held'}
SETTLED = {'completed', 'superseded', 'reconciled_not_executed', 'disabled', 'refused'}
BENCH = 'closedwiz.journey.stage-bench.v1'
# Explicitly synthetic audit example; no recorded factory measurement and no
# recovered-time claim. These invented values illustrate the report's shape.
PROVENANCE = {
    'source': 'synthetic audit example, not an operational measurement',
    'cohort': 'invented merged and open pull requests',
    'initial_review_handoffs': 10,
    'green_to_dispatch_pr_hours': 2.5,
    'meaning': 'synthetic ceiling only; gated intervals and unproven authority are not recoverable time',
}


BUILDER_FIELDS = {'ticket', 'open', 'labels', 'approval', 'approved_ready', 'fingerprint_now', 'table_complete',
                  'blockers', 'blockers_complete', 'holds', 'gates', 'live_builders', 'start_claims', 'open_prs',
                  'admission', 'complete', 'evidence'}
REVIEW_FIELDS = {'pr', 'ticket', 'open', 'draft', 'labels', 'approval', 'fingerprint_now', 'table_complete', 'head',
                 'head_now', 'branch', 'ci', 'builder', 'spans', 'closes', 'base', 'default_branch', 'subject',
                 'verdict', 'holds', 'gates', 'reviewer_available', 'admission', 'complete', 'evidence'}
NESTED = {'ci': {'head', 'state', 'required_complete'}, 'builder': {'record_branch', 'providers'},
          'evidence': {'evidence_class', 'source'}}


class Refusal(Exception):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


FAMILY = {'claude-code': 'claude', 'codex': 'gpt'}
REFUSAL_ALIASES = {
    'claude-code': ('claude', 'claude-code'),
    'antigravity': ('gemini', 'antigravity'),
    'codex': ('codex', 'gpt'),
}
REFUSED_USAGE = re.compile(r'^launch-fleet: review refused ([0-9a-f]{40}): ([A-Za-z0-9._-]+) usage limit\s*$', re.I)
OLDER = ('Builder', 'Builder for small tickets', 'Reviewer for Claude-built', 'Reviewer for GPT-built', 'Fixer')
MODELS_HEADER = ['Role', 'Harness', 'Model', 'Effort', '`room-cli thread spawn` flags']
FIXER_HEADER = ['Builder family'] + MODELS_HEADER[1:]
SETTING_HEADER = ['Setting', 'Value', '`room-cli thread spawn` flag']
REPO = re.compile(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+')
LOOP = re.compile(r'[A-Za-z0-9_-]+')
ROLES = (('Orchestrator', 'orchestrator'), ('Builder', 'builder'), ('Reviewer', 'reviewer'),
         ('Small builder', 'small_builder'), ('Fixer', 'fixer'))
ID = re.compile(r'[A-Za-z0-9._-]+')
STARTS = {'fleet_thread': ('roles', 'orchestrator'), 'builder': ('roles', 'builder'),
          'small_builder': ('roles', 'small_builder'), 'review_of_claude_built': ('reviews', 'claude'),
          'review_of_gpt_built': ('reviews', 'gpt'), 'fix_round_for_claude_builder': ('fixers', 'claude'),
          'fix_round_for_gpt_builder': ('fixers', 'gpt')}


def _lines(text):
    return [line[:-1] if line.endswith('\r') else line for line in text.split('\n')]


def _cells(line):
    if len(line) < 2 or not (line.startswith('|') and line.endswith('|')):
        raise ValueError('fleet settings: not a table row')
    return [c.strip() for c in line[1:-1].split('|')]


def _section(text, name):
    lines = _lines(text)
    at = [i for i, line in enumerate(lines) if line == '## ' + name]
    if len(at) > 1:
        raise ValueError(f'fleet settings: more than one "## {name}"')
    if not at:
        return None
    end = next((j for j in range(at[0] + 1, len(lines)) if lines[j].startswith('## ')), len(lines))
    return lines[at[0] + 1:end]


def _id(word, model=False):
    if not all(ID.fullmatch(part) for part in (word.split('/') if model else [word])):
        raise ValueError(f'fleet settings: bad {"model " if model else ""}id {word!r}')
    return word


def _choice(names, provider, model, effort):
    if not all(names):
        raise ValueError('fleet settings: an empty name cell')
    return dict(provider=_id(provider), model=None if model is None else _id(model, True), effort=_id(effort))


def _flags(cell):
    words = cell[1:-1].split(' ') if len(cell) > 1 and cell[0] == cell[-1] == '`' else []
    if len(words) == 6 and words[0::2] == ['--provider', '--model', '--reasoning-level']:
        return words[1], words[3], words[5]
    if len(words) == 4 and words[0::2] == ['--provider', '--reasoning-level']:
        return words[1], None, words[3]
    raise ValueError(f'fleet settings: bad flags {cell!r}')


def _models_table(lines):
    start = next((i for i, line in enumerate(lines) if line.startswith('|')), None)
    if start is None:
        raise ValueError('fleet settings: no Models table')
    rows = []
    for line in lines[start:]:
        if not line.startswith('|'):
            break
        rows.append(_cells(line))
    if len(rows) < 2 or rows[0] != MODELS_HEADER or rows[1] != ['---'] * 5:
        raise ValueError('fleet settings: bad Models header')
    roles, fallbacks, next_at, next_fb = {}, [], 0, 1
    for row in rows[2:]:
        if len(row) != 5:
            raise ValueError('fleet settings: a Models row without five cells')
        if row[0] == f'Reviewer fall-back {next_fb}' and next_at >= 3:
            if row[1] == 'follows Builder' and row[2:] == ['', '', '']:
                raise ValueError(f'fleet settings: {row[0]} cannot follow')
            fallbacks.append(_choice(row[1:4], *_flags(row[4])))
            next_at = len(ROLES)
            next_fb += 1
            continue
        at = next((i for i in range(next_at, len(ROLES)) if ROLES[i][0] == row[0]), None)
        if at is None:
            raise ValueError(f'fleet settings: row {row[0]!r} out of place')
        if at > next_at and next_at < 3:
            raise ValueError('fleet settings: a required Models row is missing')
        if row[1] == 'follows Builder' and row[2:] == ['', '', '']:
            if at < 3:
                raise ValueError(f'fleet settings: {row[0]} cannot follow')
            roles[ROLES[at][1]] = dict(follows='builder', choice=None)
        else:
            roles[ROLES[at][1]] = dict(follows=None, choice=_choice(row[1:4], *_flags(row[4])))
        next_at = at + 1
    if next_at < 3:
        raise ValueError('fleet settings: a required Models row is missing')
    for _, key in ROLES[3:]:
        role = roles.setdefault(key, dict(follows='builder', choice=None))
        if role['follows']:
            role['choice'] = roles['builder']['choice']
    return roles, fallbacks


def _one_table(lines, header, name):
    at = [i for i, line in enumerate(lines) if line.startswith('|')]
    if not at or at[-1] - at[0] + 1 != len(at):
        raise ValueError(f'fleet settings: not exactly one "{name}" table')
    rows = [_cells(lines[i]) for i in at]
    if len(rows) < 2 or rows[0] != header or rows[1] != ['---'] * len(header) or any(
            len(row) != len(header) for row in rows):
        raise ValueError(f'fleet settings: bad "{name}" table header')
    return rows[2:]


def _setting_table(lines, name):
    rows = _one_table(lines, SETTING_HEADER, name)
    if len(rows) != 3:
        raise ValueError(f'fleet settings: "{name}" needs exactly its Harness, Model and Effort rows')
    names, ids = [], []
    for row, (setting, flag) in zip(rows, (('Harness', '--provider'), ('Model', '--model'),
                                           ('Effort', '--reasoning-level'))):
        if (row[0] != setting or not row[2].startswith(f'`{flag} ') or not row[2].endswith('`')
                or len(row[2]) <= len(flag) + 3):
            raise ValueError(f'fleet settings: "{name}" needs its {setting} row')
        names.append(row[1])
        ids.append(row[2][len(flag) + 2:-1])
    return _choice(names, *ids)


def _older_tables(text):
    tables = []
    for name in OLDER[:4]:
        lines = _section(text, name)
        if lines is None:
            raise ValueError(f'fleet settings: one "## {name}" section required')
        tables.append(_setting_table(lines, name))
    fixer = _section(text, 'Fixer')
    if fixer is None:
        raise ValueError('fleet settings: one "## Fixer" section required')
    rows = _one_table(fixer, FIXER_HEADER, 'Fixer')
    fixers = []
    for family, own_family in (('Claude', 'claude'), ('GPT', 'gpt')):
        mine = [row for row in rows if row[0] == family]
        if len(mine) != 1:
            raise ValueError(f'fleet settings: not exactly one Fixer row {family}')
        choice = _choice(mine[0][1:4], *_flags(mine[0][4]))
        fixers.append(choice if FAMILY.get(choice['provider']) == own_family else None)
    if len(rows) != 2:
        raise ValueError('fleet settings: a Fixer table without exactly its Claude and GPT rows')
    builder, small, for_claude, for_gpt = tables
    if (for_claude['provider'] != 'codex' or for_gpt['provider'] != 'claude-code'
            or {builder['provider'], small['provider']} - set(FAMILY)):
        raise ValueError('fleet settings: builder/reviewer tables break the family rule')
    own = 0 if FAMILY[builder['provider']] == 'claude' else 1
    older = dict(follows=None, choice=None)
    return dict(read='older_tables',
                roles=dict(orchestrator=dict(older, follows='builder', choice=builder),
                           builder=dict(older, choice=builder), reviewer=dict(older, choice=tables[2 + own]),
                           small_builder=dict(older, choice=small), fixer=dict(older, choice=fixers[own])),
                reviews=dict(claude=dict(choice=for_claude, row='Reviewer'), gpt=dict(choice=for_gpt, row='Reviewer')),
                fixers=dict(claude=dict(choice=fixers[0], row='Fixer'), gpt=dict(choice=fixers[1], row='Fixer')),
                reviewer_fallbacks=[])


def read_models(text):
    section = _section(text, 'Models')
    if section is None:
        if not any(line == '## ' + name for name in OLDER for line in _lines(text)):
            raise ValueError('fleet settings: no model settings')
        return _older_tables(text)
    roles, fallbacks = _models_table(section)
    builder, reviewer, fixer = (roles[k]['choice'] for k in ('builder', 'reviewer', 'fixer'))
    reviews, fixers = {}, {}
    for family in ('claude', 'gpt'):
        reviews[family] = next((dict(choice=c, row=row) for c, row in ((reviewer, 'Reviewer'), (builder, 'Builder'))
                                if FAMILY.get(c['provider']) not in (None, family)), dict(choice=None, row=None))
        fixers[family] = next((dict(choice=c, row=row) for c, row in ((fixer, 'Fixer'), (reviewer, 'Reviewer'))
                               if FAMILY.get(c['provider']) == family), dict(choice=None, row=None))
    return dict(read='models_table', roles=roles, reviews=reviews, fixers=fixers, reviewer_fallbacks=fallbacks)


def read_fleet(repo):
    if type(repo) is not str or not REPO.fullmatch(repo) or repo.split('/')[1] in ('.', '..'):
        raise ValueError(f'not a repository: {repo!r}')
    try:
        return gitread.show(repo, 'docs/agents/fleet.md')
    except gitread.Error as error:
        raise ValueError(f'could not read docs/agents/fleet.md from the default branch of {repo}: {error}')


def loop_agent(models, listing, loop):
    if not LOOP.fullmatch(loop):
        raise ValueError(f'not a loop id: {loop!r}')
    items = listing.get('automations') if type(listing) is dict else None
    mine = [x for x in items if type(x) is dict and x.get('id') == loop] if type(items) is list else []
    if len(mine) != 1:
        raise ValueError(f'loop {loop}: not listed exactly once')
    agent, want = mine[0].get('agent', 'absent'), models['roles']['orchestrator']['choice']
    if agent is not None and (type(agent) is not dict or set(agent) != {'provider', 'model', 'reasoning'}):
        raise ValueError(f'loop {loop}: unreadable agent')
    if agent == dict(provider=want['provider'], model=want['model'], reasoning=want['effort']):
        return None
    return (f'room-cli loop update {loop} --provider {want["provider"]} --model {want["model"]} '
            f'--reasoning {want["effort"]}')


def _format_flags(c):
    if c is None:
        return None
    if c['model'] is None:
        return f'--provider {c["provider"]} --reasoning-level {c["effort"]}'
    return f'--provider {c["provider"]} --model {c["model"]} --reasoning-level {c["effort"]}'


def spawn_flags(models):
    return {start: _format_flags(models[kind][key]['choice']) for start, (kind, key) in STARTS.items()}


def refused_families_for_commit(comments, commit):
    seen, out = set(), []
    for body in comments:
        for line in _lines(body):
            m = REFUSED_USAGE.fullmatch(line.strip())
            if m and m.group(1).lower() == commit.lower():
                family = m.group(2).lower()
                if family not in seen:
                    seen.add(family)
                    out.append(family)
    return tuple(out)


def reviewer_order(models, refused=()):
    blocked = {f.lower() for f in refused}
    candidates = [models['roles']['reviewer']['choice'], *models.get('reviewer_fallbacks', ())]
    out = []
    for c in candidates:
        aliases = set(REFUSAL_ALIASES.get(c['provider'], (c['provider'],)))
        if not (aliases & blocked):
            out.append(c)
    return out


def host_args(models):
    out = {}
    for start, (kind, key) in STARTS.items():
        c = models[kind][key]['choice']
        row = dict((k, name) for name, k in ROLES)[key] if kind == 'roles' else models[kind][key]['row']
        out[start] = None if c is None else '%s %s %s' % (
            'claude' if c['provider'] == 'claude-code' else c['provider'], c['model'], row)
    return out


def require(condition, reason):
    if condition is not True:
        raise Refusal(reason)


def current_approval(c):
    effects._validate(effects.SCHEMA['$defs']['approval'], c['approval'])
    require(c['table_complete'] is True and c['fingerprint_now'] == c['approval']['fingerprint'],
            'approval not current')


def check_builder(c, models):
    """Every frontier gate, in fleet-tick's order; returns the configured builder settings."""
    require(c['complete'], 'incomplete read')
    require(c['open'], 'ticket closed')
    current_approval(c)
    require(c['approved_ready'], 'not approved ready in the current plan')
    labels = c['labels']
    require(type(labels) is list and 'ready-for-agent' in labels and not NOT_READY & set(labels),
            'not ready, or held')
    require(c['holds'] == [] and c['gates'] == [], 'a hold or gate remains')
    require(c['blockers_complete'] and all(b['merged'] is True for b in c['blockers']),
            'a blocker merge is unverified')
    require(type(c['live_builders']) is int and c['live_builders'] == 0, 'a builder exists or is unknown')
    require(c['start_claims'] == [] and c['open_prs'] == [], 'an unsettled start claim or open pull request')
    require(c['admission'] == 'ok', 'start not admitted: ' + str(c['admission']))
    return dict(models['roles']['small_builder' if SMALL & set(labels) else 'builder']['choice'])


def check_review(c, models):
    """Initial review of the exact current green head; returns the other-family reviewer settings."""
    require(c['complete'], 'incomplete read')
    require(c['open'] and c['draft'] is False, 'pull request closed or draft')
    current_approval(c)
    require(type(c['labels']) is list and 'held' not in c['labels'] and c['holds'] == [] and c['gates'] == [],
            'ticket held or gated')
    head, ci = c['head'], c['ci']
    require(type(head) is str and re.fullmatch('[0-9a-f]{40}', head) is not None and c['head_now'] == head,
            'head is not current')
    require(ci['head'] == head and ci['state'] == 'success' and ci['required_complete'] is True,
            'required CI is not green at the current head')
    require(c['closes'] == [c['ticket']], 'the pull request does not close exactly its ticket')
    require(type(c['default_branch']) is str and c['default_branch'] != '' and c['base'] == c['default_branch'],
            'the pull request does not target the default branch')
    require(type(c['subject']) is str and re.search(r'\bgreen\b', c['subject']) is not None,
            'the head is not a hand-back (no "green" in its subject)')
    require(c['verdict'] is None, 'the pull request already has a verdict')
    spans = c['spans']
    require(type(spans) is list and all(type(x) is dict and set(x) == {'head', 'given_up'} for x in spans),
            'reviewer history unreadable')
    # First review: no reviewer ever started. Fresh review: every one was given up.
    # A retained reviewer re-checks through OB6 (#1481), never a new start here.
    require(all(x['given_up'] is True for x in spans), 'a retained reviewer re-checks (OB6), no new start')
    builder = c['builder']
    require(builder['record_branch'] is not None and builder['record_branch'] == c['branch'],
            'builder start record does not match the head branch')
    providers = builder['providers']
    require(type(providers) is list and len(providers) == 1 and providers[0] in ('claude-code', 'codex'),
            'builder family unknown or conflicting')
    selected = models['reviews'][FAMILY[providers[0]]]['choice']
    require(selected is not None, 'no other-family reviewer: the review waits, never swapped')
    require(FAMILY.get(selected['provider']) not in (None, FAMILY[providers[0]]),
            'configured reviewer is the builder family')
    selected = dict(selected)
    require(c['reviewer_available'], 'selected reviewer unavailable: waits, never swapped')
    require(c['admission'] == 'ok', 'start not admitted: ' + str(c['admission']))
    return selected


def binding_digest(intent, settings, rule):
    """What a durable start intent binds besides its key: the start identity, settings and rule."""
    identity = {k: intent[k] for k in effects.KEY_FIELDS if k != 'sequence'}
    return digest(dict(identity=identity, settings=settings, rule=rule))


def claim_for(intent, generation, owner):
    """The operation claim for one intent under the pass's generation and owner."""
    claim = {k: intent[k] for k in ('schema', 'repository', 'spec', 'ticket', 'subject', 'operation_key',
                                     'created_at', 'approval', 'rule', 'evidence')}
    claim.update(kind='claim', id=f'claim-{intent["id"]}-g{generation}', scope='operation', generation=generation,
                 previous_generation=generation - 1, owner=owner, intent_id=intent['id'])
    claim['ref'] = effects.claim_ref(claim)
    return claim


def _misses(bench, limits):
    if bench is None:
        return []
    if limits is None:
        raise ValueError('stage misses need the shared limits reader result')
    if bench.get('schema') != BENCH or bench.get('authority') != 'none' or bench.get('settings') != limits:
        raise ValueError('stage-wait evidence is not the current bench under the current limits')
    return [w for w in bench['waits'] if w['result'] == 'missed' and w['end'] is None and w['key'] in bench['misses']
            and w['stage'] in ('builder_start', 'reviewer_start')]


def _miss_matches(wait, c, review):
    if review:
        return (wait['stage'] == 'reviewer_start' and wait['pull_request'] == c.get('pr')
                and wait['key'].split(':')[2] == c.get('head'))
    return wait['stage'] == 'builder_start' and wait['key'] == f'builder_start:t{c.get("ticket")}'


def _operation(c, review, action, subject, selected, world, history, planned, entry):
    """Build or reuse the one durable intent for an eligible start, with its claim and snapshot."""
    repo, spec, ticket = world['repository'], world['spec'], c['ticket']
    generation, owner = world['pass']['generation'], world['pass']['owner']
    head = c['head'] if review else None
    identity = dict(repository=repo, spec=spec, ticket=ticket, subject=subject, approval=c['approval'],
                    action=action, destination='reviewer' if review else 'builder',
                    assignment=f'review-p{c["pr"]}-{head[:12]}-r{len(c["spans"]) + 1}' if review
                    else f'builder-t{ticket}', prior_verdict=None, head=head)
    ticket_history = [r for r in history if (r['repository'], r['spec'], r['ticket']) == (repo, spec, ticket)]
    events = {}
    for r in ticket_history:
        events.setdefault(r['operation_key'], []).append(r)

    def settled(record):
        return any(e['kind'] == 'completion' and e['state'] in SETTLED for e in events.get(record['operation_key'], []))
    mine = [r for r in history + planned if r['kind'] == 'intent'
            and (r['repository'], r['spec'], r['ticket']) == (repo, spec, ticket)]
    same = sorted((r for r in mine if all(r[k] == v for k, v in identity.items())), key=lambda r: r['sequence'])
    bound = binding_digest(dict(identity, sequence=0), selected, world['rule'])
    latest = same[-1] if same else None
    if latest is not None and latest['rule'] == world['rule'] and latest['evidence'][0]['digest'] == bound:
        intent = latest
    elif latest is not None and not settled(latest):
        raise Refusal('start binding changed under an unresolved earlier intent')
    else:
        # First start, or the settled earlier intent's settings/rule changed: a new operation.
        sequence = 1 + max([r['sequence'] for r in mine if r['approval'] == c['approval']], default=0)
        evidence = dict(evidence_class=c['evidence']['evidence_class'], source=c['evidence']['source'],
                        digest=bound)
        intent = dict(identity, schema='openwiz.ops-dispatch.v1', kind='intent', created_at=world['pass']['now'],
                      id='pending', rule=world['rule'], evidence=[evidence], sequence=sequence)
        intent['operation_key'] = effects.operation_key(intent)
        # Repository-unique and deterministic: derived from the full operation identity.
        intent['id'] = f'{action.replace("_", "-")}-{intent["operation_key"][:32]}'
        intent = effects.read_record(json.dumps(intent))
        entry['new'] = not any(r == intent for r in planned)
    # An admitted claim with no later outcome may have started: that is uncertain, not absent.
    unsure = sorted(k for k, rs in events.items()
                    if any(r['kind'] == 'admission' and r['state'] == 'admitted' for r in rs)
                    and not any(r['kind'] in ('transport', 'completion') for r in rs))
    pool = {r['id']: r for r in mine + [intent] if r['approval'] == intent['approval']}
    open_seq = [r['sequence'] for r in pool.values() if not settled(r)]
    snapshot = dict(
        schema='openwiz.ops-dispatch.v1', kind='snapshot', repository=repo, spec=spec, ticket=ticket,
        approval=intent['approval'], head=intent['head'], generation=generation, owner=owner, complete=True,
        uncertain_keys=unsure, paused=False, revoked=False, holds=[], gates=[], cutoff='0' * 40,
        history_digest=digest(ticket_history), next_sequence=min(open_seq, default=intent['sequence']),
        recipient_verified=False, rule=world['rule'], consumers=[], cutoff_changes=[],
        material={k: digest([k, intent['operation_key']]) for k in (
            'intent_digest', 'evidence_digest', 'ownership_digest', 'purpose_digest', 'rule_digest')},
        intents=sorted(pool.values(), key=lambda r: r['sequence']),
        producer=dict(ticket=ticket, approval=intent['approval'], merge='0' * 40, delta_digest='0' * 64))
    claim = claim_for(intent, generation, owner)
    effects.read_record(json.dumps(claim))
    effects.read_record(json.dumps(snapshot))
    return dict(intent=intent, claim=claim, history=ticket_history, snapshot=snapshot)


def plan(world, fleet_text, effect_boundary, bench=None, limits=None):
    """One finite pass. Returns one entry per candidate, builders then reviews, in input order."""
    models = read_models(fleet_text)
    misses = _misses(bench, limits)
    generation, owner = world['pass']['generation'], world['pass']['owner']
    history = [effects.read_record(json.dumps(r, allow_nan=False)) for r in world['history']]
    planned = []
    entries, operations = [], []
    for action, candidates in (('builder_start', world['builders']), ('review_start', world['reviews'])):
        review = action == 'review_start'
        for c in candidates:
            shaped = (type(c) is dict and set(c) == (REVIEW_FIELDS if review else BUILDER_FIELDS)
                      and all(type(c[k]) is dict and set(c[k]) == v for k, v in NESTED.items() if k in c)
                      and type(c['ticket']) is int and (not review or type(c['pr']) is int))
            ticket = c['ticket'] if shaped else None
            number = (c['pr'] if review else ticket) if shaped else None
            subject = dict(kind='pull_request' if review else 'issue', number=number)
            missed = next((w['key'] for w in misses if _miss_matches(w, c, review)), None) if shaped else None
            entry = dict(action=action, subject=subject, ticket=ticket, decision='refused', reason=None,
                         settings=None, intent=None, new=False, claim=None, result=None, missed=missed)
            entries.append(entry)
            try:
                if not shaped:
                    raise Refusal('incomplete or malformed source')
                selected = (check_review if review else check_builder)(c, models)
                operation = _operation(c, review, action, subject, selected, world, history, planned, entry)
            except Refusal as refusal:
                entry['reason'] = str(refusal)
                continue
            except (KeyError, TypeError, ValueError, AttributeError, IndexError):
                # Candidate-local: an unreadable fact or invalid record refuses this start alone.
                entry.update(reason='incomplete or malformed source', new=False)
                continue
            entry.update(decision='dispatch', settings=selected, intent=operation['intent'], claim=operation['claim'])
            if entry['new']:
                planned.append(operation['intent'])
            operations.append((entry, operation))
    view = dict(generations=world['generations'], operations=[op for _, op in operations],
                **{'pass': dict(generation=generation, owner=owner)})
    for (entry, _), result in zip(operations, records.ops_pass(view, effect_boundary, effects)):
        entry['result'] = result
    return entries


def _rank(values, share):
    return values[max(0, math.ceil(share * len(values)) - 1)] if values else None


def report(bench):
    """Eligible start delays with their denominators, from TL2's stage bench (authority none)."""
    if bench.get('schema') != BENCH or bench.get('authority') != 'none':
        raise ValueError('not a TL2 stage bench without authority')
    rows = {row['stage']: row for row in bench['stages']}
    out = dict(authority='none', read_at=bench['read_at'], settings=bench['settings'], provenance=PROVENANCE)
    for stage in ('builder_start', 'reviewer_start'):
        waits = [w for w in bench['waits'] if w['stage'] == stage]
        counts = {k: sum(w['result'] == k for w in waits) for k in rows[stage]['results']}
        if counts != rows[stage]['results'] or rows[stage]['intervals'] != len(waits):
            raise ValueError(f'{stage}: denominators disagree with the waits')
        # Only a start that happened has a dispatch time; an open miss stays in the denominators.
        ended = sorted(w['wait_minutes'] for w in waits if w['end'] is not None
                       and w['result'] in ('missed', 'not missed') and w['wait_minutes'] is not None)
        limit = rows[stage]['limit_minutes']
        out[stage] = dict(limit_minutes=limit, intervals=len(waits), results=counts, measured_ended=len(ended),
                          p50_minutes=_rank(ended, 0.5), p90_minutes=_rank(ended, 0.9),
                          excess_minutes=sum(max(0.0, m - limit) for m in ended),
                          excluded={k: counts[k] for k in ('gated', 'stale', 'unknown')})
    return out


def main():
    args = sys.argv[1:]
    try:
        if len(args) in (2, 4) and args[0] == 'pass' and (len(args) == 2 or args[2] == '--bench'):
            world = json.loads(Path(args[1]).read_text(), object_pairs_hook=records.unique)
            bench = limits = None
            if len(args) == 4:
                bench = json.loads(Path(args[3]).read_text(), object_pairs_hook=records.unique)
                limits = _load(HERE / 'carried/limits.py', 'factory_limits').read(
                    HERE / 'carried/limits.conf')

            def refuse(*_):
                raise RuntimeError('OB-A1: starts are disabled')
            out = plan(world, read_fleet(world.get('repository') if type(world) is dict else None), refuse,
                       bench, limits)
        elif len(args) == 4 and args[:2] == ['host', '--repo'] and args[3] in STARTS or (
                len(args) in (3, 4) and args[:2] == ['flags', '--repo'] and (len(args) == 3 or args[3] in STARTS)):
            flags = (host_args if args[0] == 'host' else spawn_flags)(read_models(read_fleet(args[2])))
            if len(args) == 3:
                out = [flags]
            elif flags[args[3]] is None:
                why = 'no other-family choice' if args[3].startswith('review') else "no choice of the builder's family"
                print(f'ops-starts: {args[3]} waits: {why}', file=sys.stderr)
                return 1
            else:
                print(flags[args[3]])
                return 0
        elif len(args) >= 3 and args[:2] == ['reviewer-order', '--repo']:
            rest = args[3:]
            refused = []
            if len(rest) % 2 != 0:
                raise ValueError('expected --refused <family> pairs')
            for i in range(0, len(rest), 2):
                if rest[i] != '--refused' or not ID.fullmatch(rest[i + 1]):
                    raise ValueError(f'bad reviewer-order argument {rest[i]!r}')
                refused.append(rest[i + 1])
            choices = reviewer_order(read_models(read_fleet(args[2])), refused)
            if not choices:
                print('ops-starts: reviewer-order waits: all configured reviewers refused', file=sys.stderr)
                return 1
            for c in choices:
                print(_format_flags(c))
            return 0
        elif len(args) == 5 and args[:2] == ['loop-agent', '--repo']:
            if not REPO.fullmatch(args[2]) or not LOOP.fullmatch(args[3]):
                raise ValueError('a repository and a loop id are required')
            text = sys.stdin.read() if args[4] == '-' else Path(args[4]).read_text()
            update = loop_agent(read_models(read_fleet(args[2])), json.loads(text, object_pairs_hook=records.unique),
                                args[3])
            print('current' if update is None else 'stale: ' + update)
            return 0 if update is None else 1
        elif len(args) == 2 and args[0] == 'report':
            out = [report(json.loads(Path(args[1]).read_text(), object_pairs_hook=records.unique))]
        else:
            print('usage: ops-starts.py pass WORLD.json [--bench BENCH.json] | flags --repo OWNER/REPO [START] | '
                  'host --repo OWNER/REPO START | '
                  'loop-agent --repo OWNER/REPO LOOP_ID LIST.json|- | report BENCH.json', file=sys.stderr)
            return 2
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'ops-starts: refused: {error}', file=sys.stderr)
        return 2
    for item in out:
        print(json.dumps(item, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
