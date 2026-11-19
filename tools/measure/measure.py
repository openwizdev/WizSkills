#!/usr/bin/env python3
"""Workflow measurement receipt."""
import json
import sys


def main():
    record = json.load(sys.stdin)
    print(json.dumps({"case": record["case"]}))


if __name__ == "__main__":
    main()
