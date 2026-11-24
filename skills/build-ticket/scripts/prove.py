#!/usr/bin/env python3
"""Prove red before, green after, in one deterministic check.

python3 -I prove.py --base <ref> --test <path>... [--timeout <s>] [--repo <dir>] -- <test command>

Run it from the repository, or name it with `--repo`. It checks the committed HEAD, never the
working tree. It adds two throwaway worktrees (`git worktree add --detach`), one at `--base` and
one at HEAD, and copies each `--test` path from HEAD into the base worktree so a new test runs
on the old code. It runs the test command twice in each worktree and classifies each run as
`passed`, `failed` (the test ran and an assertion failed) or `error` (anything else: no build,
import or collection, no test ran, a timeout, or an outcome it does not recognise). It knows
pytest, unittest, `cargo test` and `node --test` from the exit code and summary lines.

Exit 0 only when base is `failed` 2 of 2 and head is `passed` 2 of 2; exit 1 otherwise, naming
the side that broke the rule; exit 2 on bad arguments or a git failure before any test ran.
It prints one JSON line on stdout, a line per run on stderr, and removes both worktrees on
every exit. Python 3.11+ standard library only.
"""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import subprocess
import sys
import tempfile

RUNS = 2


def git(repo, *args):
    done = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True)
    if done.returncode:
        raise SystemExit(f'prove: git {" ".join(args)}: {done.stderr.strip() or "failed"}')
    return done.stdout.strip()


def counts(text, words):
    found = {}
    for number, word in re.findall(r'(\d+) (' + '|'.join(words) + r')\b', text):
        found[word] = found.get(word, 0) + int(number)
    return found


def pytest(code, out):
    lines = [l for l in out.splitlines()
             if re.fullmatch(r'=*\s*(\d+ \w+(, \d+ \w+)*|no tests ran) in [\d.]+s(\s*\(.*\))?\s*=*', l.strip())]
    if not lines:
        return None
    n = counts(lines[-1], ['passed', 'failed', 'error', 'errors'])
    errors = n.get('error', 0) + n.get('errors', 0)
    if code == 0 and n.get('passed') and not n.get('failed') and not errors:
        return 'passed'
    reasons = re.findall(r'^FAILED \S+ - (.*)$', out, re.M)
    if (code == 1 and n.get('failed') and not errors and len(reasons) == n['failed']
            and all(re.match(r'(assert\b|AssertionError\b|Failed:)', r) for r in reasons)):
        return 'failed'
    return 'error'


def unittest(code, out):
    ran = re.findall(r'^Ran (\d+) tests? in ', out, re.M)
    end = re.findall(r'^(OK|FAILED)\b(.*)$', out, re.M)
    if not ran or not end:
        return None
    word, detail = end[-1]
    n = dict((k, int(v)) for k, v in re.findall(r'(\w+)=(\d+)', detail))
    if int(ran[-1]) == 0:
        return 'error'
    if code == 0 and word == 'OK':
        return 'passed'
    if code == 1 and word == 'FAILED' and n.get('failures') and not n.get('errors') \
            and not n.get('unexpected successes'):
        return 'failed'
    return 'error'


def cargo(code, out):
    results = re.findall(r'^test result: (ok|FAILED)\. (.*)$', out, re.M)
    if not results:
        return None
    if re.search(r'^error(\[E\d+\])?: (could not compile|failed to)', out, re.M):
        return 'error'
    passed = sum(counts(r, ['passed']).get('passed', 0) for _, r in results)
    failed = sum(counts(r, ['failed']).get('failed', 0) for _, r in results)
    if code == 0 and passed and not failed and all(w == 'ok' for w, _ in results):
        return 'passed'
    if code == 101 and failed:
        return 'failed'
    return 'error'


def node(code, out):
    n = dict((k, int(v)) for k, v in re.findall(r'^[#ℹ] (tests|pass|fail|cancelled) (\d+)\s*$', out, re.M))
    if 'tests' not in n or 'fail' not in n:
        return None
    if n.get('cancelled') or not n['tests']:
        return 'error'
    if code == 0 and n.get('pass') and not n['fail']:
        return 'passed'
    if code != 1 or not n['fail']:
        return 'error'
    # Spec reporter: each block under "failing tests" must be an assertion; TAP: each
    # failed test's YAML block must carry ERR_ASSERTION.
    if '✖ failing tests:' in out:
        blocks = re.split(r'^test at ', out.split('✖ failing tests:', 1)[1], flags=re.M)[1:]
    else:
        blocks = [b for b in re.split(r'^\s*not ok \d+', out, flags=re.M)[1:]
                  if "failureType: 'testCodeFailure'" in b]
    if len(blocks) == n['fail'] and all('ERR_ASSERTION' in b or 'AssertionError' in b for b in blocks):
        return 'failed'
    return 'error'


def classify(code, out):
    """Outcome of one run from its exit code and combined output; None code means a timeout."""
    if code is None:
        return 'error'
    for parse in (cargo, pytest, unittest, node):
        outcome = parse(code, out)
        if outcome:
            return outcome
    return 'error'


def run(command, cwd, timeout):
    proc = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode, out.decode('utf-8', 'replace')
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        out, _ = proc.communicate()
        return None, out.decode('utf-8', 'replace')
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()


def copy_tests(paths, head, base):
    for rel in paths:
        source, target = head / rel, base / rel
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True, symlinks=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target, follow_symlinks=False)


def verdict(base, head):
    if base != ['failed'] * RUNS:
        return 'base', f'base must be failed {RUNS} of {RUNS}; it was {", ".join(base)}'
    if head != ['passed'] * RUNS:
        return 'head', f'head must be passed {RUNS} of {RUNS}; it was {", ".join(head)}'
    return None, f'base failed {RUNS} of {RUNS} and head passed {RUNS} of {RUNS}'


def parse(argv):
    if '--' not in argv:
        raise SystemExit('prove: put the test command after --')
    split = argv.index('--')
    p = argparse.ArgumentParser(prog='prove.py')
    p.add_argument('--base', required=True)
    p.add_argument('--test', required=True, nargs='+', action='extend')
    p.add_argument('--timeout', type=float, default=600)
    p.add_argument('--repo', default='.')
    args = p.parse_args(argv[:split])
    args.command = argv[split + 1:]
    if not args.command:
        raise SystemExit('prove: no test command after --')
    if args.timeout <= 0:
        raise SystemExit('prove: --timeout must be positive')
    for rel in args.test:
        path = PurePosixPath(rel)
        if path.is_absolute() or '..' in path.parts or str(path) in ('', '.'):
            raise SystemExit(f'prove: --test {rel}: give a path inside the repository')
    return args


def main(argv):
    args = parse(argv)
    repo = Path(git(args.repo, 'rev-parse', '--show-toplevel'))
    base_sha = git(repo, 'rev-parse', '--verify', '--end-of-options', args.base + '^{commit}')
    head_sha = git(repo, 'rev-parse', '--verify', 'HEAD^{commit}')
    for rel in args.test:
        if not git(repo, 'ls-tree', '--name-only', head_sha, '--', rel):
            raise SystemExit(f'prove: --test {rel}: not in HEAD')
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(1))
    root = Path(tempfile.mkdtemp(prefix='prove-'))
    trees = {'base': root / 'base', 'head': root / 'head'}
    added = []
    try:
        for side, sha in (('base', base_sha), ('head', head_sha)):
            git(repo, 'worktree', 'add', '--detach', str(trees[side]), sha)
            added.append(trees[side])
        copy_tests(args.test, trees['head'], trees['base'])
        outcomes = {}
        for side in ('base', 'head'):
            outcomes[side] = []
            for n in range(1, RUNS + 1):
                code, out = run(args.command, trees[side], args.timeout)
                outcome = classify(code, out)
                outcomes[side].append(outcome)
                shown = 'timeout' if code is None else f'exit {code}'
                print(f'prove: {side} run {n}: {outcome} ({shown})', file=sys.stderr, flush=True)
                if outcome == 'error':
                    tail = out.rstrip().splitlines()[-15:]
                    print('\n'.join('  | ' + l for l in tail), file=sys.stderr, flush=True)
        broke, why = verdict(outcomes['base'], outcomes['head'])
        print(json.dumps({'base': base_sha, 'head': head_sha, 'base_runs': outcomes['base'],
                          'head_runs': outcomes['head'], 'verdict': 'fail' if broke else 'pass',
                          'broke': broke, 'why': why}), flush=True)
        if broke:
            print(f'prove: {why}', file=sys.stderr)
        return 1 if broke else 0
    finally:
        for tree in added:
            subprocess.run(['git', '-C', str(repo), 'worktree', 'remove', '--force', '--force', str(tree)],
                           capture_output=True)
        shutil.rmtree(root, ignore_errors=True)
        subprocess.run(['git', '-C', str(repo), 'worktree', 'prune'], capture_output=True)


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except SystemExit as stop:
        if isinstance(stop.code, str):
            print(stop.code, file=sys.stderr)
            sys.exit(2)
        raise
