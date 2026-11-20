#!/usr/bin/env python3
"""The agent helper (GA3, #1844): an openwiz[bot] token for gh and git.

It follows contracts/token-service.v1.md. It asks the owner's token service for
an installation token, keeps it in a private file, hands it to gh as GH_TOKEN in
one child's environment and to git through a credential helper that reads that
file, refreshes it with 300 seconds or less left, and falls back to the owner's
GitHub login with one standard-error note. It never asks for, reads or holds the
App's key, and never prints, logs or passes a token as an argument.

    agent-token.py start REQUEST
    agent-token.py run REQUEST -- COMMAND [ARG...]
    REQUEST: --requester LABEL --repository OWNER/NAME... [--read]

Each request has its own cache file, so agents on one account never share or
replace each other's tokens. Each run copies its token into a snapshot file
that lives only while COMMAND runs; gh gets it as GH_TOKEN and git through
`credential --snapshot`, which answers only git's own HTTPS transport. Whenever
it cannot answer inside a run, it prints one note and tells git to quit, so git
never signs in as another account after the App was chosen. The run also gives
git its own exec folder, whose `git-remote-http(s)` is `transport`: before git's
real transport starts, it drops curl tracing, and for
github.com refuses unless the App's helper is the last credential helper and no
extra header or URL credential could sign git in as someone else.

With OPENWIZ_TOKEN_SERVICE unset or empty, each command changes nothing and
prints nothing: run runs COMMAND exactly as today.
"""
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

SCHEMA = "openwiz.token-service.v1"
WRITE = {"metadata": "read", "contents": "write", "issues": "write",
         "pull_requests": "write", "checks": "read", "actions": "read"}
READ = {name: "read" for name in WRITE}
REFUSALS = {"usage": 2, "one-owner": 2, "not-installed": 3, "permission": 5,
            "github": 5, "expiry": 5, "unavailable": 1}
REFRESH_AT_S, MAX_LIFETIME_S, TIMEOUT_S = 300, 3900, 60
NOTE = "openwiz: no openwiz[bot] token ({}); using the owner's GitHub account\n"
WITHHELD = "openwiz: openwiz[bot] token withheld from git ({}); git stops rather than use another account\n"
REQUESTER = re.compile(r"[a-z][a-z0-9-]{0,63}")
REPOSITORY = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+")
TOKEN = re.compile(r"[A-Za-z0-9._~+/-]+=*")
REFUSAL_MESSAGE = re.compile(r"Token refused: [^\n]+\.")
GIT_HELPER_KEY = "credential.https://github.com.helper"
RUN_MARK, GIT_MARK = "OPENWIZ_AGENT_TOKEN_RUN", "OPENWIZ_AGENT_TOKEN_GIT_AT"
EXEC_MARK = "OPENWIZ_AGENT_TOKEN_EXEC_WAS"  # "0" unset, else "1" and the owner's GIT_EXEC_PATH
PATH_MARK = "OPENWIZ_AGENT_TOKEN_PATH_WAS"  # the same for the owner's PATH
# Inside a run git may reach github.com only over HTTPS, where the App signs in: ssh
# (the owner's key) runs a refusing command, and other transports such as ext:: are off.
ALLOWED_PROTOCOLS, SSH_STAND_IN = "file:https:ssh", "openwiz-ssh"
GUARDED = (("GIT_EXEC_PATH", EXEC_MARK), ("PATH", PATH_MARK),
           ("GIT_SSH_COMMAND", "OPENWIZ_AGENT_TOKEN_SSH_WAS"),
           ("GIT_ALLOW_PROTOCOL", "OPENWIZ_AGENT_TOKEN_PROTOCOLS_WAS"))
TRANSPORTS = ("git-remote-http", "git-remote-https")
CURL_TRACES = ("GIT_TRACE_CURL", "GIT_TRACE_CURL_NO_DATA", "GIT_CURL_VERBOSE")
USAGE = ("agent-token.py start REQUEST | run REQUEST -- COMMAND [ARG...]; "
         "REQUEST is --requester LABEL --repository OWNER/NAME... [--read]")


class Refused(Exception):
    """A local usage error: one line on stderr and exit 2, before any call."""


def needs_refresh(now, expires_at):
    """The contract's refresh rule: ask again at 300 seconds or less left."""
    return expires_at - now <= REFRESH_AT_S


def _no_repeats(pairs):
    if len({key for key, _ in pairs}) != len(pairs):
        raise ValueError("repeated key")
    return dict(pairs)


def _parse(raw):
    try:
        return json.loads(raw.decode("utf-8").strip(), object_pairs_hook=_no_repeats)
    except ValueError:
        return None


def ask(argv, request, env):
    """One service call: (None, answer) on exit 0, else (reason, None).

    The answer is read from a pipe and never echoed. The call's standard error
    is discarded, so no service or pairing text reaches the agent's terminal.
    """
    try:
        done = subprocess.run(argv, input=request, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, env=env, timeout=TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return "unreachable", None
    message = _parse(done.stdout)
    if done.returncode == 0:
        return None, message
    if (isinstance(message, dict) and set(message) == {"schema", "kind", "refusal", "message"}
            and message["schema"] == SCHEMA and message["kind"] == "refusal"
            and isinstance(message["refusal"], str)
            and REFUSALS.get(message["refusal"]) == done.returncode
            and isinstance(message["message"], str)
            and REFUSAL_MESSAGE.fullmatch(message["message"])):
        return message["refusal"], None
    return ("bad-answer" if isinstance(message, dict) else "unreachable"), None


def check_answer(message, wanted, now):
    """(token, expires_at), or None unless the answer is exactly the request's scope."""
    if not (isinstance(message, dict) and set(message) == {
            "schema", "kind", "token", "expires_at", "repositories", "permissions"}):
        return None
    expires_at = message["expires_at"]
    if (message["schema"] != SCHEMA or message["kind"] != "answer"
            or not isinstance(message["token"], str) or not TOKEN.fullmatch(message["token"])
            or type(expires_at) is not int
            or not REFRESH_AT_S < expires_at - now <= MAX_LIFETIME_S
            or message["repositories"] != wanted["repositories"]
            or message["permissions"] != wanted["permissions"]):
        return None
    return message["token"], expires_at


def route(env):
    """(None, argv) for the configured route, or (reason, None) when it is off or unusable."""
    service = env.get("OPENWIZ_TOKEN_SERVICE", "")
    if not service.startswith("/") or any(c in service for c in "'\n\r\0"):
        return "unreachable", None  # never run a path the quotes cannot hold
    if env.get("OPENWIZ_TOKEN_SERVICE_ROUTE") == "pairing":
        if env.get("OPENWIZ_TOKEN_SERVICE_READBACK") != "passed":
            return "pairing-off", None  # GA5's read-back gates the cloud route
        return None, ["room-cli", "mac", "run", "--stdin", f"python3 -I '{service}' mint"]
    if env.get("OPENWIZ_TOKEN_SERVICE_ROUTE") == "local":
        return None, ["python3", "-I", service, "mint"]
    return "unreachable", None


def mint(argv, wanted, env):
    """(None, token, expires_at) or (reason, None, None): one request, one checked answer."""
    request = json.dumps({"schema": SCHEMA, "kind": "request", **wanted}).encode() + b"\n"
    call_env = {k: v for k, v in env.items() if k != "GH_TOKEN"}
    now = int(time.time())
    reason, message = ask(argv, request, call_env)
    if reason:
        return reason, None, None
    got = check_answer(message, wanted, now)
    return ("bad-answer", None, None) if got is None else (None, *got)


def _outside_git(fd):
    try:
        os.stat(".git", dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise Refused("the private token directory must be outside every Git working tree")


class Private:
    """The 0700 directory, outside every Git working tree, that holds token files.

    It is reached one component at a time from `/`, each opened with O_NOFOLLOW
    relative to the last, and every check and file operation uses those held
    descriptors, so no swap of a path component can redirect a write. Every
    directory on the way is owned by root or the caller, and one that others can
    write to must be sticky, so no other user can move what it holds.
    """

    def __init__(self, env, create):
        raw = env.get("OPENWIZ_AGENT_TOKEN_DIR") or ""
        if not raw:
            runtime = env.get("XDG_RUNTIME_DIR", "")
            raw = (os.path.join(runtime, "openwiz-agent-token") if runtime.startswith("/")
                   else os.path.join(str(Path.home()), ".cache", "openwiz-agent-token"))
        if not os.path.isabs(raw):
            raise Refused("the private token directory must be an absolute path")
        self.path = os.path.normpath(raw)
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in [p for p in self.path.split("/") if p]:
                child = self._step(fd, part, create)
                os.close(fd)
                fd = child
            _outside_git(fd)
            info = os.fstat(fd)
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise Refused("the private token directory must be a 0700 directory you own")
        except BaseException:
            os.close(fd)
            raise
        self.fd = fd

    @staticmethod
    def _step(fd, part, create):
        """The descriptor of `part` inside `fd`, created 0700 when missing."""
        _outside_git(fd)
        above, me = os.fstat(fd), os.getuid()
        others = above.st_mode & 0o022  # a group, even the caller's own, can have other members
        if above.st_uid not in (0, me) or (others and not above.st_mode & stat.S_ISVTX):
            raise Refused("the private token directory must sit in folders only you or root can change")
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        try:
            try:
                child = os.open(part, flags, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                child = os.open(part, flags, dir_fd=fd)
        except OSError:
            raise Refused("the private token directory must be a real directory, through no symlink")
        if os.fstat(child).st_uid not in (0, me):
            os.close(child)
            raise Refused("the private token directory must sit in folders only you or root can change")
        return child

    def read(self, name):
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.fd)
        except OSError:
            return None
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
                return None
            return _parse(handle.read())

    def write(self, name, value):
        temporary = f".tmp-{secrets.token_hex(8)}"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600,
                     dir_fd=self.fd)
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(value, handle)
            os.replace(temporary, name, src_dir_fd=self.fd, dst_dir_fd=self.fd)
        except BaseException:
            self.unlink(temporary)
            raise

    def remove_folder(self, name):
        try:
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.fd)
        except FileNotFoundError:
            return
        try:
            for entry in os.listdir(fd):
                os.unlink(entry, dir_fd=fd)
        finally:
            os.close(fd)
        os.rmdir(name, dir_fd=self.fd)

    def unlink(self, name):
        try:
            os.unlink(name, dir_fd=self.fd)
        except FileNotFoundError:
            pass


def usable(held, now):
    """A token file's token, unless it is malformed or due for refresh."""
    if (isinstance(held, dict) and isinstance(held.get("token"), str)
            and TOKEN.fullmatch(held["token"]) and type(held.get("expires_at")) is int
            and not needs_refresh(now, held["expires_at"])):
        return held["token"]
    return None


def cache_name(wanted):
    """One cache file per requester and scope, so agents never share or replace each other's."""
    digest = hashlib.sha256(json.dumps(wanted, sort_keys=True).encode()).hexdigest()
    return f"token-{digest[:32]}.json"


def token_for(private, wanted, env):
    """(token, expires_at) to hand over, or (None, None) after the run's one fallback note."""
    name = cache_name(wanted)
    reason, argv = route(env)
    if not reason:
        held = private.read(name)
        if (usable(held, int(time.time())) and held.get("repositories") == wanted["repositories"]
                and held.get("permissions") == wanted["permissions"]):
            return held["token"], held["expires_at"]
        reason, token, expires_at = mint(argv, wanted, env)
    if reason:
        private.unlink(name)
        sys.stderr.write(NOTE.format(reason))
        return None, None
    private.write(name, {"token": token, "expires_at": expires_at, **wanted})
    return token, expires_at


def configured(env):
    return bool(env.get("OPENWIZ_TOKEN_SERVICE"))


def parse_request(args):
    """The request from --requester, --repository... and --read; the rest after `--`."""
    wanted = {"requester": None, "repositories": [], "permissions": WRITE}
    args = list(args)
    while args and args[0] != "--":
        flag = args.pop(0)
        if flag == "--read":
            wanted["permissions"] = READ
        elif flag in ("--requester", "--repository") and args:
            value = args.pop(0)
            if flag == "--requester":
                wanted["requester"] = value
            else:
                wanted["repositories"].append(value)
        else:
            raise Refused(f"usage: {USAGE}")
    if not (wanted["requester"] and REQUESTER.fullmatch(wanted["requester"])):
        raise Refused("--requester is a short lowercase label, such as builder-1844")
    repositories = wanted["repositories"]
    if (not repositories or len(set(map(str.lower, repositories))) != len(repositories)
            or not all(REPOSITORY.fullmatch(r) for r in repositories)
            or len({r.split("/")[0].lower() for r in repositories}) != 1):
        raise Refused("--repository is OWNER/NAME, at least one, each once, all of one owner")
    return wanted, args[1:] if args else None


def start(args, env):
    """Get the request's first token (or fall back), so the agent's first use is quick."""
    wanted, rest = parse_request(args)
    if rest is not None:
        raise Refused(f"usage: {USAGE}")
    if configured(env):
        token_for(Private(env, create=True), wanted, env)
    return 0


def without_inherited(env):
    """The environment with any App credential an outer run handed down removed."""
    child = dict(env)
    if RUN_MARK not in child:
        return child
    child.pop(RUN_MARK)
    child.pop("GH_TOKEN", None)
    for key, mark in GUARDED:
        was = child.pop(mark, "")
        if was.startswith("1"):
            child[key] = was[1:]
        elif was == "0":
            child.pop(key, None)
    first = child.pop(GIT_MARK, "")
    count = child.get("GIT_CONFIG_COUNT", "0")
    if first.isdigit() and count.isdigit():
        pairs = [(child.pop(f"GIT_CONFIG_KEY_{i}", ""), child.pop(f"GIT_CONFIG_VALUE_{i}", ""))
                 for i in range(int(count))]
        del pairs[int(first):int(first) + 2]
        for i, (key, value) in enumerate(pairs):
            child[f"GIT_CONFIG_KEY_{i}"], child[f"GIT_CONFIG_VALUE_{i}"] = key, value
        child["GIT_CONFIG_COUNT"] = str(len(pairs))
    return child


def git_helper(snapshot):
    """The one credential helper `run` gives git: it reads this run's snapshot only."""
    return (f"!exec {shlex.quote(sys.executable)} -I {shlex.quote(os.path.abspath(__file__))}"
            f" credential --snapshot {shlex.quote(snapshot)}")


def run(args, env):
    """Run COMMAND with this run's token in its own environment, or as the owner after the note."""
    wanted, command = parse_request(args)
    if not command:
        raise Refused(f"usage: {USAGE}")
    if not configured(env):
        return execute(command, env)
    private = Private(env, create=True)
    token, expires_at = token_for(private, wanted, env)
    child = without_inherited(env)
    if not token:
        return execute(command, child)
    name = f"run-{secrets.token_hex(16)}.json"
    snapshot = os.path.join(private.path, name)
    private.write(name, {"token": token, "expires_at": expires_at})
    farm = None
    try:
        farm = exec_folder(private, child)  # no guarded git, no App token: it refuses first
        for key, mark in GUARDED:
            child[mark] = "1" + child[key] if key in child else "0"
        child.update(guarded_env(os.path.join(private.path, farm), child))
        count = child.get("GIT_CONFIG_COUNT", "0") or "0"
        if not count.isdigit():
            raise Refused("GIT_CONFIG_COUNT must be a number")
        count = int(count)
        for offset, value in enumerate(("", git_helper(snapshot))):  # "" resets the list
            child[f"GIT_CONFIG_KEY_{count + offset}"] = GIT_HELPER_KEY
            child[f"GIT_CONFIG_VALUE_{count + offset}"] = value
        child.update({"GIT_CONFIG_COUNT": str(count + 2), "GH_TOKEN": token,
                      RUN_MARK: snapshot, GIT_MARK: str(count)})
        return execute(command, child, wait=True)
    finally:
        private.unlink(name)
        if farm:
            private.remove_folder(farm)


def guarded_env(folder, child):
    """The variables a run sets so git can only sign in to github.com as the App."""
    return {"GIT_EXEC_PATH": folder, "PATH": folder + os.pathsep + child.get("PATH", os.defpath),
            "GIT_SSH_COMMAND": shlex.quote(os.path.join(folder, SSH_STAND_IN)),
            "GIT_ALLOW_PROTOCOL": ALLOWED_PROTOCOLS}


def exec_folder(private, child):
    """The name of this run's git exec folder in the private directory, or Refused.

    It links every program of git's real exec folder, except git-remote-http(s),
    which run `transport` first, and `git` itself. The run puts the folder first on
    PATH, and its `git` refuses unless GIT_EXEC_PATH, GIT_SSH_COMMAND and
    GIT_ALLOW_PROTOCOL are still the run's and no `--exec-path=` overrides it, then
    starts the real git without GH_TOKEN, which only gh needs. Its `openwiz-ssh`,
    the run's GIT_SSH_COMMAND, refuses, since SSH has no App identity. So git can't
    run unguarded, sign in with the owner's SSH key or see the App token by accident.
    """
    real_git = shutil.which("git", path=child.get("PATH", os.defpath))
    try:
        real = subprocess.run([real_git or "git", "--exec-path"], env=child, capture_output=True,
                              text=True, timeout=10).stdout.strip() if real_git else ""
        names = os.listdir(real) if real.startswith("/") else []
    except (OSError, subprocess.SubprocessError):
        names = []
    if not names:
        raise Refused("cannot guard git's transport, so no openwiz[bot] token is handed over")
    name = f"exec-{secrets.token_hex(16)}"
    folder = os.path.join(private.path, name)
    note = WITHHELD.replace("{}", "%s").replace("\n", "\\n")
    scripts = {
        entry: f"exec {shlex.quote(sys.executable)} -I {shlex.quote(os.path.abspath(__file__))} "
               f"transport {shlex.quote(os.path.join(real, entry))} \"$@\"\n" for entry in TRANSPORTS}
    expected = guarded_env(folder, child)
    checks = "".join(
        f'if [ "${{{key}-}}" != {shlex.quote(expected[key])} ]; then\n  reason="{key} was changed"\nfi\n'
        for key in ("GIT_EXEC_PATH", "GIT_SSH_COMMAND", "GIT_ALLOW_PROTOCOL"))
    scripts[SSH_STAND_IN] = f'printf {shlex.quote(note)} "SSH has no openwiz[bot] identity" >&2\nexit 128\n'
    scripts["git"] = (
        f'reason=\n{checks}'
        f'for arg in "$@"; do\n  case $arg in --exec-path=*) reason="an --exec-path override";; esac\ndone\n'
        f'if [ -n "$reason" ]; then\n  printf {shlex.quote(note)} "$reason" >&2\n  exit 128\nfi\n'
        f'unset GH_TOKEN\nexec {shlex.quote(real_git)} "$@"\n')
    os.mkdir(name, 0o700, dir_fd=private.fd)
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=private.fd)
    try:
        for entry in {*names, *scripts}:
            if entry not in scripts:
                os.symlink(os.path.join(real, entry), entry, dir_fd=fd)
                continue
            script = os.open(entry, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o700, dir_fd=fd)
            with os.fdopen(script, "w") as handle:
                handle.write("#!/bin/sh\n" + scripts[entry])
    except BaseException:
        os.close(fd)
        private.remove_folder(name)
        raise
    os.close(fd)
    return name


def execute(command, env, wait=False):
    """Run COMMAND; with wait, stay to remove this run's snapshot after it ends."""
    try:
        if not wait:
            os.execvpe(command[0], command, env)
        child = subprocess.Popen(command, env=env)
    except OSError:
        raise Refused("cannot run the command")
    signal.signal(signal.SIGTERM, lambda number, frame: child.send_signal(number))
    while True:
        try:
            code = child.wait()
            return 128 - code if code < 0 else code
        except KeyboardInterrupt:
            continue  # the terminal's interrupt reached the command too


def config_problem(snapshot, env):
    """None when git, as configured right now, can sign in to github.com only through this
    run's helper: it is the last credential helper and no extra header is set. Else the reason."""
    try:
        listed = subprocess.run(["git", "config", "--list", "-z"], capture_output=True,
                                env=env, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return "cannot read git's configuration"
    if listed.returncode != 0:
        return "cannot read git's configuration"
    helpers = []
    for item in listed.stdout.split(b"\0"):
        key, _, value = item.decode("utf-8", "replace").partition("\n")
        key = key.lower()
        if key.startswith("http.") and key.endswith(".extraheader") and value:
            return "an extra HTTP header is set"
        if key.startswith("credential.") and key.endswith(".helper"):
            helpers.append((key, value))
    if helpers[-2:] != [(GIT_HELPER_KEY.lower(), ""), (GIT_HELPER_KEY.lower(), git_helper(snapshot))]:
        return "another credential helper follows or replaces it"
    return None


def only_git_transport(snapshot, env):
    """None inside git's own HTTPS transport with this run's helper last, else the reason."""
    try:
        parent = subprocess.run(["ps", "-o", "comm=", "-p", str(os.getppid())],
                                capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "cannot check the caller"
    # git-remote-https (truncated to 15 characters by ps on Linux) sends the answer
    # to github.com only; `git credential fill` would print it to its caller.
    if not os.path.basename(parent).startswith("git-remote-http"):
        return "not git's HTTPS transport"
    return config_problem(snapshot, env)


def transport(args, env):
    """git-remote-http(s) inside a run: no curl tracing, and for github.com no identity
    but the App's, checked before git's real transport can sign in."""
    if not args or not os.path.isabs(args[0]) or os.path.basename(args[0]) not in TRANSPORTS:
        raise Refused(f"usage: {USAGE}")
    real, rest = args[0], args[1:]
    for key in CURL_TRACES:  # git's only curl traces, which can show the Authorization header
        env.pop(key, None)
    url = urllib.parse.urlsplit(rest[-1] if len(rest) > 1 else "https://github.com")
    if RUN_MARK in env and (url.hostname or "").lower() == "github.com":
        reason = ("the URL holds a credential" if url.username or url.password
                  else config_problem(env[RUN_MARK], env))
        if reason:
            sys.stderr.write(WITHHELD.format(reason))
            return 128
    try:
        os.execve(real, [real, *rest], env)
    except OSError:
        raise Refused("cannot run git's transport")


def snapshot_token(snapshot, env):
    """(None, token) for git's own transport in this run, else (reason, None)."""
    try:
        private = Private(env, create=False)
    except Refused:
        return "no private directory", None
    name = os.path.basename(snapshot)
    if (snapshot != env.get(RUN_MARK) or os.path.dirname(snapshot) != private.path
            or not re.fullmatch(r"run-[0-9a-f]{32}\.json", name)):
        return "not this run's helper", None
    reason = only_git_transport(snapshot, env)
    if reason:
        return reason, None
    held = private.read(name)
    if (isinstance(held, dict) and isinstance(held.get("token"), str)
            and TOKEN.fullmatch(held["token"]) and type(held.get("expires_at")) is int
            and held["expires_at"] > time.time()):
        return None, held["token"]
    return "no current token", None


def credential(args, env):
    """git's credential helper: answer `get` for https://github.com from this run's snapshot.

    Inside a run git signs in as the App or not at all: when this helper cannot
    answer, it prints one note and answers `quit=1`, so git stops before any later
    helper can sign it in as someone else.
    """
    if len(args) != 3 or args[0] != "--snapshot" or args[2] != "get" or not configured(env):
        return 0
    fields = dict(line.split("=", 1) for line in sys.stdin.read().splitlines() if "=" in line)
    if fields.get("protocol") != "https" or fields.get("host") != "github.com":
        return 0
    reason, token = snapshot_token(args[1], env)
    if reason:
        sys.stderr.write(WITHHELD.format(reason))
        sys.stdout.write("quit=1\n")
    else:
        sys.stdout.write(f"username=x-access-token\npassword={token}\n")
    return 0


def main(argv):
    commands = {"start": start, "run": run, "credential": credential, "transport": transport}
    try:
        if not argv or argv[0] not in commands:
            raise Refused(f"usage: {USAGE}")
        return commands[argv[0]](list(argv[1:]), dict(os.environ))
    except Refused as error:
        sys.stderr.write(f"openwiz: agent-token: {error}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
