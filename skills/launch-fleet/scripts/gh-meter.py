#!/usr/bin/env python3
from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys

USAGE = """A `gh` meter: who spends the GitHub allowance (OpenWiz#2621, FR5 of #2428).

gh-meter.py install DIR    write DIR/gh, a shim that runs the real `gh`
gh-meter.py report LOG...  calls and REST units per role and per endpoint,
                           and the top five endpoints by REST units

Put DIR first on PATH. The shim runs the next `gh` on PATH after DIR (or
GH_METER_REAL) with the caller's arguments, input, output and exit status;
a `gh` before DIR (a caller's own wrapper that runs the shim) is never it.
It exits 127, running nothing, when DIR is not on PATH, when no `gh` follows
it, when it is entered again from its own real `gh`'s run, or when it can't
open GH_METER_LOG for appending. GH_METER_REAL, when set, is run as given:
the PATH checks above don't apply to it (the re-entry check does).
`install` refuses, writing nothing, when DIR/gh exists in any form, a symlink
included: it creates the shim exclusively and never follows a link.
When GH_METER_LOG is set, it appends one JSON line per call:

  time, role (GH_METER_ROLE: fleet, builder, reviewer, orchestrator,
  heartbeat, other; anything else is other), method, endpoint, kind (rest,
  graphql, or none for a local command such as `gh auth`), exit, rest_units,
  uncertain, rest_used_before and rest_used_after, and status for an
  --include read whose response header block was verified.

Only fixed words reach the log. method is an HTTP method from GET, POST,
PATCH, PUT, DELETE and HEAD, or a known gh subcommand; anything else is
`other`. endpoint is a route template from ROUTES, matched segment by
segment: a word is kept only where its route has that word, every dynamic
segment becomes its route's placeholder (:owner, :repo, :team, :n for
digits only, :sha, :path, :ref, :branch, :name, ...), so a slug that equals
a known word is still a placeholder, and from the first segment no route
has, that segment and every one after it is :x. The query string is
dropped. A command, or an API path root, the meter does not know (an
alias, say) is logged as endpoint `unknown`, method `other`.

rest_used_* is REST's `used` from `gh api rate_limit`, which costs no
allowance, read just before and after the call; null when unreadable, when
GH_METER_RATE=0 (fixture runs, where the fake has no allowance), and, for
after, when the allowance reset between the two reads. On a shared account
other agents' calls land between the two reads, so their difference is a
shared-account observation, not this call's own cost.

rest_units is this call's own REST requests, counted, not measured: one for
a REST call, none for a 304, GraphQL, `rate_limit` and local commands. A
status counts only from a verified response header block: a status line,
header lines and a blank line, at the start of the output or, for
--paginate --include, right after a non-empty page body that parses as
JSON; only the last body may be empty, and the split must be the only one
the output allows. When the page count or the status can't be established
(no verified block, a body that isn't JSON under --paginate,
--paginate without --include or under --jq or --template, a conditional
header without --include, an unknown command) the call counts one and
uncertain is true: a lower bound.

The log never holds a token, a body, an argument value or any response
header: only the fields above. If the log write fails after the call, the
shim warns on stderr and keeps the call's exit status. Exit 2 on bad
arguments or an unreadable log.
"""
FIELDS = ('time', 'role', 'method', 'endpoint', 'kind', 'exit', 'rest_units', 'uncertain', 'rest_used_before',
          'rest_used_after')
ROLES = ('fleet', 'builder', 'reviewer', 'orchestrator', 'heartbeat', 'other')
METHODS = {'GET', 'POST', 'PATCH', 'PUT', 'DELETE', 'HEAD'}
LOCAL = {'auth', 'config', 'alias', 'help', 'version', 'completion', 'extension', '--version', '--help'}
GRAPHQL = {'issue', 'pr', 'repo', 'project'}
REST_COMMANDS = {'api', 'run', 'workflow', 'release', 'label', 'search', 'gist', 'secret', 'variable', 'cache',
                 'ruleset', 'browse', 'status', 'codespace', 'org', 'ssh-key', 'gpg-key', 'attestation'}
VERBS = {'view', 'list', 'create', 'edit', 'comment', 'close', 'reopen', 'merge', 'checks', 'diff', 'review',
         'ready', 'status', 'checkout', 'delete', 'rerun', 'watch', 'download', 'clone', 'fork', 'sync', 'run',
         'enable', 'disable', 'set', 'get', 'token', 'login', 'logout', 'setup-git', 'refresh', 'switch',
         'develop', 'lock', 'unlock', 'pin', 'unpin', 'transfer', 'upload', 'archive', 'unarchive', 'rename',
         'cancel', 'issues', 'prs', 'code', 'commits', 'repos', 'item-list', 'item-add', 'field-list', 'copy',
         'update-branch', 'install', 'upgrade', 'remove', 'export', 'import', 'verify'}
ROUTES = """
repos/:owner/:repo/issues/:n/comments repos/:owner/:repo/issues/:n/events repos/:owner/:repo/issues/:n/timeline
repos/:owner/:repo/issues/:n/labels/:name repos/:owner/:repo/issues/:n/assignees repos/:owner/:repo/issues/:n/lock
repos/:owner/:repo/issues/:n/reactions repos/:owner/:repo/issues/:n/sub_issues/priority
repos/:owner/:repo/issues/:n/sub_issue repos/:owner/:repo/issues/:n/parent
repos/:owner/:repo/issues/:n/dependencies/blocked_by/:n repos/:owner/:repo/issues/:n/dependencies/blocking
repos/:owner/:repo/issues/comments/:n/reactions repos/:owner/:repo/issues/events/:n
repos/:owner/:repo/pulls/:n/files repos/:owner/:repo/pulls/:n/commits repos/:owner/:repo/pulls/:n/merge
repos/:owner/:repo/pulls/:n/requested_reviewers repos/:owner/:repo/pulls/:n/update-branch
repos/:owner/:repo/pulls/:n/reviews/:n/comments repos/:owner/:repo/pulls/:n/reviews/:n/events
repos/:owner/:repo/pulls/:n/reviews/:n/dismissals repos/:owner/:repo/pulls/:n/comments/:n/replies
repos/:owner/:repo/pulls/comments/:n/reactions
repos/:owner/:repo/commits/:sha/check-runs repos/:owner/:repo/commits/:sha/check-suites
repos/:owner/:repo/commits/:sha/status repos/:owner/:repo/commits/:sha/statuses repos/:owner/:repo/commits/:sha/pulls
repos/:owner/:repo/commits/:sha/comments repos/:owner/:repo/commits/:sha/branches-where-head
repos/:owner/:repo/statuses/:sha repos/:owner/:repo/check-runs/:n/annotations repos/:owner/:repo/check-runs/:n/rerun
repos/:owner/:repo/check-suites/:n/check-runs repos/:owner/:repo/check-suites/:n/rerequest
repos/:owner/:repo/git/ref/:ref* repos/:owner/:repo/git/refs/:ref* repos/:owner/:repo/git/matching-refs/:ref*
repos/:owner/:repo/git/trees/:sha repos/:owner/:repo/git/blobs/:sha repos/:owner/:repo/git/commits/:sha
repos/:owner/:repo/git/tags/:sha repos/:owner/:repo/contents/:path* repos/:owner/:repo/readme/:path*
repos/:owner/:repo/branches/:branch/protection repos/:owner/:repo/compare/:range* repos/:owner/:repo/tarball/:ref*
repos/:owner/:repo/zipball/:ref* repos/:owner/:repo/merges
repos/:owner/:repo/actions/runs/:n/jobs repos/:owner/:repo/actions/runs/:n/logs
repos/:owner/:repo/actions/runs/:n/artifacts repos/:owner/:repo/actions/runs/:n/rerun
repos/:owner/:repo/actions/runs/:n/rerun-failed-jobs repos/:owner/:repo/actions/runs/:n/cancel
repos/:owner/:repo/actions/runs/:n/approve repos/:owner/:repo/actions/runs/:n/attempts/:n/jobs
repos/:owner/:repo/actions/runs/:n/pending_deployments repos/:owner/:repo/actions/jobs/:n/logs
repos/:owner/:repo/actions/jobs/:n/rerun repos/:owner/:repo/actions/workflows/:workflow/runs
repos/:owner/:repo/actions/workflows/:workflow/dispatches repos/:owner/:repo/actions/workflows/:workflow/enable
repos/:owner/:repo/actions/workflows/:workflow/disable repos/:owner/:repo/actions/artifacts/:n/:format
repos/:owner/:repo/actions/secrets/:name repos/:owner/:repo/actions/variables/:name repos/:owner/:repo/actions/caches
repos/:owner/:repo/releases/:n/assets repos/:owner/:repo/releases/latest repos/:owner/:repo/releases/tags/:tag
repos/:owner/:repo/releases/assets/:n repos/:owner/:repo/labels/:name repos/:owner/:repo/milestones/:n
repos/:owner/:repo/collaborators/:owner/permission repos/:owner/:repo/assignees/:owner repos/:owner/:repo/hooks/:n
repos/:owner/:repo/deployments/:n/statuses repos/:owner/:repo/environments/:name repos/:owner/:repo/rulesets/:n
repos/:owner/:repo/rules/branches/:branch* repos/:owner/:repo/topics repos/:owner/:repo/languages
repos/:owner/:repo/contributors repos/:owner/:repo/forks repos/:owner/:repo/keys/:n repos/:owner/:repo/pages
repos/:owner/:repo/codeowners/errors repos/:owner/:repo/dispatches repos/:owner/:repo/events
repos/:owner/:repo/teams repos/:owner/:repo/subscription
user/repos user/orgs user/emails user/keys user/teams user/installations user/subscriptions
users/:owner/repos users/:owner/orgs users/:owner/events users/:owner/keys
orgs/:owner/repos orgs/:owner/members/:owner orgs/:owner/installations orgs/:owner/teams/:team/members
orgs/:owner/teams/:team/repos orgs/:owner/teams/:team/memberships/:owner
orgs/:owner/actions/secrets/:name orgs/:owner/actions/variables/:name
search/issues search/code search/commits search/repositories search/users search/labels search/topics
rate_limit graphql meta markdown events organizations repositories/:n installation/repositories
notifications/threads/:n/subscription gists/:gist/comments/:n app/installations/:n/access_tokens teams/:n/members
"""


def route_tree(routes):
    root = {}
    for route in routes.split():
        node = root
        for part in route.split('/'):
            node = node.setdefault(part, {})
    nodes = [root]
    while nodes:
        node = nodes.pop()
        names = [k for k in node if k.startswith(':')]
        if len(names) > 1 or (names not in ([], [':n']) and len(node) > 1):
            raise ValueError('a route position mixes a named placeholder with other words: %s' % sorted(node))
        nodes += node.values()
    return root


TREE = route_tree(ROUTES)
VALUE_FLAGS = {'-X', '--method', '-H', '--header', '-f', '--raw-field', '-F', '--field', '--input', '-q', '--jq',
               '-t', '--template', '--cache', '--hostname', '-p', '--preview'}
BODY_FLAGS = {'-f', '--raw-field', '-F', '--field', '--input'}
FILTER_FLAGS = {'-q', '--jq', '-t', '--template'}
CONDITIONAL = re.compile(r'\s*if-(none-match|modified-since)\s*:', re.I)
NUMBER = re.compile(r'[0-9]+')
STATUS = re.compile(rb'HTTP/[0-9.]+ ([0-9]{3})( [^\r\n]*)?\r?')
HEADER = re.compile(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+:[^\r\n]*\r?")


def fail(message):
    print('gh-meter: %s' % message, file=sys.stderr)
    sys.exit(2)


def template(path):
    parts = re.sub(r'^https://api\.github\.com/', '', path.split('?', 1)[0]).strip('/').split('/')
    if parts[0] not in TREE:
        return 'unknown'
    node, out = TREE, []
    for i, part in enumerate(parts):
        names = [k for k in node if k.startswith(':')]
        if part in node and not part.startswith(':'):
            out.append(part)
            node = node[part]
        elif names == [':n'] and NUMBER.fullmatch(part):
            out.append(':n')
            node = node[':n']
        elif names and names != [':n']:
            out.append(names[0].rstrip('*'))
            if names[0].endswith('*'):
                break
            node = node[names[0]]
        else:
            out += [':x'] * (len(parts) - i)
            break
    return '/'.join(out)


def parse_api(args):
    method, endpoint, body = None, None, False
    call = {'include': False, 'paginate': False, 'filtered': False, 'conditional': False, 'unknown': False}
    i = 0
    while i < len(args):
        a = args[i]
        name = a.split('=', 1)[0] if a.startswith('--') else a
        value = a.split('=', 1)[1] if a.startswith('--') and '=' in a else None
        if name in VALUE_FLAGS:
            if value is None:
                i += 1
                value = args[i] if i < len(args) else ''
            if name in ('-X', '--method'):
                method = value.upper()
            body = body or name in BODY_FLAGS
            call['filtered'] = call['filtered'] or name in FILTER_FLAGS
            call['conditional'] = call['conditional'] or (name in ('-H', '--header')
                                                          and bool(CONDITIONAL.match(value)))
        elif a.startswith('-X') and not a.startswith('--'):
            method = a[2:].upper()
        elif name in ('-i', '--include'):
            call['include'] = True
        elif name == '--paginate':
            call['paginate'] = True
        elif not a.startswith('-') and endpoint is None:
            endpoint = a
        i += 1
    endpoint = template(endpoint or '')
    method = method or ('POST' if body or endpoint == 'graphql' else 'GET')
    call.update(method=method if method in METHODS else 'other', endpoint=endpoint,
                kind='graphql' if endpoint == 'graphql' else 'rest', unknown=endpoint == 'unknown')
    return call


def parse(args):
    if args[:1] == ['api']:
        return parse_api(args[1:])
    words, skip = [], False
    for a in args:
        if skip or a.startswith('-'):
            skip = a in ('-R', '--repo')
            continue
        words.append(a)
    command = words[0] if words else (args[0] if args else '')
    verb = words[1] if len(words) > 1 else ''
    verb = verb if verb in VERBS or not verb else 'other'
    call = {'include': False, 'paginate': False, 'filtered': False, 'conditional': False, 'unknown': False}
    if command in LOCAL or not args:
        call.update(method=verb, endpoint=' '.join([command, verb]).strip(), kind='none')
    elif command in GRAPHQL or command in REST_COMMANDS:
        call.update(method=verb, endpoint=' '.join([command, verb]).strip(),
                    kind='graphql' if command in GRAPHQL else 'rest')
    else:
        call.update(method='other', endpoint='unknown', kind='rest', unknown=True)
    return call


def header_block(lines, i):
    if i >= len(lines) or not STATUS.fullmatch(lines[i]):
        return None
    j = i + 1
    while j < len(lines) and HEADER.fullmatch(lines[j]):
        j += 1
    if i + 1 < j < len(lines) and lines[j] in (b'', b'\r'):
        return int(STATUS.fullmatch(lines[i]).group(1)), j + 1
    return None


def is_json(lines, empty=False):
    text = b'\n'.join(lines).strip()
    if not text:
        return empty
    try:
        json.loads(text)
    except ValueError:
        return False
    return True


def statuses(out, paginate):
    lines = out.split(b'\n')
    first = header_block(lines, 0)
    if first is None:
        return None
    if not paginate:
        return [first[0]]
    found, at = [first[0]], first[1]
    while True:
        pages = [j for j in range(at, len(lines)) if header_block(lines, j) and is_json(lines[at:j])]
        last = is_json(lines[at:], empty=True)
        if len(pages) + last != 1:
            return None
        if last:
            return found
        status, at = header_block(lines, pages[0])
        found.append(status)


def real_gh():
    if os.environ.get('GH_METER_ACTIVE'):
        refuse('the shim called itself: a gh after it on PATH runs the shim again')
    os.environ['GH_METER_ACTIVE'] = '1'
    if os.environ.get('GH_METER_REAL'):
        return os.environ['GH_METER_REAL']
    shim = os.path.realpath(os.environ.get('GH_METER_SHIM_DIR', ''))
    dirs = os.environ.get('PATH', '').split(os.pathsep)
    at = [i for i, d in enumerate(dirs) if d and os.path.realpath(d) == shim]
    if not at:
        refuse("the shim's directory is not on PATH")
    for d in dirs[at[-1] + 1:]:
        candidate = os.path.join(d, 'gh')
        if d and os.path.realpath(d) != shim and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    refuse('no real gh on PATH after the shim')


def refuse(message):
    print('gh-meter: %s' % message, file=sys.stderr)
    sys.exit(127)


def rest_used(gh):
    if os.environ.get('GH_METER_RATE') == '0':
        return None, None
    try:
        run = subprocess.run([gh, 'api', 'rate_limit'], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        core = json.loads(run.stdout)['resources']['core'] if run.returncode == 0 else {}
        used, reset = core.get('used'), core.get('reset')
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None, None
    return (used if isinstance(used, int) and not isinstance(used, bool) else None), reset


def shim(args):
    gh = real_gh()
    log = os.environ.get('GH_METER_LOG')
    if not log:
        os.execv(gh, [gh, *args])
    try:
        fd = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC, 0o600)
    except OSError as e:
        refuse("can't open the log for appending (%s); gh was not run" % e.strerror)
    call = parse(args)
    free = call['kind'] != 'rest' or call['endpoint'] == 'rate_limit'
    before, reset = (None, None) if call['kind'] == 'none' else rest_used(gh)
    if call['include']:
        run = subprocess.run([gh, *args], stdout=subprocess.PIPE)
        sys.stdout.buffer.write(run.stdout)
        sys.stdout.buffer.flush()
        found = None if call['filtered'] and call['paginate'] else statuses(run.stdout, call['paginate'])
    else:
        run = subprocess.run([gh, *args])
        found = None if call['paginate'] or call['conditional'] or call['unknown'] else []
    after, reset_after = (None, None) if call['kind'] == 'none' else rest_used(gh)
    if reset != reset_after:
        after = None
    role = os.environ.get('GH_METER_ROLE', 'other')
    line = {'time': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'role': role if role in ROLES else 'other', 'method': call['method'], 'endpoint': call['endpoint'],
            'kind': call['kind'], 'exit': run.returncode,
            'rest_units': 0 if free else sum(s != 304 for s in found) if found else 1,
            'uncertain': not free and found is None, 'rest_used_before': before, 'rest_used_after': after}
    if found:
        line['status'] = found[-1]
    data = (json.dumps(line) + '\n').encode()
    try:
        if os.write(fd, data) != len(data):
            raise OSError(0, 'a short write')
    except OSError as e:
        print("gh-meter: warning: this call's log line was not written (%s)" % e.strerror, file=sys.stderr)
    finally:
        os.close(fd)
    sys.exit(run.returncode)


def install(d):
    d = Path(d).resolve()
    paths = (str(d), sys.executable, str(Path(__file__).resolve()))
    if any("'" in p for p in paths):
        fail("a path with a ' can't be quoted in the shim")
    d.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(d / 'gh', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o755)
    except FileExistsError:
        fail('%s exists: install writes only a new shim, never over a file or a link' % (d / 'gh'))
    except OSError as e:
        fail("can't create %s: %s" % (d / 'gh', e.strerror))
    try:
        os.write(fd, ("#!/bin/sh\nGH_METER_SHIM_DIR='%s' exec '%s' -I '%s' exec \"$@\"\n" % paths).encode())
        os.fchmod(fd, 0o755)
    finally:
        os.close(fd)


def unique(pairs):
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError('a repeated key')
    return dict(pairs)


def whole(value, nullable=False):
    if value is None:
        return nullable
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def meter_line(call):
    if not isinstance(call, dict) or not set(FIELDS) <= set(call) <= set(FIELDS) | {'status'}:
        return False
    return (call['role'] in ROLES and call['kind'] in ('rest', 'graphql', 'none')
            and all(isinstance(call[k], str) for k in ('time', 'method', 'endpoint'))
            and isinstance(call['exit'], int) and not isinstance(call['exit'], bool) and whole(call['rest_units'])
            and isinstance(call['uncertain'], bool)
            and whole(call['rest_used_before'], True) and whole(call['rest_used_after'], True)
            and whole(call.get('status'), 'status' not in call))


def read(paths):
    calls = []
    for path in paths:
        try:
            with open(path) as f:
                for n, text in enumerate(f, 1):
                    call = json.loads(text, object_pairs_hook=unique)
                    if not meter_line(call):
                        raise ValueError('line %d is not a meter line' % n)
                    calls.append(call)
        except (OSError, ValueError) as e:
            fail('%s: %s' % (path, e))
    return calls


def delta(call):
    a, b = call.get('rest_used_before'), call.get('rest_used_after')
    return b - a if isinstance(a, int) and isinstance(b, int) and b >= a else None


def report(paths):
    calls = read(paths)
    roles = defaultdict(lambda: [0, 0, 0, 0, 0, None])
    endpoints = defaultdict(lambda: [0, 0])
    for c in calls:
        r = roles[c['role']]
        r[0] += 1
        r[1] += c['kind'] == 'rest'
        r[2] += c['kind'] == 'graphql'
        r[3] += c['rest_units']
        r[4] += c['uncertain']
        d = delta(c)
        if d is not None:
            r[5] = (r[5] or 0) + d
        e = endpoints[(c['method'], c['endpoint'], c['kind'])]
        e[0] += 1
        e[1] += c['rest_units']
    out = ['Total: %d calls, %d REST units, %d GraphQL calls, from %d logs; %d calls uncertain'
           % (len(calls), sum(r[3] for r in roles.values()), sum(r[2] for r in roles.values()), len(paths),
              sum(r[4] for r in roles.values())),
           '', 'Per role. REST units are counted, a lower bound where a call is uncertain. Used delta is a',
           "shared-account observation: the account's REST `used` change around each call, every agent's",
           'calls included, left out where the allowance reset between the reads.', '',
           '| Role | Calls | REST calls | GraphQL calls | REST units | Uncertain | Used delta (shared account) |',
           '| --- | --- | --- | --- | --- | --- | --- |']
    order = sorted(roles, key=lambda r: ROLES.index(r) if r in ROLES else len(ROLES))
    out += ['| %s | %d | %d | %d | %d | %d | %s |' % (r, *roles[r][:5], '-' if roles[r][5] is None else roles[r][5])
            for r in order]
    out += ['', 'Per endpoint:', '', '| Method | Endpoint | Kind | Calls | REST units |', '| --- | --- | --- | --- | --- |']
    ranked = sorted(endpoints.items(), key=lambda kv: (-kv[1][1], -kv[1][0], kv[0][1], kv[0][0]))
    out += ['| %s | %s | %s | %d | %d |' % (*k, *v) for k, v in ranked]
    out += ['', 'Top five endpoints by REST units:']
    out += ['%d. %s %s: %d units, %d calls' % (i, k[0], k[1], v[1], v[0])
            for i, (k, v) in enumerate([kv for kv in ranked if kv[1][1] > 0][:5], 1)]
    print('\n'.join(out))


def main(argv):
    if argv[:1] == ['exec']:
        shim(argv[1:])
    elif argv[:1] == ['install'] and len(argv) == 2:
        install(argv[1])
    elif argv[:1] == ['report'] and len(argv) > 1:
        report(argv[1:])
    else:
        fail(USAGE.strip())


if __name__ == '__main__':
    main(sys.argv[1:])
