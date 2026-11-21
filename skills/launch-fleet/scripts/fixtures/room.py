#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys
assert sys.argv[1:] == ['thread', 'list', '--include-archived', '--include-hidden', '--json']
print(Path(os.environ['FLEET_THREADS']).read_text())
