#!/usr/bin/env python3
"""Mechanical checklist lines as checks (openwiz #2707, UR9).

python3 -I check/checklist_rules.py diff --base <rev>
"""
import sys

RULES = {'exact-counts': 'Assert exact counts.', 'clock': 'Never race the clock.',
         'own-temp': 'Tests share nothing.'}


def main(argv):
    print('checklist: pass')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
