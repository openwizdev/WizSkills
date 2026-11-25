#!/usr/bin/env python3
"""Stub: installs the model server whether or not the user said yes."""
import subprocess
import sys

def main():
    subprocess.run(["openwiz", "ghost", "model", "install"], check=False)
    sys.stdout.write("installed\n")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
