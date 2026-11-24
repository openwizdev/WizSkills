#!/usr/bin/env python3
import contextlib
import fcntl
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
REVOKE_MARK = "OPENWIZ_AGENT_TOKEN_REVOKE"
EXEC_MARK = "OPENWIZ_AGENT_TOKEN_EXEC_WAS"
PATH_MARK = "OPENWIZ_AGENT_TOKEN_PATH_WAS"
ALLOWED_PROTOCOLS, SSH_STAND_IN = "file:https:ssh", "openwiz-ssh"
GUARDED = (("GIT_EXEC_PATH", EXEC_MARK), ("PATH", PATH_MARK),
           ("GIT_SSH_COMMAND", "OPENWIZ_AGENT_TOKEN_SSH_WAS"),
           ("GIT_ALLOW_PROTOCOL", "OPENWIZ_AGENT_TOKEN_PROTOCOLS_WAS"),
           ("GH_CONFIG_DIR", "OPENWIZ_AGENT_TOKEN_GH_CONFIG_WAS"))
LEGACY_APP_KEY = "OPENWIZ_GITHUB_APP_KEY"
GH_ALLOWED = frozenset({"api", "cache", "issue", "label", "pr", "release", "repo", "run", "search",
                        "status", "workflow"})
GH_REFUSE = "openwiz-gh-child"
GH_WITHHELD = "openwiz: openwiz[bot] token withheld from gh ({}); gh stops rather than use another account\n"
TRANSPORTS = ("git-remote-http", "git-remote-https")
CURL_TRACES = ("GIT_TRACE_CURL", "GIT_TRACE_CURL_NO_DATA", "GIT_CURL_VERBOSE")
USAGE = ("agent-token.py start REQUEST | run REQUEST -- COMMAND [ARG...] | revoke REQUEST; "
         "REQUEST is --requester LABEL --repository OWNER/NAME... [--read]")


class Refused(Exception):
    pass


def needs_refresh(now, expires_at):
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
    service = env.get("OPENWIZ_TOKEN_SERVICE", "")
    if not service.startswith("/") or any(c in service for c in "'\n\r\0"):
        return "unreachable", None
    if env.get("OPENWIZ_TOKEN_SERVICE_ROUTE") == "pairing":
        if env.get("OPENWIZ_TOKEN_SERVICE_READBACK") != "passed":
            return "pairing-off", None
        return None, ["room-cli", "mac", "run", "--stdin", f"python3 -I '{service}' mint"]
    if env.get("OPENWIZ_TOKEN_SERVICE_ROUTE") == "local":
        return None, ["python3", "-I", service, "mint"]
    return "unreachable", None


def mint(argv, wanted, env):
    request = json.dumps({"schema": SCHEMA, "kind": "request", **wanted}).encode() + b"\n"
    call_env = {k: v for k, v in env.items() if k not in ("GH_TOKEN", LEGACY_APP_KEY)}
    reason, message = ask(argv, request, call_env)
    if reason:
        return reason, None, None
    got = check_answer(message, wanted, int(time.time()))
    return ("bad-answer", None, None) if got is None else (None, *got)


def _clear(fd):
    for entry in os.listdir(fd):
        if not stat.S_ISDIR(os.stat(entry, dir_fd=fd, follow_symlinks=False).st_mode):
            os.unlink(entry, dir_fd=fd)
            continue
        inner = os.open(entry, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        try:
            _clear(inner)
        finally:
            os.close(inner)
        os.rmdir(entry, dir_fd=fd)


def no_legacy_app_key(env):
    if any(name == LEGACY_APP_KEY for name in env):
        raise Refused(f"{LEGACY_APP_KEY} is set: remove the old App-key secret from this agent's "
                      "environment, since the token service holds the key")


def _outside_git(fd):
    try:
        os.stat(".git", dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise Refused("the private token directory must be outside every Git working tree")


class Private:

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
        _outside_git(fd)
        above, me = os.fstat(fd), os.getuid()
        others = above.st_mode & 0o022
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
            _clear(fd)
        finally:
            os.close(fd)
        os.rmdir(name, dir_fd=self.fd)

    def unlink(self, name):
        try:
            os.unlink(name, dir_fd=self.fd)
        except FileNotFoundError:
            pass


def usable(held, now):
    if (isinstance(held, dict) and isinstance(held.get("token"), str)
            and TOKEN.fullmatch(held["token"]) and type(held.get("expires_at")) is int
            and not needs_refresh(now, held["expires_at"])):
        return held["token"]
    return None


def cache_name(wanted):
    digest = hashlib.sha256(json.dumps(wanted, sort_keys=True).encode()).hexdigest()
    return f"token-{digest[:32]}.json"


def token_for(private, wanted, env, snapshot=None):
    name = cache_name(wanted)
    reason, argv = route(env)
    if not reason:
        with locked(private):
            held = private.read(name)
            if (usable(held, int(time.time())) and held.get("repositories") == wanted["repositories"]
                    and held.get("permissions") == wanted["permissions"]):
                if snapshot:
                    private.write(snapshot, {"token": held["token"], "expires_at": held["expires_at"],
                                             "request": name})
                return held["token"], held["expires_at"]
        reason, token, expires_at = mint(argv, wanted, env)
    stored = True
    with locked(private):
        if reason:
            retire(private, name)
        else:
            drop(private, name, name, retire=False)
            try:
                private.write(name, {"token": token, "expires_at": expires_at, **wanted})
                if snapshot:
                    private.write(snapshot, {"token": token, "expires_at": expires_at, "request": name})
            except OSError:
                stored = False
        kept = list(kept_tokens(private, name))
    base = revoke_base(env)
    if not stored:
        failed = revoke_held(None, base, token)
        raise Refused("the private token directory went away, so the new token "
                      + (f"was not revoked ({failed}): suspend the installation" if failed else "was revoked"))
    for held in kept:
        revoke_held(private, base, held)
    if reason:
        sys.stderr.write(NOTE.format(reason))
        return None, None
    return token, expires_at


def configured(env):
    return bool(env.get("OPENWIZ_TOKEN_SERVICE"))


def parse_request(args):
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
    wanted, rest = parse_request(args)
    if rest is not None:
        raise Refused(f"usage: {USAGE}")
    if configured(env):
        no_legacy_app_key(env)
        token_for(Private(env, create=True), wanted, env)
    return 0


def without_inherited(env):
    child = dict(env)
    if RUN_MARK not in child:
        return child
    child.pop(RUN_MARK)
    child.pop(REVOKE_MARK, None)
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
    return (f"!exec {shlex.quote(sys.executable)} -I {shlex.quote(os.path.abspath(__file__))}"
            f" credential --snapshot {shlex.quote(snapshot)}")


def run(args, env):
    wanted, command = parse_request(args)
    if not command:
        raise Refused(f"usage: {USAGE}")
    if not configured(env):
        return execute(command, env)
    no_legacy_app_key(env)
    close_channel(env)
    private = Private(env, create=True)
    name = f"run-{secrets.token_hex(16)}.json"
    token, expires_at = token_for(private, wanted, env, snapshot=name)
    child = without_inherited(env)
    if not token:
        return execute(command, child)
    snapshot = os.path.join(private.path, name)
    cache, held = cache_name(wanted), {"token": token, "expires_at": expires_at}
    farm = channel = None
    try:
        farm, real_gh = exec_folder(private, child)
        folder = os.path.join(private.path, farm)
        try:
            identity = gh_identity(real_gh) if real_gh else None
        except OSError:
            identity = None
        if identity:
            private.write(gh_binding(name), {"gh": real_gh, "refuse": os.path.join(folder, GH_REFUSE),
                                             "identity": identity})
        for key, mark in GUARDED:
            child[mark] = "1" + child[key] if key in child else "0"
        child.update(guarded_env(os.path.join(private.path, farm), child))
        count = child.get("GIT_CONFIG_COUNT", "0") or "0"
        if not count.isdigit():
            raise Refused("GIT_CONFIG_COUNT must be a number")
        count = int(count)
        for offset, value in enumerate(("", git_helper(snapshot))):
            child[f"GIT_CONFIG_KEY_{count + offset}"] = GIT_HELPER_KEY
            child[f"GIT_CONFIG_VALUE_{count + offset}"] = value
        child.pop("GH_TOKEN", None)
        channel = Channel(lambda request: run_revoke(private, env, cache, held, request))
        child.update({"GIT_CONFIG_COUNT": str(count + 2), RUN_MARK: snapshot, GIT_MARK: str(count),
                      REVOKE_MARK: str(channel.theirs.fileno())})
        return execute(command, child, wait=True, keep=channel.theirs.fileno())
    finally:
        if channel:
            channel.stop()
        with locked(private):
            retired = drop(private, name, cache, retire=False)
        if retired:
            revoke_held(private, revoke_base(env), retired)
        elif held["token"] and held["expires_at"] > time.time() and not os.fstat(private.fd).st_nlink:
            rescue(env, cache, held)
        private.unlink(gh_binding(name))
        if farm:
            private.remove_folder(farm)


def guarded_env(folder, child):
    return {"GIT_EXEC_PATH": folder, "PATH": folder + os.pathsep + child.get("PATH", os.defpath),
            "GIT_SSH_COMMAND": shlex.quote(os.path.join(folder, SSH_STAND_IN)),
            "GIT_ALLOW_PROTOCOL": ALLOWED_PROTOCOLS,
            "GH_CONFIG_DIR": os.path.join(folder, "gh-config")}


def exec_folder(private, child):
    real_git = shutil.which("git", path=child.get("PATH", os.defpath))
    real_gh = shutil.which("gh", path=child.get("PATH", os.defpath))
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
    if real_gh:
        scripts["gh"] = (f"exec {shlex.quote(sys.executable)} -I {shlex.quote(os.path.abspath(__file__))} "
                         f"gh {shlex.quote(os.path.abspath(real_gh))} "
                         f"{shlex.quote(os.path.join(folder, GH_REFUSE))} \"$@\"\n")
        gh_note = GH_WITHHELD.replace("{}", "%s").replace("\n", "\\n")
        scripts[GH_REFUSE] = f'printf {shlex.quote(gh_note)} "gh tried to start another program" >&2\nexit 1\n'
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
    return name, real_gh and os.path.abspath(real_gh)


def gh_identity(path):
    info = os.stat(path)
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022:
        return None
    identity = [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]
    if info.st_uid in (0, os.getuid()):
        return identity
    if not sys.platform.startswith("linux"):
        return None
    if not isinstance(path, int):
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY)
        try:
            return gh_identity(fd) if _root_only_path_to(path, os.fstat(fd)) else None
        finally:
            os.close(fd)
    try:
        if not _root_only_path_to(os.readlink(f"/proc/self/fd/{path}"), info):
            return None
        return identity + [_gh_bytes(path, None)]
    except OSError:
        return None


def _root_only_path_to(path, info):
    entry = owner_only_gh_path(path, uid=0)
    found = os.lstat(entry) if entry else None
    return bool(found) and (found.st_dev, found.st_ino) == (info.st_dev, info.st_ino)


def _gh_bytes(fd, copy):
    hashed, offset = hashlib.sha256(), 0
    while chunk := os.pread(fd, 1 << 20, offset):
        hashed.update(chunk)
        offset += len(chunk)
        while copy is not None and chunk:
            chunk = chunk[os.write(copy, chunk):]
    return hashed.hexdigest()


def sealed_gh(fd, digest):
    add_seals, get_seals = getattr(fcntl, "F_ADD_SEALS", 1033), getattr(fcntl, "F_GET_SEALS", 1034)
    seals = (getattr(fcntl, "F_SEAL_SHRINK", 2) | getattr(fcntl, "F_SEAL_GROW", 4)
             | getattr(fcntl, "F_SEAL_WRITE", 8) | getattr(fcntl, "F_SEAL_SEAL", 1))
    copy = os.memfd_create("openwiz-gh", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        _gh_bytes(fd, copy)
        fcntl.fcntl(copy, add_seals, seals)
        sealed = os.open(f"/proc/self/fd/{copy}", os.O_RDONLY)
    finally:
        os.close(copy)
    try:
        if fcntl.fcntl(sealed, get_seals) & seals == seals and _gh_bytes(sealed, None) == digest:
            return sealed
    except OSError:
        pass
    os.close(sealed)
    return None


def execute(command, env, wait=False, keep=None):
    try:
        if not wait:
            os.execvpe(command[0], command, env)
        child = subprocess.Popen(command, env=env, pass_fds=() if keep is None else (keep,))
    except OSError:
        raise Refused("cannot run the command")
    signal.signal(signal.SIGTERM, lambda number, frame: child.send_signal(number))
    while True:
        try:
            code = child.wait()
            return 128 - code if code < 0 else code
        except KeyboardInterrupt:
            continue


def config_problem(snapshot, env):
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
    try:
        parent = subprocess.run(["ps", "-o", "comm=", "-p", str(os.getppid())],
                                capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "cannot check the caller"
    if not os.path.basename(parent).startswith("git-remote-http"):
        return "not git's HTTPS transport"
    return config_problem(snapshot, env)


def transport(args, env):
    if not args or not os.path.isabs(args[0]) or os.path.basename(args[0]) not in TRANSPORTS:
        raise Refused(f"usage: {USAGE}")
    real, rest = args[0], args[1:]
    for key in CURL_TRACES:
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


def snapshot_token(snapshot, env, check=only_git_transport):
    try:
        private = Private(env, create=False)
    except Refused:
        return "no private directory", None
    name = os.path.basename(snapshot)
    if (snapshot != env.get(RUN_MARK) or os.path.dirname(snapshot) != private.path
            or not re.fullmatch(r"run-[0-9a-f]{32}\.json", name)):
        return "not this run's helper", None
    reason = check(snapshot, env)
    if reason:
        return reason, None
    held = private.read(name)
    if (isinstance(held, dict) and isinstance(held.get("token"), str)
            and TOKEN.fullmatch(held["token"]) and type(held.get("expires_at")) is int
            and held["expires_at"] > time.time()):
        return None, held["token"]
    return "no current token", None


def credential(args, env):
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


def gh_binding(snapshot_name):
    return "gh-" + snapshot_name[len("run-"):]


def bound_gh(real, refuse, env):
    snapshot = env.get(RUN_MARK, "")
    name = os.path.basename(snapshot)
    try:
        private = Private(env, create=False)
    except Refused:
        return "no private directory", None
    if os.path.dirname(snapshot) != private.path or not re.fullmatch(r"run-[0-9a-f]{32}\.json", name):
        return "not this run's gh", None
    bound = private.read(gh_binding(name))
    if not (isinstance(bound, dict) and bound.get("gh") == real and bound.get("refuse") == refuse):
        return "not the gh this run chose", None
    path = real if sys.platform.startswith("linux") else owner_only_gh_path(real)
    if path is None:
        return "this system cannot run the file it checked, and a folder above gh is not owner-only", None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY)
    except OSError:
        return "the gh this run chose cannot be opened to check", None
    try:
        current = gh_identity(fd)
    except OSError:
        current = None
    if current is None or current != bound.get("identity"):
        os.close(fd)
        return "the gh this run chose was changed", None
    if len(current) == 5:
        try:
            sealed = sealed_gh(fd, current[4])
        except OSError:
            sealed = None
        os.close(fd)
        if sealed is None:
            return "the gh this run chose was changed", None
        fd = sealed
    return None, (fd, path)


def owner_only_directory(info, uid):
    return stat.S_ISDIR(info.st_mode) and info.st_uid in (0, uid) and not info.st_mode & 0o022


def owner_only_gh_path(path, uid=None):
    if not path.startswith("/"):
        return None
    uid = os.getuid() if uid is None else uid
    folder = "/"
    remaining = path[1:]
    symlinks = 0
    try:
        if not owner_only_directory(os.lstat(folder), uid):
            return None
        while remaining:
            name, slash, remaining = remaining.partition("/")
            if name in ("", "."):
                continue
            if name == "..":
                folder = os.path.dirname(folder)
                continue
            entry = os.path.join(folder, name)
            info = os.lstat(entry)
            if stat.S_ISLNK(info.st_mode):
                symlinks += 1
                if symlinks > 40:
                    return None
                target = os.readlink(entry)
                if target.startswith("/"):
                    folder = "/"
                    target = target.lstrip("/")
                remaining = target + slash + remaining
            elif not slash:
                return entry
            elif owner_only_directory(info, uid):
                folder = entry
            else:
                return None
    except OSError:
        return None
    return None


def exec_gh(fd, path, args, env):
    sealed = False
    if sys.platform.startswith("linux"):
        os.set_inheritable(fd, True)
        path = f"/proc/self/fd/{fd}"
        sealed = os.readlink(path).startswith("/memfd:")
    try:
        os.execve(path, args, env)
    except OSError:
        if sealed:
            raise Refused("cannot run gh's sealed in-memory copy: this kernel or sandbox does not allow "
                          "executable memfds (vm.memfd_noexec, seccomp or a security module)") from None
        raise


def gh(args, env):
    if len(args) < 2:
        raise Refused(f"usage: {USAGE}")
    real, refuse, args = args[0], args[1], [args[0], *args[2:]]
    reason, checked = bound_gh(real, refuse, env)
    if reason:
        sys.stderr.write(GH_WITHHELD.format(reason))
        return 128
    fd, path = checked
    try:
        return gh_checked(fd, path, refuse, args, env)
    finally:
        os.close(fd)


def gh_checked(fd, path, refuse, args, env):
    if len(args) < 2 or args[1] not in GH_ALLOWED:
        sys.stderr.write(GH_WITHHELD.format("that gh command is not on the App's list"))
        return 128
    reason, token = snapshot_token(env.get(RUN_MARK, ""), env, check=lambda snapshot, env: None)
    if reason:
        sys.stderr.write(GH_WITHHELD.format(reason))
        return 128
    was = env.get("OPENWIZ_AGENT_TOKEN_GH_CONFIG_WAS", "")
    if was.startswith("1"):
        env["GH_CONFIG_DIR"] = was[1:]
    else:
        env.pop("GH_CONFIG_DIR", None)
    env.update({"GH_TOKEN": token, "GH_PAGER": "cat", "GH_EDITOR": shlex.quote(refuse),
                "GH_BROWSER": shlex.quote(refuse)})
    try:
        exec_gh(fd, path, args, env)
    except OSError:
        raise Refused("cannot run gh")


API_BASE = "https://api.github.com"
NOT_REVOKED = "openwiz: openwiz[bot] token not revoked ({}); the token is kept for a later revoke\n"
NO_TOKEN = "openwiz: openwiz[bot] token not revoked (no token found)\n"
SNAPSHOT = re.compile(r"run-[0-9a-f]{32}\.json")
REVOKE_REASONS = ("GitHub refused", "GitHub unreachable", "not the GitHub API", "no token found")


def revoke_base(env):
    base = env.get("OPENWIZ_GITHUB_API_BASE", API_BASE)
    if base == API_BASE:
        return base
    try:
        parts = urllib.parse.urlsplit(base)
        port = parts.port
    except ValueError:
        return None
    if (parts.scheme == "http" and port and parts.netloc == f"127.0.0.1:{port}"
            and not (parts.path or parts.query or parts.fragment)):
        return base
    return None


@contextlib.contextmanager
def locked(private):
    fcntl.flock(private.fd, fcntl.LOCK_EX)
    try:
        yield
    finally:
        fcntl.flock(private.fd, fcntl.LOCK_UN)


def token_of(held):
    if (isinstance(held, dict) and isinstance(held.get("token"), str)
            and TOKEN.fullmatch(held["token"]) and type(held.get("expires_at")) is int):
        return held["token"]
    return None


def live_token(held):
    return token_of(held) if token_of(held) and held["expires_at"] > time.time() else None


def listed(private):
    try:
        return sorted(os.listdir(private.fd))
    except OSError:
        return []


def holders(private, token):
    return [name for name in listed(private) if re.fullmatch(r"(token|kept|run)-[0-9a-f-]+\.json", name)
            and live_token(private.read(name)) == token]


def kept_name(cache):
    return f"kept-{cache[len('token-'):-len('.json')]}-{secrets.token_hex(16)}.json"


def drop(private, name, cache, retire):
    try:
        os.stat(name, dir_fd=private.fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    held = private.read(name)
    token = live_token(held)
    expired = token_of(held) and not token
    others = [found for found in holders(private, token) if found != name] if token else []
    if expired or any(found.startswith("kept-") for found in others) or (others and not retire):
        private.unlink(name)
        return None
    os.rename(name, kept_name(cache), src_dir_fd=private.fd, dst_dir_fd=private.fd)
    return token


def kept_tokens(private, cache):
    kept = re.compile(f"kept-{cache[len('token-'):-len('.json')]}-[0-9a-f]{{32}}\\.json")
    found = {}
    for name in filter(kept.fullmatch, listed(private)):
        held = private.read(name)
        if live_token(held):
            found.setdefault(held["token"], held["expires_at"])
    return found


def retire(private, cache):
    drop(private, cache, cache, retire=True)
    for name in listed(private):
        held = private.read(name) if SNAPSHOT.fullmatch(name) else None
        if isinstance(held, dict) and held.get("request") == cache:
            drop(private, name, cache, retire=True)


def keep(private, cache, token, expires_at):
    if any(name.startswith("kept-") for name in holders(private, token)):
        return False
    private.write(kept_name(cache), {"token": token, "expires_at": expires_at})
    return True


def revoke_held(private, base, token):
    reason = revoke_call(base, token) if base else "not the GitHub API"
    if not reason and private:
        with locked(private):
            for name in holders(private, token):
                private.unlink(name)
    return reason


def revoke_call(base, token):
    import urllib.error
    import urllib.request

    request = urllib.request.Request(base + "/installation/token", method="DELETE", headers={
        "Accept": "application/vnd.github+json", "Authorization": "Bearer " + token,
        "User-Agent": "OpenWiz-agent-token", "X-GitHub-Api-Version": "2022-11-28"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=TIMEOUT_S) as response:
            return None if response.status == 204 else "GitHub refused"
    except urllib.error.HTTPError:
        return "GitHub refused"
    except (OSError, ValueError):
        return "GitHub unreachable"


def revoke_request(private, base, cache, held=None):
    found = {}
    if private:
        with locked(private):
            retire(private, cache)
            if held:
                keep(private, cache, *held)
            found = kept_tokens(private, cache)
    if held:
        found.setdefault(*held)
    if not found:
        return "no token found"
    failed = None
    for token in found:
        failed = revoke_held(private, base, token) or failed
    return failed


def recovery(env):
    try:
        return Private(env, create=True)
    except (Refused, OSError):
        return None


def run_revoke(private, env, cache, held, request):
    if request != cache:
        return "other"
    base = revoke_base(env)
    if base is None:
        return "not the GitHub API"
    target = private if os.fstat(private.fd).st_nlink else recovery(env)
    live = (held["token"], held["expires_at"]) if held["token"] and held["expires_at"] > time.time() else None
    try:
        reason = revoke_request(target, base, cache, live)
    except OSError:
        reason = revoke_request(None, base, cache, live)
    finally:
        if target and target is not private:
            os.close(target.fd)
    if not reason:
        held["token"] = None
    return reason or "ok"


def rescue(env, cache, held):
    target, elsewhere = recovery(env), False
    if target:
        try:
            with locked(target):
                elsewhere = not keep(target, cache, held["token"], held["expires_at"])
        except OSError:
            pass
    if not elsewhere:
        revoke_held(target, revoke_base(env), held["token"])
    if target:
        os.close(target.fd)


class Channel:

    def __init__(self, serve):
        import socket
        import threading

        self.mine, self.theirs = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.theirs.set_inheritable(True)
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self.loop, args=(serve,), daemon=True)
        self.thread.start()

    def loop(self, serve):
        import socket

        while True:
            try:
                message, fds, _, _ = socket.recv_fds(self.mine, 1024, 1)
            except OSError:
                return
            if not fds:
                if self.stopping.is_set():
                    return
                continue
            try:
                reply = socket.socket(fileno=fds[0])
            except OSError:
                os.close(fds[0])
                continue
            with reply:
                try:
                    reply.sendall(serve(message.decode("ascii", "replace")).encode())
                except OSError:
                    pass

    def stop(self):
        self.stopping.set()
        self.theirs.send(b"")
        self.thread.join()
        self.mine.close()
        self.theirs.close()


def close_channel(env):
    raw = env.get(REVOKE_MARK, "")
    if RUN_MARK in env and raw.isdigit():
        try:
            if stat.S_ISSOCK(os.fstat(int(raw)).st_mode):
                os.close(int(raw))
        except (OSError, OverflowError):
            pass


def ask_run(env, cache):
    import socket

    raw = env.get(REVOKE_MARK, "")
    if RUN_MARK not in env or not raw.isdigit():
        return None
    try:
        channel = socket.socket(fileno=os.dup(int(raw)))
    except (OSError, OverflowError):
        return None
    with channel:
        if channel.family != socket.AF_UNIX or channel.type != socket.SOCK_DGRAM:
            return None
        mine, theirs = socket.socketpair()
        answer = b""
        with mine:
            try:
                with theirs:
                    socket.send_fds(channel, [cache.encode()], [theirs.fileno()])
                while chunk := mine.recv(1024):
                    answer += chunk
            except OSError:
                return None
    answer = answer.decode("ascii", "replace")
    return "" if answer == "ok" else answer if answer in REVOKE_REASONS else None


def revoke(args, env):
    wanted, rest = parse_request(args)
    if rest is not None:
        raise Refused(f"usage: {USAGE}")
    base = revoke_base(env)
    if base is None:
        sys.stderr.write(NOT_REVOKED.format("not the GitHub API"))
        return 1
    cache = cache_name(wanted)
    reason = ask_run(env, cache)
    if reason is None:
        try:
            private = Private(env, create=False)
        except Refused:
            private = None
        try:
            reason = revoke_request(private, base, cache)
        finally:
            if private:
                os.close(private.fd)
    if reason:
        sys.stderr.write(NO_TOKEN if reason == "no token found" else NOT_REVOKED.format(reason))
        return 1
    return 0


def main(argv):
    commands = {"start": start, "run": run, "credential": credential, "transport": transport, "gh": gh,
                "revoke": revoke}
    try:
        if not argv or argv[0] not in commands:
            raise Refused(f"usage: {USAGE}")
        environ = os.environ
        names = set(environ)
        if LEGACY_APP_KEY in names and "OPENWIZ_TOKEN_SERVICE" in names and environ["OPENWIZ_TOKEN_SERVICE"]:
            no_legacy_app_key(names)
        return commands[argv[0]](list(argv[1:]), dict(environ))
    except Refused as error:
        sys.stderr.write(f"openwiz: agent-token: {error}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
