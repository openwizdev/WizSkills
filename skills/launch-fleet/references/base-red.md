# A red main

Read this for a `base red` or a `resume #P for #N at <head>` line (AD3, openwizdev/OpenWiz#3117).

## Pause and resume

`fleet.sh` compares the latest failing required checks on the pull request with the latest completed runs for the same names at the default branch tip. A base check is red when it concludes `failure`, `timed_out` or `startup_failure`.

- On `base red`, record `launch-fleet: paused, base red <base commit> <checks>; head <head>` on the pull request when the line asks. The same head and base commit keep one active pause. Leave the builder alone. A line saying the pause is already recorded handles only its fix issue.
- When the held checks are green on the base and the head has no failing check outside the pause, `resume` tells the builder to merge the default branch and re-run CI. After confirmed delivery, record `launch-fleet: resumed <head>, base green <base commit>` once. This delivery uses the PR resume record as its guard.
- While the base is still running or its result is unknown, the active pause holds only failures it names. A fresh PR head is judged on its own, including when an old pause lacks a head field.
- After a resume, only the held failures known to have completed before that resume are quiet. Another failing check or a later failed run is judged afresh. A legacy status uses its creation time.
- A builder-owned failure emits `CI failed`. Cross-repository pull requests keep their usual `CI failed` path.

## Open the fix issue once

The issue clause names the currently red required checks on main, using the first of those names for `Main is red: <check>` and linking its latest completed red run at that tip. An open fix issue titled for any of those checks covers the red base. An incomplete issue search withholds the issue clause. A later tick can still ask to open the issue after the pause is already recorded.

Use one repository-wide claim on the named base commit across all ticks, specs and wakes. The issue clause is an invitation to claim. Use this guard even when the current tick printed only one invitation.

1. Recheck that the issue clause still applies. Post a commit comment with exactly `launch-fleet: base fix opening` on the named base commit. Save the returned comment ID. Use the repository commit comments endpoint, `repos/<owner>/<repo>/commits/<base commit>/comments`.
2. Read all pages of that commit's comments from GitHub. Among exact opening records from the repository's record authors, only the lowest ID may proceed. A trusted `launch-fleet: base fix opened #<issue>` record ends the attempt for that commit. Stop on an incomplete read. If another claim won, withdraw your own claim with `launch-fleet: base fix withdrawn` and leave creation to its owner.
3. With the winning claim, recheck the default branch tip and its red checks. Read the repository's open issues directly, with every page, using `repos/<owner>/<repo>/issues?state=open&per_page=100`. Use exact titles for any of the red checks and exclude pull requests. An existing fix issue satisfies the claim. If nothing covers the red base and the same issue clause still applies, create the named issue with the `ready-for-agent` label, the checks and the red run link. Withdraw the claim if fresh evidence shows the issue is no longer due.
4. After reading back the matching issue, edit your claim through `repos/<owner>/<repo>/comments/<comment ID>` to `launch-fleet: base fix opened #<issue>` and verify the saved record. A later wake sees the commit comment even while issue search catches up. If the issue create or its read-back has an unknown outcome, leave the claim in place and ask the orchestrator to reconcile it against the issue list. Release an unfinished claim only after confirming the original sender has stopped and no issue was created. A claim still pending after ten minutes produces a `reconcile fix issue claim <ID>` line. Use that line to reconcile the same claim. Elapsed time alone gives no permission to create another issue.
