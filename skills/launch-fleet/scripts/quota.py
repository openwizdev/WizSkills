import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

sys.dont_write_bytecode = True

QUOTA_ERROR = re.compile(
    r"(?:individual quota reached|claude usage limit reached|you've hit your limit|"
    r"usage limit reached|(?<!disk )\bquota (?:exceeded|reached)\b)",
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
    if m and now is not None:
        try:
            secs = sum(int(n) * UNIT[u.lower()] for n, u in PART.findall(m.group(1)))
            if secs > 0:
                dt = datetime.fromtimestamp(now, tz=timezone.utc) + timedelta(seconds=secs)
                return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
        except (ValueError, OverflowError, OSError):
            return None
    return None


def detect(text, now):
    if not text or not QUOTA_ERROR.search(text):
        return None
    reset = parse_reset(text, now)
    if reset:
        return f'launch-fleet: start not tried: quota, resets {reset}'
    return 'launch-fleet: start not tried: quota'


def archived(thread):
    try:
        result = subprocess.run(
            ['room-cli', 'thread', 'archive', thread, '--json'],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=90,
        )
        answer = json.loads(result.stdout) if result.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False
    if not isinstance(answer, dict):
        return False
    if answer.get('id') == thread and answer.get('state') == 'archived':
        return True
    archived_ids = answer.get('archivedThreadIds')
    return (answer.get('ok') is True and answer.get('threadId') == thread
            and isinstance(archived_ids, list) and thread in archived_ids)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='quota.py')
    sub = parser.add_subparsers(dest='cmd', required=True)
    check = sub.add_parser('check')
    retire = sub.add_parser('retire')
    retire.add_argument('thread')
    for p in (check, retire):
        p.add_argument('--now', type=int)
        p.add_argument('--file')
    args = parser.parse_args(argv)
    if args.cmd == 'retire' and not re.fullmatch(r'thr_[A-Za-z0-9][A-Za-z0-9_-]*', args.thread):
        parser.error('retire requires a CloudRoom thread ID')
    try:
        if args.file is not None:
            text = Path(args.file).read_text(encoding='utf-8', errors='replace')
        else:
            text = sys.stdin.read()
    except OSError as error:
        print(f'quota: could not read input: {error.strerror or error}', file=sys.stderr)
        return 2
    now = args.now
    if args.cmd == 'check' and now is None:
        env_now = os.environ.get('LAUNCH_FLEET_NOW')
        now = int(env_now) if env_now and env_now.isdigit() else int(time.time())
    record = detect(text, now)
    if record is None:
        print('ok')
        return 0
    if args.cmd == 'retire' and not archived(args.thread):
        print('quota: archive was not confirmed; keep the start claimed', file=sys.stderr)
        return 2
    print(record)
    return 1


if __name__ == '__main__':
    sys.exit(main())
