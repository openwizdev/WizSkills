# Dream cycle scout

Follow only the assigned repository, area or lens. Run `room-cli files wait` in the foreground on a copying Cloudroom workspace, then carry on in the same turn. If it fails, return the named gap. Start with the controller's inventory slice and pinned checkout.

## Read-only scope

Read source, history, references and records with permitted read-only tools. Keep one local scratch findings file. Leave repositories, issues, branches, loops and records untouched. Records kept by rule can be fixed when misleading. They are never delete candidates.

Search locally before a GitHub search. Before calling a target unused, look at imports and callers, raw URLs, workflows, scheduler loop scripts outside Git, systemd units, and records kept by rule. Missing access or a partial search is unconfirmed. For deletes, find the strongest live reason to keep the target and the caller or owner to test it against. For fixes, show the current behavior and the mismatch.

## A business lens

Use the sources in the brief and the project's time rules. A lens gives a concrete lead, then evidence must show what decision changes.

| Lens | Look for |
| --- | --- |
| Strategy | Stale goals or plans contradicted by measured results or later decisions |
| People | Open next steps with no recent touch and promised follow-ups, including the seven-day window when the brief uses it |
| Market | A competitor move that changes an open decision, or a stalled metric |
| Money | Unused or duplicate subscriptions, unknown recurring costs, unwatched renewals or a broken cost rule |
| Product and delivery | Owed work with no ticket, or proposals duplicating open specs |
| Ideas | A note, bookmark or advice that changes an existing ticket or deserves a new decision |

A link shares a concrete behavior or changes a decision, promise, ticket or row. Open the ends, quote each verbatim with its reference and date, and give the best reason they are unrelated. Keyword overlap is a lead. Route business links to the owning person's or pillar's private `pillar-inbox`, with `ticket: null`.

## Return one file

Use the [findings format](../../contracts/dream-cycle.v1.md#findings-line-defsfinding). Write one JSONL object per finding to the assigned filename, with a unique ID, exact paths, a permitted read command and its short result, and `why_keep`. Use all required link fields for links. A proposed ticket title is for a clear, testable outcome. Record read failures with their sources for the controller's unconfirmed list.

Hand the controller the file bytes through the approved private handoff. On Cloudroom, send a nonempty scratch file with `room-cli thread tell --parent --message-file <scratch-file>` when the controller cannot read it directly. Return an empty file or an explicit empty-file receipt for a completed slice with no candidates. State the gaps separately. The turn ends after delivery or an explicit handoff failure.
