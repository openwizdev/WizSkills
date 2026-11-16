#!/bin/sh
# WizSkills installer (openwiz.wizskills.v1).
#
#   sh install.sh --version <version> --dest <dir>
#
# Fetches only the tag v<version> from https://github.com/openwizdev/WizSkills.git,
# verifies its release record (the annotated tag's JSON message: schema, version,
# commit, tree), the tagged tree, plugin.json and CHANGELOG.md, then publishes a
# detached checkout at <dir> in one rename. An existing <dir> must already be that exact,
# clean release: matching is a no-op, anything else is refused unchanged.
# Needs a POSIX shell and Git. Never defaults to latest or main, never forces,
# never retries, never changes the caller's Git configuration.
#
# Exit codes: 0 installed or verified no-op; 1 verification or state refusal;
# 2 invalid arguments or version; 3 fetch or local I/O failure.
set -u
umask 022
LC_ALL=C
export LC_ALL
REMOTE='https://github.com/openwizdev/WizSkills.git'
SCHEMA='openwiz.wizskills.release.v1'
VERSION_ERE='(0\.[1-9][0-9]*|[1-9][0-9]*\.(0|[1-9][0-9]*))\.(0|[1-9][0-9]*)(-(0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)(\.(0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?(\+[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?'
OID_ERE='[0-9a-f]{40}'
# The caller's repository environment must not redirect any Git operation here.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY \
    GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_COMMON_DIR GIT_NAMESPACE GIT_PREFIX
GIT_TERMINAL_PROMPT=0
GIT_OPTIONAL_LOCKS=0
GIT_NO_REPLACE_OBJECTS=1
export GIT_TERMINAL_PROMPT GIT_OPTIONAL_LOCKS GIT_NO_REPLACE_OBJECTS

staging=''
cleanup() {
    if [ -n "$staging" ]; then
        rm -rf "$staging"
    fi
}
trap cleanup EXIT
trap 'exit 3' HUP INT TERM

# Diagnostics are fixed reasons: never paths, payloads or upstream output.
fail() {
    printf 'install.sh: refused: %s\n' "$2" >&2
    exit "$1"
}

# Every Git call: no hooks, no fsmonitor, no line-ending or filter rewriting.
g() {
    git -c core.hooksPath=/dev/null -c core.fsmonitor=false -c core.autocrlf=false \
        -c core.attributesFile=/dev/null \
        -c core.eol=lf -c core.symlinks=true -c core.filemode=true \
        -c core.untrackedCache=false -c core.splitIndex=false -c gc.auto=0 \
        -c advice.detachedHead=false "$@"
}

matches() { # matches <ERE> <value>: the whole single-line value matches.
    case $2 in *'
'*) return 1 ;; esac
    printf '%s\n' "$2" | grep -Eqx -- "$1"
}

# 1. Arguments: each exactly once, nothing else.
version=''
dest=''
seen_version=0
seen_dest=0
while [ $# -gt 0 ]; do
    case $1 in
    --version)
        [ $# -ge 2 ] && [ $seen_version -eq 0 ] || fail 2 'usage: install.sh --version <version> --dest <dir>'
        version=$2
        seen_version=1
        shift 2
        ;;
    --dest)
        [ $# -ge 2 ] && [ $seen_dest -eq 0 ] || fail 2 'usage: install.sh --version <version> --dest <dir>'
        dest=$2
        seen_dest=1
        shift 2
        ;;
    *) fail 2 'usage: install.sh --version <version> --dest <dir>' ;;
    esac
done
[ $seen_version -eq 1 ] && [ $seen_dest -eq 1 ] || fail 2 'usage: install.sh --version <version> --dest <dir>'
matches "$VERSION_ERE" "$version" || fail 2 'invalid version'
[ -n "$dest" ] || fail 2 'invalid destination'
case $dest in *'
'*) fail 2 'invalid destination' ;; esac
command -v git >/dev/null 2>&1 || fail 3 'git not found'

# Resolve the destination explicitly: absolute, no dot segments, no symlink anywhere.
case $dest in /*) ;; *) dest=$(pwd -P)/$dest || fail 3 'unreadable working directory' ;; esac
resolved=''
rest=$dest
while [ -n "$rest" ]; do
    part=${rest%%/*}
    case $rest in */*) rest=${rest#*/} ;; *) rest='' ;; esac
    case $part in
    '') continue ;;
    . | ..) fail 2 'invalid destination' ;;
    esac
    resolved=$resolved/$part
    if [ -L "$resolved" ]; then
        fail 1 'symlink in destination path'
    fi
done
[ -n "$resolved" ] || fail 2 'invalid destination'
dest=$resolved
parent=${dest%/*}
[ -n "$parent" ] || parent=/
[ -d "$parent" ] || fail 1 'destination parent is not an existing directory'
existing=0
if [ -e "$dest" ]; then
    [ -d "$dest" ] || fail 1 'destination is not a directory'
    existing=1
fi

# 2. Fetch the one tag into isolated staging beside the destination, then verify.
staging=$(mktemp -d "$parent/.wizskills-install.XXXXXX") || {
    staging=''
    fail 3 'cannot create staging'
}
# A unique name: if a plain mv ever moves it into a foreign directory, it
# cannot meet or replace an entry already there.
work=$staging/${staging##*/}
objects=$staging/objects
g init -q "$work" >/dev/null 2>&1 || fail 3 'cannot create staging'
mkdir "$objects" || fail 3 'cannot create staging'
tag=v$version
g -C "$work" fetch --quiet --no-tags --no-recurse-submodules --no-write-fetch-head \
    "$REMOTE" "refs/tags/$tag:refs/tags/$tag" >/dev/null 2>&1 || fail 3 'fetch failed'

[ "$(g -C "$work" cat-file -t "refs/tags/$tag" 2>/dev/null)" = tag ] || fail 1 'release tag is not annotated'
tag_oid=$(g -C "$work" rev-parse --verify --quiet "refs/tags/$tag") || fail 1 'unreadable release tag'
matches "$OID_ERE" "$tag_oid" || fail 1 'unreadable release tag'
tag_body=$staging/tag
g -C "$work" cat-file tag "$tag_oid" >"$tag_body" 2>/dev/null || fail 1 'unreadable release tag'
# Header lines, then a blank line, then the message: the record, nothing else.
head_object=$(sed -n '1s/^object //p' "$tag_body")
head_type=$(sed -n '2s/^type //p' "$tag_body")
head_tag=$(sed -n '3s/^tag //p' "$tag_body")
[ "$head_type" = commit ] && [ "$head_tag" = "$tag" ] || fail 1 'release tag does not directly name a commit'
matches "$OID_ERE" "$head_object" || fail 1 'release tag does not directly name a commit'
message=$(sed '1,/^$/d' "$tag_body" | tr '\n\r\t' '   ')

# The record: one JSON object of exactly four distinct string members, values
# without escapes. Whitespace is allowed only between tokens.
ws='[[:space:]]*'
member="$ws\"[a-z]+\"$ws:$ws\"[^\"\\\\]*\"$ws"
matches "$ws\\{$member(,$member){3}\\}$ws" "$message" || fail 1 'malformed release record'
pairs=$(printf '%s\n' "$message" | sed -e 's/^[[:space:]]*{//' -e 's/}[[:space:]]*$//' | tr ',' '\n')
record_schema=''
record_version=''
record_commit=''
record_tree=''
count=0
nl='
'
old_ifs=$IFS
IFS=$nl
for pair in $pairs; do
    key=$(printf '%s\n' "$pair" | sed 's/^[[:space:]]*"\([a-z]*\)".*$/\1/')
    value=$(printf '%s\n' "$pair" | sed 's/^[^:]*:[[:space:]]*"\([^"]*\)"[[:space:]]*$/\1/')
    count=$((count + 1))
    case $key in
    schema) [ -z "$record_schema" ] && record_schema=$value || fail 1 'malformed release record' ;;
    version) [ -z "$record_version" ] && record_version=$value || fail 1 'malformed release record' ;;
    commit) [ -z "$record_commit" ] && record_commit=$value || fail 1 'malformed release record' ;;
    tree) [ -z "$record_tree" ] && record_tree=$value || fail 1 'malformed release record' ;;
    *) fail 1 'malformed release record' ;;
    esac
done
IFS=$old_ifs
[ $count -eq 4 ] || fail 1 'malformed release record'
[ "$record_schema" = "$SCHEMA" ] || fail 1 'malformed release record'
[ "$record_version" = "$version" ] || fail 1 'release record names another version'
matches "$OID_ERE" "$record_commit" && matches "$OID_ERE" "$record_tree" || fail 1 'malformed release record'
[ "$record_commit" = "$head_object" ] || fail 1 'release record does not match the tagged commit'
actual_tree=$(g -C "$work" rev-parse --verify --quiet "$record_commit^{tree}") || fail 1 'release record does not match the tagged commit'
[ "$actual_tree" = "$record_tree" ] || fail 1 'tree mismatch'

# worktree_tree <dir>: the tree of every path under <dir> outside its top-level
# .git, from raw bytes: no attributes, filters or line-ending conversion, and no
# Git special-path omissions. Objects go to scratch storage; <dir> is only read.
# A nested .git, an empty directory, a name with a newline or any other file
# type cannot be a release path and fails.
worktree_tree() {
    list=$staging/paths.$$
    index=$staging/index.$$
    rows=$staging/rows.$$
    rm -f "$list" "$index" "$rows"
    newline_names=$(cd "$1" && find . -name '*
*' -print) || return 1
    [ -z "$newline_names" ] || return 1
    (cd "$1" && find . -path ./.git -prune -o -print) >"$list" || return 1
    : >"$rows"
    while IFS= read -r path; do
        [ "$path" = . ] && continue
        rel=${path#./}
        case /$rel/ in */.git/*) return 1 ;; esac
        full=$1/$rel
        if [ -L "$full" ]; then
            mode=120000
            # Keep every target byte: a sentinel stops command substitution
            # trimming newlines, then drop only the one readlink appends.
            target=$(readlink "$full" && printf x) || return 1
            target=${target%x}
            target=${target%?}
            oid=$(printf '%s' "$target" | GIT_OBJECT_DIRECTORY=$objects \
                g -C "$work" hash-object --no-filters -w --stdin 2>/dev/null) || return 1
        elif [ -d "$full" ]; then
            [ -n "$(ls -A "$full")" ] || return 1
            continue
        elif [ -f "$full" ]; then
            if [ -n "$(find "$full" -prune -perm -0100 -print)" ]; then mode=100755; else mode=100644; fi
            oid=$(GIT_OBJECT_DIRECTORY=$objects g -C "$work" hash-object --no-filters -w -- "$full" 2>/dev/null) || return 1
        else
            return 1
        fi
        matches "$OID_ERE" "$oid" || return 1
        # NUL-terminated records: Git takes each path literally, never unquoted.
        printf '%s %s\t%s\000' "$mode" "$oid" "$rel" >>"$rows"
    done <"$list"
    GIT_INDEX_FILE=$index GIT_OBJECT_DIRECTORY=$objects \
        g -C "$work" update-index --add -z --index-info <"$rows" >/dev/null 2>&1 || return 1
    GIT_INDEX_FILE=$index GIT_OBJECT_DIRECTORY=$objects g -C "$work" write-tree 2>/dev/null
    status=$?
    rm -f "$list" "$index" "$rows"
    return $status
}

# plugin.json's one "version" member and the changelog's latest section agree.
check_package() {
    plugin=$1/.claude-plugin/plugin.json
    changelog=$1/CHANGELOG.md
    [ -f "$plugin" ] && [ -f "$changelog" ] || return 1
    [ "$(grep -c '"version"' "$plugin")" = 1 ] || return 1
    plugin_version=$(sed -n 's/^[[:space:]]*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)"[[:space:]]*,\{0,1\}[[:space:]]*$/\1/p' "$plugin")
    [ "$plugin_version" = "$version" ] || return 1
    [ "$(sed -n 1p "$changelog")" = '# Changelog' ] || return 1
    latest=$(sed -n '/^## /{p;q;}' "$changelog")
    matches "## $(printf '%s' "$version" | sed 's/[.+]/\\&/g') - [0-9]{4}-[0-9]{2}-[0-9]{2}" "$latest" || return 1
}

if [ $existing -eq 0 ]; then
    # 3. A missing destination: check out the release, verify every byte and mode.
    g -C "$work" checkout -q --detach "$record_commit" >/dev/null 2>&1 || fail 3 'checkout failed'
    [ "$(worktree_tree "$work")" = "$record_tree" ] || fail 1 'tree mismatch'
    check_package "$work" || fail 1 'plugin.json or CHANGELOG.md disagrees with the version'
    # Publish in one step: rename the verified checkout, beside the destination
    # on the same filesystem, to the destination. A reader sees no destination
    # or the complete install, never a partly filled directory.
    inode() { ls -di "$1" 2>/dev/null | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]].*//'; }
    staged=$(inode "$work")
    matches '[0-9]+' "$staged" || fail 3 'cannot identify the staged installation'
    if [ -e "$dest" ] || [ -L "$dest" ]; then
        fail 1 'destination appeared during installation'
    fi
    # GNU mv -T -n renames without replacing anything and never moves into a
    # directory that appeared meanwhile (renameat2 RENAME_NOREPLACE).
    mv -T -n "$work" "$dest" 2>/dev/null
    if [ -e "$work" ] || [ -L "$work" ]; then
        # Not renamed: a destination appeared, or this mv lacks -T (BSD).
        if [ -e "$dest" ] || [ -L "$dest" ]; then
            fail 1 'destination appeared during installation'
        fi
        # A plain mv renames to a missing destination in one step. If a
        # directory appeared just before it, mv moved the install inside it:
        # move it straight back and refuse, leaving that directory as it was.
        mv "$work" "$dest" 2>/dev/null
        if [ -e "$work" ] || [ -L "$work" ]; then
            if [ -e "$dest" ] || [ -L "$dest" ]; then
                fail 1 'destination appeared during installation'
            fi
            fail 3 'cannot publish the installation'
        fi
        inner=$dest/${work##*/}
        if [ "$(inode "$dest")" != "$staged" ] && [ "$(inode "$inner")" = "$staged" ]; then
            # Check the move back too. If it fails, never retry or delete
            # inside that directory: refuse, and say where this run's files are.
            if mv "$inner" "$work" 2>/dev/null && [ "$(inode "$work")" = "$staged" ] \
                && ! [ -e "$inner" ] && ! [ -L "$inner" ]; then
                fail 1 'destination appeared during installation'
            fi
            fail 1 'destination appeared during installation; could not move this install back out, so it is left in a .wizskills-install. folder inside the destination'
        fi
    fi
    [ "$(inode "$dest")" = "$staged" ] || fail 1 'destination appeared during installation'
    exit 0
fi

# 4. An existing destination: exactly this version, commit and tree, clean.
[ -d "$dest/.git" ] && [ ! -L "$dest/.git" ] || fail 1 'destination is not this release'
top=$(g -C "$dest" rev-parse --show-toplevel 2>/dev/null) || fail 1 'destination is not this release'
[ "$top" = "$dest" ] || fail 1 'destination is not this release'
[ "$(g -C "$dest" rev-parse --verify --quiet "refs/tags/$tag")" = "$tag_oid" ] || fail 1 'destination is not this release'
[ "$(g -C "$dest" rev-parse --verify --quiet HEAD)" = "$record_commit" ] || fail 1 'destination is not this release'
g -C "$dest" symbolic-ref -q HEAD >/dev/null 2>&1 && fail 1 'destination is not this release'
g -C "$dest" diff-index --cached --quiet "$record_commit" -- >/dev/null 2>&1 || fail 1 'destination is dirty'
[ "$(worktree_tree "$dest")" = "$record_tree" ] || fail 1 'destination is dirty'
check_package "$dest" || fail 1 'plugin.json or CHANGELOG.md disagrees with the version'
exit 0
