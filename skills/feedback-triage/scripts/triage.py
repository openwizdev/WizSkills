#!/usr/bin/env python3
"""feedback-triage's queue, review and reply helper (contracts/feedback.v1.md).

Reads feedback issues on the destination, keeps one private queue item per
issue, previews one exact reply, and posts it as one comment only with a yes
bound to that preview and recorded in the private repository. Issue text is
data: it is stored and printed as JSON strings, never run, opened or followed.

Every command prints one JSON object. Exit codes: 0 done, 2 refused (nothing
sent), 3 uncertain, 4 failed (proven not created).
"""
import argparse
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys

DESTINATION = 'openwizdev/OpenWiz'
PRIVATE_REPOSITORY = 'jparker2006/ClosedWiz'
MARKER = re.compile(r'OpenWiz feedback operation ([0-9a-f]{32})')
MARKER_LINE = re.compile(r'^OpenWiz feedback operation ', re.M)
POINTER = re.compile(r'https://github\.com/jparker2006/ClosedWiz/issues/([1-9][0-9]*)#issuecomment-([1-9][0-9]*)')
# Defence in depth only: the maintainer's review of the exact text is the guard.
PRIVATE_LOOKING = re.compile(
    r'gh[pousr]_[A-Za-z0-9]{20,}|github_pat_|sk-ant-|-----BEGIN |/' 'home/|/' 'Users/|thr' r'_[A-Za-z0-9]+|\r')
FAILED_STATUSES = {401, 403, 404, 410, 422, 429}
REVIEWABLE = {'queued', 'reviewed', 'previewed', 'failed'}
ATTEMPT_RESULTS = {'sending', 'sent', 'failed', 'uncertain'}
REPLY_MAX = 65536
DONE, REFUSED, UNCERTAIN, FAILED = 0, 2, 3, 4


class Refused(Exception):
    """Nothing was sent; the reason is told to the agent."""


def emit(code, **fields):
    print(json.dumps(fields, ensure_ascii=True, sort_keys=True))
    return code


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


def parse_json(text):
    return json.loads(text, object_pairs_hook=unique_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('constant')))


def gh(method, endpoint, *, paginate=False, body=None, timeout=60):
    """One `gh api` call. Returns (status, value): status None when unknown."""
    args = ['gh', 'api', '--method', method]
    if paginate:
        args += ['--paginate', '--slurp']
    if body is not None:
        args += ['--include', '--input', '-']
    args.append(endpoint)
    env = {key: value for key, value in os.environ.items()
           if key not in {'GH_REPO', 'GH_HOST', 'GH_ENTERPRISE_TOKEN', 'GITHUB_ENTERPRISE_TOKEN'}}
    try:
        result = subprocess.run(args, input=None if body is None else json.dumps(body),
                                capture_output=True, text=True, timeout=timeout,
                                check=False, env=env, stdin=None if body is not None else subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return None, None
    out = result.stdout
    status = None
    if body is not None:
        head, sep, out = out.replace('\r\n', '\n').partition('\n\n')
        match = re.match(r'HTTP/[0-9.]+ ([0-9]{3})\b', head)
        if not sep or not match:
            return None, None
        status = int(match.group(1))
    elif result.returncode == 0:
        status = 200
    try:
        value = parse_json(out)
    except (ValueError, RecursionError):
        return (status if status and status >= 400 else None), None
    if body is None and result.returncode != 0:
        return None, value
    return status, value


def read(endpoint, **kwargs):
    status, value = gh('GET', endpoint, **kwargs)
    if status != 200:
        raise Refused(f'could not read {endpoint}')
    return value


def same_name(value, name):
    """GitHub matches owner and repository names in any capitals (RN6); anything not ASCII is refused."""
    return isinstance(value, str) and value.isascii() and value.lower() == name.lower()


def destination_public():
    repo = read(f'repos/{DESTINATION}')
    if not (isinstance(repo, dict) and same_name(repo.get('full_name'), DESTINATION)
            and repo.get('private') is False and repo.get('visibility') == 'public'
            and repo.get('archived') is False and repo.get('has_issues') is True):
        raise Refused(f'{DESTINATION} is not verified public, unarchived and open for issues')


def logged_in():
    user = read('user')
    if not (isinstance(user, dict) and type(user.get('login')) is str and type(user.get('id')) is int):
        raise Refused('the logged-in account is unreadable')
    return {'login': user['login'], 'id': user['id']}


def as_feedback(item):
    """The issue's compact record if it is feedback under the contract, else None."""
    if not isinstance(item, dict) or 'pull_request' in item:
        return None
    number, title, body, user = item.get('number'), item.get('title'), item.get('body'), item.get('user')
    if not (type(number) is int and number > 0 and type(title) is str and type(body) is str
            and isinstance(user, dict) and type(user.get('login')) is str and type(user.get('id')) is int):
        return None
    text, sep, last = body.rpartition('\n\n')
    match = MARKER.fullmatch(last)
    if not sep or not match or '\n' in last or MARKER_LINE.search(text):
        return None
    return {'number': number, 'title': title, 'body': body, 'operation_id': match.group(1),
            'author': {'login': user['login'], 'id': user['id']}}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


class Queue:
    """Private, owner-only state: one item per issue, and separate attempt evidence.

    The root is checked as its real path, outside every repository; its folders,
    lock and records must be real files, never links, and are opened without
    following links, so nothing can redirect a private read or write.
    """

    def __init__(self, root):
        self.root = Path(os.path.realpath(Path(root).expanduser().absolute()))
        for parent in [self.root, *self.root.parents]:
            if os.path.lexists(parent / '.git'):
                raise Refused('the queue must live outside every repository')
        self.items = self.root / 'items'
        self.attempts = self.root / 'attempts'

    @staticmethod
    def real_dir(path, create):
        try:
            mode = os.lstat(path).st_mode
        except FileNotFoundError:
            if not create:
                return False
            os.mkdir(path, 0o700)
            mode = os.lstat(path).st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise Refused(f'{path} is linked or not a folder')
        if create:
            os.chmod(path, 0o700)
        return True

    def readable(self):
        """For readers: refuse linked storage, create nothing."""
        if self.real_dir(self.root, False):
            self.real_dir(self.items, False)
            self.real_dir(self.attempts, False)

    @contextlib.contextmanager
    def locked(self):
        old = os.umask(0o077)
        try:
            os.makedirs(self.root.parent, mode=0o700, exist_ok=True)
            for path in (self.root, self.items, self.attempts):
                self.real_dir(path, True)
            try:
                lock = os.open(self.root / 'lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            except OSError:
                raise Refused('the queue lock is linked or unreadable') from None
            try:
                fcntl.flock(lock, fcntl.LOCK_EX)
                yield self
            finally:
                os.close(lock)
        finally:
            os.umask(old)

    @staticmethod
    def read_json(path):
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, encoding='utf-8') as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise ValueError('not a file')
            return parse_json(source.read())

    @staticmethod
    def write_json(folder, name, value):
        temp = folder / f'.{name}.{secrets.token_hex(8)}.tmp'
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(value, out, ensure_ascii=True, sort_keys=True, indent=1)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, folder / name)
        directory = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def path(self, number):
        return self.items / f'{number}.json'

    def exists(self, number):
        return os.path.lexists(self.path(number))

    def load(self, number, persist=True):
        """The item. A restart that finds `sending` is uncertain; only a locked writer saves that."""
        try:
            item = self.read_json(self.path(number))
            if not isinstance(item, dict) or item.get('issue', {}).get('number') != number:
                raise ValueError('wrong record')
        except FileNotFoundError:
            raise Refused(f'#{number} is not in the queue; if it was ever sent, it cannot be told now') from None
        except (OSError, ValueError, AttributeError):
            raise Refused(f'#{number} has an unreadable record: whether a reply was sent cannot be told') from None
        if item['phase'] == 'sending':
            item['phase'] = 'uncertain'
            item['reason'] = 'restarted while sending'
            if persist:
                self.save(item)
        return item

    def save(self, item):
        self.write_json(self.items, f'{item["issue"]["number"]}.json', item)

    def load_attempts(self, number, persist=True):
        """Every create attempt for the issue, kept apart from its item. Missing is none."""
        try:
            record = self.read_json(self.attempts / f'{number}.json')
            attempts = record['attempts']
            if (record.get('issue') != number or not isinstance(attempts, list)
                    or any(not isinstance(a, dict) or a.get('result') not in ATTEMPT_RESULTS for a in attempts)):
                raise ValueError('wrong record')
        except FileNotFoundError:
            return []
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise Refused(f'#{number} has unreadable attempt evidence: whether a reply was sent cannot be told') from None
        if attempts and attempts[-1]['result'] == 'sending':
            attempts[-1].update(result='uncertain', reason='restarted while sending')
            if persist:
                self.save_attempts(number, attempts)
        return attempts

    def save_attempts(self, number, attempts):
        self.write_json(self.attempts, f'{number}.json', {'issue': number, 'attempts': attempts})

    def all(self):
        if not self.real_dir(self.items, False):
            return []
        numbers = sorted(int(name[:-5]) for name in os.listdir(self.items)
                         if name.endswith('.json') and name[:-5].isdigit())
        return numbers


def follow(item, last):
    """Bring the item in line with its newest attempt, the authority on what was sent. True if changed."""
    before = json.dumps(item, sort_keys=True)
    result = last['result']
    if result in {'sent', 'uncertain'}:
        if item.get('reply') != last['reply']:
            if 'reply' in item:
                item['unsent_draft'] = item['reply']  # a replacement draft is kept, marked unsent
            item['reply'] = last['reply']
        item.pop('binding', None)
        item.update(phase=result)
        item.pop('reason', None)
        if last.get('reason'):
            item['reason'] = last['reason']
        if 'comment' in last:
            item['comment'] = last['comment']
    elif result == 'failed' and (item['phase'] in {'sending', 'uncertain'}
                                 or item.get('binding', {}).get('digest') == last['binding']):
        item.pop('binding', None)  # its yes is spent
        item.update(phase='failed', reason=last.get('reason'))
    return json.dumps(item, sort_keys=True) != before


def synced(queue, number, persist=True):
    """The item and its attempts, the item following its newest attempt."""
    item = queue.load(number, persist)
    attempts = queue.load_attempts(number, persist)
    if attempts and follow(item, attempts[-1]) and persist:
        queue.save(item)
    return item, attempts


def public_view(item):
    issue = dict(item['issue'], untrusted=True)
    view = {key: value for key, value in item.items() if key not in {'issue', 'approval'}}
    view['issue'] = issue
    return view


def current_issue(number, item):
    issue = as_feedback(read(f'repos/{DESTINATION}/issues/{number}'))
    if issue is None or issue != item['issue']:
        raise Refused(f'#{number} changed or is no longer feedback: review it again')


def cmd_scan(queue, _args):
    destination_public()
    pages = read(f'repos/{DESTINATION}/issues?state=open&per_page=100', paginate=True)
    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
        raise Refused('the issue list is unreadable')
    queued, changed, blocked = [], [], []
    for page in pages:
        for raw in page:
            issue = as_feedback(raw)
            if issue is None:
                continue
            number = issue['number']
            try:
                if queue.exists(number):
                    if queue.load(number)['issue'] != issue:
                        changed.append(number)
                    continue
                attempts = queue.load_attempts(number)
            except Refused:
                blocked.append(number)
                continue
            if attempts and attempts[-1]['result'] != 'failed':
                blocked.append(number)  # attempted before and its record is lost: never requeue
                continue
            queue.save({'issue': issue, 'phase': 'queued', 'refusals': []})
            queued.append(number)
    return emit(DONE, queued=sorted(queued), changed=sorted(changed), blocked=sorted(blocked))


def cmd_refresh(queue, args):
    """Replace an edited issue's snapshot; its review, reply and any preview start again."""
    item, attempts = synced(queue, args.number)
    if item['phase'] not in REVIEWABLE or (attempts and attempts[-1]['result'] != 'failed'):
        raise Refused(f'#{args.number} is {item["phase"]}: it can no longer be refreshed')
    destination_public()
    issue = as_feedback(read(f'repos/{DESTINATION}/issues/{args.number}'))
    if issue is None or issue['number'] != args.number:
        raise Refused(f'#{args.number} is no longer feedback')
    for key in ('review', 'reply', 'binding'):
        item.pop(key, None)
    item.update(issue=issue, phase='queued', refreshes=item.get('refreshes', 0) + 1)
    queue.save(item)
    return emit(DONE, phase='queued', number=args.number)


def cmd_list(queue, _args):
    items = [synced(queue, n, persist=False)[0] for n in queue.all()]
    items = [{'number': i['issue']['number'], 'phase': i['phase'],
              'actionable': i.get('review', {}).get('actionable')} for i in items]
    return emit(DONE, items=items)


def cmd_show(queue, args):
    return emit(DONE, **public_view(synced(queue, args.number, persist=False)[0]))


def cmd_propose(queue, args):
    item, _attempts = synced(queue, args.number)
    if item['phase'] not in REVIEWABLE:
        raise Refused(f'#{args.number} is {item["phase"]}: its reply can no longer change')
    try:
        with open(args.reply_file, encoding='utf-8', newline='') as source:
            reply = source.read()
    except (OSError, UnicodeError):
        raise Refused('the reply file is unreadable') from None
    if not reply.strip() or len(reply) > REPLY_MAX:
        raise Refused(f'the reply must be 1 to {REPLY_MAX} characters')
    if PRIVATE_LOOKING.search(reply):
        raise Refused('the reply holds private-looking material; write it fresh in public words')
    item.update(phase='reviewed', reply=reply, review={
        'what': args.what, 'actionable': args.actionable == 'yes', 'next_step': args.next})
    item.pop('binding', None)
    queue.save(item)
    return emit(DONE, phase='reviewed', number=args.number)


def cmd_preview(queue, args):
    item, _attempts = synced(queue, args.number)
    if item['phase'] not in {'reviewed', 'previewed', 'failed'}:
        raise Refused(f'#{args.number} is {item["phase"]}: nothing to preview')
    destination_public()
    current_issue(args.number, item)
    account = logged_in()
    if account['login'] != args.maintainer:
        raise Refused(f'the logged-in account is not {args.maintainer}')
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    binding = {'destination': DESTINATION, 'issue': args.number, 'issue_digest': digest(item['issue']),
               'account': account, 'reply': item['reply'], 'previewed_at': now,
               'nonce': secrets.token_hex(16)}
    item.update(phase='previewed', binding=dict(binding, digest=digest(binding)))
    queue.save(item)
    url = f'https://github.com/{DESTINATION}/issues/{args.number}'
    shown = (f'Reply as {account["login"]} on {url} (public: anyone can read it), once:\n\n'
             f'{item["reply"]}\n\nApproval binding {item["binding"]["digest"]}')
    return emit(DONE, phase='previewed', binding=item['binding']['digest'], preview=shown)


def cmd_refuse(queue, args):
    item, _attempts = synced(queue, args.number)
    if item['phase'] not in {'reviewed', 'previewed', 'failed'}:
        raise Refused(f'#{args.number} is {item["phase"]}')
    item.pop('binding', None)
    item['phase'] = 'reviewed'
    item['refusals'].append(args.reason)
    queue.save(item)
    return emit(DONE, phase='reviewed', number=args.number)


def check_record(pointer, binding):
    match = POINTER.fullmatch(pointer or '')
    if not match:
        raise Refused('the approval needs its private record pointer')
    record_issue, record_comment = int(match.group(1)), int(match.group(2))
    repo = read(f'repos/{PRIVATE_REPOSITORY}')
    if not (isinstance(repo, dict) and repo.get('private') is True):
        raise Refused('the private repository is not verified private')
    holder = read(f'repos/{PRIVATE_REPOSITORY}/issues/{record_issue}')
    if not (isinstance(holder, dict) and holder.get('title') == f'Private record: OpenWiz #{binding["issue"]}'):
        raise Refused('the private record is not on this issue\'s private record')
    record = read(f'repos/{PRIVATE_REPOSITORY}/issues/comments/{record_comment}')
    if not (isinstance(record, dict) and type(record.get('body')) is str and isinstance(record.get('user'), dict)
            and record.get('issue_url') == f'https://api.github.com/repos/{PRIVATE_REPOSITORY}/issues/{record_issue}'
            and record['user'].get('id') == binding['account']['id']
            and f'Approval binding {binding["digest"]}' in record['body'].splitlines()):
        raise Refused('the private record does not hold this yes')


def matches(comment, attempt):
    """The attempt's own comment: on its issue, by its account, its exact text, and new."""
    return (isinstance(comment, dict) and type(comment.get('id')) is int
            and comment['id'] not in attempt['existing']
            and same_name(comment.get('issue_url'), f'https://api.github.com/repos/{DESTINATION}/issues/{attempt["issue"]}')
            and isinstance(comment.get('user'), dict) and comment['user'].get('id') == attempt['account']['id']
            and comment.get('body') == attempt['reply'])


def finish(queue, number, item, attempts, phase, **facts):
    """Record one outcome: the attempt evidence first, then the item if it is still there."""
    attempts[-1].update(result=phase, **facts)
    queue.save_attempts(number, attempts)
    if item is not None:
        item.update(phase=phase)
        item.pop('reason', None)
        if 'reason' in facts:
            item['reason'] = facts['reason']
        if 'comment' in facts:
            item['comment'] = facts['comment']
        if phase == 'failed':
            item.pop('binding', None)
        queue.save(item)


def settle(queue, number, item, attempts, comment):
    finish(queue, number, item, attempts, 'sent', comment={'id': comment['id'], 'url': comment.get('html_url')})
    return emit(DONE, phase='sent', number=number, url=comment.get('html_url'))


def unsettled(queue, number, item, attempts, reason):
    finish(queue, number, item, attempts, 'uncertain', reason=reason)
    return emit(UNCERTAIN, phase='uncertain', number=number, reason=reason,
                next='reconcile on the issue before anything else; never send again')


def outcome(item):
    code = {'sent': DONE, 'uncertain': UNCERTAIN}[item['phase']]
    return emit(code, phase=item['phase'], number=item['issue']['number'], repeated=True,
                url=item.get('comment', {}).get('url'), reason=item.get('reason'))


def comment_pages(number):
    pages = read(f'repos/{DESTINATION}/issues/{number}/comments?per_page=100', paginate=True)
    if (not isinstance(pages, list) or any(not isinstance(page, list) for page in pages)
            or any(not isinstance(c, dict) or type(c.get('id')) is not int for page in pages for c in page)):
        raise Refused('the issue\'s comments are unreadable')
    return [c for page in pages for c in page]


def cmd_send(queue, args):
    item, attempts = synced(queue, args.number)
    if item['phase'] in {'sent', 'uncertain'}:
        return outcome(item)  # a repeated yes posts nothing; a new yes never clears an attempt
    binding = item.get('binding')
    if item['phase'] != 'previewed' or not binding or args.binding != binding['digest']:
        raise Refused('no yes to the current preview: preview it again and ask')
    if any(attempt['binding'] == binding['digest'] for attempt in attempts):
        raise Refused('this yes was already spent on an earlier attempt: preview it again and ask')
    check_record(args.record, binding)
    destination_public()
    current_issue(args.number, item)
    if logged_in() != binding['account']:
        raise Refused('the logged-in account changed since the preview')
    existing = sorted(c['id'] for c in comment_pages(args.number))
    attempts.append({'binding': binding['digest'], 'issue': args.number, 'account': binding['account'],
                     'reply': binding['reply'], 'record': args.record, 'existing': existing,
                     'comment_id': None, 'result': 'sending'})
    queue.save_attempts(args.number, attempts)  # durable evidence before the one create request
    item.update(phase='sending', approval={'record': args.record, 'binding': binding['digest']})
    queue.save(item)
    status, created = gh('POST', f'repos/{DESTINATION}/issues/{args.number}/comments',
                         body={'body': binding['reply']}, timeout=args.timeout)
    if status in FAILED_STATUSES and isinstance(created, dict):
        finish(queue, args.number, item, attempts, 'failed', reason=f'HTTP {status}')
        return emit(FAILED, phase='failed', number=args.number, reason=f'HTTP {status}')
    if status != 201 or not isinstance(created, dict) or type(created.get('id')) is not int:
        return unsettled(queue, args.number, item, attempts, 'no complete response')
    attempts[-1]['comment_id'] = created['id']
    queue.save_attempts(args.number, attempts)  # the created id is kept before the read-back
    try:
        back = read(f'repos/{DESTINATION}/issues/comments/{created["id"]}')
    except Refused:
        return unsettled(queue, args.number, item, attempts, 'the created comment could not be read back')
    if not matches(back, attempts[-1]):
        return unsettled(queue, args.number, item, attempts, 'the read-back differs from the approved reply')
    return settle(queue, args.number, item, attempts, back)


def cmd_reconcile(queue, args):
    attempts = queue.load_attempts(args.number)
    if not attempts or attempts[-1]['result'] != 'uncertain':
        raise Refused(f'#{args.number} has no uncertain attempt to reconcile')
    try:
        item, attempts = synced(queue, args.number)
    except Refused:
        item = None  # lost or unreadable: the attempt evidence alone is reconciled
    attempt = attempts[-1]
    known = attempt.get('comment_id')
    if args.comment and known is not None and args.comment != known:
        return unsettled(queue, args.number, item, attempts, f'this attempt created comment {known}, not {args.comment}')
    try:
        if known is not None or args.comment:
            found = [read(f'repos/{DESTINATION}/issues/comments/{known or args.comment}')]
        else:
            found = comment_pages(args.number)
    except Refused:
        return unsettled(queue, args.number, item, attempts, 'a reconciliation read failed')
    hits = [c for c in found if matches(c, attempt)]
    if len(hits) == 1:
        return settle(queue, args.number, item, attempts, hits[0])
    if len(hits) > 1:
        return unsettled(queue, args.number, item, attempts, 'more than one matching comment: possibly duplicated')
    return unsettled(queue, args.number, item, attempts,
                     'no new matching comment found; an empty read is not proof of no effect')


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--state', default=str(Path.home() / '.openwiz' / 'feedback-triage' / DESTINATION.lower()))
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('scan')
    sub.add_parser('list')
    for name in ('show', 'refresh', 'propose', 'preview', 'refuse', 'send', 'reconcile'):
        command = sub.add_parser(name)
        command.add_argument('number', type=int)
        if name == 'propose':
            command.add_argument('--what', required=True)
            command.add_argument('--actionable', choices=['yes', 'no'], required=True)
            command.add_argument('--next', required=True)
            command.add_argument('--reply-file', required=True)
        if name == 'preview':
            command.add_argument('--maintainer', required=True)
        if name == 'refuse':
            command.add_argument('--reason', required=True)
        if name == 'send':
            command.add_argument('--binding')
            command.add_argument('--record')
            command.add_argument('--timeout', type=float, default=60)
        if name == 'reconcile':
            command.add_argument('--comment', type=int)
    args = parser.parse_args(argv)
    try:
        queue = Queue(args.state)
        if args.command in {'list', 'show'}:  # read-only: no lock, no write
            queue.readable()
            return globals()[f'cmd_{args.command}'](queue, args)
        with queue.locked():
            return globals()[f'cmd_{args.command}'](queue, args)
    except Refused as refusal:
        return emit(REFUSED, refused=str(refusal))


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
