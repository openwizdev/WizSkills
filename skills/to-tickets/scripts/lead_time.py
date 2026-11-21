import argparse
import datetime
import json
import sys

SCHEMAS = ('openwiz.war-room.collector.v1', 'openwiz.war-room.collector.read.v1')


class Unreadable(Exception):
    pass


def moment(text):
    try:
        return datetime.datetime.fromisoformat(text.replace('Z', '+00:00'))
    except (AttributeError, ValueError):
        raise Unreadable(f'unreadable time {text!r}') from None


def unknown(n, why, start=None, end=None):
    return {'spec': n, 'lead_time_seconds': None, 'from': start, 'until': end, 'unknown': why}


def lead_time(row, tickets):
    n, members, start, end = row['spec'], row['tickets'], row['created_at'], row['last_merge_at']
    if not members:
        return unknown(n, 'its tickets are unknown' if members is None else 'it has no tickets', start, end)
    rows = {t['ticket']: t for t in tickets}
    for m in members:
        state = rows[m]['state'] if m in rows else 'unknown'
        if state != 'merged':
            why = f"#{m}'s state is unknown" if state == 'unknown' else f'#{m} is {state}'
            return unknown(n, why, start, end)
    if start is None:
        return unknown(n, 'its creation time is unknown', start, end)
    if end is None:
        return unknown(n, 'its last merge time is unknown', start, end)
    if moment(end) != max(moment(rows[m]['merged_at']) for m in members):
        raise Unreadable(f'spec #{n}: its last merge {end} is not its members\' latest')
    seconds = int((moment(end) - moment(start)).total_seconds())
    if seconds < 0 or row['span_seconds'] != seconds:
        raise Unreadable(f'spec #{n}: its span {row["span_seconds"]} disagrees with {start} to {end}')
    return {'spec': n, 'lead_time_seconds': seconds, 'from': start, 'until': end, 'unknown': None}


def report(document, asked):
    if not isinstance(document, dict) or document.get('schema') not in SCHEMAS:
        raise Unreadable("not the war-room collector's snapshot or read")
    fact = document['factory'].get('flow')
    if fact is None or fact['state'] == 'unavailable':
        return {'flow': 'unavailable', 'specs': [unknown(n, 'the flow fact is unavailable') for n in asked]}
    value = fact['value']
    specs = {row['spec']: row for row in value['specs']}
    numbers = asked or sorted(specs)
    rows = [lead_time(specs[n], value['tickets']) if n in specs else unknown(n, "not in the collector's flow fact")
            for n in numbers]
    return {'flow': fact['state'], 'specs': rows}


DESCRIPTION = "Spec lead time for the war room (#1353, F6): from the spec's creation to"


def main():
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument('collector')
    parser.add_argument('--spec', type=int, action='append', default=[])
    args = parser.parse_args()
    try:
        with open(args.collector, encoding='utf-8') as f:
            out = report(json.load(f), args.spec)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, AttributeError, Unreadable) as e:
        print(f'lead_time: {e}', file=sys.stderr)
        return 2
    print(json.dumps(out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
