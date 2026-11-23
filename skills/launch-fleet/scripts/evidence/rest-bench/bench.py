#!/usr/bin/env python3
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys

USAGE = """The REST bench of FR5 (OpenWiz#2621): calls per run on the existing fixtures.

python3 -I bench.py fixtures OUT      run each wake script's own test suite with
                                     that script's runs under gh-meter.py, one
                                     log per script in OUT, and print the table
python3 -I bench.py live SAMPLES      the hour's REST and GraphQL `used` from
                                     `gh api rate_limit` samples (JSON lines)

fleet.sh spec runs through test.sh's FLEET_SH; each Python script's suite runs
in this process with subprocess patched, so only that script's own runs (and
whatever they start) see the meter's shim first on PATH. Every run uses its
suite's own fake `gh` and GH_METER_RATE=0, so nothing reaches GitHub.
The AFTER bench reruns the same command on the same fixtures.
"""

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent.parent
METER = SCRIPTS / 'gh-meter.py'
WAKES_PER_HOUR = 6
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
    try:
        runpy.run_path(str(SCRIPTS / test), run_name='__main__')
    except SystemExit:
        pass
    finally:
        subprocess.Popen.__init__ = original
        sys.argv = argv
    return log, runs[0]


def fleet_suite(out):
    log, runs = out / 'fleet.sh.jsonl', out / 'fleet.sh.runs'
    wrapper = out / 'fleet-metered.sh'
    wrapper.write_text(
        '#!/bin/sh\nif [ "${1:-}" = spec ]; then\n  echo run >> \'%s\'\n'
        '  PATH=\'%s\':"$PATH" GH_METER_LOG=\'%s\' GH_METER_ROLE=fleet GH_METER_RATE=0 exec /bin/sh \'%s\' "$@"\n'
        'fi\nexec /bin/sh \'%s\' "$@"\n' % (runs, SHIM, log, SCRIPTS / 'fleet.sh', SCRIPTS / 'fleet.sh'))
    env = dict(os.environ, FLEET_SH=str(wrapper), TEST_JOBS=os.environ.get('TEST_JOBS', '2'))
    subprocess.run(['sh', str(SCRIPTS / 'test.sh')], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return log, len(runs.read_text().splitlines()) if runs.exists() else 0


def counts(log):
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return (len(calls), sum(c['kind'] == 'rest' for c in calls), sum(c['kind'] == 'graphql' for c in calls),
            sum(c['rest_units'] for c in calls))


def fixtures(out):
    global SHIM
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    SHIM = out / 'shim'
    subprocess.run([sys.executable, '-I', str(METER), 'install', str(SHIM)], check=True)
    rows = [('fleet.sh spec', 'fleet', *fleet_suite(out))]
    for script, sub, test in PYTHON:
        rows.append((script + (' ' + sub if sub else ''), 'orchestrator', *python_suite(out, script, sub, test)))
    print('| Script | Role | Fixture runs | Calls | REST calls | GraphQL calls | REST units '
          '| REST units per run | REST units per spec-hour (x%d wakes) |' % WAKES_PER_HOUR)
    print('| --- | --- | --- | --- | --- | --- | --- | --- | --- |')
    for name, role, log, runs in rows:
        calls, rest, graphql, units = counts(log)
        per = units / runs if runs else 0
        print('| %s | %s | %d | %d | %d | %d | %d | %.1f | %.0f |'
              % (name, role, runs, calls, rest, graphql, units, per, per * WAKES_PER_HOUR))
    print()
    subprocess.run([sys.executable, '-I', str(METER), 'report', *[str(r[2]) for r in rows if r[2].exists()]])


def live(path):
    samples = [json.loads(line) for line in Path(path).read_text().splitlines()]
    good = [s for s in samples if 'core' in s]
    for kind in ('core', 'graphql'):
        spent, windows = 0, 1
        for a, b in zip(good, good[1:]):
            if b[kind]['reset'] == a[kind]['reset']:
                spent += b[kind]['used'] - a[kind]['used']
            else:
                spent += b[kind]['used']
                windows += 1
        print('%s: %d samples over %d minutes, %d used (a lower bound across %d reset windows), '
              'min remaining %d of %d'
              % (kind, len(good), (good[-1]['t'] - good[0]['t']) // 60, spent, windows,
                 min(s[kind]['remaining'] for s in good), good[0][kind]['limit']))
    print('unreadable samples: %d' % (len(samples) - len(good)))


if __name__ == '__main__':
    if sys.argv[1:2] == ['fixtures'] and len(sys.argv) == 3:
        fixtures(sys.argv[2])
    elif sys.argv[1:2] == ['live'] and len(sys.argv) == 3:
        live(sys.argv[2])
    else:
        sys.exit(USAGE.strip())
