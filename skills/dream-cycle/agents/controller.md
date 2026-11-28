# Controller commands and handoffs

Use the section for the step you are running or resuming.

## 1. Open or resume the run

Read the project instructions, its `docs/agents/dream-cycle.md`, [dream-cycle v1](../../../contracts/dream-cycle.v1.md) and its [schema](../../../contracts/dream-cycle.v1.schema.json). Take the repos, areas, business sources, windows, retained records, models and concurrency, scout and `link_budget` limits from settings. Missing required settings are a reported gap.

Use the dated folder under the configured private report path. Record the scope, pinned read inputs, dispatches, completed artifacts, issue receipts and summary receipt there. Resume the next missing step from verified artifacts. Use fresh staging directories for interrupted commands and save only completed outputs. Keep one controller for the run.

## 2. Inventory and scout

Use one clean read-only clone per repository and share that pinned checkout for local searches. From this skill's folder, replace angle-bracketed placeholders with the run's values. Use absolute paths for run inputs and outputs.

```sh
python3 -I scripts/inventory.py <clone> --days <days> --pr-idle-days <pr-idle-days> --limit <inventory-limit>
```

Save inventory JSON per repository. Exit 2 still carries partial results and `unconfirmed` reasons. Record absent output as an unconfirmed read. Dispatch one scout per configured repository, area or lens within the budget, with [scout.md](../scout.md), its scope, checkout and inventory slice only. Give each a distinct findings filename. Keep business lenses separate. Use the project's worker runner. On Cloudroom, use `room-cli thread spawn`, `room-cli thread tell` and `room-cli thread output`.

Re-tell any scout that ends its turn without its findings file. Send the same brief and output name, and wait for the file or a named gap. Use permitted private handoffs to collect bytes from separate sandboxes. Save those bytes under the assigned filename, or save a zero-byte file after an explicit empty-file receipt. Record the result in the run folder.

## 3. Check links and merge

For the link funnel follow the controller steps in [prover.md](../prover.md). Combine program candidates and scout links, complete their `changes` claims before the program check, and keep the program's drops. Reject any deletion of a record on the project's keep list. Pass only surviving links and scoped non-link findings to merge. Put one contract JSONL file per input in the fresh findings directory.

```sh
python3 -I scripts/dream.py merge <findings-dir> --out <merged.json> --batches-dir <fresh-batches-dir> --batches <count>
```

Start prover waves as scouts deliver usable findings. Early waves can merge their completed slices separately. Reuse a verdict after the full merge only if its winning finding and evidence still match. Send non-link rows to provers and use separate blind packets for links. Save drops and resolve missing verdicts or mark them unproven.

## 4. Render and save privately

Use the final link scores, canary results and ledger from the prover brief. Put one effective verdict per finding in the report input, with raw first and second passes kept in separate private folders. Collect all failed reads in the unconfirmed file. Render into a fresh private staging directory, with inboxes under the same directory as the report.

```sh
python3 -I scripts/dream.py report <merged.json> <verdicts-dir> --date <YYYY-MM-DD> --out <report.md> --tickets-out <tickets.json> --days <days> --scope <comma-separated-scope> --unconfirmed <unconfirmed.json> --link-scores <report-scores.json> --rejected-links <gate-a-drops.json> --ledger <ledger.jsonl> --canaries <report-canaries.json> --inboxes-dir <fresh-inboxes-dir> --routes-out <routes.json>
```

Save the report, inboxes and sidecars to the dated run folder in the verified private repository. Read back the saved report and use its verified private-record link. Keep owner calls, orchestrator chores and private fixes in the report for their owners. Group ticket candidates by repository area when they share one coherent change.

## 5. File confirmed clear wins

Read [triage's labels and rules](../../triage/SKILL.md#the-work-and-the-labels) and its [brief format](../../triage/AGENT-BRIEF.md). The rendered ticket list is a filing plan. Only file `CONFIRMED` clear wins with a title, a scoped proof and a private-record link. Recheck retained records. Use one category plus `ready-for-agent`. A delete ticket goes through the normal approval, build and review path. Ready means briefed.

Write neutral titles, bodies and briefs. Summarize repeatable technical evidence in public words, and keep exact source quotes and details in the private record. Before any create or uncertain retry, read back issues by exact title in the destination repository across open and closed states. Reuse a matching issue for this finding, hold an ambiguous match, and save the read-back URL and brief receipt. Resume an incomplete brief only on this run's own issue after reading its comments.

## 6. Tell the owner

Send the configured owner one private summary with the report link, counts and the top ten deletes, fixes and links grouped by kind. Put says-vs-does and promise-to-work first among links. Include owner calls and unconfirmed gaps. Read back an uncertain delivery before retrying and save its receipt.
