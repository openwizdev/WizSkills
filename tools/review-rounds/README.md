# Review-rounds bench

`bench.py` measures review rounds on merged pull requests, for spec openwizdev/OpenWiz#2484. It only reads: it sends its own fixed GraphQL `query` documents through `gh api graphql` with the signed-in account, and refuses to send any other document.

```sh
python3 -I tools/review-rounds/bench.py \
  --repo openwizdev/OpenWiz --repo openwizdev/WizSkills --repo openwizdev/WizSite \
  --repo openwizdev/WizRoom --repo openwizdev/WizMarket \
  --merged-from 2026-11-15T23:00Z --merged-to 2026-11-22T22:58Z [--opened-after <time>]
```

It prints Markdown tables, then the same numbers as a fenced JSON block. It exits 1 with a `bench:` line when a read fails or a search can't be trusted, and 2 for bad arguments.

## Definitions

- **Cohort:** PRs merged in the window, both ends included. With `--opened-after`, only PRs created after that time.
- **Round:** one comment whose body starts `VERDICT:`, by a record author (`openwiz[bot]` or `jparker2006`). Every PR comment is read, page by page.
- **`CHANGES` round:** a round whose first word is `CHANGES`. **APPROVE at first:** the earliest round is `APPROVE`. **Re-approval:** an `APPROVE` after an earlier `APPROVE` on the same PR.
- **Reviewed:** a PR with at least one round. The round and `CHANGES` statistics are over reviewed PRs. The median is the middle value (or the mean of the two middle values), and p90 is the nearest-rank 90th percentile.
- **New blocking finding:** a line `- **R<n> [blocking]** `<path>` ... (<Check>)`, where the check is Spec, Sweep or Standards. A finding carried over as `resolved` or `still open` has no path after its label, so it isn't counted again. The first round's findings are counted under the first review, and every later round's under re-checks.
- **Ticket PR:** a PR with a closing issue whose body has `Size: S.`, `Size: M.` or `Size: L.`. Every closing issue is read. A PR whose closing issues carry two sizes shows both (for example `LS`) and isn't in any single size's median.
- **Diff lines:** additions plus deletions. The bands are under 300, 300-599 and 600+, with 600+ also split into 600-999 and 1000+, to line up with the spec's BEFORE table.
- **Worst PRs:** the 10 reviewed PRs with the most `CHANGES` rounds, then the most rounds.

A repository search is capped at 1,000 results. Over the cap, the bench stops and asks for a shorter window. It also stops if the search returns a PR twice or returns fewer PRs than it reported.

Tests: `env -u OPENWIZ_GITHUB_APP_KEY python3 -I -m unittest discover tools/review-rounds`.
