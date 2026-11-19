---
name: diagnose
description: Diagnose a hard bug, unexplained test failure, flaky CI test or performance regression. Use for a stuck builder or the orchestrator's optional diagnosis inside its decision after a re-check leaves a blocker open.
version: 0.2.0
---

# Diagnose

**No theory without a loop.** First run one command that goes red on the
reported bug. Then minimise, rank hypotheses, test one prediction at a time,
and fix with a regression test. Skip a phase only with an explicit reason;
the red-loop gate cannot be skipped.

Read the project's `AGENTS.md` or `CLAUDE.md`, its `GLOSSARY.md` if present,
and the ADRs for the area. Keep the caller's role, owned paths, approval gates
and the 1 + 1 review limit: diagnosis grants no permission to edit elsewhere,
run against a live system, merge or start agents. For a builder's question,
use its ticket. The orchestrator's diagnosis is optional, inside a decision
that relays Jake's answer to a parked finding: it supplies a cause and
direction for that decision and never resets the 1 + 1 rule.

## Redact first

Replace every secret with `<REDACTED>` before showing commands, outputs or
artifacts, in chat, files or GitHub. Keep credentials in environment variables,
never literal command arguments. Quote only the diagnostic lines of captured
artifacts: auth headers can be secrets. Keep personal context, real identifiers
and live session content out wherever the project's privacy rules require it.
Public diagnosis comments also exclude thread ids, exact user words and links
into private files. Keep private captures in the configured private repository;
public findings use synthetic reproducers and technical facts. Record a user
decision in your own words, with its date and the open-development contract
private-record pointer, never a quotation.
If redaction removes the signal, say so and ask through the caller's channel;
do not expose the unredacted artifact.

## 1. Build a tight feedback loop

Spend disproportionate effort here. Reading code to construct a reproducer
is fine; explaining the cause before the red command exists is not.

Try these approaches in roughly this order, within the project's permissions:

1. A failing test at the seam that reaches the bug: unit, integration or end to end.
2. An HTTP script against a development server.
3. A CLI invocation on fixture input, compared with a known-good snapshot.
4. A headless browser script asserting the exact DOM, console or network symptom.
5. A captured trace replayed through the isolated code path, with privacy rules kept.
6. A throwaway harness: the smallest service and mocked dependencies that reach it.
7. A seeded property or fuzz loop for intermittently wrong output.
8. A bisection harness over known commits, datasets or versions, suitable for `git bisect run` in an isolated copy.
9. A differential loop: the same input on old/new versions or two configurations.
10. Last resort, a structured human-assisted loop using [the template](scripts/hitl-loop.template.sh).

For that last resort, supply a concrete step and a question about the exact
symptom. The human follows the step (including signing in themselves) and
reports only `y` or `n`; never capture credentials or raw error text. For example:

```sh
bash skills/diagnose/scripts/hitl-loop.template.sh 'Open the synthetic panel and export twice.' 'Did the count duplicate?'
```

The template prints `SYMPTOM_PRESENT=yes` and exits 1 for red, prints
`SYMPTOM_PRESENT=no` and exits 0 for green, and exits 2 for inconclusive input.
In a `git bisect run` wrapper, map exit 2 to 125 (skip), so an inconclusive answer never marks a commit bad.
An agent needs a terminal the human can answer; if none is available, ask,
never invent the answer. Copy or adapt the template to the scenario as needed.

Tighten the loop: cache setup and cut unrelated initialisation; assert the
specific symptom, not merely absence of a crash; pin time and random seeds,
isolate files and freeze network dependencies. Aim for seconds, not minutes.

**Flaky tests:** aim for a higher reproduction rate. Repeat the trigger,
parallelise isolated runs, stress it, narrow timing windows or inject delays
to expose the failure. Record the seed, stress/configuration and failures /
total attempts, both before and after amplification. Establish a stable enough,
high reproduction rate to debug; a lucky pass proves nothing. Set and state
the investigation effort before starting, using the ticket's budget if given.
Keep every outcome: never silently retry until CI is green. If the effort is
spent without a cause, report the measured rates and every approach tried as
unsolved, and ask for the next step.

**Gate:** show one command you have actually run, its redacted red output,
and the exact symptom it asserts. It must reach the actual bug path, be fast,
reproducible (or have a measured high reproduction rate for a flake), and be
agent-runnable, with a human only through the structured fallback above.
No red command, no hypotheses.

If you cannot build it, stop. Report what you tried and ask for the missing
reproducing environment, a redacted capture (HAR, log, core dump or timestamped
screen recording), or permission for temporary production instrumentation.
For ticket work, put the question on the ticket using the issue tracker and
needs-info procedure in `build-ticket`; otherwise ask the caller. Do not
instrument production or hypothesise while waiting.

## 2. Reproduce and minimise

Run the loop repeatedly. Confirm it catches the reported failure, not a nearby
one, and retain the exact error, wrong output or timing symptom. For flakes,
record the reproduction rate rather than claiming determinism.

Remove inputs, callers, configuration, data and steps one at a time, rerunning
after every cut. Keep the smallest scenario that still goes red. Done when
each remaining element is necessary: removing one loses the failure. Reproduce
and minimise before hypothesising; record any explicit phase exception.

## 3. Rank falsifiable hypotheses

Write 3–5 ranked hypotheses before testing any. Each must predict an observable
result: "If X causes this, changing Y will remove it; changing Z will worsen it."
Sharpen or discard any hypothesis without a falsifiable prediction.

Show the ranking before testing, on the ticket for ticket work or to the caller
otherwise, so their domain knowledge can correct it. Do not block on a reply;
proceed with the ranking if they are away.

## 4. Instrument one prediction at a time

Map each probe to one prediction. Change one variable, run the loop, record
the result, then update the ranking. Prefer debugger or REPL inspection,
then targeted boundary logs that distinguish the hypotheses. Never log
everything and search for a story afterwards.

Give every debug log a unique prefix such as `[DEBUG-a4f2]`, so cleanup can
find them all. For a performance regression, establish a measured baseline
with a timing harness, profiler or query plan, then bisect. Measure before
fixing; logs alone are not a performance measurement.

## 5. Fix with a regression test

Use a seam that exercises the real bug pattern at its call site. A shallow
single-caller test cannot prove a bug caused by multiple callers or a longer
chain. If there is no correct seam, record that architecture gap and ask on
the ticket (or through the caller's channel); do not call an untested fix done.

1. Turn the minimised reproducer into a regression test **before the fix**.
2. Run it red. If red required a code or fixture mutation, diff against a pristine copy to prove the intended mutation landed.
3. Apply the smallest fix for the cause the probes established.
4. Run the same test green.
5. Rerun the original, unminimised feedback loop. For a flake, report failures / attempts with the same trigger/configuration and budget; retries do not erase failures or establish a cure.

Follow the project's proof-first commits and full-test requirements before
handing back. Fixture tests prove fixture behavior, never live behavior.

## 6. Clean up and leave the diagnosis

Before declaring done, rerun the original loop and regression test, search
for the unique debug prefix and remove all temporary instrumentation. Delete
throwaway harnesses or move them to a clearly marked debug location. State
the established cause in the commit or pull request so the next debugger
can find it. Keep any missing regression seam explicit as an unresolved gap.

Leave a **diagnosis comment on the ticket or issue**, using the project's
issue-tracker instructions, with:

- The loop command, exact symptom and redacted red output.
- The established cause and the probe that distinguished it, or "unsolved".
- The regression test command and passing result, plus the original loop's result; any missing seam stays a gap.
- For a flake, the measured failures / total attempts, configurations and effort spent; if unsolved, what was tried and what is needed next. Never hide it with retries.

Credit: adapted from Matt Pocock's skills under the MIT License; the notice and sources are in [NOTICE.md](NOTICE.md).
