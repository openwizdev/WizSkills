# Changelog

## 0.2.0 - 2026-11-20

- WizSkills 0.2.0: 18 skills, each one short job in plain steps, with its mechanics in tested scripts, so your agents load a fraction of the text.
- Skills added: `to-spec`, `to-tickets`.
- Skills removed: `feedback`, `feedback-triage`, `onboard`, `overnight`, `plan-graph`.
- `launch-fleet` 0.3.0: launch-fleet is a short dispatcher over tested scripts (merge, records, briefs) and posts each merged ticket's cost line; the supervised pass runner (`loop.sh --pass`, `--ack`) and the dormant installation reader are removed.
- `research` 0.2.1: Wayfind, research and triage are rewritten short, one job each; wayfind reads its frontier with a new `frontier.py` script.
- `to-spec` 0.3.0: A confirmed grill now runs to-spec and to-tickets straight through: the plan is approved by its own checks (a machine plan approval record), and to-spec makes one narrated steering video in build order.
- `to-tickets` 0.3.0: A confirmed grill now runs to-spec and to-tickets straight through: the plan is approved by its own checks (a machine plan approval record), and to-spec makes one narrated steering video in build order.
- `triage` 0.2.1: Wayfind, research and triage are rewritten short, one job each; wayfind reads its frontier with a new `frontier.py` script.
- `wayfind` 0.3.0: Wayfind, research and triage are rewritten short, one job each; wayfind reads its frontier with a new `frontier.py` script.

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
