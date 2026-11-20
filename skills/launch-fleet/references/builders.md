# Builders

Read this for a `start`, `reconcile start`, `check start`, `resume` or `reconcile resume` line, a refused probe, or a Claude plan-limit restart. The builder brief is `python3 -I scripts/brief.py builder <N>`.

## 3. Builders

**Starting one** (a `start` line):

1. **Claim it.** Post `launch-fleet: starting` on the ticket with `post.py comment`, which prints its id. Then ask the check whether your claim stands: `sh "<this skill's folder>/scripts/fleet.sh" claim <N> <your comment's id>`. It reads the ticket afresh and prints `go #<N>` only when no older claim is still live (`starting`, `started` or `start checked`), no builder is recorded, no pull request is open, and the ticket is still on the frontier. Anything else (`withdraw #<N>: <why>`, or an error): edit your claim to `launch-fleet: start withdrawn`, and stop. Two ticks that overlap can't both start a builder: the older claim wins, and it keeps the ticket as you edit it to `started` and `start checked`.
2. **Start it,** with `fleet.md`'s `## Builder for small tickets` table for an exact `polish`, `huntr` or `proposal` label, otherwise `## Builder`, the ticket in its title, and the one-line brief `brief.py builder` prints, the same for every builder:

   ```sh
   room-cli thread spawn --top-level --provider <harness> --model <model> --reasoning-level <effort> \
     --title "#<N>: <ticket title>" \
     --prompt "$(python3 -I "<this skill's folder>/scripts/brief.py" builder <N>)"
   ```

   Everything about the work is in the ticket and its spec, so the brief never drifts from them. A top-level thread starts from the default branch on GitHub, and outlives this tick. A fleet thread starts it as its own child instead (`--parent-self --project "$ROOM_PROJECT_ID"` in place of `--top-level`), so it can reach it (SKILL.md, "Fleet threads").

3. **Record the outcome** by editing your claim (`post.py edit`): `launch-fleet: started` when CloudRoom started it, or `launch-fleet: start refused: <its reason>` when it said no. A refused start stays on the frontier, and is tried again 10 minutes after the refusal (the edit that made your claim one), not sooner: the refusal's record is itself one of GitHub's messages, which would otherwise wake a retry at once, again and again. If the start timed out or you can't tell, leave the claim as it is: the check asks for a reconcile after 10 minutes.

**Never wait awake.** No brief or message from a tick asks an agent to stay awake while it waits: a builder or reviewer never keeps a background watcher, a poll loop or a `sleep` waiting for CI, a review or another thread, and ends its turn instead, as `build-ticket` and `review-ticket` say. The tick's next message (CI failed, findings, a re-check, a resume) is what wakes it. A message that tells one to wait for something (#B to merge, say) says to end its turn until the resume (Jake, the cheaper-factory grill, CF1).

**One probe per batch.** Before claiming, read each `start` ticket's labels and pick its builder table, as step 2 above says: that is its assignment, and the starts with one assignment are one group. Claim them all as in step 1; then start that group's first claim alone, the probe. If CloudRoom starts it, start the rest of the group in parallel. If it refuses the probe for a reason that is not that ticket's own (the model catalog, the account or plan, the provider), edit the probe's claim to `launch-fleet: start refused: <reason>`, and every other claim of the group to `launch-fleet: start not tried: #<probe> was refused: <reason>`, without starting them. Each waits the same 10 minutes as a refusal, so the group retries together, with one probe again. A refusal for the ticket's own reason ends only that start: the next claim becomes the probe. Never swap in another provider or model.

**Claude plan-limit restart (#1196):** if `## Builder for small tickets` still selects `claude-code`, the tick prints `look: fallback builder is the limited family` and saves no fallback record; wait for an approved setting from another family before restarting. Otherwise, a Rust tick `restart` due item records `launch-fleet: builder fallback due, branch <branch>` on the ticket and names the small-ticket builder settings. Reconcile that recorded item before acting: never start twice. Stop/archive the limited builder, preserve its branch, then start the replacement from that branch using `## Builder for small tickets`, with the ticket brief and an explicit instruction to continue its existing work. Keep the old and replacement identities, the fallback claim, the branch and their handover lineage exclusively in private state; update the private builder mapping to the replacement after its start is confirmed. Update the original public checked-start record to `launch-fleet: start checked, branch <branch>`, keeping the same branch. The fallback comment keeps its branch-only first line, with no replacement identity appended. The private handover retires the old stored builder when the tick next reads it. It retains the original code on the branch, so the tick leaves the builder family conflicting for new reviewer assignments. First and fresh reviews print `look` and start no reviewer; the orchestrator or Jake chooses the reviewer explicitly. Never apply this fallback to a reviewer; its review waits for its family. A consumed fallback is never tried again automatically; an uncertain restart goes to the orchestrator.

**Reconciling** (a `reconcile start` line): before any retry, find out whether a builder started. Look for a thread titled `#<N>:` in `room-cli thread list`, and for its branch (`git ls-remote origin 'refs/heads/room/<N>-*'`). If one is there, edit the claim to `launch-fleet: started`. If not, edit it to `launch-fleet: start failed: <why>`, and the next tick starts it again. A ticket never gets two builders.

**Checking** (a `check start` line): its thread exists and is working, its title names the ticket, and its branch shows up. Then edit the claim to `launch-fleet: start checked, branch <branch>`. If the thread is gone or never started work, edit it to `launch-fleet: start failed: <why>`.

A builder stays with its ticket through every review round, and is archived when its ticket closes. It is never given another ticket.

**Waiting on another ticket (#467):** whoever tells an existing builder to
wait for #B, including the orchestrator answering a builder's question, must
also add a new `launch-fleet: waiting for #B` comment on its ticket. Post it
even when the answer uses free-form prose such as "Once #B has a verified
merge, continue." The latest wait replaces the previous one. The check also
reads the legacy first line `Orchestrator (PC, ops): **wait for #B.** ...`,
with or without the parenthesized context, an optional `yes, ` or `confirmed: `
lead-in (comma or colon accepted), and an optional period inside the bold.
Those known forms cover existing waits; new instructions always get the
structured record. It prints
`resume` only after #B is closed by a pull request merged into the default
branch. A closed issue alone is insufficient. The safety net and the full
check after a merge find waiting builders; a targeted wake finds only the
waiting tickets it names. Delivery is recorded against that wait comment's
id, so the same wait is not sent twice and a new wait can be sent again.

**Delivering a resume:** comment `launch-fleet: resume starting C for #B` on #N, then run `sh "<this skill's folder>/scripts/fleet.sh" claim N <your comment id>`. Only
`go #N` may tell its recorded builder that #B merged and to continue the
instructions in wait comment C. An older claim wins, so overlapping ticks
cannot both deliver. On success, edit your claim to `launch-fleet: resume sent
C for #B`; on a definite failure, edit it to `launch-fleet: resume failed C for
#B: <why>`. On `withdraw`, edit your claim to `launch-fleet: resume withdrawn C
for #B` and send nothing.

A claim with no outcome after 10 minutes prints `reconcile resume`. Read the
claiming thread and the builder's delivery history before any retry. Proven
delivery edits that claim to `resume sent`; a definite non-delivery edits it
to `resume failed`. A still-running or unreadable sender, or an uncertain
delivery, stays claimed and goes to the orchestrator. Never resend on a
reconcile without proving the earlier delivery did not happen.

## The due lines in full

| Line | Do |
| --- | --- |
| `look #N: blocked on scope <key>: ...` | Its builder waits on its own scope question (`needs-info`), with no branch, past the 30-minute start check. Read the builder's thread once: if it is gone, edit its start record to `launch-fleet: start failed: <why>` and tell the orchestrator. Either way, record `launch-fleet: look: <the reason>`. The check raises it once per key (the start record and the latest plain comment, written or edited; never launch-fleet's own records), so it comes back only when the question is answered or edited, a new builder starts or the `needs-info` label comes off |
