#!/usr/bin/env python3
import argparse
import json
import statistics
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HELP = """Where WizSkills' `check` spends its time (spec #2134, WQ0).

python3 check/bench.py --from 2026-11-20 --to 2026-11-22 [--save DIR]
python3 check/bench.py --runs 45007415699 45007321482 [--save DIR]
python3 check/bench.py --saved DIR [--window LABEL]

It reads finished `check` runs through `gh api` (GET only; it writes nothing
on GitHub), or a folder saved by `--save`, and prints one Markdown table: each
phase's seconds per run and the median over the window, with how many runs
knew it. A date window keeps the successful pull_request runs created in it.

Phases: queue wait (job created to started), setup (set up job, checkout,
Changesets install), the changeset gate, the comment check, the browser-tools
install, the rules and the standalone check (from the `check/run.py` log),
each suite (its `running` line to its `pass`/`fail` line) and the total (run
created to last job completed). A phase a run never finished is `unknown`,
never zero, and stays out of the median. A run with several jobs takes each
phase's longest job.
"""
REPO = 'openwizdev/WizSkills'
WORKFLOW = 'ci.yml'
SETUP_STEPS = ('Set up job', 'Run actions/checkout', 'Install the pinned Changesets')
STEP_PHASES = (('changeset gate', 'Changeset gate'), ('comment check', 'Comment check'),
               ('browser tools', 'Install pinned test-only browser tools'))
RUN_PY = '##[group]Run python3 check/run.py'
FIXED = ('queue wait', 'setup', 'changeset gate', 'comment check', 'browser tools', 'rules', 'standalone')


def when(text):
    return datetime.fromisoformat(text) if text else None


def seconds(start, end):
    return None if start is None or end is None else (end - start).total_seconds()


def step_seconds(steps, prefix):
    step = next((s for s in steps if s['name'].startswith(prefix)), None)
    if step is None or step.get('conclusion') != 'success':
        return None
    return seconds(when(step.get('started_at')), when(step.get('completed_at')))


def log_lines(text):
    for line in text.lstrip('﻿').splitlines():
        stamp, _, rest = line.partition(' ')
        try:
            yield datetime.fromisoformat(stamp), rest
        except ValueError:
            continue


def job_phases(job, log):
    steps = job.get('steps') or []
    out = {'queue wait': seconds(when(job.get('created_at')), when(job.get('started_at')))}
    setup = [step_seconds(steps, prefix) for prefix in SETUP_STEPS]
    out['setup'] = None if None in setup else sum(setup)
    for phase, prefix in STEP_PHASES:
        out[phase] = step_seconds(steps, prefix)
    started, rules_at, running = None, None, {}
    for at, text in log_lines(log):
        if text.startswith(RUN_PY):
            started = at
        elif text.startswith('rules: ') and started:
            rules_at = at
            out['rules'] = seconds(started, at)
        elif text.startswith('standalone: ') and rules_at:
            out['standalone'] = seconds(rules_at, at)
        elif text.startswith('suite ') and ': ' in text:
            suite, _, state = text.rpartition(': ')
            if state == 'running':
                running[suite] = at
                out.setdefault(suite, None)
            elif (state == 'pass' or state.startswith('fail')) and suite in running:
                out[suite] = seconds(running.pop(suite), at)
    return out


def run_phases(run, jobs, logs):
    phases = {}
    for job in jobs:
        for phase, value in job_phases(job, logs.get(job['id'], '')).items():
            known = [v for v in (phases.get(phase), value) if v is not None]
            phases[phase] = max(known) if known else None
    ends = [when(job.get('completed_at')) for job in jobs]
    phases['total'] = None if not ends or None in ends else seconds(when(run.get('created_at')), max(ends))
    return phases


def report(window, runs):
    suites = []
    for _, phases in runs:
        suites += [p for p in phases if p.startswith('suite ') and p not in suites]
    shown = lambda v: 'unknown' if v is None else f'{v:.1f}'
    lines = [f'Window: {window}', f'Runs: {len(runs)}', '',
             '| Phase | Median (s) | Known | ' + ' | '.join(str(r) for r, _ in runs) + ' |',
             '| --- | ---: | ---: |' + ' ---: |' * len(runs)]
    for phase in (*FIXED, *suites, 'total'):
        values = [phases.get(phase) for _, phases in runs]
        known = [v for v in values if v is not None]
        median = statistics.median(known) if known else None
        lines.append(f'| {phase} | {shown(median)} | {len(known)}/{len(runs)} | '
                     + ' | '.join(shown(v) for v in values) + ' |')
    return '\n'.join(lines)


def gh(path, raw=False):
    argv = ['gh', 'api', *(['--allow-escape-sequences'] if raw else []), path]
    done = subprocess.run(argv, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if done.returncode:
        raise SystemExit(f'bench: gh api {path}: {done.stderr.strip()}')
    return done.stdout if raw else json.loads(done.stdout)


def window_runs(start, end):
    runs, page = [], 1
    while True:
        got = gh(f'repos/{REPO}/actions/workflows/{WORKFLOW}/runs?event=pull_request'
                 f'&status=completed&created={start}..{end}&per_page=100&page={page}')['workflow_runs']
        if not got:
            break
        runs += [r for r in got if r.get('conclusion') == 'success']
        page += 1
    return sorted(runs, key=lambda r: r['created_at'])


def fetch(run, save):
    jobs = gh(f'repos/{REPO}/actions/runs/{run["id"]}/jobs?per_page=100')['jobs']
    logs = {job['id']: gh(f'repos/{REPO}/actions/jobs/{job["id"]}/logs', raw=True) for job in jobs}
    if save:
        folder = Path(save) / str(run['id'])
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'run.json').write_text(json.dumps(run, indent=1), encoding='utf-8')
        (folder / 'jobs.json').write_text(json.dumps({'jobs': jobs}, indent=1), encoding='utf-8')
        for job_id, text in logs.items():
            (folder / f'{job_id}.log').write_text(text, encoding='utf-8')
    return run_phases(run, jobs, logs)


def saved(folder):
    out = []
    for path in sorted((p for p in Path(folder).iterdir() if (p / 'run.json').is_file()), key=lambda p: p.name):
        run = json.loads((path / 'run.json').read_text(encoding='utf-8'))
        jobs = json.loads((path / 'jobs.json').read_text(encoding='utf-8'))['jobs']
        logs = {job['id']: (path / f'{job["id"]}.log').read_text(encoding='utf-8')
                for job in jobs if (path / f'{job["id"]}.log').is_file()}
        out.append((run['id'], run_phases(run, jobs, logs)))
    return out


def main(argv):
    parser = argparse.ArgumentParser(prog='check/bench.py', description=HELP,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--from', dest='start', metavar='DATE')
    parser.add_argument('--to', dest='end', metavar='DATE')
    parser.add_argument('--runs', nargs='+', type=int, metavar='ID')
    parser.add_argument('--saved', metavar='DIR')
    parser.add_argument('--save', metavar='DIR')
    parser.add_argument('--window', metavar='LABEL')
    args = parser.parse_args(argv)
    modes = [bool(args.start and args.end), bool(args.runs), bool(args.saved)]
    if sum(modes) != 1 or bool(args.start) != bool(args.end):
        parser.print_usage(sys.stderr)
        print('bench: give one of --from/--to, --runs or --saved', file=sys.stderr)
        return 2
    if args.saved:
        runs, window = saved(args.saved), args.window or f'saved runs in {args.saved}'
    else:
        if args.runs:
            chosen = [gh(f'repos/{REPO}/actions/runs/{r}') for r in args.runs]
            window = args.window or 'runs ' + ', '.join(map(str, args.runs))
        else:
            chosen = window_runs(args.start, args.end)
            window = args.window or f'pull_request runs of {REPO} check created {args.start}..{args.end}'
        runs = [(run['id'], fetch(run, args.save)) for run in chosen]
    print(report(window, runs))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
