#!/usr/bin/env python3
"""A synthetic stand-in for OpenWiz's kernel/driver-kit/kit.py, for write-driver's own tests only.

It writes its arguments, one per line, to the file FAKE_KIT_ARGV names, prints the file FAKE_KIT_OUT names
and exits FAKE_KIT_EXIT. The real kit is OpenWiz's; write-driver's eval (WD3) runs it.
"""
import os, sys
with open(os.environ['FAKE_KIT_ARGV'], 'w') as f:
    f.write('\n'.join(sys.argv[1:]) + '\n')
with open(os.environ['FAKE_KIT_OUT']) as f:
    sys.stdout.write(f.read())
sys.exit(int(os.environ.get('FAKE_KIT_EXIT', '0')))
