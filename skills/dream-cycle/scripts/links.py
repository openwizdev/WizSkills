#!/usr/bin/env python3
import argparse
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="links.py",
        description="Dream-cycle link funnel: candidates, Gate A check, score, ledger, and canaries.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("candidates", "check", "score", "ledger", "canaries"):
        sub.add_parser(name)
    parser.parse_known_args(argv)
    print("links.py: not implemented (DC6 #3133)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
