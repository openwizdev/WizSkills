#!/usr/bin/env python3
"""The session runner (#2324): the open Claude Code or Codex chat is the fleet.

  session.py run OWNER/NAME --spec S --harness H --model M --reviewer-harness H --reviewer-model M
             [--max 3] [--poll 10] [--ci-poll 30] [--idle 1800]

Run it in the foreground from the project checkout, with the environment host.py needs
(OPENWIZ_ADAPTERS, and LAUNCH_FLEET_RUNS or the heartbeat's own project run map by default).
Each tick reads `fleet.sh spec S` and does the lines a script can do alone, by the skill's own rules:

- `start #N`: claim it (`launch-fleet: starting`, then `fleet.sh claim`), start its builder with
  `host.py start` and record `launch-fleet: started`; at most --max builders this session started run at
  once, and the rest wait. The first start of a tick goes alone, as the batch's probe; the rest go together.
- `check start #N: thread run:N, branch B`: record `launch-fleet: start checked, branch B`.
- `review #P for #N at C`: claim it, start the reviewer with `host.py start ... review-ticket` and the
  reviewer brief, and record `launch-fleet: review started C`.
- `merge #P for #N at C`: `merge.py admit`, then `merge.py merge` (with `--base-rule-checked` only after a
  fresh `fleet.sh spec S` still prints the same line).
- `archive #N` is left for launch-fleet; any other line needs you.

No timer: after a tick that did something it ticks again at once. Otherwise it waits only for a run it
started to end (that agent's status note on its ticket or pull request leaves `working`), checking every
--poll seconds, or, with no run going, for a known pull request's checks to finish, every --ci-poll seconds.
Nothing moving for --idle seconds needs you.

It holds the spec's heartbeat lock (the folder heartbeat.py locks), so a session and a heartbeat tick never
run together. The runs it started keep going after it stops.

Exit 0 `session: done: every ticket of spec #S is closed`. Exit 1 `session: refused: ...` (the lock is held).
Exit 2 `session.py: <why>` on stderr: bad arguments or an unreadable read. Exit 3 `session: stopped at tick
<n>: needs you: <what>`. Exit 130 on interrupt. Each stop but done and refused ends with `carry on: <the
command>`.
"""
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
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
import time

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
    """Exit 1."""


class Unreadable(Exception):
    """Exit 2."""


class NeedsYou(Exception):
    """Exit 3."""


class Done(Exception):
    """Exit 0."""


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
    """The heartbeat's own per-spec lock: an exclusive flock on its job folder, made here when absent."""
    key = hashlib.sha256(('%s#%s' % (repo.lower(), spec)).encode()).hexdigest()[:20]
    folder = STATE / ('openwiz-heartbeat-' + key)
    made = False
    try:
        STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
        folder.mkdir(mode=0o700)
        made = True
    except FileExistsError:
        pass
    except OSError as e:
        raise Unreadable("can't make the lock folder (%s)" % type(e).__name__)
    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Refused('a session or heartbeat tick already runs spec #%s' % spec) from None
        try:
            yield
        finally:
            if made:
                try:
                    folder.rmdir()  # only while empty: a heartbeat installed meanwhile keeps its folder
                except OSError:
                    pass
    finally:
        os.close(fd)


class Session:
    def __init__(self, args, command):
        self.a, self.command = args, command
        self.repo, self.spec = args.repo, args.spec
        self.live = {}       # (agent, number) -> the second its run started
        self.prs = set()     # pull requests its builders handed back
        self.acted = set()   # every line this session acted on: one seen again needs you
        self.tick_no = 0
        self.authors = None

    # GitHub reads

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

    def closed(self):
        pages = post.read_json('api', '--paginate', '--slurp',
                               'repos/%s/issues/%s/sub_issues?per_page=100' % (self.repo, self.spec))
        if not isinstance(pages, list) or not all(isinstance(p, list) for p in pages):
            raise Unreadable("spec #%s's tickets could not be read" % self.spec)
        items = [i for p in pages for i in p]
        return bool(items) and all(isinstance(i, dict) and i.get('state') == 'closed' for i in items)

    def ended(self, agent, number, since):
        """The run's agent wrote a status note since its start that is no longer `working`."""
        notes = [f for f in (status.parse(c['body']) for c in self.thread(number)) if f and f['agent'] == agent]
        notes = [f for f in notes if datetime.strptime(f['time'], '%Y-%m-%dT%H:%M:%SZ').replace(
            tzinfo=timezone.utc).timestamp() >= since]
        if not notes or notes[-1]['state'] == 'working':
            return False
        found = PR.fullmatch(notes[-1].get('pr', ''))
        if found:
            self.prs.add(found[1])
        return True

    def checks_running(self):
        for p in sorted(self.prs):
            text = post.gh('pr', 'view', p, '--repo', self.repo, '--json', 'state,statusCheckRollup')
            try:
                pr = json.loads(text or '')
            except ValueError:
                raise Unreadable('pull request #%s could not be read' % p)
            if pr.get('state') != 'OPEN':
                continue
            checks = pr.get('statusCheckRollup') or []
            if not checks or any(c.get('status', 'COMPLETED') != 'COMPLETED'
                                 or c.get('state') in ('PENDING', 'EXPECTED') for c in checks):
                return True
        return False

    # Records

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
        """A start host.py didn't confirm: record a definite refusal; an unknown one stays claimed. Its stop line."""
        line = r.stdout.strip().split('\n')[0] or r.stderr.strip() or 'host.py exit %d' % r.returncode
        if r.returncode == 1 and line.startswith('stopped (driver start failed)'):
            self.edit(claim, kind % 'driver start failed')
        elif r.returncode == 1 and line.startswith('refused:'):
            self.edit(claim, kind % 'the host refused it')
        return line if line.startswith('stopped') else '#%s did not start: %s' % (number, line)

    # Lines

    def builders(self):
        return sum(agent == 'builder' for agent, _ in self.live)

    def start(self, numbers):
        """Claim and start each builder: the first alone, as the batch's probe, then the rest together."""
        started, stops = [], []
        for batch in (numbers[:1], numbers[1:]):
            since = int(time.time())  # before the driver runs: a quick run's note may land before it answers
            claims = [(n, c) for n in batch for c in [self.claim(n, 'launch-fleet: starting',
                                                                 'launch-fleet: start withdrawn')] if c]
            with ThreadPoolExecutor(max_workers=max(1, len(claims))) as pool:
                results = list(pool.map(lambda nc: (nc, script('host.py', 'start', self.repo, nc[0], self.a.harness,
                                                                self.a.model)), claims))
            for (n, claim), r in results:
                if r.returncode:
                    stops.append(self.refusal(claim, 'launch-fleet: start refused: %s', n, r))
                    continue
                self.live[('builder', n)] = since
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

    def review(self, p, head):
        claim = self.claim(p, 'launch-fleet: review starting %s' % head, 'launch-fleet: review withdrawn %s' % head)
        if not claim:
            return False
        family = 'same-family' if self.a.reviewer_harness == self.a.harness else 'other-family'
        brief = script('brief.py', 'reviewer', p, head, *(['same-family'] if family == 'same-family' else []))
        if brief.returncode:
            raise NeedsYou('brief.py made no reviewer brief for #%s' % p)
        rest = '\nDriver review: %s\n\n%s' % (family, brief.stdout.strip())
        self.edit(claim, 'launch-fleet: review starting %s%s' % (head, rest))
        since = int(time.time())
        r = script('host.py', 'start', self.repo, p, self.a.reviewer_harness, self.a.reviewer_model, 'review-ticket')
        if r.returncode:
            raise NeedsYou(self.refusal(claim, 'launch-fleet: review refused %s: %%s%s' % (head, rest.replace('%', '%%')),
                                        p, r))
        self.live[('reviewer', p)] = since
        self.edit(claim, 'launch-fleet: review started %s%s' % (head, rest))
        return True

    def merge(self, line, p, n, head):
        checks = self.checks()
        admit = script('merge.py', 'admit', self.repo, p, head, checks).stdout.strip()
        if admit.startswith('wait:'):
            return False
        flags = []
        if admit == 'base rule: no merge queue; mergeable: MERGEABLE':
            if line not in self.due():
                return False
            flags = ['--base-rule-checked']
        elif not admit.startswith('admit:'):
            raise NeedsYou('#%s was not admitted: %s' % (p, admit or 'merge.py admit said nothing'))
        body = ('VERDICT: APPROVE at %s on #%s, and the recorded plan approval of spec #%s; merged by the '
                'session runner' % (head, p, self.spec))
        r = script('merge.py', 'merge', self.repo, p, head, checks, body, '--ticket', n, *flags)
        out = r.stdout.strip()
        if r.returncode == 0 and out.startswith(('merged ', 'queued')):
            self.prs.add(p)
            return True
        if r.returncode == 0 and out.startswith('pending:'):
            return False
        raise NeedsYou('#%s did not merge: %s' % (p, out or 'merge.py exit %d' % r.returncode))

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

    # The loop

    def tick(self):
        """One tick: True when it did something, so the next tick runs at once."""
        self.tick_no += 1
        lines = self.due()
        if lines and lines[0].startswith('fleet done #%s:' % self.spec):
            raise Done()
        todo = [line for line in lines if not LEFT.match(line)]
        for line in todo:
            if not (START.match(line) or CHECKED.fullmatch(line) or REVIEW.fullmatch(line) or MERGE.fullmatch(line)):
                raise NeedsYou(line)
            if line in self.acted:
                raise NeedsYou('still due after this session did it: %s' % line)
        did = []
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
            did.append('started ' + ', '.join('#' + n for n in started))
        acted = bool(did)
        if ready[room:]:
            did.append('%s wait%s for the cap (%d)' % (', '.join('#' + n for n in ready[room:]),
                                                       's' if len(ready) - room == 1 else '', self.a.max))
        for line in todo:
            review, merge = REVIEW.fullmatch(line), MERGE.fullmatch(line)
            if (review and self.review(review[1], review[3])) or (merge and self.merge(line, *merge.groups())):
                self.acted.add(line)
                did.append('review of #%s started' % review[1] if review else '#%s merged' % merge[1])
                acted = True
        if did:
            print('session: tick %d: %s' % (self.tick_no, '; '.join(did)), flush=True)
        return acted

    def wait(self):
        """Back once a run it started has ended, or a known pull request's checks may have moved."""
        while time.monotonic() - self.moved < self.a.idle:
            if self.live:
                for key, since in sorted(self.live.items()):
                    if self.ended(*key, since):
                        del self.live[key]
                        self.moved = time.monotonic()
                        return
                time.sleep(self.a.poll)
                continue
            if self.closed():
                raise Done()
            if not self.checks_running():
                raise NeedsYou('nothing is due on spec #%s and no run or check is going' % self.spec)
            time.sleep(self.a.ci_poll)
            return
        raise NeedsYou('nothing moved on spec #%s for %g seconds' % (self.spec, self.a.idle))

    def loop(self):
        self.moved = time.monotonic()   # the last tick that did something, or the last run that ended
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
    os.environ.setdefault('LAUNCH_FLEET_RUNS', str(STATE / ('runs-%s.json' % key)))  # the heartbeat's map
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    session = Session(args, command)
    try:
        with lock(args.repo, args.spec):
            try:
                session.loop()
            except Done:
                print('session: done: every ticket of spec #%s is closed' % args.spec)
                return 0
            except NeedsYou as e:
                print('session: stopped at tick %d: needs you: %s' % (session.tick_no, e))
                print('carry on: ' + command)
                return 3
            except KeyboardInterrupt:
                print('session: stopped on interrupt at tick %d; the runs it started keep going' % session.tick_no)
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
