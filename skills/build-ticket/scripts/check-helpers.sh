#!/bin/sh
# The no-push check (OpenWiz 0.0.7, ClosedWiz#206): after a swarm, did a
# helper write to GitHub? docs/agents/helpers.md says when to run it.
#
#   sh check-helpers.sh snapshot TICKET [PULL] > FILE
#   sh check-helpers.sh check FILE [--ended WINDOW] [--own BRANCH COMMIT] [--own-comment ID]... [--loop-comment ID]...
#
# snapshot reads, through `gh`, everything on GitHub a helper of ticket TICKET
# could change: every branch under room/TICKET- and PULL's own branch; every
# comment on TICKET and PULL, and every review and review comment on PULL; and
# PULL's state. It prints them as JSON and saves a durable home-directory copy.
# Run check immediately after archiving the helpers. It saves the complete end
# state; --ended WINDOW reruns that saved comparison without reading GitHub.
# WINDOW is a file, not a timestamp: current refs/deletions cannot be reliably
# reconstructed from timestamps. Later writes stay outside the saved window.
#
# check reads the same again, and prints one "hit #TICKET: ..." line for each
# change since FILE:
#   - a branch new, moved or deleted, but for BRANCH at COMMIT (--own: your
#     own push; COMMIT is the branch's head on GitHub, your HEAD);
#   - a comment new, edited or deleted, but for comment ID named with
#     --own-comment (your own, any number of times) or --loop-comment (a loop
#     record you read and expected: allowed only when it is one of the forms
#     launch-fleet's records table lists for a ticket or a pull request, and,
#     if edited, was one before, and only when one of the record authors
#     wrote it (#717: the Record authors row of docs/agents/fleet.md on the
#     default branch, read as launch-fleet reads it);
#   - a review or a review comment new, edited or deleted;
#   - PULL merged, closed or reopened.
# Every agent posts from the same GitHub account, so nothing else can tell a
# helper's write from yours or the loop's: everything not named is a hit,
# whatever it says.
#
# The repository is $GH_REPO (owner/name), else the clone you are in; check
# reads the snapshot's. GitHub calls are reads only (`gh repo view` and `gh api`
# GETs). Local snapshots/windows go under $HOME/.openwiz/helper-checks/. Their
# paths are printed on stderr; stdout keeps its existing JSON/verdict shape.
#
# Exit 0: clean, one "clean #TICKET: ..." line. Exit 1: the hit lines. Exit 2
# when it can't tell (a read failed or was partial, a bad snapshot or bad
# arguments), with the reason on stderr and nothing on stdout: never a pass.

die() { printf 'check-helpers.sh: %s\n' "$*" >&2; exit 2; }
usage() { die "usage: check-helpers.sh snapshot TICKET [PULL] | check FILE [--ended WINDOW] [--own BRANCH COMMIT] [--own-comment ID]... [--loop-comment ID]..."; }
# A positive whole number, as GitHub numbers issues and comments.
is_number() { case $1 in '' | 0* | *[!0-9]*) return 1 ;; esac; [ ${#1} -le 15 ]; }
is_commit() { case $1 in *[!0-9a-f]*) return 1 ;; esac; [ ${#1} -eq 40 ]; }

cmd=${1:-}
[ $# -gt 0 ] && shift
OWN_BRANCH='' OWN_COMMIT='' OWN_IDS='' LOOP_IDS='' ENDED=''
case $cmd in
  snapshot)
    [ $# -eq 1 ] || [ $# -eq 2 ] || usage
    is_number "$1" || die "the ticket must be a number, not '$1'"
    TICKET=$1 PULL=${2:-}
    [ -z "$PULL" ] || is_number "$PULL" || die "the pull request must be a number, not '$PULL'"
    [ "$PULL" != "$TICKET" ] || die "the ticket and the pull request are both #$TICKET" ;;
  check)
    [ $# -ge 1 ] || usage
    FILE=$1
    shift
    while [ $# -gt 0 ]; do
      case $1 in
        --ended)
          [ $# -ge 2 ] && [ -n "$2" ] || die "--ended needs a saved window file"
          [ -z "$ENDED" ] || die "--ended is given twice"
          ENDED=$2
          shift 2 ;;
        --own)
          [ $# -ge 3 ] || die "--own needs a branch and a commit"
          [ -z "$OWN_BRANCH" ] || die "--own is given twice"
          [ -n "$2" ] || die "--own needs a branch"
          is_commit "$3" || die "--own: '$3' is not a full commit (40 lowercase hex characters)"
          OWN_BRANCH=$2 OWN_COMMIT=$3
          shift 3 ;;
        --own-comment)
          [ $# -ge 2 ] || die "--own-comment needs a comment id"
          is_number "$2" || die "--own-comment: '$2' is not a comment id"
          OWN_IDS="$OWN_IDS $2"
          shift 2 ;;
        --loop-comment)
          [ $# -ge 2 ] || die "--loop-comment needs a comment id"
          is_number "$2" || die "--loop-comment: '$2' is not a comment id"
          LOOP_IDS="$LOOP_IDS $2"
          shift 2 ;;
        *) usage ;;
      esac
    done ;;
  *) usage ;;
esac

command -v gh > /dev/null 2>&1 || die "gh is not installed"
command -v jq > /dev/null 2>&1 || die "jq is not installed"
umask 077
TMP=$(mktemp -d) || die "no temporary folder"
trap 'rm -rf "$TMP"' EXIT
trap 'exit 2' HUP INT TERM
# shellcheck disable=SC2086 # the ids are numbers, one word each
OWN_COMMENTS=$(printf '%s\n' $OWN_IDS | jq -c -s .) || die "can't read --own-comment"
# shellcheck disable=SC2086
LOOP_COMMENTS=$(printf '%s\n' $LOOP_IDS | jq -c -s .) || die "can't read --loop-comment"

valid_repo() {
  case $1 in
    */*/* | /* | */ | ./* | ../* | */. | */.. | *[!A-Za-z0-9._/-]*) return 1 ;;
    ?*/?*) return 0 ;;
    *) return 1 ;;
  esac
}

# Save before reporting success, including when stdout is redirected into /tmp.
# Each invocation gets its own directory: concurrent swarms never replace a copy.
save() {
  kind=$1 source=$2
  case ${HOME:-} in /*) ;; *) die "can't save: HOME must be absolute" ;; esac
  store="$HOME/.openwiz/helper-checks/$REPO/$TICKET"
  mkdir -p "$store" 2> /dev/null || die "can't save $kind: no durable folder"
  saved_dir=$(mktemp -d "$store/$kind.XXXXXX") || die "can't save $kind: no private folder"
  SAVED="$saved_dir/state.json"
  cp "$source" "$SAVED" || die "can't save $kind"
}

# The jq both commands share: the exact shapes they take from GitHub.
LIB='
def num: type == "number" and . > 0 and . == floor;
def commit: type == "string" and test("^[0-9a-f]{40}$");
def branch: type == "string" and test("^[A-Za-z0-9._/-]+$");
def no_repeats($what): if (map(.key) | unique | length) == length then from_entries
  else error("\($what) twice") end;
# The branches under refs/heads/$prefix: {name: commit}.
def refs($prefix): map(
  if type == "object" and (.ref | type) == "string" and (.ref | startswith("refs/heads/" + $prefix))
     and (.object | type) == "object" and .object.type == "commit" and (.object.sha | commit)
  then {key: (.ref | ltrimstr("refs/heads/")), value: .object.sha}
  else error("a branch that is not under \($prefix), or not a commit") end) | no_repeats("a branch");
# Comments and review comments on $on: {"<kind> <id> on #<on>": {at, author,
# body}}, the author its login, or null when GitHub names none (#717).
def comments($kind; $on): map(
  if type == "object" and (.id | num) and (.body | type) == "string" and (.updated_at | type) == "string"
  then {key: "\($kind) \(.id) on #\($on)", value: {at: .updated_at,
    author: (.user | if type == "object" and (.login | type) == "string" then .login else null end), body}}
  else error("a \($kind) without its id, body or time") end) | no_repeats("a \($kind)");
# Reviews on $on: {"review <id> on #<on>": {state, at, body}}.
def reviews($on): map(
  if type == "object" and (.id | num) and (.body | type) == "string" and (.state | type) == "string"
     and ((.submitted_at | type) == "string" or .submitted_at == null)
  then {key: "review \(.id) on #\($on)", value: {state, at: .submitted_at, body}}
  else error("a review without its id, body or state") end) | no_repeats("a review");
'

# list NAME PATH WHAT: every item of the paginated list at PATH, as one JSON
# array in $TMP/NAME.json. A failed call, no answer, or any page that is not
# a list (an error, cut short) is a failed read.
list() {
  gh api --paginate "$2" > "$TMP/$1.raw" 2> "$TMP/$1.err" || die "can't read $3: gh failed ($(head -n 1 "$TMP/$1.err"))"
  jq -s 'if length > 0 and all(.[]; type == "array") then add else error("not a list") end' "$TMP/$1.raw" \
    > "$TMP/$1.json" 2> /dev/null || die "can't read $3: the answer is not a whole list"
}
# shape NAME FILTER WHAT [JQ ARGS...]: $TMP/NAME.json, exactly one JSON value
# (no answer, or two, is a failed read), through LIB's FILTER, which must give
# exactly one result.
shape() {
  name=$1 filter=$2 what=$3
  shift 3
  jq -c -s "$@" "$LIB if length != 1 then error(\"the answer is not one JSON value\") else .[0] | ($filter) end" \
    "$TMP/$name.json" > "$TMP/$name.shaped" 2> "$TMP/$name.err" || {
    why=$(sed -n 's/^jq: error (at [^)]*): //p' "$TMP/$name.err" | head -n 1)
    die "can't read $what: ${why:-the answer is not JSON}"
  }
  [ "$(sed -n '$=' "$TMP/$name.shaped")" = 1 ] || die "can't read $what: not exactly one result"
}

# read_all REPO TICKET PULL: everything the check compares, as one JSON object
# in $TMP/now.json, in the snapshot's shape.
read_all() {
  repo=$1 n=$2 p=$3 prefix="room/$2-"
  pull=null head=''
  if [ -n "$p" ]; then
    gh api "repos/$repo/pulls/$p" > "$TMP/pull.json" 2> "$TMP/pull.err" || die "can't read pull request #$p: gh failed ($(head -n 1 "$TMP/pull.err"))"
    shape pull 'if type == "object" and .number == $p and (.state == "open" or .state == "closed")
        and (.merged | type) == "boolean" and (.head | type) == "object" and (.head.ref | branch)
      then {number, state, merged, head: .head.ref} else error("not a pull request") end' "pull request #$p" --argjson p "$p"
    pull=$(cat "$TMP/pull.shaped")
    head=$(jq -r .head "$TMP/pull.shaped") || die "can't read pull request #$p"
  fi
  list refs "repos/$repo/git/matching-refs/heads/$prefix" "the branches under $prefix"
  shape refs 'refs($prefix)' "the branches under $prefix" --arg prefix "$prefix"
  cp "$TMP/refs.shaped" "$TMP/branches.json" || die "can't write"
  case $head in
    '' | "$prefix"*) ;;
    *)
      list head "repos/$repo/git/matching-refs/heads/$head" "branch $head"
      shape head 'refs($b) | with_entries(select(.key == $b))' "branch $head" --arg b "$head"
      jq -c -s 'add' "$TMP/refs.shaped" "$TMP/head.shaped" > "$TMP/branches.json" || die "can't write" ;;
  esac
  list ticket "repos/$repo/issues/$n/comments?per_page=100" "the comments on #$n"
  shape ticket 'comments("comment"; $n)' "the comments on #$n" --argjson n "$n"
  set -- "$TMP/ticket.shaped"
  if [ -n "$p" ]; then
    list pr "repos/$repo/issues/$p/comments?per_page=100" "the comments on #$p"
    shape pr 'comments("comment"; $p)' "the comments on #$p" --argjson p "$p"
    list reviews "repos/$repo/pulls/$p/reviews?per_page=100" "the reviews on #$p"
    shape reviews 'reviews($p)' "the reviews on #$p" --argjson p "$p"
    list inline "repos/$repo/pulls/$p/comments?per_page=100" "the review comments on #$p"
    shape inline 'comments("review comment"; $p)' "the review comments on #$p" --argjson p "$p"
    set -- "$@" "$TMP/pr.shaped" "$TMP/reviews.shaped" "$TMP/inline.shaped"
  fi
  jq -s 'add' "$@" > "$TMP/comments.json" || die "can't write"
  jq -n --arg repo "$repo" --argjson n "$n" --argjson pull "$pull" \
    --slurpfile b "$TMP/branches.json" --slurpfile c "$TMP/comments.json" \
    '{check_helpers: 1, repo: $repo, ticket: $n, pull: $pull, branches: $b[0], comments: $c[0]}' \
    > "$TMP/now.json" || die "can't write"
}

if [ "$cmd" = snapshot ]; then
  REPO=${GH_REPO:-}
  if [ -z "$REPO" ]; then
    REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner 2> /dev/null) || die "set GH_REPO=owner/name, or run inside a clone"
  fi
  valid_repo "$REPO" || die "the repository must be owner/name, not '$REPO'"
  # TICKET must be an issue: a pull request's number would watch the wrong branches.
  gh api "repos/$REPO/issues/$TICKET" > "$TMP/issue.json" 2> "$TMP/issue.err" || die "can't read #$TICKET: gh failed ($(head -n 1 "$TMP/issue.err"))"
  shape issue 'if type == "object" and .number == $n and (.pull_request // null) == null then .number
    else error("#\($n) is not an issue") end' "#$TICKET" --argjson n "$TICKET"
  read_all "$REPO" "$TICKET" "$PULL"
  save snapshot "$TMP/now.json"
  jq . "$SAVED" || die "can't write"
  printf 'check-helpers.sh: snapshot saved: %s\n' "$SAVED" >&2
  exit 0
fi

# check: the snapshot, taken exactly as snapshot writes it.
[ -f "$FILE" ] || die "no snapshot file '$FILE'"
VALIDATE='
  if length != 1 then error("not one JSON object") else .[0] end
  | if type == "object" and keys == ["branches", "check_helpers", "comments", "pull", "repo", "ticket"]
       and .check_helpers == 1 and (.repo | type) == "string" and (.ticket | num)
       and (.pull == null or ((.pull | type) == "object" and (.pull | keys) == ["head", "merged", "number", "state"]
            and (.pull.number | num) and .pull.number != .ticket and (.pull.state == "open" or .pull.state == "closed")
            and (.pull.merged | type) == "boolean" and (.pull.head | branch)))
       and (.branches | type) == "object" and (.comments | type) == "object"
    then . else error("not a snapshot") end
  | . as $s
  | if all(.branches | to_entries[]; (.key | branch)
         and ((.key | startswith("room/\($s.ticket)-")) or .key == $s.pull.head) and (.value | commit))
    then . else error("a branch the snapshot should not hold") end
  | if all(.comments | to_entries[]; (.key | capture("^(?<kind>comment|review|review comment) (?<id>[1-9][0-9]*) on #(?<on>[1-9][0-9]*)$")) as $k
         | ($k.on | tonumber) as $on
         | ($on == $s.ticket or $on == $s.pull.number)
         and ($k.kind == "comment" or $on == $s.pull.number)
         and (.value | type) == "object"
         and (if $k.kind == "review" then (.value | keys) == ["at", "body", "state"] and (.value.state | type) == "string"
              # A snapshot saved before #717 holds no author: it trusts no one.
              else ((.value | keys) == ["at", "body"]
                    or ((.value | keys) == ["at", "author", "body"]
                        and (.value.author == null or (.value.author | type) == "string")))
                   and (.value.at | type) == "string" end)
         and (.value.body | type) == "string" and ((.value.at | type) == "string" or .value.at == null))
    then . else error("a comment the snapshot should not hold") end
'
jq -c -s "$LIB $VALIDATE" "$FILE" > "$TMP/before.json" 2> "$TMP/before.err" \
  || die "'$FILE' is not a snapshot check-helpers.sh wrote: $(sed -n 's/^jq: error (at [^)]*): //p' "$TMP/before.err" | head -n 1)"

REPO=$(jq -r .repo "$TMP/before.json") || die "can't read the snapshot"
valid_repo "$REPO" || die "the snapshot's repository is not owner/name: '$REPO'"
TICKET=$(jq -r .ticket "$TMP/before.json") || die "can't read the snapshot"
PULL=$(jq -r '.pull.number // ""' "$TMP/before.json") || die "can't read the snapshot"
if [ -n "$OWN_BRANCH" ]; then
  case $OWN_BRANCH in
    "room/$TICKET-"?*) ;;
    *) [ -n "$PULL" ] && [ "$OWN_BRANCH" = "$(jq -r .pull.head "$TMP/before.json")" ] \
         || die "--own: $OWN_BRANCH is not a branch this check reads (room/$TICKET-..., or the pull request's)" ;;
  esac
fi

WINDOW=''
if [ -n "$ENDED" ]; then
  [ -f "$ENDED" ] || die "no saved window file '$ENDED'"
  jq -c -s --slurpfile before "$TMP/before.json" '
    if length == 1 then .[0] else error("not one window") end
    | if type == "object" and keys == ["after", "before", "check_helpers_window"]
        and .check_helpers_window == 1 and .before == $before[0]
      then .after else error("invalid window or different starting snapshot") end
  ' "$ENDED" > "$TMP/ended.json" 2> /dev/null || die "invalid window or different starting snapshot"
  jq -c -s "$LIB $VALIDATE" "$TMP/ended.json" > "$TMP/now.json" 2> /dev/null \
    || die "invalid window end snapshot"
  jq -e -n --slurpfile b "$TMP/before.json" --slurpfile a "$TMP/now.json" '
    $b[0].repo == $a[0].repo and $b[0].ticket == $a[0].ticket
    and $b[0].pull.number == $a[0].pull.number
  ' > /dev/null || die "window end belongs to another ticket or pull request"
else
  read_all "$REPO" "$TICKET" "$PULL"
  jq -n --slurpfile b "$TMP/before.json" --slurpfile a "$TMP/now.json" \
    '{check_helpers_window: 1, before: $b[0], after: $a[0]}' > "$TMP/window.json" || die "can't write"
  save window "$TMP/window.json"
  WINDOW=$SAVED
fi

# Read the allowed first words from the Records table itself, relative to
# this script (the caller can be anywhere). Spec-only and commit-only rows
# do not apply.
# A missing or changed table shape must never grant a loop exemption.
RECORD_FORMS='[]'
PRIVATE=false
AUTHORS='[]'
if [ -n "$LOOP_IDS" ]; then
  # #717: a loop record counts only when the factory wrote it. Its identity
  # is the one "| Record authors | <cell> |" row of fleet.md's "## GitHub
  # identity" table, read as launch-fleet reads it (picked in jq, as this
  # script runs no awk): the whole cell backticked logins separated by
  # commas. No row, an empty one, any malformed or extra entry, or anything
  # after the value cell stops the check, never keeping only the logins that
  # did parse.
  gh api -H 'Accept: application/vnd.github.raw+json' "repos/$REPO/contents/docs/agents/fleet.md" \
    > "$TMP/fleet.md" 2> /dev/null || die "can't read the record authors from docs/agents/fleet.md"
  AUTHORS=$(jq -cRse 'split("\n")
    | reduce .[] as $line ({on: false, rows: []};
        if $line | startswith("## ") then .on = ($line == "## GitHub identity")
        elif .on and ($line | test("^[|] *Record authors *[|]")) then .rows += [$line] else . end)
    | .rows | select(length == 1) | .[0]
    | split("|") | select(length == 4 and (.[3] | test("^\\s*$"))) | .[2]
    | "`[A-Za-z0-9](-?[A-Za-z0-9])*(\\[bot\\])?`" as $login
    | select(test("^\\s*" + $login + "(\\s*,\\s*" + $login + ")*\\s*$"))
    | [scan("`([^`]*)`") | .[0] | ascii_downcase]' "$TMP/fleet.md" 2> /dev/null) \
    || die "docs/agents/fleet.md names no record authors (its \"## GitHub identity\" table's \"Record authors\" row)"
  PRIVATE=$(gh repo view "$REPO" --json isPrivate --jq .isPrivate 2>/dev/null) || PRIVATE=false
  [ "$PRIVATE" = true ] || PRIVATE=false
  case $0 in
    */*) dir=${0%/*} ;;
    *) dir=. ;;
  esac
  SCRIPT_DIR=$(CDPATH='' cd -- "$dir" && pwd) || die "can't read launch-fleet Records: no script folder"
  RECORD_FORMS=$(jq -c -R -s --argjson private "$PRIVATE" '
    def trim: gsub("^ +| +$"; "");
    split("\n## Records\n")
    | if length == 2 then .[1] | split("\n## ")[0] else error("expected one Records section") end
    | split("\n") | map(select(startswith("|")))
    | if .[0] == "| On | Record | Means |" and .[1] == "| --- | --- | --- |"
      then .[2:] else error("missing Records table header") end
    | reduce .[] as $row ({scope: "", forms: []};
        ($row | split("|") | map(trim)) as $cells
        | if ($cells | length) == 5 and $cells[0] == "" and $cells[4] == ""
          then . else error("malformed Records row") end
        | if $cells[1] != "" then .scope = $cells[1] else . end
        | .scope as $scope
        | if ["A ticket", "A pull request", "A spec", "A run\u0027s commit", "Any of them"] | index($scope) == null
          then error("unknown Records scope") else . end
        | ($cells[2] | split(" / ") | map(
            if test("^`[^`]+`$") then .[1:-1] else error("malformed record form") end
            # Keep the space before a placeholder: it distinguishes a form
            # with arguments from a fixed record that must end its line.
            | ltrimstr("launch-fleet: ") | split("<")[0]
            | if test("^[A-Za-z][A-Za-z0-9 ,:#-]*$") then . else error("unknown record prefix") end)) as $forms
        | if $scope != "A spec" and $scope != "A run\u0027s commit" then .forms += $forms else . end)
    | .forms | if length > 0 then . else error("no ticket or pull request records") end
    | . + (if $private then ["started, thread ", "start checked, thread ", "review failed ", "old builder archived, thread "] else [] end) | unique
  ' "$SCRIPT_DIR/../../launch-fleet/SKILL.md" 2> "$TMP/records.err") \
    || {
      why=$(sed -n 's/^jq: error (at [^)]*): //p' "$TMP/records.err" | head -n 1)
      die "can't read launch-fleet Records: ${why:-the Records table is unreadable}"
    }
fi

jq -r -n --slurpfile b "$TMP/before.json" --slurpfile a "$TMP/now.json" \
  --arg own_branch "$OWN_BRANCH" --arg own_commit "$OWN_COMMIT" --argjson own_comments "$OWN_COMMENTS" \
  --argjson private "$PRIVATE" --argjson loop_comments "$LOOP_COMMENTS" --argjson record_forms "$RECORD_FORMS" \
  --argjson authors "$AUTHORS" '
  $b[0] as $before | $a[0] as $after | $before.ticket as $n
  # A record launch-fleet writes on a ticket or a pull request, in one of the
  # forms its records table lists (skills/launch-fleet/SKILL.md).
  # Fixed records must end their line. Forms with arguments keep the space
  # or hash mark immediately before the placeholder in the Records table.
  # #717: and only one a record author wrote; no author is no one.
  | def authored: (.author | if type == "string" then ascii_downcase else null end) as $l
      | $l != null and any($authors[]; . == $l);
    def record: type == "object" and authored and (.body as $body | (($private or ($body | test("\\bthr_[A-Za-z0-9][A-Za-z0-9_-]*") | not)) and any($record_forms[];
      ("launch-fleet: " + .) as $prefix
      | ($body | startswith($prefix))
        and ((. | endswith(" ")) or (. | endswith("#"))
             or ($body[($prefix | length):] | test("^(\n|$)"))))));
  [ (($before.branches + $after.branches) | keys[]) as $name
    | $before.branches[$name] as $old | $after.branches[$name] as $new
    | select($old != $new)
    | select(($name == $own_branch and $new == $own_commit) | not)
    | if $old == null then "branch \($name) is new, at \($new)"
      elif $new == null then "branch \($name) was deleted; it was at \($old)"
      else "branch \($name) moved from \($old) to \($new)" end ]
  + [ select($before.pull != $after.pull) | $before.pull as $o | $after.pull as $p
    | if $p.merged and ($o.merged | not) then "pull request #\($p.number) was merged"
      elif $p.state != $o.state then "pull request #\($p.number) was \(if $p.state == "closed" then "closed" else "reopened" end)"
      else "pull request #\($p.number) changed: \($o) to \($p)" end ]
  + [ (($before.comments + $after.comments) | keys[]) as $key
    | $before.comments[$key] as $old | $after.comments[$key] as $new
    # A change is in the text or the time; an author is only learnt (#717).
    | select(($old | if type == "object" then del(.author) else . end)
             != ($new | if type == "object" then del(.author) else . end))
    | (if $key | startswith("comment ") then $key | split(" ")[1] | tonumber else null end) as $id
    | select(($id != null and ($own_comments | index([$id]) != null)) | not)
    | select(($id != null and ($loop_comments | index([$id]) != null)
              and ($new | record) and ($old == null or ($old | record))) | not)
    | if $old == null then "\($key) is new"
      elif $new == null then "\($key) was deleted"
      else "\($key) was edited" end ]
  | if length > 0 then map("hit #\($n): " + .)[]
    else "clean #\($n): nothing changed but the writes you named (branches \($after.branches | length), comments \($after.comments | length)\(if $after.pull then ", pull request #\($after.pull.number)" else "" end))" end
' > "$TMP/out.txt" 2> "$TMP/out.err" || die "can't compare: $(head -n 1 "$TMP/out.err")"

[ -z "$WINDOW" ] || printf 'check-helpers.sh: window saved: %s\n' "$WINDOW" >&2
cat "$TMP/out.txt"
case $(head -n 1 "$TMP/out.txt") in
  "clean #$TICKET: "*) exit 0 ;;
  "hit #$TICKET: "*) exit 1 ;;
  *) die "can't compare" ;;
esac
