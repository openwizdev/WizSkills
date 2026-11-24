# OpenWiz dream-cycle contract, version 1 (`dream-cycle.v1`)

The dream cycle reviews an organization's repositories and areas (including scheduler `Loops`) on a cadence, verifies every candidate by re-running its evidence, renders one dated private report, and files only confirmed clear wins as ordinary tickets. Its JSON schema is [dream-cycle.v1.schema.json](dream-cycle.v1.schema.json).

Authority: spec `openwizdev/OpenWiz#3088` (0.3.0) and ticket DC1 `#3089`. Commands: [`skills/dream-cycle/scripts/inventory.py`](../skills/dream-cycle/scripts/inventory.py) (DC2 `#3090`) and [`skills/dream-cycle/scripts/dream.py`](../skills/dream-cycle/scripts/dream.py) (DC3 `#3091`). Skill entrypoint and role briefs: [`skills/dream-cycle/SKILL.md`](../skills/dream-cycle/SKILL.md) (DC4 `#3092`).

## Guards

- **Scouts are read-only.** Scouts never delete, close, archive, commit, push, or edit repository files or GitHub records.
- **Only the controller writes.** The controller writes the dated private report in the private repository and files confirmed tickets.
- **Unproven findings are never ticketed.** Only a `CONFIRMED` finding with a non-null `ticket` title enters the ticket list.
- **Records kept by rule are never delete candidates.** Dated decisions, evidence logs, and other retained records may only be `fix` candidates when they mislead.
- **Failed reads are `unconfirmed`, never zero.** Any failed or partial read is recorded under `unconfirmed` with its reason.
- **Public tickets stay neutral.** Filed tickets use neutral technical wording and a private-record pointer; no thread IDs, personal quotes, or machine paths.

## Findings line (`#/$defs/finding`)

Each scout writes one JSON object per line (JSONL). Readers reject duplicate keys, missing keys, extra keys, and non-object lines.

| Field | Type | Rules |
| --- | --- | --- |
| `id` | string | Unique finding identifier (`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`). |
| `kind` | enum | `delete`, `fix`, `link`, or `summary`. |
| `repo` | string | Repository (`owner/repo`) or area name (for example `Loops`). |
| `paths` | array of strings | Repository-relative paths or area identifiers; `minItems: 1` for `delete`. |
| `what` | string | Non-empty single-line summary of the finding. |
| `evidence` | array of strings | At least one `<command> -> <short result>` entry. |
| `why_keep` | string | Best reason to keep the target; non-empty for `delete`, may be `""` otherwise. |
| `confidence` | enum | `high`, `medium`, or `low`. |
| `size` | enum | `S`, `M`, or `L`. |
| `ticket` | string or `null` | Proposed ticket title (1–160 chars) for actionable clear wins, or `null`. |

## Prover verdict line (`#/$defs/verdict`)

Each prover re-runs the finding's `evidence` commands and writes one JSON object per line (JSONL). Duplicate, missing, and extra keys are rejected.

| Field | Type | Rules |
| --- | --- | --- |
| `id` | string | Finding `id` being judged. |
| `verdict` | enum | `CONFIRMED`, `PLAUSIBLE`, or `REJECTED`. |
| `reason` | string | Non-empty single-line explanation of the verdict. |
| `evidence` | array of strings | At least one `<command> -> <short result>` entry from the prover's re-run. |

## Report sections

The rendered private Markdown report (`YYYY-MM-DD.md`) opens with a header and contains these sections in order:

- **Header:** `# Dream cycle report — <YYYY-MM-DD>`, followed by `- **Date:**`, `- **Scope:**` (repositories and areas, including `Loops` when configured), `- **Window:** <N> days`, and `- **Counts:**` (merged findings, confirmed, plausible, rejected, unproven, tickets to file, unconfirmed reads).
- `## Areas` — per-repository and per-area counts (including `Loops`, where scheduler loops are treated as an area like a repository).
- `## Top deletes` — ranked `CONFIRMED` and `PLAUSIBLE` delete candidates with evidence and `why_keep`.
- `## Top fixes` — ranked `CONFIRMED` and `PLAUSIBLE` fix candidates.
- `## Top links` — ranked `CONFIRMED` and `PLAUSIBLE` cross-repository or cross-area links.
- `## Rejected` — `REJECTED` findings with each prover's `reason`.
- `## Unconfirmed reads` — every failed or partial read with its repository/source and reason.
- `## Tickets filed` — one line per `CONFIRMED` finding with a non-null `ticket` title; `PLAUSIBLE`, `REJECTED`, and unproven findings never appear here.

## Inventory output (`#/$defs/inventory`)

`python3 -I skills/dream-cycle/scripts/inventory.py <repo> [--days 14] [--pr-idle-days 7] [--limit 20]`

Prints one JSON object with `schema: "openwiz.dream-cycle.inventory.v1"`, `repo`, `days`, `pr_idle_days`, `generated_at` (UTC `YYYY-MM-DDTHH:MM:SSZ`), `sections`, and `unconfirmed`.

`sections` has exactly seven keys: `stale_paths`, `orphan_branches`, `idle_issues`, `idle_prs`, `empty_milestones`, `skipped_tests`, and `generated_files`. Each section is either:

- Confirmed: `{"status": "ok", "total": <int >= 0>, "items": [...], "reason": null}`
- Unconfirmed: `{"status": "unconfirmed", "total": null, "items": [], "reason": "<why>"}`

Exit codes: `0` when all seven sections are confirmed (`unconfirmed` is `[]`); `1` on bad arguments or unreadable target; `2` when one or more reads failed or were partial (`unconfirmed` is non-empty, JSON still printed to stdout).

## Merge and report commands

- `python3 -I skills/dream-cycle/scripts/dream.py merge <findings_dir> --out <merged.json> --batches-dir <dir> [--batches 4]`
  Validates each line against `#/$defs/finding` (dropping invalid lines with `{file, line, reason}`), dedupes matching `(repo, sorted(paths))` keeping the strongest evidence and recording `merged_ids`, ranks deterministically (`kind`, `confidence`, `size`, evidence count, `id`), writes `#/$defs/merged`, and splits prover work into `N` even `batch-XX.jsonl` files.
- `python3 -I skills/dream-cycle/scripts/dream.py report <merged.json> <verdicts_dir> --date <YYYY-MM-DD> --out <report.md> --tickets-out <tickets.json> [--days 14] [--scope "<list>"] [--unconfirmed <file.json>]`
  Validates verdict lines against `#/$defs/verdict`, applies verdicts (`REJECTED` to `## Rejected`; missing verdicts stay unproven and are never ticketed), writes the Markdown report and the `CONFIRMED` ticket list JSON, and prints compact counts.

## Project settings (`docs/agents/dream-cycle.md`)

Projects store their choices in `docs/agents/dream-cycle.md` so the skill stays reusable:

| Setting | Default / shape |
| --- | --- |
| Repositories and areas | List of repositories (`owner/repo`) and areas (including `Loops` for scheduler loops, sites, war rooms, skills, docs). |
| Window (`N` days) | `14` (integer days for stale paths and idle issues; pull requests idle `7` days). |
| Private report path | Folder in the private repository (for example `reports/dream-cycle/`). |
| Models | `controller`, `scout`, and `prover` (prover from a different model family than scouts where allowed). |
| Scout budget | Maximum scouts and concurrency per cycle. |
| Ticket labels | Default labels for filed tickets (for example `ready-for-agent`). |
| Records kept by rule | Paths or patterns that are never delete candidates. |
