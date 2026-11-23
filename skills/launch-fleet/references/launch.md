# Launch a fleet

Read this when a plan graph is approved, when a spec moves to fresh wakes, or when GitHub's messages are turned on or off. Get every brief and loop prompt from `scripts/brief.py`; never write one by hand.

## Launch (the orchestrator, when a plan graph is approved: by its machine approval, or by the user)

1. **Check the approval is recorded** on the spec issue, as `to-tickets` writes it. No record, no fleet. A machine approval needs no human reply (J203): re-run to-tickets' checks on the plan as it stands (its step 4, with the record's grill link, revision number, date and changed line) and launch only when `approve.py` prints exactly the record.
2. **Make sure the project has its two loops.** They drive every fleet in the project. `room-cli loop list` shows them if they exist. If not, create them. The safety net, a check every 10 minutes until GitHub's messages are on (step 3), then every 30:

   ```sh
   sh "<this skill's folder>/scripts/loop.sh" --bundle "<owner>/<repo>" \
     > /tmp/launch-fleet-loop.sh # The absolute folder of the loaded SKILL.md.
   room-cli loop create --name "launch-fleet <owner>/<repo>" --cron '*/10 * * * *' \
     --script-file /tmp/launch-fleet-loop.sh --priority 2 \
     --prompt "$(python3 -I "<this skill's folder>/scripts/brief.py" tick "<owner>/<repo>" "<your thread id>")"
   ```

   The generated loop script runs first, in the loop's own sandbox, which needs `gh`, `git`, `jq` and Python 3 (standard library only), but has no working `room-cli`; that is why the check reads only GitHub. It bundles the installed `loop.sh`, `fleet.sh`, `records.py` and `to-tickets`'s `revision.sh`, so neither the consumer's own `skills/` nor the plugin cache is needed at runtime. The sandbox lasts between runs: the runner keeps the consumer clone up to date, while the bundled helpers stay pinned to the installation used at setup. Regenerate the script and update the safety-net loop with `--script-file` when upgrading the plugin. Each run that prints something starts a fresh thread.

   The wake loop, which GitHub's messages wake:

   ```sh
   room-cli loop create --name "launch-fleet wakes <owner>/<repo>" --webhook --new-thread --priority 2 \
     --prompt "$(python3 -I "<this skill's folder>/scripts/brief.py" wakes "<owner>/<repo>" "<your thread id>")" \
     | jq -r .id
   ```

   **The brief is only the prompt above.** Never add merge, base or workaround rules to a loop's prompt: they live in this skill, its references and `fleet.md` (M1, the base rule, and its checks), and a copy goes stale. A loop whose prompt still carries an old rule, such as closing and reopening a pull request because `main` moved, gets the prompt above again: `room-cli loop update <id> --prompt "..."`.

   It prints its id and its secret address (`url`); `jq` keeps only the id, and that first address is dropped unseen. Anyone with the address can wake the fleet, so it never goes into a file, a variable, a command's arguments, a terminal, a comment, the handoff file or a message: `room-cli loop hook <id>` issues a fresh one straight into the repository's webhook through a pipe (step 3), which also retires every earlier address. If one ever leaks, rotate it with step 3's rotation pipe. Each run gets the messages that arrived since the last as data, and starts a fresh thread. Write both loops' ids in the handoff file (the `handoff` skill). When a new orchestrator takes over, it updates the thread id in both prompts: `room-cli loop update <id> --prompt "..."`.
3. **GitHub's messages are the user's setup.** The repository's webhook is a repository setting the user owns: ask the user ([user.md](user.md)) before it exists, and add it only on their yes, in their words in the handoff file. On that yes, the address goes from Cloudroom to GitHub in one pipe, held in memory only (the user can run it themselves, or let you run it):

   ```sh
   room-cli loop hook <wake loop id> \
     | jq '{name: "web", active: true, events: ["issues", "issue_comment", "pull_request", "pull_request_review", "check_suite", "workflow_run"], config: {url: .url, content_type: "json", insecure_ssl: "0"}}' \
     | python3 -I "<this skill's folder>/scripts/route.py" gh api --method POST 'repos/{owner}/{repo}/hooks' --input - --jq '{id, events, active}'
   ```

   `route.py gh api` runs `gh api` with a clean environment: only what gh needs to find itself, its login, host and repository, certificates and a proxy passes through, and every other setting is dropped. A trace setting in the caller's shell (`GH_DEBUG=api`, the older `DEBUG=api`, Go's `GODEBUG=http2debug=2`, or any a later release adds) would otherwise write the request or response, address included, to the terminal before `--jq` filters anything. Every `gh api` call that sends or reads a webhook, here and below, runs this way. That is the repository's webhook with content type `application/json`, no secret (the address is the secret), and the individual events issues, issue comments, pull requests, pull request reviews, check suites and workflow runs. The user may instead add it in the repository's settings (Webhooks, Add webhook, the same choices), taking a fresh address straight to their clipboard (`room-cli loop hook <wake loop id> | jq -j .url | pbcopy`) and pasting it into the form, never into a file or a message.

   If an address ever leaks, rotate it: a fresh address from `room-cli loop hook` (which retires the old one) goes into the existing webhook the same way:

   ```sh
   room-cli loop hook <wake loop id> \
     | jq '{config: {url: .url, content_type: "json", insecure_ssl: "0"}}' \
     | python3 -I "<this skill's folder>/scripts/route.py" gh api --method PATCH 'repos/{owner}/{repo}/hooks/<webhook id>' --input - --jq '{id, events, active}'
   ```

   It needs owner or admin access to the repository. GitHub sends a `ping` when a webhook is added (its documentation), which wakes one tick with nothing to read. Write the webhook's id in the handoff file. Then slow the safety net and every fleet thread's loop to every 30 minutes, as messages now wake them: `room-cli loop update <id> --cron '*/30 * * * *'`, for the safety net and for each open spec's fleet loop (the real loop id under its `S` key in the private loop file; the public record names only `fleet-<S>`), and read them back with `room-cli loop list`. If the user says no, the safety net and the fleet loops stay at every 10 minutes, and the wake loop, which nothing calls, can be deleted.
4. **Start the spec's fleet loop** ("Starting one", below). Run it once after publishing its record. If a fresh loop cannot be set up, record the reason on the spec and keep its existing routing. For a spec with no loop record, run the project's safety net once.

Done when both loops exist, the user has said yes or no to GitHub's messages, and the spec has a verified fleet loop record (or a look record explains why it could not be set up).

**Turning GitHub's messages off** (the user asks, or they misbehave): delete the webhook (`python3 -I "<this skill's folder>/scripts/route.py" gh api 'repos/{owner}/{repo}/hooks' --jq '.[] | {id, events, active}'` lists them without their addresses, with tracing dropped as in step 3; `python3 -I "<this skill's folder>/scripts/route.py" gh api --method DELETE 'repos/{owner}/{repo}/hooks/<id>'`), delete the wake loop (`room-cli loop delete <id>`), and set the safety net and every open spec's fleet loop back to every 10 minutes (`room-cli loop update <id> --cron '*/10 * * * *'` for each, the same loops as step 3; read them back with `room-cli loop list`). Nothing else changes, and nothing else needs undoing: with no messages, no tick runs a fleet loop early; the fleet's records are all on GitHub, so the check finds where everything stands. Record it in the handoff file.

### Starting one (the orchestrator, after plan approval)

Set up the loop with the project's fleet agent settings and private repository
access. Confirm that fresh runs have an authorized route to read the assigned
reviewer's verdict on GitHub, deliver to assigned agents with
`room-cli thread tell`, and hand off unreachable archives privately to the
planner or orchestrator. If required access is unavailable, record a
thread-free `launch-fleet: look:` on the spec and keep its current routing.

```sh
sh "<this skill's folder>/scripts/loop.sh" --bundle "<owner>/<repo>" "<S>" \
  > /tmp/launch-fleet-<S>.sh
room-cli loop create --name "launch-fleet #<S> <owner>/<repo>" --cron '*/10 * * * *' --new-thread \
  --parent "<open Cloud manager in this project>" \
  --script-file /tmp/launch-fleet-<S>.sh --priority 2 \
  --prompt "$(python3 -I "<this skill's folder>/scripts/brief.py" wake "<S>" "<owner>/<repo>")"
```

Use the absolute folder of this loaded skill to bundle the check. Add the
project's fleet agent settings. Set the parent to the open Cloud planner or fleet manager in the same
project and read it back before activation. Keep any old manager that still
parents active agents open. The scheduler's sandbox can keep its check cache.
The brief names the repository, spec number and installed skill. The project's private configuration supplies routing.
Use the 30-minute schedule only when GitHub's messages are verified on.

Save the loop id in the configured private repository's loop map and read it
back. Post this record on the spec as a single comment and read it back
before running the loop once:

```text
launch-fleet: fleet active, loop fleet-<S>

Wake mode: fresh
```

Move an existing fleet at a quiet moment, when none of its pull requests are
being merged or re-tested. Confirm the new loop and durable
routes for its existing agents, pause the old loop before publishing the new
record, and retire the old loop after verifying the new record. Preserve the
existing builders, selected reviewers and review rounds. A fresh record
routes the spec without using its activation timestamp as a takeover cutoff.
Legacy records keep their existing takeover semantics during rollout.

**A message for a spec with its own loop** prints `wake fleet #<S>: room-cli loop run fleet-<S>`. Resolve the handle through the private loop file (`LAUNCH_FLEET_LOOPS`, key `S`) with `scripts/route.py loop`, run `room-cli loop run <that id>` once and do nothing else for that spec; never post the real id. If the file or key is missing (`route.py tick` prints `wake fleet #<S>: unresolved`), write nothing on GitHub, as any record there comes back through the same webhook and wakes the same missing handle again: name it in the loop report (`--action "fleet #<S> loop handle unresolved"`) and leave the spec to its own loop. If CloudRoom refuses the run, record nothing: the spec's loop still runs on its own. A spec whose record names no loop, or a loop another spec in the same wake names, gets no line and waits for its loop.

## Hosts without CloudRoom

After checking the spec's recorded approval, run the fleet in the open chat with the session runner. This is the default local launch. Run the commands from a checkout of the project with `origin` set. Use the installed launch-fleet skill's absolute folder, the approved harness and model IDs, and the absolute `OPENWIZ_ADAPTERS` folder from host setup. GitHub CLI, Git, jq, Python 3 and the harness must be available to the signed-in user.

```sh
python3 -I "<this skill's folder>/scripts/session.py" run "<owner>/<repo>" --spec "<S>" --harness "<builder harness>" \
  --model "<builder model>"
```

It runs in the foreground, one tick after another, with no timer. Each tick reads `fleet.sh spec <S>` and does the lines a script can do alone, by this skill's own claims and records:
- a `start` line starts that ticket's builder through `host.py`, at most `--max` (default 3) at once;
- a `check start` line records `start checked`;
- a `review` line starts the reviewer the models rule picks for the builder recorded on the ticket (its status note's harness). With both `claude` and `codex` installed, that is the other-family row `ops-starts.py flags` prints, and no row means the review waits. With only the builder's harness, it is the same family with the CLI id the models table gives the builder's recorded model (its status note's `model`, matched to a row's model name, model name and effort, or id). No single match means the review waits;
- a `merge` line merges through `merge.py`, as "Merging" in this skill says. The newest `VERDICT:` must be an APPROVE at that head, posted after the pull request's current review assignment for that same head, and the selected reviewer's done note on the ticket must follow that assignment. `fleet.sh overload merge-batch` must then admit the batch, and without a merge queue a fresh `fleet.sh every` must still print that exact line. A queued merge counts as merged only once `merge.py read` reads it merged.

For the overload guard, the session keeps the pause state in `~/.local/state/openwiz-heartbeat/overload-<key>.json` unless `LAUNCH_FLEET_OVERLOAD_STATE` names another. Before each merge batch, unless `LAUNCH_FLEET_OVERLOAD_SUPPLY` or `LAUNCH_FLEET_OVERLOAD_INPUT` supplies one, it writes a fresh observation into that batch's own private file. The observation holds the repository's queued and running Actions jobs, plus the REST and GraphQL budgets and backoff from one probe read of each pool: its rate-limit headers and any `Retry-After`. A probe without those headers, or a refusal without `Retry-After`, leaves the backoff unknown. That, or any other unreadable read, leaves the observation incomplete, so the guard refuses. A pause stays until it is resolved as [overload.md](../overload.md) says.

After a tick that did something, it ticks again at once. Otherwise it waits for a run to end (that agent's status note on the ticket leaves `working`; a reviewer's note is on its pull request's ticket), for a queued merge to land (read every `--ci-poll` seconds, even while runs are going), or, with no run going, for a known pull request's checks. On start, and so on `carry on`, it rebuilds the spec's running builders and reviewers from their GitHub records, so `--max` counts builders still running from an earlier session. It also rebuilds the queued merges `merge.py read` still reads as queued at their receipt's head; an older receipt holds nothing.

It stops in three cases, and prints where it stopped and a `carry on:` command:
- **Done (exit 0):** the check prints `spec done` or `close spec` for the spec, or the spec is no longer open and every ticket of it is closed. The spec summary, closing the spec and `archive` lines stay with this skill.
- **Needs you (exit 3):** a line it doesn't do (a question, findings, a red check, a look), a refused start or merge, or nothing moving for `--idle` seconds. Handle that line with this skill, then run the `carry on:` command.
- **Interrupt (exit 130):** it stops at once. A start or merge still answering keeps going on its own, and its record stays for this skill to reconcile.

Builders and reviewers it started keep running after it stops. It holds the spec's heartbeat lock, so a session and a heartbeat tick never run together: a second session, or a heartbeat tick during one, is refused (exit 1).

**The heartbeat is the opt-in,** for keeping the fleet going after the chat closes. Install one local heartbeat for the spec only when the user asks for that. Its scheduled command uses the tool paths from installation.

```sh
python3 -I "<this skill's folder>/scripts/heartbeat.py" install "<owner>/<repo>" "<S>" "<harness>" "<model>"
```

Show the job to the user. On their yes, repeat with `--yes`. The script installs a per-user LaunchAgent on macOS, or a systemd user timer on Linux with crontab as the fallback when the user manager is unavailable. Each runs the installed GitHub-only `fleet.sh spec <S>` check every ten minutes. When a check finds due lines, the heartbeat wakes the saved orchestrator through the driver. The heartbeat starts an orchestrator for the spec when there is no saved run or after retiring a run the driver reports stopped or missing. The job lock covers the check and the driver calls.

Use the same script with `status|pause|resume|remove|run "<owner>/<repo>" "<S>"`. Run `run` for “run the fleet now”. Pause removes the schedule and skips manual ticks until resume restores it. Remove takes down the schedule, stops the saved orchestrator and removes the scheduler state. The private job folder under `~/.local/state/openwiz-heartbeat/` holds `ticks.log`, one short line per tick, and `last-wake/runs.json`, the active orchestrator map. For a manual stop, use that map as `LAUNCH_FLEET_RUNS` with `host.py stop <owner>/<repo> <S>`. Retired run IDs stay in private maps under `retired-runs/`. If a start is unresolved, reconcile it with the driver before moving aside the job's `starting` folder.

### Running a local wake

`host.py start OWNER/NAME N HARNESS MODEL [SKILL]` sends the named skill to the selected host driver. Leaving off `SKILL` starts `build-ticket`. The heartbeat uses `host.py start <owner>/<repo> <S> <harness> <model> launch-fleet` so the wake starts on the spec.

A driver-started `launch-fleet` wake on a non-CloudRoom host takes up that spec. Set `LAUNCH_FLEET_RUNS` to the absolute path in `LAUNCH_FLEET_HEARTBEAT_RUNS` before reading or changing project runs. The heartbeat keeps that shared project map separate from the spec's private orchestrator map. Read the project's current settings and recheck the spec with `fleet.sh spec <S>` from the wake's project checkout. Handle the due lines with the skill's claim, verification and merge gates, then record the outcomes on GitHub.

- Poll through the heartbeat. Skip CloudRoom loops, webhooks and loop records.
- Deliver to a driver-run agent with `host.py wake <owner>/<repo> <N>`. Use its recorded route and read the outcome before recording delivery.
- For an archive line, settle and record the GitHub outcome. Skip the thread archive and loop report, including at the end of this wake. End the turn.
