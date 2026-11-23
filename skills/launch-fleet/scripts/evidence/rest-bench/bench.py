#!/usr/bin/env python3
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import time

USAGE = """The REST bench of FR5 (OpenWiz#2621): calls per run on the existing fixtures.

python3 -I bench.py fixtures OUT      run each wake script's own test suite with
                                     that script's runs under gh-meter.py, one
                                     log per script in OUT, and print the table
python3 -I bench.py sample SAMPLES   read `gh api rate_limit` (free) every 3 minutes
                                     until SAMPLES holds 21 points; rerun to resume.
                                     Under 1,500 left in either allowance it
                                     reads nothing until that one resets
python3 -I bench.py live SAMPLES      the hour's REST and GraphQL `used` from
                                     `gh api rate_limit` samples (JSON lines:
                                     epoch, t, and core/graphql limit, used,
                                     remaining, reset)

fleet.sh spec runs through test.sh's FLEET_SH; each Python script's suite runs
in this process with subprocess patched, so only that script's own runs (and
whatever they start) see the meter's shim first on PATH. Every run uses its
suite's own fake `gh` and GH_METER_RATE=0, so nothing reaches GitHub. Every
agent, harness and host CLI (AGENT_CLIS) is stubbed next on PATH, behind the
suites' own fakes: a stub records its name and exits 127, as if missing.
The AFTER bench reruns the same command on the same fixtures.
"""

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent.parent
METER = SCRIPTS / 'gh-meter.py'
WAKES_PER_HOUR = 6
AGENT_CLIS = ('boat', 'claude', 'codex', 'room-cli', 'bb', 'opencode', 'cursor-agent', 'droid', 'gemini', 'aider',
              'amp', 'qwen', 'goose', 'copilot', 'crush', 'pi', 'kimi', 'cline', 'pane', 'hermes', 'devin',
              'antigravity', 'fx', 'openclaw', 'agent-zero')
SAMPLES, GAP, FLOOR = 21, 180, 1500
PYTHON = [
    ('merge.py', None, 'test-merge.py'),
    ('status.py', 'repair', 'test-status.py'),
    ('post.py', None, 'test-post.py'),
    ('ops-starts.py', None, 'test-ops-starts.py'),
    ('brief.py', None, 'test-brief.py'),
]


def metered(env, log, role):
    env = dict(os.environ if env is None else env)
    env.update(PATH='%s:%s' % (SHIM, env.get('PATH', '')), GH_METER_LOG=str(log), GH_METER_ROLE=role,
               GH_METER_RATE='0')
    return env


def python_suite(out, script, sub, test):
    log, runs = out / ('%s.jsonl' % script), [0]
    original = subprocess.Popen.__init__

    def init(self, args, *a, **kw):
        argv = [str(x) for x in args] if isinstance(args, (list, tuple)) else []
        at = [i for i, x in enumerate(argv) if x.endswith('/' + script)]
        if at and (sub is None or argv[at[0] + 1:at[0] + 2] == [sub]):
            runs[0] += 1
            kw['env'] = metered(kw.get('env'), log, 'orchestrator')
        original(self, args, *a, **kw)

    subprocess.Popen.__init__ = init
    argv, sys.argv = sys.argv, [str(SCRIPTS / test)]
    status = 0
    try:
        runpy.run_path(str(SCRIPTS / test), run_name='__main__')
    except SystemExit as e:
        status = e.code if isinstance(e.code, int) else 1
    finally:
        subprocess.Popen.__init__ = original
        sys.argv = argv
    return log, runs[0], status


def fleet_suite(out):
    log, runs = out / 'fleet.sh.jsonl', out / 'fleet.sh.runs'
    wrapper = out / 'fleet-metered.sh'
    wrapper.write_text(
        '#!/bin/sh\nif [ "${1:-}" = spec ]; then\n  echo run >> \'%s\'\n'
        '  PATH=\'%s\':"$PATH" GH_METER_LOG=\'%s\' GH_METER_ROLE=fleet GH_METER_RATE=0 exec /bin/sh \'%s\' "$@"\n'
        'fi\nexec /bin/sh \'%s\' "$@"\n' % (runs, SHIM, log, SCRIPTS / 'fleet.sh', SCRIPTS / 'fleet.sh'))
    env = dict(os.environ, FLEET_SH=str(wrapper), TEST_JOBS=os.environ.get('TEST_JOBS', '2'))
    with open(out / 'test.sh.log', 'w') as output:
        run = subprocess.run(['sh', str(SCRIPTS / 'test.sh')], env=env, stdout=output, stderr=subprocess.STDOUT)
    if run.returncode:
        failed = [line for line in (out / 'test.sh.log').read_text().splitlines() if line.startswith('FAIL')]
        print('test.sh failed under the meter (%d FAIL lines):' % len(failed), *failed[:40], sep='\n',
              file=sys.stderr)
    return log, len(runs.read_text().splitlines()) if runs.exists() else 0, run.returncode


def counts(log):
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return (len(calls), sum(c['kind'] == 'rest' for c in calls), sum(c['kind'] == 'graphql' for c in calls),
            sum(c['rest_units'] for c in calls))


def fixtures(out):
    global SHIM
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    SHIM = out / 'shim'
    stubs, called = out / 'agent-stubs', out / 'agent-cli-calls'
    stubs.mkdir(exist_ok=True)
    for name in AGENT_CLIS:
        (stubs / name).write_text("#!/bin/sh\necho %s >> '%s'\nexit 127\n" % (name, called))
        (stubs / name).chmod(0o755)
    os.environ['PATH'] = '%s:%s' % (stubs, os.environ.get('PATH', ''))
    if subprocess.run([sys.executable, '-I', str(METER), 'install', str(SHIM)]).returncode:
        sys.exit('bench: the shim did not install')
    rows = [('fleet.sh spec', 'fleet', *fleet_suite(out))]
    for script, sub, test in PYTHON:
        rows.append((script + (' ' + sub if sub else ''), 'orchestrator', *python_suite(out, script, sub, test)))
    print('| Script | Role | Fixture runs | Calls | REST calls | GraphQL calls | REST units '
          '| REST units per run | REST units per spec-hour (x%d wakes) |' % WAKES_PER_HOUR)
    print('| --- | --- | --- | --- | --- | --- | --- | --- | --- |')
    for name, role, log, runs, _ in rows:
        calls, rest, graphql, units = counts(log)
        per = units / runs if runs else 0
        print('| %s | %s | %d | %d | %d | %d | %d | %.1f | %.0f |'
              % (name, role, runs, calls, rest, graphql, units, per, per * WAKES_PER_HOUR))
    print()
    reached = called.read_text().split() if called.exists() else []
    print('Agent-CLI stubs: %d installed; %d calls reached them%s' % (
        len(AGENT_CLIS), len(reached), ''.join(' (%s x%d)' % (n, reached.count(n)) for n in sorted(set(reached)))))
    print()
    report = subprocess.run([sys.executable, '-I', str(METER), 'report', *[str(r[2]) for r in rows if r[2].exists()]])
    broken = [r[0] for r in rows if r[4] != 0 or r[3] == 0]
    if broken or report.returncode:
        sys.exit('bench: a suite failed under the meter, or ran its script no times: %s' % ', '.join(broken))


def points(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()] if Path(path).exists() else []


def sample(path):
    while len(points(path)) < SAMPLES:
        last = points(path)[-1:]
        if last:
            time.sleep(max(0, last[0]['epoch'] + GAP - time.time(), *[
                last[0][kind]['reset'] + 5 - time.time()
                for kind in ('core', 'graphql') if kind in last[0] and last[0][kind]['remaining'] < FLOOR]))
        read = subprocess.run(['gh', 'api', 'rate_limit'], capture_output=True, text=True)
        now = time.time()
        point = {'epoch': round(now), 't': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now))}
        try:
            resources = json.loads(read.stdout)['resources'] if read.returncode == 0 else None
            for kind in ('core', 'graphql') if resources else ():
                point[kind] = {k: resources[kind][k] for k in ('limit', 'used', 'remaining', 'reset')}
        except (ValueError, KeyError, TypeError):
            point = {k: point[k] for k in ('epoch', 't')}
        if 'core' not in point:
            point['error'] = 'rate_limit unreadable'
        with open(path, 'a') as f:
            f.write(json.dumps(point) + '\n')
        print(len(points(path)), point['t'], flush=True)


def lone(samples, kind):
    return [b for a, b, c in zip(samples, samples[1:], samples[2:])
            if a[kind]['reset'] == c[kind]['reset'] != b[kind]['reset']]


def live(path):
    samples = points(path)
    good = [s for s in samples if 'core' in s]
    for kind in ('core', 'graphql'):
        odd = lone(good, kind)
        kept = [s for s in good if s not in odd]
        spent, windows = 0, 1
        for a, b in zip(kept, kept[1:]):
            if b[kind]['reset'] == a[kind]['reset']:
                spent += b[kind]['used'] - a[kind]['used']
            else:
                spent += b[kind]['used']
                windows += 1
        print('%s: %d samples over %d minutes, %d used (a lower bound across %d reset windows), '
              'min remaining %d of %d'
              % (kind, len(kept), (kept[-1]['epoch'] - kept[0]['epoch']) // 60, spent, windows,
                 min(s[kind]['remaining'] for s in kept), kept[0][kind]['limit']))
        for s in odd:
            print('  left out: %s, used %d, reset %d, unlike both neighbours (another allowance window)'
                  % (s['t'], s[kind]['used'], s[kind]['reset']))
    print('unreadable samples: %d' % (len(samples) - len(good)))

if __name__ == '__main__':
    if sys.argv[1:2] == ['fixtures'] and len(sys.argv) == 3:
        fixtures(sys.argv[2])
    elif sys.argv[1:2] == ['sample'] and len(sys.argv) == 3:
        sample(sys.argv[2])
    elif sys.argv[1:2] == ['live'] and len(sys.argv) == 3:
        live(sys.argv[2])
    else:
        sys.exit(USAGE.strip())
