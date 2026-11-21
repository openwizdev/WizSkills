# OpenWiz comments contract, version 1 (`openwiz.comments.v1`)

Which comments stay in our code, how CI keeps new ones out, and how a repository's comment lines are counted, BEFORE and AFTER, the same way everywhere. The checker is [`tools/comment-check/check.py`](../tools/comment-check/check.py) (standard-library Python, one file); the count report's schema is [comments.v1.schema.json](comments.v1.schema.json); the fixtures are in [`fixtures/comments/`](fixtures/comments/), and `tools/comment-check/test_check.py` proves the checker against them.

**Contract and checker first** (#1816, CC1 of spec #1815). Each repository's own ticket (CC2, CC6, CC8, CC9, CC11, CC12) carries a byte-identical copy of this file and the checker and wires the diff mode into its CI; all but CC2 also cut that repository's comments, and CC3 to CC5 cut OpenWiz's by area; CC7 gives review-ticket its comment pass; CC10 draws the count report in the war room.

Authority: spec #1815, from Jake's comment-cut decisions (J238, C1 to C3), 2026-11-19 and 2026-11-20 (private record: the [pointer](open-development.v1.md#the-pointer) to issue 3065, comment 7034782715).

## Words

| Word | Meaning here |
| --- | --- |
| **Comment** | Text the language ignores: a line comment, a block comment, a doc comment, or a Python string that stands alone as a statement (a docstring included). Text inside a string literal is never a comment, even when it holds code with comments of its own. |
| **Comment line** | A line that holds any part of a comment, whole or trailing code. |
| **Block** | One trailing comment, or a run of whole-line comments on consecutive lines of one kind (doc or not). A multi-line block comment or docstring is one block. The checker judges blocks, never single lines. |
| **Added line** | A line the pull request adds or changes, from `git diff <base>...<head>`. |
| **Allowed kind** | A block the checker lets in, below. Every other block is disallowed. |
| **Escape tag** | `comment-ok: <reason>`, the one way to keep a block that is none of the allowed kinds. |
| **Tool directive** | A comment a tool reads to run or build the code. It is code, not a comment. |

## What stays

Only these kinds. The checker reads each one from its form, so the form is the rule: a block that means one of these but lacks its form fails.

| Kind | The form the checker reads | Example |
| --- | --- | --- |
| Licence or notice header | `SPDX-License-Identifier:`, `Copyright` or `Licensed under` in a block with no code before it in the file (a shebang or encoding line is not code) | `// SPDX-License-Identifier: MIT` |
| A constraint from outside our code | The block starts `External:` and holds a link to something that isn't ours (not `github.com/openwizdev/` or `github.com/jparker2006/`) | `# External: the vendor API rounds timeouts down, https://example.com/vendor/issues/7` |
| Public API docs a published documentation build renders | A doc comment of its own language (Rust `///`, `//!`, `/** */`, `/*! */`; JavaScript and TypeScript `/** */` only; Python's standalone strings, docstrings included; CSS has none) in a path the repository names with `--docs`. A repository with no published documentation build names none | `/// Returns the answer.` under `--docs crates/sdk/` |
| A security or data-loss warning | The block starts `SECURITY:`, `SAFETY:`, `PRIVACY:` or `DATA LOSS:` and says something after it | `// SAFETY: the buffer outlives every reader.` |
| A private-record pointer | The block holds a pointer in the [open development contract's form](open-development.v1.md#the-pointer) | `# Private record: https://github.com/jparker2006/<private repository>/issues/9001#issuecomment-9000000001`, with the private repository's name in place of `<private repository>` |

The form proves only the shape. Whether the outside constraint is real, the warning true and the docs really published is the reviewer's to judge (CC7's comment pass); a block that wears a form it hasn't earned is a review finding.

## Meaning first

Adapted from pstack's `/no-comments` (Lauren Tan, MIT), in our own words:

1. **When unsure, the comment goes.** Keeping a comment needs a reason from the list above; doubt is not one.
2. **A surprise in our own code is a refactor, not a comment.** Rename it, extract it, give it a type or write the test that pins it, so the code says it without prose.
3. **"Important" and "do not remove" are leads, not proof.** Read the code the comment guards and check the claim before keeping or deleting it.
4. **A constraint comment becomes a check.** If a comment guards a rule (keep this order, never call that first), encode the rule as a type, a test or a CI check, then delete the comment.
5. **A suppressed correctness lint is a bug to fix.** Remove the suppression and fix the cause; a switch survives only for a style rule or a rule that is wrong for this line, with its reason.
6. **Nothing that carried meaning is lost.** A comment that told the reader something true becomes a name, a test or a check before it is deleted, and the cut's pull request lists each one; the check or test is red first.

Our addition: private-record pointers and privacy warnings stay, so the open development contract keeps working.

## The escape tag

For the rare real exception none of the kinds covers, a block starts with the tag and its reason:

```text
# comment-ok: the synthetic runner reads this line as its job name
```

One form: `comment-ok:` at the start of the block's first line, then a reason of at least one non-space character. `comment-ok:` with nothing after it fails as `escape-tag-reason`. The reason is for the reviewer: a tag whose reason doesn't hold up is a review finding.

## Tool directives are code

These are neither counted nor checked:

- A shebang on line 1 (`#!/usr/bin/env python3`), and a Python encoding line on line 1 or 2 (`# -*- coding: utf-8 -*-`).
- A lint or formatter switch **with its reason**: the comment starts with one of `noqa`, `type: ignore`, `pragma:`, `pylint:`, `fmt: off|on|skip`, `ruff:`, `mypy:`, `pyright:`, `isort:`, `eslint`, `eslint-disable`, `eslint-enable`, `prettier-ignore`, `@ts-ignore`, `@ts-expect-error`, `@ts-nocheck`, `biome-ignore`, `shellcheck `, `yamllint `, `stylelint-disable`, `stylelint-enable`, `istanbul ignore`, `c8 ignore` or `v8 ignore`, and gives a reason after ` -- ` or a second ` # `, each followed by a space and then the reason: `# shellcheck disable=SC2086 -- word splitting is wanted here`. The same switch without a reason (or with `#reason` and no space) is a comment and fails as `directive-reason`. Only real comments are switches: a Python string that reads like one is a standalone string, counted and judged as a comment.
- A pinned GitHub Action's version, which update tools read: a line whose only value is a `uses:` field, plain or quoted, `uses: owner/action@<40 hex digits> # v7.0.1`, in a workflow (under `.github/workflows/`) or an action manifest (`action.yml`, `action.yaml`). Elsewhere it is a comment.

Rust's `#[allow(...)]` and `#![allow(...)]` are attributes, not comments: Clippy's `allow_attributes_without_reason` makes each state its reason (CC2).

## What counts as a comment

| Language | Files | Comments | Not comments |
| --- | --- | --- | --- |
| Rust | `.rs` | `//`, `///`, `//!`, `/* */` (nested), `/** */`, `/*! */` | strings, raw strings `r#"..."#`, byte and C strings, char literals, lifetimes, attributes |
| Python | `.py`, `.pyi`, extensionless with a `python` shebang | `#` comments (Python's own tokenizer) and every string that stands alone as a statement (Python's own parser), docstrings included | strings in expressions; a file that doesn't parse is read with the TOML rules |
| Shell | `.sh`, `.bash`, extensionless with a `sh`, `bash`, `dash` or `zsh` shebang | `#` starting a word (an escaped space doesn't end a word) | quoted text, `$#`, `${#x}`, here-documents (`<<`, never a `<<<` here-string), arithmetic `$(( ))`, `(( ))` and `$[ ]` |
| YAML | `.yml`, `.yaml` | `#` at a line's start or after a space, outside quotes; the shell rules inside a `run:` block scalar | other block scalars' content; quoted text, including a quoted value that runs over several lines (a quote opens only where a value starts, never inside a plain value) |
| TOML | `.toml` | `#` outside strings | basic and literal strings; multi-line strings, including a closing run of four or five quotes |
| JavaScript, TypeScript | `.js`, `.mjs`, `.cjs`, `.jsx`, extensionless with a `node` shebang; `.ts`, `.mts`, `.cts`, `.tsx` | `//`, `/* */`, `/** */` | strings, template literals (with `${}` inside), regular expression literals |
| CSS | `.css` | `/* */` | strings |
| HTML | `.html`, `.htm` | `<!-- -->` in text; the CSS rules inside `<style>`; the JavaScript rules inside a `<script>` whose own `type` attribute is absent, empty, `module` or a JavaScript type | tags and their attributes (quoted values included); other `<script>` types (JSON, templates), escaped text |

Every other file (Markdown and other prose, JSON, lock files) has no comments here: prose is cut by the cleanup waves, not this contract.

## What is excluded

Excluded files are never counted and never fail:

- **Vendored:** any path with a folder named `vendor`, `vendored`, `third_party`, `third-party` or `node_modules`, and any path `.gitattributes` marks `linguist-vendored`.
- **Generated:** `*.min.js`, `*.min.css`, a file with `@generated` or `DO NOT EDIT` in its first five lines, and any path `.gitattributes` marks `linguist-generated`.
- **Licence files:** `LICENSE`, `LICENCE`, `COPYING` and `NOTICE`, with any extension or suffix.
- **This contract's fixtures:** any path under a `fixtures/comments/` folder, as they plant disallowed comments on purpose.
- **A repository's own exclusions,** passed as `--exclude <glob>` (repeatable; `*` crosses folders, a trailing `/` names a folder). The repository's CI names each one, and its pull request says why.

## Diff mode, for CI

```sh
python3 -I tools/comment-check/check.py diff --base <base rev> [--head <rev>] [--docs <path>]... [--exclude <glob>]...
```

It reads every file the pull request adds or changes at `--head` (default `HEAD`), judges whole files so that a block comment's middle line is read correctly, and reports each disallowed block that touches an added line, at its first added line:

```text
src/lib.rs:18: comment: a comment outside the allowed kinds: delete it, or turn what it meant into a name, a test or a check
```

The reasons are `comment`, `escape-tag-reason`, `external-link`, `directive-reason`, and `unreadable` for a changed file in a listed language that isn't UTF-8 text (it fails rather than going unread). It exits 0 when nothing fails, 1 with one line per failure on stdout, and 2 when Git can't read the revisions or a blob it named. A path with a control character or a byte that isn't UTF-8 is printed as Git quotes it (`"odd\nname.py"`, `"\377x.py"`); every other path is printed as it is. Paths reach Git NUL-delimited and as literal pathspecs, so no file name escapes the check. Old comments never fail a pull request: a block fails only when the pull request adds or changes one of its lines.

## Count mode and its report

```sh
python3 -I tools/comment-check/check.py count [--before <rev>] [--at <rev>] [--by-file] [--docs <path>]... [--exclude <glob>]... [<path>...]
```

It counts the UTF-8 text files Git tracks at `--at` (default `HEAD`), limited to the paths given (all when none), and, with `--before`, the same paths at that revision in the same way. It reads only Git's objects, so BEFORE and AFTER come from one checkout and an untracked file never counts. It prints one JSON report ([schema](comments.v1.schema.json)):

| Field | What |
| --- | --- |
| `schema` | Always `openwiz.comments.v1` |
| `paths`, `docs`, `exclude` | The arguments the counts were taken with; a cut reports BEFORE and AFTER with the same ones |
| `before` | The tally at `--before`, or `null` |
| `after` | The tally at `--at` |
| `<tally>.rev` | The full commit id counted |
| `<tally>.files` | Files counted: a listed language, not excluded |
| `<tally>.comment_lines` | Comment lines in those files, allowed kinds included |
| `<tally>.disallowed_lines` | Lines of blocks that would fail the diff mode: what is left to cut |
| `<tally>.languages` | Per language that has a counted file: its `files` and `comment_lines` |
| `<tally>.by_file` | With `--by-file`, every counted file with at least one comment line and its count, keyed by its path as the diff mode prints it |

A cut's pull request reports `before.comment_lines` and `after.comment_lines` for its area, from one run with `--before <the base it branched from>`. The war room reads `after.comment_lines` per repository.

## Carrying the checker

Every repository carries `contracts/comments.v1.md` and `tools/comment-check/check.py` byte-identical to OpenWiz's; the schema, fixtures and tests travel when the repository wants the proofs. A change goes to OpenWiz first, as a new ticket, and the copies follow it byte for byte. Each repository's CI runs the diff mode against the pull request's base, with its own `--docs` and `--exclude`, and names them in its workflow.

## Gaps

- The checker reads forms, not meaning: a false `External:` or a stale warning passes it. CC7's review pass reads the meaning.
- Comments inside string literals (a script held in a Rust raw string or a JavaScript template literal) are not seen. YAML block scalars other than `run:` are treated as text.
- Shell's reader fails safe: a double-quoted command substitution it can't be sure of (one holding a backtick, `case`, a here-document or an unquoted inner `$(`) holds no comment, nor does the rest of the line its quote closes on, and a file that ends inside a quote or a quoted substitution has no comment from its first quoted substitution on. A real comment there goes unchecked and uncounted, because failing valid shell costs more than missing a comment the reviewer still reads.
- JavaScript's `/` is read as a regular expression after an operator, an opening bracket, `}` or a keyword such as `return`, and as division otherwise; rare code can fool it. JSX text is read as code, so a `//` in it reads as a comment.
- `.gitattributes` marks are read with `git check-attr --source`, Git 2.40 or later; an older Git reads none.

## Credit

The rules under "Meaning first" are adapted from the `no-comments` skill and its `comment-sicko` agent in pstack (github.com/cursor/plugins, `pstack/skills/no-comments/` and `pstack/agents/comment-sicko.md`), by Lauren Tan, under the MIT License, and her talk "All Code Is Slop (Except Mine)" (AI Engineer, 2026-11-14). No text is copied; the persona is left out, and private-record pointers are our addition.
