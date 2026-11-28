# Verdict format: Class, Late, pre-existing and Disproved

This page is the contract for four additions to the report of [the skill's step 4](../SKILL.md#4-report) and of [re-checks](re-checks.md). It adds line forms and one grade; it changes nothing about when a finding blocks. A finding still blocks only with its `User path:` or `Risk:` line, and there are no other blocker grades.

## Class

Every `[blocking]` finding carries exactly one line under it, among its indented lines:

- `Class: <word>`, with one word from the list below, or
- `Class: other: <word>`, with one lowercase word (letters and `-`) when none fits.

The class names what every instance of the cause shares, so the builder can fix the whole class, not one line. One cause is one finding, whatever the number of places it shows; two causes are two findings, each with its class. A blocker keeps its class word in every later report that gives it a status. `[polish]` and `[pre-existing]` findings carry no `Class:` line.

| Word | What every instance shares |
| --- | --- |
| `input` | Outside data read in a shape, type or value the code doesn't check |
| `error-path` | A failure, exit status or partial result handled wrong or reported as success |
| `guard` | A check, allowlist, detector or default that lets through what it can't recognise |
| `output` | What a caller, log or public record sees: wrong, raw or private text |
| `state` | Ordering, retries, repeats, locks or stale reads |
| `files` | A path, write, overwrite or delete of a file the code doesn't own |
| `process` | A child process, shell command, argument or environment |
| `credential` | A token, key, identity or permission used, kept or shown wrongly |

## Late

At a re-check, a new finding whose `file:line` sits in code unchanged between the first verdict's head and this head carries one line under it:

- `Late: <why the first review missed it>`

It is graded `[pre-existing]`. The one exception is a late finding with a `Risk:` line (security, privacy or data loss): it stays `[blocking]`, keeps its `Late:` line and takes a `Class:` like any blocker. A first review has no late findings.

## Pre-existing

`[pre-existing]` is a grade beside `[blocking]` and `[polish]`, for a late finding without `Risk:`. It never blocks, never holds the verdict, asks the builder for nothing, and costs no round. It is filed like polish, with `review.py follow-up`, and its finding line ends `Pre-existing issue: #<n>.`; in every later report its status is that same `Pre-existing issue: #<n>.` A re-check that holds any back says so in the count line [re-checks](re-checks.md) gives, `<n> findings on unchanged code held back as pre-existing.`

## Disproved

Before posting, the reviewer tries to disprove every candidate finding and drops each one it can't prove. Every report, first verdict or re-check, carries exactly one line, as its own paragraph before `Checked:`:

- `Disproved: <n> candidate findings dropped.`

`<n>` is a whole number: `0`, or digits with no leading zero. The words stay the same for every `<n>`, `1` included.

## Examples

Synthetic first verdict: Pantry ticket #41 under spec #38, pull request #57, whose description lists one ruling.

```md
VERDICT: CHANGES at 4b1f0c9e2d7a5b3c8f6e1d0a9b2c4e7f5a3d1c08

Full review by Codex, Sol 6.2, Medium. CI green on this commit: build, test.

Intent: `pantry export` writes the whole cookbook to one zip and refuses to overwrite an existing file.

- **R1 [blocking]** `src/export.rs:48` (Spec) An existing `cookbook.zip` is overwritten. Fix: open it with `create_new(true)` and exit 3.
  Class: files
  User path: a cook exports twice in one day; the second export silently replaces the first.
  Shows the break: `touch cookbook.zip && pantry export; echo $?` printed `0`; the ticket needs `3`. Rerun at this commit: same.
- **R2 [polish]** `src/cli.rs:30` (Sweep) The help says "zip archive file"; the glossary's word is "export". Fix: "Write the cookbook as one export." Polish issue: #58.

- **Ruling 1** upheld: the importer reads `photos/` in every export (`src/import.rs:14`).

Disproved: 2 candidate findings dropped.

Checked: Standards (`AGENTS.md`, `docs/agents/`, ADR 0002), Spec (#41, spec #38), full sweep. Ran: `cargo test` (31 passed); R1's command; the test with the change undone (fails, as it should).

Next: the builder fixes or disputes R1 once, then one re-check.
```

Synthetic re-check, after the builder fixed R1 at `9e8d7c6` by changing only `src/export.rs`:

```md
VERDICT: CHANGES at 9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2f1e0d

Re-check of R1 and the code changed since 4b1f0c9, by Codex, Sol 6.2, Medium. CI green on this commit: build, test.

Intent: `pantry export` writes the whole cookbook to one zip and refuses to overwrite an existing file.

- **R1 [blocking]** resolved at 9e8d7c6: R1's command now prints `3`, and `cookbook.zip` is unchanged.
  Class: files
- **R2 [polish]** Polish issue: #58.
- **R3 [pre-existing]** `src/import.rs:22` (Sweep) An export with no `photos/` folder imports with a blank cover. Fix: use the default cover. Pre-existing issue: #61.
  Late: the first review read the importer only for Ruling 1's `photos/` path.
- **R4 [blocking]** `src/share.rs:9` (Sweep) The share link puts the cook's session token in the URL. Fix: send it in a header.
  Late: the first review took `src/share.rs` as outside the export and never opened it.
  Class: credential
  Risk: privacy: anyone the link is sent to can act as the cook.
  Shows the break: `pantry share --dry-run` printed `https://example.test/c?token=synthetic`. Rerun at this commit: same.

- **Ruling 1** upheld: the importer reads `photos/` in every export (`src/import.rs:14`).

1 findings on unchanged code held back as pre-existing.

Disproved: 1 candidate findings dropped.

Checked: R1 and `git diff 4b1f0c9 9e8d7c6` with the three checks. Ran: R1's command (prints `3`); `cargo test` (33 passed).

Next: a fresh, stronger builder fixes R4 once, then one final check.
```
