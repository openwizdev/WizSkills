#!/bin/sh
# #384: a generated Loop must outlive its plugin install and work in a
# consumer with no skills/. All GitHub answers and git remotes are synthetic.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
FIX=$HERE/fixtures
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/bin" "$work/plugin cache/skills/launch-fleet/scripts/carried" \
  "$work/plugin cache/skills/to-tickets" "$work/remote" "$work/runtime"
cp "$HERE/loop.sh" "$HERE/fleet.sh" "$HERE/records.py" "$HERE/budget.py" "$work/plugin cache/skills/launch-fleet/scripts/"
cp "$HERE/../../to-tickets/revision.sh" "$HERE/../../to-tickets/check-links.sh" "$work/plugin cache/skills/to-tickets/"
cp "$HERE/carried/alarm.py" "$work/plugin cache/skills/launch-fleet/scripts/carried/"
mkdir "$work/plugin cache/skills/launch-fleet/scripts/github-app"
cp "$HERE/github-app/agent-token.py" "$work/plugin cache/skills/launch-fleet/scripts/github-app/"
mkdir -p "$work/plugin cache/skills/setup/scripts"
cp "$HERE/../../setup/scripts/settings.py" "$work/plugin cache/skills/setup/scripts/"
mkdir "$work/linked skills"
ln -s "$work/plugin cache/skills/launch-fleet" "$work/linked skills/launch-fleet"
# GI7 (#2549): the fake gh also records the token each call gets (synthetic).
printf '%s\n' 'import base64, json, sys' \
  'data = json.load(open(sys.argv[1]))["files"]["docs/agents/fleet.md"].encode()' \
  'text = base64.b64encode(data).decode()' \
  'body = "".join(text[n:n + 60] + "\n" for n in range(0, len(text), 60))' \
  'print(json.dumps({"type": "file", "encoding": "base64", "size": len(data), "content": body}))' > "$work/contents.py"
printf '#!/bin/sh\nif [ $# = 2 ] && [ "$1" = api ] && [ "$2" = repos/synthetic-owner/synthetic-repo/contents/docs/agents/fleet.md ]; then\n  printf "%%s %%s\\n" "${GH_TOKEN:-none}" "${LAUNCH_FLEET_GITHUB_AUTH:-account}" >> "%s"; echo read >> "%s"\n  exec "%s" -I "%s" "%s"\nfi\nprintf "%%s %%s\\n" "${GH_TOKEN:-none}" "${LAUNCH_FLEET_GITHUB_AUTH:-account}" >> "%s"\n[ -n "${OPENWIZ_GITHUB_APP_KEY+set}" ] && echo key >> "%s" || echo no-key >> "%s"\nexec "%s" -I -S "%s" "$@"\n' \
  "$work/read.log" "$work/order.log" "$(command -v python3)" "$work/contents.py" "$work/world.json" \
  "$work/gh-token.log" "$work/gh-key.log" "$work/gh-key.log" "$(command -v python3)" "$FIX/gh.py" > "$work/bin/gh"
chmod +x "$work/bin/gh"
export PATH="$work/bin:$PATH" GH_REPO=synthetic-owner/synthetic-repo
export FAKE_GH_REMOTE="$work/remote" FAKE_GH_WORLD="$work/world.json" FAKE_GH_LOG="$work/gh.log"
export LAUNCH_FLEET_HOME="$work/home" LAUNCH_FLEET_CACHE="$work/cache"
export LAUNCH_FLEET_NOW=1793534400 TMPDIR="$work/runtime"
unset GH_TOKEN GITHUB_TOKEN OPENWIZ_GITHUB_APP_KEY
# CS5 setup uses caller-normalized synthetic reads and durable repository state.
jq --argjson now "$LAUNCH_FLEET_NOW" '.observed_at = $now |
  .budgets[] |= (.reset_at = ($now + 3600))' \
  "$HERE/carried/healthy.json" > "$work/observation.json"
export LAUNCH_FLEET_OVERLOAD_INPUT="$work/observation.json"
export LAUNCH_FLEET_OVERLOAD_STATE="$work/pause.json"
unset LAUNCH_FLEET_REVISION
git -C "$work/remote" init -q
printf 'one\n' > "$work/remote/version"
git -C "$work/remote" add version
git -C "$work/remote" -c user.name=synthetic -c user.email=synthetic@example.invalid commit -qm one
jq '(.issues[] | select(.number == 12)) |= (.state = "CLOSED" | .comments += [
  {id: 1202, at: "2026-11-01T11:05:00Z", body: "launch-fleet: archived"}])
  | .pulls += [(.pulls[0] | .number = 22 | .closes = [12] | .mergedAt = "2026-11-01T11:00:00Z"
    | .files = [{filename: "src/store/store.rs", status: "modified"}])]' "$FIX/check.json" > "$work/world.json"
sh "$FIX/revision.sh" 10 > "$work/revision"
fingerprint=$(sha256sum < "$work/revision" | cut -d' ' -f1)
jq --arg fp "$fingerprint" '(.issues[].comments[]?.body) |= gsub("@@FP@@"; $fp)' \
  "$work/world.json" > "$work/approved.json"
mv "$work/approved.json" "$work/world.json"

# This is the setup command's public seam. The uploaded file must carry all
# three scripts; neither the install nor the consumer provides them at run time.
python3 - "$HERE/../references/launch.md" "$work/linked skills/launch-fleet" "$work/loop.sh" <<'PY'
import pathlib
import subprocess
import sys
import textwrap

text = pathlib.Path(sys.argv[1]).read_text()
setup = text.split("## Launch", 1)[1].split("```sh\n", 1)[1]
setup = textwrap.dedent(setup.split('   room-cli loop create --name', 1)[0])
setup = setup.replace("<this skill's folder>", sys.argv[2])
setup = setup.replace("<owner>/<repo>", "synthetic-owner/synthetic-repo")
setup = setup.replace("/tmp/launch-fleet-loop.sh", sys.argv[3])
subprocess.run(["sh", "-c", setup], check=True)
PY
sh -n "$work/loop.sh"
mkdir "$work/gen-probe"
for tool in dirname mktemp grep cat rm; do
  printf '#!/bin/sh\n[ -n "${OPENWIZ_GITHUB_APP_KEY+set}" ] && echo "%s key" >> "%s" || echo "%s no-key" >> "%s"\nexec %s "$@"\n' \
    "$tool" "$work/gen-probe.log" "$tool" "$work/gen-probe.log" "$(command -v "$tool")" > "$work/gen-probe/$tool"
  chmod +x "$work/gen-probe/$tool"
done
(export OPENWIZ_GITHUB_APP_KEY=synthetic-key-sentinel-2843 PATH="$work/gen-probe:$PATH"
  sh "$work/linked skills/launch-fleet/scripts/loop.sh" --bundle synthetic-owner/synthetic-repo > "$work/loop-key.sh")
cmp "$work/loop.sh" "$work/loop-key.sh"
if grep -v ' no-key$' "$work/gen-probe.log"; then echo 'the generator handed the key to a child' >&2; exit 1; fi
for tool in dirname mktemp grep cat rm; do
  if ! grep -qx "$tool no-key" "$work/gen-probe.log"; then echo "unprobed: $tool" >&2; exit 1; fi
done
echo 'ok   generating the bundle with the key set hands it to no child (#2843)'
rm -rf "$work/plugin cache"
cd "$work"
printf 'start #13: W3: widget page (spec #10)\n' > "$work/want"
fallback="loop.sh: no OPENWIZ_GITHUB_APP_KEY secret; GitHub as today's account"
run() {
  if sh "$work/loop.sh" > "$work/out" 2> "$work/err"; then :
  else cat "$work/err" >&2; return 1; fi
  cmp "$work/want" "$work/out"
  [ "$(grep -c '^fleet.sh: used ' "$work/err")" = 1 ]
  [ "$(head -n 1 "$work/err")" = "$fallback" ]
  [ "$(wc -l < "$work/err" | tr -d ' ')" = 2 ]
  grep -qx 'issue view 10 subIssues' "$work/gh.log"
  [ -z "$(ls -A "$work/runtime")" ]
}
run
[ ! -e "$LAUNCH_FLEET_HOME/$GH_REPO/skills" ]
grep -qx 'repo clone' "$work/gh.log"
echo 'ok   bundled loop runs the packaged fleet and revision in a plain consumer'

# The consumer still refreshes. Its later skills must not replace the bundle.
printf 'two\n' > "$work/remote/version"
mkdir -p "$work/remote/skills/launch-fleet/scripts" "$work/remote/skills/to-tickets"
printf 'exit 99\n' > "$work/remote/skills/launch-fleet/scripts/fleet.sh"
printf 'exit 99\n' > "$work/remote/skills/to-tickets/revision.sh"
git -C "$work/remote" add -A
git -C "$work/remote" -c user.name=synthetic -c user.email=synthetic@example.invalid commit -qm two
rm -rf "$work/cache"
: > "$work/gh.log"
run
[ "$(cat "$LAUNCH_FLEET_HOME/$GH_REPO/version")" = two ]
! grep -q 'repo clone' "$work/gh.log"
echo 'ok   later runs refresh the consumer while keeping the packaged helpers'

# E6: the installed loop.sh run directly (no bundle) uses its own installed
# fleet and revision helpers, never the consumer clone's hostile skills/.
mkdir -p "$work/installed/skills/launch-fleet/scripts/carried" "$work/installed/skills/to-tickets"
cp "$HERE/loop.sh" "$HERE/fleet.sh" "$HERE/records.py" "$HERE/budget.py" "$work/installed/skills/launch-fleet/scripts/"
cp "$HERE/../../to-tickets/revision.sh" "$HERE/../../to-tickets/check-links.sh" "$work/installed/skills/to-tickets/"
cp "$HERE/carried/alarm.py" "$work/installed/skills/launch-fleet/scripts/carried/"
mkdir "$work/installed/skills/launch-fleet/scripts/github-app"
cp "$HERE/github-app/agent-token.py" "$work/installed/skills/launch-fleet/scripts/github-app/"
mkdir -p "$work/installed/skills/setup/scripts"
cp "$HERE/../../setup/scripts/settings.py" "$work/installed/skills/setup/scripts/"
rm -rf "$work/cache"
status=0
sh "$work/installed/skills/launch-fleet/scripts/loop.sh" > "$work/out" 2> "$work/err" || status=$?
[ "$status" = 0 ] || { cat "$work/err" >&2; exit 1; }
cmp "$work/want" "$work/out"
[ -z "$(ls -A "$work/runtime")" ]
echo 'ok   a direct installed loop runs its installed helpers, not the consumer skills/'

off="loop.sh: the App identity is off; GitHub as today's account"
token=synthetic-app-token-2549
{
  printf '#!/bin/sh\nprintf "%%s\\n" "$*" >> "%s"\necho mint >> "%s"\n' "$work/openwiz.log" "$work/order.log"
  printf '[ "${FAKE_OPENWIZ_FAIL:-}" = 1 ] && { echo "openwiz: github token: refused" >&2; exit 5; }\n'
  printf 'printf "%%s\\n" %s\necho "expires_at 1793538000" >&2\n' "$token"
} > "$work/bin/openwiz"
chmod +x "$work/bin/openwiz"
identity() { # "token identity" every gh call gets; the stderr line expected, or ''
  rm -rf "$work/cache"
  : > "$work/gh-token.log"
  : > "$work/openwiz.log"
  sh "$work/loop.sh" > "$work/out" 2> "$work/err" || { cat "$work/err" >&2; return 1; }
  cmp "$work/want" "$work/out"
  [ -s "$work/gh-token.log" ]
  [ -z "$(grep -vx "$1" "$work/gh-token.log")" ]
  [ "$(grep -c '^fleet.sh: used ' "$work/err")" = 1 ]
  lines=1
  [ -z "$2" ] || { grep -qxF "$2" "$work/err"; lines=2; }
  [ "$(wc -l < "$work/err" | tr -d ' ')" = "$lines" ]
  ! grep -q "$token" "$work/out" "$work/err" "$work/openwiz.log"
}
(OPENWIZ_GITHUB_APP_KEY=c3ludGhldGlj identity 'none account' "$off")
[ ! -s "$work/openwiz.log" ]
echo "ok   with the key secret and no token service the check runs on today's account, never mints (#2394, #2835)"
cp "$work/world.json" "$work/world-off.json"
jq '.files["docs/agents/fleet.md"] |= (sub("\\| App \\| Synthetic, for the factory \\|\n"; "") + "| App identity | on |\n")' \
  "$work/world-off.json" > "$work/world-on.json"
cp "$work/world-on.json" "$work/world.json"
(: > "$work/read.log"; : > "$work/order.log"; OPENWIZ_GITHUB_APP_KEY=c3ludGhldGlj identity 'none account' "$off")
[ ! -s "$work/openwiz.log" ]
echo "ok   with the App identity on and no token service, loop.sh falls back with its note and never runs openwiz (catches: attempting openwiz github token with key unset, #2835)"
cp "$work/world-off.json" "$work/world.json"
(LAUNCH_FLEET_GITHUB_AUTH=installation identity 'none account' "$fallback")
[ ! -s "$work/openwiz.log" ]
(OPENWIZ_GITHUB_APP_KEY=c3ludGhldGlj FAKE_OPENWIZ_FAIL=1 identity 'none account' "$off")
[ ! -s "$work/openwiz.log" ]
rm "$work/bin/openwiz"
# The fake gh stays first; no installed openwiz is in these system folders.
(PATH="$work/bin:/usr/bin:/bin" OPENWIZ_GITHUB_APP_KEY=c3ludGhldGlj identity 'none account' "$off")
echo "ok   without the secret, openwiz or a token, the check runs as today's account and says so (#2549)"

ga4=synthetic-ga4-token-0123456789
mkdir -m 700 "$work/token-private"
service() {
  export OPENWIZ_TOKEN_SERVICE="$FIX/token_service.py" OPENWIZ_TOKEN_SERVICE_ROUTE=local \
    OPENWIZ_AGENT_TOKEN_DIR="$work/token-private" FAKE_SERVICE_LOG="$work/service.log" \
    OPENWIZ_GITHUB_APP_KEY=c3ludGhldGlj
  : > "$work/service.log"
  rm -f "$work/token-private/"*
}
(service; : > "$work/gh-key.log"; identity 'none account' "$off")
[ -s "$work/gh-key.log" ] && [ -z "$(grep -vx no-key "$work/gh-key.log")" ]
[ ! -s "$work/service.log" ]
! grep -q "$ga4" "$work/out" "$work/err" "$work/gh.log"
echo "ok   with a token service and no App identity row the wake never runs the helper and reads GitHub as today's account (#2394)"
printf '%s\n' 'import runpy, sys' "open('$work/order.log', 'a').write('helper\\n')" \
  "runpy.run_path('$FIX/token_service.py', run_name='__main__')" > "$work/service-order.py"
cp "$work/world-on.json" "$work/world.json"
(service; export OPENWIZ_TOKEN_SERVICE="$work/service-order.py"; : > "$work/gh-key.log"; : > "$work/read.log"; : > "$work/order.log"
  identity "$ga4 installation" ''
  [ "$(cat "$work/read.log")" = 'none account' ]
  [ "$(cat "$work/order.log")" = "$(printf 'read\nhelper')" ])
[ "$(jq -c .legacy_key "$work/service.log")" = false ]
[ "$(jq -c .request "$work/service.log")" = '{"schema":"openwiz.token-service.v1","kind":"request","requester":"fleet-check","repositories":["synthetic-owner/synthetic-repo"],"permissions":{"metadata":"read","contents":"read","issues":"read","pull_requests":"read","checks":"read","actions":"read"}}' ]
[ "$(jq -c .argv "$work/service.log")" = '["mint"]' ]
! grep -q "$ga4" "$work/out" "$work/err" "$work/gh.log"
[ -z "$(find "$work/token-private" -name 'step-*.json')" ]
cp "$work/world-off.json" "$work/world.json"
echo "ok   with the App identity on and a token service, one account read of fleet.md, then one read-only helper run; its bound continuation reads GitHub as the installation (#1846, #2835, #2869)"
mkdir "$work/probe"
for tool in mktemp mkdir cat; do
  printf '#!/bin/sh\n[ -n "${OPENWIZ_GITHUB_APP_KEY+set}" ] && echo key >> "%s" || echo no-key >> "%s"\nexec %s "$@"\n' \
    "$work/probe.log" "$work/probe.log" "$(command -v "$tool")" > "$work/probe/$tool"
  chmod +x "$work/probe/$tool"
done
(service; export PATH="$work/probe:$PATH"; : > "$work/probe.log"; identity 'none account' "$off")
[ -s "$work/probe.log" ] && [ -z "$(grep -vx no-key "$work/probe.log")" ]
echo 'ok   with a token service no bundled bootstrap command gets the legacy key (#1846)'
(service; export LAUNCH_FLEET_TOKEN_STEP=1; identity 'none account' "$off")
[ ! -s "$work/service.log" ]
echo 'ok   an inherited step marker never turns the App identity on (#1846, #2394)'
(service; : > "$work/gh-key.log"; export FAKE_SERVICE_REFUSE=1; identity 'none account' "$off")
[ -s "$work/gh-key.log" ] && [ -z "$(grep -vx no-key "$work/gh-key.log")" ]
[ ! -s "$work/service.log" ]
[ -z "$(ls -A "$work/token-private")" ]
echo "ok   a service that would refuse is never asked (#1846, #2394)"
(service; export OPENWIZ_TOKEN_SERVICE= PATH="$work/probe:$work/bin:/usr/bin:/bin"; : > "$work/probe.log"
  identity 'none account' "$off")
[ ! -s "$work/service.log" ]
[ -s "$work/probe.log" ]
[ -z "$(grep -vx no-key "$work/probe.log")" ]
echo 'ok   with no service configured the wake drops the key and still never mints (#1846, #2394, #2843)'

absent() {
  if grep -q "$@"; then echo "found: $*" >&2; return 1; fi
}
sentinel=synthetic-key-sentinel-2843
(export OPENWIZ_GITHUB_APP_KEY="$sentinel" PATH="$work/probe:$PATH"; : > "$work/probe.log"; : > "$work/gh-key.log"
  for script in "$work/loop.sh" "$work/installed/skills/launch-fleet/scripts/loop.sh"; do
    rm -rf "$work/cache"
    sh -x "$script" > "$work/out" 2> "$work/trace" || { cat "$work/trace" >&2; exit 1; }
    cmp "$work/want" "$work/out"
    grep -q '^+ ' "$work/trace"
    grep -qxF "$off" "$work/trace"
    absent -F "$sentinel" "$work/trace"
  done
  [ -s "$work/probe.log" ]
  [ -z "$(grep -vx no-key "$work/probe.log")" ]
  [ -s "$work/gh-key.log" ]
  [ -z "$(grep -vx no-key "$work/gh-key.log")" ])
echo "ok   the off decision never expands the key and no child gets it (#2843)"

mkdir "$work/shim" "$work/was"
for tool in gh git; do
  printf '#!/bin/sh\necho %s >> "%s"\nexec "%s" "$@"\n' "$tool" "$work/shim.log" "$(command -v "$tool")" > "$work/shim/$tool"
  chmod +x "$work/shim/$tool"
done
printf '#!/bin/sh\nenv | grep -E "^(GIT_CONFIG|GIT_EXEC_PATH=|GIT_SSH|GIT_ALLOW_PROTOCOL=|GH_CONFIG_DIR=|GH_TOKEN=|OPENWIZ_AGENT_TOKEN_(RUN|GIT_AT|[A-Z_]*_WAS)=)" >> "%s"\nexec "%s" "$@"\n' \
  "$work/git-env.log" "$(command -v git)" > "$work/was/git"
chmod +x "$work/was/git"
printf '%s\n' "GH_CONFIG_DIR=$work/gh-config-was" GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=synthetic.kept \
  GIT_CONFIG_VALUE_0=yes > "$work/git-env.want"
inherit() {
  export PATH="$work/shim:$work/was:$PATH" OPENWIZ_AGENT_TOKEN_PATH_WAS="1$work/was:$PATH" \
    GIT_EXEC_PATH="$(git --exec-path)" OPENWIZ_AGENT_TOKEN_EXEC_WAS=0 \
    GIT_SSH_COMMAND="$work/shim/git" OPENWIZ_AGENT_TOKEN_SSH_WAS=0 \
    GIT_ALLOW_PROTOCOL=file:https:ssh OPENWIZ_AGENT_TOKEN_PROTOCOLS_WAS=0 \
    GH_CONFIG_DIR="$work/shim/gh-config" OPENWIZ_AGENT_TOKEN_GH_CONFIG_WAS="1$work/gh-config-was" \
    GIT_CONFIG_COUNT=3 GIT_CONFIG_KEY_0=synthetic.kept GIT_CONFIG_VALUE_0=yes \
    GIT_CONFIG_KEY_1=credential.https://github.com.helper GIT_CONFIG_VALUE_1= \
    GIT_CONFIG_KEY_2=credential.https://github.com.helper GIT_CONFIG_VALUE_2="!$work/shim/git" \
    OPENWIZ_AGENT_TOKEN_RUN="$work/shim/run-synthetic.json" OPENWIZ_AGENT_TOKEN_GIT_AT=1 \
    GH_TOKEN=synthetic-installation-token-2843
  : > "$work/shim.log"; : > "$work/git-env.log"; : > "$work/gh-token.log"
}
dropped() {
  [ ! -s "$work/shim.log" ]
  [ -s "$work/git-env.log" ]
  sort -u "$work/git-env.log" | cmp - "$work/git-env.want"
  [ -s "$work/gh-token.log" ]
  [ -z "$(grep -vx 'none account' "$work/gh-token.log")" ]
}
for marker in '$$' ''; do
  (line=$fallback; if [ -n "$marker" ]; then service; line=$off; fi; inherit; rm -rf "$work/cache"
    sh -c "LAUNCH_FLEET_TOKEN_STEP=$marker; export LAUNCH_FLEET_TOKEN_STEP; exec sh \"\$1\"" sh "$work/loop.sh" \
      > "$work/out" 2> "$work/err" || { cat "$work/err" >&2; exit 1; }
    cmp "$work/want" "$work/out"
    [ "$(head -n 1 "$work/err")" = "$line" ]
    [ "$(wc -l < "$work/err" | tr -d ' ')" = 2 ]
    dropped
    [ ! -s "$work/service.log" ])
done
echo "ok   a matching step marker with inherited shims runs every command as today's account (#2843)"

direct_loop="$work/installed/skills/launch-fleet/scripts/loop.sh"
for mode in ppid pid; do
  (service; inherit; rm -rf "$work/cache"; : > "$work/read.log"
    if [ "$mode" = ppid ]; then
      sh -c 'LAUNCH_FLEET_TOKEN_STEP=$$; export LAUNCH_FLEET_TOKEN_STEP; sh "$1"' sh "$direct_loop" \
        > "$work/out" 2> "$work/err" || { cat "$work/err" >&2; exit 1; }
    else
      sh -c 'LAUNCH_FLEET_TOKEN_STEP=$$; export LAUNCH_FLEET_TOKEN_STEP; exec sh "$1"' sh "$direct_loop" \
        > "$work/out" 2> "$work/err" || { cat "$work/err" >&2; exit 1; }
    fi
    cmp "$work/want" "$work/out"
    [ "$(head -n 1 "$work/err")" = "$off" ]
    [ "$(wc -l < "$work/err" | tr -d ' ')" = 2 ]
    [ "$(cat "$work/read.log")" = 'none account' ]
    dropped
    [ ! -s "$work/service.log" ])
done
cp "$work/world-on.json" "$work/world.json"
(service; export OPENWIZ_TOKEN_SERVICE="$work/service-order.py"; inherit; rm -rf "$work/cache"
  : > "$work/read.log"; : > "$work/order.log"
  sh -c 'LAUNCH_FLEET_TOKEN_STEP=$$; export LAUNCH_FLEET_TOKEN_STEP; sh "$1"' sh "$direct_loop" \
    > "$work/out" 2> "$work/err" || { cat "$work/err" >&2; exit 1; }
  cmp "$work/want" "$work/out"
  [ ! -s "$work/shim.log" ]
  [ "$(cat "$work/read.log")" = 'none account' ]
  [ "$(cat "$work/order.log")" = "$(printf 'read\nhelper')" ]
  [ -s "$work/gh-token.log" ]
  [ -z "$(grep -vx "$ga4 installation" "$work/gh-token.log")" ]
  [ "$(grep -c '^fleet.sh: used ' "$work/err")" = 1 ]
  [ "$(wc -l < "$work/err" | tr -d ' ')" = 1 ]
  ! grep -q "$ga4" "$work/out" "$work/err" "$work/gh.log"
  [ -z "$(find "$work/token-private" -name 'step-*.json')" ])
(service; export OPENWIZ_TOKEN_SERVICE="$work/service-order.py" FAKE_SERVICE_REFUSE=1
  rm -rf "$work/cache"; : > "$work/read.log"; : > "$work/order.log"; : > "$work/gh-token.log"
  sh "$direct_loop" > "$work/out" 2> "$work/err" || { cat "$work/err" >&2; exit 1; }
  cmp "$work/want" "$work/out"
  [ "$(cat "$work/read.log")" = 'none account' ]
  [ "$(cat "$work/order.log")" = "$(printf 'read\nhelper')" ]
  [ -s "$work/gh-token.log" ]
  [ -z "$(grep -vx 'none account' "$work/gh-token.log")" ]
  grep -q 'no openwiz\[bot\] token' "$work/err"
  [ -z "$(find "$work/token-private" -name 'step-*.json')" ])
cp "$work/world-off.json" "$work/world.json"
for bad_step in missing bad-nonce bad-pid bad-repo bad-mode symlink; do
  (service; inherit; rm -rf "$work/cache"; : > "$work/read.log"
    sid=0123456789abcdef0123456789abcdef
    nonce=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    other=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
    sfile="$work/token-private/step-$sid.json"
    rfile="$work/token-private/run-0123456789abcdef0123456789abcdef.json"
    printf '{"token":"%s","expires_at":1793538000}\n' "$ga4" > "$rfile"
    chmod 600 "$rfile"
    export OPENWIZ_AGENT_TOKEN_RUN="$rfile"
    case $bad_step in
      missing) ;;
      bad-nonce)
        sh -c 'printf "{\"pid\":%s,\"nonce\":\"%s\",\"repo\":\"synthetic-owner/synthetic-repo\"}\n" "$$" "$2" > "$1"; chmod 600 "$1"; LAUNCH_FLEET_TOKEN_STEP="$3:$4"; export LAUNCH_FLEET_TOKEN_STEP; sh "$5"' \
          sh "$sfile" "$other" "$sid" "$nonce" "$direct_loop" > "$work/out" 2> "$work/err" || { cat "$work/err" >&2; exit 1; } ;;
      bad-pid)
        printf '{"pid":1,"nonce":"%s","repo":"synthetic-owner/synthetic-repo"}\n' "$nonce" > "$sfile"; chmod 600 "$sfile" ;;
      bad-repo)
        sh -c 'printf "{\"pid\":%s,\"nonce\":\"%s\",\"repo\":\"other/repo\"}\n" "$$" "$2" > "$1"; chmod 600 "$1"; LAUNCH_FLEET_TOKEN_STEP="$3:$2"; export LAUNCH_FLEET_TOKEN_STEP; sh "$4"' \
          sh "$sfile" "$nonce" "$sid" "$direct_loop" > "$work/out" 2> "$work/err" || { cat "$work/err" >&2; exit 1; } ;;
      bad-mode)
        sh -c 'printf "{\"pid\":%s,\"nonce\":\"%s\",\"repo\":\"synthetic-owner/synthetic-repo\"}\n" "$$" "$2" > "$1"; chmod 644 "$1"; LAUNCH_FLEET_TOKEN_STEP="$3:$2"; export LAUNCH_FLEET_TOKEN_STEP; sh "$4"' \
          sh "$sfile" "$nonce" "$sid" "$direct_loop" > "$work/out" 2> "$work/err" || { cat "$work/err" >&2; exit 1; } ;;
      symlink)
        printf '{"pid":1,"nonce":"%s","repo":"synthetic-owner/synthetic-repo"}\n' "$nonce" > "$work/step-target.json"; chmod 600 "$work/step-target.json"
        ln -s "$work/step-target.json" "$sfile" ;;
    esac
    case $bad_step in
      missing | bad-pid | symlink)
        LAUNCH_FLEET_TOKEN_STEP="$sid:$nonce" sh "$direct_loop" > "$work/out" 2> "$work/err" || { cat "$work/err" >&2; exit 1; } ;;
    esac
    cmp "$work/want" "$work/out"
    [ "$(head -n 1 "$work/err")" = "$off" ]
    [ "$(cat "$work/read.log")" = 'none account' ]
    dropped
    [ ! -s "$work/service.log" ])
done
(service; rm -rf "$work/cache"
  LAUNCH_FLEET_TOKEN_STEP=synthetic-step-sentinel-2869 sh -x "$direct_loop" > "$work/out" 2> "$work/trace" \
    || { cat "$work/trace" >&2; exit 1; }
  cmp "$work/want" "$work/out"
  absent -F synthetic-step-sentinel-2869 "$work/trace")
echo "ok   inherited or forged continuation tokens are rejected and re-read, while approved-read continuations verify and consume their private token (#2869)"

sed -n '/<!-- GI7 identity -->/,/^  ```$/p' "$HERE/../references/identity.md" | sed '1,2d;$d;s/^  //' > "$work/block.sh"
(inherit
  sh -c '. "$1"; app gh --version > /dev/null 2>&1 || :; app_git -C "$2" rev-parse HEAD > /dev/null' \
    sh "$work/block.sh" "$work/remote" 2> "$work/err" || { cat "$work/err" >&2; exit 1; }
  [ "$(cat "$work/err")" = "GitHub as today's account: the App identity is off" ]
  dropped)
sed -n '/^restore_today_account() {$/,/^}$/p' "$HERE/loop.sh" > "$work/restore.loop"
sed -n '/^restore_today_account() {$/,/^}$/p' "$work/block.sh" > "$work/restore.block"
[ -s "$work/restore.loop" ]
cmp "$work/restore.loop" "$work/restore.block"
echo "ok   the identity block drops inherited shims with loop.sh's restore_today_account (#2843)"

for marks in x:3 01:3 4:3 :3 -:3 1:x 1:01 1: 1:- 1:1234567890 x:- -:-; do
  (inherit; at=${marks%%:*} count=${marks#*:}
    if [ "$at" = - ]; then unset OPENWIZ_AGENT_TOKEN_GIT_AT; else export OPENWIZ_AGENT_TOKEN_GIT_AT="$at"; fi
    if [ "$count" = - ]; then unset GIT_CONFIG_COUNT; else export GIT_CONFIG_COUNT="$count"; fi
    for copy in loop block; do
      sh -c '. "$1"; restore_today_account; env' sh "$work/restore.$copy" > "$work/env"
      absent '^GIT_CONFIG_COUNT=' "$work/env"
      absent -E '^GIT_CONFIG_(KEY|VALUE)_' "$work/env"
    done
    absent '^OPENWIZ_AGENT_TOKEN_' "$work/env"
    absent '^GH_TOKEN=' "$work/env")
done
for marks in x:- -:- x:x -:01; do
  (inherit; at=${marks%%:*} count=${marks#*:}
    if [ "$at" = - ]; then unset OPENWIZ_AGENT_TOKEN_GIT_AT; else export OPENWIZ_AGENT_TOKEN_GIT_AT="$at"; fi
    if [ "$count" = - ]; then unset GIT_CONFIG_COUNT; else export GIT_CONFIG_COUNT="$count"; fi
    unset GIT_CONFIG_KEY_2 GIT_CONFIG_VALUE_2
    export GIT_CONFIG_KEY_5=synthetic.sparse GIT_CONFIG_VALUE_5=five GIT_CONFIG_KEY_12=synthetic.sparse \
      GIT_CONFIG_VALUE_40=forty
    [ "$marks" != -:01 ] || unset OPENWIZ_AGENT_TOKEN_PATH_WAS
    for copy in loop block; do
      sh -c '. "$1"; restore_today_account; "$2"' sh "$work/restore.$copy" "$(command -v env)" > "$work/env"
      absent -E '^GIT_CONFIG_(COUNT|KEY_[0-9]+|VALUE_[0-9]+)=' "$work/env"
      sh -x -c '. "$1"; restore_today_account' sh "$work/restore.$copy" 2> "$work/trace"
      absent -E 'synthetic-installation-token-2843|synthetic.sparse|forty' "$work/trace"
    done)
done
(unset OPENWIZ_AGENT_TOKEN_RUN; export GH_TOKEN=synthetic-own-account-2843
  sh -c '. "$1"; restore_today_account; printf "%s\n" "$GH_TOKEN"' sh "$work/restore.loop" > "$work/env"
  [ "$(cat "$work/env")" = synthetic-own-account-2843 ])
echo "ok   restore_today_account drops every git config entry, sparse indexes included, on an unreadable mark and keeps an own GH_TOKEN (#2843)"

for shell in bash dash; do
  command -v "$shell" > /dev/null
  for ifs in : '' _ 5 G ' ' - readonly-space readonly-underscore; do
    (inherit; export OPENWIZ_AGENT_TOKEN_GIT_AT=x GIT_CONFIG_COUNT=x
      unset GIT_CONFIG_KEY_2 GIT_CONFIG_VALUE_2
      export GIT_CONFIG_KEY_5=synthetic.sparse GIT_CONFIG_VALUE_5=five GIT_CONFIG_KEY_12=synthetic.sparse \
        GIT_CONFIG_VALUE_40=forty SYNTHETIC_LINES='one
GIT_CONFIG_KEY_5 synthetic;name_9=two'
      for copy in loop block; do
        case $ifs in
          -) set -- 'unset IFS' '[ -z "${IFS+x}" ]' ;;
          readonly-space) set -- 'IFS=" "; readonly IFS' '[ "$IFS" = " " ]' ;;
          readonly-underscore) set -- 'IFS=_; readonly IFS' '[ "$IFS" = _ ]' ;;
          *) set -- 'IFS=$3' '[ "${IFS-unset}" = "$3" ]' ;;
        esac
        "$shell" -c "$1"'; . "$1"; restore_today_account; '"$2"' || exit 1; "$2"' \
          sh "$work/restore.$copy" "$(command -v env)" "$ifs" > "$work/env"
        [ -s "$work/env" ]
        absent -E '^GIT_CONFIG_(COUNT|KEY_[0-9]+|VALUE_[0-9]+)=' "$work/env"
        absent -E '^(OPENWIZ_AGENT_TOKEN_|GH_TOKEN=|restore_)' "$work/env"
      done)
  done
done
echo "ok   restore_today_account drops every git config entry under any caller IFS, in bash and dash, readonly included, and leaves IFS as it was (#2875)"

# Failed refreshes and first clones must not emit work or leave runtime files.
mv "$work/remote" "$work/offline"
status=0
sh "$work/loop.sh" > "$work/out" 2> "$work/err" || status=$?
[ "$status" = 2 ] && [ ! -s "$work/out" ]
grep -q "can't fetch" "$work/err"
[ -z "$(ls -A "$work/runtime")" ]
LAUNCH_FLEET_HOME="$work/new-home" FAKE_GH_FAIL=repo_clone sh "$work/loop.sh" \
  > "$work/out" 2> "$work/err" && exit 1 || status=$?
[ "$status" = 2 ] && [ ! -s "$work/out" ]
grep -q "can't clone" "$work/err"
[ -z "$(ls -A "$work/runtime")" ]
echo 'ok   clone and refresh failures exit 2 without due lines or temporary files'

# Generation must fail before emitting a partial upload when a helper is absent.
mkdir -p "$work/incomplete/skills/launch-fleet/scripts" "$work/incomplete/skills/to-tickets"
cp "$HERE/loop.sh" "$work/incomplete/skills/launch-fleet/scripts/loop.sh"
status=0
sh "$work/incomplete/skills/launch-fleet/scripts/loop.sh" --bundle synthetic-owner/synthetic-repo \
  > "$work/out" 2> "$work/err" || status=$?
[ "$status" = 2 ] && [ ! -s "$work/out" ]
echo 'ok   an incomplete install cannot generate a partial loop'

cp "$HERE/fleet.sh" "$work/incomplete/skills/launch-fleet/scripts/fleet.sh"
cp "$FIX/revision.sh" "$work/incomplete/skills/to-tickets/revision.sh"
printf '\nOPENWIZ_BUNDLED_HELPER_EOF\n' >> "$work/incomplete/skills/launch-fleet/scripts/fleet.sh"
status=0
sh "$work/incomplete/skills/launch-fleet/scripts/loop.sh" --bundle synthetic-owner/synthetic-repo \
  > "$work/out" 2> "$work/err" || status=$?
[ "$status" = 2 ] && [ ! -s "$work/out" ]
grep -q 'heredoc delimiter' "$work/err"
echo 'ok   a helper cannot terminate its quoted bundle early'

for repo in '../consumer' 'owner/../consumer' 'owner/consumer;echo'; do
  status=0
  sh "$HERE/loop.sh" --bundle "$repo" > "$work/out" 2> "$work/err" || status=$?
  [ "$status" = 2 ] && [ ! -s "$work/out" ]
  grep -q 'GH_REPO must be owner/name' "$work/err"
done
echo 'ok   unsafe repository names cannot generate a loop'

