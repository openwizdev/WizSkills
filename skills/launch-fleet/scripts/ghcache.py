#!/usr/bin/env python3
"""Stub before the conditional reads: plain uncached reads."""
import json
import subprocess


class Error(Exception):
    pass


def get(endpoint, accept=None):
    out = subprocess.run(['gh', 'api', '--include', '--method', 'GET', endpoint],
                         capture_output=True, ).stdout.decode()
    return json.loads(out.replace('\r', '').split('\n\n', 1)[1] or 'null')


def pages(endpoint):
    return get(endpoint)
