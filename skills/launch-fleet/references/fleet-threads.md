# Fleet threads

A spec's fleet thread is started by its loop; install and the orchestrator send `brief.py fleet <S> <owner>/<repo>` for its first wake, and the loop's own prompt is `brief.py wake <S> <owner>/<repo>`. The first wake is an ordinary wake.

### Starting one

The orchestrator bundles the spec's check, creates its loop as a child of the open Cloud manager on the Orchestrator row (`ops-starts.py flags --repo <owner>/<repo> fleet_thread`, given to the loop as `--provider`, `--model` and `--reasoning`), saves the loop id privately and posts the `fleet active` record, as [references/launch.md](launch.md) says. Moving an existing fleet keeps its builders, selected reviewers and review rounds.

### Each wake

**First, the Orchestrator row:** with this spec's loop id (`route.py loop "$LAUNCH_FLEET_LOOPS" <S>`), run `room-cli loop list | python3 -I "<this skill's folder>/scripts/ops-starts.py" loop-agent --repo <owner>/<repo> <loop id> -`. `current` goes on. `stale: room-cli loop update <loop id> ...` means the Models table's Orchestrator row changed: run that update, check again until it prints `current`, run `room-cli loop run <loop id>` once, report `acted` with `--action "fleet #<S> loop on the Orchestrator row"` and end, doing no other work, so the next wake starts on the new row and threads already running finish on theirs. Exit 2 (an unreadable table, listing or loop): report `needs-you` with its reason and end.

Then do "Each wake" above for `fleet.sh spec <S>`. Before any merge, require the same merge line from `fleet.sh every`. Read verdicts and quiet reviewers on GitHub, never from thread output. An unreachable archive or a required retirement is relayed privately to the planner or orchestrator and stays pending until confirmed. Save routing changes, the run map's too, to the private repository's latest map, preserving other entries, and read them back before posting public success; on a race, re-read and reconcile.
