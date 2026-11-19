# Records and private routing

Read this before writing a record the step you are on does not name, or when changing private routing. `scripts/post.py` writes every record and refuses private identities.

## Public records and private routing

Follow `contracts/open-development.v1.md`, Fleet records. Every GitHub write, on either repository, uses the public form. Never put a thread id in a comment, report, reason or helper log. Due lines and CloudRoom commands are private routing inputs: do not copy their identities into public `look` or failure reasons. Name the ticket, pull request, commit, branch or claim comment instead. Check every proposed public body for thread ids before posting; if its reason contains one, replace the reason with a plain description tied to those public facts.

`scripts/records.py` resolves builders by the exact `#<N>: ` title prefix and the checked branch, excluding helpers. Reviewers match `Review #<P> at <short start commit>`. Order records by comment creation: each `review started <A>` opens a span until the next start. Re-checks, told-again and give-up records at any later commit belong to that original reviewer. Giving up closes the whole span, even if its claim was edited in place and later told-again records remain. Never contact a closed span; start a fresh reviewer or record a thread-free `look`. None or an unreadable source is out of reach; two matches or disagreement with private state is a `look`, never a guess. Today's forms are read only when repository privacy is positively known; unknown is public.

Before posting a successful start or delivery, save its identity in private state, outside the public checkout (or `private/orchestration/` in the private repository). Set `LAUNCH_FLEET_STATE` to that absolute JSON file. Its shape is `{"repo":"owner/name","threads":{"builder:N":"<thread>","review:P:FULL_START_COMMIT":"<thread>","review:P:claim:CLAIM_COMMENT_ID":"<thread>","comment:CLAIM_COMMENT_ID":"<sender>","fleet:S":"<fleet>"}}`. It holds thread identities only. Loop ids go in a separate private file beside it, never in this map: set `LAUNCH_FLEET_LOOPS` to that absolute JSON file, shaped `{"repo":"owner/name","loops":{"S":"<loop id>"}}`; no check reads it, only the agent resolving a handle. Save each claim's sender before sending; a re-check adds its commit key to the same reviewer. Before editing a review-start claim to success, save its immutable `review:P:claim:CLAIM_COMMENT_ID` key as well. Give-up retires every routing key for that reviewer, but keeps that claim mapping for archive-only cleanup at ticket closure. Never overwrite or delete a retired claim mapping: a replacement, even at the same commit, gets a new claim key. Commit aliases may change; they cannot replace the retained claim identity. The reader never changes this map. Do not guess a sender for an unresolved resume, release or nightly claim: without private evidence proving delivery or non-delivery, leave it claimed and ask the orchestrator. A safety-net sandbox without CloudRoom can use this private map; without either source it reports out of reach, and the agent tick resolves the public facts in its own CloudRoom context.

An old-builder archive records `launch-fleet: old builder archived, start <start comment id>` for legacy takeovers. The spec's loop is advertised as `launch-fleet: fleet active, loop fleet-<S>`. A separate line `Wake mode: fresh` in that same comment marks a loop that starts fresh threads. The real loop id stays under `S` in the private loop file. No wake writes its own identity as the fleet's identity.

## Records

The loop's memory: comments on GitHub, each starting `launch-fleet:`. Edit a claim as its start moves on; a retry is a new comment.

| On | Record | Means |
| --- | --- | --- |
| A ticket | `launch-fleet: starting` | A start is claimed |
| | `launch-fleet: started` | Its builder started |
| | `launch-fleet: builder fallback due, branch <branch>` | The single builder fallback is reserved |
| | `launch-fleet: start checked, branch <branch>` | Thread, ticket and branch checked |
| | `launch-fleet: start refused: <reason>` / `start not tried: <why>` / `start failed: <why>` / `start withdrawn` | No builder: it stays on the frontier (a refused or untried start after 10 minutes) |
| | `launch-fleet: held for ordering: issue #B merges to main` / `held for ordering: PR #P merges to main` | An owned ordering-only hold, after its label change |
| | `launch-fleet: held manual: <why>` / `held live: <why>` | A manual/live gate, even while already labelled held; its owner supplies separate release evidence |
| | `launch-fleet: release starting <hold comment id>` / `released ordering C` / `release failed C: <why>` / `release withdrawn C` | A release intent and its verified outcome; unresolved intents block starts |
| | `launch-fleet: held for #<P>` / `noted #<P>` | An existing contract hold, or a builder told of a change |
| | `launch-fleet: asked the orchestrator` | Its `needs-info` question was passed on |
| | `launch-fleet: told the user` | A person's ticket is ready, and the user knows |
| | `launch-fleet: complete: <evidence>` | The orchestrator or owning fleet thread records a person's completed work and names its evidence; with the ticket closed, its dependents may start |
| | `launch-fleet: waiting for #<B>` / `resume starting <wait comment id> for #<B>` / `resume sent <wait comment id> for #<B>` / `resume failed <wait comment id> for #<B>: <why>` / `resume withdrawn <wait comment id> for #<B>` | The builder waits for a verified merge, or was told to resume that wait |
| | `launch-fleet: archived` | Its builder and reviewer are archived |
| | `launch-fleet: old builder archived, start <start comment id>` | The orchestrator archived that builder, from before the spec's fleet thread, so the fleet thread may start its own (a takeover) |
| A pull request | `launch-fleet: review starting <commit>` / `review started <commit>` / `review refused <commit>: <reason>` / `review failed <commit>: <why>` / `review withdrawn <commit>` | Its reviewer for that commit |
| | `launch-fleet: re-check sent <commit>` | The same reviewer asked to re-check |
| | `launch-fleet: review told again <commit>` / `review given up <commit>: <why>` | A quiet reviewer was told again, or given up on (its thread archived) |
| | `launch-fleet: CI failure sent <commit>` / `findings sent <commit>` | The builder was told |
| | `launch-fleet: merge queued <commit>: <what allowed it>` | It waits in the merge queue at that commit |
| | `launch-fleet: re-test starting <commit>` / `re-test sent <commit> on <base> in run <run id>: <what main changed>` / `re-test failed <commit>: <why>` | Its CI was started again at that head, and the `main` it tested (the re-test guard) |
| | `launch-fleet: merge main asked <commit>` | Its builder was told to merge `main` in, as its re-test ran on an old `main` |
| | `launch-fleet: merge blocked <commit>: <why>` | The merge waits for someone |
| A spec | `launch-fleet: needs approval: <what changed>` / `spec summary` | The user was asked, or told it is done |
| | `launch-fleet: fleet active, loop fleet-<S>` | The spec's loop's public handle (the real loop id stays under `S` in the private loop file). The latest counts. A separate `Wake mode: fresh` line keeps existing assignments across wakes |
| | `launch-fleet: look: live check not recorded as passed` / `live check passed` | Evidence is missing (one alert), or a newer explicit pass has been verified and the wait is released; the pass line may append `: <evidence source>` |
| | `launch-fleet: look: live check evidence to verify in comment <id>` | The tick inspected that new evidence comment without establishing the required pass; do not repeat its verification task |
| A run's commit | `launch-fleet: nightly telling <run> attempt <attempt>` / `nightly told <run> attempt <attempt>` / `nightly uncertain <run> attempt <attempt>` | Notification claimed, delivered, or settled after one uncertainty notice |
| Any of them | `launch-fleet: look: <the line's reason>` | Someone was asked to look |

## The check

`scripts/fleet.sh`, beside this file, is the loop's check, the tick's read of what it was woken for, and the frontier and contract-note helpers. It only reads, through `gh` and `jq`. For a spec with a ticket that could start, it runs `to-tickets`'s `revision.sh` (in `skills/to-tickets/`) to check the approval is current. `scripts/loop.sh` is the safety net's script, which runs it, and with `FLEET_SPEC` set, a fleet thread's loop's script, which runs `spec <S>`.

| Command | Prints |
| --- | --- |
| `sh "<this skill's folder>/scripts/fleet.sh"` | Every due line, or nothing when nothing is due (exit 0) |
| `sh "<this skill's folder>/scripts/fleet.sh" wake <N>...` | The due lines about issues and pull requests `<N>...` alone, read alone: a pull request with every ticket it closes, a ticket with its spec's approval (its whole spec, when it could start), an issue approved on its own, a spec in full. A number that is no issue or pull request is nothing. Lines on anything else wait for the check, and so do a spec's own lines (`re-approve`, `spec done`, `close spec`) unless the wake names the spec; for a spec with a fleet thread, only its `wake fleet` line |
| `sh "<this skill's folder>/scripts/fleet.sh" spec <S>` | The due lines of spec `<S>` alone; `fleet done #<S>` when `<S>` is no open spec. Legacy fleet records can still produce takeover lines. The full check prints nothing about a spec with a fleet thread, and `wake` prints only its `wake fleet` line |
| `sh "<this skill's folder>/scripts/fleet.sh" every` | The check's lines on every spec, fleet threads' too, and on the issues approved on their own: a fleet thread's read before a merge |
| `sh "<this skill's folder>/scripts/fleet.sh" frontier` | Every ticket that may start now |
| `sh "<this skill's folder>/scripts/fleet.sh" holds` | Every contract change note due for a builder (legacy command name) |
| `sh "<this skill's folder>/scripts/fleet.sh" claim <N> <comment id>` | After a claim on ticket or pull request `<N>`: `go #<N>`, or `withdraw #<N>: <why>`. It reads only `<N>`, as `wake` does |

It exits 2, with the reason, when it can't read what it needs. Its tests run on synthetic GitHub answers: `sh "<this skill's folder>/scripts/test.sh"`.
