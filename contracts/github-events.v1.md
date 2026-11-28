# GitHub events contract (`openwiz.github-events.v1`)

The router turns one GitHub webhook delivery into the spec checks for one fleet. It uses the repository and issue or pull request in the delivery. The caller runs the checks in the fleet's configured spec repository. The 30-minute safety-net check stays on its own schedule, including when a delivery is missed, delayed, ignored or refused.

Source: [spec #3716](https://github.com/openwizdev/OpenWiz/issues/3716) and [ticket #3740](https://github.com/openwizdev/OpenWiz/issues/3740).

## Event and target

Read the event name from `X-GitHub-Event`, the action from `action` and the source repository from `repository.full_name`. Match header names case-insensitively. The event and action values match literally. [GitHub webhook events and payloads](https://docs.github.com/en/webhooks/webhook-events-and-payloads)

| Event | Action and condition | Target numbers in the source repository |
| --- | --- | --- |
| `check_suite` | `completed` | The PR numbers in `check_suite.pull_requests[].number`. |
| `check_run` | `completed` | The PR numbers in `check_run.pull_requests[].number`. |
| `pull_request` | `closed` with `pull_request.merged` equal to JSON `true` | `pull_request.number`. |
| `pull_request` | `synchronize` | `pull_request.number`. |
| `pull_request_review` | `submitted` | `pull_request.number`. |
| `issue_comment` | `created` | `issue.number`. Resolve it as a PR when `issue.pull_request` is present and as a ticket otherwise. |
| `issues` | `labeled` or `unlabeled` | The ticket at `issue.number`. |

After authentication, ignore every other event or action, including a PR closed without merging. An empty PR list yields no target. Resolve each PR to its ticket through GitHub's closing issue references, using the referenced repository and issue number. Resolve each ticket through its GitHub parent. Output only parents in the fleet's configured spec repository, since the output identifies specs by number. A missing closing reference or parent yields no spec for that target. Other targets in the same delivery can still resolve.

A route that supplies only a body can match the action and corresponding payload object in the table. Without an unambiguous match, ignore the delivery. The route selection determines whether body-only delivery is suitable.

## Signature and delivery ledger

- Read the secret from the environment by name only, `OPENWIZ_WEBHOOK_SECRET`. When it is set and the route supplies headers, require `X-Hub-Signature-256` to match `sha256=` followed by the HMAC-SHA256 hex digest of the exact body bytes. Compare in constant time. Refuse missing or incorrect signatures before lookups or ledger updates. Never write, log or print the value. [GitHub signature validation](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries)
- For an authenticated, acted-on event with `X-GitHub-Delivery`, claim that ID once before routing. Keep the last 1,000 claimed IDs in `.openwiz/home/github-events.json` as a JSON array ordered from oldest to newest. Serialize the duplicate check and append and update the ledger atomically. A recorded ID exits quietly, even if replayed after a process restart. Once an ID falls out of the window, it can be claimed again. Without the header there is no ID to record or deduplicate.

## Router command

- With headers, run `skills/launch-fleet/scripts/events.py --headers <file> --body <file>` to read one delivery from the two files.
- Without headers, run `skills/launch-fleet/scripts/events.py` with the delivery body on standard input.

Both forms follow the [output and exit status rules](#output) below.

## Output

Exit `0` for an accepted delivery, including every quiet outcome. For each resolved spec, print exactly one `check spec <S>` line to stdout, where `<S>` is its positive decimal issue number. Sort by number, remove duplicates and terminate each printed line with a newline. Print zero bytes when no checks are due.

Exit `2` with empty stdout on refusal, including failed required signature validation.

## Fixtures

[The synthetic fixtures](fixtures/github-events/) each describe a scenario. Start each scenario with a fresh home and keep that home across its `deliveries` in order. A fixture contains:

- `closing_tickets` and `parents`, fake GitHub lookup tables keyed by `owner/repo#number`. A PR maps to an array of closing tickets. A ticket maps to its parent reference or `null`. Omitted entries represent missing references. `example-org/example-repo` is the fleet's spec repository in every fixture.
- `ledger_fill` (optional), the number of IDs used to seed the ledger in order, from `example-history-1` up through that count.
- `secret_configured` (optional, default `false`), whether the harness provisions a disposable secret in the environment. For a delivery with `sign_body: true`, the harness signs the same serialized JSON bytes it sends. Literal signature headers in these fixtures are deliberately invalid. No secret value is stored in the fixtures.
- `deliveries`, each with `headers` (an object, or `null` for a body-only route), a JSON `body`, and `expected`. The [output schema](github-events.v1.schema.json) validates each `expected` object. Its `stdout` array represents the lines without their newline terminators and its `exit_code` records the process status. The harness also checks numeric order when comparing the lines.

`check-suite-completed.json` exercises sorting and uniqueness across several PRs. `duplicate-delivery.json` replays the same ID, and `ledger-window.json` checks the eviction boundary. `bad-signature.json` includes an invalid signature, a missing signature and a signed retry with the same ID. `ignored-event.json` shows a quiet webhook run while the independent safety-net schedule remains in effect.
