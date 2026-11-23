#!/usr/bin/env python3
import fcntl
import os
from pathlib import Path
import re
import subprocess
import sys
import time

sys.dont_write_bytecode = True
REPO = re.compile(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+')
SHA = re.compile(r'[0-9a-f]{40}|[0-9a-f]{64}')
MAX_AGE = 60
STAMP = 'gitread-fetched'
USAGE = 'gitread: usage: gitread.py show OWNER/NAME PATH [--max-age SECONDS]'


class Error(Exception):
    pass


def cache_root():
    base = os.environ.get('XDG_CACHE_HOME') or os.path.join(os.path.expanduser('~'), '.cache')
    return Path(base) / 'launch-fleet' / 'git'


def git(cache, *args):
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GIT_DIR=str(cache))
    try:
        run = subprocess.run(['git', *args], capture_output=True, env=env, timeout=60, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Error(f'git {args[0]} failed: {error}')
    return run


def verified(cache, repo):
    run = git(cache, 'config', '--get', 'gitread.repo')
    if run.returncode != 0 or run.stdout.decode(errors='replace').strip() != repo:
        raise Error(f'cache {cache} is not a verified cache of {repo}; remove it to start afresh')
    run = git(cache, 'rev-parse', '--is-bare-repository')
    if run.returncode != 0 or run.stdout.strip() != b'true':
        raise Error(f'cache {cache} is not a bare repository; remove it to start afresh')


def stamp(cache):
    try:
        when, commit = (cache / STAMP).read_text().split()
        when = float(when)
    except (OSError, ValueError):
        return None
    if not SHA.fullmatch(commit) or not when <= time.time():
        return None
    return when, commit


def fetch(cache, repo):
    run = git(cache, 'fetch', '--quiet', '--depth', '1', '--no-tags', f'https://github.com/{repo}.git', 'HEAD')
    if run.returncode != 0:
        raise Error(f'could not fetch the default branch of {repo}: '
                    f'{run.stderr.decode(errors="replace").strip() or "git fetch exit %d" % run.returncode}')
    run = git(cache, 'rev-parse', '--verify', '--quiet', 'FETCH_HEAD^{commit}')
    commit = run.stdout.decode(errors='replace').strip()
    if run.returncode != 0 or not SHA.fullmatch(commit):
        raise Error(f'the fetch of {repo} named no commit')
    if git(cache, 'update-ref', 'refs/gitread/tip', commit).returncode != 0:
        raise Error(f'could not record the fetched tip of {repo}')
    tmp = cache / (STAMP + '.tmp')
    tmp.write_text(f'{time.time()} {commit}\n')
    os.replace(tmp, cache / STAMP)
    return commit


def show(repo, path, max_age=MAX_AGE):
    try:
        return locked_show(repo, path, max_age)
    except OSError as error:
        raise Error(f'could not use the cache for {repo}: {error}')


def locked_show(repo, path, max_age):
    if type(repo) is not str or not REPO.fullmatch(repo) or repo.split('/')[1] in ('.', '..'):
        raise Error(f'not a repository: {repo!r}')
    if (type(path) is not str or not path or path.startswith('/') or '\n' in path or '\0' in path
            or any(part in ('', '.', '..') for part in path.split('/'))):
        raise Error(f'not a repository path: {path!r}')
    if type(max_age) not in (int, float) or not max_age >= 0:
        raise Error(f'not a max age: {max_age!r}')
    owner, name = repo.split('/')
    cache = cache_root() / owner / (name + '.git')
    cache.parent.mkdir(parents=True, exist_ok=True)
    lock = open(cache.parent / (name + '.lock'), 'w')
    with lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not cache.exists():
            if git(cache, 'init', '--quiet', '--bare').returncode != 0 or \
                    git(cache, 'config', 'gitread.repo', repo).returncode != 0:
                raise Error(f'could not create the cache for {repo}')
        verified(cache, repo)
        last = stamp(cache)
        if last is not None and time.time() - last[0] < max_age:
            commit = last[1]
            if git(cache, 'cat-file', '-e', f'{commit}^{{commit}}').returncode != 0:
                raise Error(f'cache {cache} does not hold the commit its stamp names; remove it to start afresh')
        else:
            commit = fetch(cache, repo)
        kind = git(cache, 'cat-file', '-t', f'{commit}:{path}')
        if kind.returncode != 0 or kind.stdout.strip() != b'blob':
            raise Error(f'{path} is not a file at the tip of the default branch of {repo} ({commit})')
        run = git(cache, 'show', f'{commit}:{path}')
    if run.returncode != 0:
        raise Error(f'could not read {path} from {repo} at {commit}')
    try:
        return run.stdout.decode()
    except UnicodeDecodeError:
        raise Error(f'{path} in {repo} is not UTF-8 text')


def main(argv):
    args, max_age = list(argv), MAX_AGE
    if '--max-age' in args:
        at = args.index('--max-age')
        try:
            max_age = int(args[at + 1])
        except (IndexError, ValueError):
            max_age = -1
        del args[at:at + 2]
        if max_age < 0 or '--max-age' in args:
            print(USAGE, file=sys.stderr)
            return 2
    if len(args) != 3 or args[0] != 'show':
        print(USAGE, file=sys.stderr)
        return 2
    try:
        text = show(args[1], args[2], max_age)
    except Error as error:
        print(f'gitread: {error}', file=sys.stderr)
        return 2
    sys.stdout.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
