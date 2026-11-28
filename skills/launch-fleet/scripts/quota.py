import argparse
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re
import sys
import time

sys.dont_write_bytecode = True

QUOTA_ERROR = re.compile(
    r"(?:individual quota reached|claude usage limit reached|you've hit your limit|"
    r"usage limit reached|quota exceeded|quota reached)",
    re.I,
)
ISO_RESET = re.compile(
    r"(?:resets?(?:\s+at)?|try again(?:\s+at)?)\s*[:·-]?\s*"
    r"([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2}))",
    re.I,
)
REL_RESET = re.compile(
    r"(?:resets?|try again)\s+in\s+((?:[0-9]+\s*[dhms](?![A-Za-z])[\s,]*)+)",
    re.I,
)
PART = re.compile(r"([0-9]+)\s*([dhms])(?![A-Za-z])", re.I)
UNIT = {'d': 86400, 'h': 3600, 'm': 60, 's': 1}


def parse_reset(text, now):
    m = ISO_RESET.search(text)
    if m:
        raw = m.group(1)
        try:
            dt = datetime.fromisoformat(raw.replace('Z', '+00:00')).astimezone(timezone.utc)
        except (ValueError, OverflowError):
            return None
        return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    m = REL_RESET.search(text)
    if m:
        secs = sum(int(n) * UNIT[u.lower()] for n, u in PART.findall(m.group(1)))
        if secs > 0:
            try:
                dt = datetime.fromtimestamp(now, tz=timezone.utc) + timedelta(seconds=secs)
            except (ValueError, OverflowError, OSError):
                return None
            return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    return None


def detect(text, now=None):
    if not text or not QUOTA_ERROR.search(text):
        return None
    if now is None:
        env_now = os.environ.get('LAUNCH_FLEET_NOW')
        now = int(env_now) if env_now and env_now.isdigit() else int(time.time())
    reset = parse_reset(text, now)
    if reset:
        return f'launch-fleet: start not tried: quota, resets {reset}'
    return 'launch-fleet: start not tried: quota'


def main(argv=None):
    parser = argparse.ArgumentParser(prog='quota.py')
    sub = parser.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('check')
    p.add_argument('--now', type=int, default=None)
    p.add_argument('--file', default=None)
    args = parser.parse_args(argv)
    try:
        if args.file is not None:
            text = Path(args.file).read_text(encoding='utf-8', errors='replace')
        else:
            text = sys.stdin.read()
    except OSError as error:
        print(f'quota: could not read input: {error.strerror or error}', file=sys.stderr)
        return 2
    record = detect(text, now=args.now)
    if record is None:
        print('ok')
        return 0
    print(record)
    return 1


if __name__ == '__main__':
    sys.exit(main())
