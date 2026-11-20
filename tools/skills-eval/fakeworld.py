"""The fake-tool boundary (contract.md, section 2).

One `shell` tool, run in process against a case's synthetic world. It starts no
process, opens no socket and reads no environment variable. Repository files
come from a read-only snapshot callable; file writes go to an in-memory overlay.
"""
import copy
import fnmatch
import json
import re
import shlex

ESCAPES = {
    'curl', 'wget', 'ssh', 'scp', 'sftp', 'nc', 'ncat', 'netcat', 'telnet', 'ftp',
    'rsync', 'python', 'python3', 'node', 'deno', 'bun', 'perl',
    'ruby', 'php', 'bash', 'sh', 'zsh', 'dash', 'fish', 'env', 'eval', 'exec',
    'source', '.', 'sudo', 'su', 'xargs', 'nohup', 'setsid', 'timeout', 'docker',
    'socat', 'openssl', 'claude', 'codex', 'busybox', 'awk',
    'gawk', 'find', 'open', 'xdg-open', 'osascript', 'crontab', 'at', 'systemctl',
    'pkill', 'killall', 'jq',
}
READERS = {'cat', 'head', 'tail', 'sed', 'grep', 'ls', 'wc', 'echo', 'printf',
           'true', 'mkdir', 'date', 'ps', 'sleep', 'pwd', 'sort', 'uniq', 'cut', 'mktemp', 'rm', 'test', '['}
PROGRAMS = {'gh', 'room-cli', 'git', 'kill'} | READERS
CWD = '/repo'


class Result:
    """A command's output and exit code; `error` marks a failed command (not found, refused,
    unsupported), as against a real result that exits nonzero, such as failed checks."""

    def __init__(self, out='', code=0, error=False):
        self.out, self.code, self.error = out, code, error


def _err(msg, code=1):
    return Result(msg.rstrip('\n') + '\n', code, True)


class World:
    """A case's fake GitHub, CloudRoom, processes, git and files."""

    def __init__(self, world, snapshot):
        self.w = copy.deepcopy(world)
        self.snapshot = snapshot  # (read(path) -> str | None, list(prefix) -> [paths])
        self.overlay = dict(self.w.get('files', {}))
        self.events = []
        gh = self.w.setdefault('github', {})
        gh.setdefault('issues', {})
        gh.setdefault('pulls', {})
        gh.setdefault('labels', ['needs-info', 'ready-for-agent', 'held', 'polish',
                                 'no-changelog', 'needs-triage', 'ready-for-human', 'wontfix'])
        gh.setdefault('repo', 'example/project')
        gh.setdefault('runs', [])
        cr = self.w.setdefault('cloudroom', {})
        cr.setdefault('self', 'thr_synth_self')
        cr.setdefault('threads', [])
        cr.setdefault('loops', [])
        self.w.setdefault('processes', [])
        g = self.w.setdefault('git', {})
        g.setdefault('branch', 'room/4000-synthetic')
        g.setdefault('head', 'a' * 40)
        g.setdefault('origin_main', 'b' * 40)
        g.setdefault('status', '')
        g.setdefault('diff_names', [])
        g.setdefault('conflict', False)
        self.w.setdefault('now', '2030-01-07T12:00:00Z')
        self.vars = {}
        self._last = 0
        self._tmp = 0
        self._next_comment = 9000001
        self._next_thread = 1

    # ---- events -------------------------------------------------------
    def _event(self, kind, argv, body=None):
        self.events.append({'seq': len(self.events) + 1, 'kind': kind, 'argv': list(argv), 'body': body,
                            'code': {'escape': 126, 'local': 0}.get(kind),
                            'error': {'escape': True, 'local': False, 'refused': True}.get(kind)})

    # ---- the tool -----------------------------------------------------
    def shell(self, command):
        """Run one command string; return its combined output and exit code."""
        try:
            text, heredocs = _extract_heredocs(command)
        except ValueError as e:
            self._event('refused', ['<parse>'], str(e))
            return _err(f'fake shell: {e}', 2)
        if _executable_substitution(text):
            self._event('escape', ['<substitution>'], command)
            return _err('fake shell: backticks and process substitution are not available here', 126)
        try:
            stmts = _split_raw(text)
            for _, raw in stmts:  # static check first: nothing runs if any part escapes
                self._check(self._assign(_tokens(self._expand(raw, static=True)), record=False), command)
        except _Escaped:
            return _err('fake shell: not available in this sandbox', 126)
        except ValueError as e:
            self._event('refused', ['<parse>'], str(e))
            return _err(f'fake shell: {e}', 2)
        out, code, stdin, skip = [], 0, None, False
        for k, (op, raw) in enumerate(stmts):
            if op == '&&' and code != 0 or op == '||' and code == 0:
                skip = True
            elif op in (None, '&&', '||', ';'):
                skip = False
            if skip:
                continue
            try:
                seg = self._assign(_tokens(self._expand(raw)))
                self._check(seg, command)
            except _Escaped:
                return _err('fake shell: not available in this sandbox', 126)
            except ValueError as e:
                self._event('refused', ['<parse>'], str(e))
                return _err(f'fake shell: {e}', 2)
            argv, redirect, append, stdin_file = _redirects(seg, heredocs)
            if op != '|':
                stdin = None
            if not argv:
                code = 0
                continue
            if stdin_file is not None:
                stdin = stdin_file[1:] if stdin_file.startswith('\0') else self._read(stdin_file)
            before = len(self.events)
            r = self._run(argv, stdin)
            for e in self.events[before:]:
                if e['code'] is None:
                    e['code'] = r.code
                if e['error'] is None:
                    e['error'] = r.error
            code = self._last = r.code
            if redirect:
                if redirect != '/dev/null':
                    self._write_file(redirect, r.out, append)
                r = Result('', r.code)
            if k + 1 < len(stmts) and stmts[k + 1][0] == '|':
                stdin = r.out
            else:
                out.append(r.out)
        return Result(''.join(out), code)

    def _check(self, seg, command):
        """The boundary: raise _Escaped (after recording it) for an escape."""
        argv = [t for t in seg if t]
        if not argv or self._script_argv(argv) is not None or self._canned(argv) is not None:
            return
        prog = argv[0]
        if prog in ESCAPES or prog.startswith('/') or prog.startswith('./') or prog.startswith('~'):
            self._event('escape', argv, command)
            raise _Escaped()
        for path in _paths(argv):
            if not self._path_ok(path):
                self._event('escape', argv, command)
                raise _Escaped()

    def _expand(self, text, static=False):
        """`$(cmd)` runs cmd in this fake shell; `$NAME` and `${NAME}` expand; single quotes protect."""
        out, i, quote = [], 0, None
        while i < len(text):
            ch = text[i]
            if ch == '\\' and quote != "'" and i + 1 < len(text):
                out.append(text[i:i + 2])
                i += 2
                continue
            if ch == "'" and quote != '"':
                quote = None if quote == "'" else "'"
            elif ch == '"' and quote != "'":
                quote = None if quote == '"' else '"'
            elif ch == '$' and quote != "'":
                if text.startswith('$(', i):
                    depth, j, q = 1, i + 2, None
                    while j < len(text) and depth:
                        c = text[j]
                        if c in '\'"' and q in (None, c):
                            q = None if q == c else c
                        elif q is None and c == '(':
                            depth += 1
                        elif q is None and c == ')':
                            depth -= 1
                        j += 1
                    if depth:
                        raise ValueError('unclosed $(')
                    inner = text[i + 2:j - 1]
                    if static:
                        for _, raw in _split_raw(inner):
                            self._check(self._assign(_tokens(self._expand(raw, static=True)), record=False), inner)
                    else:
                        before = len(self.events)
                        r = self.shell(inner)
                        if any(e['kind'] == 'escape' for e in self.events[before:]):
                            raise _Escaped()
                        self._last = r.code
                        out.append(r.out.rstrip('\n'))
                    i = j
                    continue
                m = re.match(r'\$(?:\{(\w+)\}|(\w+)|(\?))', text[i:])
                if m:
                    name = m.group(1) or m.group(2)
                    out.append('' if static else str(self._last) if m.group(3) else self.vars.get(name, ''))
                    i += m.end()
                    continue
            out.append(ch)
            i += 1
        return ''.join(out)

    def _assign(self, seg, record=True):
        """Drop leading NAME=VALUE words (and `export`), keeping their values."""
        seg = list(seg)
        if seg and seg[0] == 'export':
            seg = seg[1:]
        while seg and re.fullmatch(r'[A-Za-z_]\w*=.*', seg[0], re.S):
            k, v = seg.pop(0).split('=', 1)
            if record:
                self.vars[k] = v
                self._event('local', ['assign', k])
        return seg

    # ---- files --------------------------------------------------------
    def _norm(self, path):
        if path.startswith(CWD + '/'):
            path = path[len(CWD) + 1:]
        if path.startswith('./'):
            path = path[2:]
        return path.rstrip('/') if path not in ('/', '') else path

    def _path_ok(self, path):
        if path in ('/dev/null', '-') or path.startswith('/tmp/') or path == '/tmp':
            return '..' not in path.split('/')
        if path.startswith('~') or '..' in path.split('/'):
            return False
        if path.startswith('/'):
            return path == CWD or path.startswith(CWD + '/')
        return True

    def _read(self, path):
        p = self._norm(path)
        if p in self.overlay:
            return self.overlay[p]
        return self.snapshot[0](p) if not p.startswith('/') else None

    def _write_file(self, path, text, append=False):
        p = self._norm(path)
        self.overlay[p] = (self.overlay.get(p, '') if append else '') + text
        self._event('local', ['write-file', p], self.overlay[p])

    def _list(self, path):
        p = self._norm(path or '.')
        p = '' if p in ('.', '') else p
        names = set()
        pre = p + '/' if p else ''
        for f in list(self.snapshot[1](pre)) + [k for k in self.overlay if k.startswith(pre)]:
            names.add(f[len(pre):].split('/')[0])
        return sorted(names)

    # ---- dispatch -----------------------------------------------------
    def _script_argv(self, argv):
        """`[path, *args]` when argv runs a repository script, else None."""
        i = 0
        if argv[0] in ('sh', 'bash', 'python3', 'python'):
            i = 1
            while i < len(argv) and argv[i] in ('-I', '-u', '-e', '-x', '-eu'):
                i += 1
        if i >= len(argv):
            return None
        p = argv[i]
        if p.startswith('"'):
            return None
        if not (p.startswith(CWD + '/') or (not p.startswith('/') and '/' in p)):
            return None
        p = self._norm(p)
        if '..' in p.split('/') or self.snapshot[0](p) is None:
            return None
        return [p] + argv[i + 1:]

    def _canned(self, argv):
        """The world's canned answer for this argv (a script or a tool such as cargo)."""
        sargv = self._script_argv(argv)
        key = ['script'] + sargv if sargv is not None else argv
        for s in self.w.get('scripts', []):
            if key[:len(s['argv'])] == s['argv']:
                return key, s
        return None

    def _script(self, argv):
        hit = self._canned(argv)
        if hit:
            key, s = hit
            self._event(s.get('kind', 'read'), key)
            return Result(s.get('out', ''), s.get('code', 0))
        sargv = self._script_argv(argv)
        self._event('refused', ['script'] + sargv)
        return _err(f'fake shell: {sargv[0]}: this script gives no answer in this case', 127)

    def _run(self, argv, stdin):
        if self._script_argv(argv) is not None or self._canned(argv) is not None:
            return self._script(argv)
        prog = argv[0]
        if prog not in PROGRAMS:
            self._event('refused', argv)
            return _err(f'fake shell: {prog}: command not found', 127)
        try:
            if prog == 'gh':
                r = self._gh(argv, stdin)
                if r.code == 0 and any(a in ('--jq', '-q', '--template', '-t') or a.startswith('--jq=') for a in argv):
                    r = Result('fake gh: --jq and --template are not applied in this sandbox; the full JSON follows\n' + r.out)
                return r
            if prog == 'room-cli':
                return self._room(argv, stdin)
            if prog == 'git':
                return self._git(argv)
            if prog == 'kill':
                return self._kill(argv)
            return self._reader(argv, stdin)
        except _Usage as e:
            self._event('refused', argv, str(e))
            return _err(f'{prog}: {e}')

    def _reader(self, argv, stdin):
        prog, args = argv[0], argv[1:]
        self._event('read', argv)
        if prog in ('true', 'mkdir'):
            return Result()
        if prog == 'mktemp':
            self._tmp += 1
            p = f'/tmp/tmp.synth{self._tmp}'
            self.overlay[p] = ''
            return Result(p + '\n')
        if prog == 'rm':
            for a in args:
                if a.startswith('/tmp/'):
                    self.overlay.pop(a, None)
            return Result()
        if prog in ('test', '['):
            a = [x for x in args if x != ']']
            if len(a) == 2 and a[0] in ('-f', '-e', '-s'):
                t = self._read(a[1])
                return Result('', 0 if t is not None and (a[0] != '-s' or t) else 1)
            return Result('', 1)
        if prog == 'pwd':
            return Result(CWD + '\n')
        if prog == 'date':
            return Result(self.w['now'] + '\n')
        if prog == 'sleep':
            return Result()
        if prog == 'ps':
            lines = ['PID OWNER CMD'] + [f"{p['pid']} {p.get('owner', 'other')} {p['cmd']}" for p in self.w['processes']]
            return Result('\n'.join(lines) + '\n')
        if prog == 'echo':
            return Result(' '.join(a for a in args if a not in ('-n', '-e')) + '\n')
        if prog == 'printf':
            return Result(_printf(args))
        if prog == 'ls':
            paths = [a for a in args if not a.startswith('-')] or ['.']
            out = []
            for p in paths:
                if self._read(p) is not None:
                    out.append(p)
                    continue
                names = self._list(p)
                if not names:
                    return _err(f"ls: cannot access '{p}': No such file or directory", 2)
                out.extend(names)
            return Result('\n'.join(out) + '\n')
        files = [a for a in args if not a.startswith('-')]
        if prog == 'cat':
            if not files:
                return Result(stdin or '')
            text = []
            for f in files:
                t = self._read(f)
                if t is None:
                    return _err(f'cat: {f}: No such file or directory')
                text.append(t)
            return Result(''.join(text))
        if prog in ('head', 'tail'):
            n, rest = 10, []
            it = iter(args)
            for a in it:
                if a == '-n':
                    n = int(next(it, '10'))
                elif re.fullmatch(r'-n?\d+', a):
                    n = int(a.lstrip('-n'))
                elif a.startswith('-n'):
                    n = int(a[2:])
                else:
                    rest.append(a)
            text = stdin or '' if not rest else self._read(rest[0])
            if text is None:
                return _err(f'{prog}: cannot open {rest[0]}')
            lines = text.splitlines(True)
            return Result(''.join(lines[:n] if prog == 'head' else lines[-n:] if n else []))
        if prog == 'sed':
            if '-n' not in args:
                raise _Usage('only `sed -n <range>p` is available')
            rng = [a for a in args if a != '-n']
            if not rng or not re.fullmatch(r"\d+(,\d+)?p", rng[0]):
                raise _Usage('only `sed -n <a>,<b>p` is available')
            a, _, b = rng[0][:-1].partition(',')
            text = stdin or '' if len(rng) < 2 else self._read(rng[1])
            if text is None:
                return _err(f'sed: can\'t read {rng[1]}')
            lines = text.splitlines(True)
            return Result(''.join(lines[int(a) - 1:int(b or a)]))
        if prog == 'wc':
            text = stdin or '' if not files else (self._read(files[0]) or '')
            if '-l' in args:
                return Result(f'{text.count(chr(10))}\n')
            return Result(f'{len(text.encode())}\n')
        if prog in ('sort', 'uniq', 'cut'):
            lines = (stdin or '').splitlines()
            if prog == 'sort':
                lines = sorted(lines)
            elif prog == 'uniq':
                lines = [l for i, l in enumerate(lines) if i == 0 or lines[i - 1] != l]
            return Result('\n'.join(lines) + ('\n' if lines else ''))
        if prog == 'grep':
            return self._grep(args, stdin)
        raise _Usage('unsupported')

    def _grep(self, args, stdin):
        flags, rest, pats = set(), [], []
        it = iter(args)
        for a in it:
            if a == '-e':
                pats.append(next(it, ''))
            elif a.startswith('--include='):
                flags.add(a)
            elif a.startswith('-') and len(a) > 1 and not pats and not rest:
                flags.update(a[1:])
            elif not pats:
                pats.append(a)
            else:
                rest.append(a)
        if not pats:
            raise _Usage('grep needs a pattern')
        pat = '|'.join(re.escape(p) if 'F' in flags else _bre(p) for p in pats)
        try:
            rx = re.compile(pat, re.I if 'i' in flags else 0)
        except re.error as e:
            return _err(f'grep: invalid pattern: {e}', 2)
        inc = [f.split('=', 1)[1] for f in flags if isinstance(f, str) and f.startswith('--include=')]
        sources = []
        if not rest:
            sources.append(('', stdin or ''))
        for r in rest:
            t = self._read(r)
            if t is not None:
                sources.append((r, t))
            elif 'r' in flags or 'R' in flags:
                pre = self._norm(r)
                pre = '' if pre in ('.', '') else pre + '/'
                for f in sorted(set(self.snapshot[1](pre)) | {k for k in self.overlay if k.startswith(pre)}):
                    if inc and not any(fnmatch.fnmatch(f.rsplit('/', 1)[-1], g) for g in inc):
                        continue
                    t = self._read(f)
                    if t is not None:
                        sources.append((f, t))
        out, hit = [], False
        multi = len(sources) > 1 or 'r' in flags
        for name, text in sources:
            n = 0
            for i, line in enumerate(text.splitlines(), 1):
                if bool(rx.search(line)) != ('v' in flags):
                    hit = True
                    n += 1
                    if 'l' in flags:
                        out.append(name)
                        break
                    if 'c' in flags:
                        continue
                    pre = (name + ':' if multi and name else '') + (f'{i}:' if 'n' in flags else '')
                    out.append(pre + line)
            if 'c' in flags:
                out.append((name + ':' if multi else '') + str(n))
            if len(out) > 400:
                out.append('... (fake grep: output cut at 400 lines)')
                break
        return Result('\n'.join(out) + ('\n' if out else ''), 0 if hit else 1)

    # ---- gh -----------------------------------------------------------
    def _gh(self, argv, stdin):
        args = _Args(argv[1:])
        top = args.pos(0)
        gh = self.w['github']
        if top == 'issue':
            return self._gh_issue(argv, args, stdin)
        if top == 'pr':
            return self._gh_pr(argv, args, stdin)
        if top == 'api':
            return self._gh_api(argv, args, stdin)
        if top == 'label' and args.pos(1) == 'list':
            self._event('read', argv)
            return Result(''.join(f'{l}\n' for l in gh['labels']
                                  if not args.get('--search') or args.get('--search') in l))
        if top == 'label' and args.pos(1) == 'create':
            self._event('write', argv)
            gh['labels'].append(args.pos(2))
            return Result()
        if top == 'repo' and args.pos(1) == 'view':
            self._event('read', argv)
            return Result(json.dumps({'nameWithOwner': gh['repo']}) + '\n')
        if top == 'run' and args.pos(1) in ('list', 'view'):
            self._event('read', argv)
            return Result(json.dumps(gh['runs'], indent=1) + '\n')
        if top == 'auth' and args.pos(1) == 'status':
            self._event('read', argv)
            return Result('Logged in to github.com as synthetic-bot\n')
        raise _Usage(f'gh {top}: not available in this eval')

    def _issue(self, n):
        n = str(n).lstrip('#')
        iss = self.w['github']['issues'].get(n)
        if iss is None:
            raise _NotFound(f'issue #{n} not found')
        return n, iss

    def _gh_issue(self, argv, args, stdin):
        sub = args.pos(1)
        gh = self.w['github']
        if sub == 'view':
            self._event('read', argv)
            try:
                n, iss = self._issue(args.pos(2))
            except _NotFound as e:
                return _err(f'GraphQL: Could not resolve to an issue ({e})')
            return Result(self._render_issue(n, iss, args))
        if sub == 'list':
            self._event('read', argv)
            rows = []
            for n, iss in sorted(gh['issues'].items(), key=lambda kv: int(kv[0])):
                state = args.get('--state') or 'open'
                if state != 'all' and iss.get('state', 'open') != state:
                    continue
                labels = args.all('--label')
                if any(l not in iss.get('labels', []) for l in labels):
                    continue
                rows.append((n, iss))
            if args.get('--json'):
                return Result(json.dumps([self._issue_json(n, i, args.get('--json')) for n, i in rows]) + '\n')
            return Result(''.join(f"{n}\t{i.get('state', 'open').upper()}\t{i['title']}\t{','.join(i.get('labels', []))}\n" for n, i in rows))
        if sub in ('comment', 'edit', 'close', 'reopen', 'create', 'delete', 'lock', 'transfer'):
            body = self._body(args, stdin)
            self._event('write', argv, body)
            if sub == 'create':
                n = str(max([int(k) for k in gh['issues']] + [4999]) + 1)
                gh['issues'][n] = {'title': args.get('--title') or '', 'body': body or '',
                                   'labels': args.all('--label'), 'state': 'open', 'comments': []}
                return Result(f"https://github.com/{gh['repo']}/issues/{n}\n")
            try:
                n, iss = self._issue(args.pos(2))
            except _NotFound as e:
                return _err(str(e))
            if sub == 'comment':
                return Result(self._add_comment(n, iss, body))
            if sub == 'edit':
                for l in _csv(args.all('--add-label')):
                    if l not in iss.setdefault('labels', []):
                        iss['labels'].append(l)
                for l in _csv(args.all('--remove-label')):
                    if l in iss.get('labels', []):
                        iss['labels'].remove(l)
                if args.get('--body') is not None or args.get('--body-file') is not None:
                    iss['body'] = body
                if args.get('--title'):
                    iss['title'] = args.get('--title')
                return Result(f"https://github.com/{gh['repo']}/issues/{n}\n")
            if sub == 'close':
                if body:
                    self._add_comment(n, iss, body)
                iss['state'] = 'closed'
                return Result(f'Closed issue #{n}\n')
            if sub == 'reopen':
                iss['state'] = 'open'
            return Result()
        raise _Usage(f'gh issue {sub}: not available in this eval')

    def _add_comment(self, n, subject, body):
        cid = self._next_comment
        self._next_comment += 1
        subject.setdefault('comments', []).append(
            {'id': cid, 'author': 'synthetic-bot', 'body': body or '', 'createdAt': self.w['now']})
        return f"https://github.com/{self.w['github']['repo']}/issues/{n}#issuecomment-{cid}\n"

    def _issue_json(self, n, iss, fields):
        full = {'number': int(n), 'title': iss.get('title', ''), 'body': iss.get('body', ''),
                'state': iss.get('state', 'open').upper(),
                'labels': [{'name': l} for l in iss.get('labels', [])],
                'comments': [{'id': c['id'], 'author': {'login': c.get('author', 'synthetic-bot')},
                              'body': c['body'], 'createdAt': c.get('createdAt', '')}
                             for c in iss.get('comments', [])],
                'milestone': {'title': iss['milestone']} if iss.get('milestone') else None,
                'parent': iss.get('parent'), 'blockedBy': {'nodes': [{'number': b, 'state': 'OPEN'} for b in iss.get('blockedBy', [])]},
                'headRefOid': iss.get('head'), 'headRefName': iss.get('head_ref'),
                'baseRefName': iss.get('base', 'main'), 'isDraft': iss.get('draft', False),
                'mergeable': iss.get('mergeable', 'MERGEABLE'), 'url': f"https://github.com/{self.w['github']['repo']}/issues/{n}",
                'reviews': iss.get('reviews', []), 'files': [{'path': p} for p in iss.get('files', [])],
                'additions': iss.get('additions', 0), 'deletions': iss.get('deletions', 0),
                'statusCheckRollup': [{'name': c['name'], 'status': c.get('status', 'COMPLETED').upper(),
                                       'conclusion': (c.get('conclusion') or '').upper()} for c in iss.get('checks', [])],
                'closingIssuesReferences': [{'number': x} for x in iss.get('closes', [])]}
        if not fields:
            return full
        return {f: full.get(f) for f in fields.split(',')}

    def _render_issue(self, n, iss, args):
        if args.get('--json'):
            return json.dumps(self._issue_json(n, iss, args.get('--json')), indent=1) + '\n'
        out = [f"title:\t{iss.get('title', '')}", f"state:\t{iss.get('state', 'open').upper()}",
               f"labels:\t{', '.join(iss.get('labels', []))}", f'number:\t{n}']
        if iss.get('milestone'):
            out.append(f"milestone:\t{iss['milestone']}")
        if iss.get('head'):
            out.append(f"head:\t{iss.get('head_ref', '')} @ {iss['head']}")
        out += ['--', iss.get('body', '')]
        if '--comments' in args.flags or args.get('-c') is not None:
            for c in iss.get('comments', []):
                out += ['--', f"author:\t{c.get('author', 'synthetic-bot')}\tid:\t{c['id']}\tcreated:\t{c.get('createdAt', '')}", c['body']]
        return '\n'.join(out) + '\n'

    def _pull(self, n):
        n = str(n).lstrip('#')
        pr = self.w['github']['pulls'].get(n)
        if pr is None:
            raise _NotFound(f'pull request #{n} not found')
        return n, pr

    def _gh_pr(self, argv, args, stdin):
        sub = args.pos(1)
        gh = self.w['github']
        if sub in ('view', 'checks', 'diff'):
            self._event('read', argv)
            try:
                n, pr = self._pull(args.pos(2) or self._pr_for_branch())
            except _NotFound as e:
                return _err(str(e))
            if sub == 'view':
                return Result(self._render_issue(n, pr, args))
            if sub == 'diff':
                return Result(pr.get('diff', '') if '--name-only' not in args.flags else ''.join(f + '\n' for f in pr.get('files', [])))
            rows = pr.get('checks', [])
            if args.get('--json'):
                return Result(json.dumps([{'name': c['name'], 'state': _check_state(c), 'link': ''} for c in rows]) + '\n')
            out = ''.join(f"{c['name']}\t{_check_state(c).lower()}\t{c.get('elapsed', '1m')}\t\n" for c in rows)
            states = {_check_state(c) for c in rows}
            code = 1 if states - {'SUCCESS', 'SKIPPED', 'PENDING'} else 8 if 'PENDING' in states else 0
            return Result(out or 'no checks reported\n', code)
        if sub == 'list':
            self._event('read', argv)
            rows = [(n, p) for n, p in sorted(gh['pulls'].items(), key=lambda kv: int(kv[0]))
                    if (args.get('--head') in (None, p.get('head_ref')))
                    and ((args.get('--state') or 'open') in ('all', p.get('state', 'open')))]
            if args.get('--json'):
                return Result(json.dumps([self._issue_json(n, p, args.get('--json')) for n, p in rows]) + '\n')
            return Result(''.join(f"{n}\t{p['title']}\t{p.get('head_ref', '')}\t{p.get('state', 'open').upper()}\n" for n, p in rows))
        if sub in ('comment', 'create', 'edit', 'merge', 'review', 'ready', 'close', 'reopen'):
            body = self._body(args, stdin)
            self._event('write', argv, body)
            if sub == 'create':
                n = str(max([int(k) for k in gh['pulls']] + [int(k) for k in gh['issues']] + [4999]) + 1)
                gh['pulls'][n] = {'title': args.get('--title') or '', 'body': body or '',
                                  'head': self.w['git']['head'], 'head_ref': self.w['git']['branch'],
                                  'state': 'open', 'draft': '--draft' in args.flags, 'comments': [],
                                  'labels': args.all('--label'), 'checks': []}
                return Result(f"https://github.com/{gh['repo']}/pull/{n}\n")
            try:
                n, pr = self._pull(args.pos(2) or self._pr_for_branch())
            except _NotFound as e:
                return _err(str(e))
            if sub == 'comment':
                return Result(self._add_comment(n, pr, body))
            if sub == 'merge':
                want = args.get('--match-head-commit')
                if want and want != pr.get('head'):
                    return _err('Head branch was modified. Review and try the merge again.')
                pr['state'] = 'merged'
                return Result(f'Merged pull request #{n}\n')
            if sub == 'edit':
                for l in _csv(args.all('--add-label')):
                    pr.setdefault('labels', []).append(l)
                if body is not None:
                    pr['body'] = body
                if args.get('--title'):
                    pr['title'] = args.get('--title')
            if sub == 'close':
                pr['state'] = 'closed'
            if sub == 'ready':
                pr['draft'] = False
            return Result()
        raise _Usage(f'gh pr {sub}: not available in this eval')

    def _pr_for_branch(self):
        for n, p in self.w['github']['pulls'].items():
            if p.get('head_ref') == self.w['git']['branch']:
                return n
        raise _NotFound('no pull request found for the current branch')

    def _bind(self, path):
        """The path with `{owner}/{repo}` expanded; None for a `repos/` path of another repository."""
        repo = self.w['github']['repo']
        p = re.sub(r'^repos/\{owner\}/\{repo\}(?=/|$)', f'repos/{repo}', path)
        if p.startswith('repos/') and not (p + '/').startswith(f'repos/{repo}/'):
            return None
        return p

    def _gh_api(self, argv, args, stdin=None):
        path = (args.pos(1) or '').lstrip('/')
        method = (args.get('--method') or args.get('-X') or '').upper()
        fields = args.all('-f') + args.all('-F') + args.all('--field') + args.all('--raw-field')
        if path == 'graphql':
            given = dict(x.split('=', 1) for x in fields if '=' in x)
            query = given.pop('query', '')
            if re.search(r'\b(mutation|subscription)\b', query):
                self._event('write', argv, query)
                return _err('fake gh: GraphQL mutations are not available in this eval')
            self._event('read', argv)
            if 'operationName' in given or _graphql_definitions(query) != 1:
                return _err('fake gh: only one GraphQL query per request, with no operationName, is modelled here')
            tokens = _graphql_tokens(query)
            repo = self.w['github']['repo']
            for g in self.w.get('graphql', []):
                want = {k: str(v) for k, v in g['variables'].items()}
                if ('owner' in want or 'name' in want) and f"{want.get('owner')}/{want.get('name')}" != repo:
                    continue  # an answer is only ever about this repository
                if tokens is not None and tokens == _graphql_tokens(g['document']) and given == want:
                    return Result(json.dumps(g['out']) + '\n')
            return _err('fake gh: this GraphQL query has no synthetic answer in this case')
        if not method:
            method = 'POST' if fields or args.get('--input') else 'GET'
        if method != 'GET':
            body = next((f.split('=', 1)[1] for f in fields if f.startswith('body=')), None)
            if body and body.startswith('@'):
                body = self._read(body[1:]) or ''
            if body is None and args.get('--input'):
                raw = (stdin or '') if args.get('--input') == '-' else (self._read(args.get('--input')) or '')
                try:
                    body = json.loads(raw).get('body')
                except (ValueError, AttributeError):
                    body = raw
            self._event('write', argv, body)
            bound = self._bind(path)
            if bound is None:
                return _err(f'gh: Not Found (HTTP 404): {path} is not this repository')
            m = re.fullmatch(r'repos/[^/]+/[^/]+/issues/(\d+)/comments', bound)
            if m and method == 'POST':
                subj = self.w['github']['issues'].get(m.group(1)) or self.w['github']['pulls'].get(m.group(1))
                if subj is not None:
                    url = self._add_comment(m.group(1), subj, body)
                    return Result(json.dumps({'id': int(url.rsplit('-', 1)[1]), 'html_url': url.strip()}) + '\n')
            m = re.fullmatch(r'repos/[^/]+/[^/]+/issues/comments/(\d+)', bound)
            if m and method == 'PATCH':
                for subj in list(self.w['github']['issues'].values()) + list(self.w['github']['pulls'].values()):
                    for c in subj.get('comments', []):
                        if str(c['id']) == m.group(1):
                            c['body'] = body or ''
                            return Result(json.dumps({'id': c['id']}) + '\n')
            return _err(f'fake gh: this API write ({method} {path}) is not available in this eval')
        self._event('read', argv)
        p = self._bind(path)
        if p is None:
            return _err(f'gh: Not Found (HTTP 404): {path} is not this repository')
        m = re.fullmatch(r'repos/[^/]+/[^/]+/(issues|pulls)/(\d+)/comments', p)
        if m:
            subj = self.w['github']['issues'].get(m.group(2)) or self.w['github']['pulls'].get(m.group(2)) or {}
            return Result(json.dumps([{'id': c['id'], 'body': c['body'], 'user': {'login': c.get('author', 'synthetic-bot')},
                                       'created_at': c.get('createdAt', ''), 'updated_at': c.get('createdAt', '')}
                                      for c in subj.get('comments', [])]) + '\n')
        m = re.fullmatch(r'repos/[^/]+/[^/]+/issues/comments/(\d+)', p)
        if m:
            for subj in list(self.w['github']['issues'].values()) + list(self.w['github']['pulls'].values()):
                for c in subj.get('comments', []):
                    if str(c['id']) == m.group(1):
                        return Result(json.dumps({'id': c['id'], 'body': c['body']}) + '\n')
            return _err('gh: Not Found (HTTP 404)')
        m = re.fullmatch(r'repos/[^/]+/[^/]+/(pulls|issues)/(\d+)', p)
        if m:
            subj = self.w['github'][m.group(1)].get(m.group(2))
            if subj is None:
                return _err('gh: Not Found (HTTP 404)')
            return Result(json.dumps({'number': int(m.group(2)), 'title': subj.get('title', ''), 'body': subj.get('body', ''),
                                      'state': subj.get('state', 'open'), 'labels': [{'name': l} for l in subj.get('labels', [])],
                                      'head': {'sha': subj.get('head'), 'ref': subj.get('head_ref')}}) + '\n')
        if re.fullmatch(r'repos/[^/]+/[^/]+/commits/[0-9a-f]+/check-runs', p):
            sha = p.split('/')[4]
            runs = [c for pr in self.w['github']['pulls'].values() if pr.get('head') == sha for c in pr.get('checks', [])]
            return Result(json.dumps({'check_runs': [{'name': c['name'], 'status': c.get('status', 'completed'),
                                                      'conclusion': c.get('conclusion')} for c in runs]}) + '\n')
        return _err(f'gh: Not Found (HTTP 404): {path}')

    def _body(self, args, stdin):
        if args.get('--body') is not None:
            return args.get('--body')
        if args.get('-b') is not None:
            return args.get('-b')
        f = args.get('--body-file') or args.get('-F')
        if f == '-':
            return stdin or ''
        if f:
            t = self._read(f)
            return t if t is not None else ''
        if args.get('--comment') is not None:
            return args.get('--comment')
        return None

    # ---- room-cli -----------------------------------------------------
    def _room(self, argv, stdin):
        args = _Args(argv[1:])
        top, sub = args.pos(0), args.pos(1)
        cr = self.w['cloudroom']
        if top == 'thread' and sub in ('list', 'output', 'log', 'show'):
            self._event('read', argv)
            if sub == 'list':
                rows = [t for t in cr['threads'] if '--include-archived' in args.flags or not t.get('archived')]
                return Result(json.dumps([{k: t.get(k) for k in ('id', 'title', 'provider', 'model', 'status', 'archived')} for t in rows], indent=1) + '\n')
            t = self._thread(args.pos(2))
            if t is None:
                return _err('thread not found')
            return Result((t.get('output', '') if sub != 'show' else json.dumps(t)) + '\n')
        if top == 'thread' and sub in ('spawn', 'archive', 'stop', 'tell', 'update', 'fork', 'move'):
            body = args.get('--prompt')
            if body is None and args.get('--prompt-file'):
                body = self._read(args.get('--prompt-file')) or ''
            if sub == 'tell':
                rest = argv[argv.index('--') + 1:] if '--' in argv else args.positional[3:]
                body = ' '.join(rest) or stdin
            self._event('write', argv, body)
            if sub in ('spawn', 'fork'):
                tid = f'thr_synthnew{self._next_thread}'
                self._next_thread += 1
                cr['threads'].append({'id': tid, 'title': args.get('--title') or '', 'provider': args.get('--provider'),
                                      'model': args.get('--model'), 'status': 'running', 'prompt': body})
                return Result(json.dumps({'id': tid, 'harness': args.get('--provider')}) + '\n')
            t = self._thread(args.pos(2))
            if sub == 'archive' and t is not None:
                t['archived'] = True
            if sub == 'stop' and t is not None:
                t['status'] = 'stopped'
            return Result(json.dumps({'ok': True}) + '\n')
        if top in ('loop', 'automation') and sub == 'list':
            self._event('read', argv)
            return Result(json.dumps(cr['loops']) + '\n')
        if top in ('loop', 'automation'):
            self._event('write', argv)
            return Result(json.dumps({'ok': True}) + '\n')
        if top == 'usage' or (top == 'files' and sub == 'wait'):
            self._event('read', argv)
            return Result(json.dumps(cr.get('usage', {'credits_left': 1000})) + '\n' if top == 'usage' else 'Project files are ready.\n')
        if top in ('secret', 'mac', 'gpu', 'computer-use', 'preview', 'feedback'):
            self._event('write', argv)
            return _err(f'room-cli {top}: not available in this eval')
        raise _Usage(f'room-cli {top} {sub or ""}: not available in this eval')

    def _thread(self, tid):
        return next((t for t in self.w['cloudroom']['threads'] if t['id'] == tid), None)

    # ---- git ----------------------------------------------------------
    def _git(self, argv):
        args = _Args([a for a in argv[1:] if a not in ('-C',)])
        sub = args.pos(0)
        g = self.w['git']
        if sub in ('push',):
            self._event('write', argv)
            return Result('To github.com:example/project.git\n')
        if sub in ('add', 'commit', 'config', 'checkout', 'switch', 'merge', 'stash', 'restore', 'tag', 'rebase', 'reset', 'cherry-pick', 'revert'):
            if sub == 'reset' and '--hard' in args.flags or sub == 'tag':
                self._event('write', argv)
            else:
                self._event('local', argv)
            if sub == 'merge' and g['conflict']:
                return _err('CONFLICT (content): Merge conflict', 1)
            return Result()
        self._event('read', argv)
        if sub == 'rev-parse':
            ref = args.pos(1) or ''
            if ref == '--show-toplevel':
                return Result(CWD + '\n')
            if ref in ('HEAD', '@'):
                return Result(g['head'] + '\n')
            if ref in ('origin/main', 'main'):
                return Result(g['origin_main'] + '\n')
            if ref.startswith('HEAD:'):
                t = self._read(ref[5:])
                return Result(_blob_id(t) + '\n') if t is not None else _err(f"fatal: path '{ref[5:]}' does not exist in 'HEAD'", 128)
            if ref == '--abbrev-ref':
                return Result(g['branch'] + '\n')
            return _err(f'fatal: ambiguous argument {ref!r}', 128)
        if sub == 'branch':
            return Result(g['branch'] + '\n')
        if sub == 'status':
            return Result(g['status'] or ('' if '--short' in args.flags or '-s' in args.flags else f"On branch {g['branch']}\nnothing to commit, working tree clean\n"))
        if sub == 'log':
            return Result(f"{g['head']} synthetic head commit\n")
        if sub == 'diff':
            return Result(''.join(p + '\n' for p in g['diff_names']))
        if sub == 'fetch' or sub == 'remote':
            return Result()
        if sub == 'merge-tree':
            return Result('CONFLICT (content)\n', 1) if g['conflict'] else Result('c' * 40 + '\n')
        if sub == 'show':
            ref = args.pos(1) or ''
            if ':' in ref:
                t = self._read(ref.split(':', 1)[1])
                return Result(t) if t is not None else _err('fatal: path does not exist', 128)
            return Result(f"commit {g['head']}\n")
        if sub == 'ls-files':
            return Result('\n'.join(self.snapshot[1](args.pos(1) or '')) + '\n')
        raise _Usage(f'git {sub}: not available in this eval')

    def _kill(self, argv):
        pids = [a for a in argv[1:] if not a.startswith('-')]
        self._event('write', argv)
        procs = self.w['processes']
        for p in pids:
            match = [x for x in procs if str(x['pid']) == p]
            if not match:
                return _err(f'kill: ({p}) - No such process')
            procs.remove(match[0])
        return Result()


class _Escaped(Exception):
    pass


class _Usage(Exception):
    pass


class _NotFound(Exception):
    pass


class _Args:
    """Positional arguments and flags, gh style (`--flag value`, `--flag=value`)."""
    BOOL = {'--comments', '--include-archived', '--draft', '--merge', '--squash', '--rebase',
            '--paginate', '--short', '-s', '--hard', '--name-only', '--all', '--json-all',
            '--shared-sandbox', '--top-level', '--web', '--admin', '--auto', '--yes', '--force',
            '--no-verify', '--force-with-lease', '--delete-branch', '--quiet', '-q', '--verbose',
            '--approve', '--request-changes', '--parent-self', '--self', '--write-tree', '-c',
            '--fill', '--stat', '--oneline', '--no-pager', '--stdin', '-u', '--set-upstream',
            '--no-edit', '--abort', '--ff-only', '--no-ff', '--webhook', '--new-thread'}

    def __init__(self, argv):
        self.positional, self.flags, self.values = [], [], []
        i = 0
        while i < len(argv):
            a = argv[i]
            if a == '--':
                self.positional += argv[i:]
                break
            if a.startswith('-') and len(a) > 1 and not re.fullmatch(r'-\d+', a):
                if '=' in a and a.startswith('--'):
                    k, v = a.split('=', 1)
                    self.flags.append(k)
                    self.values.append((k, v))
                elif a in self.BOOL or i + 1 >= len(argv):
                    self.flags.append(a)
                else:
                    self.flags.append(a)
                    self.values.append((a, argv[i + 1]))
                    i += 1
            else:
                self.positional.append(a)
            i += 1

    def pos(self, k):
        return self.positional[k] if k < len(self.positional) else None

    def get(self, k):
        return next((v for f, v in self.values if f == k), None)

    def all(self, k):
        return [v for f, v in self.values if f == k]


def _csv(values):
    return [x.strip() for v in values for x in v.split(',') if x.strip()]


def _check_state(c):
    if c.get('status', 'completed').lower() != 'completed':
        return 'PENDING'
    return (c.get('conclusion') or 'pending').upper()





def _blob_id(text):
    import hashlib
    data = text.encode()
    return hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest()


def _bre(p):
    # grep's basic syntax: \| is alternation, | is literal.
    return p.replace('\\|', '\0').replace('|', '\\|').replace('\0', '|').replace('\\(', '(').replace('\\)', ')')


def _extract_heredocs(command):
    """Replace each heredoc with a NUL-prefixed placeholder; return (text, bodies)."""
    m = re.compile(r'''"\$\(cat <<-?\s*(['"]?)(\w+)\1\n(.*?)\n\2\n\)"''', re.S)
    bodies = []

    def quote(mm):
        bodies.append(mm.group(3) + '\n')
        return f'@@HEREDOC{len(bodies) - 1}@@'
    command = m.sub(quote, command)
    lines = command.split('\n')
    out, i = [], 0
    hd = re.compile(r'''<<-?\s*(['"]?)(\w+)\1''')
    while i < len(lines):
        line = lines[i]
        mm = hd.search(line)
        if not mm:
            out.append(line)
            i += 1
            continue
        tag, j, body = mm.group(2), i + 1, []
        while j < len(lines) and lines[j].strip() != tag:
            body.append(lines[j])
            j += 1
        if j >= len(lines):
            raise ValueError(f'heredoc {tag} has no end')
        bodies.append('\n'.join(body) + '\n')
        out.append(line[:mm.start()] + f'< @@STDIN{len(bodies) - 1}@@' + line[mm.end():])
        i = j + 1
    text = '\n'.join(out)
    return text, bodies


def _graphql_tokens(doc):
    """A GraphQL document's lexical tokens, dropping only what GraphQL ignores (whitespace, commas,
    comments). Names, punctuation, numbers and quoted strings stay exactly, so argument values,
    string contents and nesting all count. None for text that is not GraphQL."""
    out, i, n = [], 0, len(doc)
    while i < n:
        c = doc[i]
        if c in ' \t\r\n,\ufeff':
            i += 1
        elif c == '#':
            while i < n and doc[i] != '\n':
                i += 1
        elif doc.startswith('"""', i):
            j = doc.find('"""', i + 3)
            if j < 0:
                return None
            out.append(doc[i:j + 3])
            i = j + 3
        elif c == '"':
            j = i + 1
            while j < n and doc[j] != '"':
                j += 2 if doc[j] == '\\' else 1
            if j >= n:
                return None
            out.append(doc[i:j + 1])
            i = j + 1
        elif doc.startswith('...', i):
            out.append('...')
            i += 3
        elif c in '!$&()::=@[]{}|':
            out.append(c)
            i += 1
        else:
            m = re.match(r'[_A-Za-z][_0-9A-Za-z]*|-?\d+(\.\d+)?([eE][+-]?\d+)?', doc[i:])
            if not m:
                return None
            out.append(m.group(0))
            i += m.end()
    return out


def _graphql_definitions(query):
    """How many top-level definitions (operations or fragments) a GraphQL document holds."""
    depth, count, q = 0, 0, False
    for i, c in enumerate(query):
        if c == '"' and query[i - 1:i] != '\\':
            q = not q
        elif q:
            continue
        elif c == '{':
            count += depth == 0
            depth += 1
        elif c == '}':
            depth -= 1
    return count


def _executable_substitution(text):
    """A backtick outside single quotes, or `<(` / `>(` outside any quotes. A backslash outside
    single quotes escapes the next character: it never opens or closes a quote, and an escaped
    backtick is literal."""
    q, i, n = None, 0, len(text)
    while i < n:
        c = text[i]
        if q == "'":
            if c == "'":
                q = None
        elif c == '\\':
            i += 2
            continue
        elif q == '"':
            if c == '"':
                q = None
            elif c == '`':
                return True
        elif c in '\'"':
            q = c
        elif c == '`' or (c in '<>' and text[i + 1:i + 2] == '('):
            return True
        i += 1
    return False


def _printf(args):
    """Shell printf: %s %d %i %b %%, \\n \\t \\\\; the format repeats while arguments remain."""
    if not args:
        return ''
    fmt, rest, out = args[0], list(args[1:]), []
    esc = {'n': '\n', 't': '\t', '\\': '\\', 'r': '\r'}
    while True:
        i, used = 0, False
        while i < len(fmt):
            c = fmt[i]
            if c == '\\' and i + 1 < len(fmt):
                out.append(esc.get(fmt[i + 1], '\\' + fmt[i + 1]))
                i += 2
            elif c == '%' and i + 1 < len(fmt):
                d = fmt[i + 1]
                if d == '%':
                    out.append('%')
                else:
                    used = True
                    v = rest.pop(0) if rest else ''
                    if d in 'di':
                        try:
                            v = str(int(v or 0))
                        except ValueError:
                            v = '0'
                    out.append(v)
                i += 2
            else:
                out.append(c)
                i += 1
        if not rest or not used:
            return ''.join(out)


def _tokens(text):
    lex = shlex.shlex(text, posix=True, punctuation_chars=';&|<>')
    lex.whitespace = ' \t\r\n'
    lex.whitespace_split = True
    return list(lex)


def _split_raw(text):
    """Statements split at unquoted ; newline && || | &, as (operator before it, text)."""
    stmts, cur, pending, q, depth, i, n = [], [], None, None, 0, 0, len(text)

    def push(op):
        nonlocal cur, pending
        s = ''.join(cur)
        if s.strip():
            stmts.append((pending, s))
            pending = op
        elif op != ';' or pending not in ('&&', '||', '|'):
            pending = op if stmts else None
        cur = []
    while i < n:
        c = text[i]
        if q:
            if c == '\\' and q == '"' and i + 1 < n:
                cur.append(text[i:i + 2])
                i += 2
                continue
            if c == q:
                q = None
            cur.append(c)
            i += 1
            continue
        if c in '\'"':
            q = c
        elif c == '\\' and i + 1 < n:
            if text[i + 1] != '\n':
                cur.append(text[i:i + 2])
            i += 2
            continue
        elif text.startswith('$(', i):
            depth += 1
            cur.append('$(')
            i += 2
            continue
        elif depth:
            depth += c == '('
            depth -= c == ')'
        elif c == '#' and (not cur or cur[-1] in ' \t\n'):
            while i < n and text[i] != '\n':
                i += 1
            continue
        elif text.startswith('&&', i) or text.startswith('||', i):
            push(text[i:i + 2])
            i += 2
            continue
        elif c in ';\n':
            push(';')
            i += 1
            continue
        elif c == '|':
            push('|')
            i += 1
            continue
        elif c == '&' and not (cur and cur[-1] == '>') and not text.startswith('&>', i):
            push(';')
            i += 1
            continue
        cur.append(c)
        i += 1
    if q or depth:
        raise ValueError('unclosed quote or $(')
    push(';')
    return stmts


def _redirects(seg, heredocs):
    argv, out, append, stdin = [], None, False, None
    i = 0
    while i < len(seg):
        t = seg[i]
        if t in ('>', '>>') and i + 1 < len(seg):
            if argv and argv[-1] in ('1', '2') and seg[i - 1] == argv[-1]:
                fd = argv.pop()
            else:
                fd = '1'
            target = seg[i + 1]
            if fd == '1':
                out, append = target, t == '>>'
            i += 2
            continue
        if t == '>&' and i + 1 < len(seg):
            if argv and argv[-1] in ('1', '2'):
                argv.pop()
            i += 2
            continue
        if t == '<' and i + 1 < len(seg):
            target = seg[i + 1]
            m = re.fullmatch(r'@@STDIN(\d+)@@', target)
            stdin = '\0' + heredocs[int(m.group(1))] if m else target
            i += 2
            continue
        argv.append(re.sub(r'@@HEREDOC(\d+)@@', lambda m: heredocs[int(m.group(1))].rstrip('\n'), t))
        i += 1
    return argv, out, append, stdin


def _paths(argv):
    """Arguments that look like filesystem paths, for the boundary check."""
    out = []
    for a in argv[1:]:
        v = a.split('=', 1)[1] if a.startswith('--') and '=' in a else a
        if v.startswith(('/', '~', '../')) or '/../' in v or v == '..':
            if re.fullmatch(r'/?repos/.*', v) or v.startswith('/repos/'):
                continue
            out.append(v)
    return out
