"""Collection core for #2236. All source reads and synthesis are injected.

No subprocess, API client, model client or action executor belongs here.
"""
import copy
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import cases as E1
import score as S

SOURCES = ('issue_comments', 'review_comments', 'reviews')
SOURCE_URLS = {
    'issue_comments': r'https://github\.com/[\w.-]+/[\w.-]+/(?:issues|pull)/[1-9]\d*#issuecomment-(?P<id>[1-9]\d*)',
    'review_comments': r'https://github\.com/[\w.-]+/[\w.-]+/pull/[1-9]\d*#discussion_r(?P<id>[1-9]\d*)',
    'reviews': r'https://github\.com/[\w.-]+/[\w.-]+/pull/[1-9]\d*#pullrequestreview-(?P<id>[1-9]\d*)',
}


def week_start(week):
    if not isinstance(week, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', week):
        raise ValueError('week must be a Monday, YYYY-MM-DD')
    day = dt.date.fromisoformat(week)
    if day.weekday() != 0:
        raise ValueError('week must be a Monday, YYYY-MM-DD')
    return dt.datetime.combine(day, dt.time(), dt.timezone.utc)


def validate_case(case, skills):
    """Reuse E1's structural/privacy guards and historical wrong-action controls."""
    try:
        if not isinstance(case, dict) or E1.problems(case, skills):
            raise ValueError('invalid synthetic candidate')
        # The same pinned schema E1's offline scorer uses; never a live read.
        schema = json.loads((Path(__file__).resolve().parents[3] /
                             'contracts/decisions.v1.schema.json').read_text())
        for kind in ('pass', 'fail'):
            for ctl in case['controls'][kind]:
                ok, reasons, _ = S.score(case, E1.control_transcript(case, ctl), schema)
                if ok != (kind == 'pass') or (kind == 'fail' and ctl['reason'] not in reasons):
                    raise ValueError('invalid synthetic controls')
    except (KeyError, TypeError, AttributeError, IndexError):
        raise ValueError('invalid synthetic candidate') from None


def collect(week, read_page, synthesize, skills, *, known_cases=None, incidents=None):
    """Read every normalized page of all three source families, or raise.

    read_page(source, week, page) -> {items: [id, updated_at, body, url objects],
                                    next_page: next integer | None}.
    synthesize(item) -> None | {incident: stable synthetic key, case: E1 case}.
    Raw bodies are transient. No partial collection is returned on failure.
    """
    start = week_start(week)
    end = start + dt.timedelta(days=7)
    known_cases = known_cases or {}
    incidents = copy.deepcopy(incidents or {})
    candidates, provenance, sources = {}, {}, {}
    for source in SOURCES:
        page, seen_pages, seen_records, records = 1, set(), {}, {}
        while page is not None:
            try:
                response = read_page(source, week, page)
                if not isinstance(response, dict) or set(response) != {'items', 'next_page'}:
                    raise ValueError()
                items, nxt = response['items'], response['next_page']
                if not isinstance(items, list) or (nxt is not None and
                        (type(nxt) is not int or nxt != page + 1 or not items)):
                    raise ValueError()
                page_hash = hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()
                if items and page_hash in seen_pages:
                    raise ValueError()
                seen_pages.add(page_hash)
                for item in items:
                    if not isinstance(item, dict) or set(item) != {'id', 'updated_at', 'body', 'url'}:
                        raise ValueError()
                    if type(item['id']) is not int or item['id'] <= 0 or not isinstance(item['body'], str):
                        raise ValueError()
                    link = re.fullmatch(SOURCE_URLS[source], item['url']) if isinstance(item['url'], str) else None
                    if link is None or link['id'] != str(item['id']):
                        raise ValueError()
                    if not isinstance(item['updated_at'], str) or not re.fullmatch(
                            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', item['updated_at']):
                        raise ValueError()
                    when = dt.datetime.fromisoformat(item['updated_at'].replace('Z', '+00:00'))
                    key = str(item['id'])
                    digest = hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
                    if key in seen_records:
                        if seen_records[key] != digest:
                            raise ValueError()
                        continue
                    seen_records[key] = digest
                    if not start <= when < end:
                        continue
                    records[key] = digest
                    draft = synthesize(copy.deepcopy(item))
                    if draft is None:
                        continue
                    if not isinstance(draft, dict) or set(draft) != {'incident', 'case'}:
                        raise ValueError()
                    incident, case = draft['incident'], draft['case']
                    if not isinstance(incident, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]*', incident):
                        raise ValueError()
                    validate_case(case, skills)
                    cid = case['id']
                    if case['category'] != 'incident':
                        raise ValueError()
                    if incident in incidents and incidents[incident] != cid:
                        raise ValueError()
                    previous = candidates.get(cid, known_cases.get(cid))
                    if previous is not None and previous != case:
                        raise ValueError()
                    incidents[incident] = cid
                    candidates[cid] = copy.deepcopy(case)
                    links = provenance.setdefault(cid, {'links': []})['links']
                    if item['url'] not in links:
                        links.append(item['url'])
                page = nxt
            except Exception:
                # A remote error can contain credentials, transcripts or identifiers.
                raise ValueError(f'{source}: incomplete read or invalid synthetic candidate') from None
        sources[source] = {'week': week, 'records': records}
    return {'cases': candidates, 'incidents': incidents, 'provenance': provenance, 'sources': sources}
