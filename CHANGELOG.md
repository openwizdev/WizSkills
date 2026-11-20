# Changelog

## 0.2.0 - 2026-11-20

- WizSkills 0.2.0: 18 skills, each one short job in plain steps, with its mechanics in tested scripts, so your agents load a fraction of the text.
- Skills added: `to-spec`, `to-tickets`.
- Skills removed: `feedback`, `feedback-triage`, `onboard`, `overnight`, `plan-graph`.
- `build-ticket` 0.2.0: The builder checklist states the current review-round limit (one review plus one re-check, then at most one fresh round) in place of "2 + 1".
- `diagnose` 0.2.0: The loop's clean also reads each file's staged copy, so a debug tag Git would commit is never called clean, and a timed-out rate run has its whole process group stopped before the next run starts.
- `grill` 0.2.0: wayfind's frontier refuses an issue without the `wayfind:map` label and a Record authors row with extra columns; grill's helper tests pin its refusal of a changed or superseded same-ID request.
- `huntr` 0.2.0: Every final path of a hunt now ends with `lease.mjs finish`, which publishes the final result and releases the lease even through a brief GitHub read failure; a dispatch that blocks every slice finishes at once; and pacing refuses a last-empty time without Z or an offset.
- `install` 0.2.0: A resumed first fleet returns to Connect for a repository setup already prepared, and to Choose the agents while Local is chosen or the Cloud choice's builder tables have not read back.
- `install` 0.2.0: The setup doctor's fixes now fix what they name (App repository selection, an unoffered model or effort, a complete prepare preview, a separate driver), and it withholds a driver answer the driver kit flags as possibly holding a credential.
- `launch-fleet` 0.2.0: launch-fleet is a short dispatcher over tested scripts (merge, records, briefs) and posts each merged ticket's cost line; the supervised pass runner (`loop.sh --pass`, `--ack`) and the dormant installation reader are removed.
- `launch-fleet` 0.2.0: launch-fleet starts a spec's fleet on to-tickets' machine plan approval, with no human approval. Comments on the spec's video steer nothing until OpenWiz #1402's identity separation is verified; the check says so once, and the owner steers through the orchestrator.
- `launch-fleet` 0.2.0: launch-fleet wakes the right fleet for GitHub messages from any repository whose pull requests close the project's tickets, and resolves a fleet's loop handle with a tested lookup that leaves a spec with no loop id to its own loop. Its webhook setup, rotation, list and delete run `gh` through `route.py gh` with a clean environment, so no trace setting in the caller's shell can print the webhook address.
- `launch-fleet` 0.2.0: Plans cut for the shortest critical chain and the widest graph: the plan record's chain counts open outside blockers, `prefer.py` keeps the better of two cuts, and `lead_time.py` reports each spec's lead time from the collector. Fleets record four bounded self-grants and refuse model or effort changes, and start every ticket whose hard blockers merged and whose owned paths don't collide.
- `launch-fleet` 0.2.0: launch-fleet starts, wakes and stops builders through the host driver the project chooses in `docs/agents/host.md`, and keeps each run privately so a changed setting only moves later starts.
- `launch-fleet` 0.2.0: launch-fleet starts a builder only when a maintainer put `ready-for-agent` on the ticket and nobody edited it since; otherwise it raises one look saying a maintainer must add the label again.
- `launch-fleet` 0.2.0: `status.py run --note <id> -- <command>` keeps an agent's claim live while long work runs, and stops the work when the claim is lost; a heartbeat never reopens a done or stopped note.
- `launch-fleet` 0.2.0: The wake's `needs-info` repair never removes a hold a person set. It takes off a label only under a GitHub App's own login, and only one its own write applied in the same wake. A label from an earlier wake, such as a put-back whose note edit failed, or any label while the agents post as a person's own account, stays and is reported.
- `launch-fleet` 0.2.0: A fleet wake's status step is one `status.py repair` call. It adds `needs-info` only while a note still asks, records the repair in its own fleet note until the label is settled (so a later wake finishes a repair an earlier one left part way), takes off only the application it made, puts back and reports a person's application it took, and reports a failed check as a failed check.
- `launch-fleet` 0.2.0: The status writer reads back after a claim edit: it steps down when another live note of its kind exists, and puts back a release a sibling wake wrote in between.
- `research` 0.2.0: Wayfind, research and triage are rewritten short, one job each; wayfind reads its frontier with a new `frontier.py` script.
- `setup` 0.2.0: Setup's settings check refuses a second Record authors row and a duplicate or malformed spawn flag in any builder, reviewer or Fixer table, naming the row or flag, as the review and launch readers already do.
- `to-spec` 0.2.0: A confirmed grill now runs to-spec and to-tickets straight through: the plan is approved by its own checks (a machine plan approval record), and to-spec makes one narrated steering video in build order.
- `to-spec` 0.2.0: The steering video fails and names the moment when the voice command fails or a moment's take is silent or stale, and it now exports to an output on another filesystem.
- `to-tickets` 0.2.0: A confirmed grill now runs to-spec and to-tickets straight through: the plan is approved by its own checks (a machine plan approval record), and to-spec makes one narrated steering video in build order.
- `to-tickets` 0.2.0: Plans cut for the shortest critical chain and the widest graph: the plan record's chain counts open outside blockers, `prefer.py` keeps the better of two cuts, and `lead_time.py` reports each spec's lead time from the collector. Fleets record four bounded self-grants and refuse model or effort changes, and start every ticket whose hard blockers merged and whose owned paths don't collide.
- `to-tickets` 0.2.0: Machine plan approval counts a missing Relies on file as planned only when a direct blocker owns that file, or a folder containing it, in the dependent ticket's own repository; a file in the --root checkout counts only for tickets in that checkout's repository.
- `triage` 0.2.0: Wayfind, research and triage are rewritten short, one job each; wayfind reads its frontier with a new `frontier.py` script.
- `wayfind` 0.2.0: Wayfind, research and triage are rewritten short, one job each; wayfind reads its frontier with a new `frontier.py` script.
- `wayfind` 0.2.0: wayfind's frontier refuses an issue without the `wayfind:map` label and a Record authors row with extra columns; grill's helper tests pin its refusal of a changed or superseded same-ID request.
- `wayfind` 0.2.0: wayfind's frontier counts only record authors' claims and releases, never says `yours` for a blocked or kind-less question, and reads every comment and question page in order.

## 0.1.2 - 2026-11-18

- `install`: no longer chooses or activates an engine; after setup it checks CloudRoom, explains the product in a few lines and hands over to `onboard`, and every step reuses what an earlier one recorded.
- `launch-fleet`: `fleet.sh overload` can read the war room collector's queue at the time of each new-work call through an OpenWiz checkout's own supplier (`LAUNCH_FLEET_OVERLOAD_SUPPLY`), and refuses new work as unknown when that supplier fails; the limit-recovery notes name the war room's renamed files.
- `onboard`: starts from a fresh install with a new Connect step for the one chosen repository (GitHub sign-in, the user's own App or an explicit skip, the prepared project and its private brain), reuses the recorded harness, model and effort, and launches the first fleet as one launch-fleet fleet thread instead of the engine's tick.
- `setup`: the person may explicitly skip the App, so their verified personal GitHub login acts on the selected repository and the App stays missing.
- `contracts/cli.v1.md` (carried contract): records the removal of the terminal app and `ui`, the retirement of the executing `fleet tick`, `--expect-plan` and the `engine` commands, and the shipped `loop validate`, `loop export`, `loop plan` and `loop apply` reports.

## 0.1.1 - 2026-11-16

- `build-ticket`: builders rule on choices inside the ticket and log each ruling in the pull request, follow a project's standing supporting-edit rule, and answer the review loop's v2 states, including one fresh round.
- `diagnose`: the orchestrator's diagnosis now comes only inside a decision that relays the owner's answer to a parked finding.
- `launch-fleet`: routes each review's v2 `Next:` line, starts at most one fresh round per pull request and parks findings for the owner; its GitHub App is private and checks the App's owner and installation before minting a token.
- `review-ticket`: marks every ruling upheld or overturned, logs a re-check's remaining user-path blockers as follow-up issues, and sends risk blockers to one fresh round before parking them for the owner.
- `contracts/cli.v1.md` (carried contract): adds four planned `loop` commands, `validate`, `export`, `plan` and `apply`, each reported as not built yet.

## 0.1.0 - 2026-11-16

- First public release of OpenWiz's skills, one line per skill below.
- `ask-wiz`: first public release.
- `build-ticket`: first public release.
- `diagnose`: first public release.
- `feedback`: first public release.
- `feedback-triage`: first public release.
- `grill`: first public release.
- `handoff`: first public release.
- `hill-climb`: first public release.
- `huntr`: first public release.
- `image`: first public release.
- `install`: first public release.
- `launch-fleet`: first public release.
- `onboard`: first public release.
- `overnight`: first public release.
- `plan-graph`: first public release.
- `research`: first public release.
- `review-ticket`: first public release.
- `setup`: first public release.
- `triage`: first public release.
- `wayfind`: first public release.
- `where-are-we`: first public release.
