#!/usr/bin/env python3
"""Stub: keeps every rewrite, so a worsening bench is not reverted."""
import sys
from pathlib import Path

def main(argv):
    if len(argv) != 3 or argv[1] != "--home":
        sys.stdout.write("usage\n")
        return 2
    home = Path(argv[2])
    (home / "skill.json").write_text(
        '{"phrases":["worse"],"codes":[],"tone":"","never_suggest":[]}\n',
        encoding="utf-8")
    sys.stdout.write("kept\n")
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
