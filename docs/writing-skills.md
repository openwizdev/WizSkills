# Writing WizSkills

Write a short procedure an agent can repeat. State when to start, what to do,
and how to verify the result. Judge a revision by the context loaded for the
whole successful workflow, including dependencies, tool results and retries.
Keep the reproducible static count of required paths separate from tokens
observed by the host.

1. **Give each skill one coherent outcome.** Say what comes in, what comes out,
   and where the job ends. Split independently triggered work or roles with
   distinct authority. A coherent unit has a clear handoff and avoids loading a
   chain of tiny skills.
2. **Spend words on behavior that needs changing.** Keep unusual conventions
   and fixes for observed failures. Cut familiar advice, session history and
   hypothetical cases. Every line agents read should help them act or decide.
3. **Aim for 50–100 lines in the entrypoint.** Count the whole file, including
   metadata and notices, and report words or host tokens alongside lines.
   Explain longer files in review. An editing target helps authors spot excess
   while leaving room for essential behavior.
4. **Write a description that distinguishes the trigger.** Lead with the
   capability and the request that calls for it. Name a nearby boundary where
   confusion is likely, and put the steps in the body. Test a match and a
   near-miss because discovery can select the wrong skill or stop at the
   description.
5. **Make pointers conditional and actionable.** Name the file and the
   observable condition for reading it. Keep the common procedure inline and
   related rules together. Reading every reference up front spends context on
   branches the agent will never take.
6. **Give each step an observable end.** Name the artifact, verified state or
   user decision that completes it. Tighten vague end conditions before adding
   steps. A checkable end makes progress and handoff reproducible.
7. **Put exact mechanics in tested programs.** Reuse helpers for parsing,
   hashes, validation, state transitions and repeatable writes. State the
   command, inputs, short result, and how to recover from a refusal or uncertain
   outcome. Call through an interpreter if packaging drops executable bits.
   Tested programs give repeatable results and keep verbose mechanics out of
   the model's context.
8. **Keep one maintained source per rule.** Look up cheap facts in settings or
   tool help. Put project choices in project settings, use the skill for the
   reusable method, and retain the required notices in the package. A single
   authority prevents copies of a rule from drifting.
9. **Keep essential guards visible and enforced.** State privacy, approval,
   role separation and exact-record checks before their effects. A helper that
   owns enforcement must preserve the guard and its recovery behavior. These
   checks determine who may act, what may be disclosed and which evidence
   establishes success.
10. **Use a short positive procedure and one revealing example.** Use a defined
    term such as *frontier* for questions whose prerequisites are settled. Show
    a sample input or result where the shape would otherwise be a guess. Shared
    vocabulary and one precise example spare repeated explanation.
11. **Verify invocation and dependencies in each supported host.** Preserve
    the existing invocation policy unless it is deliberately changed. Verify
    referenced tools and skills, count any loaded dependency bodies, and
    provide a supported file-read path where direct invocation is unavailable.
    The workflow must still work where it is shipped.
12. **Design for restart, refusal and uncertainty.** Name the durable state,
    the next unfinished step and the stop condition. Read back uncertain
    effects before retrying, and carry forward verified decisions. A resumed
    session should neither repeat a write nor lose an approval.
13. **Judge behavior before removing a constraint.** Compare old and new
    workflows on realistic requests and intended models. Include a near-miss
    and a difficult branch. Check traces and observable results, automate
    deterministic helper checks, and repeat meaningful behavioral trials.
    Smaller text can hide a lost guard or a task that no longer completes.
14. **Keep human orientation outside the runtime payload.** Explain when,
    why and what success looks like in human docs. Route users with choices
    and links. Update docs, routes, manifests and callers together so browsing
    stays accurate without adding another copy of the runbook.
