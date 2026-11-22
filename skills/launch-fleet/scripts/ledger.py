#!/usr/bin/env python3
import argparse
from decimal import Decimal, ROUND_HALF_UP
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
USAGE = '''The cost per merged PR ledger (CL2, #2285; spec #2275). Read-only.

  python3 -I ledger.py OWNER/NAME [--spec S] [--json]

It reads, through `gh api graphql`, every closed issue of OWNER/NAME (with
`--spec`, only spec S's closed sub-issues, wherever they live) and its comments
by the record authors (`docs/agents/fleet.md`'s `Record authors` row) whose
first line starts `launch-fleet: cost`. The newest such comment per ticket is
its row: `launch-fleet: cost: ... (PR #<P>): ...; total <t> credits, ...` gives
<t> credits; `cost unknown` or `total unknown` gives unknown, never zero. It
prints one row per merged pull request, `#<N>  PR #<P>  <credits or unknown>`,
then `Merged: <n>; known: <k>; unknown: <u>; total: <t> credits; cost per
merged PR: <t/k> credits (<k> of <n> known)`, two decimals; with no known row
the total and the cost per merged PR are `unknown`. `--json` prints the same
fields. A failed or partial read, or a record it can't read, prints nothing
and exits 1; bad arguments exit 2. It writes nothing.
'''
_spec = importlib.util.spec_from_file_location('launch_fleet_post', Path(__file__).resolve().parent / 'post.py')
post = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(post)

COMMENTS = ('comments(first: 100%s) { pageInfo { hasNextPage endCursor } '
            'nodes { author { __typename login } body } }')
ISSUE = 'number state repository { nameWithOwner } ' + COMMENTS % ''
CLOSED = ('query($owner: String!, $name: String!, $after: String) { repository(owner: $owner, name: $name) { '
          'issues(states: CLOSED, first: 50, after: $after) { pageInfo { hasNextPage endCursor } '
          'nodes { ' + ISSUE + ' } } } }')
SPEC = ('query($owner: String!, $name: String!, $number: Int!, $after: String) { '
        'repository(owner: $owner, name: $name) { issue(number: $number) { '
        'subIssues(first: 50, after: $after) { pageInfo { hasNextPage endCursor } nodes { ' + ISSUE + ' } } } } }')
MORE = ('query($owner: String!, $name: String!, $number: Int!, $after: String) { '
        'repository(owner: $owner, name: $name) { issue(number: $number) { ' + COMMENTS % ', after: $after' + ' } } }')
PR = r'\(PR ((?:[A-Za-z0-9-]+/[A-Za-z0-9_.-]+)?#[1-9][0-9]*)\)'
KNOWN = re.compile(r'launch-fleet: cost: Ticket #[1-9][0-9]* cost ' + PR + r': .*; total (?:([0-9]+(?:\.[0-9]+)?) credits|unknown)\b')
UNKNOWN = re.compile(r'launch-fleet: cost unknown ' + PR + r'(?::|$)')
CENT = Decimal('0.01')


class Failed(Exception):
    pass


def graphql(query, **fields):
    args = ['api', 'graphql', '-f', 'query=' + query]
    for key, value in fields.items():
        if value is not None:
            args += ['-F' if type(value) is int else '-f', f'{key}={value}']
    try:
        r = subprocess.run(['gh', *args], capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
        answer = json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        answer = None
    if not isinstance(answer, dict) or answer.get('errors') or not isinstance(answer.get('data'), dict):
        raise Failed('a GitHub read failed, so no ledger is printed')
    return answer['data']


def page_of(conn):
    info = conn['pageInfo']
    more, cursor = info['hasNextPage'], info['endCursor']
    if type(more) is not bool or not isinstance(conn['nodes'], list) or (more and not isinstance(cursor, str)):
        raise TypeError(conn)
    return conn['nodes'], (cursor if more else None)


def every(read):
    nodes, after = page_of(read(None))
    yield from nodes
    while after is not None:
        more, after = page_of(read(after))
        yield from more


def comments(where, issue):
    owner, name = where.split('/')
    nodes, after = page_of(issue['comments'])
    while after is not None:
        conn = graphql(MORE, owner=owner, name=name, number=issue['number'], after=after)
        more, after = page_of(conn['repository']['issue']['comments'])
        nodes += more
    return nodes


def rest_login(author):
    if not isinstance(author, dict) or not isinstance(author.get('login'), str):
        return None
    return author['login'] + '[bot]' if author.get('__typename') == 'Bot' else author['login']


def newest_cost_row(repo, where, issue, authors):
    newest = None
    for c in comments(where, issue):
        if not isinstance(c['body'], str):
            raise TypeError(c)
        first = c['body'].split('\n', 1)[0]
        if post.grants.authored(rest_login(c['author']), authors) and first.startswith('launch-fleet: cost'):
            newest = first
    if newest is None:
        return None
    ticket = ('' if where.casefold() == repo.casefold() else where) + f"#{issue['number']}"
    known, unknown = KNOWN.match(newest), UNKNOWN.match(newest)
    if known:
        return ticket, known.group(1), None if known.group(2) is None else Decimal(known.group(2))
    if unknown:
        return ticket, unknown.group(1), None
    raise Failed(f'the newest cost record on {ticket} could not be read, so no ledger is printed')


def ledger(repo, spec, authors):
    owner, name = repo.split('/')
    if spec is None:
        issues = every(lambda after: graphql(CLOSED, owner=owner, name=name, after=after)
                       ['repository']['issues'])
    else:
        def subs(after):
            found = graphql(SPEC, owner=owner, name=name, number=spec, after=after)['repository']['issue']
            if found is None:
                raise Failed(f'spec #{spec} could not be read, so no ledger is printed')
            return found['subIssues']
        issues = every(subs)
    rows = []
    try:
        for issue in issues:
            where = issue['repository']['nameWithOwner']
            if (type(issue['number']) is not int or issue['state'] not in ('OPEN', 'CLOSED')
                    or not isinstance(where, str) or not post.REPO.fullmatch(where)):
                raise TypeError(issue)
            if issue['state'] == 'CLOSED':
                found = newest_cost_row(repo, where, issue, authors)
                if found:
                    rows.append((where.casefold() != repo.casefold(), where.casefold(), issue['number'], found))
    except (TypeError, KeyError, AttributeError):
        raise Failed('a GitHub answer was not the expected shape, so no ledger is printed')
    return [r[-1] for r in sorted(rows)]


def money(value):
    return None if value is None else value.quantize(CENT, rounding=ROUND_HALF_UP)


def summary(rows):
    known = [c for _, _, c in rows if c is not None]
    total = sum(known, Decimal(0)) if known else None
    each = total / len(known) if known else None
    return {'merged': len(rows), 'known': len(known), 'unknown': len(rows) - len(known),
            'total': money(total), 'cost_per_merged_pr': money(each)}


def text(rows):
    s = summary(rows)
    lines = [f'{t}  PR {p}  {money(c) if c is not None else "unknown"}' for t, p, c in rows]
    total = 'unknown' if s['total'] is None else f"{s['total']} credits"
    each = 'unknown' if s['cost_per_merged_pr'] is None else f"{s['cost_per_merged_pr']} credits"
    lines.append(f"Merged: {s['merged']}; known: {s['known']}; unknown: {s['unknown']}; total: {total}; "
                 f"cost per merged PR: {each} ({s['known']} of {s['merged']} known)")
    return '\n'.join(lines) + '\n'


def number(value):
    return None if value is None else float(value)


def as_json(rows):
    s = summary(rows)
    s.update(total=number(s['total']), cost_per_merged_pr=number(s['cost_per_merged_pr']))
    return json.dumps({'rows': [{'ticket': t, 'pr': p, 'credits': number(money(c))} for t, p, c in rows], **s},
                      indent=2) + '\n'


def main():
    parser = argparse.ArgumentParser(description=USAGE, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('repo')
    parser.add_argument('--spec', type=int)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    if not post.REPO.fullmatch(args.repo) or (args.spec is not None and args.spec < 1):
        parser.error('want OWNER/NAME and a positive --spec')
    try:
        try:
            authors = post.authors(args.repo)
        except post.Stop as stop:
            raise Failed(str(stop))
        rows = ledger(args.repo, args.spec, authors)
    except Failed as failed:
        print(f'ledger: {failed}', file=sys.stderr)
        return 1
    sys.stdout.write(as_json(rows) if args.json else text(rows))
    return 0


if __name__ == '__main__':
    sys.exit(main())
