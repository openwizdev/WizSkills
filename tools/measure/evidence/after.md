# WS14 after measurements

The 0.2.0 candidate is measured against [WS1's baseline](README.md) with the
same harness and convention: [the counting convention](../README.md#comparable-static-loaded-path-count),
the [case stops](../cases.md#static-path-boundaries), `js-tiktoken@1.0.21` and
`o200k_base`. The candidate is WizSkills
`dc48e732b7c6f4405ffe66f1f171843595d2e194`. launch-fleet is counted again
once #1340 (WizSkills #60) merges.

- [Candidate path manifest](after-paths.json): the same case IDs and stops,
  with each candidate's required paths.
- [Static after counts](static-after.json): `static-count.cjs` output for that
  manifest.
- [After rows](after.csv): the baseline's columns at the candidate pin.

Reproduce the static counts as the harness README says, with the candidate
manifest in place of the baseline's:

```sh
node tools/measure/static-count.cjs tools/measure/evidence/after-paths.json "$tokenizer" > "$tokenizer_dir/after.json"
diff -u tools/measure/evidence/static-after.json "$tokenizer_dir/after.json"
```

## Pass or fail, per skill

A skill **passes** when its case loads fewer packaged tokens than the same
case at the baseline. to-spec and to-tickets are both compared with
plan-graph's `plan-graph.approval`. to-tickets runs that case's own input and
stop. `to-spec.chain` runs the confirmed grill through to-spec and on into
to-tickets, which is how to-spec now works.

| Skill | Case | Tokens before | Tokens after | Change | Result |
| --- | --- | ---: | ---: | ---: | --- |
| ask-wiz | `ask-wiz.route` | 7,588 | 2,097 | -72% | pass |
| build-ticket | `build-ticket.regression` | 53,161 | 26,984 | -49% | pass |
| diagnose | `diagnose.reproduce` | 2,220 | 1,277 | -42% | pass |
| grill | `grill.new` | 26,553 | 23,388 | -12% | pass |
| handoff | `handoff.resume` | 1,667 | 1,022 | -39% | pass |
| hill-climb | `hill-climb.select` | 6,432 | 2,979 | -54% | pass |
| huntr | `huntr.intake` | 7,246 | 3,179 | -56% | pass |
| image | `image.capture` | 2,684 | 1,779 | -34% | pass |
| install | `install.pinned` | 2,690 | 2,890 | +7% | **fail** |
| install (onboard merged) | `onboard.resume` | 90,611 | 44,692 | -51% | pass |
| launch-fleet | `launch-fleet.wake` | 43,331 | 24,497 | -43% | pass |
| research | `research.synthesis` | 2,785 | 1,469 | -47% | pass |
| review-ticket | `review-ticket.exact-head` | 22,300 | 13,932 | -38% | pass |
| setup | `setup.repair` | 14,940 | 13,668 | -9% | pass |
| to-spec | `to-spec.chain` | 38,193 | 18,267 | -52% | pass |
| to-tickets | `plan-graph.approval` | 38,193 | 16,456 | -57% | pass |
| triage | `triage.dispatch` | 15,643 | 13,736 | -12% | pass |
| wayfind | `wayfind.resume` | 29,913 | 24,956 | -17% | pass |
| where-are-we | `where-are-we.status` | 1,676 | 1,112 | -34% | pass |

install's own case fails. Its single entrypoint grew from 99 to 139 lines
when onboard merged into it, and `install.pinned` stops before the first
fleet, so the case pays for the merged steps without using them. The
onboard road that moved into install, `onboard.resume`, loads 51% less.

The removed skills have no after case. feedback (`feedback.preview`),
feedback-triage (`feedback-triage.sort`) and overnight (`overnight.gate`) left
the catalog, and plan-graph split into to-spec and to-tickets.

## In total

| Measure | Before | After | Change | Result |
| --- | ---: | ---: | ---: | --- |
| Skills in the catalog | 21 | 18 | -3 | pass (SK-A's 18) |
| Entrypoint lines, all skills | 4,740 | 1,591 | -66% | pass |
| Entrypoint words, all skills | 79,650 | 22,027 | -72% | pass |
| Packaged tokens, the 18 cases measured both times | 369,633 | 220,113 | -40% | pass |
| Skills whose case loads fewer tokens | | 17 of 18 | | install fails |

The 18 cases are the 17 skills' own cases plus `onboard.resume`, all
measured at both pins. `to-spec.chain` repeats plan-graph's baseline, so it
stays out of the sum. All 21 baseline cases total 391,168 tokens. The three
removed skills' cases account for the other 21,535.

## Lines and words, per skill (SK-B)

The spec's aim is 50 to 100 lines with no hard cap. Every skill longer than
100 lines gives its reason.

| Skill | Lines before | Lines after | Words before | Words after | Over 100 lines because |
| --- | ---: | ---: | ---: | ---: | --- |
| ask-wiz | 145 | 58 | 1,259 | 767 | |
| build-ticket | 377 | 72 | 6,777 | 1,596 | |
| diagnose | 185 | 103 | 1,625 | 885 | Wrapped at 80 columns: its longest line is 325 characters, against 887 in build-ticket |
| grill | 238 | 89 | 3,960 | 750 | |
| handoff | 99 | 59 | 1,289 | 707 | |
| hill-climb | 468 | 107 | 4,188 | 1,882 | Keeps the design run's taste-brief and judging rules in its steps |
| huntr | 103 | 131 | 3,703 | 1,228 | Wrapped at 80 columns: its words fell 67% while its lines grew |
| image | 213 | 77 | 1,780 | 1,176 | |
| install | 99 | 139 | 1,782 | 1,814 | Holds onboard's first fleet too: install and onboard had 240 lines before |
| launch-fleet | 720 | 130 | 18,244 | 2,787 | Its line and record tables, one row per kind, are 47 of its lines |
| research | 168 | 76 | 2,041 | 1,030 | |
| review-ticket | 476 | 98 | 7,757 | 1,995 | |
| setup | 93 | 74 | 1,954 | 1,053 | |
| to-spec | 580 (plan-graph) | 75 | 9,008 (plan-graph) | 586 | |
| to-tickets | 580 (plan-graph) | 76 | 9,008 (plan-graph) | 573 | |
| triage | 185 | 103 | 2,812 | 1,366 | Keeps its disposition table, one row per outcome |
| wayfind | 163 | 70 | 2,489 | 1,059 | |
| where-are-we | 58 | 54 | 1,177 | 773 | |

Removed: feedback (65 lines), feedback-triage (83), onboard (141), overnight
(81) and plan-graph (580, now to-spec and to-tickets).

## Workflow trials (SK-C)

WS1 observed four workflow outcomes at the baseline: `grill.new`,
`plan-graph.approval`, `build-ticket.regression` and
`review-ticket.exact-head`, all passing. Their after-trials at the candidate
pin have not run. Their outcomes and every host token field stay `unknown`
in [after.csv](after.csv) until sanitized receipts are recorded. The
other cases were never observed before and are not observed after either.
The static counts above are a separate measure of packaged context, not of
tokens a host delivered.

## Path rulings

The candidate manifest follows the same scope rules as the baseline's. These
choices settle where a rewrite moved or reworded a read:

1. build-ticket's case includes review-ticket's SKILL.md, because step 4 has
   the builder run review-ticket's step 2 checklist on its own diff. It also
   includes launch-fleet's SKILL.md, its `references/identity.md` and the
   identity contract for the hand-back push.
2. A contract that a skill cites only beside a command it fully spells out,
   such as the agent-status contract beside `status.py`, is background
   reading and adds nothing.
3. review-ticket and triage still tell the agent to follow the
   open-development contract, so it stays in both cases, as it was at the
   baseline.
4. `launch-fleet.wake` includes `references/builders.md` for the start line
   and `references/records.md` for private routing, which also requires the
   open-development contract. The review-watchdog reference applies only
   where the project names a watchdog, and the fixture names none.
5. `handoff.resume` reads the saved page. `page.md` is the template for a new
   page, so it adds nothing to a resume.
6. `onboard.resume` now runs install's first-fleet branch through setup,
   grill, to-spec and to-tickets, and stops at `first_fleet.py launch`'s
   preview. The preview needs no launch-fleet text.
7. `install.pinned` stops before setup. install's tool list names OpenWiz's
   installer contracts, and those belong to OpenWiz.
