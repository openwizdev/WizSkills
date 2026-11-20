#!/usr/bin/env python3
"""WizSkills' own check (openwiz.wizskills.v1, WZ7).

python3 check/run.py

Run from anywhere; it checks the tree that holds this `check/` folder. It
runs the skill rules, the standalone check (`check/standalone.py --tree <root>`)
and every skill's own suites, all of them even after a failure, and exits 1
if any fails or is missing, 2 on arguments. Python 3.11+ standard library,
POSIX `sh`; no network, no secret, no file outside the tree.
"""
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent

# Each carried skill's own suites, run from the tree's root. The inventory
# guard below refuses any newly added suite until this list includes it.
SUITES = {
    'check': [['python3', '-I', 'check/test_notice.py']],
    'build-ticket': [['python3', '-I', 'skills/build-ticket/scripts/test_ticket.py']],
    'triage': [['python3', '-I', 'skills/triage/test/test_find_work.py'],
               ['python3', '-I', 'skills/triage/test/test_public_records.py']],
    'install': [['python3', '-I', 'skills/install/tests/test_first_fleet.py'],
                ['python3', '-I', 'skills/install/tests/test_doctor.py']],
    'huntr': [['sh', 'skills/huntr/scripts/test.sh']],
    'grill': [['sh', 'skills/grill/scripts/test.sh'],
              ['python3', 'skills/grill/scripts/test_records.py']],
    'diagnose': [['node', '--test', 'skills/diagnose/tests/hitl-loop.test.mjs'],
                 ['python3', '-I', 'skills/diagnose/scripts/test_loop.py']],
    'where-are-we': [['python3', '-I', 'skills/where-are-we/test/test_read_github.py']],
    'handoff': [['python3', '-I', 'skills/handoff/test/test_handoff.py']],
    'ask-wiz': [['python3', '-I', 'skills/ask-wiz/test/test_routes.py']],
    'hill-climb': [['python3', '-I', '-m', 'unittest', 'discover', '-s', 'skills/hill-climb/tests']],
    'setup': [['python3', '-I', 'skills/setup/scripts/test_settings.py']],
    'image': [['python3', '-I', '-m', 'unittest', 'discover', '-s', 'skills/image/tests'],
              ['python3', '-I', '-m', 'unittest', 'discover', '-s', 'skills/image/references']],
    'to-spec': [['python3', '-I', 'skills/to-spec/test/test_video.py']],
    'to-tickets': [['python3', '-I', 'skills/to-tickets/scripts/test_check_approval.py'],
                   ['sh', 'skills/to-tickets/test/test-revision.sh'],
                   ['python3', '-I', 'skills/to-tickets/test/test_relies.py'],
                   ['python3', '-I', 'skills/to-tickets/test/test_picture.py'],
                   ['python3', '-I', 'skills/to-tickets/test/test_request.py']],
    'review-ticket': [['python3', '-I', 'skills/review-ticket/scripts/test_review.py']],
    'wayfind': [['python3', '-I', 'skills/wayfind/test/test_frontier.py']],
    'research': [['python3', '-I', 'skills/research/test/test_workers.py'],
                 ['python3', '-I', 'skills/research/test/test_snapshot_commands.py']],
    'launch-fleet': [['sh', 'skills/launch-fleet/scripts/test.sh'],
                     ['python3', '-I', 'skills/launch-fleet/test/ops-protocol/test_protocol.py'],
                     ['python3', '-I', 'skills/launch-fleet/scripts/test-effects.py'],
                     ['python3', '-I', 'skills/launch-fleet/scripts/test-grants.py'],
                     ['python3', '-I', 'skills/launch-fleet/scripts/test-inbox.py'],
                     ['python3', '-I', 'skills/launch-fleet/scripts/test-records.py'],
                     ['python3', '-I', 'skills/launch-fleet/scripts/test-status.py'],
                     ['python3', '-I', 'skills/launch-fleet/scripts/test-ops-starts.py'],
                     ['python3', '-I', 'skills/launch-fleet/scripts/test-on1.py'],
                     ['sh', 'skills/launch-fleet/scripts/test-loop.sh'],
                     ['python3', '-I', 'skills/launch-fleet/scripts/test-limit-replacement.py'],
                     ['python3', '-I', 'skills/launch-fleet/scripts/test-limit-recovery.py'],
                     ['python3', '-I', 'skills/launch-fleet/scripts/test-post.py'],
                     ['python3', '-I', 'skills/launch-fleet/scripts/test-merge.py'],
                     ['python3', '-I', 'skills/launch-fleet/scripts/test-brief.py'],
                     ['python3', '-I', 'skills/launch-fleet/scripts/test-host.py'],
                     ['python3', '-I', 'skills/launch-fleet/scripts/test-route.py']],
    # Not a skill: the check's own version rule and changesets (WS18).
    'check': [['python3', '-I', 'check/test_versions.py'],
              ['python3', '-I', 'check/test_changesets.py']],
}

# The skills not adapted from Matt Pocock's, each with the source line its
# SKILL.md carries exactly, on a line of its own, instead of his notice.
ORIGINAL = "**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills."
SOURCE_LINES = {
    'hill-climb': ORIGINAL,
    'huntr': ORIGINAL,
    'image': ORIGINAL,
    'install': ORIGINAL,
    'where-are-we': "**Source:** dot-context's written plan. Not adapted from Matt Pocock's skills.",
}

# Matt Pocock's copyright and MIT notice (github.com/mattpocock/skills
# @ a496f55), compared with whitespace collapsed.
MATT_NOTICE = ' '.join("""Copyright (c) 2026 Matt Pocock
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.""".split())
MATT_COPYRIGHT = 'Copyright (c) 2026 Matt Pocock'

ASK_WIZ = 'ask-wiz'
ASK_WIZ_POLICY = 'policy:\n  allow_implicit_invocation: false'
FRONTMATTER_KEYS = ('name', 'description', 'version')
DESCRIPTION_MAX = 1024
OPENAI_KEYS = ('display_name', 'short_description')

PLUGIN = '.claude-plugin/plugin.json'
MARKETPLACE = '.claude-plugin/marketplace.json'
PLUGIN_KEYS = {'name', 'version', 'description', 'author', 'homepage', 'repository',
               'license', 'keywords', 'skills'}
MARKETPLACE_KEYS = {'name', 'owner', 'description', 'plugins'}
ENTRY_KEYS = {'name', 'source', 'description', 'version', 'category', 'keywords'}
VERSION = re.compile(
    r'(?:0\.[1-9][0-9]*|[1-9][0-9]*\.(?:0|[1-9][0-9]*))\.(?:0|[1-9][0-9]*)'
    r'(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)'
    r'(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?'
    r'(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?')
# A skill's own version (J205): plain semver 2.0.0, no leading `v`.
SKILL_VERSION = re.compile(
    r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'
    r'(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)'
    r'(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?'
    r'(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?', re.ASCII)
SKILL_NAME = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*')


class Findings(list):
    def add(self, rule, file, message, line=None):
        self.append((rule, file, line, message))


# ---- The skill rules ----

def rules(root):
    out = Findings()
    names = layout(root, out)
    for name in names:
        skill(root, name, out)
    links(root, out)
    plugin_version = plugin(root, names, out)
    marketplace(root, plugin_version, out)
    return out


def layout(root, out):
    skills = root / 'skills'
    if skills.is_symlink() or not skills.is_dir():
        out.add('layout', 'skills', 'the skills folder is missing')
        return []
    names = []
    for entry in sorted(os.scandir(skills), key=lambda e: e.name):
        at = f'skills/{entry.name}'
        if entry.is_symlink():
            continue  # links() reports every symlink under skills/
        if entry.is_dir():
            if not SKILL_NAME.fullmatch(entry.name):
                out.add('layout', at, 'a skill folder is named in lowercase and hyphens')
            elif not (Path(entry.path) / 'SKILL.md').is_file():
                out.add('layout', f'{at}/SKILL.md', 'every folder in skills/ is a skill with a SKILL.md')
            else:
                names.append(entry.name)
        elif not (entry.name == 'README.md' and entry.is_file()):
            out.add('layout', at, 'only README.md and skill folders belong in skills/')
    if not (skills / 'README.md').is_file() or (skills / 'README.md').is_symlink():
        out.add('layout', 'skills/README.md', 'the skill rules file is missing')
    if not names:
        out.add('layout', 'skills', 'no skill is carried')
    return names


def skill(root, name, out):
    at = f'skills/{name}/SKILL.md'
    text = read(root / at)
    if text is None:
        out.add('layout', at, 'SKILL.md is not readable UTF-8')
        return
    split = split_frontmatter(text)
    if split is None:
        out.add('frontmatter', at, 'it opens with a `---` line, the frontmatter, then a closing `---` line')
        body = text
    else:
        front, body = split
        frontmatter(at, name, front, out)
    source = SOURCE_LINES.get(name)
    collapsed = ' '.join(body.split())
    if source is not None:
        if not any(line.strip() == source for line in body.splitlines()):
            out.add('notice', at, f'it carries its source line exactly, on a line of its own: `{source}`')
        if MATT_COPYRIGHT in collapsed:
            out.add('notice', at, "it is not adapted from Matt Pocock's skills, so it never carries his notice")
    else:
        notice_at = f'skills/{name}/NOTICE.md'
        if MATT_NOTICE not in ' '.join((read(root / notice_at) or '').split()):
            out.add('notice', notice_at, "it carries Matt Pocock's copyright and MIT notice word for word")
        last = next((line for line in reversed(body.splitlines()) if line.strip()), '')
        if MATT_COPYRIGHT in collapsed or '](NOTICE.md)' not in last:
            out.add('notice', at, 'it ends with a credit line linking NOTICE.md and never carries the notice itself')
    yaml_at = f'skills/{name}/agents/openai.yaml'
    yaml = read(root / yaml_at)
    if yaml is None:
        out.add('codex', yaml_at, 'every skill has one for Codex')
    else:
        openai_yaml(yaml_at, name, yaml, out)


def read(path):
    try:
        if path.is_symlink():
            return None
        return path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return None


def split_frontmatter(text):
    lines = text.split('\n')
    if not lines or lines[0] != '---':
        return None
    for i, line in enumerate(lines[1:], 1):
        if line == '---':
            return lines[1:i], '\n'.join(lines[i + 1:])
    return None


def frontmatter(at, name, front, out):
    values, flags = {}, 0
    for n, line in enumerate(front, 2):
        key, sep, rest = line.partition(':')
        if not sep or not re.fullmatch(r'[a-z][a-z0-9_-]*', key):
            out.add('frontmatter', at, 'each frontmatter line is a one-line `key: value`', n)
            continue
        if name == ASK_WIZ and key == 'disable-model-invocation':
            flags += 1
            if rest != ' true' or flags != 1:
                out.add('frontmatter', at, 'ask-wiz has exactly one `disable-model-invocation: true`', n)
            continue
        if key not in FRONTMATTER_KEYS:
            out.add('frontmatter', at, f'`{key}` is not allowed: only `name`, `description` and `version`', n)
            continue
        value, why = scalar(rest)
        if why and key == 'version' and key not in values:
            values[key] = None
            out.add('frontmatter', at, '`version` is not a semver version such as `0.2.0`', n)
        elif why:
            out.add('frontmatter', at, f'`{key}` {why}', n)
        elif key in values:
            out.add('frontmatter', at, f'`{key}` appears twice', n)
        elif key == 'version' and not SKILL_VERSION.fullmatch(value):
            values[key] = None
            out.add('frontmatter', at, '`version` is not a semver version such as `0.2.0`', n)
        else:
            values[key] = value
    if name == ASK_WIZ and flags == 0:
        out.add('frontmatter', at, 'ask-wiz requires `disable-model-invocation: true`')
    if 'name' not in values:
        out.add('frontmatter', at, 'the frontmatter has no valid `name`')
    elif values['name'] != name:
        out.add('frontmatter', at, f'`name` is not its folder\'s name `{name}`')
    if 'description' not in values:
        out.add('frontmatter', at, 'the frontmatter has no valid `description`')
    elif len(values['description']) > DESCRIPTION_MAX:
        out.add('frontmatter', at, f'`description` is longer than {DESCRIPTION_MAX} characters')
    if 'version' not in values:
        out.add('frontmatter', at, 'the frontmatter has no valid `version` (semver, such as `0.2.0`)')


INDICATORS = tuple('-?:,[]{}#&*!|>%@`')
SPECIAL = {'true', 'false', 'null', '~', 'yes', 'no', 'on', 'off'}


def scalar(rest):
    """A one-line YAML value YAML reads as the same text, or a reason."""
    raw = rest.strip()
    if not raw:
        return None, 'needs a value on the same line'
    if not rest.startswith(' '):
        return None, 'needs a space after its `:`'
    if raw.startswith('"'):
        if len(raw) < 2 or not raw.endswith('"'):
            return None, 'opens a double quote it does not close'
        value, chars = [], iter(raw[1:-1])
        for c in chars:
            if c == '\\':
                e = next(chars, None)
                if e not in ('"', '\\'):
                    return None, 'uses an escape other than \\" or \\\\'
                value.append(e)
            elif c == '"':
                return None, 'has an unescaped double quote inside'
            else:
                value.append(c)
        value = ''.join(value)
    elif raw.startswith("'"):
        if len(raw) < 2 or not raw.endswith("'"):
            return None, 'opens a single quote it does not close'
        inner = raw[1:-1]
        if "'" in inner.replace("''", ''):
            return None, 'has an unescaped single quote inside'
        value = inner.replace("''", "'")
    else:
        if raw.startswith(INDICATORS):
            return None, 'starts with a YAML indicator: quote it'
        if ': ' in raw or ' #' in raw or raw.endswith(':'):
            return None, 'has `: `, ` #` or a final `:`, which YAML misreads: quote it'
        if raw.lower() in SPECIAL or is_number(raw):
            return None, 'reads as a YAML boolean, null or number: quote it'
        value = raw
    if not value.strip():
        return None, 'is empty'
    return value, None


def is_number(text):
    try:
        float(text)
        return True
    except ValueError:
        return False


def openai_yaml(at, name, text, out):
    if name == ASK_WIZ:
        stripped = text.rstrip()
        if stripped.endswith(ASK_WIZ_POLICY):
            text = stripped[:-len(ASK_WIZ_POLICY)]
        else:
            out.add('codex', at, 'ask-wiz requires exactly `policy.allow_implicit_invocation: false`')
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines or lines[0] != 'interface:':
        out.add('codex', at, 'it opens with `interface:`')
    else:
        lines = lines[1:]
    seen = set()
    for line in lines:
        key, sep, value = line[2:].partition(':') if line.startswith('  ') else ('', '', '')
        if not sep or key not in OPENAI_KEYS:
            out.add('codex', at, 'only `interface.display_name` and `interface.short_description` '
                    'are allowed (and `policy` only for ask-wiz)')
            continue
        _, why = scalar(value)
        if why:
            out.add('codex', at, f'`{key}` {why}')
        if key in seen:
            out.add('codex', at, f'`{key}` appears twice')
        seen.add(key)
    for key in OPENAI_KEYS:
        if key not in seen:
            out.add('codex', at, f'`interface.{key}` is missing')


# ---- Links: no symlinks under skills/, every relative Markdown link resolves ----

def links(root, out):
    skills = root / 'skills'
    if skills.is_symlink() or not skills.is_dir():
        return
    real_root = root.resolve()
    for folder, dirs, files in os.walk(skills):
        here = Path(folder)
        for entry in sorted(dirs + files):
            path = here / entry
            at = path.relative_to(root).as_posix()
            if path.is_symlink():
                out.add('symlink', at, 'no symlinks under skills/: plugin installs may drop them', 1)
            elif entry in files and entry.endswith('.md'):
                markdown(path, at, real_root, out)
        dirs[:] = [d for d in dirs if not (here / d).is_symlink()]


def markdown(path, at, real_root, out):
    text = read(path)
    if text is None:
        out.add('links', at, 'not readable UTF-8', 1)
        return
    for line, target in markdown_targets(text):
        if '://' in target or target.startswith('mailto:'):
            continue
        file = unquote(re.split(r'[#?]', target, maxsplit=1)[0])
        if not file:
            continue
        if file.startswith('/'):
            out.add('links', at, 'a relative link never uses an absolute path', line)
            continue
        resolved = (path.parent / file).resolve()
        if not resolved.exists():
            out.add('links', at, 'a relative link does not resolve', line)
        elif not resolved.is_relative_to(real_root):
            out.add('links', at, 'a relative link leaves the tree', line)


def markdown_targets(text):
    """(line, target) of each Markdown link and link definition, outside code."""
    targets, fence = [], None
    for n, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if fence:
            if stripped.startswith(fence):
                fence = None
            continue
        opener = next((f for f in ('```', '~~~') if stripped.startswith(f)), None)
        if opener:
            fence = opener
            continue
        line = ''.join(line.split('`')[::2])
        definition = re.match(r'\s*\[[^\]]*\]: (.*)', line)
        if definition:
            targets.append((n, first_token(definition.group(1))))
            continue
        rest = line
        while '](' in rest:
            rest = rest[rest.index('](') + 2:]
            end = rest.find(')')
            end = len(rest) if end < 0 else end
            targets.append((n, first_token(rest[:end])))
            rest = rest[end:]
    return targets


def first_token(text):
    parts = text.split()
    return parts[0].lstrip('<').rstrip('>') if parts else ''


# ---- The plugin manifest and marketplace ----

def no_duplicates(pairs):
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError('duplicate key')
    return dict(pairs)


def json_object(root, rel, out):
    path = root / rel
    try:
        if path.is_symlink():
            raise OSError
        data = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=no_duplicates)
    except (OSError, UnicodeDecodeError, ValueError):
        out.add('manifest', rel, 'missing, unreadable, not JSON, or has a duplicate key')
        return None
    if not isinstance(data, dict):
        out.add('manifest', rel, 'it is a JSON object')
        return None
    return data


def only_keys(rel, where, data, allowed, out):
    for key in sorted(set(data) - allowed):
        out.add('manifest', rel, f'{where}`{key}` is not allowed (only {", ".join(sorted(allowed))})')


def plugin(root, names, out):
    data = json_object(root, PLUGIN, out)
    if data is None:
        return None
    only_keys(PLUGIN, '', data, PLUGIN_KEYS, out)
    if data.get('name') != 'openwiz':
        out.add('manifest', PLUGIN, '`name` is `openwiz`')
    version = data.get('version')
    if not (isinstance(version, str) and VERSION.fullmatch(version)):
        out.add('manifest', PLUGIN, '`version` is a SemVer version without a leading `v`')
        version = None
    description = data.get('description')
    if not (isinstance(description, str) and description.strip()):
        out.add('manifest', PLUGIN, '`description` is a non-empty string')
    entries = data.get('skills')
    expected = [f'./skills/{name}' for name in sorted(names)]
    if not (isinstance(entries, list) and all(isinstance(e, str) for e in entries)):
        out.add('manifest', PLUGIN, '`skills` is an array of `./skills/<name>` strings')
        return version
    for entry in sorted(set(entries) - set(expected)):
        out.add('manifest', PLUGIN, f'`{entry}` is not a carried skill folder')
    for entry in sorted(set(e for e in entries if entries.count(e) > 1)):
        out.add('manifest', PLUGIN, f'`{entry}` is listed twice')
    for entry in expected:
        if entry not in entries:
            out.add('manifest', PLUGIN, f'it does not list the carried skill `{entry}`')
    if entries != sorted(entries):
        out.add('manifest', PLUGIN, '`skills` is sorted by name')
    return version


def marketplace(root, version, out):
    data = json_object(root, MARKETPLACE, out)
    if data is None:
        return
    only_keys(MARKETPLACE, '', data, MARKETPLACE_KEYS, out)
    if data.get('name') != 'wizskills':
        out.add('manifest', MARKETPLACE, '`name` is `wizskills`')
    owner = data.get('owner')
    if not (isinstance(owner, dict) and isinstance(owner.get('name'), str) and owner['name'].strip()):
        out.add('manifest', MARKETPLACE, '`owner` is an object with a non-empty `name`')
    plugins = data.get('plugins')
    if not (isinstance(plugins, list) and len(plugins) == 1 and isinstance(plugins[0], dict)):
        out.add('manifest', MARKETPLACE, '`plugins` holds exactly one plugin entry')
        return
    entry = plugins[0]
    only_keys(MARKETPLACE, '`plugins[0]`: ', entry, ENTRY_KEYS, out)
    if entry.get('name') != 'openwiz':
        out.add('manifest', MARKETPLACE, '`plugins[0].name` is `openwiz`')
    if entry.get('source') != './':
        out.add('manifest', MARKETPLACE, '`plugins[0].source` is `./`, the repository root')
    if 'version' in entry and entry['version'] != version:
        out.add('manifest', MARKETPLACE, f'`plugins[0].version` agrees with {PLUGIN}')


# ---- The standalone check and the suites ----

def clean_env():
    return {k: v for k, v in os.environ.items() if k not in ('GH_TOKEN', 'GITHUB_TOKEN',
            'TEST_ONLY', 'TEST_EXPECTED', 'TEST_PASS', 'TEST_WORKER', 'LIST_CASES')}


def command_path(command):
    """The tree file a suite command runs or discovers, relative to the root."""
    if command[:2] == ['python3', '-I'] and command[2:4] == ['-m', 'unittest']:
        return command[-1], True
    return command[-1], False


def unittest_file(path):
    """Only known unittest class definitions count as discovery coverage.

    Unknown/script-style files require their own explicit entrypoint. Actual
    collection below also refuses classes that contain no runnable tests.
    """
    try:
        module = ast.parse(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, SyntaxError):
        return False
    modules = {'unittest'}
    bases = set()
    for node in module.body:
        if isinstance(node, ast.Import):
            modules.update(alias.asname or alias.name for alias in node.names if alias.name == 'unittest')
        elif isinstance(node, ast.ImportFrom) and node.module == 'unittest':
            bases.update(alias.asname or alias.name for alias in node.names if alias.name == 'TestCase')
        elif isinstance(node, ast.ClassDef):
            if any((isinstance(base, ast.Attribute) and base.attr == 'TestCase'
                    and isinstance(base.value, ast.Name) and base.value.id in modules)
                   or (isinstance(base, ast.Name) and base.id in bases) for base in node.bases):
                return True
    return False


# An isolated interpreter collects each matched file, counts its actual cases,
# then executes the collection. A successful empty collection is still a failure.
UNIT_RUNNER = r"""
import importlib.util, pathlib, sys, unittest
folder, pattern = sys.argv[1:]
loader = unittest.TestLoader()
if pattern == 'test*.py':
    suite = loader.discover(folder, pattern=pattern)
else:
    # discover ignores filenames such as test-effects.py even with an exact
    # pattern. Explicitly listed files need a loader that accepts their names.
    spec = importlib.util.spec_from_file_location('listed_suite', pathlib.Path(folder) / pattern)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    suite = loader.loadTestsFromModule(module)
counts = {}
def count(item):
    if isinstance(item, unittest.TestSuite):
        for child in item: count(child)
    else:
        module = sys.modules.get(type(item).__module__)
        file = getattr(module, '__file__', None)
        if file:
            key = pathlib.Path(file).resolve()
            counts[key] = counts.get(key, 0) + 1
count(suite)
empty = [p for p in pathlib.Path(folder).glob(pattern) if not counts.get(p.resolve(), 0)]
for path in sorted(empty):
    print('suite collection: zero tests: ' + path.as_posix(), flush=True)
result = unittest.TextTestRunner().run(suite)
sys.exit(0 if result.wasSuccessful() and not empty else 1)
"""


def suites(root):
    covered = set()
    for commands in SUITES.values():
        for command in commands:
            rel, folder = command_path(command)
            if folder:
                covered.update(p.relative_to(root).as_posix() for p in (root / rel).glob('test*.py')
                               if unittest_file(p))
            else:
                covered.add(rel)
    # Huntr's public shell entrypoint executes its four Node test modules.
    covered.update('skills/huntr/scripts/' + name for name in
                   ('gate.test.mjs', 'manifest.test.mjs', 'records.test.mjs', 'controller.test.mjs'))
    discovered = {p.relative_to(root).as_posix() for p in (root / 'skills').rglob('*')
                  if p.is_file() and 'fixtures' not in p.parts and
                  ((p.name.startswith('test') and p.suffix in ('.py', '.sh'))
                   or p.name.endswith('.test.mjs'))}
    unlisted = discovered - covered
    for rel in sorted(unlisted):
        print(f'suite inventory: {rel}: unlisted', flush=True)
    failed = bool(unlisted)
    for name, commands in SUITES.items():
        for command in commands:
            shown = ' '.join(command)
            rel, folder = command_path(command)
            target = root / rel
            present = target.is_dir() and any(target.glob('test*.py')) if folder else target.is_file()
            if target.is_symlink() or not present:
                print(f'suite {name}: {shown}: missing', flush=True)
                failed = True
                continue
            cwd = root
            argv = [sys.executable if command[0] == 'python3' else command[0], *command[1:]]
            if folder:
                argv = [sys.executable, '-I', '-c', UNIT_RUNNER, rel, 'test*.py']
            elif command[0] == 'python3' and unittest_file(target):
                argv = [sys.executable, '-I', '-c', UNIT_RUNNER, target.parent.relative_to(root).as_posix(), target.name]
            if name == 'huntr':
                cwd = root / 'check/fixtures/huntr-project'
                settings = cwd / 'docs/agents/huntr.md'
                if not settings.is_file() or settings.is_symlink():
                    print(f'suite {name}: synthetic consumer missing', flush=True)
                    failed = True
                    continue
                argv[-1] = str(target.resolve())
            print(f'suite {name}: {shown}: running', flush=True)
            try:
                code = subprocess.run(argv, cwd=cwd, env=clean_env()).returncode
            except OSError:
                print(f'suite {name}: {shown}: cannot start', flush=True)
                failed = True
                continue
            print(f'suite {name}: {shown}: {"pass" if code == 0 else f"fail ({code})"}', flush=True)
            failed = failed or code != 0
    return not failed


def standalone(root):
    script = root / 'check' / 'standalone.py'
    if script.is_symlink() or not script.is_file():
        print('standalone: missing check/standalone.py', flush=True)
        return False
    code = subprocess.run([sys.executable, '-I', str(script), '--tree', str(root)], cwd=root,
                          env=clean_env()).returncode
    print(f'standalone: {"pass" if code == 0 else f"fail ({code})"}', flush=True)
    return code == 0


def main(argv):
    if argv:
        print('usage: python3 check/run.py (no arguments)', file=sys.stderr)
        return 2
    findings = rules(ROOT)
    for rule, file, line, message in findings:
        print(f'rules: {rule} {file}{f":{line}" if line else ""}: {message}', flush=True)
    print(f'rules: {"pass" if not findings else f"fail ({len(findings)})"}', flush=True)
    ok_standalone = standalone(ROOT)
    ok_suites = suites(ROOT)
    ok = not findings and ok_standalone and ok_suites
    print(f'check: {"pass" if ok else "fail"}', flush=True)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
