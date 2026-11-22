#!/usr/bin/env python3
import argparse
import sys


def main(argv):
    parser = argparse.ArgumentParser(prog='check/bench.py')
    parser.add_argument('--saved')
    parser.add_argument('--window')
    args = parser.parse_args(argv)
    print(f'Window: {args.window}')
    print('| Phase | Median (s) | Known |')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
