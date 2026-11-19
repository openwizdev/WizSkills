#!/usr/bin/env python3
"""build-ticket's lookups and records. Python 3.11+ standard library, `gh`, `git`.

  ticket.py read REPO N                     the ticket's owned paths, links and readiness
  ticket.py scope REPO N [--base REF] [--supporting PATH]...
                                            every changed path: owned, supporting or OUT
  ticket.py records REPO PR [--fleet-ref REF]
                                            the newest record-author verdict and decision
  ticket.py author                          set git's author to the GitHub user's noreply
  ticket.py push RECEIPT -- PUSH-COMMAND... run the push; keep the first success's receipt
  ticket.py post-receipt REPO PR RECEIPT    post the receipt once, read back

Exit 0 done, 1 refused (the last line says why), 2 an input it cannot read.
It prints a short result, never a log, and writes only what its command names.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys

LOGIN = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})(?:\[bot\])?')
SHA = re.compile(r'\b[0-9a-f]{40}\b')
REPO_QUALIFIER = re.compile(r'\s+in\s+`[\w.-]+/[\w.-]+`\s*$')


class Unreadable(Exception):
    pass


def run(argv, what):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        raise Unreadable(f'cannot read {what}')
    if r.returncode:
        raise Unreadable(f'cannot read {what}')
    return r.stdout


def gh_json(argv, what):
    try:
        return json.loads(run(['gh', *argv], what))
    except ValueError:
        raise Unreadable(f'cannot read {what}: not JSON')


def section(body, heading):
    lines, inside = [], False
    for line in body.splitlines():
        if line.startswith('## '):
            inside = line[3:].strip().lower() == heading
            continue
        if inside:
            lines.append(line)
    return lines


def owned_paths(body):
    """[(path or None, text)] for each bullet under `## Owned paths`."""
    out = []
    for line in section(body, 'owned paths'):
        if not line.startswith('- '):
            continue
        text = line[2:].strip()
        bare = REPO_QUALIFIER.sub('', text)
        m = re.match(r'`([^`\s]+)`(.*)$', bare)
        if m and m.group(1).strip() and '..' not in m.group(1).split('/'):
            out.append((m.group(1), (m.group(1) + m.group(2)).strip()))
        else:
            out.append((None, text))
    return out


def ticket(repo, n):
    data = gh_json(['issue', 'view', str(n), '--repo', repo, '--json',
                    'number,title,state,labels,body,blockedBy,blocking,parent'], f'ticket #{n}')
    if not isinstance(data, dict) or not isinstance(data.get('body'), str):
        raise Unreadable(f'cannot read ticket #{n}: unexpected shape')
    return data


def nodes(data, key):
    value = data.get(key) or {}
    return [x for x in value.get('nodes', []) if isinstance(x, dict)]


def cmd_read(repo, n):
    t = ticket(repo, n)
    labels = sorted(l.get('name', '') for l in t.get('labels', []))
    print(f'ticket #{t["number"]}: {t["title"]}')
    print(f'state: {t["state"]}; labels: {", ".join(labels) or "none"}')
    parent = t.get('parent') or {}
    print(f'spec: #{parent["number"]}' if parent.get('number') else 'spec: none')
    owned = owned_paths(t['body'])
    for path, text in owned:
        print(f'owned: {text}' if path else f'owned, not a path: {text}')
    relies = [l for l in t['body'].splitlines() if l.startswith('**Relies on:**')]
    for line in relies:
        print('relies on: ' + line[len('**Relies on:**'):].strip())
    blockers = nodes(t, 'blockedBy')
    for b in blockers:
        print(f'blocked by: #{b.get("number")} {b.get("state")}')
    for b in nodes(t, 'blocking'):
        print(f'blocks: #{b.get("number")} {b.get("state")}')
    open_blockers = [b for b in blockers if b.get('state') != 'CLOSED']
    if t['state'] != 'OPEN':
        why = f'the ticket is {t["state"]}'
    elif 'ready-for-agent' not in labels:
        why = 'no ready-for-agent label'
    elif 'needs-info' in labels:
        why = 'needs-info is open'
    elif open_blockers:
        why = ', '.join(f'#{b.get("number")}' for b in open_blockers) + ' is open'
    elif not any(path for path, _ in owned):
        why = 'no owned paths'
    else:
        print('ready: yes')
        return 0
    print(f'ready: no: {why}')
    return 1


def covers(rule, path):
    return path.startswith(rule) if rule.endswith('/') else path == rule


def changed(base):
    run(['git', 'rev-parse', '--verify', '--quiet', base + '^{commit}'], f'base {base}')
    paths = set()
    diff = run(['git', 'diff', '--name-status', '-z', '--find-renames', f'{base}...HEAD'], 'the diff')
    fields = diff.split('\0')
    i = 0
    while i < len(fields) and fields[i]:
        status = fields[i]
        count = 2 if status[:1] in ('R', 'C') else 1
        paths.update(fields[i + 1:i + 1 + count])
        i += 1 + count
    status = run(['git', 'status', '--porcelain=v1', '-z', '--untracked-files=all'], 'git status')
    fields = status.split('\0')
    i = 0
    while i < len(fields) and fields[i]:
        entry = fields[i]
        paths.add(entry[3:])
        if entry[:1] in ('R', 'C') or entry[1:2] in ('R', 'C'):
            i += 1
            paths.add(fields[i])
        i += 1
    return sorted(p for p in paths if p)


def cmd_scope(repo, n, base, supporting):
    owned = [path for path, _ in owned_paths(ticket(repo, n)['body']) if path]
    paths = changed(base)
    outside = 0
    for path in paths:
        if any(covers(rule, path) for rule in owned):
            print(f'owned: {path}')
        elif any(covers(rule, path) for rule in supporting):
            print(f'supporting: {path}')
        else:
            print(f'OUT: {path}')
            outside += 1
    if outside:
        print(f'scope: {outside} path(s) outside the owned paths: ask first')
        return 1
    print('scope: ok')
    return 0


def record_authors(ref):
    text = run(['git', 'show', f'{ref}:docs/agents/fleet.md'], f'docs/agents/fleet.md at {ref}')
    rows = [l for l in text.splitlines() if re.match(r'\|\s*Record authors\s*\|', l)]
    if len(rows) != 1:
        raise Unreadable('no single Record authors row: trust nobody')
    cell = rows[0].split('|')[2].strip()
    logins = [x.strip() for x in cell.split(',')] if cell else []
    names = [x[1:-1] if len(x) > 1 and x[0] == x[-1] == '`' else '' for x in logins]
    if not names or not all(LOGIN.fullmatch(x) for x in names):
        raise Unreadable('malformed Record authors row: trust nobody')
    return [x.lower() for x in names]


def comments(repo, number):
    pages = gh_json(['api', '--paginate', '--slurp', f'repos/{repo}/issues/{number}/comments'],
                    f'comments on #{number}')
    if not isinstance(pages, list) or not all(isinstance(p, list) for p in pages):
        raise Unreadable(f'cannot read comments on #{number}: unexpected shape')
    return [c for page in pages for c in page if isinstance(c, dict)]


def author_of(comment):
    user = comment.get('user')
    login = user.get('login') if isinstance(user, dict) else None
    return login.lower() if isinstance(login, str) else None


def cmd_records(repo, pr, ref):
    authors = record_authors(ref)
    items = comments(repo, pr)
    head = gh_json(['api', f'repos/{repo}/pulls/{pr}'], f'pull request #{pr}')
    head = (head.get('head') or {}).get('sha') if isinstance(head, dict) else None
    trusted = [c for c in items if author_of(c) in authors]
    print('authors: ' + ', '.join(authors))
    verdicts = [c for c in trusted if str(c.get('body', '')).lstrip().startswith('VERDICT:')]
    if verdicts:
        v = verdicts[-1]
        body = str(v.get('body', ''))
        named = SHA.search(body)
        named = named.group(0) if named else 'no head'
        current = 'yes' if head and named == head else f'no ({head or "unknown"})'
        print(f'verdict: comment {v.get("id")} by {author_of(v)} at {named}, current head: {current}')
        nxt = [l.strip() for l in body.splitlines() if l.strip().startswith('Next:')]
        print('next: ' + (nxt[-1] if nxt else 'none'))
    else:
        print('verdict: none')
    decisions = [c for c in trusted
                 if str(c.get('body', '')).lstrip().startswith('**Orchestrator decision:**')]
    if decisions:
        d = decisions[-1]
        first = str(d.get('body', '')).strip().splitlines()[0]
        print(f'decision: comment {d.get("id")} by {author_of(d)}: {first}')
    print(f'ignored: {len(items) - len(trusted)} comment(s) not by a record author')
    return 0


def cmd_author():
    user = gh_json(['api', 'user'], 'the GitHub user')
    login, uid = user.get('login'), user.get('id')
    if not (isinstance(login, str) and LOGIN.fullmatch(login) and isinstance(uid, int)):
        raise Unreadable('cannot read the GitHub user: unexpected shape')
    email = f'{uid}+{login}@users.noreply.github.com'
    run(['git', 'config', 'user.name', login], 'git config')
    run(['git', 'config', 'user.email', email], 'git config')
    print(f'author: {login} <{email}>')
    return 0


def outside_checkout(path):
    top = Path(run(['git', 'rev-parse', '--show-toplevel'], 'the checkout').strip()).resolve()
    target = Path(path)
    if not target.is_absolute():
        raise Unreadable('the receipt needs an absolute path outside the checkout')
    resolved = target.parent.resolve() / target.name
    if resolved == top or top in resolved.parents:
        raise Unreadable('the receipt needs an absolute path outside the checkout')
    return target


def cmd_push(receipt, command):
    target = outside_checkout(receipt)
    if not command:
        raise Unreadable('no push command after --')
    if subprocess.run(command).returncode:
        print('push failed: no receipt')
        return 1
    if target.exists():
        print(f'receipt kept: {target.read_text(encoding="utf-8").strip()}')
        return 0
    at = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    head = run(['git', 'rev-parse', 'HEAD'], 'HEAD').strip()
    line = f'First successful push: {head} at {at}\n'
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, 'x', encoding='utf-8') as f:
        f.write(line)
    print('receipt saved: ' + line.strip())
    return 0


def cmd_post_receipt(repo, pr, receipt):
    try:
        body = Path(receipt).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        raise Unreadable('cannot read the receipt file')
    if not re.fullmatch(r'First successful push: [0-9a-f]{40} at \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\n', body):
        raise Unreadable('the receipt file is not one receipt line')

    def existing():
        return next((c for c in comments(repo, pr) if c.get('body') == body), None)

    found = existing()
    if found:
        print(f'receipt reused: comment {found.get("id")}')
        return 0
    subprocess.run(['gh', 'api', '--method', 'POST', f'repos/{repo}/issues/{pr}/comments',
                    '-f', 'body=' + body], capture_output=True, timeout=120)
    found = existing()
    if found:
        print(f'receipt posted: comment {found.get("id")}')
        return 0
    print('receipt not posted: keep the file and run post-receipt again')
    return 1


def main(argv):
    try:
        if argv[:1] == ['read'] and len(argv) == 3:
            return cmd_read(argv[1], int(argv[2]))
        if argv[:1] == ['scope'] and len(argv) >= 3:
            base, supporting, rest = 'origin/main', [], argv[3:]
            while rest:
                if rest[0] == '--base' and len(rest) > 1:
                    base = rest[1]
                elif rest[0] == '--supporting' and len(rest) > 1:
                    supporting.append(rest[1])
                else:
                    raise ValueError
                rest = rest[2:]
            return cmd_scope(argv[1], int(argv[2]), base, supporting)
        if argv[:1] == ['records'] and len(argv) in (3, 5):
            ref = 'origin/main'
            if len(argv) == 5:
                if argv[3] != '--fleet-ref':
                    raise ValueError
                ref = argv[4]
            return cmd_records(argv[1], int(argv[2]), ref)
        if argv == ['author']:
            return cmd_author()
        if argv[:1] == ['push'] and len(argv) >= 4 and argv[2] == '--':
            return cmd_push(argv[1], argv[3:])
        if argv[:1] == ['post-receipt'] and len(argv) == 4:
            return cmd_post_receipt(argv[1], int(argv[2]), argv[3])
        raise ValueError
    except ValueError:
        print(__doc__.split('\n\n')[1], file=sys.stderr)
        return 2
    except Unreadable as e:
        print(f'ticket.py: {e}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
