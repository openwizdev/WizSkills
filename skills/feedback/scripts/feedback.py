#!/usr/bin/env python3

import argparse
import datetime
import errno
import fcntl
import json
import os
import platform
import re
import secrets
import shutil
import stat
import subprocess
import sys
import unicodedata
import urllib.parse
from pathlib import Path

DESTINATION = 'openwizdev/OpenWiz'
API_REPO = 'https://api.github.com/repos/' + DESTINATION
WEB_REPO = 'https://github.com/' + DESTINATION
SCHEMA = 'openwiz.feedback-operation.v1'
MARKER = 'OpenWiz feedback operation '
FACTS_PREFIX = 'OpenWiz feedback facts '
FACTS_MAX = 1024
FACTS_ORDER = (
    'v', 'kind', 'area', 'openwiz', 'wizskills', 'skill', 'os', 'arch',
    'host', 'driver', 'harness', 'model', 'log_lines', 'redactions',
)
DROPPABLE_FACTS = set(FACTS_ORDER) - {'v'}
REPORT_KEYS = {'title', 'kind', 'area', 'ran', 'happened', 'expected', 'host', 'driver', 'harness', 'model'}
SLUG_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,31}$')
VERSION_RE = re.compile(r'^[0-9]+\.[0-9]+\.[0-9]+$')
SKILL_VER_RE = re.compile(r'^feedback@[0-9]+\.[0-9]+\.[0-9]+$')
MODEL_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{0,63}$')
KINDS = ('bug', 'idea', 'question')
OS_FAMILIES = ('linux', 'macos', 'windows', 'other')
ARCH_FAMILIES = ('x86_64', 'arm64', 'other')
LOG_MAX_LINES = 40
LOG_MAX_CHARS = 200
REDACTIONS_MAX = 9999
OPENWIZ_VERSION_TIMEOUT_S = 2
OP_ID = re.compile(r'[0-9a-f]{32}')
PREVIEW_ID = re.compile(r'[0-9]{6}')
FAILED_STATUSES = {401, 403, 404, 410, 422, 429}
PHASES = {'draft', 'previewed', 'refused', 'sending', 'sent', 'failed', 'uncertain'}
EDITABLE = {'draft', 'previewed', 'refused', 'failed'}
TITLE_MAX = 256
BODY_MAX = 65536
LINK_MAX = 6000
TIMEOUT_S = 60
SECTION_HEADERS = {
    'ran': 'What I ran:',
    'happened': 'What happened:',
    'expected': 'What I expected:',
}
LOG_HEADER = 'Log (secrets removed):'
SECTION_LABELS = {*SECTION_HEADERS.values(), LOG_HEADER}
FAILED_HINTS = {
    401: 'The login expired; sign in again with gh auth login, or use the browser link.',
    403: 'GitHub refused this account or is rate-limiting it; check your account or wait, or use the browser link.',
    404: 'Issues are not open there right now.',
    410: 'Issues are not open there right now.',
    422: 'GitHub rejected the text; edit the draft and preview again.',
    429: 'GitHub is rate-limiting requests; wait and try later.',
}
SINCE_MARGIN = datetime.timedelta(days=1)
PRIVATE_KEY_START = re.compile(r'-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----')
PRIVATE_KEY_BLOCK = re.compile(r'-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)')
URL_CRED = re.compile(r'[A-Za-z][A-Za-z0-9+.-]*://[^\s/@]+:[^\s/@]+@[^\s"\'<>]+')
SECRET_PATTERNS = (
    (re.compile(r'\bsynthetic-token-[A-Za-z0-9_-]+\b'), '[secret removed]'),
    (re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b'), '[secret removed]'),
    (re.compile(r'\b[sr]k_(?:live|test)_[A-Za-z0-9]{10,}\b'), '[secret removed]'),
    (re.compile(r'\bglpat-[A-Za-z0-9_-]{10,}\b'), '[secret removed]'),
    (re.compile(r'\bnpm_[A-Za-z0-9]{10,}\b'), '[secret removed]'),
    (re.compile(r'\bhf_[A-Za-z0-9]{10,}\b'), '[secret removed]'),
    (re.compile(r'\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{16,}\b'), '[secret removed]'),
    (re.compile(r'\b(?:AKIA|ASIA)[0-9A-Z]{16}\b'), '[secret removed]'),
    (re.compile(r'\bxox[a-z]-[A-Za-z0-9-]{10,}\b'), '[secret removed]'),
    (re.compile(r'\bAIza[0-9A-Za-z_-]{35}\b'), '[secret removed]'),
    (re.compile(r'\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b'), '[secret removed]'),
    (re.compile(r'\bBearer\s+[A-Za-z0-9._~+/=-]{16,}\b'), '[secret removed]'),
    (URL_CRED, '[secret removed]'),
    (re.compile(r'\b((?:[A-Za-z0-9_]*_)?(?:password|passwd|secret|token|api[_-]?key|auth[_-]?token)\s*[:=]\s*)'
                r'(?!\[(?:secret|path|link|email|ip|id) removed\])\S+', re.I), r'\1[secret removed]'),
)
LINK_RE = re.compile(r'(?:https?|ssh|ftp)://[^\s"\'<>()]+|\bwww\.[^\s"\'<>()]+|git@[A-Za-z0-9._-]+:[^\s"\'<>()]+', re.I)
EMAIL_RE = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
IPV4_RE = re.compile(r'\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b(?::\d{1,5})?')
IPV6_RE = re.compile(r'(?<![A-Za-z0-9:])(?:[0-9a-fA-F]{1,4}:){2,7}[0-9a-fA-F]{0,4}(?![A-Za-z0-9:])'
                     r'|(?<![A-Za-z0-9:])::(?:[0-9a-fA-F]{1,4}:){0,5}[0-9a-fA-F]{1,4}(?![A-Za-z0-9:])')
PATH_RE = re.compile(r'~/[^\s"\'<>:,;)]*'
                     r'|(?<![A-Za-z0-9._:-])/(?:Users|home|root|var|tmp|etc|opt|srv|mnt|media|Volumes|private|code|repos|run|proc|sys)/[^\s"\'<>:,;)]*'
                     r'|(?<![A-Za-z0-9._:-])/[A-Za-z0-9._-]+/[A-Za-z0-9._/@~+-]+'
                     r'|\b[A-Za-z]:\\[^\s"\'<>:,;)]+')
ID_RE = re.compile(r'\b(?:thr|prj|ses|sess|acct|acc|usr|user|org|ws|run|job|req)_[A-Za-z0-9_-]{4,}\b'
                   r'|\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b')
SHELL_PROMPT_RE = re.compile(r'^[ \t]*(?:[A-Za-z0-9._-]+@[A-Za-z0-9._-]+(?::[^\s$#%>]*)?\s*[$#%>]|PS [A-Z]:\\[^>]*>|[$#%>])\s+')
SKILL_VERSION_LINE = re.compile(r'^version:\s*["\']?([0-9]+\.[0-9]+\.[0-9]+)["\']?\s*$')


def same_name(value, name):
    return isinstance(value, str) and value.isascii() and value.lower() == name.lower()


SHARE_ISSUE = re.compile(r'https://github\.com/openwizdev/OpenWiz/issues/([1-9][0-9]{0,9})')
URLISH = re.compile(r'[A-Za-z][A-Za-z0-9+.-]*://|\bwww\.|\blocalhost\b|\b\d{1,3}(\.\d{1,3}){3}\b'
                    r'|\b(?:[a-z0-9-]+\.)+[a-z]{2,}\.?(?::[\w.~-]*)?/|\b[a-z0-9-]+:\d+/'
                    r'|@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.?:~?[\w.-]*/', re.I)
KEYS_030 = ['schema', 'operation_id', 'destination', 'phase', 'title', 'chosen_body', 'body',
            'account', 'preview', 'attempts', 'issue', 'reason', 'evidence']
KEYS = ['schema', 'operation_id', 'destination', 'phase', 'title', 'chosen_body', 'body', 'facts', 'warnings',
        'account', 'preview', 'attempts', 'issue', 'reason', 'evidence']
KEYS_WITH_REPORT = [*KEYS, 'report_fields']


class Stop(Exception):
    pass


class SaveError(Stop):

    replaced = False


class UnsyncedError(SaveError):

    replaced = True


def out(answer, code):
    sys.stdout.write(json.dumps(answer, ensure_ascii=False, indent=2) + '\n')
    return code


def now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)


def iso(t):
    return t.strftime('%Y-%m-%dT%H:%M:%SZ')


def state_dir():
    env = os.environ.get('OPENWIZ_STATE_DIR', '')
    if env:
        if not os.path.isabs(env):
            raise Stop('OPENWIZ_STATE_DIR must be an absolute path.')
        return Path(env)
    home = os.environ.get('HOME', '')
    if not home or not os.path.isabs(home):
        raise Stop('No state directory: HOME is not an absolute path and OPENWIZ_STATE_DIR is not set.')
    if sys.platform == 'darwin':
        return Path(home, 'Library/Application Support/openwiz')
    xdg = os.environ.get('XDG_STATE_HOME', '')
    return Path(xdg if xdg and os.path.isabs(xdg) else os.path.join(home, '.local/state'), 'openwiz')


def inside_repository(path):
    try:
        resolved = path.resolve(strict=False)
    except (OSError, RuntimeError):
        raise Stop(f'The state directory {path} cannot be resolved; feedback records stay outside every repository.')
    for parent in [path, *path.parents, resolved, *resolved.parents]:
        if os.path.lexists(parent / '.git'):
            raise Stop(f'The state directory is inside a repository ({parent}); feedback records stay outside every repository.')


def area():
    root = state_dir()
    inside_repository(root)
    old = os.umask(0o077)
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        place = root / 'feedback'
        place.mkdir(mode=0o700, exist_ok=True)
    finally:
        os.umask(old)
    inside_repository(place)
    for d in (root, place):
        info = os.lstat(d)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise Stop(f'{d} is not a plain directory.')
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise Stop(f'{d} must be owned by you and closed to others (mode 700).')
    return place


def record_path(place, op):
    if not OP_ID.fullmatch(op or ''):
        raise Stop('Not an operation id: 32 lowercase hexadecimal characters.')
    return place / f'{op}.json'


def read_record(path):
    try:
        text = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        raise Stop('No record for this operation. OpenWiz cannot tell whether earlier feedback was created; nothing was sent.')
    except OSError as e:
        raise Stop(f'The record cannot be read ({e.strerror}). OpenWiz cannot tell whether earlier feedback was created; nothing was sent.')

    def pairs(items):
        keys = [k for k, _ in items]
        if len(keys) != len(set(keys)):
            raise ValueError('repeated key')
        return dict(items)
    try:
        rec = json.loads(text, object_pairs_hook=pairs)
    except ValueError:
        rec = None
    if not (isinstance(rec, dict) and list(rec) in (KEYS, KEYS_030, KEYS_WITH_REPORT) and rec['schema'] == SCHEMA
            and rec['phase'] in PHASES and same_name(rec['destination'], DESTINATION)
            and path.name == f"{rec['operation_id']}.json"):
        raise Stop('The record is unreadable. OpenWiz cannot tell whether earlier feedback was created; nothing was sent.')
    if list(rec) == KEYS_030:
        rec.update(facts=None, warnings=[], report_fields=None)
    return rec


def write_record(place, rec):
    path = place / f"{rec['operation_id']}.json"
    tmp = place / f".{rec['operation_id']}.{secrets.token_hex(4)}.tmp"
    keys = KEYS_WITH_REPORT if 'report_fields' in rec else KEYS
    data = (json.dumps({k: rec[k] for k in keys}, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            view = memoryview(data)
            while view:
                n = os.write(fd, view)
                if n <= 0:
                    raise OSError(errno.EIO, 'nothing written')
                view = view[n:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise SaveError(f'The operation record could not be saved ({e.strerror or e}); the previous record is kept.')
    try:
        dfd = os.open(place, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError as e:
        raise UnsyncedError(f'The operation record was written, but its folder could not be synced ({e.strerror or e}), '
                            'so whether it survives a crash is unconfirmed.')


TWIN = ('Operation {} with this exact text may already have been created. '
        'Reconcile it first; this text is not offered again.')


class StoreLock:

    def __init__(self, place):
        self.path = place / '.store.lock'

    def __enter__(self):
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        os.close(self.fd)


def twin(place, op, title, chosen_body):
    for path in sorted(place.glob('*.json')):
        if path.name == f'{op}.json':
            continue
        other = read_record(path)
        if (other['title'], other['chosen_body']) == (title, chosen_body) and \
                recorded(other, Lock(place, other['operation_id']).held())['phase'] in ('uncertain', 'sending'):
            return other['operation_id']
    return None


class Lock:

    def __init__(self, place, op):
        self.path = place / f'{op}.lock'

    def __enter__(self):
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self.fd)
            raise Stop('Another step on this operation is running now. Nothing more was done; check its status when it ends.')
        return self

    def __exit__(self, *exc):
        os.close(self.fd)

    def held(self):
        try:
            fd = os.open(self.path, os.O_RDONLY)
        except FileNotFoundError:
            return False
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            return False
        except BlockingIOError:
            return True
        finally:
            os.close(fd)


def read_text(path, what):
    try:
        return Path(path).read_bytes().decode('utf-8')
    except (OSError, UnicodeDecodeError):
        raise Stop(f'The {what} file cannot be read as UTF-8 text.')


def chosen(title_file, body_file):
    title = read_text(title_file, 'title').strip()
    body = read_text(body_file, 'body').replace('\r\n', '\n').rstrip()
    if not title or '\n' in title or '\r' in title:
        raise Stop('The title must be one line, not empty.')
    if len(title) > TITLE_MAX:
        raise Stop(f'The title is longer than {TITLE_MAX} characters; shorten it.')
    if not body:
        raise Stop('The body is empty; write what you want the OpenWiz maintainers to read.')
    if '\r' in body or any(line.startswith(MARKER) or line.startswith(FACTS_PREFIX) for line in body.split('\n')):
        raise Stop('The body cannot hold a carriage return or its own feedback marker or facts line.')
    visible(title, body)
    warnings = check_secrets_and_warnings([('title', title), ('body', body)])
    return title, body, None, warnings, None


def check_secrets_and_warnings(sections):
    for name, text in sections:
        if not text:
            continue
        for lineno, line in enumerate(text.split('\n'), 1):
            if PRIVATE_KEY_START.search(line):
                raise Stop(f'Refused: private key block found in {name} (line {lineno}); remove it before previewing.')
            for pat, _ in SECRET_PATTERNS:
                if pat.search(line):
                    raise Stop(f'Refused: token-shaped secret found in {name} (line {lineno}); remove it before previewing.')
    warnings = []
    seen = set()
    for name, text in sections:
        if not text:
            continue
        for lineno, line in enumerate(text.split('\n'), 1):
            checks = (
                ('path', PATH_RE, f'Private-looking path in {name} (line {lineno})'),
                ('email', EMAIL_RE, f'E-mail address in {name} (line {lineno})'),
                ('ip', IPV4_RE, f'IP address in {name} (line {lineno})'),
                ('ip', IPV6_RE, f'IP address in {name} (line {lineno})'),
                ('id', ID_RE, f'Private-looking identifier in {name} (line {lineno})'),
            )
            for kind, pat, msg in checks:
                if pat.search(line) and (kind, name, lineno) not in seen:
                    seen.add((kind, name, lineno))
                    warnings.append(msg)
    return warnings


def scrub_log(path):
    text = read_text(path, 'log').replace('\r\n', '\n').replace('\r', '\n')
    count = 0
    text, n = PRIVATE_KEY_BLOCK.subn('[secret removed]', text)
    count += n
    lines = text.split('\n')
    while lines and lines[-1] == '':
        lines.pop()
    if not lines:
        raise Stop('The log file is empty.')
    lines = lines[-LOG_MAX_LINES:]
    out_lines = []
    for line in lines:
        line = SHELL_PROMPT_RE.sub('', line, count=1)
        for pat, repl in SECRET_PATTERNS:
            line, n = pat.subn(repl, line)
            count += n
        for pat, repl in (
            (LINK_RE, '[link removed]'),
            (EMAIL_RE, '[email removed]'),
            (IPV4_RE, '[ip removed]'),
            (IPV6_RE, '[ip removed]'),
            (PATH_RE, '[path removed]'),
            (ID_RE, '[id removed]'),
        ):
            line, n = pat.subn(repl, line)
            count += n
        if len(line) > LOG_MAX_CHARS:
            line = line[:LOG_MAX_CHARS]
        out_lines.append('    ' + line)
    if count > REDACTIONS_MAX:
        raise Stop(f'The log holds more than {REDACTIONS_MAX} redactions; trim it first.')
    return '\n'.join(out_lines), len(out_lines), count


def read_skill_version():
    skill_md = Path(__file__).resolve().parent.parent / 'SKILL.md'
    try:
        lines = skill_md.read_text(encoding='utf-8').split('\n')
    except OSError:
        return None
    if lines[:1] != ['---'] or '---' not in lines[1:]:
        return None
    end = lines.index('---', 1)
    for line in lines[1:end]:
        m = SKILL_VERSION_LINE.fullmatch(line)
        if m:
            return f'feedback@{m.group(1)}'
    return None


def read_wizskills_version():
    manifest = Path(__file__).resolve().parents[3] / '.claude-plugin' / 'plugin.json'
    try:
        data = json.loads(manifest.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    ver = data.get('version') if isinstance(data, dict) else None
    return ver if isinstance(ver, str) and VERSION_RE.fullmatch(ver) else None


def read_openwiz_version():
    try:
        run = subprocess.run(
            ['openwiz', '--version'],
            capture_output=True,
            text=True,
            env={'PATH': os.environ.get('PATH', ''), 'LC_ALL': 'C'},
            timeout=OPENWIZ_VERSION_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if run.returncode != 0:
        return None
    m = re.fullmatch(r'(?:openwiz\s+)?v?([0-9]+\.[0-9]+\.[0-9]+)', run.stdout.strip(), re.I)
    return m.group(1) if m else None


def read_os_family():
    if sys.platform.startswith('linux'):
        return 'linux'
    if sys.platform == 'darwin':
        return 'macos'
    if sys.platform in ('win32', 'cygwin'):
        return 'windows'
    return 'other'


def read_arch_family():
    machine = (os.uname().machine if hasattr(os, 'uname') else platform.machine()).lower()
    if machine in ('x86_64', 'amd64'):
        return 'x86_64'
    if machine in ('arm64', 'aarch64'):
        return 'arm64'
    return 'other'


def validate_facts(facts):
    if facts is None:
        return None
    if not isinstance(facts, dict):
        raise Stop('Facts must be a JSON object.')
    for k in facts:
        if k not in FACTS_ORDER:
            raise Stop(f'Unknown fact key `{k}`.')
    if facts.get('v') != 1 or type(facts.get('v')) is not int:
        raise Stop('Invalid fact `v`: must be 1.')
    checks = {
        'v': lambda v: type(v) is int and v == 1,
        'kind': lambda v: isinstance(v, str) and v in KINDS,
        'area': lambda v: isinstance(v, str) and bool(SLUG_RE.fullmatch(v)),
        'openwiz': lambda v: isinstance(v, str) and bool(VERSION_RE.fullmatch(v)),
        'wizskills': lambda v: isinstance(v, str) and bool(VERSION_RE.fullmatch(v)),
        'skill': lambda v: isinstance(v, str) and bool(SKILL_VER_RE.fullmatch(v)),
        'os': lambda v: isinstance(v, str) and v in OS_FAMILIES,
        'arch': lambda v: isinstance(v, str) and v in ARCH_FAMILIES,
        'host': lambda v: isinstance(v, str) and bool(SLUG_RE.fullmatch(v)),
        'driver': lambda v: isinstance(v, str) and bool(SLUG_RE.fullmatch(v)),
        'harness': lambda v: isinstance(v, str) and bool(SLUG_RE.fullmatch(v)),
        'model': lambda v: isinstance(v, str) and bool(MODEL_RE.fullmatch(v)),
        'log_lines': lambda v: type(v) is int and 0 <= v <= LOG_MAX_LINES,
        'redactions': lambda v: type(v) is int and 0 <= v <= REDACTIONS_MAX,
    }
    ordered = {}
    for k in FACTS_ORDER:
        if k in facts:
            val = facts[k]
            if not checks[k](val):
                raise Stop(f'Invalid fact `{k}`: value is outside the contract pattern.')
            ordered[k] = val
    if len(ordered) <= 1:
        return None
    return ordered


def format_facts_line(facts):
    ordered = validate_facts(facts)
    if ordered is None:
        return None
    line = FACTS_PREFIX + json.dumps(ordered, separators=(',', ':'), ensure_ascii=True)
    if not line.isascii() or len(line) > FACTS_MAX:
        raise Stop(f'The facts line exceeds {FACTS_MAX} ASCII characters; drop a fact.')
    return line


def chosen_report(report_file, log_file=None, drop=(), no_facts=False):
    raw = read_text(report_file, 'report')

    def pairs(items):
        keys = [k for k, _ in items]
        if len(keys) != len(set(keys)):
            raise ValueError('repeated key')
        return dict(items)

    try:
        data = json.loads(raw, object_pairs_hook=pairs)
    except ValueError:
        raise Stop('The report file must be a valid JSON object with no repeated keys.')
    if not isinstance(data, dict):
        raise Stop('The report file must be a JSON object.')
    for k in data:
        if k not in REPORT_KEYS:
            raise Stop(f'Unknown key `{k}` in report file.')
    for k in drop:
        if k not in DROPPABLE_FACTS:
            raise Stop(f'Unknown fact key `{k}` for --drop.')

    def read_field(name, required=False):
        val = data.get(name)
        if val is None:
            if required:
                raise Stop(f'The report file is missing required `{name}`.')
            return ''
        if not isinstance(val, str):
            raise Stop(f'Invalid `{name}` in report file: must be a string.')
        return val.replace('\r\n', '\n')

    title = read_field('title', required=True).strip()
    if not title or '\n' in title or '\r' in title:
        raise Stop('The title must be one line, not empty.')
    if len(title) > TITLE_MAX:
        raise Stop(f'The title is longer than {TITLE_MAX} characters; shorten it.')

    fields = {name: read_field(name, required=name == 'happened').rstrip() for name in SECTION_HEADERS}
    if not fields['happened']:
        raise Stop('The `happened` field is empty; write what you want the OpenWiz maintainers to read.')

    text_sections = [('title', title), *fields.items()]
    for name, text in text_sections:
        if '\r' in text or any(line.startswith(MARKER) or line.startswith(FACTS_PREFIX) for line in text.split('\n')):
            raise Stop(f'The `{name}` section cannot hold a carriage return or its own feedback marker or facts line.')
        if name in SECTION_HEADERS and any(line in SECTION_LABELS for line in text.split('\n')):
            raise Stop(f'The `{name}` section cannot contain a feedback section label on its own line.')
    warnings = check_secrets_and_warnings(text_sections)
    body_parts = [f'{SECTION_HEADERS[name]}\n{text}' for name, text in fields.items() if text]

    log_lines = None
    redactions = None
    if log_file:
        scrubbed, log_lines, redactions = scrub_log(log_file)
        body_parts.append(f'{LOG_HEADER}\n{scrubbed}')

    body = '\n\n'.join(body_parts)
    visible(title, body)

    if no_facts:
        facts = None
    else:
        raw_facts = {'v': 1}
        for k in ('kind', 'area', 'host', 'driver', 'harness', 'model'):
            if k in data and data[k] is not None:
                raw_facts[k] = data[k]
        ow = read_openwiz_version()
        if ow:
            raw_facts['openwiz'] = ow
        ws = read_wizskills_version()
        if ws:
            raw_facts['wizskills'] = ws
        sk = read_skill_version()
        if sk:
            raw_facts['skill'] = sk
        raw_facts['os'] = read_os_family()
        raw_facts['arch'] = read_arch_family()
        if log_lines is not None:
            raw_facts['log_lines'] = log_lines
            raw_facts['redactions'] = redactions
        for k in drop:
            raw_facts.pop(k, None)
        facts = validate_facts(raw_facts)
    return title, body, facts, warnings, fields


def visible(title, body):
    for what, text in (('title', title), ('body', body)):
        hidden = next((c for c in text if unicodedata.category(c) == 'Cf'), None)
        if hidden:
            raise Stop(f'The {what} holds an invisible character, U+{ord(hidden):04X}; remove it.')


def full_body(chosen_body, op, facts=None):
    facts_line = format_facts_line(facts)
    if facts_line:
        body = f'{chosen_body}\n\n{facts_line}\n\n{MARKER}{op}'
    else:
        body = f'{chosen_body}\n\n{MARKER}{op}'
    if len(body) > BODY_MAX:
        raise Stop(f'The body with its marker is longer than {BODY_MAX} characters; shorten it.')
    return body


TOKEN_VARS = ('GH_TOKEN', 'GITHUB_TOKEN')


def link_hint(op=None):
    cmd = f'link {op}' if op else 'link <operation_id>'
    return f'or run {cmd} to open the public form in your browser.'


def no_gh_msg(op=None):
    return (f'GitHub CLI (gh) is not installed. Nothing was sent. '
            f'Install gh and sign in with gh auth login, {link_hint(op)}')


def gh_env(op=None):
    host = os.environ.get('GH_HOST', '')
    if host not in ('', 'github.com'):
        raise Stop('GH_HOST names another GitHub host; feedback goes only to github.com.')
    for name in TOKEN_VARS:
        if name in os.environ:
            raise Stop(f'{name} is set, so gh would use that token instead of your own login. Nothing was sent; '
                       f'OpenWiz never uses a token given to it. Unset {name} yourself to use gh, {link_hint(op)}')
    env = dict(os.environ)
    env.update(GH_PROMPT_DISABLED='1', NO_COLOR='1', GH_NO_UPDATE_NOTIFIER='1', GH_PAGER='cat')
    if not shutil.which('gh', path=env.get('PATH', '')):
        raise Stop(no_gh_msg(op))
    return env


def gh(args, payload=None, op=None):
    try:
        run = subprocess.run(['gh', 'api', '--include', *args], input=payload, capture_output=True,
                             env=gh_env(op), timeout=TIMEOUT_S)
    except FileNotFoundError:
        raise Stop(no_gh_msg(op))
    except (OSError, subprocess.TimeoutExpired):
        return None
    head, sep, rest = run.stdout.partition(b'\r\n\r\n')
    if not sep:
        head, sep, rest = run.stdout.partition(b'\n\n')
    first = head.split(b'\n', 1)[0].strip()
    status = re.fullmatch(rb'HTTP/[0-9.]+ ([1-5][0-9]{2})(?: .*)?', first)
    if not (sep and status):
        return None
    try:
        data = json.loads(rest.decode('utf-8'))
    except ValueError:
        return None
    code = int(status.group(1))
    if (code < 400) != (run.returncode == 0):
        return None
    return code, data


def read_destination(op=None):
    got = gh(['--method', 'GET', f'repos/{DESTINATION}'], op=op)
    if not got or got[0] != 200 or not isinstance(got[1], dict):
        raise Stop(f'The destination {DESTINATION} could not be read; nothing was sent.')
    repo = got[1]
    if not (same_name(repo.get('full_name'), DESTINATION) and repo.get('private') is False
            and repo.get('visibility') == 'public' and repo.get('archived') is False
            and repo.get('has_issues') is True):
        raise Stop(f'The destination {DESTINATION} is not a public, open repository with issues; nothing was sent.')


NO_LOGIN = 'Your GitHub login could not be read through gh. Nothing was sent; OpenWiz never logs in or uses another account.'


def stored_login(op=None):
    env = gh_env(op)
    try:
        run = subprocess.run(['gh', 'auth', 'status', '--json', 'hosts', '--hostname', 'github.com'],
                             capture_output=True, env=env, timeout=TIMEOUT_S)
        status = json.loads(run.stdout.decode('utf-8')) if run.returncode == 0 else None
    except FileNotFoundError:
        raise Stop(no_gh_msg(op))
    except (OSError, subprocess.TimeoutExpired, ValueError):
        status = None
    hosts = status.get('hosts') if isinstance(status, dict) else None
    entries = hosts.get('github.com') if isinstance(hosts, dict) else None
    if isinstance(entries, list) and len(entries) > 1:
        raise Stop(f'gh holds more than one GitHub account for github.com. Nothing was sent; '
                   f'OpenWiz never switches account. Remove extra accounts outside OpenWiz so only yours remains, '
                   f'{link_hint(op)}')
    entry = entries[0] if isinstance(entries, list) and entries else None
    if not (isinstance(entry, dict) and entry.get('active') is True
            and isinstance(entry.get('login'), str) and entry['login']):
        raise Stop(f'gh is installed, but you are not logged in to github.com. Nothing was sent; '
                   f'OpenWiz never logs in or uses another account. Run gh auth login yourself, {link_hint(op)}')
    return entry['login']


def read_account(op=None):
    login = stored_login(op)
    got = gh(['--method', 'GET', 'user'], op=op)
    user = got[1] if got and got[0] == 200 else None
    if not (isinstance(user, dict) and user.get('login') == login
            and type(user.get('id')) is int and user['id'] > 0):
        raise Stop(f'{NO_LOGIN} Run gh auth login yourself, {link_hint(op)}')
    return {'login': user['login'], 'id': user['id']}


def matches(issue, rec, number=None):
    return (isinstance(issue, dict) and same_name(issue.get('repository_url'), API_REPO)
            and 'pull_request' not in issue
            and (number is None or issue.get('number') == number)
            and isinstance(issue.get('user'), dict) and issue['user'].get('id') == rec['account']['id']
            and issue.get('title') == rec['title'] and issue.get('body') == rec['body'])


def read_issue(number):
    got = gh(['--method', 'GET', f'repos/{DESTINATION}/issues/{number}'])
    return got[1] if got and got[0] == 200 else None


SAY = {
    'draft': 'Draft kept; nothing previewed or sent.',
    'previewed': 'Shown exactly; waiting for an explicit yes to this preview.',
    'refused': 'Not sent. The draft is kept, so it can be edited and previewed again.',
    'sending': 'The create request is being made now.',
    'failed': 'GitHub refused the request, so no issue was created. You can preview it again and, after a new yes, try once more.',
    'uncertain': 'OpenWiz cannot tell whether the issue was created. Nothing will be sent again for it. Check the issue list, then reconcile.',
}


def sent_say(rec):
    url = rec['issue']['url'] if isinstance(rec.get('issue'), dict) and rec['issue'].get('url') else WEB_REPO
    return (f'Filed public issue {url} (read back; not yet read by the OpenWiz maintainers). '
            'OpenWiz\'s triage adds the `feedback` label and comments with the pull request and the release '
            'only if triage sends it to a fleet and that fix merges; a report held for the OpenWiz maintainers '
            'can close without that comment.')


def failed_say(rec):
    m = re.search(r'HTTP (\d{3})', rec.get('reason') or '')
    code = int(m.group(1)) if m else None
    hint = FAILED_HINTS.get(code)
    if hint:
        return (f'GitHub refused the request (HTTP {code}), so no issue was created. {hint} '
                'You can preview it again and, after a new yes, try once more.')
    return SAY['failed']


def answer(rec, **extra):
    if rec['phase'] == 'sent':
        say = sent_say(rec)
    elif rec['phase'] == 'failed':
        say = failed_say(rec)
    else:
        say = SAY[rec['phase']]
    a = {'operation_id': rec['operation_id'], 'phase': rec['phase'], 'say': say}
    if rec['reason']:
        a['reason'] = rec['reason']
    if rec['issue']:
        a['issue'] = rec['issue']
    if rec.get('warnings'):
        a['warnings'] = rec['warnings']
    if rec['phase'] == 'uncertain':
        a['check'] = f'{WEB_REPO}/issues?q=' + urllib.parse.quote(f'"{MARKER}{rec["operation_id"]}" in:body')
    a.update(extra)
    return a


def facts_summary_lines(facts):
    lines = []
    if 'kind' in facts:
        lines.append(f'- Kind: {facts["kind"]}')
    if 'area' in facts:
        lines.append(f'- Area: {facts["area"]}')
    if 'openwiz' in facts:
        lines.append(f'- OpenWiz {facts["openwiz"]}')
    if 'wizskills' in facts:
        lines.append(f'- WizSkills {facts["wizskills"]}')
    if 'skill' in facts:
        lines.append(f'- Skill: {facts["skill"]}')
    if 'os' in facts and 'arch' in facts:
        lines.append(f'- Platform: {facts["os"]}, {facts["arch"]}')
    elif 'os' in facts:
        lines.append(f'- OS: {facts["os"]}')
    elif 'arch' in facts:
        lines.append(f'- Arch: {facts["arch"]}')
    if 'host' in facts:
        lines.append(f'- Host: {facts["host"]}')
    if 'driver' in facts:
        lines.append(f'- Driver: {facts["driver"]}')
    if 'harness' in facts and 'model' in facts:
        lines.append(f'- Agent: {facts["harness"]}, model {facts["model"]}')
    elif 'harness' in facts:
        lines.append(f'- Agent: {facts["harness"]}')
    elif 'model' in facts:
        lines.append(f'- Model: {facts["model"]}')
    if 'log_lines' in facts and 'redactions' in facts:
        lines.append(f'- Log: {facts["log_lines"]} lines ({facts["redactions"]} redactions)')
    elif 'log_lines' in facts:
        lines.append(f'- Log: {facts["log_lines"]} lines')
    elif 'redactions' in facts:
        lines.append(f'- Log redactions: {facts["redactions"]}')
    return lines


def preview_text(rec):
    parts = [
        f'Destination: {DESTINATION} (public: anyone can read it)',
        f"Account: {rec['account']['login']}",
        f'A yes creates one public issue on {DESTINATION}, once.',
        '',
        'Title:',
        rec['title'],
        '',
        'Body:',
        rec['body'],
    ]
    if rec.get('facts'):
        parts.extend([
            '',
            "Facts (the facts line above the marker is for OpenWiz's agents):",
            *facts_summary_lines(rec['facts']),
            'To drop a fact, edit with --drop <key> (or --no-facts to drop all).',
        ])
    if rec.get('warnings'):
        parts.extend([
            '',
            'Warnings (you may keep or remove these before saying yes):',
            *(f'- {w}' for w in rec['warnings']),
        ])
    parts.extend([
        '',
        f"To create it, reply: yes {rec['preview']['id']}",
    ])
    return '\n'.join(parts)


def recorded(rec, lock_held=False):
    if rec['phase'] == 'sending' and not lock_held:
        rec = dict(rec, phase='uncertain', reason='a restart found the create request without its result',
                   evidence=rec['evidence'] + ['restart in sending'])
    return rec


def load_input(a):
    if a.report_file:
        if a.title_file or a.body_file:
            raise Stop('Use either --report-file or --title-file with --body-file, not both.')
        return chosen_report(a.report_file, log_file=a.log_file, drop=a.drop or (), no_facts=a.no_facts)
    if not (a.title_file and a.body_file):
        raise Stop('Pass --report-file, or both --title-file and --body-file.')
    if a.log_file or a.drop or a.no_facts:
        raise Stop('--log-file, --drop and --no-facts require --report-file.')
    return chosen(a.title_file, a.body_file)


def cmd_draft(a):
    place = area()
    title, body, facts, warnings, fields = load_input(a)
    op = secrets.token_hex(16)
    rec = dict(schema=SCHEMA, operation_id=op, destination=DESTINATION, phase='draft', title=title,
               chosen_body=body, body=full_body(body, op, facts), facts=facts, warnings=warnings,
               account=None, preview=None, attempts=0, issue=None, reason=None, evidence=[], report_fields=fields)
    with Lock(place, op), StoreLock(place):
        other = twin(place, op, title, body)
        if other:
            raise Stop(TWIN.format(other))
        write_record(place, rec)
    return out(answer(rec), 0)


def cmd_edit(a):
    place = area()
    title, body, facts, warnings, fields = load_input(a)
    with Lock(place, a.op):
        rec = recorded(read_record(record_path(place, a.op)))
        if rec['phase'] not in EDITABLE:
            return out(answer(rec, refused='This operation can no longer be edited.'), 1)
        with StoreLock(place):
            other = twin(place, a.op, title, body)
            if other:
                raise Stop(TWIN.format(other))
            rec.update(phase='draft', title=title, chosen_body=body, body=full_body(body, a.op, facts),
                       facts=facts, warnings=warnings, account=None, preview=None, reason=None, report_fields=fields)
            write_record(place, rec)
    return out(answer(rec), 0)


def cmd_preview(a):
    place = area()
    with Lock(place, a.op):
        stored = read_record(record_path(place, a.op))
        rec = recorded(stored)
        if rec['phase'] not in EDITABLE:
            if rec != stored:
                write_record(place, rec)
            return out(answer(rec, refused='This operation is not previewed again.'), 1)
        visible(rec['title'], rec['chosen_body'])
        check_secrets_and_warnings([('title', rec['title']), ('body', rec['chosen_body'])])
        validate_facts(rec['facts'])
        account = read_account(rec['operation_id'])
        read_destination(rec['operation_id'])
        rec.update(phase='previewed', account=account, reason=None,
                   preview={'id': f'{secrets.randbelow(10 ** 6):06d}', 'at': iso(now())})
        write_record(place, rec)
    return out(answer(rec, preview=preview_text(rec)), 0)


def cmd_refuse(a):
    place = area()
    with Lock(place, a.op):
        rec = recorded(read_record(record_path(place, a.op)))
        if rec['phase'] not in EDITABLE:
            return out(answer(rec), 1)
        rec.update(phase='refused', preview=None, reason=a.reason.strip() or 'refused')
        write_record(place, rec)
    return out(answer(rec), 0)


def refuse_send(place, rec, reason, say=None):
    rec.update(phase='refused', preview=None, reason=reason)
    write_record(place, rec)
    extra = {'say': say} if say else {}
    return out(answer(rec, **extra), 1)


def cmd_send(a):
    place = area()
    with Lock(place, a.op):
        stored = read_record(record_path(place, a.op))
        rec = recorded(stored)
        if rec['phase'] in ('sending', 'sent', 'failed', 'uncertain'):
            if rec != stored:
                write_record(place, rec)
            note = 'a failed operation needs a new preview and a new yes' if rec['phase'] == 'failed' else 'no create call was made'
            return out(answer(rec, refused=note), 1)
        if rec['phase'] != 'previewed' or not rec['preview']:
            return refuse_send(place, rec, 'there is no current preview to say yes to')
        try:
            visible(rec['title'], rec['chosen_body'])
            check_secrets_and_warnings([('title', rec['title']), ('body', rec['chosen_body'])])
            expected_body = full_body(rec['chosen_body'], rec['operation_id'], rec['facts'])
        except Stop as e:
            return refuse_send(place, rec, str(e))
        if not PREVIEW_ID.fullmatch(a.preview_id or '') or a.preview_id != rec['preview']['id']:
            return refuse_send(
                place, rec, 'the yes was for a different or earlier preview',
                say='Not sent: that preview code was wrong or missing, so this preview is void. '
                    'Preview again and reply with the new code.')
        try:
            account = read_account(rec['operation_id'])
            read_destination(rec['operation_id'])
        except Stop as e:
            return refuse_send(place, rec, str(e))
        if account != rec['account']:
            return refuse_send(place, rec, 'the GitHub account changed since the preview')
        if rec['body'] != expected_body:
            return refuse_send(place, rec, 'the body or facts changed since the preview')
        with StoreLock(place):
            other = twin(place, rec['operation_id'], rec['title'], rec['chosen_body'])
            if other:
                return refuse_send(place, rec, TWIN.format(other))
            rec.update(phase='sending', attempts=rec['attempts'] + 1, reason=None)
            try:
                write_record(place, rec)
            except SaveError as e:
                extra = (' The stored record may now read as sending, which status shows as uncertain; '
                         'reconcile before any new attempt.') if e.replaced else ''
                raise Stop(f'{e} No create request was made, so nothing was sent.{extra}')
        payload = json.dumps({'title': rec['title'], 'body': rec['body']}, ensure_ascii=False).encode('utf-8')
        got = gh(['--method', 'POST', f'repos/{DESTINATION}/issues', '--input', '-'], payload)
        if got and got[0] in FAILED_STATUSES:
            rec.update(phase='failed', preview=None, reason=f'GitHub answered HTTP {got[0]}',
                       evidence=rec['evidence'] + [f'create: complete HTTP {got[0]} response'])
        elif got and got[0] == 201 and isinstance(got[1], dict) and type(got[1].get('number')) is int:
            number = got[1]['number']
            url = f'{WEB_REPO}/issues/{number}'
            if matches(read_issue(number), rec, number):
                rec.update(phase='sent', preview=None, issue={'number': number, 'url': url},
                           evidence=rec['evidence'] + [f'create: HTTP 201; read back #{number}'])
            else:
                rec.update(phase='uncertain', issue={'number': number, 'url': url},
                           reason='created, but its read-back failed or differs',
                           evidence=rec['evidence'] + [f'create: HTTP 201 #{number}; read-back failed or differs'])
        else:
            what = f'HTTP {got[0]}' if got else 'no complete response'
            rec.update(phase='uncertain', reason=f'the create request ended with {what}',
                       evidence=rec['evidence'] + [f'create: {what}'])
        try:
            write_record(place, rec)
        except SaveError as e:
            if e.replaced:
                note = (f'{e} The outcome above is stored but not confirmed durable; after a crash the record '
                        'may read as sending, which is uncertain. Do not send again; run status first, and '
                        'reconcile if it reads uncertain.')
            else:
                note = (f'{e} The outcome above was not saved: the stored record still says sending, which reads '
                        'as uncertain. Do not send again; run status, then reconcile, once there is space to save.')
            return out(answer(rec, record_not_saved=note), 1)
    return out(answer(rec), 0 if rec['phase'] == 'sent' else 1)


def cmd_reconcile(a):
    place = area()
    with Lock(place, a.op):
        stored = read_record(record_path(place, a.op))
        rec = recorded(stored)
        if rec['phase'] != 'uncertain':
            return out(answer(rec, refused='Only an uncertain operation is reconciled.'), 1)

        def stay(reason):
            rec.update(reason=reason, evidence=rec['evidence'] + [f'reconcile: {reason}'])
            write_record(place, rec)
            return out(answer(rec), 1)
        try:
            account = read_account()
        except Stop:
            return stay('your GitHub login could not be read')
        if account != rec['account']:
            return stay('the GitHub account is not the one the preview bound')
        since = datetime.datetime.strptime(rec['preview']['at'], '%Y-%m-%dT%H:%M:%SZ') - SINCE_MARGIN
        query = f"repos/{DESTINATION}/issues?creator={account['login']}&state=all&since={iso(since)}&per_page=100"
        try:
            run = subprocess.run(['gh', 'api', '--method', 'GET', '--paginate', '--slurp', query],
                                 capture_output=True, env=gh_env(), timeout=TIMEOUT_S)
            pages = json.loads(run.stdout.decode('utf-8')) if run.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pages = None
        if not (isinstance(pages, list) and pages and all(isinstance(p, list) for p in pages)
                and all(isinstance(i, dict) and type(i.get('number')) is int for p in pages for i in p)):
            return stay('the issue list could not be read completely')
        marker = f"{MARKER}{rec['operation_id']}"
        numbers = {i['number'] for p in pages for i in p
                   if isinstance(i.get('body'), str) and i['body'].endswith(marker)}
        if a.issue:
            numbers.add(a.issue)
        issues = [read_issue(n) for n in sorted(numbers)]
        if any(i is None for i in issues):
            return stay('a candidate issue could not be read')
        issues = [i for i in issues if isinstance(i.get('body'), str) and i['body'].endswith(marker)]
        if not issues:
            return stay('no issue with this operation\'s marker was found; that alone does not prove none was created')
        if len(issues) > 1:
            return stay('more than one issue carries this marker; it may be duplicated')
        if not matches(issues[0], rec):
            return stay('the issue with this marker differs from the preview; it may have been changed')
        number = issues[0]['number']
        rec.update(phase='sent', preview=None, reason=None, issue={'number': number, 'url': f'{WEB_REPO}/issues/{number}'},
                   evidence=rec['evidence'] + [f'reconcile: exactly one matching #{number}'])
        write_record(place, rec)
    return out(answer(rec), 0)


def cmd_status(a):
    place = state_dir() / 'feedback'
    rec = read_record(record_path(place, a.op))
    rec = recorded(rec, Lock(place, a.op).held())
    extra = {'preview': preview_text(rec)} if rec['phase'] == 'previewed' else {}
    return out(answer(rec, **extra), 0)


def split_report_sections(chosen_body):
    lines = chosen_body.split('\n')
    if LOG_HEADER in lines:
        lines = lines[:lines.index(LOG_HEADER)]

    headers = {label: name for name, label in SECTION_HEADERS.items()}
    current = headers.get(lines[0]) if lines else None
    if current not in ('ran', 'happened'):
        text = '\n'.join(lines).rstrip()
        if text:
            return '', text, ''

    sections = {name: [] for name in SECTION_HEADERS}
    next_section = {'ran': 'happened', 'happened': 'expected'}
    for line in lines[1:]:
        if line in headers and sections[current] and sections[current][-1] == '':
            if headers[line] != next_section.get(current):
                break
            current = headers[line]
        else:
            sections[current].append(line)
    else:
        ran, happened, expected = ('\n'.join(sections[name]).rstrip() for name in SECTION_HEADERS)
        if happened:
            return ran, happened, expected
    raise Stop('The saved report sections could not be read. Edit the draft before using a browser link.')


def cmd_link(a):
    place = state_dir() / 'feedback'
    rec = read_record(record_path(place, a.op))
    rec = recorded(rec, Lock(place, a.op).held())
    if rec['phase'] not in EDITABLE:
        return out(answer(rec, refused='This operation is already sent or uncertain; do not file it again in the browser.'), 1)
    if 'report_fields' not in rec:
        ran, happened, expected = split_report_sections(rec['chosen_body'])
    elif rec['report_fields'] is None:
        ran, happened, expected = '', rec['chosen_body'], ''
    else:
        fields = rec['report_fields']
        if (not isinstance(fields, dict) or fields.keys() != SECTION_HEADERS.keys()
                or not all(isinstance(value, str) for value in fields.values()) or not fields['happened']):
            raise Stop('The saved report fields are unreadable. Edit the draft before using a browser link.')
        ran, happened, expected = (fields[name] for name in SECTION_HEADERS)
    visible(rec['title'], '\n'.join(p for p in (ran, happened, expected) if p))
    check_secrets_and_warnings([('title', rec['title']), ('ran', ran), ('happened', happened), ('expected', expected)])
    params = [
        ('template', 'feedback.yml'),
        ('title', rec['title']),
        ('what-happened', happened),
    ]
    if expected:
        params.append(('expected', expected))
    if ran:
        params.append(('steps', ran))
    facts = rec.get('facts') if isinstance(rec.get('facts'), dict) else {}
    if facts.get('openwiz'):
        params.append(('version', facts['openwiz']))
    setup_parts = []
    if facts.get('host'):
        setup_parts.append(f"Host: {facts['host']}")
    if facts.get('harness'):
        setup_parts.append(f"Harness: {facts['harness']}")
    if facts.get('model'):
        setup_parts.append(f"Model: {facts['model']}")
    if setup_parts:
        params.append(('setup', ', '.join(setup_parts)))
    url = f'{WEB_REPO}/issues/new?' + urllib.parse.urlencode(params)
    if len(url) > LINK_MAX:
        raise Stop(f'The browser link is longer than {LINK_MAX} characters; shorten it.')
    return out(answer(
        rec,
        url=url,
        say='Open this link in your browser to review and submit the public issue yourself. '
            'Nothing was sent, and OpenWiz does not count it as sent.',
    ), 0)


def cmd_list(a):
    place = state_dir() / 'feedback'
    if not place.exists():
        return out({'operations': [], 'say': 'No feedback operations found.'}, 0)
    info = os.lstat(place)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise Stop(f'{place} is not a plain directory.')
    rows = []
    for path in sorted(place.glob('*.json')):
        st = path.stat()
        rec = read_record(path)
        rec = recorded(rec, Lock(place, rec['operation_id']).held())
        preview_at = (rec['preview']['at']
                      if isinstance(rec.get('preview'), dict) and isinstance(rec['preview'].get('at'), str)
                      else None)
        rows.append((st.st_mtime_ns, preview_at or '', rec['operation_id'], {
            'operation_id': rec['operation_id'],
            'phase': rec['phase'],
            'title': rec['title'],
            'preview_at': preview_at,
        }))
    rows.sort(key=lambda r: (r[0], r[1], r[2]), reverse=True)
    ops = [r[3] for r in rows]
    say = f'{len(ops)} feedback operation(s), newest first.' if ops else 'No feedback operations found.'
    return out({'operations': ops, 'say': say}, 0)


def cmd_share(a):
    text = read_text(a.text_file, 'share text').replace('\r\n', '\n').strip()
    if not text:
        raise Stop('The share text is empty.')
    if '\r' in text or URLISH.search(text):
        raise Stop('The share text cannot hold a link, an address or a local host; the one allowed link is added on its own.')
    issue = SHARE_ISSUE.fullmatch(a.url)
    if a.url != WEB_REPO and not issue:
        raise Stop(f'Only {WEB_REPO} or one of its issues can be shared, with no query or fragment.')
    if issue:
        read_destination()
        got = read_issue(int(issue.group(1)))
        if not (isinstance(got, dict) and same_name(got.get('repository_url'), API_REPO) and 'pull_request' not in got
                and got.get('number') == int(issue.group(1))):
            raise Stop('That address is not an issue on the public OpenWiz repository.')
    return out({'share': f'{text}\n\n{a.url}',
                'say': 'This is exactly what you can copy. OpenWiz copies, posts and sends nothing.'}, 0)


DESCRIPTION = 'One consented feedback operation, under contracts/feedback.v1.md (#2292).'


class JsonParser(argparse.ArgumentParser):

    def error(self, message):
        raise Stop(f'Usage error: {message}')


def main(argv):
    p = JsonParser(prog='feedback.py', description=DESCRIPTION)
    sub = p.add_subparsers(dest='cmd', required=True)
    for name in ('draft', 'edit'):
        s = sub.add_parser(name)
        if name == 'edit':
            s.add_argument('op')
        s.add_argument('--title-file')
        s.add_argument('--body-file')
        s.add_argument('--report-file')
        s.add_argument('--log-file')
        s.add_argument('--drop', action='append', default=[])
        s.add_argument('--no-facts', action='store_true')
    for name in ('preview', 'status', 'link'):
        sub.add_parser(name).add_argument('op')
    sub.add_parser('list')
    s = sub.add_parser('refuse')
    s.add_argument('op')
    s.add_argument('--reason', required=True)
    s = sub.add_parser('send')
    s.add_argument('op')
    s.add_argument('--preview-id')
    s = sub.add_parser('reconcile')
    s.add_argument('op')
    s.add_argument('--issue', type=int)
    s = sub.add_parser('share')
    s.add_argument('--text-file', required=True)
    s.add_argument('--url', required=True)
    try:
        a = p.parse_args(argv)
        if getattr(a, 'issue', None) is not None and a.issue < 1:
            p.error('--issue must be a positive issue number')
        return globals()['cmd_' + a.cmd](a)
    except Stop as e:
        return out({'refused': str(e)}, 1)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
