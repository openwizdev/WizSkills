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
die() { printf 'loop.sh: %s\n' "$*" >&2; exit 2; }
repository() {
  case $1 in
    */*/* | /* | */ | *[!A-Za-z0-9._/-]* | ./* | ../* | */. | */..) return 1 ;;
    ?*/?*) return 0 ;;
    *) return 1 ;;
  esac
}

spec_number() { case $1 in '' | 0* | *[!0-9]* | ??????????*) return 1 ;; esac; }

# Finite passes (#1456). `--pass STATE SECONDS -- COMMAND...` runs one bounded
# pass in the foreground and ends. A supervisor that is the Linux child
# subreaper of the command runs it under a deadline: every descendant, even one
# that starts a new session or closes the lock, stays its descendant, and all
# that are left when the command ends are killed and checked gone, so no
# detached child, watcher or sleep survives the pass. If that containment is
# unavailable or fails, the pass fails (exit 125 inside, exit 1 here). The lock is a kernel
# lock held by the pass's own processes: a stale or unrelated PID can never
# suppress work, a healthy concurrent pass is never duplicated, and a process
# that escaped its pass but still holds the lock is reported, not silent. Each
# pass keeps its output under its own id until its result is spooled; a pass
# whose runner died first is recovered, under the lock, by the next pass. A
# nonzero exit, a stopped deadline, an interrupted pass, a lock held past its
# deadline or a result that could not be saved makes this run exit 1. Every
# result stays pending, printed by every later run (a busy one too), until
# `--ack STATE RESULT` acknowledges it. STATE is private and absolute; SECONDS
# must stay below the scheduler's own limit for the script.
# The pass supervisor (#1456 R1). `run PIDS SECONDS COMMAND...`: run the
# command as the child subreaper's descendant, with the lock descriptor, under
# the deadline, recording itself and every descendant (with start times, so a
# reused PID is never touched) in PIDS several times a second. When the command
# ends, at the deadline or when TERM, INT or HUP reaches the supervisor, kill
# every descendant still alive, confirm none remains, then remove PIDS. Exit:
# the command's status (128+signal when killed or signalled), 124 at the
# deadline, 125 when containment fails (PIDS is then kept). `reap PIDS`: when the
# recorded supervisor is dead (SIGKILL or a crash), kill what it recorded and
# their descendants, print each reaped PID and remove PIDS. Exit 0 when it
# reaped any, 1 when there was nothing to reap, 125 when one survives.
supervise='
import ctypes, os, signal, subprocess, sys, time
def table():
    found = {}
    for name in os.listdir("/proc"):
        if name.isdigit():
            try:
                with open("/proc/%s/stat" % name) as stat:
                    fields = stat.read().rsplit(")", 1)[1].split()
                if fields[0] != "Z":
                    found[int(name)] = (int(fields[1]), fields[19])
            except (OSError, ValueError, IndexError):
                pass
    return found
def below(roots, procs):
    found, frontier = set(), set(roots)
    while frontier:
        frontier = {pid for pid, (parent, _) in procs.items() if parent in frontier and pid not in found}
        found |= frontier
    return found
def kill_until_gone(targets, reap=lambda: None):
    for _ in range(250):
        reap()
        left = targets()
        if not left:
            return True
        for pid in left:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        time.sleep(0.02)
    return False
mode, pids = sys.argv[1], sys.argv[2]
if mode == "reap":
    try:
        with open(pids) as record:
            lines = [line.split() for line in record if line.strip()]
    except FileNotFoundError:
        sys.exit(1)
    procs = table()
    (supervisor, born), recorded = lines[0], {int(pid): start for pid, start in lines[1:]}
    if procs.get(int(supervisor), (0, None))[1] == born:
        sys.exit(1)  # its supervisor still runs and cleans up itself
    def targets():
        procs = table()
        mine = {pid for pid, start in recorded.items() if procs.get(pid, (0, None))[1] == start}
        return mine | below(mine, procs)
    reaped = targets()
    if not kill_until_gone(targets):
        print("loop.sh: a recorded process outlived its reap", file=sys.stderr)
        sys.exit(125)
    os.remove(pids)
    print(" ".join(map(str, sorted(reaped))))
    sys.exit(0 if reaped else 1)
seconds, command = int(sys.argv[3]), sys.argv[4:]
try:
    if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0):  # PR_SET_CHILD_SUBREAPER
        raise OSError("prctl refused")
except (AttributeError, OSError) as error:
    print("loop.sh: no child subreaper: %s" % error, file=sys.stderr)
    sys.exit(125)
me = os.getpid()
stop = []
for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
    signal.signal(number, lambda number, frame: stop.append(number))
seen = {}
def record():
    procs = table()
    new = {pid: procs[pid][1] for pid in below({me}, procs) if pid not in seen}
    if new or not seen:
        seen.update(new)
        seen.setdefault(me, procs[me][1])
        with open(pids + ".new", "w") as out:
            out.write("%d %s\n" % (me, seen[me]))
            out.writelines("%d %s\n" % item for item in seen.items() if item[0] != me)
        os.replace(pids + ".new", pids)
def descendants():
    return below({me}, table())
def signal_all(number):
    for pid in descendants():
        try:
            os.kill(pid, number)
        except ProcessLookupError:
            pass
def reap():
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if not pid:
            return
record()
child = subprocess.Popen(command, pass_fds=(9,))
deadline = time.monotonic() + seconds
while True:
    record()
    code = child.poll()
    if code is not None:
        status = 128 - code if code < 0 else code
        break
    if stop:
        status = 128 + stop[0]
        break
    if time.monotonic() >= deadline:
        signal_all(signal.SIGTERM)
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        status = 124
        break
    time.sleep(0.05)
if not kill_until_gone(descendants, reap):
    print("loop.sh: descendants outlived the pass", file=sys.stderr)
    sys.exit(125)
os.remove(pids)
sys.exit(status)
'
now() { printf '%s\n' "${LAUNCH_FLEET_NOW:-$(date +%s)}"; }
pass_state() {
  case $1 in /*) ;; *) die 'the pass state must be an absolute path' ;; esac
  umask 077
  mkdir -p "$1/pending" "$1/acked" "$1/passes" || die "can't make the pass state"
}
spool() { # result id, file: once, unless already pending or acknowledged
  [ -e "$state/pending/$1" ] || [ -e "$state/acked/$1" ] && return 0
  cp "$2" "$state/pending/.$1" && mv "$state/pending/.$1" "$state/pending/$1" && return 0
  rm -f "$state/pending/.$1"
  return 1
}
note() { # result id, text
  printf '%s\n' "$2" > "$state/note" && spool "$1" "$state/note"
}
deliver() {
  for result in "$state"/pending/*; do
    [ -f "$result" ] || continue
    printf 'result %s:\n' "${result##*/}"
    cat "$result"
  done
}
recover() { # under the lock: every pass dir left behind is an unrecorded result
  rm -f "$state"/pending/.?* 2> /dev/null
  for pass in "$state"/passes/*; do
    [ -d "$pass" ] || continue
    if [ ! -e "$pass/finished" ]; then
      printf 'pass interrupted: its runner ended before recording the outcome\n' >> "$pass/out" || return 1
      : > "$pass/finished" || return 1
      failed=1
    fi
    if [ -s "$pass/out" ]; then spool "${pass##*/}" "$pass/out" || return 1; fi
    rm -rf "$pass" || return 1
  done
}
if [ "${1:-}" = --ack ]; then
  [ $# = 3 ] || die 'usage: loop.sh --ack STATE RESULT'
  case $3 in '' | .* | *[!A-Za-z0-9._-]*) die 'unknown result' ;; esac
  state=$2
  pass_state "$state"
  if [ -f "$state/pending/$3" ]; then
    : > "$state/acked/$3" && rm -f "$state/pending/$3" || die "can't acknowledge $3"
  elif [ ! -e "$state/acked/$3" ]; then
    die "no pending result $3"
  fi
  find "$state/acked" -type f -mtime +7 -exec rm -f {} + 2> /dev/null
  exit 0
fi
if [ "${1:-}" = --pass ]; then
  [ $# -ge 5 ] && [ "$4" = -- ] || die 'usage: loop.sh --pass STATE SECONDS -- COMMAND [ARG...]'
  case $3 in '' | 0* | *[!0-9]* | ??????*) die 'SECONDS must be 1 to 99999' ;; esac
  state=$2 seconds=$3
  shift 4
  command -v flock > /dev/null && command -v python3 > /dev/null || die 'needs flock and python3'
  pass_state "$state"
  exec 9>> "$state/lock" || die "can't open the pass lock"
  failed=0 reaped=
  # A dead supervisor's leftovers are reaped before anything runs, even while
  # one of them still holds the lock (#1456 R1).
  reap_dead() {
    gone=$(python3 -I -c "$supervise" reap "$state/pids") && reaped="$reaped $gone" && return 0
    [ $? = 125 ] && { note "unreaped-$(now)" 'pass containment failed: a process left by a dead pass could not be stopped, so no pass runs'; deliver; exit 1; }
    return 1
  }
  if ! flock -n 9 && ! { reap_dead && flock -w 3 9; }; then
    # Another process holds the lock: never run beside it, but deliver.
    holder() {
      read -r started id limit < "$state/started" 2> /dev/null || return 1
      case $started$limit in '' | *[!0-9]*) return 1 ;; esac
    }
    # A finishing or just-started holder writes or removes its mark within
    # moments; give it that bounded moment before calling the lock orphaned.
    if holder || ! flock -w 3 9; then
      status=0
      if holder; then
        age=$(($(now) - started))
        if [ "$age" -gt $((limit + 60)) ]; then
          note "overdue-$id" "pass overdue: running $age s, past its $limit-second deadline; its lock still holds the work"
          status=1
        fi
      else
        read -r last < "$state/last" 2> /dev/null || last=none
        note "orphan-after-$last" "pass lock held with no running pass: a process left from pass $last still holds it, so no pass runs"
        status=1
      fi
      deliver
      exit $status
    fi
  fi
  reap_dead
  if [ -n "$reaped" ]; then
    note "reaped-$(now)-$$" "pass reaped:$reaped (left by a pass whose supervisor died)" || die "can't record the reaped processes"
    failed=1
  fi
  id=$(now)-$$
  printf '%s %s %s\n' "$(now)" "$id" "$seconds" > "$state/started" || die "can't record the pass start"
  recover || { deliver; die "can't recover an earlier pass's result"; }
  pass=$state/passes/$id
  mkdir "$pass" || die "can't make the pass record"
  status=0
  python3 -I -c "$supervise" run "$state/pids" "$seconds" "$@" < /dev/null > "$pass/out" 2> "$pass/err" || status=$?
  case $status in
    0) ;;
    124) printf 'pass over deadline: stopped after %s s\n' "$seconds" >> "$pass/out" ;;
    125) printf 'pass containment failed: its processes could not all be stopped (see the pass record)\n' >> "$pass/out" ;;
    *) printf 'pass failed: exit %s (its stderr is kept with the pass record)\n' "$status" >> "$pass/out" ;;
  esac
  : > "$pass/finished"
  cp "$pass/err" "$state/err" 2> /dev/null
  if [ -s "$pass/out" ] && ! spool "$id" "$pass/out"; then
    echo "loop.sh: can't save the result of pass $id; it is kept for the next pass" >&2
    deliver
    exit 1
  fi
  rm -rf "$pass"
  printf '%s\n' "$id" > "$state/last"
  rm -f "$state/started"
  deliver
  [ "$status" = 0 ] && [ "$failed" = 0 ] || exit 1
  exit 0
fi

if [ "${1:-}" = --bundle ]; then
  [ $# = 2 ] || [ $# = 3 ] || die 'usage: loop.sh --bundle owner/name [spec]'
  repository "$2" || die 'GH_REPO must be owner/name'
  [ $# = 2 ] || spec_number "$3" || die "FLEET_SPEC must be a spec's number"
  source=$(cd -P "$(dirname "$0")/../.." && pwd) || die "can't find the installed skills"
  files='launch-fleet/scripts/loop.sh launch-fleet/scripts/fleet.sh launch-fleet/scripts/records.py plan-graph/revision.sh launch-fleet/scripts/carried/alarm.py'
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
runtime=$(mktemp -d) || { echo "loop.sh: can't unpack the bundled loop" >&2; exit 2; }
trap 'rm -rf "$runtime"' EXIT
trap 'exit 2' HUP INT TERM
mkdir -p "$runtime/skills/launch-fleet/scripts/carried" "$runtime/skills/plan-graph" || exit 2
OPENWIZ_BUNDLE_BOOTSTRAP
    for file in $files; do
      printf 'cat > "$runtime/skills/%s" <<%s || exit 2\n' "$file" "'OPENWIZ_BUNDLED_HELPER_EOF'"
      cat "$source/$file" || exit 2
      printf '\nOPENWIZ_BUNDLED_HELPER_EOF\n'
    done
    printf 'LAUNCH_FLEET_RUNTIME="$runtime/skills" sh "$runtime/skills/launch-fleet/scripts/loop.sh"\n'
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
if [ -z "${OPENWIZ_GITHUB_APP_KEY:-}" ]; then
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
LAUNCH_FLEET_REVISION=$scripts/plan-graph/revision.sh
export LAUNCH_FLEET_REVISION
# Refresh may have overlapped another observation. Recheck before the poll.
overload nonessential-poll
if [ -n "$FLEET_SPEC" ]; then exec sh "$scripts/launch-fleet/scripts/fleet.sh" spec "$FLEET_SPEC"; fi
exec sh "$scripts/launch-fleet/scripts/fleet.sh"
