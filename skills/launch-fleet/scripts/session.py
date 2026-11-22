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
QUEUED = 'launch-fleet: merge queued '
DRIVERS = {'Claude Code': 'claude', 'Codex': 'codex'}
OTHER = {'claude': 'codex', 'codex': 'claude'}
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


def run(argv, check=True):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL)
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
        self.queued = {}
        self.acted = set()
        self.pending = []
        self.tick_no = 0
        self.authors = None
        self.models = {args.reviewer_harness: args.reviewer_model, args.harness: args.model}


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
            receipts = [c for c in comments if first(c).startswith(QUEUED)]
            if receipts and self.state(p) == 'OPEN':
                self.queued[p] = first(max(receipts, key=lambda c: c['id']))[len(QUEUED):][:40]

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

    def reviewer(self, n):
        harnesses = {f['harness'] for f in (status.parse(c['body']) for c in self.thread(n))
                     if f and f['agent'] == 'builder'}
        if len(harnesses) != 1 or next(iter(harnesses)) not in DRIVERS:
            raise NeedsYou("#%s's builder family is unknown or conflicting (%s), so its review waits"
                           % (n, ', '.join(sorted(harnesses)) or 'no builder status note'))
        built = DRIVERS[next(iter(harnesses))]
        if shutil.which('claude') and shutil.which('codex'):
            harness, family = OTHER[built], 'other-family'
        elif shutil.which(built):
            harness, family = built, 'same-family'
        else:
            raise NeedsYou("#%s's builder harness %s is not installed, so its review waits" % (n, built))
        if harness not in self.models:
            raise NeedsYou('no %s reviewer model was given (--harness or --reviewer-harness %s), so the review of '
                           '#%s waits' % (harness, harness, n))
        return harness, self.models[harness], family

    def review(self, p, n, head):
        harness, model, family = self.reviewer(n)
        claim = self.claim(p, 'launch-fleet: review starting %s' % head, 'launch-fleet: review withdrawn %s' % head)
        if not claim:
            return False
        brief = script('brief.py', 'reviewer', p, head, *(['same-family'] if family == 'same-family' else []))
        if brief.returncode:
            raise NeedsYou('brief.py made no reviewer brief for #%s' % p)
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

    def verdict(self, p, head):
        comments = self.thread(p)
        verdicts = [c for c in comments if c['body'].startswith('VERDICT:')]
        assigned = [c for c in comments if first(c).startswith(ASSIGNED)]
        if not verdicts or not first(max(verdicts, key=lambda c: c['id'])).startswith('VERDICT: APPROVE at ' + head):
            raise NeedsYou('#%s was not merged: its newest VERDICT is not an APPROVE at %s' % (p, head))
        if not assigned:
            raise NeedsYou('#%s was not merged: it has no review assignment for its VERDICT to belong to' % p)
        if max(c['id'] for c in verdicts) < max(c['id'] for c in assigned):
            raise NeedsYou('#%s was not merged: its newest VERDICT is older than its current review assignment' % p)

    def batch(self):
        r = run(['sh', str(HERE / 'fleet.sh'), 'overload', 'merge-batch'])
        try:
            answer = json.loads(r.stdout)
        except ValueError:
            answer = None
        if r.returncode == 0 and isinstance(answer, dict) and answer.get('allowed') is True:
            return
        if isinstance(answer, dict):
            why = '%s (%s)' % (answer.get('level'), ', '.join(map(str, answer.get('causes') or [])))
        else:
            why = (r.stderr.strip().split('\n') or [''])[-1] or 'exit %d' % r.returncode
        raise NeedsYou('fleet.sh overload merge-batch did not admit a merge batch: %s' % why)

    def merge(self, line, p, n, head):
        self.verdict(p, head)
        checks = self.checks()
        admit = script('merge.py', 'admit', self.repo, p, head, checks).stdout.strip()
        if admit.startswith('wait:'):
            return False
        flags = []
        if admit == 'base rule: no merge queue; mergeable: MERGEABLE':
            every = run(['sh', str(HERE / 'fleet.sh'), 'every'])
            if every.returncode:
                raise Unreadable('fleet.sh every failed (exit %d)' % every.returncode)
            if line not in every.stdout.splitlines():
                raise NeedsYou('#%s was not merged: fleet.sh every no longer prints its merge line, so another '
                               'pull request merges first or it needs a re-test' % p)
            flags = ['--base-rule-checked']
        elif not admit.startswith('admit:'):
            raise NeedsYou('#%s was not admitted: %s' % (p, admit or 'merge.py admit said nothing'))
        body = ('VERDICT: APPROVE at %s on #%s, and the recorded plan approval of spec #%s; merged by the '
                'session runner' % (head, p, self.spec))
        r, = self.answers([self.detached("#%s's merge" % p, 'merge.py', 'merge', self.repo, p, head, checks, body,
                                         '--ticket', n, *flags)])
        out = r.stdout.strip()
        if r.returncode == 0 and out.startswith('merged '):
            return '#%s merged' % p
        if r.returncode == 0 and out.startswith('queued'):
            self.queued[p] = head
            return '#%s queued' % p
        if r.returncode == 0 and out.startswith('pending:'):
            return False
        raise NeedsYou('#%s did not merge: %s' % (p, out or 'merge.py exit %d' % r.returncode))

    def landed(self):
        did = []
        for p, head in sorted(self.queued.items()):
            out = script('merge.py', 'read', self.repo, p, head).stdout.strip()
            if out.startswith('merged '):
                del self.queued[p]
                did.append('#%s merged' % p)
            elif out != 'queued':
                raise NeedsYou('#%s left the merge queue: %s' % (p, out or 'merge.py read said nothing'))
        return did

    def checks(self):
        text = post.gh('api', 'repos/%s/contents/docs/agents/fleet.md' % self.repo,
                       '-H', 'Accept: application/vnd.github.raw+json') or ''
        section, names = None, []
        for row in text.splitlines():
            if row.startswith('## '):
                section = row
            elif section == '## CI checks':
                found = re.match(r'\| *`([^`]+)` *\|', row)
                if found:
                    names.append(found[1])
        if not names:
            raise NeedsYou('docs/agents/fleet.md lists no CI checks, so nothing can merge')
        return ','.join(names)


    def tick(self):
        self.tick_no += 1
        did = self.landed()
        lines = self.due()
        if lines and lines[0].startswith('fleet done #%s:' % self.spec):
            if self.closed():
                raise Done('every ticket of spec #%s is closed' % self.spec)
            raise NeedsYou('spec #%s is not an open spec, but its tickets are not all closed: %s'
                           % (self.spec, lines[0]))
        finished = [line for line in lines if FINISHED.match(line) and FINISHED.match(line)[1] == self.spec]
        todo = [line for line in lines if not LEFT.match(line) and line not in finished
                and not (MERGE.fullmatch(line) and MERGE.fullmatch(line)[1] in self.queued)]
        if finished and not todo:
            did += self.landed()
            if did:
                print('session: tick %d: %s' % (self.tick_no, '; '.join(did)), flush=True)
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
        if any(MERGE.fullmatch(line) for line in todo):
            self.batch()
        for line in todo:
            review, merge = REVIEW.fullmatch(line), MERGE.fullmatch(line)
            done = review and self.review(*review.groups()) and 'review of #%s started' % review[1]
            done = done or (merge and self.merge(line, *merge.groups()))
            if done:
                self.acted.add(line)
                did.append(done)
                acted = True
        if did:
            print('session: tick %d: %s' % (self.tick_no, '; '.join(did)), flush=True)
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
            if not (self.queued or self.closed() or self.checks_running()):
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
    for name in ('--harness', '--model', '--reviewer-harness', '--reviewer-model'):
        entry.add_argument(name, required=True)
    entry.add_argument('--max', type=int, default=3)
    entry.add_argument('--poll', type=float, default=10)
    entry.add_argument('--ci-poll', type=float, default=30)
    entry.add_argument('--idle', type=float, default=1800)
    args = parser.parse_args(argv)
    if not REPO.fullmatch(args.repo) or args.repo.split('/')[1] in ('.', '..') or not NUMBER.fullmatch(args.spec):
        parser.error('expected OWNER/NAME and a positive spec number')
    if not all(WORD.fullmatch(v) for v in (args.harness, args.model, args.reviewer_harness, args.reviewer_model)):
        parser.error('harnesses and models must be driver identifiers')
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
