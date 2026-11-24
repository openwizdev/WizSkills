#!/usr/bin/env python3
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import signal
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO = re.compile(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+')
NUMBER = re.compile(r'[1-9][0-9]{0,8}')
WORD = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,119}')
START = re.compile(r'start #([1-9][0-9]*): ')
CHECKED = re.compile(r'check start #([1-9][0-9]*): thread run:\1, branch ([^ ,;]+)')
REVIEW = re.compile(r'review #([1-9][0-9]*) for #([1-9][0-9]*) at ([0-9a-f]{40}): (?:first review|a fresh reviewer)'
                    r'(?: \(retry after .*\))?')
MERGE = re.compile(r'merge #([1-9][0-9]*) for #([1-9][0-9]*) at ([0-9a-f]{40}): APPROVE and CI green')
LEFT = re.compile(r'archive #[1-9][0-9]*: ')
FINISHED = re.compile(r'(?:spec done|close spec) #([1-9][0-9]*): ')
ASSIGNED = ('launch-fleet: review started ', 'launch-fleet: re-check sent ')
BUILT = ('launch-fleet: starting', 'launch-fleet: started', 'launch-fleet: start checked, branch ')
DRIVERS = {'Claude Code': 'claude', 'Codex': 'codex'}
OTHER = {'claude': 'codex', 'codex': 'claude'}
PROVIDERS = {'claude-code': 'claude', 'codex': 'codex'}
REVIEWS = {'claude': 'review_of_claude_built', 'codex': 'review_of_gpt_built'}
FLAGS = re.compile(r'--provider (\S+) --model (\S+) --reasoning-level \S+')
PR = re.compile(r'https://github\.com/[^/]+/[^/]+/pull/([1-9][0-9]*)')
STATE = Path.home() / '.local/state/openwiz-heartbeat'
TIMEOUT = 1000


def sibling(name):
    spec = importlib.util.spec_from_file_location('session_' + name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


post, status = sibling('post'), sibling('status')


class Refused(Exception):
    pass


class Unreadable(Exception):
    pass


class NeedsYou(Exception):
    pass


class Done(Exception):
    pass


def run(argv, env=None):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL, env=env)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Unreadable('%s did not run (%s)' % (Path(argv[2] if argv[0] == sys.executable else argv[0]).name,
                                                  type(e).__name__))
    return r


def script(name, *args):
    return run([sys.executable, '-I', str(HERE / name), *map(str, args)])


@contextmanager
def lock(repo, spec):
    key = hashlib.sha256(('%s#%s' % (repo.lower(), spec)).encode()).hexdigest()[:20]
    folder = STATE / ('openwiz-heartbeat-' + key)
    for _ in range(10):
        made = False
        try:
            STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
            folder.mkdir(mode=0o700)
            made = True
        except FileExistsError:
            pass
        except OSError as e:
            raise Unreadable("can't make the lock folder (%s)" % type(e).__name__)
        try:
            fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
        except FileNotFoundError:
            continue
        except OSError as e:
            raise Unreadable("can't open the lock folder (%s)" % type(e).__name__)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Refused('a session or heartbeat tick already runs spec #%s' % spec) from None
            try:
                current = os.path.samestat(os.fstat(fd), folder.stat())
            except FileNotFoundError:
                current = False
            if not current:
                continue
            try:
                yield
            finally:
                if made:
                    try:
                        folder.rmdir()
                    except OSError:
                        pass
            return
        finally:
            os.close(fd)
    raise Refused('the lock folder of spec #%s kept changing' % spec)


def stamp(text):
    try:
        return datetime.strptime(text or '', '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        raise Unreadable('a record has no readable time')


def first(comment):
    return comment['body'].split('\n')[0]


class Session:
    def __init__(self, args, command):
        self.a, self.command = args, command
        self.repo, self.spec = args.repo, args.spec
        self.live = {}
        self.prs = {}
        self.acted = set()
        self.pending = []
        self.tick_no = 0
        self.authors = None


    def thread(self, number):
        if self.authors is None:
            try:
                self.authors = post.authors(self.repo)
            except post.Stop as e:
                raise Unreadable(str(e))
        items = post.thread(self.repo, number)
        if items is None:
            raise Unreadable('#%s could not be read' % number)
        return [c for c in items if post.ours(c, self.authors) and isinstance(c.get('body'), str)]

    def due(self):
        r = run(['sh', str(HERE / 'fleet.sh'), 'spec', self.spec])
        if r.returncode:
            raise Unreadable('fleet.sh spec %s failed (exit %d)' % (self.spec, r.returncode))
        return [line for line in r.stdout.splitlines() if line.strip()]

    def tickets(self):
        pages = post.read_json('api', '--paginate', '--slurp',
                               'repos/%s/issues/%s/sub_issues?per_page=100' % (self.repo, self.spec))
        if not isinstance(pages, list) or not all(isinstance(p, list) for p in pages):
            raise Unreadable("spec #%s's tickets could not be read" % self.spec)
        items = [i for p in pages for i in p]
        if not all(isinstance(i, dict) and isinstance(i.get('number'), int) for i in items):
            raise Unreadable("spec #%s's tickets could not be read" % self.spec)
        return items

    def closed(self):
        items = self.tickets()
        return bool(items) and all(i.get('state') == 'closed' for i in items)

    def notes(self, agent, number, since):
        found = [f for f in (status.parse(c['body']) for c in self.thread(number)) if f and f['agent'] == agent]
        return [f for f in found if stamp(f['time']) >= since]

    def ended(self, agent, target, since, number):
        notes = self.notes(agent, number, since)
        if not notes or notes[-1]['state'] == 'working':
            return False
        found = PR.fullmatch(notes[-1].get('pr', ''))
        if found:
            self.prs[found[1]] = number
        return True

    def restore(self):
        for item in self.tickets():
            if item.get('state') == 'closed':
                continue
            n = str(item['number'])
            comments = self.thread(n)
            starts = [c for c in comments if first(c).startswith(BUILT)]
            for f in (status.parse(c['body']) for c in comments):
                found = f and f['agent'] == 'builder' and PR.fullmatch(f.get('pr', ''))
                if found:
                    self.prs[found[1]] = n
            if starts:
                since = stamp(max(starts, key=lambda c: c['id']).get('created_at'))
                notes = self.notes('builder', n, since)
                if not notes or notes[-1]['state'] == 'working':
                    self.live[('builder', n)] = (since, n)
        for p, n in sorted(self.prs.items()):
            comments = self.thread(p)
            assigned = [c for c in comments if first(c).startswith(ASSIGNED)]
            if assigned:
                since = stamp(max(assigned, key=lambda c: c['id']).get('created_at'))
                notes = self.notes('reviewer', n, since)
                if not notes or notes[-1]['state'] == 'working':
                    self.live[('reviewer', p)] = (since, n)

    def state(self, p):
        text = post.gh('pr', 'view', p, '--repo', self.repo, '--json', 'state,statusCheckRollup')
        try:
            pr = json.loads(text or '')
        except ValueError:
            raise Unreadable('pull request #%s could not be read' % p)
        if not isinstance(pr, dict):
            raise Unreadable('pull request #%s could not be read' % p)
        self.rollup = pr.get('statusCheckRollup') or []
        return pr.get('state')

    def checks_running(self):
        for p in sorted(self.prs):
            if self.state(p) != 'OPEN':
                continue
            if not self.rollup or any(c.get('status', 'COMPLETED') != 'COMPLETED'
                                      or c.get('state') in ('PENDING', 'EXPECTED') for c in self.rollup):
                return True
        return False

    def detached(self, label, name, *args):
        out, err = tempfile.TemporaryFile('w+'), tempfile.TemporaryFile('w+')
        try:
            child = subprocess.Popen([sys.executable, '-I', str(HERE / name), *map(str, args)], stdin=subprocess.DEVNULL,
                                     stdout=out, stderr=err, text=True, start_new_session=True)
        except OSError as e:
            raise Unreadable('%s did not run (%s)' % (name, type(e).__name__))
        self.pending.append(label)
        return label, child, out, err

    def answers(self, jobs):
        end = time.monotonic() + TIMEOUT
        while any(child.poll() is None for _, child, _, _ in jobs):
            if time.monotonic() > end:
                raise Unreadable('%s did not answer in %d seconds' % (', '.join(self.pending), TIMEOUT))
            time.sleep(0.05)
        results = []
        for label, child, out, err in jobs:
            out.seek(0)
            err.seek(0)
            results.append(SimpleNamespace(returncode=child.returncode, stdout=out.read(), stderr=err.read()))
            self.pending.remove(label)
        return results

    def claim(self, number, body, withdrawn):
        try:
            made = post.comment(self.repo, int(number), body)
        except post.Stop as e:
            raise NeedsYou('the claim on #%s was not written: %s' % (number, e))
        claim = made.split()[-1]
        r = run(['sh', str(HERE / 'fleet.sh'), 'claim', number, claim])
        if r.stdout.strip() != 'go #%s' % number:
            self.edit(claim, withdrawn)
            return None
        return claim

    def edit(self, claim, body):
        try:
            post.edit(self.repo, int(claim), body)
        except post.Stop as e:
            raise NeedsYou('comment %s was not edited to "%s": %s' % (claim, body.split('\n')[0], e))

    def refusal(self, claim, kind, number, r):
        line = r.stdout.strip().split('\n')[0] or r.stderr.strip() or 'host.py exit %d' % r.returncode
        if r.returncode == 1 and line.startswith('stopped (driver start failed)'):
            self.edit(claim, kind % 'driver start failed')
        elif r.returncode == 1 and line.startswith('refused:'):
            self.edit(claim, kind % 'the host refused it')
        return line if line.startswith('stopped') else '#%s did not start: %s' % (number, line)


    def builders(self):
        return sum(agent == 'builder' for agent, _ in self.live)

    def start(self, numbers):
        started, stops = [], []
        for batch in (numbers[:1], numbers[1:]):
            since = int(time.time())
            claims = [(n, c) for n in batch for c in [self.claim(n, 'launch-fleet: starting',
                                                                 'launch-fleet: start withdrawn')] if c]
            jobs = [self.detached("#%s's start" % n, 'host.py', 'start', self.repo, n, self.a.harness, self.a.model)
                    for n, _ in claims]
            for (n, claim), r in zip(claims, self.answers(jobs)):
                if r.returncode:
                    stops.append(self.refusal(claim, 'launch-fleet: start refused: %s', n, r))
                    continue
                self.live[('builder', n)] = (since, n)
                self.edit(claim, 'launch-fleet: started')
                started.append(n)
            if stops:
                raise NeedsYou('; '.join(stops))
        return started

    def checked(self, n, branch):
        records = [c for c in self.thread(n) if c['body'].split('\n')[0] == 'launch-fleet: started']
        if not records:
            raise NeedsYou('#%s has a branch but no started record to check' % n)
        self.edit(max(records, key=lambda c: c['id'])['id'], 'launch-fleet: start checked, branch %s' % branch)

    def built(self, n):
        harnesses = {f['harness'] for f in (status.parse(c['body']) for c in self.thread(n))
                     if f and f['agent'] == 'builder'}
        if len(harnesses) != 1 or next(iter(harnesses)) not in DRIVERS:
            raise NeedsYou("#%s's builder family is unknown or conflicting (%s), so its review waits"
                           % (n, ', '.join(sorted(harnesses)) or 'no builder status note'))
        return DRIVERS[next(iter(harnesses))]

    def rule(self):
        r = script('ops-starts.py', 'flags', '--repo', self.repo)
        try:
            flags = json.loads(r.stdout) if r.returncode == 0 else None
        except ValueError:
            flags = None
        if not isinstance(flags, dict):
            raise NeedsYou('the models rule could not be read: %s'
                           % ((r.stderr.strip().split('\n') or [''])[-1] or 'ops-starts.py exit %d' % r.returncode))
        rows = {}
        for start, cell in flags.items():
            found = FLAGS.fullmatch(cell) if isinstance(cell, str) else None
            rows[start] = (PROVIDERS.get(found[1]), found[2]) if found else None
        return rows

    def reviewer(self, p, n):
        built, rows = self.built(n), self.rule()
        if shutil.which('claude') and shutil.which('codex'):
            row = rows.get(REVIEWS[built])
            if row is None:
                raise NeedsYou('the review of #%s waits: ops-starts: %s waits: no other-family choice'
                               % (p, REVIEWS[built]))
            if row[0] != OTHER[built]:
                raise NeedsYou('the review of #%s waits: the models rule names no %s reviewer' % (p, OTHER[built]))
            return row[0], row[1], 'other-family'
        if not shutil.which(built):
            raise NeedsYou("#%s's builder harness %s is not installed, so its review waits" % (n, built))
        recorded = [f['model'] for f in (status.parse(c['body']) for c in self.thread(n))
                    if f and f['agent'] == 'builder']
        models = {cli for harness, names, cli in self.identities() if harness == built and recorded[-1:] and
                  recorded[-1] in names}
        if len(models) != 1:
            raise NeedsYou("the review of #%s waits: the builder's recorded model %s is %s a %s model in the "
                           "models rule" % (p, (recorded or ['(none)'])[-1], 'not' if not models else 'more than',
                                            built))
        return built, models.pop(), 'same-family'

    def identities(self):
        found, section, setting = [], None, {}
        for row in self.fleet().splitlines() + ['## end']:
            if row.startswith('## '):
                if {'Harness', 'Model', 'Effort'} <= set(setting):
                    harness, model, effort = (setting[k] for k in ('Harness', 'Model', 'Effort'))
                    if harness[1] and model[1]:
                        found.append((PROVIDERS.get(harness[1]), {model[0], model[1], '%s %s' % (model[0], effort[0])},
                                      model[1]))
                section, setting = row[3:], {}
                continue
            cells = [c.strip() for c in row.strip().strip('|').split('|')] if row.startswith('|') else []
            flags = FLAGS.search(cells[-1]) if cells else None
            if section == 'Models' and len(cells) == 5 and flags:
                found.append((PROVIDERS.get(flags[1]), {flags[2], cells[2], '%s %s' % (cells[2], cells[3])}, flags[2]))
            elif len(cells) == 3 and cells[0] in ('Harness', 'Model', 'Effort'):
                value = re.fullmatch(r'`--(?:provider|model|reasoning-level) (\S+)`', cells[2])
                setting[cells[0]] = (cells[1], value[1] if value else None)
        return found

    def review(self, p, n, head):
        harness, model, family = self.reviewer(p, n)
        claim = self.claim(p, 'launch-fleet: review starting %s' % head, 'launch-fleet: review withdrawn %s' % head)
        if not claim:
            return False
        target = '%s#%s' % (self.repo, p)
        brief = script('brief.py', 'reviewer', target, head, *(['same-family'] if family == 'same-family' else []))
        if brief.returncode:
            raise NeedsYou('brief.py made no reviewer brief for %s' % target)
        rest = '\nDriver review: %s\n\n%s' % (family, brief.stdout.strip())
        self.edit(claim, 'launch-fleet: review starting %s%s' % (head, rest))
        since = int(time.time())
        r, = self.answers([self.detached("#%s's review start" % p, 'host.py', 'start', self.repo, p, harness, model,
                                         'review-ticket')])
        if r.returncode:
            raise NeedsYou(self.refusal(claim, 'launch-fleet: review refused %s: %%s%s' % (head, rest.replace('%', '%%')),
                                        p, r))
        self.live[('reviewer', p)] = (since, n)
        self.prs[p] = n
        self.edit(claim, 'launch-fleet: review started %s%s' % (head, rest))
        return True

    def fleet(self):
        return post.gh('api', 'repos/%s/contents/docs/agents/fleet.md' % self.repo,
                       '-H', 'Accept: application/vnd.github.raw+json') or ''

    def tick(self):
        self.tick_no += 1
        did = []
        lines = self.due()
        if lines and lines[0].startswith('fleet done #%s:' % self.spec):
            if self.closed():
                raise Done('every ticket of spec #%s is closed' % self.spec)
            raise NeedsYou('spec #%s is not an open spec, but its tickets are not all closed: %s'
                           % (self.spec, lines[0]))
        finished = [line for line in lines if FINISHED.match(line) and FINISHED.match(line)[1] == self.spec]
        todo = [line for line in lines if not LEFT.match(line) and line not in finished]
        if finished and not todo:
            raise Done(finished[0])
        for line in todo:
            if not (START.match(line) or CHECKED.fullmatch(line) or REVIEW.fullmatch(line) or MERGE.fullmatch(line)):
                raise NeedsYou(line)
            if line in self.acted:
                raise NeedsYou('still due after this session did it: %s' % line)
        acted = bool(did)
        for line in todo:
            found = CHECKED.fullmatch(line)
            if found:
                self.checked(*found.groups())
                self.acted.add(line)
                did.append('checked #%s' % found[1])
        starts = {START.match(line)[1]: line for line in todo if START.match(line)}
        ready = list(starts)
        room = max(0, self.a.max - self.builders())
        if ready[:room]:
            started = self.start(ready[:room])
            self.acted.update(starts[n] for n in started)
            if started:
                did.append('started ' + ', '.join('#' + n for n in started))
        acted = acted or bool(did)
        if ready[room:]:
            did.append('%s wait%s for the cap (%d)' % (', '.join('#' + n for n in ready[room:]),
                                                       's' if len(ready) - room == 1 else '', self.a.max))
        for line in todo:
            review = REVIEW.fullmatch(line)
            if review and self.review(*review.groups()):
                self.acted.add(line)
                did.append('review of #%s started' % review[1])
                acted = True
        if did:
            print('session: tick %d: %s' % (self.tick_no, '; '.join(did)), flush=True)
        merges = [line for line in todo if MERGE.fullmatch(line)]
        if merges:
            raise NeedsYou("%s: merge it with launch-fleet's Merging steps, then carry on" % merges[0])
        return acted

    def wait(self):
        while time.monotonic() - self.moved < self.a.idle:
            if self.live:
                for key, (since, number) in sorted(self.live.items()):
                    if self.ended(*key, since, number):
                        del self.live[key]
                        self.moved = time.monotonic()
                        return
                time.sleep(self.a.poll)
                continue
            if not (self.closed() or self.checks_running()):
                raise NeedsYou('nothing is due on spec #%s and no run or check is going' % self.spec)
            time.sleep(self.a.ci_poll)
            return
        raise NeedsYou('nothing moved on spec #%s for %g seconds' % (self.spec, self.a.idle))

    def loop(self):
        self.moved = time.monotonic()
        self.restore()
        while True:
            if self.tick():
                self.moved = time.monotonic()
            else:
                self.wait()


def arguments(argv):
    parser = argparse.ArgumentParser(prog='session.py', description="Run a spec's fleet in this chat.")
    sub = parser.add_subparsers(dest='action', required=True)
    entry = sub.add_parser('run')
    entry.add_argument('repo', metavar='OWNER/NAME')
    entry.add_argument('--spec', required=True)
    for name in ('--harness', '--model'):
        entry.add_argument(name, required=True)
    entry.add_argument('--max', type=int, default=3)
    entry.add_argument('--poll', type=float, default=10)
    entry.add_argument('--ci-poll', type=float, default=30)
    entry.add_argument('--idle', type=float, default=1800)
    args = parser.parse_args(argv)
    if not REPO.fullmatch(args.repo) or args.repo.split('/')[1] in ('.', '..') or not NUMBER.fullmatch(args.spec):
        parser.error('expected OWNER/NAME and a positive spec number')
    if not all(WORD.fullmatch(v) for v in (args.harness, args.model)):
        parser.error('the harness and model must be driver identifiers')
    if args.max < 1 or min(args.poll, args.ci_poll, args.idle) <= 0:
        parser.error('--max must be at least 1, and --poll, --ci-poll and --idle above 0')
    return args


def main(argv):
    args = arguments(argv)
    command = shlex.join(['python3', '-I', str(Path(__file__).resolve()), *argv])
    os.environ.setdefault('GH_REPO', args.repo)
    key = hashlib.sha256(args.repo.lower().encode()).hexdigest()[:20]
    os.environ.setdefault('LAUNCH_FLEET_RUNS', str(STATE / ('runs-%s.json' % key)))
    signal.signal(signal.SIGINT, signal.default_int_handler)
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    session = Session(args, command)
    try:
        with lock(args.repo, args.spec):
            try:
                session.loop()
            except Done as e:
                print('session: done: %s' % e)
                return 0
            except NeedsYou as e:
                print('session: stopped at tick %d: needs you: %s' % (session.tick_no, e))
                print('carry on: ' + command)
                return 3
            except KeyboardInterrupt:
                left = ''.join('; %s had not answered, so its record stays for launch-fleet to reconcile' % job
                               for job in session.pending)
                print('session: stopped on interrupt at tick %d; the runs it started keep going%s'
                      % (session.tick_no, left))
                print('carry on: ' + command)
                return 130
    except Refused as e:
        print('session: refused: %s' % e)
        return 1
    except Unreadable as e:
        print('session.py: %s' % e, file=sys.stderr)
        print('carry on: ' + command, file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
