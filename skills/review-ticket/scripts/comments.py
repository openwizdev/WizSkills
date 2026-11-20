#!/usr/bin/env python3
import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="review-ticket's comment pass over one pull request's diff.")
    parser.add_argument("diff", help="the diff file, or - for standard input")
    parser.add_argument("--docs", action="append", default=[])
    parser.parse_args()
    return 0


if __name__ == "__main__":
    sys.exit(main())
