# Review-rounds bench

`bench.py` measures review rounds on merged pull requests, for spec openwizdev/OpenWiz#2484. It only reads: it sends its own fixed GraphQL `query` documents through `gh api graphql` with the signed-in account, and refuses to send any other document.

```sh
python3 -I tools/review-rounds/bench.py \
  --repo openwizdev/OpenWiz --repo openwizdev/WizSkills --repo openwizdev/WizSite \
  --repo openwizdev/WizRoom --repo openwizdev/WizMarket \
  --merged-from 2026-11-15T23:00Z --merged-to 2026-11-22T22:58Z [--opened-after <time>] \
  [--clone openwizdev/OpenWiz=<local clone> ...]
```

`--clone` names a local git clone for one `--repo`, used for the late measure and the diff size. The bench runs only `git diff` and `git cat-file -e` in it, with `--literal-pathspecs` and `--no-lazy-fetch`, so it never fetches, even in a partial clone, where an object it lacks makes that measure unknown. The clone must already hold every verdict head, for example after `git fetch origin '+refs/pull/*/head:refs/remotes/origin/pr/*'`.

It prints Markdown tables, then the same numbers as a fenced JSON block. It exits 1 with a `bench:` line when a read fails or a search can't be trusted, and 2 for bad arguments. Naming one repository twice, in any letter case (GitHub names are case-insensitive), is a bad argument.

## Definitions

- **Cohort:** PRs merged in the window, both ends included. With `--opened-after`, only PRs created after that time.
- **Round:** one comment whose body starts `VERDICT:`, by a record author (`openwiz[bot]` or `jparker2006`). Every PR comment is read, page by page.
- **`CHANGES` round:** a round whose first word is `CHANGES`. **APPROVE at first:** the earliest round is `APPROVE`. **Re-approval:** an `APPROVE` after an earlier `APPROVE` on the same PR.
- **Reviewed:** a PR with at least one round. The round and `CHANGES` statistics are over reviewed PRs. The median is the middle value (or the mean of the two middle values), and p90 is the nearest-rank 90th percentile.
- **New blocking finding:** a line `- **R<n> [blocking]** `<path>` ... (<Check>)`, where the check is Spec, Sweep or Standards. A finding carried over as `resolved` or `still open` has no path after its label, so it isn't counted again. The first round's findings are counted under the first review, and every later round's under re-checks.
- **Ticket PR:** a PR with a closing issue whose body has `Size: S.`, `Size: M.` or `Size: L.`. Every closing issue is read. A PR whose closing issues carry two sizes shows both (for example `LS`) and isn't in any single size's median.
- **Diff lines:** additions plus deletions. The bands are under 300, 300-599 and 600+, with 600+ also split into 600-999 and 1000+, to line up with the spec's BEFORE table.
- **Late finding:** a finding line `- **R<n> [blocking]** `<path>` ... (<Check>)` or `- **R<n> [pre-existing]** `<path>` ... (<Check>)` in a re-check, whose id had no such line in an earlier round. It counts once, at its first such line, in either grade, so a late finding regraded `[pre-existing]` still counts. The late share is late findings over first-review blockers plus late findings; the blocker totals above stay as they were. A verdict's head is the commit its `VERDICT: <word> at <commit>` header names.
- **Changed by the fix / unchanged since the first review:** for a late finding at `<file>:<line>` (or `<file>:<line>-<line>`), the bench runs `git diff <first verdict head> <its verdict head> -- <file>` in the local clone, with `<file>` a literal path, never a pattern. The finding is **changed** when that diff adds or rewrites any of its lines at its own head, so a file new since the first review counts as changed. It is **unchanged** when the diff leaves every one of its lines alone, even when the lines moved. It is **unknown** when no `--clone` is given, a finding names no line, a head is missing from the clone or the file is missing at its head. The diff is always read from the clone, never through GitHub.
- **Withdrawn blocker:** a blocking finding whose status line reads `- **R<n> [blocking]** withdrawn:` in any round, counted once per id. The withdrawn share is withdrawn blockers over all new blocking findings.
- **Polish issue:** an issue named by `Polish issue: #<n>` on a `- **R<id> [polish]**` line of a round. It is looked up in the repository of the PR's closing issues when they all share one repository, otherwise in the PR's own, with one GraphQL `issue` query. It counts only when it is bound to this PR and finding, as `review.py follow-up` files it: its title ends `(polish for #<ticket>, R<id>)`, where `#<ticket>` is one of the PR's closing issues in that repository and `R<id>` is a finding that named it, and its body says `Found in pull request <PR>` with this PR's number (`#<n>`, `<n>` or `<owner>/<name>#<n>`). An issue that is missing or not bound is **unknown**.
- **Ignored polish issue:** a polish issue that, 7 days after its PR merged, was open or was closed as not planned. Its state then comes from its close and reopen history: the last close or reopen at or before that time, with the close's reason. No event means open. A history that is longer than one page, doesn't end in the issue's current state, or has a close with no reason is **unknown**. A PR merged less than 7 days before the run is **not yet due**, and its issues aren't read. The ignored share is over polish issues that are due and known. **Withdrawn or ignored** is withdrawn blockers plus ignored polish issues, over blocking findings plus due, known polish issues. When a cohort has polish issues but none is due and known, it is unavailable: the JSON has `either_pct: null` and `pending` (`not yet due`, or `unknown` when none is pending), and the table prints that reason with the withdrawn share alone.
- **Diff size:** for each reviewed PR, `git diff --numstat -z --find-renames <base>...<head>` in the local clone, with the PR's `baseRefOid` and `headRefOid`. Lines are additions plus deletions, so a binary file adds a file and no lines. A moved file is one file with only its edited lines, and is a test or code by its new path. A **test path** has a directory named `test`, `tests`, `__tests__`, `testdata` or `fixtures`, a file name starting `test_`, or a name ending `_test.<ext>`, `.test.<ext>`, `_spec.<ext>` or `.spec.<ext>`. Tests inside a code file, such as a Rust `mod tests`, count as code. The table shows median lines and files per PR for code and tests, for each repository and for ticket PRs in the diff-line bands above. A PR without a clone or without both commits is **unknown**.
- **Worst PRs:** the 10 reviewed PRs with the most `CHANGES` rounds, then the most rounds.

A repository search is capped at 1,000 results. Over the cap, the bench stops and asks for a shorter window. It also stops if the search returns a PR twice or returns fewer PRs than it reported.

Tests: `env -u OPENWIZ_GITHUB_APP_KEY python3 -I -m unittest discover tools/review-rounds`.
