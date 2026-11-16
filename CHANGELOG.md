# Changelog

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
