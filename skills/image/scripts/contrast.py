#!/usr/bin/env python3
"""Skeleton: accepts arguments, measures nothing yet."""
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('colours', nargs='*')
parser.add_argument('--min')
parser.parse_args()
