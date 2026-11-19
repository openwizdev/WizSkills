#!/usr/bin/env python3
"""Write and check agent status notes: contracts/agent-status.v1.md (#1254, revision 4).

  status.py write --repo OWNER/NAME --ticket N --agent KIND --state STATE [--why TEXT]
                  --harness TEXT --model TEXT --step TEXT [--pr URL] [--preview URL]
                  [--time TIME] [--note ID]
  status.py check --repo OWNER/NAME

write: exit 0 written, 2 refused or failed (a refusal comes before any call),
3 stop: the claim is another note's or the fence stopped it (nothing more written).
check: exit 0 no mismatch, 1 mismatches printed, 2 could not read. It never writes.
Every GitHub call goes through `gh api`.
"""
import argparse
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True

MARKER = '<!-- openwiz:status v1 -->'
LEASE = timedelta(minutes=30)
KINDS = ('builder', 'reviewer', 'fleet')
STATES = ('working', 'asking', 'done', 'stopped')
CLAIMING = ('working', 'asking')
ASKING_LABEL = 'needs-info'
# Key, longest value, required. The order is the note's line order.
KEYS = (('agent', 300, True), ('state', 300, True), ('harness', 60, True), ('model', 60, True),
        ('step', 300, True), ('time', 300, True), ('pr', 300, False), ('preview', 300, False))
REPO = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')
TIME = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z')
STATE = re.compile(r'(working|asking|done|stopped)( \(([^()]{1,100})\))?')
PR = re.compile(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[1-9][0-9]*')
PREVIEW = re.compile(r'https://[^\s"<>]+')
CONTROL = re.compile(r'[\x00-\x1f\x7f]')
QUOTE = re.compile('["“”]')
# What a note never holds. A guard fails closed: every thr_ token, synthetic or not.
PRIVATE = (
    ('a thread id', re.compile(r'(?<![A-Za-z0-9])thr_', re.I)),
    ('a CloudRoom id', re.compile(r'(?<![A-Za-z0-9])(?:proj|prj|mch|usr|acct|auto|cr)_[A-Za-z0-9]', re.I)),
    ('a machine path', re.compile(
        r'(?<![\w.:/~-])(?:~/|/(?:Users|home|root|tmp|var|private|mnt|Volumes|opt|srv|code)(?:/|\b))', re.I)),
    ('a machine path', re.compile(r'(?<![A-Za-z0-9])[A-Za-z]:\\')),
)


class Refused(Exception):
    pass


class Failed(Exception):
    pass


class Stop(Exception):
    pass


def refuse(field, why):
    raise Refused(f'{field}: {why}')


def plain(field, value, longest):
    if not value:
        refuse(field, 'empty')
    if CONTROL.search(value):
        refuse(field, 'not one line of plain text')
    if len(value) > longest:
        refuse(field, f'longer than {longest} characters')
    for what, pattern in PRIVATE:
        if pattern.search(value):
            refuse(field, f'holds {what}')
    if QUOTE.search(value) or value.startswith('>'):
        refuse(field, 'holds quoted words')


def shaped(fields):
    """Refused naming the field (never echoing the value), or None: the contract's shape."""
    for key, longest, required in KEYS:
        if key in fields:
            plain(key, fields[key], longest)
        elif required:
            refuse(key, 'missing')
    if fields['agent'] not in KINDS:
        refuse('agent', 'not builder, reviewer or fleet')
    if not STATE.fullmatch(fields['state']) or (fields['state'].startswith(('working', 'asking', 'done'))
                                                 and fields['state'] not in STATES):
        refuse('state', 'not working, asking, done, stopped or stopped (<why>)')
    if not TIME.fullmatch(fields['time']):
        refuse('time', 'not YYYY-MM-DDTHH:MM:SSZ')
    if 'pr' in fields and not PR.fullmatch(fields['pr']):
        refuse('pr', 'not a GitHub pull request link')
    if 'preview' in fields and not PREVIEW.fullmatch(fields['preview']):
        refuse('preview', 'not an https link')


def body(fields):
    return '\n'.join([MARKER] + [f'{key}: {fields[key]}' for key, _, _ in KEYS if key in fields])


def parse(text):
    """A note's fields, or None when it doesn't read exactly as the contract says."""
    lines = (text or '').replace('\r\n', '\n').split('\n')
    if lines[0] != MARKER:
        return None
    fields = {}
    for line in lines[1:]:
        key, sep, value = line.partition(': ')
        if not sep or key in fields or key not in dict((k, 0) for k, _, _ in KEYS):
            return None
        fields[key] = value
    try:
        shaped(fields)
    except Refused:
        return None
    return fields


def gh(method, path, payload=None, accept=None, raw=False):
    command = ['gh', 'api', '--method', method, path]
    if accept:
        command += ['-H', accept]
    if payload is not None:
        command += ['--input', '-']
    try:
        result = subprocess.run(command, input=None if payload is None else json.dumps(payload),
                                capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Failed(f'{method} {path}: {error}')
    if result.returncode != 0:
        raise Failed(f'{method} {path}: {result.stderr.strip()[:300]}')
    if raw:
        return result.stdout
    try:
        return json.loads(result.stdout) if result.stdout.strip() else None
    except ValueError:
        raise Failed(f'{method} {path}: not JSON')


def pages(path):
    """Every item of a paged REST list."""
    items, page = [], 1
    while True:
        chunk = gh('GET', f'{path}?per_page=100&page={page}')
        if not isinstance(chunk, list):
            raise Failed(f'GET {path}: not a list')
        if not chunk:
            return items
        items += chunk
        page += 1


def record_authors(repo):
    spec = importlib.util.spec_from_file_location('grants', Path(__file__).resolve().parent / 'grants.py')
    grants = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(grants)
    try:
        text = gh('GET', f'repos/{repo}/contents/docs/agents/fleet.md',
                  accept='Accept: application/vnd.github.raw', raw=True)
        return grants.record_authors(text)
    except (Failed, ValueError) as error:
        raise Failed(f'no record authors in docs/agents/fleet.md: {error}')


def when(stamp):
    return datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)


def notes(comments, authors):
    """The record authors' readable notes, oldest first: (id, fields, updated)."""
    found = []
    for item in comments:
        login = item['user']['login'] if isinstance(item.get('user'), dict) else None
        fields = parse(item.get('body'))
        if isinstance(login, str) and login.lower() in authors and fields:
            found.append((int(item['id']), fields, when(item['updated_at'])))
    return sorted(found, key=lambda n: n[0])


def live(note, now):
    return note[1]['state'] in CLAIMING and now - note[2] < LEASE


def holder(found, kind, now):
    """The oldest live note of KIND, which holds its claim, or None."""
    return next((n for n in found if n[1]['agent'] == kind and live(n, now)), None)


def write(args, now):
    state = args.state if args.why is None else f'{args.state} ({args.why})'
    if args.why is not None and args.state != 'stopped':
        refuse('state', 'only stopped carries a reason')
    fields = {'agent': args.agent, 'state': state, 'harness': args.harness, 'model': args.model,
              'step': args.step, 'time': args.time or now.strftime('%Y-%m-%dT%H:%M:%SZ')}
    for key in ('pr', 'preview'):
        if getattr(args, key) is not None:
            fields[key] = getattr(args, key)
    shaped(fields)
    if args.note is not None and not re.fullmatch(r'[1-9][0-9]*', args.note):
        refuse('note', 'not a comment id')
    repo, n, kind = args.repo, args.ticket, args.agent
    authors = record_authors(repo)
    comments = f'repos/{repo}/issues/{n}/comments'
    labels = [label['name'] for label in gh('GET', f'repos/{repo}/issues/{n}')['labels']]
    found = notes(pages(comments), authors)
    claiming = args.state in CLAIMING
    if args.note is not None:
        own = next((x for x in found if x[0] == int(args.note)), None)
        if own is None:
            raise Stop(f'note {args.note} is not a record author\'s status note on #{n}')
        if own[1]['agent'] != kind:
            raise Stop(f'note {args.note} is a {own[1]["agent"]} note')
        if own[1]['state'].startswith('stopped'):
            raise Stop(f'note {args.note} is stopped')
        first = holder(found, kind, now)
        if first and first[0] < own[0]:
            raise Stop(f'note {first[0]} holds the {kind} claim')
        was = own[1]['state']
        gh('PATCH', f'repos/{repo}/issues/comments/{own[0]}', {'body': body(fields)})
        note_id, verb = own[0], 'edited'
    else:
        first = holder(found, kind, now)
        if claiming and first:
            raise Stop(f'note {first[0]} holds the {kind} claim')
        made = gh('POST', comments, {'body': body(fields)})
        note_id, verb, was = int(made['id']), 'posted', None
        if claiming:
            first = holder(notes(pages(comments), authors), kind, datetime.now(timezone.utc))
            if first and first[0] < note_id:
                gh('PATCH', f'repos/{repo}/issues/comments/{note_id}',
                   {'body': body(dict(fields, state='stopped (lost claim)'))})
                raise Stop(f'note {first[0]} holds the {kind} claim; note {note_id} is stopped (lost claim)')
    if args.state == 'asking' and ASKING_LABEL not in labels:
        gh('POST', f'repos/{repo}/issues/{n}/labels', {'labels': [ASKING_LABEL]})
    if was == 'asking' and args.state != 'asking' and ASKING_LABEL in labels:
        gh('DELETE', f'repos/{repo}/issues/{n}/labels/{ASKING_LABEL}')
    print(f'#{n}: {kind} {state}, status note {note_id} {verb}')


QUERY = '''query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    issues(states: OPEN, first: 50, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number
        labels(first: 100) { nodes { name } }
        comments(first: 100) { pageInfo { hasNextPage } nodes { databaseId author { login } body updatedAt } }
        closedByPullRequestsReferences(first: 50, includeClosedPrs: true) { nodes { number state url } }
      }
    }
  }
}'''


def mismatches(number, labels, found, prs, now):
    lines = []
    merged = [pr['url'] for pr in prs if pr['state'] == 'MERGED']
    for note in found:
        nid, fields, updated = note
        state, kind = fields['state'], fields['agent']
        if state not in CLAIMING:
            continue
        head = f'#{number} note {nid} {kind} {state}'
        first = holder(found, kind, now)
        if merged:
            lines.append(f'{head}: pull request {merged[0]} merged')
        elif not live(note, now):
            lines.append(f'{head}: lapsed, no edit for 30 minutes')
        elif state == 'asking' and ASKING_LABEL not in labels:
            lines.append(f'{head}: no {ASKING_LABEL} label')
        elif first[0] != nid:
            lines.append(f'{head}: note {first[0]} holds the {kind} claim')
    return lines


def check(args, now):
    owner, name = args.repo.split('/')
    authors = record_authors(args.repo)
    cursor, found = None, []
    while True:
        page = gh('POST', 'graphql', {'query': QUERY,
                                      'variables': {'owner': owner, 'name': name, 'cursor': cursor}})
        issues = page['data']['repository']['issues']
        for issue in issues['nodes']:
            if issue['comments']['pageInfo']['hasNextPage']:
                comments = pages(f'repos/{args.repo}/issues/{issue["number"]}/comments')
            else:
                comments = [{'id': c['databaseId'], 'user': c['author'], 'body': c['body'],
                             'updated_at': c['updatedAt']} for c in issue['comments']['nodes']]
            found += mismatches(issue['number'], [label['name'] for label in issue['labels']['nodes']],
                                notes(comments, authors), issue['closedByPullRequestsReferences']['nodes'], now)
        if not issues['pageInfo']['hasNextPage']:
            break
        cursor = issues['pageInfo']['endCursor']
    for line in found:
        print(line)
    return 1 if found else 0


def main(argv):
    parser = argparse.ArgumentParser(prog='status.py')
    sub = parser.add_subparsers(dest='command', required=True)
    w = sub.add_parser('write')
    for flag in ('--repo', '--ticket', '--agent', '--state', '--harness', '--model', '--step'):
        w.add_argument(flag, required=True)
    for flag in ('--why', '--pr', '--preview', '--time', '--note'):
        w.add_argument(flag)
    c = sub.add_parser('check')
    c.add_argument('--repo', required=True)
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    try:
        if not REPO.fullmatch(args.repo):
            raise Refused('repo: not OWNER/NAME')
        if args.command == 'check':
            try:
                return check(args, now)
            except Failed as error:
                raise Failed(f'could not read: {error}')
            except (KeyError, TypeError, IndexError, ValueError) as error:
                raise Failed(f'could not read: unexpected GitHub answer: {error!r}')
        if not re.fullmatch(r'[1-9][0-9]*', args.ticket):
            raise Refused('ticket: not an issue number')
        try:
            write(args, now)
        except (KeyError, TypeError, IndexError, ValueError) as error:
            raise Failed(f'unexpected GitHub answer: {error!r}')
        return 0
    except Refused as error:
        print(f'status.py: refused: {error}', file=sys.stderr)
        return 2
    except Stop as error:
        print(f'status.py: stop: {error}', file=sys.stderr)
        return 3
    except Failed as error:
        print(f'status.py: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
