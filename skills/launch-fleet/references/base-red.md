# A red main

Read this for a `base red` or a `resume #P for #N at <commit>` line (AD3, openwizdev/OpenWiz#3117).

When `main` is red, every open pull request fails the same checks, and none of their builders caused it. `fleet.sh` stops telling them so: a pull request whose failing checks all fail on main too is paused, main gets one fix ticket, and the paused pull requests resume once main is green.

## How fleet.sh decides

Where it would print `CI failed #P`, it first reads the checks on the tip of the default branch (`commits/<default>/check-runs`, one REST read for the whole tick) and takes the latest completed run of each check name there. Then, for that pull request's failing required checks:

- **All of them fail on main** (`failure`, `timed_out` or `startup_failure`): `base red #P for #N at <head>: <checks> fail(s) on main at <base commit> too; record paused, base red <base commit> <checks>, and leave its builder be`. Nothing is printed while the pull request's latest pause or resume record is a pause for that same base commit.
- **The pull request is paused** (its latest such record is `paused, base red`) and every check that pause named is green on main: `resume #P for #N at <head>: main is green again at <base commit> (<checks>); tell its builder to merge main in and re-run CI, thread <id>; record resumed <head>, base green <base commit>`. A `resumed` record naming the current head prints nothing more.
- **Paused, and main is not green yet** (still red, or still running): nothing; it stays paused.
- **Anything else** (a check green on main, a check with no completed run on main, a pull request in another repository): `CI failed`, as before.

## The fix ticket

When one of main's checks is red, `fleet.sh` also searches the open issues for titles `Main is red: <check>`. If none of the failing checks has one, the first `base red` line of the tick ends `; open issue "Main is red: <first check>" labelled ready-for-agent, naming <checks> and its first red run <link>`. Open exactly that issue: its title, the `ready-for-agent` label, and a body that names the failing checks, the base commit and the run link from the line. Later lines and later ticks find it open and ask for nothing. A search GitHub reports as incomplete asks for nothing, so a second issue is never opened.

## Records

On the pull request, each written once:

| Record | Means |
| --- | --- |
| `launch-fleet: paused, base red <base commit> <check>, <check>` | Its failures are main's; its builder was not told |
| `launch-fleet: resumed <head>, base green <base commit>` | Main was green again; its builder was told to merge main in and re-run CI |

A paused pull request that gets a new head and fails again is judged afresh at that head, against main as it is then.
