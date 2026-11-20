#!/usr/bin/env python3
"""write-driver's mechanics, under contracts/write-driver.v1.md (openwiz.write-driver.v1).

    write_driver.py begin --state <dir>
    write_driver.py host --state <dir> --host <host> --costly yes|no
    write_driver.py copy --state <dir> --openwiz <checkout> --into <repository folder> --login machine|host
                        [--key-variable <NAME>]
    write_driver.py ticket --host <host> --account <login> --out <folder>
    write_driver.py ask --state <dir> --operation kit|expired-login|host [--step <host step>] --effect <effect>
    write_driver.py reply --state <dir> --file <the user's next message>
    write_driver.py sign-in --state <dir> --harness <harness>
    write_driver.py kit --state <dir> --openwiz <checkout> --driver <program> --repo <owner/name> --ticket <n>
                        --harness <h> --model <m> [--skill <s>] [--wait <seconds>] [--asked <ask id>]
    write_driver.py lesson live-shape --state <dir> --live <file> --fixture <file>
    write_driver.py lesson wake-after-turn --state <dir> --turn-ended yes|no --wake answered|error
                        --note-edited yes|no --second-note yes|no
    write_driver.py lesson expired-login --state <dir> --driver <program> --harness <h> [--asked <ask id>]
    write_driver.py started run --state <dir> --driver <program> --run <run id>
    write_driver.py started add --state <dir> --what <what> -- <its stop command...>
    write_driver.py stop-all --state <dir>
    write_driver.py report --state <dir> [--pr <pull request url>]
    write_driver.py share offer --state <dir>
    write_driver.py share reply --state <dir> --file <the user's next message>

Every exact text comes from the contract's one `write-driver-v1` block. The run's state is one owner-only
JSON file, <dir>/run.json. Exit 0: done; 1: refused (the last line says why), or a kit check failed;
2: the kit could not run; 3: skipped on the user's no. It never reads, asks for, prints or stores a login, token or key: GitHub is
reached only through the user's own signed-in `gh`. The kit reaches the driver through `proxy`, which
records each run its `start` answers, once the kit's own checks accept that answer, for stop-all. The
expired-login probe runs the driver under Landlock and seccomp, or not at all, so on macOS it alone is skipped.
Python 3.9+, standard library, Linux or macOS.
"""
import argparse
import ctypes
import importlib.util
import json
import math
import os
import re
import shlex
import signal
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True
CONTRACT = Path(__file__).resolve().parents[3] / 'contracts' / 'write-driver.v1.md'
REPOSITORY = 'openwizdev/OpenWiz'
DRIVER_TIMES = 1966  # the pinned "Driver times" issue on openwizdev/OpenWiz: checked, never searched for
# A credential word, even joined to others by `_`, `-` or digits (`EXAMPLE_API_TOKEN`): the contract's W1.
CREDENTIAL = re.compile(r'(?i)(?<![a-z])(?:logins?|tokens?|keys?|apikeys?|passwords?|passphrases?|secrets?'
                        r'|credentials?|cookies?|pats?|oauth|bearer)(?![a-z])')
YES = re.compile(r'(?i)\s*(?:yes|y|yeah|yep|yes please|go ahead)[.!]?\s*')
# The template's own names, each renamed for the host in a copy; a template without one is refused.
RENAMES = (("'driver': 'template'", "'driver': '{host}'"),
           ('OPENWIZ_TEMPLATE_STATE', 'OPENWIZ_{env}_STATE'),
           ('openwiz-template', 'openwiz-{host}'))


class Refused(Exception):
    pass


# --- the contract's forms -------------------------------------------------------------------------------

_FORMS = None


def forms():
    """The contract's `write-driver-v1` block."""
    global _FORMS
    if _FORMS is None:
        text = CONTRACT.read_text(encoding='utf-8')
        blocks = re.findall(r'^```write-driver-v1\n(.*?)^```$', text, re.M | re.S)
        if len(blocks) != 1:
            raise Refused('contracts/write-driver.v1.md has no single write-driver-v1 block')
        _FORMS = json.loads(blocks[0])
    return _FORMS


def pattern(name):
    """A form's regex: literal text, each `<field>` its field's pattern, a repeat the same value."""
    b = forms()
    out, seen = [], set()
    for i, part in enumerate(re.split(r'<([a-z]+)>', b[name])):
        if i % 2 == 0:
            out.append(re.escape(part))
        elif part in seen:
            out.append('(?P=%s)' % part)
        else:
            seen.add(part)
            out.append('(?P<%s>%s)' % (part, b['fields'][part]))
    return re.compile(''.join(out))


def render(name, **values):
    """A form with its values, refused unless it reads back whole as that form."""
    text = re.sub(r'<([a-z]+)>', lambda m: values[m[1]], forms()[name])
    if not pattern(name).fullmatch(text):
        raise Refused('a value does not fit the contract\'s %s form' % name)
    return text


def field(name, value):
    return bool(re.fullmatch(forms()['fields'][name], value))


class _Repeated(ValueError):
    pass


def strict(text):
    def pairs(items):
        if len({k for k, _ in items}) != len(items):
            raise _Repeated
        return dict(items)
    return json.loads(text, object_pairs_hook=pairs)


def minutes_of(time_text):
    return int(time_text.split(' ')[0])


def read_copy(text):
    return {'result': 'valid'} if text == forms()['copy_line'] else {'result': 'invalid', 'code': 'copy-line'}


def read_fleet(text):
    m = pattern('fleet_file').fullmatch(text)
    return {'result': 'valid', 'account': m['account']} if m else {'result': 'invalid', 'code': 'fleet-file'}


def read_ticket(text):
    try:
        t = strict(text)
    except ValueError:
        t = None
    if (not isinstance(t, dict) or set(t) != {'title', 'body', 'labels'} or not isinstance(t['title'], str)
            or not isinstance(t['body'], str) or not isinstance(t['labels'], list)
            or not all(isinstance(x, str) for x in t['labels'])):
        return {'result': 'invalid', 'code': 'ticket-fields'}
    title = pattern('ticket_title').fullmatch(t['title'])
    body = pattern('ticket_body').fullmatch(t['body'])
    if not title or not body or title['host'] != body['host']:
        return {'result': 'invalid', 'code': 'ticket-text'}
    if sorted(t['labels']) != sorted(forms()['ticket_labels']):
        return {'result': 'invalid', 'code': 'ticket-labels'}
    return {'result': 'valid', 'host': title['host']}


def read_start(text):
    m = pattern('start_record').fullmatch(text)
    return {'result': 'valid', 'host': m['host']} if m else {'result': 'invalid', 'code': 'start-record'}


def read_ask(text):
    for kind in ('ask', 'sign_in'):
        m = pattern(kind).fullmatch(text)
        if m:
            if kind == 'ask' and CREDENTIAL.search(m['step']):
                return {'result': 'invalid', 'code': 'credential'}
            if kind == 'ask':
                return {'result': 'valid', 'kind': 'cost-or-machine', 'effect': m['effect']}
            return {'result': 'valid', 'kind': 'sign-in'}
    return {'result': 'invalid', 'code': 'ask-form'}


def shape(value, at=()):
    """A JSON reply's leaves, each its path (keys and items kept apart) and type, never its value."""
    if isinstance(value, dict):
        if not value:
            return [json.dumps([list(at), 'empty object'])]
        return sorted(p for k, v in value.items() for p in shape(v, at + (('key', k),)))
    if isinstance(value, list):
        if not value:
            return [json.dumps([list(at), 'empty array'])]
        return sorted({p for v in value for p in shape(v, at + (('item',),))})
    kind = {bool: 'bool', int: 'number', float: 'number', str: 'string', type(None): 'null'}[type(value)]
    return [json.dumps([list(at), kind])]


def skeleton(text):
    return [re.sub(r'[A-Za-z0-9._-]+', 'w', line) for line in text.split('\n')]


def read_lesson(text):
    try:
        r = strict(text)
    except ValueError:
        r = None
    name = r.get('lesson') if isinstance(r, dict) else None
    text_or_json = lambda v: isinstance(v, (str, dict, list))  # noqa: E731
    flag = lambda v: isinstance(v, bool)  # noqa: E731
    fields = {'live-shape': {'lesson': str, 'live': text_or_json, 'fixture': text_or_json},
              'wake-after-turn': {'lesson': str, 'turn_ended': flag, 'wake': lambda v: v in ('answered', 'error'),
                                  'note_edited': flag, 'second_note': flag},
              'expired-login': {'lesson': str, 'exit': lambda v: type(v) is int, 'left_running': flag,
                                'answer': lambda v: isinstance(v, dict) and all(isinstance(x, str)
                                                                                for x in v.values())}}
    want = fields.get(name) if name in forms()['lessons'] else None
    if not want or set(r) != set(want) or not all(
            (isinstance(r[k], t) if isinstance(t, type) else t(r[k])) for k, t in want.items()):
        return {'result': 'invalid', 'code': 'lesson-fields'}
    fail = lambda code: {'result': 'fail', 'code': code}  # noqa: E731
    if name == 'live-shape':
        if isinstance(r['live'], str) != isinstance(r['fixture'], str):
            return fail('shape-differs')
        same = (skeleton(r['live']) == skeleton(r['fixture']) if isinstance(r['live'], str)
                else shape(r['live']) == shape(r['fixture']))
        return {'result': 'pass'} if same else fail('shape-differs')
    if name == 'wake-after-turn':
        if not r['turn_ended']:
            return fail('turn-still-running')
        if r['wake'] != 'answered' or not r['note_edited']:
            return fail('not-woken')
        return fail('second-note') if r['second_note'] else {'result': 'pass'}
    answer = r['answer']
    if r['exit'] == 0:
        return fail('silent-start')
    if (r['exit'] != 1 or set(answer) != {'error', 'next'} or not field('error', answer['error'])
            or not pattern('sign_in_next').fullmatch(answer['next'])):
        return fail('no-sign-in-next')
    return fail('left-running') if r['left_running'] else {'result': 'pass'}


def results_line(lead, names, line):
    alt = '|'.join(map(re.escape, forms()['results']))
    m = re.fullmatch(re.escape(lead) + ': ' + ', '.join('%s (%s)' % (re.escape(n), alt) for n in names), line)
    return list(m.groups()) if m else None


def read_report(text):
    b, lines = forms(), text.split('\n')
    bad = {'result': 'invalid', 'code': 'report-form'}
    passed = pattern('report_passed').fullmatch(lines[0])
    reached = pattern('report_not_passing').fullmatch(lines[0])
    if not (passed or reached) or len(lines) != (5 if passed else 4):
        return bad
    kit = results_line('Kit', b['checks'], lines[1])
    lessons = results_line('Live lessons', b['lessons'], lines[2])
    stopped = pattern('stopped').fullmatch(lines[3])
    if kit is None or lessons is None or not (stopped or pattern('not_stopped').fullmatch(lines[3])):
        return bad
    if passed and not pattern('pull_request').fullmatch(lines[4]):
        return bad
    every = kit.count('pass') == len(kit) and lessons.count('pass') == len(lessons)
    if passed and not every:
        return {'result': 'invalid', 'code': 'report-not-passing'}
    if reached and (every or int(reached['k']) != kit.count('pass')):
        return {'result': 'invalid', 'code': 'report-count'}
    m = passed or reached
    return {'result': 'passed' if passed else 'not-passing', 'host': m['host'], 'minutes': minutes_of(m['time']),
            'stopped': bool(stopped), 'share_offer': bool(passed and stopped)}


def read_share(text):
    m = pattern('share_line').fullmatch(text)
    return {'result': 'valid', 'host': m['host'], 'minutes': minutes_of(m['time'])} if m else \
        {'result': 'refused', 'code': 'share-line'}


def read_preview(text):
    m = pattern('share_preview').fullmatch(text)
    if not m:
        return {'result': 'refused', 'code': 'share-preview'}
    return {'result': 'valid', 'issue': int(m['issue']), 'account': m['account'], 'host': m['host'],
            'minutes': minutes_of(m['time'])}


def explicit_yes(text):
    """The user's next message is an explicit yes: a plain yes and nothing else. Anything else is a no."""
    return bool(YES.fullmatch(text))


# --- the run's state ------------------------------------------------------------------------------------

def load(folder, host=True):
    path = Path(folder) / 'run.json'
    try:
        state = json.loads(path.read_text())
    except FileNotFoundError:
        raise Refused('no run in %s: run `begin` at paste first' % folder)
    if host and state['host'] is None:
        raise Refused('name the host first: `host --host <host> --costly yes|no`')
    return state


def save(folder, state):
    folder = Path(folder)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    new = folder / 'run.json.new'
    fd = os.open(new, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(state, f, indent=1)
    os.replace(new, folder / 'run.json')


def passing(state):
    return (all(state['kit'].get(c) == 'pass' for c in forms()['checks'])
            and all(state['lessons'].get(n) == 'pass' for n in forms()['lessons']))


def changed(state):
    """Evidence or tracked resources changed: the report and any share waiting for its yes no longer hold."""
    state['report'] = None
    if state['share'] and state['share']['state'] == 'previewed':
        state['share'] = None


def mark_clock(state):
    """The clock stops when the last of the kit's five checks and three lessons passes."""
    changed(state)
    if passing(state):
        state['passed_at'] = state.get('passed_at') or time.time()
    else:
        state['passed_at'] = None


def elapsed(state):
    seconds = (state.get('passed_at') or time.time()) - state['paste']
    n = max(1, math.ceil(seconds / 60))
    return '1 minute' if n == 1 else '%d minutes' % n


def consent(state, ask_id, operation):
    """None to go ahead; 'skip' on the user's no. Refused when a costly step has no answered ask."""
    if not state['costly'] and ask_id is None:
        return None
    if ask_id is None:
        raise Refused('this step on %s may cost money or start a machine: ask first (`ask`), then pass --asked'
                      % state['host'])
    ask = next((a for a in state['asks'] if a['id'] == ask_id), None)
    if ask is None:
        raise Refused('no ask %s' % ask_id)
    if ask['operation'] != operation:
        raise Refused('ask %s is not an ask for this step: it asked to %s; ask for this one (`ask --operation %s`)'
                      % (ask_id, ask['step'], operation))
    if ask['answer'] is None:
        raise Refused('ask %s has no answer yet: wait for the user\'s next message, then run `reply`' % ask_id)
    if ask['used']:
        raise Refused('ask %s already covered one step: one ask covers one step, so ask again' % ask_id)
    ask['used'] = True
    return None if ask['answer'] == 'yes' else 'skip'


# --- commands -------------------------------------------------------------------------------------------

def cmd_begin(a):
    if (Path(a.state) / 'run.json').exists():
        print('resuming: the clock started at paste')
        return 0
    save(a.state, {'host': None, 'costly': None, 'paste': time.time(), 'passed_at': None, 'kit': {},
                   'lessons': {}, 'asks': [], 'started': [], 'stop_all': False, 'report': None, 'share': None})
    print('clock started at paste')
    return 0


def cmd_host(a):
    state = load(a.state, host=False)
    if not field('host', a.host):
        raise Refused('%s is not a host name: 1 to 40 lower-case letters, digits or -, starting with a letter '
                      'and not ending with -' % a.host)
    if state['host'] not in (None, a.host):
        raise Refused('this run is for %s: one run, one host' % state['host'])
    state['host'], state['costly'] = a.host, a.costly == 'yes'
    save(a.state, state)
    print('host %s: %s' % (a.host, 'every costly or machine-starting step asks first' if state['costly']
                           else 'no step costs money or starts a machine'))
    return 0


# Driver v1's login line: where the user's login lives, right under the README's title.
LOGIN = {'machine': 'Login: stays on your machine', 'host': 'Login: held by {host}'}


KEY_VARIABLE = re.compile(r'[A-Z][A-Z0-9_]{0,63}')


def login_line(readme, line, key_variable=None):
    """Open the README, right under its title, with exactly this login line, and no other; for a cloud host that
    takes an API key, the name of the variable the user sets for it under that line, never a value."""
    lines = readme.read_text(encoding='utf-8').split('\n') if readme.exists() else []
    if not lines or not lines[0].startswith('# '):
        raise Refused('the template README.md has no title to put the login line under: write it by hand')
    rest = [x for x in lines[1:] if not x.startswith(('Login:', 'API key:'))]
    while rest and not rest[0].strip():
        rest.pop(0)
    key = ['API key: set `%s` yourself; the driver never asks for it.' % key_variable, ''] if key_variable else []
    readme.write_text('\n'.join([lines[0], '', line, ''] + key + rest), encoding='utf-8')


def cmd_copy(a):
    state = load(a.state)
    host = state['host']
    if a.key_variable is not None and (a.login != 'host' or not KEY_VARIABLE.fullmatch(a.key_variable)):
        raise Refused('the key variable is a name only (capital letters, digits and _), for a login the host '
                      'holds: never a value')
    src = Path(a.openwiz) / 'adapters' / 'template'
    dest = Path(a.into) / 'adapters' / host
    if dest.exists():
        raise Refused('%s already exists: the copy never overwrites it' % dest)
    driver = (src / 'driver').read_text(encoding='utf-8')
    for old, _ in RENAMES:
        if old not in driver:
            raise Refused('the template no longer has %s: copy and rename it by hand' % old)
    values = {'host': host, 'env': host.upper().replace('-', '_')}
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix='.write-driver-', dir=dest.parent))
    try:
        shutil.copytree(src, tmp / host, ignore=shutil.ignore_patterns('evidence', '__pycache__'))
        for path in sorted((tmp / host).rglob('*')):
            if not path.is_file() or path.name == 'schema.json':
                continue  # schema.json stays byte for byte the kit's
            try:
                text = path.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                continue
            new = text.replace('adapters/template/', 'adapters/%s/' % host)
            for old, to in RENAMES:
                new = new.replace(old, to.format(**values))
            if new != text:
                path.write_text(new, encoding='utf-8')
        login_line(tmp / host / 'README.md', LOGIN[a.login].format(host=host), a.key_variable)
        os.replace(tmp / host, dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('copied adapters/template to %s, renamed for %s' % (dest, host))
    return 0


def cmd_ticket(a):
    if not field('host', a.host) or not field('account', a.account):
        raise Refused('the host or account is not a valid name')
    out = Path(a.out)
    (out / 'docs' / 'agents').mkdir(parents=True, exist_ok=True)
    (out / 'docs' / 'agents' / 'fleet.md').write_text(render('fleet_file', account=a.account))
    (out / 'ticket.json').write_text(json.dumps({'title': render('ticket_title', host=a.host),
                                                 'body': render('ticket_body', host=a.host),
                                                 'labels': forms()['ticket_labels']}, indent=1) + '\n')
    (out / 'start-record.md').write_text(render('start_record', host=a.host))
    print('wrote %s, %s and %s' % (out / 'docs/agents/fleet.md', out / 'ticket.json', out / 'start-record.md'))
    return 0


# The steps this script runs itself, each asked for in these exact words; any other host step is `host`.
OPERATIONS = {'kit': 'run the driver kit', 'expired-login': 'run the expired sign-in check with your driver'}


def cmd_ask(a):
    state = load(a.state)
    if a.operation in OPERATIONS:
        if a.step:
            raise Refused('the %s step is asked for in its own words: drop --step' % a.operation)
        step = OPERATIONS[a.operation]
    elif not a.step:
        raise Refused('name the one host step in plain words: --step')
    else:
        step = a.step
    if CREDENTIAL.search(step):
        raise Refused('refused (credential): an ask never names a login, token or key, so it is never shown')
    text = render('ask', step=step, host=state['host'], effect=a.effect)
    if read_ask(text)['result'] != 'valid':
        raise Refused('refused (ask-form): that ask does not fit the contract')
    ask_id = 'ask-%d' % (len(state['asks']) + 1)
    state['asks'].append({'id': ask_id, 'operation': a.operation, 'step': step, 'effect': a.effect,
                          'answer': None, 'used': False})
    save(a.state, state)
    print(text)
    return 0


def cmd_reply(a):
    state = load(a.state)
    pending = [x for x in state['asks'] if x['answer'] is None]
    if not pending:
        raise Refused('no ask is waiting for an answer')
    pending[-1]['answer'] = 'yes' if explicit_yes(Path(a.file).read_text(encoding='utf-8')) else 'no'
    for older in pending[:-1]:
        older['answer'] = 'no'  # an answer goes to the latest ask only; an older one never gets a later yes
    save(a.state, state)
    print('%s: %s' % (pending[-1]['id'], pending[-1]['answer']))
    return 0


def cmd_sign_in(a):
    state = load(a.state)
    print(render('sign_in', harness=a.harness, host=state['host']))
    return 0


KIT_LINE = re.compile(r'(pass|fail) (version|start|wake|stop|token): .*')


def cmd_kit(a):
    state = load(a.state)
    checks = forms()['checks']
    if consent(state, a.asked, 'kit') == 'skip':
        state['kit'] = {c: 'not run' for c in checks}
        mark_clock(state)
        save(a.state, state)
        print('skipped on your no: Kit: ' + ', '.join('%s not run' % c for c in checks))
        return 3
    state['kit'] = {}  # a rerun proves nothing until it reads: no earlier result survives it
    mark_clock(state)
    save(a.state, state)
    # The kit calls the driver through this proxy, so every run its `start` answers is recorded for stop-all,
    # even when the kit's start check then fails and it never stops that run itself.
    proxy = Path(a.state) / 'kit-driver'
    proxy.write_text('#!/bin/sh\nexec %s -I %s proxy --state %s --openwiz %s --driver %s "$@"\n' % tuple(
        shlex.quote(x) for x in (sys.executable, os.path.abspath(__file__), os.path.abspath(a.state),
                                 os.path.abspath(a.openwiz), os.path.abspath(a.driver))))
    proxy.chmod(0o700)
    argv = [sys.executable, '-I', str(Path(a.openwiz) / 'kernel' / 'driver-kit' / 'kit.py'), '--driver',
            str(proxy), '--repo', a.repo, '--ticket', str(a.ticket), '--harness', a.harness, '--model', a.model,
            '--skill', a.skill, '--wait', str(a.wait)]
    try:
        p = subprocess.run(argv, capture_output=True, text=True)
    except OSError as e:
        print('the kit could not run: %s' % e.strerror)
        return 2
    sys.stdout.write(p.stdout)
    state = load(a.state)  # the proxy recorded what the kit's runs started
    lines = p.stdout.rstrip('\n').split('\n') if p.stdout.strip() else []
    found = [KIT_LINE.fullmatch(line) for line in lines]
    names = [m[2] for m in found if m]
    results = {m[2]: m[1] for m in found if m}
    if (p.returncode not in (0, 1) or not all(found) or names != checks
            or (p.returncode == 0) != all(r == 'pass' for r in results.values())):
        why = (p.stderr.strip().split('\n') or [''])[-1]
        print('the kit could not run, so nothing is recorded%s' % (': ' + why if why else ''))
        return 2
    state['kit'] = results
    mark_clock(state)
    save(a.state, state)
    print('Kit: ' + ', '.join('%s %s' % (c, results[c]) for c in checks))
    return 0 if p.returncode == 0 else 1


def kit_checks(openwiz):
    """The kit's own credential and schema checks, imported from the kit it runs: nothing is copied to drift."""
    path = Path(openwiz) / 'kernel' / 'driver-kit' / 'kit.py'
    spec = importlib.util.spec_from_file_location('openwiz_driver_kit', str(path))
    kit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kit)
    return kit


def kit_run(openwiz, out, err):
    """The run a `start` answer names, only when the kit itself would read that answer: no credential in what
    the driver printed, in any decoded string or key, and the schema's start answer. Else None."""
    try:
        kit = kit_checks(openwiz)
        out, err = out.decode('utf-8'), err.decode('utf-8')
        if kit.holds_credential(out + err):
            return None
        value = kit.parse(out)
        if any(kit.holds_credential(text) for text in kit.texts(value)):
            return None
        if kit.invalid(value, kit.load_schema()['commands']['start']['output']) is not None:
            return None
        return value['run']
    except Exception:  # a kit or answer it can't read keeps nothing of the answer
        return None


def cmd_proxy(a):
    """The kit's view of the driver: the driver itself, byte for byte, recording each run `start` answers.
    Nothing of an answer enters state until the kit's own checks accept it; a run whose answer they refuse is
    kept without its id, as one the user must stop on the host."""
    request = sys.stdin.buffer.read()
    p = subprocess.run([a.driver, *a.args], input=request, capture_output=True)
    if a.args == ['start'] and p.returncode == 0:
        run = kit_run(a.openwiz, p.stdout, p.stderr)
        if run is None:
            item = {'what': 'a driver run the kit started, whose start answer the kit refuses, so its id is not '
                            'kept', 'argv': [], 'stdin': '', 'stopped': False}
        else:
            item = {'what': 'driver run %s (started by the kit)' % run, 'argv': [a.driver, 'stop'],
                    'stdin': json.dumps({'run': run}), 'stopped': False}
        state = load(a.state)
        state['started'].append(item)
        state['stop_all'] = False
        changed(state)
        save(a.state, state)
    sys.stdout.buffer.write(p.stdout)
    sys.stderr.buffer.write(p.stderr)
    return p.returncode


def record_lesson(folder, state, record, expect_next=None):
    reading = read_lesson(json.dumps(record))
    if reading['result'] == 'invalid':
        raise Refused('that lesson record does not fit the contract (lesson-fields)')
    if reading['result'] == 'pass' and expect_next is not None and record['answer']['next'] != expect_next:
        reading = {'result': 'fail', 'code': 'no-sign-in-next'}  # a sign-in step for another harness or host
    state['lessons'][record['lesson']] = reading['result']
    mark_clock(state)
    save(folder, state)
    print('%s %s%s' % (record['lesson'], reading['result'], ': ' + reading['code'] if 'code' in reading else ''))
    return 0


def reply_text(path):
    text = Path(path).read_text(encoding='utf-8')
    try:
        value = json.loads(text)
        if isinstance(value, (dict, list)):
            return value
    except ValueError:
        pass
    return text[:-1] if text.endswith('\n') else text


def descendants():
    """Live processes under this one: what the probe's driver started, wherever its session went, since this
    process is their subreaper. It reads only each process's parent from /proc/<pid>/stat, never an environment."""
    while True:  # reap what has already exited here
        try:
            if os.waitpid(-1, os.WNOHANG)[0] == 0:
                break
        except ChildProcessError:
            break
    parents = {}
    for pid in filter(str.isdigit, os.listdir('/proc')):
        try:
            with open('/proc/%s/stat' % pid) as f:
                fields = f.read().rpartition(')')[2].split()
        except OSError:
            continue
        if fields[0] != 'Z':
            parents.setdefault(int(fields[1]), []).append(int(pid))
    found, todo = set(), [os.getpid()]
    while todo:
        for child in parents.get(todo.pop(), []):
            if child not in found:
                found.add(child)
                todo.append(child)
    return found


# --- the expired-login probe's isolation ----------------------------------------------------------------
# The driver under test runs under Landlock (it reads and runs only the system's programs and its own folder,
# writes only its box, and traces no process outside it) and a seccomp filter (no socket of any kind, no
# io_uring): no network, no host socket, no user file, no other process's environment. Where the kernel can't
# apply both, the probe refuses and runs nothing.
# Per architecture: its seccomp audit value and the numbers of socket, socketpair and io_uring_setup.
SYSCALLS = {'x86_64': (0xC000003E, (41, 53, 425)), 'aarch64': (0xC00000B7, (198, 199, 425))}
LANDLOCK_CREATE, LANDLOCK_ADD, LANDLOCK_RESTRICT = 444, 445, 446
READ = 1 | 4 | 8  # execute, read a file, read a folder
SYSTEM = ('/usr', '/bin', '/sbin', '/lib', '/lib32', '/lib64', '/etc')


def syscall(*args):
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    r = libc.syscall(*(a if isinstance(a, ctypes.c_char_p) else ctypes.c_long(a) for a in args))
    if r < 0:
        e = ctypes.get_errno()
        raise OSError(e, os.strerror(e))
    return r


def landlock_abi():
    """The kernel's Landlock version, or 0 when it has none."""
    try:
        return syscall(LANDLOCK_CREATE, 0, 0, 1)
    except OSError:
        return 0


def isolation(box, driver):
    """What runs in the probe's child before it becomes the driver, or Refused when this system can't isolate it."""
    abi, arch = landlock_abi(), SYSCALLS.get(os.uname().machine)
    if abi < 1 or arch is None:
        raise Refused('this system cannot isolate the expired-login probe (it needs Linux Landlock on x86_64 or '
                      'aarch64), so it runs nothing: check that lesson on a machine that can')
    # Each right this kernel's Landlock knows: refer (2), truncate (3), device ioctl (5); TCP (4) and the
    # abstract-socket and signal scopes (6) on top of the seccomp filter's ban on every socket.
    fs = (1 << 13) - 1 | (1 << 13 if abi >= 2 else 0) | (1 << 14 if abi >= 3 else 0) | (1 << 15 if abi >= 5 else 0)
    attr = struct.pack('=QQQ', fs, 3 if abi >= 4 else 0, 3 if abi >= 6 else 0)
    attr = attr[:8 if abi < 4 else 16 if abi < 6 else 24]
    reads = sorted({str(Path(x).resolve()) for x in SYSTEM + (sys.base_prefix, os.path.dirname(driver), '/proc',
                                                              '/dev') if os.path.isdir(x)})
    rules = [(x, READ if x != '/dev' else 4 | 8) for x in reads]
    rules += [('/dev/null', (2 | 4 | 1 << 14) & fs), (str(box), fs)]
    audit, (socket, pair, uring) = arch
    ld, jeq, jge, ret = 0x20, 0x15, 0x35, 0x06
    allow, refuse, kill = 0x7fff0000, 0x00050000 | 1, 0x80000000  # 1: EPERM
    program = [(ld, 0, 0, 4), (jeq, 0, 7, audit), (ld, 0, 0, 0), (jge, 5, 0, 0x40000000), (jeq, 3, 0, socket),
               (jeq, 2, 0, pair), (jeq, 1, 0, uring), (ret, 0, 0, allow), (ret, 0, 0, refuse), (ret, 0, 0, kill)]
    filters = ctypes.create_string_buffer(b''.join(struct.pack('=HBBI', *i) for i in program))
    fprog = ctypes.create_string_buffer(struct.pack('=HxxxxxxQ', len(program), ctypes.addressof(filters)))
    keep = (filters, fprog)  # fprog points into filters: both live as long as enter

    def enter():
        libc = ctypes.CDLL(None, use_errno=True)
        ruleset = syscall(LANDLOCK_CREATE, ctypes.c_char_p(attr), len(attr), 0)
        for path, access in rules:
            fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            syscall(LANDLOCK_ADD, ruleset, 1, ctypes.c_char_p(struct.pack('=Qi', access, fd)), 0)
            os.close(fd)
        if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
            raise OSError(ctypes.get_errno(), 'no_new_privs')
        syscall(LANDLOCK_RESTRICT, ruleset, 0)
        # PR_SET_SECCOMP, SECCOMP_MODE_FILTER
        if libc.prctl(22, 2, ctypes.c_void_p(ctypes.addressof(keep[1])), 0, 0) != 0:
            raise OSError(ctypes.get_errno(), 'seccomp')
    return enter


STAND_IN = """#!/bin/sh
# write-driver's stand-in harness: its first turn ends at once on an expired sign-in. It is not the user's harness.
: > %s
echo "Your sign-in has expired. Please sign in again to continue."
echo "Your sign-in has expired. Please sign in again to continue." >&2
exit 1
"""


def cmd_lesson(a):
    state = load(a.state)
    if a.lesson == 'live-shape':
        return record_lesson(a.state, state, {'lesson': 'live-shape', 'live': reply_text(a.live),
                                              'fixture': reply_text(a.fixture)})
    if a.lesson == 'wake-after-turn':
        return record_lesson(a.state, state, {'lesson': 'wake-after-turn', 'turn_ended': a.turn_ended == 'yes',
                                              'wake': a.wake, 'note_edited': a.note_edited == 'yes',
                                              'second_note': a.second_note == 'yes'})
    # expired-login: the driver's own `start`, against its own test fixtures, with a stand-in harness that ends
    # its first turn on a sign-in line. Nothing of the caller's reaches it: an empty home, a PATH of the stand-in,
    # the driver's fixtures and the system's programs, its own state folder, and no other variable; and the
    # kernel lets it reach nothing outside its box (isolation, above).
    if not field('harness', a.harness):
        raise Refused('%s is not a harness name: 1 to 40 lower-case letters, digits or -, starting with a letter'
                      % a.harness)
    if sys.platform == 'darwin':  # Landlock, seccomp and /proc are Linux's: on a Mac only this probe is skipped
        state['lessons']['expired-login'] = 'not run'
        mark_clock(state)
        save(a.state, state)
        print('expired-login not run: this Mac cannot isolate the probe (it needs Linux), so it is skipped; check '
              'that lesson on Linux')
        return 3
    if consent(state, a.asked, 'expired-login') == 'skip':
        state['lessons']['expired-login'] = 'not run'
        mark_clock(state)
        save(a.state, state)
        print('expired-login not run: skipped on your no')
        return 3
    save(a.state, state)
    driver = os.path.abspath(a.driver)
    box = Path(tempfile.mkdtemp(prefix='write-driver-probe-'))
    try:
        for name in ('bin', 'home', 'state'):
            (box / name).mkdir(mode=0o700)
        ran = box / 'ran'
        fd = os.open(box / 'bin' / a.harness, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
        with os.fdopen(fd, 'w') as f:
            f.write(STAND_IN % shlex.quote(str(ran)))
        env = {'PATH': os.pathsep.join([str(box / 'bin'), os.path.join(os.path.dirname(driver), 'fixtures'),
                                        '/usr/local/bin', '/usr/bin', '/bin']),
               'HOME': str(box / 'home'), 'LANG': 'C.UTF-8',
               'OPENWIZ_%s_STATE' % state['host'].upper().replace('-', '_'): str(box / 'state')}
        enter = isolation(box, driver)
        ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0)  # PR_SET_CHILD_SUBREAPER: keep what it starts
        request = {'repository': 'example-user/%s-driver-kit' % state['host'], 'ticket': 1,
                   'skill': 'build-ticket', 'harness': a.harness, 'model': 'stand-in'}
        try:
            p = subprocess.run([driver, 'start'], input=json.dumps(request), env=env, capture_output=True,
                               text=True, timeout=300, cwd=str(box / 'home'), preexec_fn=enter)
        except subprocess.SubprocessError as e:
            if isinstance(e, subprocess.TimeoutExpired):
                raise
            raise Refused('the expired-login probe could not isolate the driver, so it ran nothing')
        try:
            answer = json.loads(p.stdout)
        except ValueError:
            answer = {'error': 'the driver printed no JSON'}
        if not isinstance(answer, dict):
            answer = {'error': 'the driver printed no JSON object'}
        if p.returncode == 0 and isinstance(answer.get('run'), str):
            # It answered a run its first turn never keeps: stop it, as everything this skill started.
            subprocess.run([driver, 'stop'], input=json.dumps({'run': answer['run']}), env=env,
                           capture_output=True, text=True, timeout=300, cwd=str(box / 'home'), preexec_fn=enter)
        deadline = time.monotonic() + 5
        while descendants() and time.monotonic() < deadline:
            time.sleep(0.1)
        left = descendants()
        for pid in left:  # stop what it left, and say it was left
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        descendants()
        if not ran.exists():
            raise Refused('the driver never ran the stand-in harness %s, so this proves nothing: make `start` run '
                          'the harness by its name on PATH, then check again' % a.harness)
    finally:
        shutil.rmtree(box, ignore_errors=True)
    answer = {k: v if isinstance(v, str) else json.dumps(v) for k, v in answer.items()}
    return record_lesson(a.state, state, {'lesson': 'expired-login', 'exit': p.returncode, 'answer': answer,
                                          'left_running': bool(left)},
                         expect_next=render('sign_in_next', harness=a.harness, host=state['host']))


def cmd_started(a):
    state = load(a.state)
    if a.kind == 'run':
        item = {'what': 'driver run %s' % a.run, 'argv': [str(Path(a.driver).resolve()), 'stop'],
                'stdin': json.dumps({'run': a.run}), 'stopped': False}
    else:
        argv = a.argv[1:] if a.argv[:1] == ['--'] else a.argv
        if not argv:
            raise Refused('name the command that stops it, after --')
        item = {'what': a.what, 'argv': argv, 'stdin': '', 'stopped': False}
    state['started'].append(item)
    state['stop_all'] = False
    changed(state)
    save(a.state, state)
    print('will stop: %s' % item['what'])
    return 0


def cmd_stop_all(a):
    state = load(a.state)
    left = []
    for item in reversed(state['started']):
        if item['stopped']:
            continue
        try:  # an item with no stop command is the user's to stop on the host
            p = item['argv'] and subprocess.run(item['argv'], input=item['stdin'], capture_output=True, text=True,
                                                timeout=300)
            item['stopped'] = bool(p) and p.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            item['stopped'] = False
        print('%s %s' % ('stopped' if item['stopped'] else 'still runs:', item['what']))
        if not item['stopped']:
            left.append(item)
    state['stop_all'] = True
    save(a.state, state)
    print(stopped_line(state))
    return 1 if left else 0


def stopped_line(state):
    left = [i for i in state['started'] if not i['stopped']]
    if not left:
        return render('stopped', count=str(len(state['started'])))
    what = '; '.join('%s (stop it with: %s)' % (i['what'], ' '.join(i['argv'])) if i['argv'] else
                     '%s (stop it on the host yourself)' % i['what'] for i in left)
    return render('not_stopped', what=what[:300])


def cmd_report(a):
    state = load(a.state)
    if not state['stop_all']:
        raise Refused('run `stop-all` first: the final report comes after everything it started is stopped')
    b, host, t = forms(), state['host'], elapsed(state)
    kit = [state['kit'].get(c, 'not run') for c in b['checks']]
    lessons = [state['lessons'].get(n, 'not run') for n in b['lessons']]
    ok = passing(state)
    if ok and not a.pr:
        raise Refused('a passing report ends with its pull request: pass --pr <url>')
    lines = [render('report_passed', host=host, time=t) if ok else
             render('report_not_passing', host=host, k=str(kit.count('pass')), time=t),
             'Kit: ' + ', '.join('%s %s' % x for x in zip(b['checks'], kit)),
             'Live lessons: ' + ', '.join('%s %s' % x for x in zip(b['lessons'], lessons)),
             stopped_line(state)]
    if ok:
        lines.append(render('pull_request', pr=a.pr))
    text = '\n'.join(lines)
    reading = read_report(text)
    if reading['result'] == 'invalid':
        raise Refused('the report does not fit the contract (%s)' % reading['code'])
    state['report'] = {'text': text, 'share_offer': reading['share_offer'], 'time': t}
    save(a.state, state)
    print(text)
    return 0


def gh(args, stdin=None):
    return subprocess.run(['gh', *args], input=stdin, capture_output=True, text=True, timeout=120)


DRIVER_TIMES_QUERY = '''query { repository(owner: "openwizdev", name: "OpenWiz") {
  issue(number: %d) { number title state }
  pinnedIssues(first: 3) { nodes { issue { number title state } } } } }''' % DRIVER_TIMES


def driver_times():
    """True when #1966 is the one open, pinned issue titled exactly `Driver times`."""
    p = gh(['api', 'graphql', '-f', 'query=' + DRIVER_TIMES_QUERY])
    try:
        repo = json.loads(p.stdout)['data']['repository']
        pinned = [n['issue'] for n in repo['pinnedIssues']['nodes']]
        issue = repo['issue']
    except (ValueError, KeyError, TypeError):
        return False
    times = [i for i in pinned if i['title'] == 'Driver times' and i['state'] == 'OPEN']
    return (p.returncode == 0 and bool(issue) and issue['title'] == 'Driver times' and issue['state'] == 'OPEN'
            and [i['number'] for i in times] == [DRIVER_TIMES])


def shareable(state):
    """The report a share may come from: current, passing, and after everything started was stopped."""
    report = state['report']
    if (not report or not report['share_offer'] or not passing(state) or not state['stop_all']
            or not all(i['stopped'] for i in state['started'])):
        return None
    return report


def account_now():
    """The signed-in gh's own account name, or None. Never a credential."""
    p = gh(['api', 'user', '--jq', '.login'])
    account = p.stdout.strip()
    return account if p.returncode == 0 and field('account', account) else None


def cmd_share(a):
    state = load(a.state)
    share = state['share']
    if a.step == 'offer':
        if share is not None:
            raise Refused('the share was already offered for this run: it is offered once')
        report = shareable(state)
        if not report:
            raise Refused('no share offer: only a current passing report, after everything it started was '
                          'stopped, offers one')
        if not driver_times():
            raise Refused("I can't find where driver times go, so I won't offer to share yours")
        account = account_now()
        if not account:
            raise Refused('your signed-in gh did not name its account, so there is no share offer')
        line = render('share_line', host=state['host'], time=report['time'])
        preview = render('share_preview', account=account, issue=str(DRIVER_TIMES), host=state['host'],
                         time=report['time'])
        if read_share(line)['result'] != 'valid' or read_preview(preview)['result'] != 'valid':
            raise Refused('the share does not fit the contract')
        state['share'] = {'state': 'previewed', 'line': line, 'account': account}
        save(a.state, state)
        print(preview)
        return 0
    if share is None or share['state'] != 'previewed':
        raise Refused('nothing is waiting for a yes: a share is posted once, only after its preview')
    if not explicit_yes(Path(a.file).read_text(encoding='utf-8')):
        share['state'] = 'declined'
        save(a.state, state)
        return 0
    # The yes was to that preview: post only if it still holds, as that account, to the pinned issue.
    report = shareable(state)
    line = report and render('share_line', host=state['host'], time=report['time'])
    if line != share['line'] or not driver_times() or account_now() != share['account']:
        state['share'] = None
        save(a.state, state)
        raise Refused('the account, the Driver times issue or the report changed since that preview, so nothing '
                      'was posted: it needs a fresh preview (`share offer`) and a fresh yes')
    share['state'] = 'posting'  # saved before the one attempt: never a second one
    save(a.state, state)
    try:
        p = gh(['issue', 'comment', str(DRIVER_TIMES), '--repo', REPOSITORY, '--body-file', '-'], stdin=share['line'])
    except (OSError, subprocess.TimeoutExpired):
        share['state'] = 'unknown'
        save(a.state, state)
        raise Refused('your gh did not answer, so it may or may not have posted; I won\'t retry: look at '
                      'openwizdev/OpenWiz#%d yourself' % DRIVER_TIMES)
    share['state'] = 'posted' if p.returncode == 0 else 'failed'
    save(a.state, state)
    if p.returncode != 0:
        raise Refused('your gh did not post it, and I won\'t retry; your time stays %s' % state['report']['time'])
    print('posted: %s' % share['line'])
    return 0


def parser():
    ap = argparse.ArgumentParser(prog='write_driver.py')
    sub = ap.add_subparsers(dest='command', required=True)

    def cmd(name, **kw):
        p = sub.add_parser(name, **kw)
        if name != 'ticket':
            p.add_argument('--state', required=True)
        return p

    cmd('begin')
    p = cmd('host')
    p.add_argument('--host', required=True)
    p.add_argument('--costly', choices=('yes', 'no'), required=True)
    p = cmd('copy')
    p.add_argument('--login', choices=tuple(LOGIN), required=True)
    p.add_argument('--key-variable')
    p.add_argument('--openwiz', required=True)
    p.add_argument('--into', required=True)
    p = cmd('ticket')
    p.add_argument('--host', required=True)
    p.add_argument('--account', required=True)
    p.add_argument('--out', required=True)
    p = cmd('ask')
    p.add_argument('--operation', required=True, choices=('kit', 'expired-login', 'host'))
    p.add_argument('--step')
    p.add_argument('--effect', required=True, choices=('cost money', 'start a machine',
                                                       'cost money and start a machine'))
    p = cmd('reply')
    p.add_argument('--file', required=True)
    p = cmd('sign-in')
    p.add_argument('--harness', required=True)
    p = cmd('kit')
    for name in ('--openwiz', '--driver', '--repo', '--harness', '--model'):
        p.add_argument(name, required=True)
    p.add_argument('--ticket', type=int, required=True)
    p.add_argument('--skill', default='build-ticket')
    p.add_argument('--wait', type=int, default=900)
    p.add_argument('--asked')
    p = sub.add_parser('lesson')
    lesson = p.add_subparsers(dest='lesson', required=True)
    q = lesson.add_parser('live-shape')
    q.add_argument('--live', required=True)
    q.add_argument('--fixture', required=True)
    q = lesson.add_parser('wake-after-turn')
    q.add_argument('--turn-ended', choices=('yes', 'no'), required=True)
    q.add_argument('--wake', choices=('answered', 'error'), required=True)
    q.add_argument('--note-edited', choices=('yes', 'no'), required=True)
    q.add_argument('--second-note', choices=('yes', 'no'), required=True)
    q = lesson.add_parser('expired-login')
    q.add_argument('--driver', required=True)
    q.add_argument('--harness', required=True)
    q.add_argument('--asked')
    for q in lesson.choices.values():
        q.add_argument('--state', required=True)
    p = sub.add_parser('started')
    started = p.add_subparsers(dest='kind', required=True)
    q = started.add_parser('run')
    q.add_argument('--driver', required=True)
    q.add_argument('--run', required=True)
    q = started.add_parser('add')
    q.add_argument('--what', required=True)
    q.add_argument('argv', nargs=argparse.REMAINDER)
    for q in started.choices.values():
        q.add_argument('--state', required=True)
    cmd('stop-all')
    p = cmd('proxy')
    p.add_argument('--openwiz', required=True)
    p.add_argument('--driver', required=True)
    p.add_argument('args', nargs=argparse.REMAINDER)
    p = cmd('report')
    p.add_argument('--pr')
    p = sub.add_parser('share')
    share = p.add_subparsers(dest='step', required=True)
    share.add_parser('offer').add_argument('--state', required=True)
    q = share.add_parser('reply')
    q.add_argument('--state', required=True)
    q.add_argument('--file', required=True)
    return ap


COMMANDS = {'begin': cmd_begin, 'host': cmd_host, 'copy': cmd_copy, 'ticket': cmd_ticket, 'ask': cmd_ask, 'reply': cmd_reply,
            'sign-in': cmd_sign_in, 'kit': cmd_kit, 'lesson': cmd_lesson, 'started': cmd_started,
            'stop-all': cmd_stop_all, 'proxy': cmd_proxy, 'report': cmd_report, 'share': cmd_share}


def main(argv):
    a = parser().parse_args(argv)
    try:
        return COMMANDS[a.command](a)
    except Refused as e:
        print(e.args[0])
        return 1
    except (OSError, subprocess.TimeoutExpired) as e:
        print('write_driver.py: %s' % e)
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
