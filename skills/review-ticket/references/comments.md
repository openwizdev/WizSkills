# The comment pass

Read this when the diff adds or changes a comment. The project's comments contract (`contracts/comments.v1.md`, `openwiz.comments.v1`) decides what counts as a comment in each language and which kinds stay; this pass judges what its checker can't: whether a comment that wears an allowed form has earned it, and what every other comment should have been instead.

## What it reads

Only the pull request's diff: the comment lines it adds or changes between `origin/<base>` and `<head>`, with the code around each one. A comment the diff doesn't touch is never a finding, however stale; the pass is not a sweep of the repository.

Start with the helper. It runs the reviewed repository's own comments checker, the one the contract has every repository carry in its tools/comment-check folder, taken from the pull request's **base** revision (never the head or the checkout, which the pull request controls), in diff mode, so what counts as a comment, a block and an excluded file is exactly what the contract and CI say:

```sh
python3 -I <this skill's folder>/scripts/comments.py --base origin/<base> --head <head> [--checker <path>] [--docs <published path>]... [--exclude <glob>]...
```

Run it from the project checkout (or pass `--repo <checkout>`); pass the same `--docs` and `--exclude` the repository's CI names. `--checker` runs a trusted checker kept outside the reviewed checkout instead; one inside it is refused. It prints one `<file>:<line>: <kind>: <the line> Fix: <the code fix>.` per block the checker reports, then one `check <file>:<line>: <kind>: <the line>` per added line that wears an allowed form, and exits 1 with findings, 0 without, 2 when Git or the checker fails or a `--checker` is refused. Its kinds are `justification`, `workaround`, `suppression`, `external-link`, `escape-tag-reason`, `comment` and `unreadable`; the kind is read from the reported line, so read the whole block before you report it. Each `check` line is yours to judge, below.

When the base revision has no checker and no `--checker` is given, it prints one `no checker:` line and exits 3. Then read the diff's comments yourself against the kinds below, and never guess what the checker would have said.

## What stays

Only these kinds, each in the form the contract names:

| Kind | Form | Earned when |
| --- | --- | --- |
| Licence or notice header | `SPDX-License-Identifier:`, `Copyright` or `Licensed under`, before any code | It is the file's real licence |
| A constraint from outside our code | Starts `External:` with a link to something that isn't ours | The link shows the constraint (an API quirk, a platform bug) and our code can't remove it |
| Public API docs | The language's doc comment, in a path a published documentation build renders | That build exists and renders this path |
| A security or data-loss warning | Starts `SECURITY:`, `SAFETY:`, `PRIVACY:` or `DATA LOSS:` | It is true of the code it sits on |
| A private-record pointer | The open-development contract's pointer form | It points at the record the decision lives in |
| The escape tag | Starts `comment-ok: <reason>` | The reason names something none of the kinds covers and no name, type, test or check could say |

A tool directive (a shebang, an encoding line, a lint or formatter switch with ` -- <reason>`, a pinned action's version) is code, not a comment, but a switch is still judged below.

## What is a finding

Each of these, on a line the diff adds or changes, is one finding:

- **A justification comment:** it explains why the code is the way it is ("we do this because", "needed so that", "kept for", "intentional"). If the code surprises a reader, the fix is a clearer name, an extracted function, a type or a test that pins the behaviour; otherwise delete it.
- **A workaround comment:** it excuses a bug, hack, ordering rule or temporary state in our own code ("workaround for", "hack", "for now", "TODO", "don't move this"). The fix is the cause: fix it, or encode the rule as a type, test or check (red first) and delete the comment. "Important" and "do not remove" are leads: check what they guard before naming the fix.
- **An unjustified suppression:** a lint, type or test switch (`# noqa`, `# type: ignore`, `// eslint-disable`, `#[allow(...)]`, a skipped test) on a correctness rule, or with a reason that doesn't hold. The fix is to remove the switch and fix what it hid. A style rule or a rule wrong for that one line may keep its switch with a reason that holds.
- **A form not earned:** an `External:` whose link doesn't show the constraint or whose constraint is in our code, a warning that isn't true, docs in a path nothing publishes, or a `comment-ok:` whose reason a name, test or check could carry. The fix is the one for the kind of comment it really is.
- **A comment that restates the code** or narrates the change. The fix is to delete it.

Write each as `<file>:<line> (Standards) <what the comment says or hides>. Fix: <the name, extraction, type, test, check or deletion>`. The fix changes the code or removes the comment: never "reword", "shorten" or "clarify the comment". When the comment carried meaning, say where that meaning goes before it is deleted.

Grade it as step 3 says. Most are polish; a suppression or a false warning that hides a real-user break or a security, privacy or data-loss risk blocks with its line. A diff that adds only allowed kinds, each earned, gets no comment finding.

Credit: the rules above adapt Lauren Tan's `no-comments` skill (pstack, MIT; her notice is in [NOTICES.md](../NOTICES.md)), in our own words.
