#!/usr/bin/env python3
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
EXEC_MARK = "OPENWIZ_AGENT_TOKEN_EXEC_WAS"
PATH_MARK = "OPENWIZ_AGENT_TOKEN_PATH_WAS"
ALLOWED_PROTOCOLS, SSH_STAND_IN = "file:https:ssh", "openwiz-ssh"
GUARDED = (("GIT_EXEC_PATH", EXEC_MARK), ("PATH", PATH_MARK),
           ("GIT_SSH_COMMAND", "OPENWIZ_AGENT_TOKEN_SSH_WAS"),
           ("GIT_ALLOW_PROTOCOL", "OPENWIZ_AGENT_TOKEN_PROTOCOLS_WAS"))
TRANSPORTS = ("git-remote-http", "git-remote-https")
CURL_TRACES = ("GIT_TRACE_CURL", "GIT_TRACE_CURL_NO_DATA", "GIT_CURL_VERBOSE")
USAGE = ("agent-token.py start REQUEST | run REQUEST -- COMMAND [ARG...]; "
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
    if (isinstance(held, dict) and isinstance(held.get("token"), str)
            and TOKEN.fullmatch(held["token"]) and type(held.get("expires_at")) is int
            and not needs_refresh(now, held["expires_at"])):
        return held["token"]
    return None


def cache_name(wanted):
    digest = hashlib.sha256(json.dumps(wanted, sort_keys=True).encode()).hexdigest()
    return f"token-{digest[:32]}.json"


def token_for(private, wanted, env):
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
        token_for(Private(env, create=True), wanted, env)
    return 0


def without_inherited(env):
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
    return (f"!exec {shlex.quote(sys.executable)} -I {shlex.quote(os.path.abspath(__file__))}"
            f" credential --snapshot {shlex.quote(snapshot)}")


def run(args, env):
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
        farm = exec_folder(private, child)
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
        child.update({"GIT_CONFIG_COUNT": str(count + 2), "GH_TOKEN": token,
                      RUN_MARK: snapshot, GIT_MARK: str(count)})
        return execute(command, child, wait=True)
    finally:
        private.unlink(name)
        if farm:
            private.remove_folder(farm)


def guarded_env(folder, child):
    return {"GIT_EXEC_PATH": folder, "PATH": folder + os.pathsep + child.get("PATH", os.defpath),
            "GIT_SSH_COMMAND": shlex.quote(os.path.join(folder, SSH_STAND_IN)),
            "GIT_ALLOW_PROTOCOL": ALLOWED_PROTOCOLS}


def exec_folder(private, child):
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


def snapshot_token(snapshot, env):
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
