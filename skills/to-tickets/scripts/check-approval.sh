#!/bin/sh
# Validate the posted latest approval's table before labelling or handoff.
# Read-only: gh issue/repo view and paginated gh api GETs in gh's current repo.
# Only the record authors' approvals count (#717): the Record authors row of
# docs/agents/fleet.md, read from the default branch as launch-fleet reads it.
# Checks the public form and table, not authority, pointer provenance or
# fingerprint currentness;
# revision.sh and launch-fleet retain those checks unchanged.
# Usage: sh skills/to-tickets/scripts/check-approval.sh <spec issue number>
# Exit 0: valid table and checkpoint answers; 1: invalid table, invalid or
# missing answers, or an unreadable graph; 2: bad arguments.
set -u
spec=${1:-}
case $spec in
  '' | 0* | *[!0-9]*) echo 'usage: sh check-approval.sh <spec issue number>' >&2; exit 2 ;;
esac
[ "$#" -eq 1 ] || { echo 'usage: sh check-approval.sh <spec issue number>' >&2; exit 2; }
fail() { echo "check-approval.sh: $*" >&2; exit 1; }
work=$(mktemp -d) || fail 'cannot make a temporary folder'
trap 'rm -rf "$work"' EXIT

# Use the project mapping from the default branch, just as launch-fleet does.
# Only the operative Labels table counts, never examples or prose elsewhere.
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

# The consumer project's configured private-records repository, read from the
# default branch. Missing, malformed or duplicate settings refuse; cwd is not
# a fallback for a project's separate records repository.
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

# #717: the factory's identity, read as launch-fleet reads it: the one
# "| Record authors | <cell> |" row of fleet.md's "## GitHub identity" table,
# its whole cell backticked logins separated by commas. No row, an empty one,
# any malformed or extra entry, or anything after the value cell refuses the
# whole row, never keeping only the logins that did parse.
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
# gh may cap a connection. Never treat a partial graph as a complete row set.
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
# Every page must be an array; missing fields or repeated pages are not a read.
jq -es '
  def num: type == "number" and . > 0 and . == floor;
  if length > 0 and all(.[]; type == "array") then add else error("not whole pages") end
  | if all(.[]; type == "object" and (.id | num) and (.body | type) == "string")
       and (map(.id) | unique | length) == length
    then . else error("bad comments") end
' "$work/comments" > "$work/all-comments" 2> /dev/null || fail "cannot read spec #$spec's complete comments"

# Only a positive private-repository read permits historical quoting records.
# Missing, failed or malformed visibility reads use the public form check.
private=false
if gh repo view --json isPrivate > "$work/repo" 2> /dev/null &&
   jq -es 'length == 1 and (.[0] | type == "object" and .isPrivate == true)' \
     "$work/repo" > /dev/null 2>&1; then
  private=true
fi

# Same latest-record rule as launch-fleet: first nonblank line starts with
# **Plan graph approved by; greatest comment ID wins, never an older good one.
# #717: only among the record authors' comments, as launch-fleet drops every
# other comment, and one with no author, before any rule sees it.
jq -er --arg records "$private_records" --argjson private "$private" --slurpfile tickets "$work/tickets" --slurpfile labels "$work/labels.json" --slurpfile authors "$work/authors.json" '
  def trim: sub("^\\s+"; "") | sub("\\s+$"; "");
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
  | if (map(.key) | . == [range(.[0]; .[0] + length)]) then map(.value | cells)
    else error("approval table rows are not contiguous") end
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
# The spec's two checkpoint answers, read with the forms block of
# contracts/checkpoints.v1.md. A spec created before the cutoff and without
# the section was planned before checkpoints existed: it reads as early only.
CHECKPOINTS_SINCE=2026-11-21T00:00:00Z
here=$(cd -P "$(dirname "$0")" && pwd -P) || fail 'cannot find this script'
awk '/^```checkpoints-v1$/ {n++; on = 1; next} on && /^```$/ {on = 0; next} on {print}
     END {if (n != 1) exit 1}' "$here/../../../contracts/checkpoints.v1.md" > "$work/forms-raw" 2> /dev/null &&
  jq -es 'if length == 1 and (.[0] | type == "object")
       and all(.[0] | (.section, .section_like, .setext_text, .setext_underline, .section_end,
                       .fence, .one_way_door, .user_visible); type == "string")
    then .[0] else error("bad forms") end' "$work/forms-raw" > "$work/forms.json" 2> /dev/null ||
  fail 'cannot read the checkpoint forms from contracts/checkpoints.v1.md'
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
' "$work/graph" 2> /dev/null) || fail "cannot read spec #$spec's body and creation time"
case $reading in
  answered | absent) ;;
  absent-new) fail "spec #$spec has no ## Checkpoints section; a spec created on or after $CHECKPOINTS_SINCE needs both answers (contracts/checkpoints.v1.md)" ;;
  *) fail "spec #$spec's checkpoints are invalid (${reading#invalid }); write both answers as contracts/checkpoints.v1.md says" ;;
esac
echo "check-approval.sh: #$spec approval table is valid"
