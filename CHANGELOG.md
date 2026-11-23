# Changelog

## 0.4.3 - 2026-11-23

- `install` 0.4.2: Install checks the OpenWiz version before offering agent hosts and offers only CloudRoom for OpenWiz 0.1.0.

## 0.4.2 - 2026-11-23

- Two packaged files no longer spell a machine home path literally.
- `launch-fleet` 0.4.1: Two packaged files no longer spell a machine home path literally.
- `triage` 0.3.1: Two packaged files no longer spell a machine home path literally.

## 0.4.1 - 2026-11-22

- `install` 0.4.1: Without CloudRoom, Connect now recommends your verified personal GitHub login (`github_login.py skip-app`) instead of the GitHub App, whose setup needs CloudRoom today; the App is still there if you ask for it, and with CloudRoom the App stays the recommendation. Step 4 now refreshes the install skill from this release's own tag (or the verified build's copy when it already matches), never from `main`, so the restart keeps this fix.

## 0.4.0 - 2026-11-22

- Skills added: `feedback`, `write-driver`.
- The `feedback` skill is back: your agent files one public OpenWiz issue only after its exact preview and your explicit yes with its code, and tells you triage labels it `feedback`, and that the issue gets one comment naming the fix's pull request and release only if triage sends it to a fleet and that fix merges.
- The plan links contract and `check-links.sh` read a `## Links` line that names its blocker in the long form of the plan's own repository (`owner/name#N`, any case) as `#N`, and refuse one naming another repository with its line named.
- The models and feedback-loop contract copies match OpenWiz main again: local host selection and labelled model choices, and the feedback form's pinned warning and confirmation.
- `ask-wiz` 0.2.2: Comments in skill scripts and tests are cut to the kinds the comments contract allows; behaviour is unchanged, and CI now fails a pull request that adds any other comment.
- `ask-wiz` 0.2.2: The `feedback` skill is back: your agent files one public OpenWiz issue only after its exact preview and your explicit yes with its code, and tells you triage labels it `feedback`, and that the issue gets one comment naming the fix's pull request and release only if triage sends it to a fleet and that fix merges.
- `ask-wiz` 0.2.2: New write-driver skill: paste one line and it takes you to an OpenWiz driver of your own that passes 5 of 5 on your host, reports the time from paste, and shares it only on your yes; ask-wiz routes to it.
- `build-ticket` 0.2.2: Builders ask for a missing proof or a narrow grant through the status writer's `asking` write, reviewers' status line names the ticket number rather than the pull request's, and a log-and-merge check refuses a new finding on unchanged code.
- `build-ticket` 0.2.2: Comments in skill scripts and tests are cut to the kinds the comments contract allows; behaviour is unchanged, and CI now fails a pull request that adds any other comment.
- `build-ticket` 0.2.2: Builders commit only as their GitHub noreply address: `ticket.py author` refuses while anything overrides it, and `ticket.py push` sends only HEAD to origin and refuses any commit origin lacks whose author or committer is not a noreply address named as its login.
- `build-ticket` 0.2.2: Builders take only the App's token and push from the identity page and keep the identity `ticket.py author` set.
- `build-ticket` 0.2.2: `ticket.py push` reports a commit whose name is not its noreply address's login apart from one whose address is not a noreply address.
- `diagnose` 0.2.2: Comments in skill scripts and tests are cut to the kinds the comments contract allows; behaviour is unchanged, and CI now fails a pull request that adds any other comment.
- `feedback` 0.3.0: The `feedback` skill is back: your agent files one public OpenWiz issue only after its exact preview and your explicit yes with its code, and tells you triage labels it `feedback`, and that the issue gets one comment naming the fix's pull request and release only if triage sends it to a fleet and that fix merges.
- `feedback` 0.3.0: Comments in skill scripts and tests are cut to the kinds the comments contract allows; behaviour is unchanged, and CI now fails a pull request that adds any other comment.
- `grill` 0.2.2: Comments in skill scripts and tests are cut to the kinds the comments contract allows; behaviour is unchanged, and CI now fails a pull request that adds any other comment.
- `handoff` 0.3.1: Comments in skill scripts and tests are cut to the kinds the comments contract allows; behaviour is unchanged, and CI now fails a pull request that adds any other comment.
- `handoff` 0.3.1: The installed install, setup, triage, handoff and where-are-we skills no longer ship their recorded evidence logs; their instructions, references, scripts and tests are unchanged.
- `hill-climb` 0.2.2: Comments in skill scripts and tests are cut to the kinds the comments contract allows; behaviour is unchanged, and CI now fails a pull request that adds any other comment.
- `huntr` 0.2.2: Comments in skill scripts and tests are cut to the kinds the comments contract allows; behaviour is unchanged, and CI now fails a pull request that adds any other comment.
- `image` 0.2.2: Comments in skill scripts and tests are cut to the kinds the comments contract allows; behaviour is unchanged, and CI now fails a pull request that adds any other comment.
- `install` 0.4.0: A new project starts with one Models table (Orchestrator, Builder and Reviewer, with the Small builder and Fixer following the Builder): setup writes and checks it, still accepting the older five tables, and the first fleet's choice writes the harness, model and effort into it and starts from it.
- `install` 0.4.0: The onboarding road offers every host your installed OpenWiz has a working driver for, boat.dev included, says why any other driver isn't offered, and writes your pick as the project's host setting.
- `install` 0.4.0: Run your first fleet with the local heartbeat when you choose this computer, boat.dev, or another driver.
- `install` 0.4.0: Comments in skill scripts and tests are cut to the kinds the comments contract allows; behaviour is unchanged, and CI now fails a pull request that adds any other comment.
- `install` 0.4.0: The installed install, setup, triage, handoff and where-are-we skills no longer ship their recorded evidence logs; their instructions, references, scripts and tests are unchanged.
- `install` 0.4.0: The install skill sets up with `setup.py check`, giving each code its next step with no setup page, installs skills into your agents and puts the binary at `<root>/current/openwiz`. Choosing OpenWiz 0.1.0 hands you to the 0.1.0 install instructions (WizSkills `maint/0.2`) and their pinned `v0.1.0` fetch.
- `install` 0.4.0: The Models section `choose` adds to older fleet settings now has its Source line, so Connect still accepts the file. A retried first-fleet launch asks for a fresh preview and yes if the Orchestrator changed before the fleet started.
- `install` 0.4.0: Step 4 now overwrites only the skill folders OpenWiz's installer installed itself. Removing OpenWiz stops the local heartbeat first, then runs the installer's own remove after showing you what it will delete. Known limit (openwizdev/openwiz#2377): if a second install keeps its state folder inside the first one's, removing the first also removes the second's heartbeat; check the listed jobs before removing.
- `install` 0.4.0: The install skill installs the release it fetches: preflight clones that release's tag, the fallback fetches its files, and the done check expects its version; 0.1.0 stays installable by naming its tag. The restart and resume checks read the skill's own version, so a release bump no longer stops the install.
- `install` 0.4.0: The install no longer requires CloudRoom: it asks first where your agents run (this computer, boat.dev or CloudRoom, as equal choices), runs CloudRoom's steps only if you pick it, and this computer leads straight into the first fleet with no CloudRoom project or answer thread.
- `launch-fleet` 0.4.0: launch-fleet starts every agent from the one Models table in `docs/agents/fleet.md`, read from GitHub's default branch at each start: builders, small builders, reviewers by the cross-family rule, fixers by the fixer rule, and a spec's fleet thread on the Orchestrator row, which each wake keeps its loop on. Projects with only the older five tables keep working, read whole. `ops-starts.py flags --repo <owner>/<repo>` prints each start's spawn flags.
- `launch-fleet` 0.4.0: launch-fleet holds the final merge of a user-visible spec, or a release, for the owner's late look: `merge.py ask` posts the checkpoints contract's evidence ask on the spec, and `merge.py merge` merges only once the owner's late-look record approves that head; every other merge flows as before.
- `launch-fleet` 0.4.0: With a token service configured, launch-fleet gives every agent it starts and every fleet wake its GitHub token through the agent helper, and each brief keeps approvals, settings and workflow pushes on the owner's login; with none, nothing changes.
- `launch-fleet` 0.4.0: When a fix for a feedback report merges, launch-fleet posts one comment on the report saying it landed, in which pull request and which release will carry it.
- `launch-fleet` 0.4.0: launch-fleet's `host.py start` takes an optional skill to run through the host's driver, such as `review-ticket` or `launch-fleet`; without one it starts `build-ticket` exactly as before.
- `launch-fleet` 0.4.0: Run a fleet's GitHub heartbeat every ten minutes on your computer, with commands to preview, install, pause, resume, remove or run it now.
- `launch-fleet` 0.4.0: Fleets outside CloudRoom start, wake and stop reviewers through the host driver, using the other harness when both are installed and marking reviews by the same family when only one is available.
- `launch-fleet` 0.4.0: Comments in skill scripts and tests are cut to the kinds the comments contract allows; behaviour is unchanged, and CI now fails a pull request that adds any other comment.
- `launch-fleet` 0.4.0: launch-fleet finds its builders and reviewers through a Local `room-cli` on your own machine as well as through the Cloud CLI, reading both thread-list answers.
- `launch-fleet` 0.4.0: A long-form reference to the fleet's own repository (`owner/name#N`, any case) reads as `#N` in approval rows, waits, claims and holds, and one naming another repository is refused with its line named instead of being skipped silently.
- `launch-fleet` 0.4.0: On a merge-queue repository, `merge.py merge` enqueues through GitHub's merge queue pinned to the approved head, refuses while required checks are still running, and writes its `merge queued` receipt only after it reads the queue entry back.
- `launch-fleet` 0.4.0: launch-fleet's models test fixture for an older-tables `set` now matches OpenWiz's, with the `Source:` line `set` adds.
- `launch-fleet` 0.4.0: The local heartbeat's `status` now names an unresolved start's folder and tells you to run `remove` once the spec is done, a closed spec's tick logs `done` instead of `idle`, and `remove` retires a saved run the driver no longer knows instead of refusing; the webhook setup no longer subscribes to check suites.
- `research` 0.2.2: Comments in skill scripts and tests are cut to the kinds the comments contract allows; behaviour is unchanged, and CI now fails a pull request that adds any other comment.
- `review-ticket` 0.4.0: Fleets outside CloudRoom start, wake and stop reviewers through the host driver, using the other harness when both are installed and marking reviews by the same family when only one is available.
- `review-ticket` 0.4.0: Builders ask for a missing proof or a narrow grant through the status writer's `asking` write, reviewers' status line names the ticket number rather than the pull request's, and a log-and-merge check refuses a new finding on unchanged code.
- `review-ticket` 0.4.0: Comments in skill scripts and tests are cut to the kinds the comments contract allows; behaviour is unchanged, and CI now fails a pull request that adds any other comment.
- `review-ticket` 0.4.0: A re-check after a large `main` merge now checks the pull request's own changes from the local checkout instead of failing at GitHub's 300-file compare limit, and says which commit it could not read when it refuses.
- `setup` 0.3.0: A new project starts with one Models table (Orchestrator, Builder and Reviewer, with the Small builder and Fixer following the Builder): setup writes and checks it, still accepting the older five tables, and the first fleet's choice writes the harness, model and effort into it and starts from it.
- `setup` 0.3.0: A new project starts with a Roster of one entry, the person's own harness taking every role, and setup's check reads the table, refusing a malformed row or an unknown role by name.
- `setup` 0.3.0: The installed install, setup, triage, handoff and where-are-we skills no longer ship their recorded evidence logs; their instructions, references, scripts and tests are unchanged.
- `to-spec` 0.3.0: Every new spec carries its two checkpoint answers (one-way door, user-visible), and to-tickets' approval check refuses a new spec without them; older specs read as early only.
- `to-spec` 0.3.0: Comments in skill scripts and tests are cut to the kinds the comments contract allows; behaviour is unchanged, and CI now fails a pull request that adds any other comment.
- `to-spec` 0.3.0: write-driver no longer ships a generated Python bytecode file; to-spec drops a test that only checked its own wording.
- `to-tickets` 0.3.0: Every new spec carries its two checkpoint answers (one-way door, user-visible), and to-tickets' approval check refuses a new spec without them; older specs read as early only.
- `to-tickets` 0.3.0: Comments in skill scripts and tests are cut to the kinds the comments contract allows; behaviour is unchanged, and CI now fails a pull request that adds any other comment.
- `to-tickets` 0.3.0: A long-form reference to the fleet's own repository (`owner/name#N`, any case) reads as `#N` in approval rows, waits, claims and holds, and one naming another repository is refused with its line named instead of being skipped silently.
- `to-tickets` 0.3.0: The plan links contract and `check-links.sh` read a `## Links` line that names its blocker in the long form of the plan's own repository (`owner/name#N`, any case) as `#N`, and refuse one naming another repository with its line named.
- `to-tickets` 0.3.0: to-tickets pins its relies check reading the whole ticket before refusing a planned path, and write-driver's eval names the wake-note evidence and pull request URL it supplies rather than observes.
- `triage` 0.3.0: Triage sends a small, clear OpenWiz feedback report to a fleet as an approved brief with owned paths and both closing lines, linked back to the report; holds every other report for the owner; and never replies on a report without the owner's yes to the exact text.
- `triage` 0.3.0: Comments in skill scripts and tests are cut to the kinds the comments contract allows; behaviour is unchanged, and CI now fails a pull request that adds any other comment.
- `triage` 0.3.0: The installed install, setup, triage, handoff and where-are-we skills no longer ship their recorded evidence logs; their instructions, references, scripts and tests are unchanged.
- `triage` 0.3.0: Triage's tests now check the no-reply rule on feedback reports by running the feedback path against a fake GitHub and watching every write.
- `wayfind` 0.2.2: Comments in skill scripts and tests are cut to the kinds the comments contract allows; behaviour is unchanged, and CI now fails a pull request that adds any other comment.
- `where-are-we` 0.2.1: Comments in skill scripts and tests are cut to the kinds the comments contract allows; behaviour is unchanged, and CI now fails a pull request that adds any other comment.
- `where-are-we` 0.2.1: The installed install, setup, triage, handoff and where-are-we skills no longer ship their recorded evidence logs; their instructions, references, scripts and tests are unchanged.
- `write-driver` 0.3.0: New write-driver skill: paste one line and it takes you to an OpenWiz driver of your own that passes 5 of 5 on your host, reports the time from paste, and shares it only on your yes; ask-wiz routes to it.
- `write-driver` 0.3.0: write-driver gains an end-to-end eval: a scripted session runs the skill's script steps against a fake host, from paste to 5 of 5, its time and its share, recording synthetic wake-note evidence and reporting a supplied pull request URL, and fails if a costly step runs unasked, a live lesson is skipped, the clock does not start at paste, or a declined share posts.
- `write-driver` 0.3.0: write-driver no longer ships a generated Python bytecode file; to-spec drops a test that only checked its own wording.
- `write-driver` 0.3.0: to-tickets pins its relies check reading the whole ticket before refusing a planned path, and write-driver's eval names the wake-note evidence and pull request URL it supplies rather than observes.

## 0.3.1 - 2026-11-22

- `install` 0.3.1: Install OpenWiz 0.1.0 without CloudRoom and resolve all clashing skill names with one confirmation.

## 0.3.0 - 2026-11-20

- `ask-wiz` 0.2.1: The installed grill, ask-wiz, build-ticket and review-ticket skills no longer ship their recorded evidence logs; their instructions, references, scripts and tests are unchanged.
- `build-ticket` 0.2.1: The status writer accepts each skill at its own installed version, the `version:` in its `SKILL.md` front matter, so one note can name skills at different versions; a skill or version that is not installed is still refused, and notes written earlier still read. Builders and reviewers report each skill at that version.
- `build-ticket` 0.2.1: The installed grill, ask-wiz, build-ticket and review-ticket skills no longer ship their recorded evidence logs; their instructions, references, scripts and tests are unchanged.
- `diagnose` 0.2.1: The huntr, image, hill-climb, research, diagnose and wayfind skills no longer ship recorded evidence logs, recorded red-run fixtures or two internal-only tests; every instruction, reference and script an agent runs is unchanged.
- `grill` 0.2.1: The installed grill, ask-wiz, build-ticket and review-ticket skills no longer ship their recorded evidence logs; their instructions, references, scripts and tests are unchanged.
- `handoff` 0.3.0: handoff and launch-fleet move to 0.3.0, so their versions stay distinct from the 0.2.1 maintenance release, which carried only the synthetic-token renames.
- `handoff` 0.3.0: Handoff's and launch-fleet's shipped tests and evidence now use only the synthetic thread ids, email domains and paths OpenWiz's release privacy scan allows, so the packaged skills pass that scan; every test checks what it did before.
- `hill-climb` 0.2.1: The huntr, image, hill-climb, research, diagnose and wayfind skills no longer ship recorded evidence logs, recorded red-run fixtures or two internal-only tests; every instruction, reference and script an agent runs is unchanged.
- `huntr` 0.2.1: The huntr, image, hill-climb, research, diagnose and wayfind skills no longer ship recorded evidence logs, recorded red-run fixtures or two internal-only tests; every instruction, reference and script an agent runs is unchanged.
- `image` 0.2.1: The huntr, image, hill-climb, research, diagnose and wayfind skills no longer ship recorded evidence logs, recorded red-run fixtures or two internal-only tests; every instruction, reference and script an agent runs is unchanged.
- `install` 0.3.0: Install's first-fleet branch becomes the onboarding road: the agent asks where agents run (this machine or Cloudroom), offers three ways to start with ideas, runs a short grill you confirm in chat, lets the plan approve itself by its checks, asks the owner to pick the harness permission mode once on this machine, asks one yes naming the host and its cost right before the fleet starts through launch-fleet's own start path (the spec video is skipped without Node), teaches at each moment, and ends at your first merged pull request with a closing offer.
- `launch-fleet` 0.3.0: handoff and launch-fleet move to 0.3.0, so their versions stay distinct from the 0.2.1 maintenance release, which carried only the synthetic-token renames.
- `launch-fleet` 0.3.0: Install's first-fleet branch becomes the onboarding road: the agent asks where agents run (this machine or Cloudroom), offers three ways to start with ideas, runs a short grill you confirm in chat, lets the plan approve itself by its checks, asks the owner to pick the harness permission mode once on this machine, asks one yes naming the host and its cost right before the fleet starts through launch-fleet's own start path (the spec video is skipped without Node), teaches at each moment, and ends at your first merged pull request with a closing offer.
- `launch-fleet` 0.3.0: The status writer accepts each skill at its own installed version, the `version:` in its `SKILL.md` front matter, so one note can name skills at different versions; a skill or version that is not installed is still refused, and notes written earlier still read. Builders and reviewers report each skill at that version.
- `launch-fleet` 0.3.0: The merge helper posts a cost on the ticket's own repository, adds `merge.py settle` for a queued merge's cost, and records its queue receipt before enqueueing.
- `launch-fleet` 0.3.0: A wake keeps a red nightly alert and runs its status check before ending with nothing due, claims only the start, review, resume and release lines `fleet.sh claim` admits, calls its own `merge.py` by the loaded skill's absolute path from the project checkout, and settles a queued merge's cost with `merge.py settle` before archiving its ticket.
- `launch-fleet` 0.3.0: launch-fleet's status writer refuses a note holding a forward-slash drive path (`C:/…`), an scp-style `host:/…` path or a colon-form key such as `api_key:`, `access_token:` or `auth:`, including one in a web link's query or fragment, while a public link with a colon in its path still writes.
- `launch-fleet` 0.3.0: A `status.py run` heartbeat never removes `needs-info`. It still adds the label for an asking note, and the agent's own status write leaving asking clears it, so a hold a person set, or one the wake's repair put back, stays.
- `launch-fleet` 0.3.0: A `status.py write` leaving asking takes `needs-info` off only when its own write provably applied it. Any other `needs-info` stays, such as one a person or triage set under the same login or one the wake's repair put back, and the write prints `needs-info left on`.
- `launch-fleet` 0.3.0: Fleet starts match a native blocker by its exact node, so a same-number issue in another repository stays a hard blocker. A builder start, and a legacy takeover, also check collisions against running work that lost its ready label on a hold.
- `launch-fleet` 0.3.0: launch-fleet no longer ships its recorded red, green and proof captures: the two `evidence/` folders and the unread run logs in `scripts/fixtures/` are gone. Git history keeps them.
- `launch-fleet` 0.3.0: Handoff's and launch-fleet's shipped tests and evidence now use only the synthetic thread ids, email domains and paths OpenWiz's release privacy scan allows, so the packaged skills pass that scan; every test checks what it did before.
- `research` 0.2.1: The huntr, image, hill-climb, research, diagnose and wayfind skills no longer ship recorded evidence logs, recorded red-run fixtures or two internal-only tests; every instruction, reference and script an agent runs is unchanged.
- `review-ticket` 0.3.0: review-ticket gains a comment pass: on a pull request's diff, a justification or workaround comment, an unjustified suppression or an allowed form a comment has not earned is a finding whose fix changes the code or deletes the comment, with a helper that reads only the diff.
- `review-ticket` 0.3.0: The status writer accepts each skill at its own installed version, the `version:` in its `SKILL.md` front matter, so one note can name skills at different versions; a skill or version that is not installed is still refused, and notes written earlier still read. Builders and reviewers report each skill at that version.
- `review-ticket` 0.3.0: The installed grill, ask-wiz, build-ticket and review-ticket skills no longer ship their recorded evidence logs; their instructions, references, scripts and tests are unchanged.
- `to-spec` 0.2.1: to-spec and to-tickets no longer ship recorded evidence, red and green logs or sample renders; every instruction, reference, script and the tests that guard them stay.
- `to-tickets` 0.2.1: to-spec and to-tickets no longer ship recorded evidence, red and green logs or sample renders; every instruction, reference, script and the tests that guard them stay.
- `wayfind` 0.2.1: The huntr, image, hill-climb, research, diagnose and wayfind skills no longer ship recorded evidence logs, recorded red-run fixtures or two internal-only tests; every instruction, reference and script an agent runs is unchanged.

## 0.2.1 - 2026-11-20

- `handoff` 0.2.1: Handoff's and launch-fleet's shipped tests and evidence now use only the synthetic thread ids, email domains and paths OpenWiz's release privacy scan allows, so the packaged skills pass that scan; every test checks what it did before.
- `launch-fleet` 0.2.1: Handoff's and launch-fleet's shipped tests and evidence now use only the synthetic thread ids, email domains and paths OpenWiz's release privacy scan allows, so the packaged skills pass that scan; every test checks what it did before.

## 0.2.0 - 2026-11-20

- WizSkills 0.2.0: 18 skills, each one short job in plain steps, with its mechanics in tested scripts, so your agents load a fraction of the text.
- Skills added: `to-spec`, `to-tickets`.
- Skills removed: `feedback`, `feedback-triage`, `onboard`, `overnight`, `plan-graph`.
- `build-ticket` 0.2.0: The builder checklist states the current review-round limit (one review plus one re-check, then at most one fresh round) in place of "2 + 1".
- `diagnose` 0.2.0: The loop's clean also reads each file's staged copy, so a debug tag Git would commit is never called clean, and a timed-out rate run has its whole process group stopped before the next run starts.
- `grill` 0.2.0: wayfind's frontier refuses an issue without the `wayfind:map` label and a Record authors row with extra columns; grill's helper tests pin its refusal of a changed or superseded same-ID request.
- `huntr` 0.2.0: Every final path of a hunt now ends with `lease.mjs finish`, which publishes the final result and releases the lease even through a brief GitHub read failure; a dispatch that blocks every slice finishes at once; and pacing refuses a last-empty time without Z or an offset.
- `install` 0.2.0: A resumed first fleet returns to Connect for a repository setup already prepared, and to Choose the agents while Local is chosen or the Cloud choice's builder tables have not read back.
- `install` 0.2.0: The setup doctor's fixes now fix what they name (App repository selection, an unoffered model or effort, a complete prepare preview, a separate driver), and it withholds a driver answer the driver kit flags as possibly holding a credential.
- `launch-fleet` 0.2.0: launch-fleet is a short dispatcher over tested scripts (merge, records, briefs) and posts each merged ticket's cost line; the supervised pass runner (`loop.sh --pass`, `--ack`) and the dormant installation reader are removed.
- `launch-fleet` 0.2.0: launch-fleet starts a spec's fleet on to-tickets' machine plan approval, with no human approval. Comments on the spec's video steer nothing until OpenWiz #1402's identity separation is verified; the check says so once, and the owner steers through the orchestrator.
- `launch-fleet` 0.2.0: launch-fleet wakes the right fleet for GitHub messages from any repository whose pull requests close the project's tickets, and resolves a fleet's loop handle with a tested lookup that leaves a spec with no loop id to its own loop. Its webhook setup, rotation, list and delete run `gh` through `route.py gh` with a clean environment, so no trace setting in the caller's shell can print the webhook address.
- `launch-fleet` 0.2.0: Plans cut for the shortest critical chain and the widest graph: the plan record's chain counts open outside blockers, `prefer.py` keeps the better of two cuts, and `lead_time.py` reports each spec's lead time from the collector. Fleets record four bounded self-grants and refuse model or effort changes, and start every ticket whose hard blockers merged and whose owned paths don't collide.
- `launch-fleet` 0.2.0: launch-fleet starts, wakes and stops builders through the host driver the project chooses in `docs/agents/host.md`, and keeps each run privately so a changed setting only moves later starts.
- `launch-fleet` 0.2.0: launch-fleet tries a refused driver start or wake twice more, then marks the ticket's fleet note `stopped (driver start failed)` and leaves one comment pointing to the owner-only driver log that keeps the driver's own words, cleared by the next success; set LAUNCH_FLEET_HARNESS, LAUNCH_FLEET_MODEL and LAUNCH_FLEET_SKILLS for that note, as without them only the note is skipped.
- `launch-fleet` 0.2.0: launch-fleet starts a builder only when a maintainer put `ready-for-agent` on the ticket and nobody edited it since; otherwise it raises one look saying a maintainer must add the label again.
- `launch-fleet` 0.2.0: `status.py run --note <id> -- <command>` keeps an agent's claim live while long work runs, and stops the work when the claim is lost; a heartbeat never reopens a done or stopped note.
- `launch-fleet` 0.2.0: launch-fleet's record poster counts a comment as its own only by the id the write returned; with no receipt it adopts no identical record, which another wake may have posted, and leaves the claim for reconciliation.
- `launch-fleet` 0.2.0: The wake's `needs-info` repair never removes a hold a person set. It takes off a label only under a GitHub App's own login, and only one its own write applied in the same wake. A label from an earlier wake, such as a put-back whose note edit failed, or any label while the agents post as a person's own account, stays and is reported.
- `launch-fleet` 0.2.0: A fleet wake's status step is one `status.py repair` call. It adds `needs-info` only while a note still asks, records the repair in its own fleet note until the label is settled (so a later wake finishes a repair an earlier one left part way), takes off only the application it made, puts back and reports a person's application it took, and reports a failed check as a failed check.
- `launch-fleet` 0.2.0: The status writer reads back after a claim edit: it steps down when another live note of its kind exists, and puts back a release a sibling wake wrote in between.
- `research` 0.2.0: Wayfind, research and triage are rewritten short, one job each; wayfind reads its frontier with a new `frontier.py` script.
- `setup` 0.2.0: Setup's settings check refuses a second Record authors row and a duplicate or malformed spawn flag in any builder, reviewer or Fixer table, naming the row or flag, as the review and launch readers already do.
- `to-spec` 0.2.0: A confirmed grill now runs to-spec and to-tickets straight through: the plan is approved by its own checks (a machine plan approval record), and to-spec makes one narrated steering video in build order.
- `to-spec` 0.2.0: The steering video's post says comment steering is off for now and tells the owner to steer through their orchestrator.
- `to-spec` 0.2.0: The steering video fails and names the moment when the voice command fails or a moment's take is silent or stale, and it now exports to an output on another filesystem.
- `to-tickets` 0.2.0: A confirmed grill now runs to-spec and to-tickets straight through: the plan is approved by its own checks (a machine plan approval record), and to-spec makes one narrated steering video in build order.
- `to-tickets` 0.2.0: Plans cut for the shortest critical chain and the widest graph: the plan record's chain counts open outside blockers, `prefer.py` keeps the better of two cuts, and `lead_time.py` reports each spec's lead time from the collector. Fleets record four bounded self-grants and refuse model or effort changes, and start every ticket whose hard blockers merged and whose owned paths don't collide.
- `to-tickets` 0.2.0: Machine plan approval counts a missing Relies on file as planned only when a direct blocker owns that file, or a folder containing it, in the dependent ticket's own repository; a file in the --root checkout counts only for tickets in that checkout's repository.
- `triage` 0.2.0: Wayfind, research and triage are rewritten short, one job each; wayfind reads its frontier with a new `frontier.py` script.
- `wayfind` 0.2.0: Wayfind, research and triage are rewritten short, one job each; wayfind reads its frontier with a new `frontier.py` script.
- `wayfind` 0.2.0: wayfind's frontier refuses an issue without the `wayfind:map` label and a Record authors row with extra columns; grill's helper tests pin its refusal of a changed or superseded same-ID request.
- `wayfind` 0.2.0: wayfind's frontier counts only record authors' claims and releases, never says `yours` for a blocked or kind-less question, and reads every comment and question page in order.

## 0.1.2 - 2026-11-18

- `install`: no longer chooses or activates an engine; after setup it checks CloudRoom, explains the product in a few lines and hands over to `onboard`, and every step reuses what an earlier one recorded.
- `launch-fleet`: `fleet.sh overload` can read the war room collector's queue at the time of each new-work call through an OpenWiz checkout's own supplier (`LAUNCH_FLEET_OVERLOAD_SUPPLY`), and refuses new work as unknown when that supplier fails; the limit-recovery notes name the war room's renamed files.
- `onboard`: starts from a fresh install with a new Connect step for the one chosen repository (GitHub sign-in, the user's own App or an explicit skip, the prepared project and its private brain), reuses the recorded harness, model and effort, and launches the first fleet as one launch-fleet fleet thread instead of the engine's tick.
- `setup`: the person may explicitly skip the App, so their verified personal GitHub login acts on the selected repository and the App stays missing.
- `contracts/cli.v1.md` (carried contract): records the removal of the terminal app and `ui`, the retirement of the executing `fleet tick`, `--expect-plan` and the `engine` commands, and the shipped `loop validate`, `loop export`, `loop plan` and `loop apply` reports.

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
