#!/usr/bin/env python3
"""Collect compact GitHub status sources through explicit GETs; never infer activity.

  read-github.py        milestones, open issues and open pull requests
  read-github.py runs   queued and in-progress CI runs
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ENDPOINTS = {
    'milestones': 'repos/{owner}/{repo}/milestones?state=all&per_page=100',
    'issues': 'repos/{owner}/{repo}/issues?state=open&per_page=100',
    'pulls': 'repos/{owner}/{repo}/pulls?state=open&per_page=100',
}
RUNS = {
    'queued': 'repos/{owner}/{repo}/actions/runs?status=queued&per_page=100',
    'in_progress': 'repos/{owner}/{repo}/actions/runs?status=in_progress&per_page=100',
}


# C10 (#2317), Assumption A1: the one switch. The shared installation route is
# used only once its credentials are configured: C9's protected provisioning
# writes <state>/service/github-reads/installation.json (C8's README). Without
# it, the reads below stay exactly the `gh` reads they were. With it, a missing
# helper or a missing, expired or revoked installation refuses the read; it
# never falls back to `gh` and the personal quota.
def installation_reads():
    state = os.environ.get('OPENWIZ_STATE_DIR')
    if not state:
        xdg = Path(os.environ.get('XDG_STATE_HOME', ''))
        state = (xdg if xdg.is_absolute() else Path.home() / '.local/state') / 'openwiz'
    return os.path.lexists(Path(state) / 'service/github-reads/installation.json')


# C8's reader, as launch-fleet carries its exact copy (WZ4, #2634).
READER = Path(__file__).resolve().parents[2] / 'launch-fleet/scripts/carried/read.py'
REPOSITORY = re.compile(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+')
OUTCOME = re.compile(r'(refused|deferred): [a-z-]+( until=[0-9]+)?')


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


def invalid_constant(_value):
    raise ValueError('non-JSON constant')


def field(item, key, expected):
    value = item[key]
    if type(value) is not expected:
        raise ValueError('unexpected field type')
    return value


def project(source, item):
    if source in RUNS:
        return {key: field(item, key, expected) for key, expected in
                [('id', int), ('name', str), ('status', str), ('head_sha', str)]}
    if source == 'issues' and 'pull_request' in item:
        return None
    compact = {'number': field(item, 'number', int), 'title': field(item, 'title', str)}
    if source == 'milestones':
        compact.update({key: field(item, key, expected) for key, expected in
                        [('state', str), ('open_issues', int), ('closed_issues', int)]})
    elif source == 'issues':
        milestone = item['milestone']
        compact.update(labels=[field(label, 'name', str) for label in field(item, 'labels', list)],
                       milestone=None if milestone is None else field(milestone, 'number', int))
    else:
        compact.update(draft=field(item, 'draft', bool),
                       head={'sha': field(field(item, 'head', dict), 'sha', str)},
                       base={'ref': field(field(item, 'base', dict), 'ref', str)})
    return compact


def gh_pages(endpoint):
    """The pages through `gh`, with the caller's own repository placeholders."""
    try:
        result = subprocess.run(
            ['gh', 'api', '--method', 'GET', '--paginate', '--slurp', endpoint],
            capture_output=True, text=True, timeout=60, check=False,
        )
    except UnicodeError:
        return None, 'invalid paginated JSON'
    except (OSError, subprocess.TimeoutExpired):
        return None, 'gh unavailable or timed out'
    if result.returncode:
        return None, f'gh exited {result.returncode}'
    return json.loads(result.stdout, object_pairs_hook=unique_object, parse_constant=invalid_constant), None


def installation_pages(endpoint):
    """The complete pages through C8's read.py: the explicit repository, every page."""
    repository = os.environ.get('GH_REPO', '')
    if not REPOSITORY.fullmatch(repository):
        return None, 'installation read needs GH_REPO=owner/name'
    if not READER.is_file():
        return None, 'installation read refused: the read helper is missing'
    owner, repo = repository.split('/')
    try:
        result = subprocess.run(
            [sys.executable, '-I', str(READER), 'rest', repository, endpoint.format(owner=owner, repo=repo),
             '--purpose', 'display', '--max-age', '60'],
            capture_output=True, timeout=300, check=False, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, 'installation read unavailable or timed out'
    if result.returncode:
        # read.py's one stderr line holds only its fixed outcome words.
        line = result.stderr.decode('ascii', 'replace').strip()
        return None, f'installation read {line}' if OUTCOME.fullmatch(line) else 'installation read failed'
    text, decoder, pages, at = result.stdout.decode(), json.JSONDecoder(
        object_pairs_hook=unique_object, parse_constant=invalid_constant), [], 0
    while text[at:].strip():
        page, at = decoder.raw_decode(text, len(text) - len(text[at:].lstrip()))
        pages.append(page)
    return pages, None


def read(source, endpoint):
    try:
        pages, reason = (installation_pages if installation_reads() else gh_pages)(endpoint)
        if reason:
            return {'state': 'unconfirmed', 'reason': reason}
        if source in RUNS:  # run pages are objects, each holding one list of runs
            if not isinstance(pages, list) or any(not isinstance(page, dict) for page in pages):
                raise ValueError('expected run pages')
            pages = [page.get('workflow_runs') for page in pages]
        if (not isinstance(pages, list) or not pages
                or any(not isinstance(page, list) for page in pages)
                or any(not isinstance(item, dict) for page in pages for item in page)):
            raise ValueError('expected pages of objects')
    except (ValueError, RecursionError, UnicodeError):
        return {'state': 'unconfirmed', 'reason': 'invalid paginated JSON'}
    try:
        items = []
        for page in pages:
            for item in page:
                compact = project(source, item)
                if compact is not None:
                    items.append(compact)
    except (KeyError, TypeError, ValueError):
        return {'state': 'unconfirmed', 'reason': 'invalid source record'}
    return {'state': 'read', 'items': items}


def main(argv):
    if argv not in ([], ['runs']):
        print('usage: read-github.py [runs]', file=sys.stderr)
        return 2
    endpoints = RUNS if argv else ENDPOINTS
    sources = {name: read(name, endpoint) for name, endpoint in endpoints.items()}
    print(json.dumps(sources, separators=(',', ':')))
    return 2 if any(source['state'] == 'unconfirmed' for source in sources.values()) else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
