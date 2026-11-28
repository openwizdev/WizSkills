# Dream cycle proof

## Prover role

Run `room-cli files wait` in the foreground on a copying Cloudroom workspace and continue in the same turn. Return the named gap if it fails. Read only the assigned batch or blind packet and its authorized sources. Your only output is the local scratch proof file and its private handoff to the controller.

For a delete or fix, re-run the supplied evidence using permitted read-only operations and test the best countercase. For deletes, include loop scripts, raw URLs, workflows, systemd units and retained records when checking consumers. Return `CONFIRMED` only when you can reproduce the claim and rule out that countercase. Use `PLAUSIBLE` for a material gap and `REJECTED` for contrary evidence. Preserve failed reads as unconfirmed with their reasons.

For a link, work blind. The packet contains an opaque ID, the link type's definition and just the ends with verbatim quotes. Open both ends, or all ends for a pattern. Independently name the decision, ticket, promise or row the connection changes, and the best reason it is not a link. Reject mere similarity. A supported connection whose consequence remains uncertain is `PLAUSIBLE`.

Write one [verdict JSONL](../../contracts/dream-cycle.v1.md#prover-verdict-line-defsverdict) row per ID, with read-only commands and short results in `evidence`. Put the independently named decision and best countercase in `reason`. Use `blind: true` for blind link judgments, and `changes_confirmed: true` only when the ends prove the decision you named. Use `blind: false` and `changes_confirmed: null` for non-links. Hand the file back privately without discussing it with other provers. Done when its bytes or the handoff gap reach the controller.

## Controller role: the link funnel

Use the configured private append-only ledger, or `ledger.jsonl` beside the dated runs in the private report path. Prepare the settings JSON for the programs with `repos` mapped to the pinned local clone paths and any configured `files`, `link_budget` and per-entity limits. Keep evidence snapshots and prior watermarks, when available, in the private run. Paths below are absolute, invoked from the skill folder.

For ticket ends, add `issues_file` and `prs_file` paths to each relevant `repos` entry. These private read snapshots are JSON lists with `number`, `state`, `title`, `body`, `updated_at` and any comments used as evidence. Retain closed rows for the program check. A failed or partial snapshot is unconfirmed, even if the readable rows support other links.

### Gate A and initial ranking

Run candidate generation. Use `--watermarks` when a verified prior watermark file is available. Program candidates supply ends and type, so fill the contract finding fields including the decision in `changes`. Add the scouts' candidates, normalize to unique IDs, then run the program check on their combined JSONL. Save its stdout, including `dropped` and `unconfirmed`, alongside the survivors file. Exit 2 means some inputs could not be read. Keep those gaps and send only survivors with readable ends.

```sh
python3 -I scripts/links.py candidates --settings <settings.json> --ledger <ledger.jsonl> --date <YYYY-MM-DD> --out <candidates.json>
python3 -I scripts/links.py check <combined-links.jsonl> --settings <settings.json> --ledger <ledger.jsonl> --out <survivors.jsonl>
python3 -I scripts/links.py score <survivors.jsonl> --out <initial-scores.json>
```

Rank says-vs-does and promise-to-work first, then use program scores and newest evidence within the tiers. Give blind proof only to link rows that survive the full merge. Route business links as `pillar-inbox` with the configured owner and `ticket: null` before rendering. The inboxes and any draft routes stay in the private run folder. Done when each selected link has a surviving, scored finding with an explicit owner and route.

### Blind waves and canaries

Dispatch provers from a different model family than the scouts. A program candidate uses the configured scout family as its separation baseline. Leave links unproven if no other-family prover is available. Use isolated workers with access to the authorized sources and the blind packet. Give each prover only the opaque ID, ends and quotes, and the definition from the contract. Keep the ID map, scout reasoning, `changes` hypothesis, score, route, other verdicts and canary truth on the controller side. Continue in waves within concurrency limits. Re-tell a prover who ends without its file and record any gap.

```sh
python3 -I scripts/links.py canaries --ledger <ledger.jsonl> --settings <settings.json> --seed <YYYY-MM-DD> --out <seeds.json>
```

Mix seeded known-true and known-junk links into each prover's work under distinct opaque IDs, including fresh provers. Confirm seed truth from independent evidence before using it. If enough seeds cannot be verified, record the gap and hold link confirmations. Reserve budget for seeds and second checks before sending first passes. Count all evaluated pairs against `link_budget` and report anything left over as unproven.

Score each prover against the seed key after the files arrive. Keep one private result per seed. A missing, wrong or invalid verdict is a miss, as is a wrong decision on a known-true seed. For `report`, create `report-canaries.json` with a `canaries` array of `{id, expected}` rows using the issued IDs and the seed's `expected_verdict`. Put coverage gaps or failed decision checks in the `missed` array as `{id, expected, actual}` rows, with the reasons in the private proof notes. Include seed verdicts with those same IDs in the report's verdict directory, never in its findings.

### Second read and final inputs

Re-rank provisional links by type tier and score. Give the top five, or all if there are fewer, to fresh provers from outside the scout family with shuffled evidence and new opaque IDs. They get the same blind fields. A second check must independently reach the same decision before that link can be confirmed. Preserve both raw judgments.

After collecting proofs, compare each independently named decision with the proposed `changes`. Map opaque IDs back to findings. Save exactly one effective verdict per link, with `changes_confirmed: true` only for an independently supported matching decision. Missing or split proof stays unproven or `PLAUSIBLE`. A canary miss caps link confirmations at `PLAUSIBLE`; keep the result in the report and out of ticket filing.

```sh
python3 -I scripts/links.py score <merged-links.jsonl> --verdicts <link-verdicts.jsonl> --out <scores.json>
python3 -I scripts/links.py ledger --ledger <ledger.jsonl> --settings <settings.json> --append <transitions.jsonl> --verdicts <link-verdicts.jsonl> --recheck --date <YYYY-MM-DD>
```

Use the `scored` array from `scores.json` as `report-scores.json` and the Gate A `dropped` array as `gate-a-drops.json`. Append the resulting accepted, rejected or later transitions using the contract's ledger fields. Use accepted only for fully proven links, including the canary gate and any second check. For a retry, compare the current state and skip transitions already recorded. Save the read-back ledger output and fold any unconfirmed reasons into the report inputs. Done when scores, canaries, effective verdicts and ledger state can be read back from the private run.
