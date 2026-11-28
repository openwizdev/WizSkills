#!/bin/sh
# The script of a project's launch-fleet loop (ClosedWiz#102). A loop's script
# runs in the loop's own sandbox, which lasts between runs. --bundle OWNER/REPO
# prints an uploadable script containing this runner and the installed fleet
# and revision helpers. It refreshes the consumer clone but runs those pinned
# helpers, so the consumer needs no skills/ and no plugin cache at runtime.
# Without --bundle, it runs the helpers installed beside it, never the clone's.
# A spec's fleet thread's loop (ClosedWiz#192) also sets FLEET_SPEC (or passes
# the spec's number after --bundle OWNER/REPO): then it runs that spec's check
# alone (`fleet.sh spec <FLEET_SPEC>`).
# Exit as the check exits; 2 when the clone can't be made or updated.
app_key_set=${OPENWIZ_GITHUB_APP_KEY+set}
unset OPENWIZ_GITHUB_APP_KEY
die() { printf 'loop.sh: %s\n' "$*" >&2; exit 2; }
repository() {
  case $1 in
    */*/* | /* | */ | *[!A-Za-z0-9._/-]* | ./* | ../* | */. | */..) return 1 ;;
    ?*/?*) return 0 ;;
    *) return 1 ;;
  esac
}

restore_today_account() {
  [ -n "${OPENWIZ_AGENT_TOKEN_RUN+x}${OPENWIZ_AGENT_TOKEN_GIT_AT+x}${OPENWIZ_AGENT_TOKEN_PATH_WAS+x}${OPENWIZ_AGENT_TOKEN_EXEC_WAS+x}${OPENWIZ_AGENT_TOKEN_SSH_WAS+x}${OPENWIZ_AGENT_TOKEN_PROTOCOLS_WAS+x}${OPENWIZ_AGENT_TOKEN_GH_CONFIG_WAS+x}" ] || return 0
  for restore_pair in PATH:PATH GIT_EXEC_PATH:EXEC GIT_SSH_COMMAND:SSH GIT_ALLOW_PROTOCOL:PROTOCOLS GH_CONFIG_DIR:GH_CONFIG; do
    restore_name=${restore_pair%%:*}
    restore_mark=OPENWIZ_AGENT_TOKEN_${restore_pair#*:}_WAS
    eval "restore_value=\${$restore_mark-}"
    unset "$restore_mark"
    case $restore_value in
      1*) eval "$restore_name=\${restore_value#1}"; export "$restore_name" ;;
      *) unset "$restore_name" ;;
    esac
  done
  restore_at=${OPENWIZ_AGENT_TOKEN_GIT_AT-}
  restore_count=${GIT_CONFIG_COUNT-}
  case $restore_at in '' | *[!0-9]* | 0?* | ??????????*) restore_at= ;; esac
  case $restore_count in '' | *[!0-9]* | 0?* | ??????????*) restore_count= ;; esac
  if [ -n "$restore_at" ] && [ -n "$restore_count" ] && [ "$restore_at" -le "$restore_count" ]; then
    while [ "$restore_count" -gt "$restore_at" ]; do
      restore_count=$((restore_count - 1))
      unset "GIT_CONFIG_KEY_$restore_count" "GIT_CONFIG_VALUE_$restore_count"
    done
    GIT_CONFIG_COUNT=$restore_at
    export GIT_CONFIG_COUNT
  else
    restore_nl=$(printf '\n_'); restore_nl=${restore_nl%_}
    restore_list=$(set +x; unset OPENWIZ_GITHUB_APP_KEY GH_TOKEN GITHUB_TOKEN; restore_list=$(set)
      while [ -n "$restore_list" ]; do
        restore_line=${restore_list%%"$restore_nl"*}
        case $restore_list in *"$restore_nl"*) restore_list=${restore_list#*"$restore_nl"} ;; *) restore_list= ;; esac
        case $restore_line in GIT_CONFIG_KEY_[0-9]*=* | GIT_CONFIG_VALUE_[0-9]*=*) restore_name=${restore_line%%=*} ;; *) continue ;; esac
        case ${restore_name#GIT_CONFIG_*_} in *[!0-9]*) ;; *) printf '%s\n' "$restore_name" ;; esac
      done)
    while [ -n "$restore_list" ]; do
      restore_name=${restore_list%%"$restore_nl"*}
      case $restore_list in *"$restore_nl"*) restore_list=${restore_list#*"$restore_nl"} ;; *) restore_list= ;; esac
      unset "$restore_name"
    done
    unset GIT_CONFIG_COUNT
  fi
  unset GH_TOKEN OPENWIZ_AGENT_TOKEN_RUN OPENWIZ_AGENT_TOKEN_GIT_AT restore_pair restore_name restore_mark restore_value restore_at restore_count restore_nl restore_list
}

spec_number() { case $1 in '' | 0* | *[!0-9]* | ??????????*) return 1 ;; esac; }

if [ "${1:-}" = --bundle ]; then
  [ $# = 2 ] || [ $# = 3 ] || die 'usage: loop.sh --bundle owner/name [spec]'
  repository "$2" || die 'GH_REPO must be owner/name'
  [ $# = 2 ] || spec_number "$3" || die "FLEET_SPEC must be a spec's number"
  source=$(cd -P "$(dirname "$0")/../.." && pwd) || die "can't find the installed skills"
  files='launch-fleet/scripts/loop.sh launch-fleet/scripts/fleet.sh launch-fleet/scripts/records.py launch-fleet/scripts/budget.py to-tickets/revision.sh to-tickets/check-links.sh launch-fleet/scripts/carried/alarm.py launch-fleet/scripts/github-app/agent-token.py setup/scripts/settings.py'
  for file in $files; do
    [ -r "$source/$file" ] || die "can't read installed $file"
    # The quoted heredoc must preserve every byte, without interpreting shell
    # substitutions in a helper. Refuse a delimiter collision before emitting.
    if grep -qx 'OPENWIZ_BUNDLED_HELPER_EOF' "$source/$file"; then die "heredoc delimiter in $file"; fi
  done
  bundle=$(mktemp) || die "can't stage the bundled loop"
  trap 'rm -f "$bundle"' EXIT
  trap 'exit 2' HUP INT TERM
  {
    printf '#!/bin/sh\nGH_REPO=%s\nexport GH_REPO\n' "$2"
    [ $# = 2 ] || printf 'FLEET_SPEC=%s\nexport FLEET_SPEC\n' "$3"
    cat <<'OPENWIZ_BUNDLE_BOOTSTRAP'
app_key=
[ -z "${OPENWIZ_GITHUB_APP_KEY+set}" ] || { unset OPENWIZ_GITHUB_APP_KEY; app_key=1; }
runtime=$(mktemp -d) || { echo "loop.sh: can't unpack the bundled loop" >&2; exit 2; }
trap 'rm -rf "$runtime"' EXIT
trap 'exit 2' HUP INT TERM
mkdir -p "$runtime/skills/launch-fleet/scripts/carried" "$runtime/skills/launch-fleet/scripts/github-app" \
  "$runtime/skills/to-tickets" "$runtime/skills/setup/scripts" || exit 2
OPENWIZ_BUNDLE_BOOTSTRAP
    for file in $files; do
      printf 'cat > "$runtime/skills/%s" <<%s || exit 2\n' "$file" "'OPENWIZ_BUNDLED_HELPER_EOF'"
      cat "$source/$file" || exit 2
      printf '\nOPENWIZ_BUNDLED_HELPER_EOF\n'
    done
    printf 'if [ -n "$app_key" ]; then OPENWIZ_GITHUB_APP_KEY= LAUNCH_FLEET_RUNTIME="$runtime/skills" sh "$runtime/skills/launch-fleet/scripts/loop.sh"\n'
    printf 'else LAUNCH_FLEET_RUNTIME="$runtime/skills" sh "$runtime/skills/launch-fleet/scripts/loop.sh"; fi\n'
  } > "$bundle" || die "can't bundle the installed helpers"
  cat "$bundle" || die "can't print the bundled loop"
  exit 0
fi
[ $# = 0 ] || die 'usage: loop.sh [--bundle owner/name [spec]]'
GH_REPO=${GH_REPO:-}
repository "$GH_REPO" || die "GH_REPO must be owner/name"
FLEET_SPEC=${FLEET_SPEC:-}
[ -z "$FLEET_SPEC" ] || spec_number "$FLEET_SPEC" || die "FLEET_SPEC must be a spec's number"
export GH_REPO
token_step() {
  step_py='
import hmac, json, os, pathlib, re, secrets, stat, sys

def open_private(create):
    raw = os.environ.get("OPENWIZ_AGENT_TOKEN_DIR") or ""
    if not raw:
        runtime = os.environ.get("XDG_RUNTIME_DIR", "")
        raw = (os.path.join(runtime, "openwiz-agent-token") if runtime.startswith("/")
               else os.path.join(str(pathlib.Path.home()), ".cache", "openwiz-agent-token"))
    if not os.path.isabs(raw):
        return None, None
    path = os.path.normpath(raw)
    me = os.getuid()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in [p for p in path.split("/") if p]:
            try:
                os.stat(".git", dir_fd=fd, follow_symlinks=False)
                return None, None
            except FileNotFoundError:
                pass
            above = os.fstat(fd)
            if above.st_uid not in (0, me) or ((above.st_mode & 0o022) and not (above.st_mode & stat.S_ISVTX)):
                return None, None
            try:
                child = os.open(part, flags, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    return None, None
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
            if os.fstat(fd).st_uid not in (0, me):
                return None, None
        try:
            os.stat(".git", dir_fd=fd, follow_symlinks=False)
            return None, None
        except FileNotFoundError:
            pass
        info = os.fstat(fd)
        if info.st_uid != me or (info.st_mode & 0o077):
            return None, None
        out, fd = fd, -1
        return out, path
    except OSError:
        return None, None
    finally:
        if fd >= 0:
            os.close(fd)

def no_repeats(pairs):
    if len({k for k, _ in pairs}) != len(pairs):
        raise ValueError("repeated key")
    return dict(pairs)

mode = sys.argv[1]
if mode == "verify":
    if not os.environ.get("OPENWIZ_TOKEN_SERVICE"):
        sys.exit(1)
    loop_pid, loop_ppid = int(sys.argv[2]), int(sys.argv[3])
    if loop_pid != os.getppid():
        sys.exit(1)
    m = re.fullmatch(r"([0-9a-f]{32}):([0-9a-f]{64})", os.environ.get("LAUNCH_FLEET_TOKEN_STEP", ""))
    if not m:
        sys.exit(1)
    step_id, nonce = m.groups()
    fd, priv = open_private(False)
    if fd is None:
        sys.exit(1)
    name = f"step-{step_id}.json"
    try:
        try:
            sfd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
        except OSError:
            sys.exit(1)
        with os.fdopen(sfd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or (info.st_mode & 0o077):
                sys.exit(1)
            raw = handle.read(4096)
        try:
            data = json.loads(raw.decode("utf-8"), object_pairs_hook=no_repeats)
        except (UnicodeDecodeError, ValueError):
            sys.exit(1)
        if (not isinstance(data, dict) or set(data) != {"pid", "nonce", "repo"}
                or type(data["pid"]) is not int
                or not isinstance(data["nonce"], str)
                or not isinstance(data["repo"], str)
                or not hmac.compare_digest(data["nonce"], nonce)):
            sys.exit(1)
        try:
            os.unlink(name, dir_fd=fd)
        except OSError:
            sys.exit(1)
        if data["repo"] != os.environ.get("GH_REPO"):
            sys.exit(1)
        run_mark = os.environ.get("OPENWIZ_AGENT_TOKEN_RUN", "")
        if run_mark:
            rname = os.path.basename(run_mark)
            if (data["pid"] != loop_ppid
                    or os.path.dirname(run_mark) != priv
                    or not re.fullmatch(r"run-[0-9a-f]{32}\.json", rname)):
                sys.exit(1)
            try:
                rfd = os.open(rname, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
            except OSError:
                sys.exit(1)
            try:
                rinfo = os.fstat(rfd)
                if not stat.S_ISREG(rinfo.st_mode) or rinfo.st_uid != os.getuid() or (rinfo.st_mode & 0o077):
                    sys.exit(1)
            finally:
                os.close(rfd)
        elif data["pid"] != loop_pid:
            sys.exit(1)
        sys.exit(0)
    finally:
        os.close(fd)
elif mode == "launch":
    helper, repo, script = sys.argv[2], sys.argv[3], sys.argv[4]
    fd, _ = open_private(True)
    if fd is None:
        sys.exit(2)
    step_id, nonce = secrets.token_hex(16), secrets.token_hex(32)
    name = f"step-{step_id}.json"
    try:
        sfd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        with os.fdopen(sfd, "w") as handle:
            json.dump({"pid": os.getpid(), "nonce": nonce, "repo": repo}, handle)
    except OSError:
        os.close(fd)
        sys.exit(2)
    os.close(fd)
    env = dict(os.environ)
    env["LAUNCH_FLEET_TOKEN_STEP"] = f"{step_id}:{nonce}"
    try:
        os.execve(sys.executable, [sys.executable, "-I", helper, "run", "--requester", "fleet-check", "--repository", repo, "--read", "--", "sh", script], env)
    except OSError:
        fd2, _ = open_private(False)
        if fd2 is not None:
            try:
                os.unlink(name, dir_fd=fd2)
            except OSError:
                pass
            os.close(fd2)
        sys.exit(2)
'
  if [ "$1" = launch ]; then
    exec python3 -I -c "$step_py" "$@"
  fi
  python3 -I -c "$step_py" "$@"
}
inside=
if [ -n "${LAUNCH_FLEET_TOKEN_STEP+set}" ] && token_step verify "$$" "$PPID"; then
  inside=1
fi
unset LAUNCH_FLEET_TOKEN_STEP
app_identity() {
  restore_today_account || return 1
  app_settings=$(gh api "repos/$GH_REPO/contents/docs/agents/fleet.md" 2> /dev/null < /dev/null) || return 1
  printf '%s' "$app_settings" \
    | python3 -I "${LAUNCH_FLEET_RUNTIME:-$(cd -P "$(dirname "$0")/../.." && pwd)}/setup/scripts/settings.py" app-identity \
      > /dev/null 2>&1
}
identity_off=
if [ -n "$inside" ]; then
  :
elif [ -z "${OPENWIZ_TOKEN_SERVICE:-}" ]; then
  if [ -n "$app_key_set" ]; then identity_off=1; fi
elif ! app_identity; then
  identity_off=1
fi
if [ -n "${OPENWIZ_TOKEN_SERVICE:-}" ] && [ -z "$inside" ] && [ -z "$identity_off" ]; then
  helper=$(cd -P "$(dirname "$0")" && pwd)/github-app/agent-token.py
  token_step launch "$helper" "$GH_REPO" "$0"
fi
if [ -n "$identity_off" ] || [ -z "$inside" ] || [ -z "${OPENWIZ_AGENT_TOKEN_RUN:-}" ]; then restore_today_account; fi
# The check reads GitHub as the OpenWiz App (GI7, #2549; the identity contract
# `openwiz.github-identity.v1`): with the loop's OPENWIZ_GITHUB_APP_KEY secret,
# `openwiz github token --read` mints a read-only installation token for gh
# (GH_TOKEN) and git (its credential helper reads GH_TOKEN from the
# environment). No token is stored, printed or passed as an argument. Without
# the secret, or when the mint fails, the check runs on today's account and
# says so on stderr, so it never stops for it.
# The check is told which identity reads (LAUNCH_FLEET_GITHUB_AUTH), so its
# unchanged probe asks what that identity can read; never an inherited value.
app=
unset LAUNCH_FLEET_GITHUB_AUTH
if [ -n "$identity_off" ]; then
  echo "loop.sh: the App identity is off; GitHub as today's account" >&2
elif [ -n "$inside" ]; then
  if [ -n "${OPENWIZ_AGENT_TOKEN_RUN:-}" ]; then
    LAUNCH_FLEET_GITHUB_AUTH=installation
    export LAUNCH_FLEET_GITHUB_AUTH
  fi
elif [ -z "$app_key_set" ]; then
  echo "loop.sh: no OPENWIZ_GITHUB_APP_KEY secret; GitHub as today's account" >&2
elif ! command -v openwiz > /dev/null; then
  echo "loop.sh: no openwiz to mint the App token; GitHub as today's account" >&2
elif app=$(openwiz github token --repository "$GH_REPO" --read 2> /dev/null < /dev/null) && [ -n "$app" ]; then
  GH_TOKEN=$app LAUNCH_FLEET_GITHUB_AUTH=installation
  export GH_TOKEN LAUNCH_FLEET_GITHUB_AUTH
  app=1
else
  app=
  echo "loop.sh: the App token mint failed; GitHub as today's account" >&2
fi
# Read GH_TOKEN from the environment only when the App token is in use.
git_() {
  if [ -n "$app" ]; then
    # shellcheck disable=SC2016 # the helper expands GH_TOKEN when git runs it
    git -c credential.helper= -c 'credential.helper=!f() { [ "$1" = get ] && printf "username=x-access-token\npassword=%s\n" "$GH_TOKEN"; }; f' "$@"
  else
    git "$@"
  fi
}
# Guard with the invoking installation (or pinned runtime), before touching
# the consumer checkout. Missing observations/state refuse; no ungated fallback.
# Both actions use the same repository-scoped durable state as merge admission.
guard_scripts=${LAUNCH_FLEET_RUNTIME:-$(cd -P "$(dirname "$0")/../.." && pwd)}
overload() {
  sh "$guard_scripts/launch-fleet/scripts/fleet.sh" overload "$1" > /dev/null \
    || die "overload refuses $1"
}
overload automatic-refresh
dir=${LAUNCH_FLEET_HOME:-$HOME/launch-fleet}/$GH_REPO
if [ -d "$dir/.git" ]; then
  git_ -C "$dir" fetch -q --depth 1 origin HEAD || die "can't fetch $GH_REPO"
  git -C "$dir" checkout -q --detach FETCH_HEAD || die "can't update the clone in $dir"
else
  mkdir -p "$(dirname "$dir")" || die "can't make $(dirname "$dir")"
  gh repo clone "$GH_REPO" "$dir" -- -q --depth 1 || die "can't clone $GH_REPO"
fi
# Always the invoking installation's (or the bundle's pinned) helpers: the
# consumer clone's skills/ is data to read, never code to run.
scripts=$guard_scripts
LAUNCH_FLEET_REVISION=$scripts/to-tickets/revision.sh
LAUNCH_FLEET_LINKS=$scripts/to-tickets/check-links.sh
export LAUNCH_FLEET_REVISION LAUNCH_FLEET_LINKS
# Refresh may have overlapped another observation. Recheck before the poll.
overload nonessential-poll
if [ -n "$FLEET_SPEC" ]; then exec sh "$scripts/launch-fleet/scripts/fleet.sh" spec "$FLEET_SPEC"; fi
exec sh "$scripts/launch-fleet/scripts/fleet.sh"
