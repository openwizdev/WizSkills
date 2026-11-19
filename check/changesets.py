#!/usr/bin/env python3
"""WizSkills' changesets: one note per pull request, per-skill bumps, bundle releases (J205, J206).

python3 -I check/changesets.py check --base REF
    The pull request gate. Every skill the commits since REF change (anything
    under skills/<name>/ except the SKILL.md `version:` line) must be named in
    a changeset the same commits add; a removed skill needs a new changeset
    naming `wizskills`. Every pending changeset must be well formed.
python3 -I check/changesets.py release [--since REF] [--date YYYY-MM-DD] [--write]
    Runs the pinned Changesets (`npm ci` first) over the pending changesets in
    a throwaway workspace with one package per skill, then prints each skill's
    bump, the bundle's own bump by J206's rules and its CHANGELOG section. A dry
    run unless --write, which sets the bumped skills' `version:` lines, the
    plugin's version and CHANGELOG.md, and deletes the consumed changesets. It
    never tags, pushes or publishes. --since is the last release (default: the
    newest `v*` tag), for skills added or removed since.

Exit 0 pass, 1 refused, 2 unusable input or setup. Python 3.11+ and Git; release
also needs Node.
"""
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUNDLE = 'wizskills'
BUMPS = ('patch', 'minor', 'major')
NAME = r'[a-z0-9]+(?:-[a-z0-9]+)*'
RELEASE_LINE = re.compile(rf'(?:"({NAME})"|\'({NAME})\'|({NAME})): (\S+)')
VERSION_LINE = re.compile(r'version: *["\']?([^"\'\s]+)["\']? *')
PLAIN = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)')
SHAPE = 'opens with `---`, one `"<skill>": patch|minor|major` line each, then `---` and a summary'
CHANGESETS = 'node_modules/@changesets/cli/bin.js'


class Unusable(Exception):
    pass


def git(*args):
    p = subprocess.run(['git', *args], cwd=ROOT, capture_output=True)
    if p.returncode:
        raise Unusable(f'git {" ".join(args)} failed')
    return p.stdout.decode('utf-8')


def parse_note(text, skills):
    """(releases {name: bump}, summary), or raise ValueError(why)."""
    lines = text.split('\n')
    if lines[0] != '---' or '---' not in lines[1:]:
        raise ValueError(SHAPE)
    end = lines.index('---', 1)
    releases = {}
    for line in lines[1:end]:
        m = RELEASE_LINE.fullmatch(line)
        if not m:
            raise ValueError(SHAPE)
        name, bump = m.group(1) or m.group(2) or m.group(3), m.group(4)
        if bump not in BUMPS:
            raise ValueError('a bump is patch, minor or major')
        if name in releases:
            raise ValueError(f'names `{name}` twice')
        if name != BUNDLE and name not in skills:
            raise ValueError(f'`{name}` is not a skill or `{BUNDLE}`')
        releases[name] = bump
    if not releases:
        raise ValueError(f'names no skill and no `{BUNDLE}`')
    summary = '\n'.join(lines[end + 1:]).strip()
    if not summary:
        raise ValueError('has no summary')
    return releases, summary


def is_note(rel):
    parts = rel.split('/')
    return len(parts) == 2 and parts[0] == '.changeset' and parts[1].endswith('.md') and parts[1] != 'README.md'


def without_version(text):
    """SKILL.md text with its front matter's `version:` line dropped."""
    lines = text.split('\n')
    if lines[:1] == ['---'] and '---' in lines[1:]:
        end = lines.index('---', 1)
        lines = [lines[0], *(l for l in lines[1:end] if not l.startswith('version:')), *lines[end:]]
    return '\n'.join(lines)


# ---- The pull request gate ----

def tree_skills(ref):
    return {p.split('/')[1] for p in git('ls-tree', '-r', '--name-only', ref, '--', 'skills/').splitlines()
            if p.count('/') == 2 and p.endswith('/SKILL.md')}


def check(base):
    merge_base = git('merge-base', base, 'HEAD').strip()
    head_skills = tree_skills('HEAD')
    before = set(git('ls-tree', '-r', '--name-only', merge_base, '--', 'skills/').splitlines())
    diff = git('diff', '--name-only', '--no-renames', '-z', merge_base, 'HEAD', '--', 'skills/')
    changed = set()
    for rel in filter(None, diff.split('\0')):
        parts = rel.split('/')
        if len(parts) < 3:
            continue
        name = parts[1]
        if rel == f'skills/{name}/SKILL.md' and name in head_skills and rel in before:
            if without_version(git('show', f'{merge_base}:{rel}')) == without_version(git('show', f'HEAD:{rel}')):
                continue
        changed.add(name)
    refusals, named = [], set()
    added = {p for p in git('diff', '--name-only', '--no-renames', '--diff-filter=A', '-z', merge_base, 'HEAD',
                            '--', '.changeset/').split('\0') if is_note(p)}
    pending = sorted(p for p in git('ls-tree', '--name-only', 'HEAD', '--', '.changeset/').splitlines() if is_note(p))
    for rel in pending:
        try:
            releases, _ = parse_note(git('show', f'HEAD:{rel}'), head_skills)
        except ValueError as why:
            refusals.append(f'{rel} {why}')
            continue
        if rel in added:
            named.update(releases)
    for name in sorted(changed):
        if name in head_skills and name not in named:
            refusals.append(f'`{name}` changed but no new changeset names it: '
                            'add one under .changeset/ (see .changeset/README.md)')
        elif name not in head_skills and BUNDLE not in named:
            refusals.append(f'`{name}` was removed but no new changeset names `{BUNDLE}`')
    for line in refusals:
        print(f'changeset check: {line}')
    if refusals:
        print('changeset check: fail')
        return 1
    print(f'changeset check: pass ({", ".join(sorted(changed)) or "no skill changed"})')
    return 0


# ---- The release ----

def skill_version(path):
    lines = path.read_text(encoding='utf-8').split('\n')
    end = lines.index('---', 1) if lines[:1] == ['---'] and '---' in lines[1:] else 0
    found = [VERSION_LINE.fullmatch(l) for l in lines[1:end] if l.startswith('version:')]
    if len(found) != 1 or not found[0]:
        raise Unusable(f'{path.relative_to(ROOT).as_posix()} has no valid `version:`: run check/run.py')
    return found[0].group(1)


def bumped(version, bump):
    m = PLAIN.fullmatch(version)
    if not m:
        raise Unusable(f'the plugin version {version} is not a plain X.Y.Z')
    x, y, z = map(int, m.groups())
    return {'major': f'{x + 1}.0.0', 'minor': f'{x}.{y + 1}.0', 'patch': f'{x}.{y}.{z + 1}'}[bump]


def bundle_bump(skill_bumps, explicit, added, removed):
    """J206: patch for a few fixes, minor for many changes or a catalog change, major for a break."""
    reasons = {b: [] for b in BUMPS}
    if explicit:
        reasons[explicit].append(f'`{BUNDLE}`: {explicit} in a changeset')
    if 'major' in skill_bumps.values():
        reasons['major'].append("a skill's major bump")
    if added:
        reasons['minor'].append('skills added: ' + ', '.join(added))
    if removed:
        reasons['minor'].append('skills removed: ' + ', '.join(removed))
    if len(skill_bumps) > 3:
        reasons['minor'].append(f'{len(skill_bumps)} skills changed')
    if 'minor' in skill_bumps.values():
        reasons['minor'].append("a skill's minor bump")
    if skill_bumps and set(skill_bumps.values()) == {'patch'}:
        n = len(skill_bumps)
        reasons['patch'].append(f'{n} skill{"s" if n != 1 else ""} changed, all patch')
    for bump in reversed(BUMPS):
        if reasons[bump]:
            return bump, '; '.join(reasons[bump])
    raise AssertionError('a pending changeset always names something')


def bullets(changelog):
    """The newest section's bullets of a Changesets CHANGELOG.md, one line each."""
    out, seen = [], 0
    for line in changelog.read_text(encoding='utf-8').split('\n'):
        if line.startswith('## '):
            seen += 1
            if seen > 1:
                break
        elif seen and line.startswith('- '):
            out.append(line[2:].strip())
        elif seen and line.startswith('  ') and out:
            out[-1] += ' ' + line.strip()
    return [' '.join(b.split()) for b in out]


def plan(names, versions, plugin_version, notes):
    """Run the pinned Changesets in a throwaway workspace: ({skill: new}, {name: bullets})."""
    if not (ROOT / CHANGESETS).is_file():
        raise Unusable('Changesets is not installed: run `npm ci` at the repository root')
    with tempfile.TemporaryDirectory(prefix='wizskills-release-') as tmp:
        work = Path(tmp)
        packages = {n: work / 'skills' / n for n in names}
        packages[BUNDLE] = work / 'release-bundle'
        for name, folder in packages.items():
            folder.mkdir(parents=True)
            version = plugin_version if name == BUNDLE else versions[name]
            (folder / 'package.json').write_text(json.dumps({'name': name, 'version': version, 'private': True}))
        (work / 'package.json').write_text(json.dumps(
            {'name': 'wizskills-release-plan', 'private': True, 'workspaces': ['skills/*', 'release-bundle']}))
        (work / 'package-lock.json').write_text(json.dumps({'lockfileVersion': 3, 'packages': {}}))
        (work / '.changeset').mkdir()
        shutil.copy(ROOT / '.changeset/config.json', work / '.changeset/config.json')
        for note in notes:
            shutil.copy(note, work / '.changeset' / note.name)
        (work / 'node_modules').symlink_to(ROOT / 'node_modules')
        env = {k: v for k, v in os.environ.items() if k not in ('GH_TOKEN', 'GITHUB_TOKEN')}
        p = subprocess.run(['node', str(work / CHANGESETS), 'version'], cwd=work, capture_output=True,
                           text=True, env={**env, 'CI': '1'})
        if p.returncode:
            raise Unusable('Changesets refused the pending changesets: ' + ' '.join(p.stderr.split()[-12:]))
        new, notes_by = {}, {}
        for name, folder in packages.items():
            version = json.loads((folder / 'package.json').read_text())['version']
            if name != BUNDLE and version != versions[name]:
                new[name] = version
            if (folder / 'CHANGELOG.md').is_file():
                notes_by[name] = bullets(folder / 'CHANGELOG.md')
        return new, notes_by


def release(since, date, write):
    names = sorted(e.name for e in (ROOT / 'skills').iterdir() if (e / 'SKILL.md').is_file())
    if BUNDLE in names:
        raise Unusable(f'a skill may not be named `{BUNDLE}`, the bundle')
    note_files = sorted(p for p in (ROOT / '.changeset').glob('*.md') if p.name != 'README.md')
    if not note_files:
        print('release: nothing pending')
        return 0
    skill_bumps, explicit, refused = {}, None, []
    for path in note_files:
        try:
            releases, _ = parse_note(path.read_text(encoding='utf-8'), set(names))
        except ValueError as why:
            refused.append(f'release: .changeset/{path.name} {why}')
            continue
        for name, bump in releases.items():
            if name == BUNDLE:
                explicit = max(explicit or bump, bump, key=BUMPS.index)
            else:
                skill_bumps[name] = max(skill_bumps.get(name, bump), bump, key=BUMPS.index)
    if refused:
        print('\n'.join(refused))
        return 1
    if since is None:
        since = git('describe', '--tags', '--abbrev=0', '--match', 'v*', 'HEAD').strip()
    before = {p.split('/')[1] for p in git('ls-tree', '-r', '--name-only', since, '--', 'skills/').splitlines()
              if p.count('/') == 2 and p.endswith('/SKILL.md')}
    added, removed = sorted(set(names) - before), sorted(before - set(names))
    versions = {n: skill_version(ROOT / 'skills' / n / 'SKILL.md') for n in names}
    plugin_path = ROOT / '.claude-plugin/plugin.json'
    plugin_data = json.loads(plugin_path.read_text(encoding='utf-8'))
    bump, why = bundle_bump(skill_bumps, explicit, added, removed)
    version = bumped(plugin_data['version'], bump)
    new, notes_by = plan(names, versions, plugin_data['version'], note_files)
    section = [f'## {version} - {date}', '']
    section += [f'- Skills added: {", ".join(f"`{n}`" for n in added)}.'] if added else []
    section += [f'- Skills removed: {", ".join(f"`{n}`" for n in removed)}.'] if removed else []
    section += [f'- {b}' for b in notes_by.get(BUNDLE, [])]
    section += [f'- `{n}` {new[n]}: {b}' for n in sorted(new) for b in notes_by.get(n, [])]
    print(f'release: {BUNDLE} {plugin_data["version"]} -> {version} ({bump})')
    print(f'why: {why}')
    for n in sorted(new):
        print(f'skill {n}: {versions[n]} -> {new[n]} ({skill_bumps[n]})')
    if not write:
        print('dry run: nothing written')
        print('\n' + '\n'.join(section))
        return 0
    changelog_path = ROOT / 'CHANGELOG.md'
    changelog = changelog_path.read_text(encoding='utf-8')
    header = '# Changelog\n\n'
    if not changelog.startswith(header):
        raise Unusable('CHANGELOG.md does not open with `# Changelog` and a blank line')
    for n in sorted(new):
        path = ROOT / 'skills' / n / 'SKILL.md'
        lines = path.read_text(encoding='utf-8').split('\n')
        end = lines.index('---', 1)
        lines = [f'version: {new[n]}' if 0 < i < end and l.startswith('version:') else l
                 for i, l in enumerate(lines)]
        path.write_text('\n'.join(lines), encoding='utf-8')
    plugin_data['version'] = version
    plugin_path.write_text(json.dumps(plugin_data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    market_path = ROOT / '.claude-plugin/marketplace.json'
    if market_path.is_file():
        market = json.loads(market_path.read_text(encoding='utf-8'))
        if 'version' in market.get('plugins', [{}])[0]:
            market['plugins'][0]['version'] = version
            market_path.write_text(json.dumps(market, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    changelog_path.write_text(header + '\n'.join(section) + '\n\n' + changelog[len(header):], encoding='utf-8')
    for path in note_files:
        path.unlink()
    print('\n' + '\n'.join(section))
    s, c = len(new), len(note_files)
    print(f'written: {s} skill{"s" if s != 1 else ""}, plugin.json, CHANGELOG.md; '
          f'{c} changeset{"s" if c != 1 else ""} consumed')
    return 0


def valid_date(text):
    try:
        return bool(re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', text)) and bool(datetime.date.fromisoformat(text))
    except ValueError:
        return False


def main(argv):
    parser = argparse.ArgumentParser(prog='check/changesets.py')
    sub = parser.add_subparsers(dest='command', required=True)
    gate = sub.add_parser('check')
    gate.add_argument('--base', required=True)
    rel = sub.add_parser('release')
    rel.add_argument('--since')
    rel.add_argument('--date', default=datetime.datetime.now(datetime.timezone.utc).date().isoformat())
    rel.add_argument('--write', action='store_true')
    args = parser.parse_args(argv)
    if args.command == 'release' and not valid_date(args.date):
        print('changesets: --date is YYYY-MM-DD', file=sys.stderr)
        return 2
    try:
        if args.command == 'check':
            return check(args.base)
        return release(args.since, args.date, args.write)
    except Unusable as why:
        print(f'changesets: {why}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
