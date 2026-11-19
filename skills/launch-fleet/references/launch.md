# Launch a fleet

Read this when a plan graph is approved, when a spec moves to fresh wakes, or when GitHub's messages are turned on or off. Get every brief and loop prompt from `scripts/brief.py`; never write one by hand.

## Launch (the orchestrator, when the user approves a plan graph)

1. **Check the approval is recorded** on the spec issue, as `to-tickets` writes it. No record, no fleet.
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
   (umask 077; room-cli loop create --name "launch-fleet wakes <owner>/<repo>" --webhook --new-thread --priority 2 \
     --prompt "$(python3 -I "<this skill's folder>/scripts/brief.py" wakes "<owner>/<repo>" "<your thread id>")" \
     > /tmp/launch-fleet-wakes.json)
   jq -r .id /tmp/launch-fleet-wakes.json
   ```

   **The brief is only the prompt above.** Never add merge, base or workaround rules to a loop's prompt: they live in this skill, its references and `fleet.md` (M1, the base rule, and its checks), and a copy goes stale. A loop whose prompt still carries an old rule, such as closing and reopening a pull request because `main` moved, gets the prompt above again: `room-cli loop update <id> --prompt "..."`.

   It prints its id and its secret address (`url`), the address only once, into that file, which only you can read. Anyone with the address can wake the fleet, so it never goes into a comment, a file in the repository, the handoff file or a message: only into the repository's webhook (step 3). `room-cli loop hook <id>` gives it a new address, if it ever leaks; then update the webhook to it. Each run gets the messages that arrived since the last as data, and starts a fresh thread. Write both loops' ids in the handoff file (the `handoff` skill). When a new orchestrator takes over, it updates the thread id in both prompts: `room-cli loop update <id> --prompt "..."`.
3. **GitHub's messages are the user's setup.** The repository's webhook is a repository setting the user owns: ask the user ([user.md](user.md)) before it exists, and add it only on their yes, in their words in the handoff file. Either the user adds it in the repository's settings (Webhooks, Add webhook: the payload address from the file, content type `application/json`, no secret (the address is the secret), and "Let me select individual events": issues, issue comments, pull requests, pull request reviews, check suites, workflow runs), or, if they ask you to, you add it:

   ```sh
   jq -n --slurpfile w /tmp/launch-fleet-wakes.json '{name: "web", active: true,
       events: ["issues", "issue_comment", "pull_request", "pull_request_review", "check_suite", "workflow_run"],
       config: {url: $w[0].url, content_type: "json", insecure_ssl: "0"}}' \
     | gh api --method POST 'repos/{owner}/{repo}/hooks' --input - --jq '{id, events, active}'
   rm -f /tmp/launch-fleet-wakes.json
   ```

   It needs owner or admin access to the repository. GitHub sends a `ping` when a webhook is added (its documentation), which wakes one tick with nothing to read. Write the webhook's id in the handoff file. Then slow the safety net and every fleet thread's loop to every 30 minutes, as messages now wake them: `room-cli loop update <id> --cron '*/30 * * * *'`, for the safety net and for each open spec's fleet loop (the real loop id under its `S` key in the private loop file; the public record names only `fleet-<S>`), and read them back with `room-cli loop list`. If the user says no, the safety net and the fleet loops stay at every 10 minutes, and the wake loop, which nothing calls, can be deleted.
4. **Start the spec's fleet loop** ("Starting one", below). Run it once after publishing its record. If a fresh loop cannot be set up, record the reason on the spec and keep its existing routing. For a spec with no loop record, run the project's safety net once.

Done when both loops exist, the user has said yes or no to GitHub's messages, and the spec has a verified fleet loop record (or a look record explains why it could not be set up).

**Turning GitHub's messages off** (the user asks, or they misbehave): delete the webhook (`gh api 'repos/{owner}/{repo}/hooks' --jq '.[] | {id, events, active}'` lists them without their addresses; `gh api --method DELETE 'repos/{owner}/{repo}/hooks/<id>'`), delete the wake loop (`room-cli loop delete <id>`), and set the safety net and every open spec's fleet loop back to every 10 minutes (`room-cli loop update <id> --cron '*/10 * * * *'` for each, the same loops as step 3; read them back with `room-cli loop list`). Nothing else changes, and nothing else needs undoing: with no messages, no tick runs a fleet loop early; the fleet's records are all on GitHub, so the check finds where everything stands. Record it in the handoff file.

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

**A message for a spec with its own loop** prints `wake fleet #<S>: room-cli loop run fleet-<S>`. Resolve the handle through the private loop file (`LAUNCH_FLEET_LOOPS`, key `S`), run `room-cli loop run <that id>` once and do nothing else for that spec; never post the real id. If the file or key is missing, record a thread-free `launch-fleet: look: fleet loop handle unresolved` on the spec and leave it to its own loop. If CloudRoom refuses the run, record nothing: the spec's loop still runs on its own. A spec whose record names no loop, or a loop another spec in the same wake names, gets no line and waits for its loop.
