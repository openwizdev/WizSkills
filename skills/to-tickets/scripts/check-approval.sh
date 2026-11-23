#!/bin/sh
set -u
usage='usage: sh check-approval.sh [--checkpoints] <spec issue number>'
mode=table
if [ "${1:-}" = --checkpoints ]; then mode=checkpoints; shift; fi
spec=${1:-}
case $spec in
  '' | 0* | *[!0-9]*) echo "$usage" >&2; exit 2 ;;
esac
[ "$#" -eq 1 ] || { echo "$usage" >&2; exit 2; }
fail() { echo "check-approval.sh: $*" >&2; exit 1; }
unreadable_exit=1
unreadable() { echo "check-approval.sh: $*" >&2; exit "$unreadable_exit"; }
work=$(mktemp -d) || fail 'cannot make a temporary folder'
trap 'rm -rf "$work"' EXIT

checkpoints() {
CHECKPOINTS_SINCE=2026-11-21T00:00:00Z
here=$(cd -P "$(dirname "$0")" && pwd -P) || unreadable 'cannot find this script'
awk '/^```checkpoints-v1$/ {n++; on = 1; next} on && /^```$/ {on = 0; next} on {print}
     END {if (n != 1) exit 1}' "$here/../../../contracts/checkpoints.v1.md" > "$work/forms-raw" 2> /dev/null &&
  jq -es 'if length == 1 and (.[0] | type == "object")
       and all(.[0] | (.section, .section_like, .setext_text, .setext_underline, .section_end,
                       .fence, .one_way_door, .user_visible); type == "string")
    then .[0] else error("bad forms") end' "$work/forms-raw" > "$work/forms.json" 2> /dev/null ||
  unreadable 'cannot read the checkpoint forms from contracts/checkpoints.v1.md'
reading=$(jq -esr --slurpfile forms "$work/forms.json" --arg since "$CHECKPOINTS_SINCE" '
  $forms[0] as $f
  | def whole($form): test("\\A(?:" + $form + ")\\z");
    def fence: capture("\\A {0,3}(?<f>`+|~+)").f;
  .[0]
  | if (.body | type) == "string"
       and (.createdAt | type == "string" and test("\\A[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\\z"))
    then . else error("unreadable spec") end
  | (.createdAt >= $since) as $new
  | (.body | gsub("\r\n"; "\n") | gsub("\r"; "\n") | split("\n")) as $lines
  | ($lines | length) as $n
  | (reduce $lines[] as $line ({open: null, inside: []};
      if .open == null then
        if ($line | whole($f.fence)) then .open = ($line | fence) | .inside += [true]
        else .inside += [false] end
      else
        .inside += [true]
        | if ($line | test("\\A {0,3}(`+|~+)[ \\t]*\\z"))
             and ($line | fence) as $close
             | ($close[0:1] == .open[0:1] and ($close | length) >= (.open | length))
          then .open = null else . end
      end) | .inside) as $inside
  | [range(0; $n) | select($inside[.] | not)] as $outside
  | if any($outside[]; . as $i | $lines[$i] as $line
        | (($line | whole($f.section_like)) and ($line | whole($f.section) | not))
          or (($line | whole($f.setext_text)) and $i + 1 < $n and ($inside[$i + 1] | not)
              and ($lines[$i + 1] | whole($f.setext_underline))))
    then "invalid section-heading"
    else [$outside[] | select($lines[.] | whole($f.section))] as $starts
    | if ($starts | length) == 0 then (if $new then "absent-new" else "absent" end)
      elif ($starts | length) > 1 then "invalid section-repeated"
      else (first($outside[] | select(. > $starts[0] and ($lines[.] | whole($f.section_end)))) // $n) as $stop
      | [$lines[$starts[0] + 1:$stop][] | select(test("\\S"))] as $answers
      | if ($answers | length) < 2 then "invalid answer-missing"
        elif ($answers | length) == 2 and ($answers[0] | whole($f.one_way_door))
             and ($answers[1] | whole($f.user_visible)) then "answered"
        else "invalid answer-line" end
      end
    end
' "$work/graph" 2> /dev/null) || unreadable "cannot read spec #$spec's body and creation time"
case $reading in
  answered | absent) ;;
  absent-new) fail "spec #$spec has no ## Checkpoints section; a spec created on or after $CHECKPOINTS_SINCE needs both answers (contracts/checkpoints.v1.md)" ;;
  *) fail "spec #$spec's checkpoints are invalid (${reading#invalid }); write both answers as contracts/checkpoints.v1.md says" ;;
esac
}

if [ "$mode" = checkpoints ]; then
  unreadable_exit=2
  cat > "$work/graph" || unreadable "cannot read spec #$spec's body and creation time"
  checkpoints
  echo "check-approval.sh: #$spec checkpoint answers are valid"
  exit 0
fi

gh api -H 'Accept: application/vnd.github.raw+json' \
  'repos/{owner}/{repo}/contents/docs/agents/triage-labels.md' > "$work/labels.md" ||
  fail 'cannot read project labels from docs/agents/triage-labels.md'
awk '/^## /{on = ($0 == "## Labels")} on && /^[|] *`[^`]+` *[|]/' \
  "$work/labels.md" > "$work/label-rows" || fail 'cannot read the project labels table'
jq -Rne '
  [inputs | capture("^\\| *`(?<role>[^`]+)` *\\| *`(?<name>[^`]*)` *\\|")
   | select(.role == "ready-for-agent" or .role == "ready-for-human")
   | {key: .role, value: .name}] as $rows
  | if ($rows | map(.key) | sort) == ["ready-for-agent", "ready-for-human"]
       and all($rows[]; .value != "")
    then $rows | from_entries else error("both ready roles must map exactly once") end
' < "$work/label-rows" > "$work/labels.json" 2> /dev/null ||
  fail 'project labels table must map ready-for-agent and ready-for-human exactly once to nonempty names'

gh api -H 'Accept: application/vnd.github.raw+json' \
  'repos/{owner}/{repo}/contents/docs/agents/issue-tracker.md' > "$work/tracker.md" ||
  fail 'cannot read project private records setting'
private_records=$(jq -Rner '
  [inputs | select(test("^(- )?\\*\\*Private records:\\*\\*"))] as $rows
  | if ($rows | length) != 1 then error("one private records setting required")
    else $rows[0] | capture("^(- )?\\*\\*Private records:\\*\\* `(?<repository>[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9][A-Za-z0-9_.-]*)`(?:, [^\\r\\n]+|\\.)?$").repository
    end
' < "$work/tracker.md" 2>/dev/null) || fail 'invalid project private records setting'
[ -n "$private_records" ] || fail 'invalid project private records setting'

gh api -H 'Accept: application/vnd.github.raw+json' \
  'repos/{owner}/{repo}/contents/docs/agents/fleet.md' > "$work/fleet.md" ||
  fail 'cannot read the record authors from docs/agents/fleet.md'
awk '/^## /{on = ($0 == "## GitHub identity")} on && /^[|] *Record authors *[|]/' "$work/fleet.md" > "$work/authors.txt" &&
  jq -Rse 'split("\n") | map(select(length > 0)) | select(length == 1) | .[0]
    | split("|") | select(length == 4 and (.[3] | test("^\\s*$"))) | .[2]
    | "`[A-Za-z0-9](-?[A-Za-z0-9])*(\\[bot\\])?`" as $login
    | select(test("^\\s*" + $login + "(\\s*,\\s*" + $login + ")*\\s*$"))
    | [scan("`([^`]*)`") | .[0] | ascii_downcase]' "$work/authors.txt" > "$work/authors.json" 2> /dev/null ||
  fail 'docs/agents/fleet.md names no record authors (its "## GitHub identity" table'"'"'s "Record authors" row)'

gh issue view "$spec" --json body,createdAt,subIssues > "$work/graph" || fail "cannot read spec #$spec's tickets"
jq -es '
  def num: type == "number" and . > 0 and . == floor;
  if length != 1 then error("not one graph") else .[0].subIssues end
  | if (.totalCount | num) and (.nodes | type) == "array"
       and .totalCount == (.nodes | length) and all(.nodes[]; .number | num)
       and ([.nodes[].number] | unique | length) == .totalCount
    then [.nodes[].number] | sort else error("incomplete graph") end
' "$work/graph" > "$work/tickets" 2> /dev/null || fail "cannot read spec #$spec's complete, unique tickets"

gh api --paginate "repos/{owner}/{repo}/issues/$spec/comments?per_page=100" > "$work/comments" ||
  fail "cannot read spec #$spec's comments"
jq -es '
  def num: type == "number" and . > 0 and . == floor;
  if length > 0 and all(.[]; type == "array") then add else error("not whole pages") end
  | if all(.[]; type == "object" and (.id | num) and (.body | type) == "string")
       and (map(.id) | unique | length) == length
    then . else error("bad comments") end
' "$work/comments" > "$work/all-comments" 2> /dev/null || fail "cannot read spec #$spec's complete comments"

private=false
repo=''
if gh repo view --json isPrivate,nameWithOwner > "$work/repo" 2> /dev/null; then
  if jq -es 'length == 1 and (.[0] | type == "object" and .isPrivate == true)' \
       "$work/repo" > /dev/null 2>&1; then
    private=true
  fi
  repo=$(jq -esr 'if length == 1 and (.[0].nameWithOwner | type == "string" and test("^[A-Za-z0-9-]+/[A-Za-z0-9_.-]+$"))
    then .[0].nameWithOwner | ascii_downcase else error("unknown") end' "$work/repo" 2> /dev/null) || repo=''
fi

jq -er --arg records "$private_records" --arg repo "$repo" --argjson private "$private" --slurpfile tickets "$work/tickets" --slurpfile labels "$work/labels.json" --slurpfile authors "$work/authors.json" '
  def trim: sub("^\\s+"; "") | sub("\\s+$"; "");
  def long_ref: "(?<![A-Za-z0-9_./-])(?<o>[A-Za-z0-9-]+/[A-Za-z0-9_.-]+)#(?<n>[1-9][0-9]*)";
  def short: gsub(long_ref; if $repo != "" and (.o | ascii_downcase) == $repo then "#\(.n)" else "\(.o)#\(.n)" end);
  def foreign: [scan(long_ref) | select($repo == "" or (.[0] | ascii_downcase) != $repo) | "\(.[0])#\(.[1])"] | unique;
  def public_form:
    . as $lines
    | ($lines[0] | capture("^\\*\\*Plan graph approved by (?<decider>[^,\\r\\n]+), [0-9]{4}-[0-9]{2}-[0-9]{2}, revision [1-9][0-9]*:\\*\\* (?<decision>[^\"“”]+)$") // null) as $header
    | $header != null and ($header.decision | trim | length) > 0
      and (($lines[1] // "" | capture("^Private record: https://github\\.com/(?<repository>[A-Za-z0-9-]+/[A-Za-z0-9_.-]+)/(issues|pull)/[1-9][0-9]*#issuecomment-[1-9][0-9]*$").repository) // null) == $records
      and all($lines[];
        (test("thr_[A-Za-z0-9][A-Za-z0-9_-]*") | not)
        and (test("^ {0,3}>") | not)
        and (if contains($header.decider // "") or contains("Jake") then
          (test(":(?:\\*\\*)?[ \\t]*\\\\?[\"“”]") | not) else true end));
  def cells:
    sub("\\s+$"; "")
    | if startswith("|") and endswith("|") then
      # A pipe is a separator only after an even run of backslashes.
      reduce (explode[]) as $char ({cells: [""], escaped: false};
        if $char == 124 and (.escaped | not) then .cells += [""]
        else .cells[-1] += ([$char] | implode) end
        | .escaped = (if $char == 92 then (.escaped | not) else false end))
      | .cells
      | if .[0] == "" and .[-1] == "" then .[1:-1] | map(trim)
        else error("approval table must end with an unescaped |") end
    else error("approval table must use launch-fleet rows beginning and ending with |") end;
  # Keep only table lines outside fenced examples (such as revision text).
  # Keep their indexes too: scattered rows are not one Markdown table.
  def table:
    reduce (to_entries[]) as $line ({fence: null, rows: []};
      if .fence != null then
        .fence as $fence
        | if ($line.value | test("^ {0,3}" + $fence.char + "{" + ($fence.size | tostring) + ",} *$"))
        then .fence = null else . end
      elif ($line.value | test("^ {0,3}(`{3,}|~{3,})")) then
        ($line.value | capture("^ {0,3}(?<f>`{3,}|~{3,})").f) as $f
        | .fence = {char: $f[0:1], size: ($f | length)}
      elif ($line.value | test("^\\s*\\|")) then .rows += [$line]
      else . end)
    | .rows;
  [.[] | select((.user | if type == "object" then .login else null end
                 | if type == "string" then ascii_downcase else null end) as $l
                | $l != null and any($authors[0][]; . == $l))
   | select((.body | split("\n") | map(select(test("\\S"))) | first // "" | sub("^\\s+"; ""))
                | startswith("**Plan graph approved by"))] | max_by(.id)
  | if . == null then error("no posted plan graph approval") else .body end
  | split("\n") | map(rtrimstr("\r"))
  | if $private or public_form then . else error("public approval form requires a decision, date and private pointer, without quotes or thread ids") end
  | table
  | if length < 3 then error("approval table is missing") else . end
  | if (map(.key) | . == [range(.[0]; .[0] + length)]) then .
    else error("approval table rows are not contiguous") end
  | ([.[2:][] | .value as $line | ($line | cells) as $c
      | select(($c | length) == 4) | [($c[0], $c[2]) | foreign[]] | unique | select(length > 0)
      | {line: $line, refs: .}] | first) as $bad
  | if $bad != null then error("approval table line `\($bad.line | sub("\\s+$"; "") | short)` names \($bad.refs | join(", ")), not this repository")
    else map(.value | cells | (if length == 4 then .[0] |= short | .[2] |= short else . end)) end
  | if .[0] == ["Ticket", "Title", "Blocked by", "Label"] then .
    else error("approval table columns must be Ticket | Title | Blocked by | Label") end
  | if (.[1] | length) == 4 and all(.[1][]; test("^:?-{3,}:?$")) then .[2:]
    else error("approval table separator must have four columns") end
  | map(if length == 4 and (.[0] | test("^#[1-9][0-9]*$")) and .[1] != "" and .[2] != ""
              and (.[3] == "held" or .[3] == $labels[0]["ready-for-agent"] or .[3] == $labels[0]["ready-for-human"])
        then .[0][1:] | tonumber else error("approval table row needs a ticket, title, blockers and valid ready label or held") end)
  | if length == (unique | length) and sort == $tickets[0] then true
    else error("approval table tickets must equal the complete sub-issue set, each once") end
' "$work/all-comments" > /dev/null 2> "$work/error" || {
  cat "$work/error" >&2
  fail "spec #$spec's posted approval table is invalid; correct it before labelling or handoff"
}
checkpoints
echo "check-approval.sh: #$spec approval table is valid"
