#!/usr/bin/env python3
"""Write and check agent status: contracts/agent-status.v1.md (#1254).

  status.py write --repo OWNER/NAME --ticket N --state STATE --kind KIND
                  --harness TEXT --model TEXT --step TEXT [--pr URL] [--preview URL] [--time TIME]
  status.py check --repo OWNER/NAME

write: exit 0 written, 2 refused or failed (a refusal comes before any call).
check: exit 0 no mismatch, 1 mismatches printed, 2 could not read. It never writes.
Every GitHub call goes through `gh api`.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote

sys.dont_write_bytecode = True

MARKER = '<!-- openwiz.agent-status.v1 -->'
# Label, colour and description, as the contract's table fixes them.
LABELS = {
    'building': ('fbca04', 'An agent is building this ticket (openwiz.agent-status.v1)'),
    'in-review': ('0e8a16', 'Its pull request is in review (openwiz.agent-status.v1)'),
    'needs-you': ('d93f0b', 'An agent waits on the user (openwiz.agent-status.v1)'),
    'held': ('5319e7', 'Held (openwiz.agent-status.v1)'),
}
KINDS = ('builder', 'reviewer', 'fleet')
# Field, its name in the comment, and its longest value.
FIELDS = (('kind', 'Kind', 300), ('harness', 'Harness', 60), ('model', 'Model', 60),
          ('step', 'Last step', 300), ('time', 'Time', 300), ('pr', 'Pull request', 300),
          ('preview', 'Preview', 300))
REPO = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')
TIME = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z')
PR = re.compile(r'none|https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[1-9][0-9]*')
PREVIEW = re.compile(r'none|https://[^\s"<>]+')
CONTROL = re.compile(r'[\x00-\x1f\x7f]')
QUOTE = re.compile('["“”]')
# What the status never holds. A guard fails closed: every thr_ token, synthetic or not.
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


def refuse(field, why):
    raise Refused(f'{field}: {why}')


def checked(values):
    """Each field's value, or Refused naming the field (never echoing the value)."""
    for field, _, longest in FIELDS:
        value = values[field]
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
    if values['kind'] not in KINDS:
        refuse('kind', 'not builder, reviewer or fleet')
    if not TIME.fullmatch(values['time']):
        refuse('time', 'not YYYY-MM-DDTHH:MM:SSZ')
    if not PR.fullmatch(values['pr']):
        refuse('pr', 'not a GitHub pull request link')
    if not PREVIEW.fullmatch(values['preview']):
        refuse('preview', 'not an https link')
    return values


def body(values):
    lines = [MARKER, '**Agent status**', '']
    lines += [f'- **{name}:** {values[field]}' for field, name, _ in FIELDS]
    return '\n'.join(lines)


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
        items += chunk
        if not chunk:
            return items
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


def status_comment(comments, authors):
    """The earliest record author's comment whose first line is the marker."""
    for item in comments:
        user = item.get('user') or {}
        login = user.get('login') if isinstance(user, dict) else None
        text = item.get('body') or ''
        if isinstance(login, str) and login.lower() in authors and text.split('\n', 1)[0].rstrip('\r') == MARKER:
            return item
    return None


def write(args):
    values = checked({'kind': args.kind, 'harness': args.harness, 'model': args.model, 'step': args.step,
                      'time': args.time or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                      'pr': args.pr or 'none', 'preview': args.preview or 'none'})
    if args.state not in (*LABELS, 'none'):
        raise Refused('state: not building, in-review, needs-you, held or none')
    repo, n = args.repo, args.ticket
    authors = record_authors(repo)
    issue = gh('GET', f'repos/{repo}/issues/{n}')
    have = [label['name'] for label in issue['labels']]
    if args.state in LABELS:
        names = {label['name'].lower() for label in pages(f'repos/{repo}/labels')}
        if args.state not in names:
            color, description = LABELS[args.state]
            gh('POST', f'repos/{repo}/labels', {'name': args.state, 'color': color, 'description': description})
    for old in have:
        if old in LABELS and old != args.state:
            gh('DELETE', f'repos/{repo}/issues/{n}/labels/{quote(old, safe="")}')
    if args.state in LABELS and args.state not in have:
        gh('POST', f'repos/{repo}/issues/{n}/labels', {'labels': [args.state]})
    found = status_comment(pages(f'repos/{repo}/issues/{n}/comments'), authors)
    if found:
        gh('PATCH', f'repos/{repo}/issues/comments/{found["id"]}', {'body': body(values)})
        print(f'#{n}: {args.state}, status comment {found["id"]} edited')
    else:
        made = gh('POST', f'repos/{repo}/issues/{n}/comments', {'body': body(values)})
        print(f'#{n}: {args.state}, status comment {made["id"]} posted')


QUERY = '''query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    issues(states: OPEN, first: 100, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number
        labels(first: 100) { nodes { name } }
        closedByPullRequestsReferences(first: 50, includeClosedPrs: true) { nodes { number state url } }
      }
    }
  }
}'''


def mismatches(issue):
    labels = [label['name'] for label in issue['labels']['nodes'] if label['name'] in LABELS]
    prs = issue['closedByPullRequestsReferences']['nodes']
    merged = [pr['url'] for pr in prs if pr['state'] == 'MERGED']
    if len(labels) > 1:
        return f'{", ".join(labels)}: more than one state label'
    if labels and labels[0] in ('building', 'in-review', 'needs-you') and merged:
        return f'{labels[0]}: pull request {merged[0]} merged'
    if labels == ['in-review'] and not any(pr['state'] == 'OPEN' for pr in prs):
        return 'in-review: no open pull request closes it'
    return None


def check(args):
    owner, name = args.repo.split('/')
    cursor, found = None, []
    while True:
        try:
            page = gh('POST', 'graphql', {'query': QUERY,
                                          'variables': {'owner': owner, 'name': name, 'cursor': cursor}})
            issues = page['data']['repository']['issues']
            for issue in issues['nodes']:
                problem = mismatches(issue)
                if problem:
                    found.append(f'#{issue["number"]} {problem}')
            more, cursor = issues['pageInfo']['hasNextPage'], issues['pageInfo']['endCursor']
        except (KeyError, TypeError, IndexError) as error:
            raise Failed(f'unexpected GraphQL answer: {error!r}')
        if not more:
            break
    for line in found:
        print(line)
    return 1 if found else 0


def main(argv):
    parser = argparse.ArgumentParser(prog='status.py')
    sub = parser.add_subparsers(dest='command', required=True)
    w = sub.add_parser('write')
    for flag in ('--repo', '--ticket', '--state', '--kind', '--harness', '--model', '--step'):
        w.add_argument(flag, required=True)
    for flag in ('--pr', '--preview', '--time'):
        w.add_argument(flag)
    c = sub.add_parser('check')
    c.add_argument('--repo', required=True)
    args = parser.parse_args(argv)
    try:
        if not REPO.fullmatch(args.repo):
            raise Refused('repo: not OWNER/NAME')
        if args.command == 'check':
            try:
                return check(args)
            except Failed as error:
                raise Failed(f'could not read: {error}')
        if not re.fullmatch(r'[1-9][0-9]*', args.ticket):
            raise Refused('ticket: not an issue number')
        try:
            write(args)
        except (KeyError, TypeError, IndexError) as error:
            raise Failed(f'unexpected GitHub answer: {error!r}')
        return 0
    except Refused as error:
        print(f'status.py: refused: {error}', file=sys.stderr)
        return 2
    except Failed as error:
        print(f'status.py: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
