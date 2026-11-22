#!/usr/bin/env python3
"""REST read budget (#2433, FR3): a stub until the gate is written."""
import json
import sys

print(json.dumps({'allowed': True, 'remaining': 4000, 'limit': 5000, 'reset': 1900001800, 'reason': 'stub'}))
sys.exit(0)
