#!/usr/bin/env python3
"""Stub of the gh meter (OpenWiz#2621): a shim that only passes calls through."""
import os
from pathlib import Path
import sys

if sys.argv[1:2] == ['install']:
    d = Path(sys.argv[2])
    d.mkdir(parents=True, exist_ok=True)
    (d / 'gh').write_text('#!/bin/sh\nPATH="${PATH#*:}" exec gh "$@"\n')
    (d / 'gh').chmod(0o755)
