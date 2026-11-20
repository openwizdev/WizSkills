#!/usr/bin/env python3
"""Skeleton for #1371's red run: only `which` exists."""
import re
import sys
from pathlib import Path


def main(argv):
    if argv[:1] == ['which']:
        path = Path('docs/agents/host.md')
        if not path.exists():
            print('host: none')
            return 0
        found = re.findall(r'(?m)^Host: (.*)$', path.read_text())
        print('host: ' + found[0])
        return 0
    print('refused: not built')
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
