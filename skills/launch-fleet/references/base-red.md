# A red main

Read this for a `base red` or a `resume #P for #N at <commit>` line (AD3, openwizdev/OpenWiz#3117).

When `main` is red, open pull requests fail the same checks, and their builders did not cause it. `fleet.sh` pauses a pull request whose failing checks all fail on main, asks for one fix ticket, and resumes the paused pull requests once main is green.

## How fleet.sh decides

Where it would print `CI failed #P`, it first reads the checks on the tip of the default branch (`commits/<default>/check-runs`, one REST read for the whole tick) and keeps the latest completed run of each check name. A run is red only when its conclusion is `failure`, `timed_out` or `startup_failure`. Then, for that pull request's failing required checks:

- **All of them are red on main:** `base red #P for #N at <head>: <checks> fail(s) on main at <base commit> too; record paused, base red <base commit> <checks>, and leave its builder be`. Nothing is printed when the pull request's latest pause or resume record is already a pause for that same base commit.
- **The pull request is paused** and every check that pause named is green on main, and it is not failing a check outside that pause: `resume #P for #N at <head>: main is green again at <base commit> (<checks>); tell its builder to merge main in and re-run CI`. A `resumed` record that names the current head prints nothing more.
- **Paused, and main is not green yet** (still red, still running, or not a red conclusion): nothing, while none of its failing checks is green on main.
- **Anything else** (a failing check that is green on main, a check with no completed run on main, a pull request in another repository): `CI failed`, as before.

## The fix ticket

When one of main's checks is red, `fleet.sh` searches the open issues for titles `Main is red: <check>`. The first red run is the latest completed run of that check on main's tip, the run this tick sees. If none of the failing checks already has an open issue, the first `base red` line of the tick ends `; open issue "Main is red: <first check>" labelled ready-for-agent, naming <checks> and its first red run <link>`. Open exactly that issue. Later lines in the tick, and later ticks that find it open, ask for nothing. A search GitHub reports as incomplete asks for nothing, so a second issue is never opened on a partial list.

## Records

On the pull request, each written once:

| Record | Means |
| --- | --- |
| `launch-fleet: paused, base red <base commit> <check>, <check>` | Its failures are main's; its builder was not told |
| `launch-fleet: resumed <head>, base green <base commit>` | Main was green again; its builder was told to merge main in and re-run CI |

The resume line's record is its guard. It is not one of the four `fleet.sh claim` lines (`start`, `review`, the builder `resume #<ticket>`, `release`): claiming it would withdraw. A paused pull request that gets a new head is judged again at that head. A pause for the same base commit is not recorded twice.
