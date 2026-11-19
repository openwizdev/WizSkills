#!/usr/bin/env python3
"""diagnose's loop helper. Python 3.11+ standard library; prints one short line.

  loop.py rate --runs N [--timeout SECONDS] -- COMMAND...
      Run COMMAND N times (no shell, output discarded, never echoed) and print
      `rate: F/N failed; exits <code>x<count>...; timeouts T`. Every run counts:
      a failure never stops the count and no run is retried. Exit 1 if any run
      failed or timed out, 0 if none did, 2 if COMMAND cannot start (an
      environment failure, never the symptom) or the arguments are wrong.
  loop.py tag
      Print a fresh debug prefix such as `[DEBUG-a4f2]`.
  loop.py clean PREFIX
      From the root of the Git work tree around the current directory, from
      any subdirectory, search tracked and untracked, not ignored, files for
      PREFIX. Exit 0 `clean: ...` when none is left, 1 `left: ...` naming each
      root-relative file:line, 2 outside a Git tree or for a PREFIX that is
      not `[DEBUG-xxxx]`-shaped.
"""
import os
import re
import secrets
import subprocess
import sys
from collections import Counter

TAG = re.compile(r'\[DEBUG-[0-9A-Za-z]{2,16}\]')


def refuse(message):
    print(f'loop: {message}', file=sys.stderr)
    sys.exit(2)


def rate(args):
    runs, timeout = None, None
    if '--' not in args:
        refuse('usage: loop.py rate --runs N [--timeout SECONDS] -- COMMAND...')
    split = args.index('--')
    options, command = args[:split], args[split + 1:]
    while options:
        name, value, options = options[0], options[1] if len(options) > 1 else None, options[2:]
        try:
            if name == '--runs':
                runs = int(value)
            elif name == '--timeout':
                timeout = float(value)
            else:
                raise ValueError
        except (TypeError, ValueError):
            refuse(f'unreadable option {name}')
    if runs is None or runs < 1 or not command or (timeout is not None and timeout <= 0):
        refuse('usage: loop.py rate --runs N [--timeout SECONDS] -- COMMAND...')
    exits, timeouts = Counter(), 0
    for _ in range(runs):
        try:
            code = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            timeouts += 1
            continue
        except OSError:
            refuse('cannot start the command: an environment failure, not the symptom')
        exits[code] += 1
    failed = timeouts + sum(n for code, n in exits.items() if code != 0)
    shown = ' '.join(f'{code}x{n}' for code, n in sorted(exits.items())) or 'none'
    print(f'rate: {failed}/{runs} failed; exits {shown}; timeouts {timeouts}')
    return 1 if failed else 0


def clean(args):
    if len(args) != 1 or not TAG.fullmatch(args[0]):
        refuse('usage: loop.py clean [DEBUG-xxxx]')
    prefix = args[0]
    top = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True)
    if top.returncode != 0:
        refuse('not inside a Git work tree')
    root = os.fsdecode(top.stdout.rstrip(b'\n'))
    listed = subprocess.run(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
                            cwd=root, capture_output=True)
    if listed.returncode != 0:
        refuse('cannot list the Git work tree')
    left = []
    for path in sorted(set(filter(None, listed.stdout.decode('utf-8', 'surrogateescape').split('\0')))):
        try:
            with open(os.path.join(root, path), encoding='utf-8', errors='replace') as file:
                left += [f'{path}:{n}' for n, line in enumerate(file, 1) if prefix in line]
        except (FileNotFoundError, IsADirectoryError):
            continue  # deleted from the work tree, or a submodule
    if left:
        print(f'left: {len(left)} {prefix} in {", ".join(left)}')
        return 1
    print(f'clean: no {prefix} left')
    return 0


def main(argv):
    command, args = (argv[0], argv[1:]) if argv else (None, [])
    if command == 'rate':
        return rate(args)
    if command == 'tag' and not args:
        print(f'[DEBUG-{secrets.token_hex(2)}]')
        return 0
    if command == 'clean':
        return clean(args)
    refuse('usage: loop.py rate --runs N [--timeout SECONDS] -- COMMAND... | tag | clean PREFIX')


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
