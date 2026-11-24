# huntr attack mode

Read this only for an attack run: the `son-of-anton` skill (or the orchestrator)
starts one. One run is one heavy pass over the project's **own** targets: one
controller and many attackers. It files what it proves. It never edits code,
approves work or merges. Run scripts from the consuming repository root as
`node <installed-huntr>/scripts/<script>`. A refusal exits 2 with its reason.

Settings: the project's `docs/agents/huntr.md` sections `## Attack targets`
(`Target | Kind | Copy | Live rate | Files to`, with `Kind` as `surface` or
`infra`, `Live rate` a whole number `0` or more, and `Files to` as
`owner/repo`), `## Attack models` (controller and attacker rows) and its
`Attack record:` issue.

## Guards

- **Own targets only.** Before every probe, run `targets.mjs check <settings> <target>`.
  Exit 2 stops that probe. Never touch a third party, a service the project
  only depends on, or anyone else's factory.
- **Copies first, no floods.** Use a target's Copy whenever it has one. Go live
  only for what a copy can't show, under its Live rate (`0`: no live traffic).
  Never send denial-of-service, load or flood traffic.
- **Injection stays in copies.** Poisoned issues, pull requests and READMEs
  aimed at the project's agents go only into a throwaway repository or copy,
  never onto a live tracker.
- **Secrets stay put.** Prove a found secret is readable and stop. Never print,
  copy or use it. It goes the private route.
- **Roles.** The controller and attackers never edit, commit, push or approve.
  Builders fix, and the fleet's reviewers review.

## 1. Plan

1. `lease.mjs id` once, and save it as `<run>`. Run `targets.mjs list <settings>`;
   unreadable settings end the run as blocked (step 4).
2. Read the latest record on the attack record issue: findings, open fixes and
   their checks. Aim at what changed since (commits, deploys, new targets) and
   rerun every fixed hole's check. Skip a clean target and technique pair that
   hasn't changed.
3. Cross targets with techniques: headers and TLS, sign-in and sessions,
   input injection, secrets in repositories, builds and logs, the install line
   and release assets, token scope, sandbox reach, prompt injection against
   skills and agents, loops and their scripts, and gate attacks. One attacker
   per slice, with no artificial cap. Pin `origin/main` for each code target.
   A gate attack makes a deliberately bad change in a throwaway clone (a
   weakened test or assertion, a hidden skip, an edited check or its fixture,
   or a stub that only fakes the behaviour) and runs the project's own checks
   on it locally: the test suite, CI's check entrypoint, and the review and
   build helpers' checks. A check that stays green is a finding. The bad
   change is never pushed, and never opened as a pull request on a live
   repository.

**Done when** the matrix is written in resumable state.

## 2. Dispatch

For each slice, write `{"slice","target","technique","questions"}` to a file
and run `targets.mjs brief <settings> <slice.json> <pin>`. Start each attacker
through Cloudroom in its own sandbox with the Attack models attacker row. A
missing model is a blocked slice, never a substitute. End the turn. On each
wake, read reports with `hunters.mjs collect <pin> <slice>=<report>...` and
archive those attackers.

## 3. Prove, route, file

1. Rerun each lead yourself, minimal and against the copy where possible. An
   unproven lead stays a note in the record.
2. Write the finding as JSON: `target`, `technique`, `severity`
   (`low|medium|high|critical`), `live_users`, `secrets`, `person_data`,
   `money`, `machine_level`, `summary`, `proof_command`, `steps`.
3. Search the tracker for a duplicate first. Then run `findings.mjs route <finding.json>`
   (prints `{"channel": "public|advisory|private", "fix": "builder-now|triage"}`):
   - `public`: `findings.mjs issue <finding.json> > body.md`, then file it on
     the target's Files to repository with `needs-triage`, and read it back;
   - `advisory`: a draft GitHub private security advisory on that repository
     (`gh api -X POST repos/<owner>/<repo>/security-advisories`), with the steps;
   - `private`: an issue on the private records repository, with the steps.
4. `fix: builder-now` (critical): start one builder at once with the fleet's
   builder row, briefed to fix it and add the failing-first check, and tell
   the orchestrator. `fix: triage`: leave it `needs-triage`.

## 4. Record and finish

Post one record on the attack record issue: `<run>`, pins, every slice as
reported or blocked, findings by channel (public links, private counts only),
then `disproved: <n>`: the findings that disprove a merged claim (a spec Proof
line, a changelog line, a test's name or a doc saying the code does what it
doesn't), counted like fixes and filed like any other finding. Then gaps and
next focus. Archive every attacker, then
`room-cli thread archive --self`.

## Every fixed hole leaves a check

Each finding's acceptance criteria include a check or test that fails before
the fix. Its reviewer requests changes without one. The next run reruns those
checks first.
