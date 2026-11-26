#!/usr/bin/env python3
import json
import re
import sys
import unicodedata
from pathlib import Path

ISSUE = 'agent-issue'
PR = 'agent-pr'
SCHEMAS = {ISSUE: 'agent-issue/1', PR: 'agent-pr/1'}
KINDS = ('bug', 'feature', 'chore', 'spec', 'research')
READIES = ('ready-for-agent', 'needs-grill', 'blocked')
EFFORTS = ('tiny', 'small', 'medium', 'large')
GATES = ('release', 'secrets', 'auth', 'ci-permissions', 'migration', 'spending')
RESULTS = ('pass', 'fail')
ID_NUM = re.compile(r'^[1-9][0-9]{0,9}$')
ID_SLUG = re.compile(r'^[a-z][a-z0-9._]{0,63}$')
ACCEPTANCE = re.compile(r'^A[1-9][0-9]{0,3}$')
AGENT = re.compile(r'^[a-z][a-z0-9-]{0,31}$')
REPO = re.compile(r'^[a-z][a-z0-9_-]{0,40}$')
LANE = re.compile(r'^[a-z][a-z0-9]{0,20}$')
RISK = re.compile(r'^(low|medium|high)(?:: \S(?:.*\S)?)?$')
HEADER = re.compile(r'^Review #([1-9][0-9]{0,9}) at ([0-9a-f]{7})$')
FINDING = re.compile(r'^- (blocking|nit) (\S+):([1-9][0-9]*): (.+) Fix: (\S.*)$')
VERDICT = re.compile(r'^VERDICT: (APPROVE|CHANGES) at ([0-9a-f]{7})$')
SECRET = re.compile(
    r'-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----'
    r'|ghp_[A-Za-z0-9]{20,}'
    r'|github_pat_[A-Za-z0-9_]{20,}'
    r'|gho_[A-Za-z0-9]{20,}'
    r'|ghs_[A-Za-z0-9]{20,}'
    r'|ghu_[A-Za-z0-9]{20,}'
    r'|xox[baprs]-[A-Za-z0-9-]{10,}'
    r'|(?i:(?:api[_-]?key|token|secret|password)\s*[:=]\s*\S{8,})'
)
MAX_BODY = 65536
PROSE_MAX = 3
LIST_MAX = 20
ISSUE_KEYS = {
    'schema', 'id', 'kind', 'goal', 'summary', 'acceptance', 'owned_paths',
    'out_of_scope', 'depends', 'blocks', 'risk', 'gates', 'effort', 'ready', 'context',
}
ISSUE_REQUIRED = ISSUE_KEYS - {'summary'}
PR_KEYS = {
    'schema', 'closes', 'intent', 'changes', 'proof', 'risk', 'rollback',
    'owned_paths', 'gates',
}
USAGE = '''usage: python3 -I lint.py [--json] <command> ...
  issue  --body-file <path>
  pr     --body-file <path> [--issue-file <path>] [--mode ready|draft]
  review --body-file <path>
  branch --name <branch> [--repo <slug>] [--issue-id <id>]
  title  --title <text> --issue-id <id> [--expect <text>]
exit 0 valid, 1 findings, 2 bad invocation
'''


class RecordError(Exception):
    pass


def good_id(value):
    if not isinstance(value, str):
        return False
    if ID_NUM.fullmatch(value):
        return True
    return bool(ID_SLUG.fullmatch(value)) and not value.endswith('.') and '..' not in value


def good_path(path):
    if not isinstance(path, str) or not path or path != path.strip() or '\\' in path or path.startswith('/'):
        return False
    if not re.fullmatch(r'[A-Za-z0-9._@][A-Za-z0-9._@/-]*', path):
        return False
    parts = path[:-1].split('/') if path.endswith('/') else path.split('/')
    return bool(parts) and all(part not in ('', '.', '..') for part in parts)


def covered(owned, path):
    for prefix in owned:
        if prefix.endswith('/'):
            if path.startswith(prefix) or path + '/' == prefix:
                return True
        elif path == prefix:
            return True
    return False


def good_url(value):
    if not isinstance(value, str) or len(value) > 500 or any(ch.isspace() for ch in value):
        return False
    if not (value.startswith('https://') or value.startswith('http://')):
        return False
    host = value.split('://', 1)[1].split('/', 1)[0]
    return bool(host) and '@' not in host and '.' in host


def secret(text):
    return bool(SECRET.search(text))


def hidden(text):
    return any(unicodedata.category(ch) in {'Cc', 'Cf'} or ord(ch) == 127 for ch in text)


def problem(text, lo, hi):
    if not isinstance(text, str):
        return 'must be a string'
    if text != text.strip() or '\n' in text or '\r' in text:
        return 'must be one line'
    if secret(text):
        return 'looks like a secret'
    if hidden(text):
        return 'has a hidden character'
    if len(text) < lo or len(text) > hi:
        return 'must be %d to %d characters' % (lo, hi)
    return None


def sentence(text):
    why = problem(text, 8, 240)
    if why:
        return why
    if not text.endswith(('.', '?', '!')) or '. ' in text or '? ' in text or '! ' in text or ' ' not in text:
        return 'must be one sentence'
    return None


def command(text):
    why = problem(text, 1, 400)
    if why:
        return why
    if not re.match(r'^[A-Za-z0-9./_-]', text) or text.endswith(('.', '?', '!')):
        return 'must be a command'
    return None


def loads(text):
    def hook(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise RecordError('duplicate key')
            obj[key] = value
        return obj

    try:
        value = json.loads(text, object_pairs_hook=hook)
    except RecordError:
        raise
    except json.JSONDecodeError as exc:
        raise RecordError('JSON: ' + exc.msg) from exc
    if not isinstance(value, dict):
        raise RecordError('JSON must be an object')
    return value


def opener(line, info):
    if not line or line[0] not in '`~':
        return None
    char, n = line[0], 0
    while n < len(line) and line[n] == char:
        n += 1
    if n < 3:
        return None
    rest = line[n:].rstrip(' ')
    if rest != info or line[n + len(rest):].strip(' ') != '':
        return None
    return line[:n]


def closer(line, mark):
    token = line.rstrip(' ')
    return len(token) >= len(mark) and token.startswith(mark) and set(token) == {mark[0]}


def extract(text, info):
    lines = text.splitlines()
    records, inside, unclosed, i = [], set(), None, 0
    while i < len(lines):
        mark = opener(lines[i], info)
        if not mark:
            i += 1
            continue
        start = i
        i += 1
        body = []
        while i < len(lines) and not closer(lines[i], mark):
            body.append(lines[i])
            i += 1
        if i >= len(lines):
            unclosed = start + 1
            inside.update(range(start, len(lines)))
            break
        inside.update(range(start, i + 1))
        records.append((start + 1, '\n'.join(body)))
        i += 1
    prose = sum(1 for n, line in enumerate(lines) if n not in inside and line.strip())
    return records, prose, unclosed


def line_of(body, base, key):
    token = '"%s"' % key
    for offset, line in enumerate(body.splitlines()):
        if token in line:
            return base + 1 + offset
    return base


def finding(where, line, rule, message):
    return {'where': where, 'line': line, 'rule': rule, 'message': message}


class Bag:
    def __init__(self, where, body, base):
        self.where, self.body, self.base, self.findings = where, body, base, []

    def add(self, rule, message, key=None, line=None):
        item = finding(
            self.where,
            self.base if line is None and key is None else line if line is not None else line_of(self.body, self.base, key),
            rule, message)
        if item not in self.findings:
            self.findings.append(item)


def normalize(text):
    bom = text.startswith('\ufeff')
    if bom:
        text = text[1:]
    return text.replace('\r\n', '\n').replace('\r', '\n'), bom


def prepare(text, info):
    findings = []
    text, bom = normalize(text)
    if bom:
        findings.append(finding('body', 1, 'text', 'starts with a hidden character'))
    if '\x00' in text or len(text.encode('utf-8')) > MAX_BODY:
        findings.append(finding('body', 1, 'text', 'is empty, binary, or longer than 65536 bytes'))
        return findings, None
    if secret(text):
        findings.append(finding('body', 1, 'text', 'looks like a secret'))
    records, prose, unclosed = extract(text, info)
    if prose > PROSE_MAX:
        findings.append(finding('body', 1, 'prose', 'keep prose to at most 3 lines'))
    if unclosed:
        findings.append(finding('body', unclosed, 'fence', 'fence is not closed'))
        return findings, None
    if len(records) != 1:
        findings.append(finding('body', 1, 'fence', 'needs exactly one %s fence' % info))
        return findings, None
    base, body = records[0]
    try:
        obj = loads(body)
    except RecordError as exc:
        findings.append(finding('body', base, 'json', str(exc)))
        return findings, None
    return findings, (obj, body, base)


def require(bag, obj, required, allowed):
    for key in obj:
        if key not in allowed:
            bag.add('keys', 'unknown key', key)
    for key in sorted(required):
        if key not in obj:
            bag.add(key, 'missing', key)


def string_items(bag, obj, key, check, empty_ok, message):
    if key not in obj:
        return None
    value = obj[key]
    if not isinstance(value, list) or len(value) > LIST_MAX or (not value and not empty_ok):
        bag.add(key, message, key)
        return None
    seen = set()
    for item in value:
        if not isinstance(item, str) or item in seen or not check(item):
            bag.add(key, message, key)
            return None
        seen.add(item)
    return value


def gates_of(bag, obj):
    if 'gates' not in obj:
        return None
    value = obj['gates']
    if (not isinstance(value, list) or len(value) != len(set(value))
            or any(not isinstance(item, str) or item not in GATES for item in value)):
        bag.add('gates', 'must list only release, secrets, auth, ci-permissions, migration, spending', 'gates')
        return None
    return value


def paths_of(bag, obj):
    return string_items(bag, obj, 'owned_paths', good_path, False, 'must list repo-relative paths')


def acceptance_of(bag, obj):
    if 'acceptance' not in obj:
        return None
    value = obj['acceptance']
    if not isinstance(value, list) or not value or len(value) > LIST_MAX:
        bag.add('acceptance', 'must be a non-empty list', 'acceptance')
        return None
    seen_id, seen_check, items = set(), set(), []
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != {'id', 'check'}:
            bag.add('acceptance', 'each item has id and check', 'acceptance')
            return None
        ident, check = entry['id'], entry['check']
        if not isinstance(ident, str) or not ACCEPTANCE.fullmatch(ident) or ident in seen_id:
            bag.add('acceptance', 'each id is a unique A1, A2, ...', 'acceptance')
            return None
        if command(check) or check in seen_check:
            bag.add('acceptance', 'each check is a unique command', 'acceptance')
            return None
        seen_id.add(ident)
        seen_check.add(check)
        items.append(entry)
    return items


def title_fits(ident, text):
    prefix = '#%s: ' % ident if ID_NUM.fullmatch(ident) else '%s: ' % ident
    return len(prefix) + len(text) <= 256


def risk_problem(text):
    why = problem(text, 3, 200)
    if why:
        return why
    if not RISK.fullmatch(text):
        return 'must be low, medium, or high, with an optional note'
    return None


def check_issue(obj, body, base):
    bag = Bag('body', body, base)
    require(bag, obj, ISSUE_REQUIRED, ISSUE_KEYS)
    if obj.get('schema') != SCHEMAS[ISSUE]:
        bag.add('schema', 'must be %s' % SCHEMAS[ISSUE], 'schema')
    ident = obj.get('id')
    if 'id' in obj and not good_id(ident):
        bag.add('id', 'must be a number or a lowercase slug with no hyphen', 'id')
    if 'kind' in obj and obj['kind'] not in KINDS:
        bag.add('kind', 'must be bug, feature, chore, spec, or research', 'kind')
    if 'goal' in obj:
        why = sentence(obj['goal'])
        if why:
            bag.add('goal', why, 'goal')
    if 'summary' in obj:
        why = problem(obj['summary'], 1, 120)
        if why:
            bag.add('summary', why, 'summary')
    acceptance_of(bag, obj)
    paths_of(bag, obj)
    string_items(bag, obj, 'out_of_scope', lambda item: problem(item, 1, 200) is None, True,
                 'each entry is a unique one-line string')
    depends = string_items(bag, obj, 'depends', good_id, True, 'must list issue ids')
    blocks = string_items(bag, obj, 'blocks', good_id, True, 'must list issue ids')
    if 'risk' in obj:
        why = risk_problem(obj['risk'])
        if why:
            bag.add('risk', why, 'risk')
    gates_of(bag, obj)
    if 'effort' in obj and obj['effort'] not in EFFORTS:
        bag.add('effort', 'must be tiny, small, medium, or large', 'effort')
    if 'ready' in obj and obj['ready'] not in READIES:
        bag.add('ready', 'must be ready-for-agent, needs-grill, or blocked', 'ready')
    if 'context' in obj:
        string_items(bag, obj, 'context', lambda item: good_url(item) or good_path(item), True,
                     'must list http(s) urls or repo-relative paths')
    if good_id(ident) and isinstance(depends, list) and isinstance(blocks, list):
        if ident in depends or ident in blocks:
            bag.add('depends', 'must not name itself', 'depends')
        if set(depends) & set(blocks):
            bag.add('blocks', 'must not repeat depends', 'blocks')
    ready, effort = obj.get('ready'), obj.get('effort')
    if ready == 'ready-for-agent' and depends:
        bag.add('ready', 'ready-for-agent requires empty depends', 'ready')
    if ready == 'blocked' and isinstance(depends, list) and not depends:
        bag.add('ready', 'blocked requires depends', 'ready')
    if ready == 'ready-for-agent' and effort == 'large':
        bag.add('effort', 'split a large issue before ready-for-agent', 'effort')
    shown = obj.get('summary') if isinstance(obj.get('summary'), str) else obj.get('goal')
    if good_id(ident) and isinstance(shown, str) and not title_fits(ident, shown):
        bag.add('summary', 'add one so the title fits in 256 characters', 'summary')
    return bag.findings


def paired(bag, obj, key, fields, label):
    if key not in obj:
        return None
    value = obj[key]
    if not isinstance(value, list) or not value or len(value) > LIST_MAX:
        bag.add(key, 'must be a non-empty list', key)
        return None
    seen, items = set(), []
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != set(fields):
            bag.add(key, label, key)
            return None
        ident = entry.get('acceptance')
        if not isinstance(ident, str) or not ACCEPTANCE.fullmatch(ident) or ident in seen:
            bag.add(key, 'each acceptance id is a unique A1, A2, ...', key)
            return None
        seen.add(ident)
        items.append(entry)
    return items


def check_pr(obj, body, base, mode):
    bag = Bag('body', body, base)
    require(bag, obj, PR_KEYS, PR_KEYS)
    if obj.get('schema') != SCHEMAS[PR]:
        bag.add('schema', 'must be %s' % SCHEMAS[PR], 'schema')
    if 'closes' in obj and not good_id(obj['closes']):
        bag.add('closes', 'must be one issue id', 'closes')
    if 'intent' in obj:
        why = sentence(obj['intent'])
        if why:
            bag.add('intent', why, 'intent')
    changes = paired(bag, obj, 'changes', ('acceptance', 'change'), 'each item has acceptance and change')
    proof = paired(bag, obj, 'proof', ('acceptance', 'command', 'result', 'red_first'),
                   'each item has acceptance, command, result, and red_first')
    if changes is not None:
        for entry in changes:
            why = problem(entry['change'], 1, 200)
            if why:
                bag.add('changes', why, 'changes')
                break
    if proof is not None:
        for entry in proof:
            why = command(entry['command'])
            if why or entry['result'] not in RESULTS or not isinstance(entry['red_first'], bool):
                bag.add('proof', 'needs a command, result pass or fail, and red_first true or false', 'proof')
                break
            if mode == 'ready' and entry['result'] != 'pass':
                bag.add('proof', 'result must be pass before review', 'proof')
                break
    if changes is not None and proof is not None:
        if {item['acceptance'] for item in changes} != {item['acceptance'] for item in proof}:
            bag.add('proof', 'must cover the same acceptance ids as changes', 'proof')
    if 'risk' in obj:
        why = risk_problem(obj['risk'])
        if why:
            bag.add('risk', why, 'risk')
    if 'rollback' in obj:
        why = problem(obj['rollback'], 8, 200)
        if why:
            bag.add('rollback', why, 'rollback')
    paths_of(bag, obj)
    gates_of(bag, obj)
    return bag.findings


def cross(pr, issue, body, base):
    bag = Bag('body', body, base)
    if issue['ready'] != 'ready-for-agent':
        bag.add('ready', 'the issue is not ready-for-agent', line=1)
    if pr['closes'] != issue['id']:
        bag.add('closes', 'must be the issue id', 'closes')
    if set(pr['gates']) != set(issue['gates']):
        bag.add('gates', 'must match the issue', 'gates')
    wanted = {item['id']: item['check'] for item in issue['acceptance']}
    got = {item['acceptance'] for item in pr['changes']}
    proved = {item['acceptance']: item for item in pr['proof']}
    if got != set(wanted) or set(proved) != set(wanted):
        bag.add('changes', 'must cover each acceptance id once', 'changes')
    else:
        for ident, check in wanted.items():
            if proved[ident]['command'] != check:
                bag.add('proof', 'command must equal the acceptance check', 'proof')
                break
    for path in pr['owned_paths']:
        if not covered(issue['owned_paths'], path):
            bag.add('owned_paths', 'leaves the issue owned paths', 'owned_paths')
            break
    if issue['kind'] == 'bug' and not any(item['red_first'] for item in pr['proof']):
        bag.add('proof', 'a bug needs red_first true', 'proof')
    return bag.findings


def lint_issue(text):
    findings, parsed = prepare(text, ISSUE)
    if not parsed:
        return findings
    obj, body, base = parsed
    findings.extend(check_issue(obj, body, base))
    return findings


def lint_pr(text, issue_text=None, mode='ready'):
    findings, parsed = prepare(text, PR)
    obj = body = base = None
    if parsed:
        obj, body, base = parsed
        findings.extend(check_pr(obj, body, base, mode))
    issue = None
    issue_findings = []
    if issue_text is not None:
        issue_findings, issue_parsed = prepare(issue_text, ISSUE)
        if issue_parsed:
            issue, issue_body, issue_base = issue_parsed
            issue_findings = issue_findings + check_issue(issue, issue_body, issue_base)
        for item in issue_findings:
            item['where'] = 'issue'
    if issue_text is not None and not findings and not issue_findings and obj is not None and issue is not None:
        findings.extend(cross(obj, issue, body, base))
    return findings + issue_findings


def lint_review(text):
    text, bom = normalize(text)
    findings = []
    if bom or '\x00' in text:
        findings.append(finding('body', 1, 'text', 'has a hidden character'))
    if secret(text):
        findings.append(finding('body', 1, 'text', 'looks like a secret'))
    content = [(n, line) for n, line in enumerate(text.splitlines(), 1) if line.strip()]
    if not content:
        findings.append(finding('body', 1, 'review', 'missing header'))
        return findings
    header = HEADER.fullmatch(content[0][1])
    if not header:
        findings.append(finding('body', content[0][0], 'review', 'header must be Review #<n> at <sha7>'))
    verdict = VERDICT.fullmatch(content[-1][1]) if len(content) > 1 else None
    if not verdict:
        findings.append(finding('body', content[-1][0], 'verdict', 'last line must be VERDICT: APPROVE|CHANGES at <sha7>'))
    if header and verdict and header.group(2) != verdict.group(2):
        findings.append(finding('body', content[-1][0], 'verdict', 'header sha and verdict sha differ'))
    blocking = 0
    for n, line in content[1:-1] if verdict else content[1:]:
        match = FINDING.fullmatch(line)
        if not match or line.count(' Fix: ') != 1:
            findings.append(finding('body', n, 'finding', 'must be severity, file:line, issue, and Fix'))
            continue
        if not good_path(match.group(2)):
            findings.append(finding('body', n, 'finding', 'path must stay inside the repository'))
        if problem(match.group(4), 1, 200) or problem(match.group(5), 1, 200):
            findings.append(finding('body', n, 'finding', 'issue and fix must each be one line'))
        if match.group(1) == 'blocking':
            blocking += 1
    if verdict and verdict.group(1) == 'APPROVE' and blocking:
        findings.append(finding('body', content[-1][0], 'verdict', 'APPROVE requires zero blocking findings'))
    if verdict and verdict.group(1) == 'CHANGES' and not blocking:
        findings.append(finding('body', content[-1][0], 'verdict', 'CHANGES requires a blocking finding'))
    return findings


def parse_branch(name):
    if not isinstance(name, str) or name.count('/') != 1:
        return None, 'must be <agent>/<repo>-<N>-<lane>'
    agent, rest = name.split('/', 1)
    parts = rest.split('-')
    if (not AGENT.fullmatch(agent) or agent.endswith('-') or '--' in agent or len(parts) < 3):
        return None, 'must be <agent>/<repo>-<N>-<lane>'
    lane, number, repo = parts[-1], parts[-2], '-'.join(parts[:-2])
    if (not repo or not REPO.fullmatch(repo) or repo.endswith('-') or '--' in repo
            or not LANE.fullmatch(lane) or not good_id(number)):
        return None, 'must be <agent>/<repo>-<N>-<lane>'
    return {'agent': agent, 'repo': repo, 'id': number, 'lane': lane}, None


def lint_branch(name, repo=None, issue_id=None):
    parsed, why = parse_branch(name)
    if why:
        return [finding('branch', 1, 'branch', why)]
    findings = []
    if repo is not None and (not isinstance(repo, str) or not REPO.fullmatch(repo) or repo.endswith('-') or '--' in repo):
        findings.append(finding('branch', 1, 'repo', 'must be a lowercase slug'))
    elif repo is not None and parsed['repo'] != repo:
        findings.append(finding('branch', 1, 'repo', 'segment must match --repo'))
    if issue_id is not None and not good_id(issue_id):
        findings.append(finding('branch', 1, 'id', 'must be a number or a lowercase slug with no hyphen'))
    elif issue_id is not None and parsed['id'] != issue_id:
        findings.append(finding('branch', 1, 'id', 'N must be the issue id'))
    return findings


def lint_title(title, issue_id, expect=None):
    if not good_id(issue_id):
        return [finding('title', 1, 'id', 'must be a number or a lowercase slug with no hyphen')]
    if not isinstance(title, str) or '\n' in title or title != title.strip() or secret(title) or hidden(title):
        return [finding('title', 1, 'title', 'must be one line')]
    prefix = '#%s: ' % issue_id if ID_NUM.fullmatch(issue_id) else '%s: ' % issue_id
    findings = []
    if not title.startswith(prefix):
        findings.append(finding('title', 1, 'title', 'must start with %s' % prefix))
    elif expect is not None and title[len(prefix):] != expect:
        findings.append(finding('title', 1, 'title', 'must use the summary, or the goal when there is no summary'))
    if len(title) > 256:
        findings.append(finding('title', 1, 'title', 'must be at most 256 characters'))
    return findings


def report(findings, as_json):
    findings = sorted(findings, key=lambda item: (item['where'], item['line'], item['rule'], item['message']))
    if as_json:
        print(json.dumps({'ok': not findings, 'findings': findings}, sort_keys=True))
    else:
        for item in findings:
            print('%s:%d: %s: %s' % (item['where'], item['line'], item['rule'], item['message']))
        print('agent-record: ok' if not findings else 'agent-record: %d finding(s)' % len(findings))
    return 1 if findings else 0


def read_text(path):
    if path == '-':
        return sys.stdin.read()
    try:
        return Path(path).read_text(encoding='utf-8')
    except (OSError, UnicodeError) as exc:
        raise RecordError('%s: unreadable' % path) from exc


def options(argv, required, optional):
    opts, i = {}, 0
    while i < len(argv):
        key = argv[i]
        if key not in required | optional or i + 1 >= len(argv):
            return None
        opts[key] = argv[i + 1]
        i += 2
    if not required <= set(opts):
        return None
    return opts


def main(argv):
    as_json = False
    args = []
    for arg in argv:
        if arg == '--json':
            as_json = True
        elif arg in ('-h', '--help'):
            print(USAGE, end='')
            return 0
        else:
            args.append(arg)
    if not args:
        print(USAGE, end='', file=sys.stderr)
        return 2
    cmd, rest = args[0], args[1:]
    try:
        if cmd == 'issue':
            opts = options(rest, {'--body-file'}, set())
            if opts is None:
                raise RecordError('usage')
            findings = lint_issue(read_text(opts['--body-file']))
        elif cmd == 'pr':
            opts = options(rest, {'--body-file'}, {'--issue-file', '--mode'})
            if opts is None:
                raise RecordError('usage')
            mode = opts.get('--mode', 'ready')
            if mode not in ('ready', 'draft'):
                raise RecordError('usage')
            issue = read_text(opts['--issue-file']) if '--issue-file' in opts else None
            findings = lint_pr(read_text(opts['--body-file']), issue, mode)
        elif cmd == 'review':
            opts = options(rest, {'--body-file'}, set())
            if opts is None:
                raise RecordError('usage')
            findings = lint_review(read_text(opts['--body-file']))
        elif cmd == 'branch':
            opts = options(rest, {'--name'}, {'--repo', '--issue-id'})
            if opts is None:
                raise RecordError('usage')
            findings = lint_branch(opts['--name'], opts.get('--repo'), opts.get('--issue-id'))
        elif cmd == 'title':
            opts = options(rest, {'--title', '--issue-id'}, {'--expect'})
            if opts is None:
                raise RecordError('usage')
            findings = lint_title(opts['--title'], opts['--issue-id'], opts.get('--expect'))
        else:
            raise RecordError('usage')
    except RecordError as exc:
        print(USAGE if str(exc) == 'usage' else str(exc), end='' if str(exc) == 'usage' else '\n', file=sys.stderr)
        return 2
    return report(findings, as_json)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
