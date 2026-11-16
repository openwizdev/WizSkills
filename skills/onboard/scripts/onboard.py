#!/usr/bin/env python3
"""The onboarding skill's mechanical checks (#1108). Standard library only.

  onboard.py create-repo --state FILE --repo OWNER/NAME [--yes]
  onboard.py choose --state FILE --options FILE --harness P --model M --effort E --agents cloud|local
  onboard.py spec --state FILE --spec N --repo OWNER/NAME
  onboard.py launch --state FILE --spec N --openwiz PROGRAM [--yes --confirm DIGEST]
  onboard.py progress --state FILE --spec N --openwiz PROGRAM

It adds no approval, planner or engine. `create-repo` makes the one disposable
demo repository, private, with the user's own gh identity, only on --yes: it
saves the name first, reads it back, and reads before any retry of a create
whose answer was lost. `launch` starts work only through the
engine's existing tick (contracts/fleet-tick.v1.md, reviewed-plan execution),
and only when launch-fleet's own frontier reader (../../launch-fleet/scripts/
fleet.sh frontier, which checks that plan-graph's approval is current) and the
tick's dry run name exactly the same tickets of this onboarding's spec, with
the user's recorded settings for every builder profile the fleet can use, and
the other model family reviewing. A preview prints a confirmation digest of its
exact effects; `--yes --confirm DIGEST` runs only if a fresh dry run still has
exactly those effects. Every command checks the checkout is the repository this
onboarding recorded. The launch is saved before it runs, and is never
run twice: a repeat only reads progress, and an uncertain outcome stays
uncertain for the engine's own recovery.

The state file is private and owner-only; keep it outside the checkout. It
holds the user's choices, this onboarding's spec and its one launch record.

Exits: 0 done; 1 a read failed; 2 usage; 5 refused, nothing started;
6 uncertain, never retried; 7 busy; 10 state unavailable; 12 preview, awaiting --yes.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

FLEET_SH = Path(__file__).resolve().parents[2] / 'launch-fleet/scripts/fleet.sh'
OPTIONS = {
    'create-repo': ({'--state', '--repo'}, {'--yes'}, set()),
    'choose': ({'--state', '--options', '--harness', '--model', '--effort', '--agents'}, set(), set()),
    'spec': ({'--state', '--spec', '--repo'}, set(), set()),
    'launch': ({'--state', '--spec', '--openwiz'}, {'--yes'}, {'--confirm'}),
    'progress': ({'--state', '--spec', '--openwiz'}, set(), set()),
}
FAMILY = {'claude-code': 'claude', 'codex': 'gpt'}
STATES = ('ready', 'building', 'in_review', 'changes_requested', 'merged', 'held', 'blocked')
NOTHING = 'nothing started.'


class Exit(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def strict(text):
    """One JSON value; a repeated key anywhere is refused."""
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('duplicate key')
            value[key] = item
        return value
    return json.loads(text, object_pairs_hook=pairs)


def parse(argv):
    if not argv or argv[0] not in OPTIONS:
        raise Exit(2, 'usage: onboard.py choose|spec|launch|progress ... (see its header)')
    values, switches, optional = OPTIONS[argv[0]]
    got, rest = {}, argv[1:]
    while rest:
        name = rest.pop(0)
        if name in got or (name not in values | optional and name not in switches):
            raise Exit(2, 'usage: unknown or repeated option %s' % name)
        if name in switches:
            got[name] = True
            continue
        if not rest:
            raise Exit(2, 'usage: %s needs a value' % name)
        got[name] = rest.pop(0)
    missing = sorted(values - set(got))
    if missing:
        raise Exit(2, 'usage: missing %s' % ', '.join(missing))
    if '--spec' in got and not re.fullmatch(r'[1-9][0-9]{0,9}', got['--spec']):
        raise Exit(2, 'usage: --spec takes an issue number')
    if argv[0] == 'launch' and ('--confirm' in got) != bool(got.get('--yes')) or not re.fullmatch(r'[0-9a-f]{64}', got.get('--confirm', '0' * 64)):
        raise Exit(2, 'usage: --yes takes --confirm with the digest of the preview the user said yes to')
    if '--repo' in got and not re.fullmatch(r'[A-Za-z0-9][-A-Za-z0-9]*/[-A-Za-z0-9_.]+', got['--repo']):
        raise Exit(2, 'usage: --repo takes owner/name')
    if '--agents' in got and got['--agents'] not in ('cloud', 'local'):
        raise Exit(2, 'usage: --agents is cloud or local')
    if '--openwiz' in got:
        program = got['--openwiz']
        if not os.path.isabs(program) or not os.path.isfile(program) or not os.access(program, os.X_OK):
            raise Exit(2, 'usage: --openwiz takes the installed program by absolute path')
    return argv[0], got


class State:
    """The private state file, held under its lock for the whole command."""

    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_absolute():
            raise Exit(2, 'usage: --state takes an absolute path')
        try:
            self.lock = os.open(str(self.path) + '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        except OSError:
            raise Exit(10, 'The onboarding state is unavailable; ' + NOTHING)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Exit(7, 'Another onboarding command is using this state; ' + NOTHING)
        self.value = self.read()

    def read(self):
        try:
            info = os.lstat(self.path)
        except FileNotFoundError:
            return {}
        except OSError:
            raise Exit(10, 'The onboarding state is unreadable; ' + NOTHING)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise Exit(10, 'The onboarding state must be an owner-only regular file; ' + NOTHING)
        try:
            value = strict(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            raise Exit(10, 'The onboarding state is unreadable; ' + NOTHING)
        if not isinstance(value, dict) or set(value) - {'created', 'choices', 'repo', 'spec', 'preview', 'launch'}:
            raise Exit(10, 'The onboarding state has an unknown shape; ' + NOTHING)
        return value

    def save(self):
        temp = self.path.with_name(self.path.name + '.new')
        try:
            fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(self.value, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
            return True
        except OSError:
            try:
                os.unlink(temp)
            except OSError:
                pass
            return False


def run(argv, env=None):
    try:
        return subprocess.run(argv, capture_output=True, timeout=600, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None


def look(name):
    """'private', 'public' or 'absent', from one read; None when the read itself failed."""
    env = dict(os.environ)
    env.pop('GH_REPO', None)
    result = run(['gh', 'repo', 'view', name, '--json', 'nameWithOwner,isPrivate'], env)
    if result is None:
        return None
    if result.returncode != 0:
        return 'absent' if b'Could not resolve to a Repository' in result.stderr else None
    try:
        found = strict(result.stdout.decode('utf-8'))
        assert found['nameWithOwner'] == name and type(found['isPrivate']) is bool
    except (UnicodeDecodeError, ValueError, KeyError, TypeError, AssertionError):
        return None
    return 'private' if found['isPrivate'] else 'public'


def create_repo(got):
    name = got['--repo']
    print('Effect: create one new private GitHub repository, %s, with your gh identity. Nothing else is created; '
          'its CloudRoom project stays yours to make or pick.' % name)
    if not got.get('--yes'):
        print("Nothing created. On the user's yes to exactly this, run again with --yes.")
        return 12
    state = State(got['--state'])
    record = state.value.get('created')
    if record and record['repo'] != name and record['state'] != 'absent':
        raise Exit(5, 'This onboarding already made %s; it makes one demo repository.' % record['repo'])
    seen = look(name)
    if seen is None:
        raise Exit(1 if not record else 6, 'Could not read whether %s exists; nothing created.' % name)
    if record and record['repo'] == name and record['state'] in ('pending', 'uncertain', 'created'):
        if seen == 'private':
            state.value['created'] = {'repo': name, 'state': 'created'}
            if not state.save():
                raise Exit(6, 'Could not save the created repository; it exists, so never create it again.')
            print('Created and read back: %s, private.' % name)
            return 0
        if seen == 'public' or record['state'] == 'created':
            raise Exit(5, '%s is not the private repository this onboarding created; nothing created.' % name)
    elif seen != 'absent':
        raise Exit(5, '%s already exists; choose another name, or use it as an existing repository; '
                      'nothing created.' % name)
    state.value['created'] = {'repo': name, 'state': 'pending'}
    if not state.save():
        raise Exit(10, 'Could not save the repository name first; nothing created.')
    run(['gh', 'repo', 'create', name, '--private'])
    seen = look(name)
    ended = {'private': 'created', 'absent': 'absent'}.get(seen, 'uncertain')
    state.value['created'] = {'repo': name, 'state': ended}
    saved = state.save()
    if ended == 'created' and saved:
        print('Created and read back: %s, private.' % name)
        return 0
    if ended == 'absent' and saved:
        raise Exit(5, 'GitHub did not create %s; nothing created. Try again only after the user says yes again.' % name)
    raise Exit(6, 'Whether %s was created is uncertain; read it back before any retry (run this again).' % name)


def choose(got):
    try:
        offered = strict(Path(got['--options']).read_text(encoding='utf-8'))
        assert offered['schema'] == 'openwiz.cloud-options.v1' and offered['state'] == {'kind': 'offered'}
        harnesses = [h for h in offered['harnesses'] if h['provider'] == got['--harness']]
    except (OSError, ValueError, KeyError, TypeError, AssertionError):
        raise Exit(1, 'The saved `openwiz models --json` output is unreadable; nothing recorded.')
    efforts = [e for h in harnesses for m in h['models'] if m['model'] == got['--model'] for e in m['efforts']]
    if len(harnesses) != 1 or got['--effort'] not in efforts:
        raise Exit(5, 'That harness, model and effort are not among the offered options; nothing recorded.')
    if got['--harness'] not in FAMILY:
        raise Exit(5, "The engine's review rules cover Claude Code and Codex builders only; nothing recorded.")
    state = State(got['--state'])
    state.value['choices'] = {'harness': got['--harness'], 'model': got['--model'],
                              'effort': got['--effort'], 'agents': got['--agents']}
    if not state.save():
        raise Exit(10, 'Could not save the choices; nothing recorded.')
    where = 'in the Cloud' if got['--agents'] == 'cloud' else 'on this computer (Local)'
    print('Recorded: builders use %s %s %s, and run %s.' % (got['--harness'], got['--model'], got['--effort'], where))
    return 0


def repository(recorded):
    """The environment for every read and run, once the checkout is the recorded repository."""
    if not recorded:
        raise Exit(5, 'This onboarding recorded no repository; record its spec first; ' + NOTHING)
    env = dict(os.environ)
    named = env.pop('GH_REPO', None)
    if named is not None and named != recorded:
        raise Exit(5, 'GH_REPO names %s, but this onboarding is for %s; %s' % (named, recorded, NOTHING))
    result = run(['gh', 'repo', 'view', '--json', 'nameWithOwner', '--jq', '.nameWithOwner'], env)
    if result is None or result.returncode != 0:
        raise Exit(1, 'Could not read which repository this checkout is; ' + NOTHING)
    here = result.stdout.decode('utf-8', 'replace').strip()
    if here != recorded:
        raise Exit(5, 'This checkout is %s, but this onboarding is for %s; %s' % (here, recorded, NOTHING))
    env['GH_REPO'] = recorded
    return env


def record_spec(got):
    state = State(got['--state'])
    spec = int(got['--spec'])
    repository(got['--repo'])
    if state.value.get('launch') and state.value.get('repo') not in (None, got['--repo']):
        raise Exit(5, 'This onboarding already launched in %s; nothing recorded.' % state.value['repo'])
    launch = state.value.get('launch')
    if launch and launch['spec'] != spec and launch['state'] != 'refused':
        raise Exit(5, 'This onboarding already launched spec #%d; it plans one first fleet.' % launch['spec'])
    state.value['spec'] = spec
    state.value['repo'] = got['--repo']
    if not state.save():
        raise Exit(10, 'Could not save the spec; nothing recorded.')
    print('Recorded: this onboarding planned spec #%d in %s.' % (spec, got['--repo']))
    return 0


def frontier(env):
    result = run(['sh', str(FLEET_SH), 'frontier'], env)
    if result is None or result.returncode != 0:
        raise Exit(1, 'Could not read the approved frontier; ' + NOTHING)
    tickets = {}
    for line in result.stdout.decode('utf-8', 'replace').splitlines():
        match = re.fullmatch(r'#([1-9][0-9]*) (.+)', line)
        if not match or int(match[1]) in tickets:
            raise Exit(1, 'The frontier read was not in its form; ' + NOTHING)
        tickets[int(match[1])] = match[2]
    return tickets


def review(spec, choices, plan, ready):
    """The planned starts, or why the reviewed plan is refused."""
    if plan.get('schema') != 'openwiz.fleet-tick.v1' or plan.get('mode') != 'dry_run' \
            or not isinstance(plan.get('actions'), list):
        raise Exit(1, "The engine's dry run was not a fleet tick preview; " + NOTHING)
    if not ready and not plan['actions']:
        raise Exit(5, 'No approved ticket is ready to start: the plan is unapproved, changed since its approval, '
                      'or still blocked; ' + NOTHING)
    want = {k: choices[k] for k in ('harness', 'model', 'effort')}
    rules = plan.get('rules')
    if not isinstance(rules, dict) or rules.get('builder') != want or rules.get('builder_small') != want:
        raise Exit(5, "The fleet's builder tables (builder and small-ticket builder) are not exactly the user's "
                      'choice; run setup so both match, then preview again; ' + NOTHING)
    reviewer = rules.get('reviewer_' + FAMILY.get(want['harness'], 'unknown'))
    reviewer_family = FAMILY.get(reviewer.get('harness')) if isinstance(reviewer, dict) else None
    if reviewer_family is None or reviewer_family == FAMILY.get(want['harness']):
        raise Exit(5, "The fleet's reviewer for these builders is not from the other model family; " + NOTHING)
    starts = []
    for action in plan['actions']:
        ok = (isinstance(action, dict) and action.get('kind') == 'start_builder' and action.get('rule') == 'frontier'
              and action.get('spec') == spec and type(action.get('ticket')) is int
              and action.get('outcome') == {'state': 'planned'} and isinstance(action.get('facts'), dict))
        if not ok:
            raise Exit(5, "The engine's plan has an action other than this spec's builder starts; " + NOTHING)
        if action['facts'].get('settings') != want:
            raise Exit(5, "The engine would start builders with other settings than the user's choice; run setup "
                          'so the builder table matches, then preview again; ' + NOTHING)
        starts.append(action['ticket'])
    if len(starts) != len(set(starts)) or set(starts) != set(ready):
        raise Exit(5, "The engine's plan and the approved frontier name different tickets; " + NOTHING)
    return sorted(starts)


def outcome(result, starts):
    """done, refused (nothing changed) or uncertain: how the one execution ended."""
    if result is None:
        return 'uncertain', ['The engine gave no answer.']
    try:
        report = strict(result.stdout.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        report = None
    if result.returncode == 1 and isinstance(report, dict) and report.get('schema') == 'openwiz.cli-error.v1':
        return 'refused', ['The engine refused the reviewed plan before any effect.']
    if result.returncode != 0 or not isinstance(report, dict) or report.get('schema') != 'openwiz.fleet-tick.v1' \
            or report.get('mode') != 'run' or not isinstance(report.get('actions'), list):
        return 'uncertain', ["The engine's answer was lost or not a tick report."]
    seen, lines = {}, []
    for action in report['actions']:
        if isinstance(action, dict) and action.get('kind') == 'start_builder' and action.get('ticket') in starts:
            seen[action['ticket']] = (action.get('outcome') or {}).get('state')
    for ticket in starts:
        state = seen.get(ticket, 'unreported')
        lines.append('#%d %s' % (ticket, 'started' if state == 'done' else state))
    return ('done' if all(seen.get(t) == 'done' for t in starts) else 'uncertain'), lines


def launch(got):
    state = State(got['--state'])
    spec = int(got['--spec'])
    if state.value.get('spec') != spec:
        raise Exit(5, 'This onboarding planned no spec #%d; it launches only the spec its own grill planned; %s'
                   % (spec, NOTHING))
    choices = state.value.get('choices')
    if not choices:
        raise Exit(5, 'The harness, model, effort and agent location are not chosen yet; ' + NOTHING)
    env = repository(state.value.get('repo'))
    previous = state.value.get('launch')
    if previous and previous['spec'] == spec and previous['state'] != 'refused':
        settled = previous['state'] == 'done'
        print('Spec #%d already started once (%s); not starting again.' % (
            spec, 'done' if settled else 'uncertain: the engine reconciles it, never a retry'))
        progress(spec, got['--openwiz'], env)
        return 0 if settled else 6
    if choices['agents'] != 'cloud':
        raise Exit(5, "Local fleet agents are not available through the engine yet: its starts run in the Cloud. "
                      'Choose Cloud, or stop here; ' + NOTHING)
    ready = frontier(env)
    preview = run([got['--openwiz'], 'fleet', 'tick', '--dry-run', '--json'], env)
    if preview is None or preview.returncode != 0:
        raise Exit(1, "Could not read the engine's dry run; " + NOTHING)
    try:
        plan = strict(preview.stdout.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        raise Exit(1, "The engine's dry run was not JSON; " + NOTHING)
    starts = review(spec, choices, plan, ready)
    effects = hashlib.sha256(json.dumps(
        {'repo': state.value['repo'], 'spec': spec, 'default_branch': plan.get('default_branch'),
         'rules': plan['rules'], 'actions': plan['actions']},
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if got.get('--yes'):
        shown = state.value.get('preview') or {}
        if got['--confirm'] != effects or shown.get('effects') != effects or shown.get('spec') != spec:
            raise Exit(5, 'The effects changed since the preview the user said yes to (or it was never shown); '
                          'preview again and ask again; ' + NOTHING)
    print('Ready to start %d builders for spec #%d in the Cloud, each %s %s %s:' % (
        len(starts), spec, choices['harness'], choices['model'], choices['effort']))
    for ticket in starts:
        print('#%d %s' % (ticket, ready[ticket]))
    print('Cloud Credits: unknown until measured. Model-provider charges are separate.')
    if not got.get('--yes'):
        shown = state.path.with_name('onboard-preview-%d-%s.json' % (spec, effects))
        try:
            fd = os.open(shown, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as handle:
                handle.write(preview.stdout)
        except FileExistsError:
            pass
        except OSError:
            raise Exit(10, 'Could not save the preview; ' + NOTHING)
        state.value['preview'] = {'spec': spec, 'effects': effects}
        if not state.save():
            raise Exit(10, 'Could not save the preview; ' + NOTHING)
        print('Confirmation: %s' % effects)
        print('Nothing started. Show this to the user; on their yes to exactly these effects, run again with '
              '--yes --confirm %s.' % effects)
        return 12
    plan_path = state.path.with_name('onboard-plan-%d-%s.json' % (spec, effects))
    digest = hashlib.sha256(preview.stdout).hexdigest()
    try:
        fd = os.open(plan_path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(preview.stdout)
    except OSError:
        raise Exit(10, 'Could not save the reviewed plan; ' + NOTHING)
    state.value['launch'] = {'spec': spec, 'state': 'pending', 'plan_sha256': digest, 'tickets': starts}
    if not state.save():
        raise Exit(10, 'Could not save the launch record; ' + NOTHING)
    result = run([got['--openwiz'], 'fleet', 'tick', '--expect-plan', str(plan_path), '--json'], env)
    ended, lines = outcome(result, starts)
    state.value['launch']['state'] = ended
    saved = state.save()
    for line in lines:
        print(line)
    if ended == 'refused' and saved:
        print('Nothing changed. Preview again before another try.')
        return 5
    if not saved:
        print('Could not save the outcome; the launch stays uncertain and is never retried.')
        ended = 'uncertain'
    if ended == 'uncertain':
        print('The start is uncertain. The engine reconciles it; never start it again by hand.')
    progress(spec, got['--openwiz'], env)
    return 0 if ended == 'done' else 6


def watch(got):
    state = State(got['--state'])
    spec = int(got['--spec'])
    if state.value.get('spec') != spec:
        raise Exit(5, 'This onboarding planned no spec #%d.' % spec)
    return progress(spec, got['--openwiz'], repository(state.value.get('repo')))


def progress(spec, program, env):
    result = run([program, 'fleet', str(spec), '--json'], env)
    try:
        assert result is not None and result.returncode == 0
        view = strict(result.stdout.decode('utf-8'))
        assert view['schema'] == 'openwiz.fleet.v1' and view['data']['view'] == 'fleet'
        assert view['data']['fleet']['spec'] == spec
        tickets, counts = view['data']['tickets'], view['data']['fleet']['progress']
    except (AssertionError, UnicodeDecodeError, ValueError, KeyError, TypeError):
        print('Progress for spec #%d is unreadable right now.' % spec)
        return 1
    for ticket in tickets:
        known = ticket['state'].get('known') if isinstance(ticket.get('state'), dict) else None
        print('#%d %s' % (ticket['number'], known if known in STATES else 'unknown'))
    known = counts.get('known') if isinstance(counts, dict) else None
    if isinstance(known, dict):
        parts = ['%d %s' % (known[s], s.replace('_', ' ')) for s in STATES + ('unknown',) if known.get(s)]
        print('%d tickets: %s' % (known.get('tickets', 0), ', '.join(parts) or 'none yet'))
    else:
        print('Counts unknown: some reads are incomplete.')
    return 0


def main(argv):
    try:
        command, got = parse(argv)
        if command == 'create-repo':
            return create_repo(got)
        if command == 'choose':
            return choose(got)
        if command == 'spec':
            return record_spec(got)
        if command == 'launch':
            return launch(got)
        return watch(got)
    except Exit as stop:
        print(stop.args[0])
        return stop.code


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
