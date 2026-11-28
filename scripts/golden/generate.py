#!/usr/bin/env python3
import argparse
import base64
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CONTRACT = 1
FIXTURES = ROOT / f'fixtures/records/v{CONTRACT}'
ARCHIVE = f'wizskills-records-v{CONTRACT}.tar.gz'
REGENERATE = 'python3 -I scripts/golden/generate.py write'
TIME = '2099-01-01T00:00:00Z'
OWNER = 'synthetic-owner'
STATUS = 'skills/launch-fleet/scripts/status.py'
GRILL = 'skills/grill/scripts/records.py'
REQUEST = 'skills/to-tickets/scripts/request.py'
REVISION = 'skills/to-tickets/revision.sh'
LINKS = 'skills/to-tickets/check-links.sh'
SETUP = 'skills/setup/templates'
SPEC = 'skills/to-spec/spec.md'
TICKETS = 'skills/to-tickets/tickets.md'
ANIMATIC = 'skills/to-spec/scripts/animatic.mjs'
TO_SPEC = 'skills/to-spec/SKILL.md'
NOT_WIZSKILLS = {
    'Decision answer': 'Written by the app (openwizdev/WizSite), never by a WizSkills writer.',
    'Fleet OpenWiz rows': 'No WizSkills writer yet: setup starts writing the rows in #3140 (0.1.2 MS2).',
    'Models-offered snapshot': 'No WizSkills writer: no skill writes docs/agents/models-offered.json.',
}


class Refused(Exception):
    pass


def run(args, **kwargs):
    result = subprocess.run(args, cwd=kwargs.pop('cwd', ROOT), capture_output=True, timeout=120, **kwargs)
    if result.returncode != 0:
        raise Refused(f'{" ".join(map(str, args))}: exit {result.returncode}: '
                      f'{result.stderr.decode(errors="replace").strip()[:500]}')
    return result.stdout.decode()


def load(path):
    spec = importlib.util.spec_from_file_location(Path(path).stem, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def status_notes():
    status = load(STATUS)

    def at(name):
        return f'{name}@{status.installed(name)}'

    cases = [
        ('builder-working', {'agent': 'builder', 'state': 'working', 'skills': at('build-ticket'),
                             'step': 'writing the failing test'}),
        ('builder-asking', {'agent': 'builder', 'state': 'asking', 'skills': at('build-ticket'),
                            'step': 'waiting for the owner to answer one question'}),
        ('builder-done', {'agent': 'builder', 'state': 'done', 'skills': at('build-ticket'),
                          'step': 'opened the pull request', 'pr': 'https://github.com/example/golden/pull/7',
                          'preview': 'https://preview.example.com/golden'}),
        ('reviewer-done', {'agent': 'reviewer', 'state': 'done', 'skills': at('review-ticket'),
                           'step': 'posted the verdict', 'pr': 'https://github.com/example/golden/pull/7'}),
        ('fleet-stopped', {'agent': 'fleet', 'state': 'stopped', 'why': 'the owner said stop',
                           'skills': at('launch-fleet'), 'step': 'holding the fleet'}),
    ]
    for name, case in cases:
        why = case.pop('why', None)
        fields = {'agent': case['agent'], 'state': case['state'] if why is None else f'{case["state"]} ({why})',
                  'harness': 'Claude Code', 'model': 'Opus 5.5', 'step': case['step'], 'time': TIME}
        for key in ('skills', 'pr', 'preview'):
            if key in case:
                fields[key] = case[key]
        status.shaped(fields)
        status.bound(fields['skills'])
        text = status.body(fields)
        if status.parse(text) != fields:
            raise Refused(f'status note {name} does not read back')
        yield (f'status-note/{name}.md', text,
               {'made_by': 'script', 'writer': STATUS, 'state': case['state']})


GRILL_HEAD = '''# Grill: Golden notebook (2099-01-01)

**Private.** Every question and reply as written. Status: **{status}**. Feeds: the golden notebook spec.

Already settled: nothing.
'''
GRILL_ROUND = '''
## Round 1
Risk: ordinary

**G1 - Which order?** Notes are listed for one synthetic person.
➡️ Use date order.

**G2 - Which export?** The notebook has two formats.
➡️ Use plain text.
'''
GRILL_ROUND_ANSWER = '''
**Synthetic owner:**
> Date order, and plain text.

Settled: G1, G2. Open: none.
'''
GRILL_SUMMARY = '''
## Summary (shown to Synthetic owner for confirmation)
Risk: ordinary

1. List the notes in date order.
2. Export the notes as plain text.
'''
GRILL_SUMMARY_ANSWER = '''
**Synthetic owner:**
> Confirmed.
'''


class GrillWorld:
    repo, pr, file, head = 'example/private', 7, 'docs/grills/2099-01-01-golden-notebook.md', 'a' * 40

    def __init__(self, work):
        self.work = work
        self.world = work / 'world.json'
        bin_dir = work / 'bin'
        bin_dir.mkdir(parents=True)
        gh = bin_dir / 'gh'
        gh.write_text(f'#!/bin/sh\nexec "{sys.executable}" -I "{HERE / "fake_gh.py"}" "$@"\n')
        gh.chmod(0o700)
        self.env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        self.env |= {'GOLDEN_WORLD': str(self.world), 'PATH': f'{bin_dir}{os.pathsep}{os.environ["PATH"]}'}
        run(['git', 'init', '-q', str(work)], env=self.env)
        run(['git', '-C', str(work), 'remote', 'add', 'origin', f'https://github.com/{self.repo}.git'], env=self.env)

    def save(self, source, comments=None):
        state = json.loads(self.world.read_text()) if self.world.exists() else {'comments': []}
        state |= {'repo': self.repo, 'pr': self.pr, 'file': self.file, 'head': self.head,
                  'source': base64.b64encode(source.encode()).decode()}
        self.world.write_text(json.dumps(state))

    def call(self, *args):
        run([sys.executable, '-I', str(ROOT / GRILL), self.repo, str(self.pr), self.file, *args],
            cwd=self.work, env=self.env)
        return json.loads(self.world.read_text())['comments'][-1]['body']


def grill_requests(work):
    asked = GRILL_HEAD.format(status='open') + GRILL_ROUND
    answered = asked + GRILL_ROUND_ANSWER
    summary = answered + GRILL_SUMMARY
    confirmed = GRILL_HEAD.format(status='confirmed') + GRILL_ROUND + GRILL_ROUND_ANSWER + GRILL_SUMMARY + GRILL_SUMMARY_ANSWER
    meta = {'made_by': 'script', 'writer': GRILL}
    one = GrillWorld(work / 'round')
    one.save(asked)
    yield 'decision-request/grill-round-open.md', one.call('publish', 'golden-round-1'), meta | {
        'kind': 'grill_round', 'state': 'open'}
    one.save(answered)
    yield 'decision-request/grill-round-resolved.md', one.call('advance', '81', 'G1', 'G2'), meta | {
        'kind': 'grill_round', 'state': 'resolved'}
    two = GrillWorld(work / 'superseded')
    two.save(asked)
    two.call('publish', 'golden-round-1-old')
    yield 'decision-request/grill-round-superseded.md', two.call('supersede', '81'), meta | {
        'kind': 'grill_round', 'state': 'superseded'}
    three = GrillWorld(work / 'summary')
    three.save(summary)
    yield 'decision-request/grill-confirmation-open.md', three.call('publish', 'golden-summary'), meta | {
        'kind': 'grill_confirmation', 'state': 'open'}
    three.save(confirmed)
    yield 'decision-request/grill-confirmation-resolved.md', three.call('advance', '81', 'confirmed'), meta | {
        'kind': 'grill_confirmation', 'state': 'resolved'}
    checked = {'made_by': 'checked', 'writer': 'skills/grill/assets/grill.md', 'checked_by': GRILL}
    yield 'grill-file/round-answered.md', answered, checked | {'state': 'round'}
    yield 'grill-file/summary-confirmed.md', confirmed, checked | {'state': 'summary'}


def table_rows(path, heading):
    text = (ROOT / path).read_text()
    rows = []
    for line in text.split('\n'):
        cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
        if line.startswith('| ') and cells[0] not in (heading, '---'):
            rows.append(cells[0])
    return rows


def spec_body():
    sections = {
        'Problem Statement': 'A synthetic person cannot find their notes.',
        'Solution': 'The notebook lists the notes in date order and exports plain text.',
        'Changelog headline': 'The notebook lists your notes in date order.',
        'User Stories': '1. As a synthetic person, I want my notes in date order, so that I find the latest.',
        'Implementation Decisions': '- Notes are sorted by their date.',
        'Decision tree': '- G1: date order (grill G1).\n- G2: plain text export (grill G2).',
        'Glossary': '- Note: one dated entry; not a page.',
        'Parked': 'none',
        'Testing Decisions': '- The list page is the seam.',
        'Proof': '| Claim | Evidence |\n| --- | --- |\n| P1 Notes list in date order | A list test, red first |',
        'Checkpoints': '- One-way door: yes\n- User-visible: no',
        'Live check': 'none',
        'Out of Scope': '- Sharing notes.',
        'Further Notes': 'Synthetic.',
    }
    names = table_rows(SPEC, 'Section')
    if names != list(sections):
        raise Refused(f'{SPEC} sections changed: {names}')
    return '\n\n'.join(f'## {name}\n\n{text}' for name, text in sections.items()) + '\n'


def ticket_body(n, what, owned, links):
    text = (ROOT / TICKETS).read_text()
    found = re.search(r'Write the issue body with (.+?)\. ', ' '.join(text.split()))
    names = re.split(r', | and ', found[1]) if found else []
    if names != ['Parent', 'What to build', 'Owned paths', 'Links', 'Acceptance criteria', 'Proof']:
        raise Refused(f'{TICKETS} ticket sections changed: {names}')
    return (f'## Parent\n\nTicket {n} of spec #40. Size: S.\n\n## What to build\n\n{what}\n\n'
            f'## Owned paths\n\n- `{owned}`\n\n**Relies on:** nothing\n\n## Links\n\n{links}\n\n'
            f'## Acceptance criteria\n\n- [ ] {what}\n\n## Proof\n\nP1, red first.\n')


def plan(work):
    tickets = [
        {'number': 41, 'title': '0.9.9 GN1: notes list in date order', 'blockers': [],
         'body': ticket_body(41, 'The notes list in date order.', 'src/list/', 'none')},
        {'number': 42, 'title': '0.9.9 GN2: plain text export', 'blockers': [41],
         'body': ticket_body(42, 'The notes export as plain text.', 'src/export/',
                             '- #41 real: the notes list in date order that the export reads')},
    ]
    spec = spec_body()
    headline = 'The notebook lists your notes in date order.'
    yield 'spec-and-ticket/spec.md', spec, {'made_by': 'template', 'writer': SPEC}
    for ticket in tickets:
        yield (f'spec-and-ticket/ticket-{ticket["number"]}.md', ticket['body'],
               {'made_by': 'template', 'writer': TICKETS, 'checked_by': LINKS})
    state = {'next_issue': 43, 'issues': [
        {'number': 40, 'title': '0.9.9 spec: golden notebook', 'body': spec, 'blockedBy': [], 'parent': None,
         'state': 'OPEN', 'labels': ['spec'], 'comments': [], 'milestone': '0.9.9'}] + [
        {'number': t['number'], 'title': t['title'], 'body': t['body'], 'blockedBy': t['blockers'], 'parent': 40,
         'state': 'OPEN', 'labels': ['ready-for-agent'], 'comments': [], 'milestone': '0.9.9'} for t in tickets]}
    folder = work / 'plan'
    (folder / 'bin').mkdir(parents=True)
    (folder / 'state.json').write_text(json.dumps(state))
    gh = folder / 'bin/gh'
    gh.write_text(f'#!/bin/sh\nexec "{sys.executable}" -I "{ROOT / "skills/to-tickets/test/fake_gh.py"}" "$@"\n')
    gh.chmod(0o700)
    env = dict(os.environ, FAKE_GH_STATE=str(folder), PATH=f'{folder / "bin"}{os.pathsep}{os.environ["PATH"]}')
    revision = run(['sh', str(ROOT / REVISION), '40'], env=env)
    yield 'plan-links/revision.txt', revision, {'made_by': 'script', 'writer': REVISION}
    graph = {'schema': 'openwiz.plan-links.v1', 'kind': 'graph', 'repo': 'example/golden', 'read_at': TIME,
             'source': {'kind': 'spec', 'spec': 40}, 'tickets': [
                 {'number': t['number'], 'title': t['title'], 'state': 'OPEN', 'labels': ['ready-for-agent'],
                  'milestone': '0.9.9', 'parent': 40, 'blocked_by': [{'number': b, 'state': 'OPEN'} for b in t['blockers']],
                  'body': t['body'], 'start_recorded': False, 'pull_requests': []} for t in tickets]}
    report = run(['sh', str(ROOT / LINKS), '--json', '--graph', '-'], input=json.dumps(graph).encode())
    if json.loads(report)['result'] != 'pass':
        raise Refused('check-links refused the synthetic tickets')
    yield 'plan-links/report.json', report, {'made_by': 'script', 'writer': LINKS}
    summary = ['List the notes in date order.', 'Export the notes as plain text.']
    meta = {'id': 'golden-spec', 'risk': 'ordinary', 'spec': 40, 'summary': summary, 'headline': headline}
    request = run([sys.executable, '-I', str(ROOT / REQUEST)], input=json.dumps(meta).encode())
    yield 'decision-request/spec-confirmation-open.md', request, {
        'made_by': 'script', 'writer': REQUEST, 'kind': 'spec_confirmation', 'state': 'open'}
    (folder / 'revision.txt').write_text(revision)
    meta |= {'id': 'golden-plan', 'tickets': [{k: t[k] for k in ('number', 'title', 'blockers')} for t in tickets]}
    request = run([sys.executable, '-I', str(ROOT / REQUEST), '--revision', str(folder / 'revision.txt')],
                  input=json.dumps(meta).encode())
    yield 'decision-request/plan-approval-open.md', request, {
        'made_by': 'script', 'writer': REQUEST, 'kind': 'plan_approval', 'state': 'open'}


def fill_fleet():
    text = (ROOT / SETUP / 'fleet.md').read_text()
    rows = {
        'Orchestrator': '| Orchestrator | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |',
        'Builder': '| Builder | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |',
        'Reviewer': '| Reviewer | Codex | Sol 6.2 | Medium | `--provider codex --model gpt-6.2-sol --reasoning-level medium` |',
    }
    lines = text.split('\n')
    for i, line in enumerate(lines):
        for role, row in rows.items():
            if line.startswith(f'| {role} | <'):
                lines[i] = row
    text = '\n'.join(lines)
    source = 'synthetic-owner, 2099-01-01: the synthetic settings.'
    values = [
        ("<the person's harness, for example Claude Code>", 'Claude Code'),
        ('<driver, for example local>', 'local'),
        ("<the person's GitHub login>", OWNER),
        ("<the person's name or GitHub login>", OWNER),
        ('<Toolchain versions, as the instructions file gives them.>', 'Python 3.12.'),
        ('<isolation rule, optional: project-specific restrictions on concurrent commands and shared build output, '
         'with their source; omit if none>\n\n', ''),
        ('<root, or `<folder>`>', 'root'),
        ('`<command, exactly as the source spells it>`', '`python3 -m unittest`'),
        ('`<the check that runs it>`', '`test`'),
        ("<the instructions file's commands, linked>", '[README.md](README.md)'),
        ('<the CI workflow, linked>', '[ci.yml](.github/workflows/ci.yml)'),
        ('`<job name>`', '`test`'),
        ('<the test commands it runs, by number>', '1'),
        ('`<branch>`', '`main`'),
        ('<What the user should know about these checks: how a draft or a docs-only change shows, for example.>',
         'A draft runs the same check.'),
        ('<a linked source file, or decider, date and plain decision with a Markdown private-record comment link>', source),
        ('<decider, date and plain decision with a Markdown private-record comment link>', source),
        ('<linked source files, or decider, date and plain decision with a Markdown private-record comment link>', source),
        ('<kind of pull request>', 'Any'),
        ('<who reviews it, or none>', 'The Reviewer'),
        ('<who merges it, and the exact conditions>', 'The owner, by hand'),
        ('<With no rule recorded: "None yet: every merge waits for the user.">\n\n', ''),
        ('`<app-slug>[bot]`, `<the login of the account the fleet falls back to>`', f'`openwiz[bot]`, `{OWNER}`'),
        ("<the App's settings, and `gh api user` on the account the fleet runs as>", "the App's settings"),
    ]
    for old, new in values:
        if old not in text:
            raise Refused(f'{SETUP}/fleet.md no longer has {old!r}')
        text = text.replace(old, new)
    left = re.findall(r'<[^>\n]+>', text)
    if left:
        raise Refused(f'{SETUP}/fleet.md has unfilled placeholders: {left}')
    return text


def fleet(work):
    labels = (ROOT / SETUP / 'triage-labels.md').read_text()
    labels = re.sub(r'^\| `([a-z-]+)` \| `<label>` \|', r'| `\1` | `\1` |', labels, flags=re.M)
    folder = work / 'setup/docs/agents'
    folder.mkdir(parents=True)
    filled = fill_fleet()
    for name, text in (('fleet.md', filled), ('triage-labels.md', labels)):
        (folder / name).write_text(text)
    for name in ('issue-tracker.md', 'domain.md'):
        (folder / name).write_text((ROOT / SETUP / name).read_text())
    run([sys.executable, '-I', str(ROOT / 'skills/setup/scripts/settings.py'), 'check', '--root', str(work / 'setup')])
    meta = {'made_by': 'template', 'writer': f'{SETUP}/fleet.md', 'checked_by': 'skills/setup/scripts/settings.py'}
    yield 'fleet/fleet.md', filled, meta
    yield 'labels/triage-labels.md', labels, meta | {'writer': f'{SETUP}/triage-labels.md'}


def video():
    line = run(['node', str(ROOT / ANIMATIC), 'link', 'https://video.example.com/golden-notebook.mp4']).rstrip('\n')
    steer = re.search(r'the link, then `(Steering by comment is off[^`]+)`', (ROOT / TO_SPEC).read_text())
    if not steer:
        raise Refused(f'{TO_SPEC} no longer gives the steering line')
    yield ('video-comment/narrated-spec.md', f'{line}\n\n{steer[1]}\n',
           {'made_by': 'script', 'writer': ANIMATIC, 'checked_by': TO_SPEC})


FORMS = (
    ('Status note', lambda f: f.startswith('status-note/')),
    ('Decision request', lambda f: f.startswith('decision-request/')),
    ('Decision answer', None),
    ('Plan links', lambda f: f.startswith('plan-links/') or f.startswith('spec-and-ticket/ticket-')),
    ('Labels', lambda f: f.startswith('labels/')),
    ('Fleet OpenWiz rows', None),
    ('Fleet record authors', lambda f: f == 'fleet/fleet.md'),
    ('Fleet models', lambda f: f == 'fleet/fleet.md'),
    ('Models-offered snapshot', None),
    ('Grill file', lambda f: f.startswith('grill-file/')),
    ('Spec and ticket templates', lambda f: f.startswith('spec-and-ticket/')),
    ('Narrated-spec video comment', lambda f: f.startswith('video-comment/')),
)


def records():
    with tempfile.TemporaryDirectory(prefix='wizskills-golden-') as tmp:
        work = Path(tmp)
        made = [*status_notes(), *grill_requests(work), *plan(work), *fleet(work), *video()]
    files = {path: text for path, text, _ in made}
    forms = []
    for name, picks in FORMS:
        if picks is None:
            forms.append({'form': name, 'fixtures': [], 'why_none': NOT_WIZSKILLS[name]})
        else:
            forms.append({'form': name, 'fixtures': [{'path': path} | meta for path, _, meta in made if picks(path)]})
    index = {'schema': 'wizskills.golden-records.v1', 'records_contract': CONTRACT, 'regenerate': REGENERATE,
             'forms': forms}
    files['index.json'] = json.dumps(index, indent=2, ensure_ascii=False) + '\n'
    return files


def on_disk(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob('*')) if p.is_file()}


def write(folder):
    folder.mkdir(parents=True, exist_ok=True)
    files = records()
    for rel in set(on_disk(folder)) - set(files):
        (folder / rel).unlink()
    for rel, text in files.items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_bytes(text.encode())
    print(f'wrote {len(files)} files to {folder}')
    return 0


def stale(folder):
    want = {rel: text.encode() for rel, text in records().items()}
    have = on_disk(folder) if folder.is_dir() else {}
    problems = [f'missing: {rel}' for rel in sorted(set(want) - set(have))]
    problems += [f'not made by a writer: {rel}' for rel in sorted(set(have) - set(want))]
    problems += [f'stale or hand edited: {rel}' for rel in sorted(set(want) & set(have)) if want[rel] != have[rel]]
    return problems


def check(folder):
    problems = stale(folder)
    for line in problems:
        print(line)
    if problems:
        print(f'golden records are not fresh; regenerate them with `{REGENERATE}` and commit the result')
        return 1
    print(f'golden records fresh: {folder.relative_to(ROOT) if folder.is_relative_to(ROOT) else folder}')
    return 0


def archive(out):
    if stale(FIXTURES):
        print(f'golden records are not fresh; run `{REGENERATE}` first', file=sys.stderr)
        return 1
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode='w', format=tarfile.USTAR_FORMAT) as tar:
        for rel, data in on_disk(FIXTURES).items():
            info = tarfile.TarInfo(f'records/v{CONTRACT}/{rel}')
            info.size, info.mode, info.mtime = len(data), 0o644, 0
            tar.addfile(info, io.BytesIO(data))
    target = out / ARCHIVE
    out.mkdir(parents=True, exist_ok=True)
    with open(target, 'wb') as stream, gzip.GzipFile(filename='', mode='wb', fileobj=stream, mtime=0) as packed:
        packed.write(raw.getvalue())
    print(target)
    return 0


def main(argv):
    parser = argparse.ArgumentParser(prog='generate.py', description=(
        'Make the records-contract golden records by running the real WizSkills writers on synthetic inputs.'))
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('write', 'check'):
        sub.add_parser(name).add_argument('--dir', type=Path, default=FIXTURES)
    sub.add_parser('archive').add_argument('out', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'write':
            return write(args.dir.resolve())
        if args.command == 'check':
            return check(args.dir.resolve())
        return archive(args.out.resolve())
    except Refused as error:
        print(f'generate.py: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
