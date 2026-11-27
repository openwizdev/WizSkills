# Review rounds: the AFTER bench

This is the AFTER bench of spec openwizdev/OpenWiz#2484, ticket openwizdev/OpenWiz#2502 (RR4). It runs `bench.py` (openwizdev/WizSkills#293) over the PRs opened after both fixes merged, using the definitions in [README.md](README.md). The BEFORE numbers beside it come from the same tool. Every read is a read-only GraphQL query through `gh api graphql`.

## Window and cohort

- **Cutoff:** 2026-11-23T01:00:10Z, the later of the two fix merges. RR1 (openwizdev/WizSkills#291) merged at 2026-11-23T01:00:10Z and RR2 (openwizdev/WizSkills#297) at 2026-11-22T23:54:21Z.
- **Cohort:** PRs created after the cutoff (`--opened-after`) and merged in the window, in openwizdev/OpenWiz, WizSkills, WizSite, WizRoom and WizMarket, the BEFORE repositories. The headline is the ticket PRs among them.
- **Window:** merged from the cutoff until 60 cohort ticket PRs had merged or 7 days had passed, whichever came first. The 60th merged at 2026-11-24T06:13:14Z (openwizdev/WizSkills#315), before the 7-day end at 2026-11-30T01:00:10Z. So the window is 2026-11-23T01:00:10Z to 2026-11-24T06:13:14Z, both ends included.
- **Finding the 60th:** the PRs were listed with `bench.py`'s own `fetch` and `record` over the five repositories, merged from the cutoff and created after it. The ticket PRs, as `record` marks them, were then sorted by merge time. The 59th is openwizdev/OpenWiz#2926 (06:11:15Z) and the 61st is openwizdev/WizMarket#10 (06:14:54Z). No other ticket PR merged in the same second as the 60th. The AFTER run confirms the count: its ticket PR `All` row has 60 merged.

## Commands

AFTER, run at 2026-11-27T13:56:06Z with `bench.py` as on main at `de29154e`. It exited 0 and printed nothing on stderr:

```sh
python3 -I tools/review-rounds/bench.py \
  --repo openwizdev/OpenWiz --repo openwizdev/WizSkills --repo openwizdev/WizSite \
  --repo openwizdev/WizRoom --repo openwizdev/WizMarket \
  --merged-from 2026-11-23T01:00:10Z --merged-to 2026-11-24T06:13:14Z \
  --opened-after 2026-11-23T01:00:10Z
```

BEFORE, the same tool over the BEFORE window, run at 2026-11-27T13:50:38Z. It also exited 0 with nothing on stderr:

```sh
python3 -I tools/review-rounds/bench.py \
  --repo openwizdev/OpenWiz --repo openwizdev/WizSkills --repo openwizdev/WizSite \
  --repo openwizdev/WizRoom --repo openwizdev/WizMarket \
  --merged-from 2026-11-15T23:00Z --merged-to 2026-11-22T22:58Z
```

Neither run passes `--clone`, so the late-finding split and the diff-size table read unknown. Neither is in the spec's table. The diff-line bands use GitHub's additions and deletions, so they need no clone. Comments edited since a run can shift a count slightly.

## BEFORE beside AFTER

BEFORE is the rerun above. Its ticket PR row matches the lead's corrected baseline on spec #2484 exactly: 154 ticket PRs, 2.41 rounds, 0.99 `CHANGES`, 38% APPROVE at first and 33% with 3+ rounds. Its all-PR rows match the spec's BEFORE table within ±1 PR per cell. WizSkills now has 134 merged and 131 reviewed, against 133 and 130 then.

**Ticket PRs** (P4's measure)

| Ticket PRs | Merged | Reviewed | Rounds mean | Median | p90 | Max | `CHANGES` mean | APPROVE at first | 3+ rounds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BEFORE | 154 | 154 | 2.41 | 2 | 4 | 12 | 0.99 | 58 (38%) | 51 (33%) |
| AFTER | 60 | 48 | 1.79 | 1 | 3 | 5 | 0.75 | 26 (54%) | 12 (25%) |
| P4 target | | | 1.5 or lower | | | | | 60% or higher | |

**All PRs** (the spec's BEFORE table), BEFORE → AFTER

| Repository | Merged | Reviewed | Rounds mean | Median | p90 | Max | APPROVE at first | 3+ rounds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| OpenWiz | 284 → 26 | 275 → 19 | 1.79 → 1.74 | 2 → 1 | 3 → 3 | 12 → 5 | 167 (61%) → 12 (63%) | 40 (15%) → 5 (26%) |
| WizSkills | 134 → 40 | 131 → 40 | 2.11 → 1.65 | 2 → 1 | 3 → 3 | 5 → 4 | 57 (44%) → 22 (55%) | 42 (32%) → 6 (15%) |
| WizSite | 58 → 11 | 44 → 6 | 2.14 → 2 | 2 → 2 | 4 → 3 | 5 → 3 | 19 (43%) → 2 (33%) | 11 (25%) → 1 (17%) |
| WizRoom | 24 → 0 | 24 → 0 | 1.88 → - | 2 → - | 3 → - | 4 → - | 13 (54%) → - | 4 (17%) → - |
| WizMarket | 0 → 6 | 0 → 0 | - → - | - → - | - → - | - → - | - → - | - → - |
| **All** | **500 → 83** | **474 → 65** | **1.91 → 1.71** | **2 → 1** | **3 → 3** | **12 → 5** | **256 (54%) → 36 (55%)** | **97 (20%) → 12 (18%)** |

Distribution (all reviewed PRs) of 1, 2, 3, 4, and 5 or more rounds: BEFORE 200, 177, 61, 21, 15; AFTER 35, 18, 9, 2, 1. Verdicts went from 906 to 111, `CHANGES` from 309 to 45, and re-approvals from 126 to 7.

**Blocking findings**

| Cohort | First-review blockers (Spec/Sweep/Standards) | Per reviewed PR | Re-checks with a new blocker |
| --- | --- | --- | --- |
| All PRs, BEFORE | 480 (310/136/34) | 1.01 | 73 of 432 (17%) |
| All PRs, AFTER | 73 (53/19/1) | 1.12 | 7 of 46 (15%) |
| Ticket PRs, BEFORE | 239 (156/65/18) | 1.55 | 52 of 217 (24%) |
| Ticket PRs, AFTER | 63 (44/18/1) | 1.31 | 7 of 38 (18%) |

**Ticket PRs by diff lines**, BEFORE → AFTER

| Diff lines | Merged | Reviewed | Rounds mean | `CHANGES` mean | APPROVE at first | 3+ rounds |
| --- | --- | --- | --- | --- | --- | --- |
| under 300 | 54 → 39 | 54 → 31 | 1.80 → 1.32 | 0.57 → 0.29 | 26 (48%) → 24 (77%) | 6 (11%) → 2 (6%) |
| 300-599 | 27 → 9 | 27 → 7 | 2.15 → 2.43 | 0.93 → 1.14 | 9 (33%) → 2 (29%) | 8 (30%) → 3 (43%) |
| 600-999 | 23 → 7 | 23 → 7 | 2.57 → 2.71 | 1.30 → 1.86 | 5 (22%) → 0 (0%) | 9 (39%) → 4 (57%) |
| 1000+ | 50 → 5 | 50 → 3 | 3.14 → 3 | 1.34 → 2 | 18 (36%) → 0 (0%) | 28 (56%) → 3 (100%) |

Median ticket diff by size: S 302 → 160.50 lines (n 92 → 50), M 1185.50 → 671 (n 52 → 7), L 3174 → 206 (n 9 → 2).

## P4: not met

Mean rounds per ticket PR fell from 2.41 to 1.79, and APPROVE at first rose from 38% to 54%. Both moved the right way, but P4's targets were 1.5 or lower and 60% or higher, so P4 is not met.

## Confounders

1. **Relayed reviews the bench doesn't count.** 9 of the 60 AFTER ticket PRs were reviewed only through 15 verdicts that the lead relayed from a reviewer of another model family. They are openwizdev/OpenWiz#2718, #2751 and #2889, openwizdev/WizSite#149, and openwizdev/WizMarket#4, #6, #7, #8 and #9. Each of these comments opens with a relay line, such as `**Review verdict, posted by the lead.**` or `_Review by ..., relayed by the spec's lead._`, and its `VERDICT:` line comes further down. A round is a comment that starts `VERDICT:`, so these PRs count as merged but not reviewed. No BEFORE ticket PR had such a comment. If each relayed comment counted as a round, the AFTER ticket PRs would be 57 reviewed, 1.77 rounds mean, 30 (53%) APPROVE at first and 12 (21%) with 3+ rounds. That recount is outside `bench.py`, and it doesn't change P4's verdict.
2. **A change in who reviews.** Those 9 PRs had a reviewer from another model family, relayed by hand. In BEFORE, one reviewer posted its own `VERDICT:` comments.
3. **Merged with no verdict.** 3 more AFTER ticket PRs have no verdict comment at all: openwizdev/OpenWiz#2750, #2757 and #2926. OpenWiz#2926 says it was merged into #2699 instead. OpenWiz#2750 answers findings from a review that isn't posted on it. Every BEFORE ticket PR had a verdict.
4. **A short, early window with a different mix.** The 60th merge came 29 hours after the cutoff. 58 of the 60 ticket PRs were opened within 11 hours of it, so for many the building may have begun before the fixes merged. The AFTER mix is smaller and more WizSkills. 39 of the 60 ticket PRs are under 300 lines (BEFORE 54 of 154), and the median `S` diff is 160.5 lines (BEFORE 302). 34 of the 48 reviewed are WizSkills PRs (BEFORE 60 of 154), and WizRoom has none. Within the bands only under 300 improved. The other bands did not, on 7, 7 and 3 reviewed PRs.
5. **The cohort to date reads better.** The AFTER command with `--merged-to 2026-11-27T14:00:00Z`, run at 2026-11-27T13:57:23Z, prints this ticket PR row:

   | Cohort | Merged | Reviewed | Rounds mean | Median | p90 | Max | CHANGES mean | APPROVE at first | 3+ rounds | First-review blockers (Spec/Sweep/Standards) | Re-checks with a new blocker | Re-check blockers (Spec/Sweep/Standards) |
   | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
   | All | 154 | 137 | 1.63 | 1 | 3 | 5 | 0.54 | 85 (62%) | 20 (15%) | 136 (101/34/1) | 10 of 86 | 15 (6/8/1) |

   That run doesn't use the ticket's window, which ends at the 60th merge, and it leaves out cohort PRs that are still open. It suggests the first 60 merges understate the change. Its mean is still above 1.5, so P4 is not met on that reading either.
6. **The size limit binds newer specs only.** approve.py's size check applies to specs created on or after 2026-11-23T00:00:00Z (`SIZES_SINCE`). The AFTER cohort still has 2 `L` tickets, so part of it was planned before the limit.
7. **The self-check is in force.** 45 of the 48 reviewed AFTER ticket PRs have a `## Self-check` section in their description, as read on 2026-11-27. In BEFORE, 3 of the 267 reviewed PRs opened since 2026-11-19 mentioned it. This count comes from the PR descriptions, not from `bench.py`, and a description can change after its review.

## AFTER output

The AFTER command's output, verbatim. The JSON block that follows the tables is folded.

Window: merged 2026-11-23T01:00:10Z to 2026-11-24T06:13:14Z, opened after 2026-11-23T01:00:10Z.

**All PRs**

| Cohort | Merged | Reviewed | Rounds mean | Median | p90 | Max | CHANGES mean | APPROVE at first | 3+ rounds | First-review blockers (Spec/Sweep/Standards) | Re-checks with a new blocker | Re-check blockers (Spec/Sweep/Standards) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| openwizdev/OpenWiz | 26 | 19 | 1.74 | 1 | 3 | 5 | 0.58 | 12 (63%) | 5 (26%) | 7 (6/1/0) | 3 of 14 | 4 (0/3/1) |
| openwizdev/WizSkills | 40 | 40 | 1.65 | 1 | 3 | 4 | 0.72 | 22 (55%) | 6 (15%) | 56 (39/16/1) | 3 of 26 | 3 (1/2/0) |
| openwizdev/WizSite | 11 | 6 | 2 | 2 | 3 | 3 | 0.83 | 2 (33%) | 1 (17%) | 10 (8/2/0) | 1 of 6 | 1 (1/0/0) |
| openwizdev/WizRoom | 0 | 0 | - | - | - | - | - | - | - | 0 (0/0/0) | 0 of 0 | 0 (0/0/0) |
| openwizdev/WizMarket | 6 | 0 | - | - | - | - | - | - | - | 0 (0/0/0) | 0 of 0 | 0 (0/0/0) |
| All | 83 | 65 | 1.71 | 1 | 3 | 5 | 0.69 | 36 (55%) | 12 (18%) | 73 (53/19/1) | 7 of 46 | 8 (2/5/1) |

**Ticket PRs** (a closing issue has `Size: S.`, `M.` or `L.`)

| Cohort | Merged | Reviewed | Rounds mean | Median | p90 | Max | CHANGES mean | APPROVE at first | 3+ rounds | First-review blockers (Spec/Sweep/Standards) | Re-checks with a new blocker | Re-check blockers (Spec/Sweep/Standards) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| openwizdev/OpenWiz | 17 | 11 | 2.09 | 1 | 3 | 5 | 0.82 | 6 (55%) | 5 (45%) | 6 (5/1/0) | 3 of 12 | 4 (0/3/1) |
| openwizdev/WizSkills | 34 | 34 | 1.68 | 1 | 3 | 4 | 0.74 | 19 (56%) | 6 (18%) | 53 (36/16/1) | 3 of 23 | 3 (1/2/0) |
| openwizdev/WizSite | 4 | 3 | 2 | 2 | 3 | 3 | 0.67 | 1 (33%) | 1 (33%) | 4 (3/1/0) | 1 of 3 | 1 (1/0/0) |
| openwizdev/WizRoom | 0 | 0 | - | - | - | - | - | - | - | 0 (0/0/0) | 0 of 0 | 0 (0/0/0) |
| openwizdev/WizMarket | 5 | 0 | - | - | - | - | - | - | - | 0 (0/0/0) | 0 of 0 | 0 (0/0/0) |
| All | 60 | 48 | 1.79 | 1 | 3 | 5 | 0.75 | 26 (54%) | 12 (25%) | 63 (44/18/1) | 7 of 38 | 8 (2/5/1) |

**Ticket PRs by diff lines**

| Cohort | Merged | Reviewed | Rounds mean | Median | p90 | Max | CHANGES mean | APPROVE at first | 3+ rounds | First-review blockers (Spec/Sweep/Standards) | Re-checks with a new blocker | Re-check blockers (Spec/Sweep/Standards) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| under 300 | 39 | 31 | 1.32 | 1 | 2 | 4 | 0.29 | 24 (77%) | 2 (6%) | 14 (11/3/0) | 0 of 10 | 0 (0/0/0) |
| 300-599 | 9 | 7 | 2.43 | 2 | 5 | 5 | 1.14 | 2 (29%) | 3 (43%) | 12 (9/3/0) | 2 of 10 | 2 (0/2/0) |
| 600+ | 12 | 10 | 2.80 | 3 | 3 | 4 | 1.90 | 0 (0%) | 7 (70%) | 37 (24/12/1) | 5 of 18 | 6 (2/3/1) |
| 600-999 | 7 | 7 | 2.71 | 3 | 4 | 4 | 1.86 | 0 (0%) | 4 (57%) | 32 (21/10/1) | 4 of 12 | 4 (2/2/0) |
| 1000+ | 5 | 3 | 3 | 3 | 3 | 3 | 2 | 0 (0%) | 3 (100%) | 5 (3/2/0) | 1 of 6 | 2 (0/1/1) |

Median ticket diff by size: S 160.50 (n 50), M 671 (n 7), L 206 (n 2).

Distribution (all reviewed PRs): 1 round 35, 2 rounds 18, 3 rounds 9, 4 rounds 2, 5 or more 1. Verdicts 111, `CHANGES` 45, re-approvals 7.

**Worst PRs**

| PR | Rounds (`CHANGES`) | Size | Diff lines | Files |
| --- | --- | --- | --- | --- |
| WizSkills#309 | 4 (3) | S | 609 | 5 |
| WizSkills#338 | 4 (3) | S | 214 | 4 |
| OpenWiz#2732 | 3 (3) | S | 1103 | 5 |
| WizSkills#323 | 3 (3) | M | 698 | 4 |
| WizSkills#336 | 3 (3) | S | 682 | 5 |
| OpenWiz#2701 | 5 (2) | S | 483 | 12 |
| OpenWiz#2709 | 3 (2) | S | 476 | 6 |
| WizSkills#337 | 3 (2) | S | 1272 | 9 |
| WizSite#161 | 2 (2) | none | 405 | 11 |
| WizSkills#313 | 2 (2) | none | 541 | 9 |

**Late findings** (findings first seen at round 2 or later, graded blocking or pre-existing, by whether the fix changed their line since the first review)

| Cohort | Merged | Reviewed | Rounds mean | Blocking findings | First-review blockers and late findings | First seen at round 2+ | Graded pre-existing | Changed by the fix | Unchanged since the first review | Unknown |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| openwizdev/OpenWiz | 26 | 19 | 1.74 | 11 | 11 | 4 (36%) | 0 | 0 (0%) | 0 (0%) | 4 (100%) |
| openwizdev/WizSkills | 40 | 40 | 1.65 | 59 | 59 | 3 (5%) | 0 | 0 (0%) | 0 (0%) | 3 (100%) |
| openwizdev/WizSite | 11 | 6 | 2 | 11 | 11 | 1 (9%) | 0 | 0 (0%) | 0 (0%) | 1 (100%) |
| openwizdev/WizRoom | 0 | 0 | - | 0 | 0 | - | 0 | - | - | - |
| openwizdev/WizMarket | 6 | 0 | - | 0 | 0 | - | 0 | - | - | - |
| All | 83 | 65 | 1.71 | 81 | 81 | 8 (10%) | 0 | 0 (0%) | 0 (0%) | 8 (100%) |
| Ticket PRs | 60 | 48 | 1.79 | 71 | 71 | 8 (11%) | 0 | 0 (0%) | 0 (0%) | 8 (100%) |

**Withdrawn or ignored** (blockers withdrawn, and polish issues still open or closed as not planned 7 days after their PR merged)

| Cohort | Merged | Reviewed | Rounds mean | Blocking findings | Withdrawn | Polish issues | Not yet due | Unknown | Ignored when due | Withdrawn or ignored |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| openwizdev/OpenWiz | 26 | 19 | 1.74 | 11 | 0 (0%) | 2 | 2 | 0 | not yet due | not yet due (withdrawn alone 0%) |
| openwizdev/WizSkills | 40 | 40 | 1.65 | 59 | 2 (3%) | 13 | 13 | 0 | not yet due | not yet due (withdrawn alone 3%) |
| openwizdev/WizSite | 11 | 6 | 2 | 11 | 0 (0%) | 2 | 2 | 0 | not yet due | not yet due (withdrawn alone 0%) |
| openwizdev/WizRoom | 0 | 0 | - | 0 | - | 0 | 0 | 0 | - | - |
| openwizdev/WizMarket | 6 | 0 | - | 0 | - | 0 | 0 | 0 | - | - |
| All | 83 | 65 | 1.71 | 81 | 2 (2%) | 17 | 17 | 0 | not yet due | not yet due (withdrawn alone 2%) |
| Ticket PRs | 60 | 48 | 1.79 | 71 | 2 (3%) | 16 | 16 | 0 | not yet due | not yet due (withdrawn alone 3%) |

**Diff size against rounds** (reviewed PRs, from local git; tests counted apart; ticket PRs in the diff-line bands)

| Cohort | Merged | Reviewed | Rounds mean | Sized | Median code lines | Median test lines | Median code files | Median test files | Unknown |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| openwizdev/OpenWiz | 26 | 19 | 1.74 | 0 | - | - | - | - | 19 |
| openwizdev/WizSkills | 40 | 40 | 1.65 | 0 | - | - | - | - | 40 |
| openwizdev/WizSite | 11 | 6 | 2 | 0 | - | - | - | - | 6 |
| openwizdev/WizRoom | 0 | 0 | - | 0 | - | - | - | - | 0 |
| openwizdev/WizMarket | 6 | 0 | - | 0 | - | - | - | - | 0 |
| All | 83 | 65 | 1.71 | 0 | - | - | - | - | 65 |
| under 300 | 39 | 31 | 1.32 | 0 | - | - | - | - | 31 |
| 300-599 | 9 | 7 | 2.43 | 0 | - | - | - | - | 7 |
| 600+ | 12 | 10 | 2.80 | 0 | - | - | - | - | 10 |
| 600-999 | 7 | 7 | 2.71 | 0 | - | - | - | - | 7 |
| 1000+ | 5 | 3 | 3 | 0 | - | - | - | - | 3 |

<details><summary>JSON</summary>

```json
{
  "all": {
    "All": {
      "approve_first": {
        "count": 36,
        "pct": 55
      },
      "changes": {
        "mean": 0.69,
        "total": 45
      },
      "distribution": {
        "1": 35,
        "2": 18,
        "3": 9,
        "4": 2,
        "5+": 1
      },
      "findings": {
        "first": {
          "Spec": 53,
          "Standards": 1,
          "Sweep": 19,
          "total": 73
        },
        "rechecks": {
          "Spec": 2,
          "Standards": 1,
          "Sweep": 5,
          "count": 46,
          "total": 8,
          "with_new_blocker": 7
        }
      },
      "late": {
        "blocking": 81,
        "changed": 0,
        "findings": 81,
        "late": 8,
        "pct": 10,
        "pre_existing": 0,
        "unchanged": 0,
        "unknown": 8
      },
      "merged": 83,
      "reapprovals": 7,
      "reviewed": 65,
      "rounds": {
        "max": 5,
        "mean": 1.71,
        "median": 1,
        "p90": 3
      },
      "size": {
        "code_files": null,
        "code_lines": null,
        "sized": 0,
        "test_files": null,
        "test_lines": null,
        "unknown": 65
      },
      "three_plus": {
        "count": 12,
        "pct": 18
      },
      "verdicts": 111,
      "withdrawn_ignored": {
        "blocking": 81,
        "due": 0,
        "either_pct": null,
        "ignored": 0,
        "ignored_pct": null,
        "not_due": 17,
        "pending": "not yet due",
        "polish": 17,
        "unknown": 0,
        "withdrawn": 2,
        "withdrawn_pct": 2
      }
    },
    "openwizdev/OpenWiz": {
      "approve_first": {
        "count": 12,
        "pct": 63
      },
      "changes": {
        "mean": 0.58,
        "total": 11
      },
      "distribution": {
        "1": 12,
        "2": 2,
        "3": 4,
        "4": 0,
        "5+": 1
      },
      "findings": {
        "first": {
          "Spec": 6,
          "Standards": 0,
          "Sweep": 1,
          "total": 7
        },
        "rechecks": {
          "Spec": 0,
          "Standards": 1,
          "Sweep": 3,
          "count": 14,
          "total": 4,
          "with_new_blocker": 3
        }
      },
      "late": {
        "blocking": 11,
        "changed": 0,
        "findings": 11,
        "late": 4,
        "pct": 36,
        "pre_existing": 0,
        "unchanged": 0,
        "unknown": 4
      },
      "merged": 26,
      "reapprovals": 4,
      "reviewed": 19,
      "rounds": {
        "max": 5,
        "mean": 1.74,
        "median": 1,
        "p90": 3
      },
      "size": {
        "code_files": null,
        "code_lines": null,
        "sized": 0,
        "test_files": null,
        "test_lines": null,
        "unknown": 19
      },
      "three_plus": {
        "count": 5,
        "pct": 26
      },
      "verdicts": 33,
      "withdrawn_ignored": {
        "blocking": 11,
        "due": 0,
        "either_pct": null,
        "ignored": 0,
        "ignored_pct": null,
        "not_due": 2,
        "pending": "not yet due",
        "polish": 2,
        "unknown": 0,
        "withdrawn": 0,
        "withdrawn_pct": 0
      }
    },
    "openwizdev/WizMarket": {
      "approve_first": {
        "count": 0,
        "pct": null
      },
      "changes": {
        "mean": null,
        "total": 0
      },
      "distribution": {
        "1": 0,
        "2": 0,
        "3": 0,
        "4": 0,
        "5+": 0
      },
      "findings": {
        "first": {
          "Spec": 0,
          "Standards": 0,
          "Sweep": 0,
          "total": 0
        },
        "rechecks": {
          "Spec": 0,
          "Standards": 0,
          "Sweep": 0,
          "count": 0,
          "total": 0,
          "with_new_blocker": 0
        }
      },
      "late": {
        "blocking": 0,
        "changed": 0,
        "findings": 0,
        "late": 0,
        "pct": null,
        "pre_existing": 0,
        "unchanged": 0,
        "unknown": 0
      },
      "merged": 6,
      "reapprovals": 0,
      "reviewed": 0,
      "rounds": {
        "max": null,
        "mean": null,
        "median": null,
        "p90": null
      },
      "size": {
        "code_files": null,
        "code_lines": null,
        "sized": 0,
        "test_files": null,
        "test_lines": null,
        "unknown": 0
      },
      "three_plus": {
        "count": 0,
        "pct": null
      },
      "verdicts": 0,
      "withdrawn_ignored": {
        "blocking": 0,
        "due": 0,
        "either_pct": null,
        "ignored": 0,
        "ignored_pct": null,
        "not_due": 0,
        "pending": null,
        "polish": 0,
        "unknown": 0,
        "withdrawn": 0,
        "withdrawn_pct": null
      }
    },
    "openwizdev/WizRoom": {
      "approve_first": {
        "count": 0,
        "pct": null
      },
      "changes": {
        "mean": null,
        "total": 0
      },
      "distribution": {
        "1": 0,
        "2": 0,
        "3": 0,
        "4": 0,
        "5+": 0
      },
      "findings": {
        "first": {
          "Spec": 0,
          "Standards": 0,
          "Sweep": 0,
          "total": 0
        },
        "rechecks": {
          "Spec": 0,
          "Standards": 0,
          "Sweep": 0,
          "count": 0,
          "total": 0,
          "with_new_blocker": 0
        }
      },
      "late": {
        "blocking": 0,
        "changed": 0,
        "findings": 0,
        "late": 0,
        "pct": null,
        "pre_existing": 0,
        "unchanged": 0,
        "unknown": 0
      },
      "merged": 0,
      "reapprovals": 0,
      "reviewed": 0,
      "rounds": {
        "max": null,
        "mean": null,
        "median": null,
        "p90": null
      },
      "size": {
        "code_files": null,
        "code_lines": null,
        "sized": 0,
        "test_files": null,
        "test_lines": null,
        "unknown": 0
      },
      "three_plus": {
        "count": 0,
        "pct": null
      },
      "verdicts": 0,
      "withdrawn_ignored": {
        "blocking": 0,
        "due": 0,
        "either_pct": null,
        "ignored": 0,
        "ignored_pct": null,
        "not_due": 0,
        "pending": null,
        "polish": 0,
        "unknown": 0,
        "withdrawn": 0,
        "withdrawn_pct": null
      }
    },
    "openwizdev/WizSite": {
      "approve_first": {
        "count": 2,
        "pct": 33
      },
      "changes": {
        "mean": 0.83,
        "total": 5
      },
      "distribution": {
        "1": 1,
        "2": 4,
        "3": 1,
        "4": 0,
        "5+": 0
      },
      "findings": {
        "first": {
          "Spec": 8,
          "Standards": 0,
          "Sweep": 2,
          "total": 10
        },
        "rechecks": {
          "Spec": 1,
          "Standards": 0,
          "Sweep": 0,
          "count": 6,
          "total": 1,
          "with_new_blocker": 1
        }
      },
      "late": {
        "blocking": 11,
        "changed": 0,
        "findings": 11,
        "late": 1,
        "pct": 9,
        "pre_existing": 0,
        "unchanged": 0,
        "unknown": 1
      },
      "merged": 11,
      "reapprovals": 2,
      "reviewed": 6,
      "rounds": {
        "max": 3,
        "mean": 2.0,
        "median": 2.0,
        "p90": 3
      },
      "size": {
        "code_files": null,
        "code_lines": null,
        "sized": 0,
        "test_files": null,
        "test_lines": null,
        "unknown": 6
      },
      "three_plus": {
        "count": 1,
        "pct": 17
      },
      "verdicts": 12,
      "withdrawn_ignored": {
        "blocking": 11,
        "due": 0,
        "either_pct": null,
        "ignored": 0,
        "ignored_pct": null,
        "not_due": 2,
        "pending": "not yet due",
        "polish": 2,
        "unknown": 0,
        "withdrawn": 0,
        "withdrawn_pct": 0
      }
    },
    "openwizdev/WizSkills": {
      "approve_first": {
        "count": 22,
        "pct": 55
      },
      "changes": {
        "mean": 0.72,
        "total": 29
      },
      "distribution": {
        "1": 22,
        "2": 12,
        "3": 4,
        "4": 2,
        "5+": 0
      },
      "findings": {
        "first": {
          "Spec": 39,
          "Standards": 1,
          "Sweep": 16,
          "total": 56
        },
        "rechecks": {
          "Spec": 1,
          "Standards": 0,
          "Sweep": 2,
          "count": 26,
          "total": 3,
          "with_new_blocker": 3
        }
      },
      "late": {
        "blocking": 59,
        "changed": 0,
        "findings": 59,
        "late": 3,
        "pct": 5,
        "pre_existing": 0,
        "unchanged": 0,
        "unknown": 3
      },
      "merged": 40,
      "reapprovals": 1,
      "reviewed": 40,
      "rounds": {
        "max": 4,
        "mean": 1.65,
        "median": 1.0,
        "p90": 3
      },
      "size": {
        "code_files": null,
        "code_lines": null,
        "sized": 0,
        "test_files": null,
        "test_lines": null,
        "unknown": 40
      },
      "three_plus": {
        "count": 6,
        "pct": 15
      },
      "verdicts": 66,
      "withdrawn_ignored": {
        "blocking": 59,
        "due": 0,
        "either_pct": null,
        "ignored": 0,
        "ignored_pct": null,
        "not_due": 13,
        "pending": "not yet due",
        "polish": 13,
        "unknown": 0,
        "withdrawn": 2,
        "withdrawn_pct": 3
      }
    }
  },
  "ticket_bands": {
    "1000+": {
      "approve_first": {
        "count": 0,
        "pct": 0
      },
      "changes": {
        "mean": 2.0,
        "total": 6
      },
      "distribution": {
        "1": 0,
        "2": 0,
        "3": 3,
        "4": 0,
        "5+": 0
      },
      "findings": {
        "first": {
          "Spec": 3,
          "Standards": 0,
          "Sweep": 2,
          "total": 5
        },
        "rechecks": {
          "Spec": 0,
          "Standards": 1,
          "Sweep": 1,
          "count": 6,
          "total": 2,
          "with_new_blocker": 1
        }
      },
      "late": {
        "blocking": 7,
        "changed": 0,
        "findings": 7,
        "late": 2,
        "pct": 29,
        "pre_existing": 0,
        "unchanged": 0,
        "unknown": 2
      },
      "merged": 5,
      "reapprovals": 1,
      "reviewed": 3,
      "rounds": {
        "max": 3,
        "mean": 3.0,
        "median": 3,
        "p90": 3
      },
      "size": {
        "code_files": null,
        "code_lines": null,
        "sized": 0,
        "test_files": null,
        "test_lines": null,
        "unknown": 3
      },
      "three_plus": {
        "count": 3,
        "pct": 100
      },
      "verdicts": 9,
      "withdrawn_ignored": {
        "blocking": 7,
        "due": 0,
        "either_pct": 0,
        "ignored": 0,
        "ignored_pct": null,
        "not_due": 0,
        "pending": null,
        "polish": 0,
        "unknown": 0,
        "withdrawn": 0,
        "withdrawn_pct": 0
      }
    },
    "300-599": {
      "approve_first": {
        "count": 2,
        "pct": 29
      },
      "changes": {
        "mean": 1.14,
        "total": 8
      },
      "distribution": {
        "1": 2,
        "2": 2,
        "3": 2,
        "4": 0,
        "5+": 1
      },
      "findings": {
        "first": {
          "Spec": 9,
          "Standards": 0,
          "Sweep": 3,
          "total": 12
        },
        "rechecks": {
          "Spec": 0,
          "Standards": 0,
          "Sweep": 2,
          "count": 10,
          "total": 2,
          "with_new_blocker": 2
        }
      },
      "late": {
        "blocking": 14,
        "changed": 0,
        "findings": 14,
        "late": 2,
        "pct": 14,
        "pre_existing": 0,
        "unchanged": 0,
        "unknown": 2
      },
      "merged": 9,
      "reapprovals": 3,
      "reviewed": 7,
      "rounds": {
        "max": 5,
        "mean": 2.43,
        "median": 2,
        "p90": 5
      },
      "size": {
        "code_files": null,
        "code_lines": null,
        "sized": 0,
        "test_files": null,
        "test_lines": null,
        "unknown": 7
      },
      "three_plus": {
        "count": 3,
        "pct": 43
      },
      "verdicts": 17,
      "withdrawn_ignored": {
        "blocking": 14,
        "due": 0,
        "either_pct": null,
        "ignored": 0,
        "ignored_pct": null,
        "not_due": 1,
        "pending": "not yet due",
        "polish": 1,
        "unknown": 0,
        "withdrawn": 0,
        "withdrawn_pct": 0
      }
    },
    "600+": {
      "approve_first": {
        "count": 0,
        "pct": 0
      },
      "changes": {
        "mean": 1.9,
        "total": 19
      },
      "distribution": {
        "1": 0,
        "2": 3,
        "3": 6,
        "4": 1,
        "5+": 0
      },
      "findings": {
        "first": {
          "Spec": 24,
          "Standards": 1,
          "Sweep": 12,
          "total": 37
        },
        "rechecks": {
          "Spec": 2,
          "Standards": 1,
          "Sweep": 3,
          "count": 18,
          "total": 6,
          "with_new_blocker": 5
        }
      },
      "late": {
        "blocking": 43,
        "changed": 0,
        "findings": 43,
        "late": 6,
        "pct": 14,
        "pre_existing": 0,
        "unchanged": 0,
        "unknown": 6
      },
      "merged": 12,
      "reapprovals": 2,
      "reviewed": 10,
      "rounds": {
        "max": 4,
        "mean": 2.8,
        "median": 3.0,
        "p90": 3
      },
      "size": {
        "code_files": null,
        "code_lines": null,
        "sized": 0,
        "test_files": null,
        "test_lines": null,
        "unknown": 10
      },
      "three_plus": {
        "count": 7,
        "pct": 70
      },
      "verdicts": 28,
      "withdrawn_ignored": {
        "blocking": 43,
        "due": 0,
        "either_pct": null,
        "ignored": 0,
        "ignored_pct": null,
        "not_due": 5,
        "pending": "not yet due",
        "polish": 5,
        "unknown": 0,
        "withdrawn": 2,
        "withdrawn_pct": 5
      }
    },
    "600-999": {
      "approve_first": {
        "count": 0,
        "pct": 0
      },
      "changes": {
        "mean": 1.86,
        "total": 13
      },
      "distribution": {
        "1": 0,
        "2": 3,
        "3": 3,
        "4": 1,
        "5+": 0
      },
      "findings": {
        "first": {
          "Spec": 21,
          "Standards": 1,
          "Sweep": 10,
          "total": 32
        },
        "rechecks": {
          "Spec": 2,
          "Standards": 0,
          "Sweep": 2,
          "count": 12,
          "total": 4,
          "with_new_blocker": 4
        }
      },
      "late": {
        "blocking": 36,
        "changed": 0,
        "findings": 36,
        "late": 4,
        "pct": 11,
        "pre_existing": 0,
        "unchanged": 0,
        "unknown": 4
      },
      "merged": 7,
      "reapprovals": 1,
      "reviewed": 7,
      "rounds": {
        "max": 4,
        "mean": 2.71,
        "median": 3,
        "p90": 4
      },
      "size": {
        "code_files": null,
        "code_lines": null,
        "sized": 0,
        "test_files": null,
        "test_lines": null,
        "unknown": 7
      },
      "three_plus": {
        "count": 4,
        "pct": 57
      },
      "verdicts": 19,
      "withdrawn_ignored": {
        "blocking": 36,
        "due": 0,
        "either_pct": null,
        "ignored": 0,
        "ignored_pct": null,
        "not_due": 5,
        "pending": "not yet due",
        "polish": 5,
        "unknown": 0,
        "withdrawn": 2,
        "withdrawn_pct": 6
      }
    },
    "under 300": {
      "approve_first": {
        "count": 24,
        "pct": 77
      },
      "changes": {
        "mean": 0.29,
        "total": 9
      },
      "distribution": {
        "1": 24,
        "2": 5,
        "3": 1,
        "4": 1,
        "5+": 0
      },
      "findings": {
        "first": {
          "Spec": 11,
          "Standards": 0,
          "Sweep": 3,
          "total": 14
        },
        "rechecks": {
          "Spec": 0,
          "Standards": 0,
          "Sweep": 0,
          "count": 10,
          "total": 0,
          "with_new_blocker": 0
        }
      },
      "late": {
        "blocking": 14,
        "changed": 0,
        "findings": 14,
        "late": 0,
        "pct": 0,
        "pre_existing": 0,
        "unchanged": 0,
        "unknown": 0
      },
      "merged": 39,
      "reapprovals": 1,
      "reviewed": 31,
      "rounds": {
        "max": 4,
        "mean": 1.32,
        "median": 1,
        "p90": 2
      },
      "size": {
        "code_files": null,
        "code_lines": null,
        "sized": 0,
        "test_files": null,
        "test_lines": null,
        "unknown": 31
      },
      "three_plus": {
        "count": 2,
        "pct": 6
      },
      "verdicts": 41,
      "withdrawn_ignored": {
        "blocking": 14,
        "due": 0,
        "either_pct": null,
        "ignored": 0,
        "ignored_pct": null,
        "not_due": 10,
        "pending": "not yet due",
        "polish": 10,
        "unknown": 0,
        "withdrawn": 0,
        "withdrawn_pct": 0
      }
    }
  },
  "ticket_sizes": {
    "L": {
      "count": 2,
      "median_diff": 206.0
    },
    "M": {
      "count": 7,
      "median_diff": 671
    },
    "S": {
      "count": 50,
      "median_diff": 160.5
    }
  },
  "tickets": {
    "All": {
      "approve_first": {
        "count": 26,
        "pct": 54
      },
      "changes": {
        "mean": 0.75,
        "total": 36
      },
      "distribution": {
        "1": 26,
        "2": 10,
        "3": 9,
        "4": 2,
        "5+": 1
      },
      "findings": {
        "first": {
          "Spec": 44,
          "Standards": 1,
          "Sweep": 18,
          "total": 63
        },
        "rechecks": {
          "Spec": 2,
          "Standards": 1,
          "Sweep": 5,
          "count": 38,
          "total": 8,
          "with_new_blocker": 7
        }
      },
      "late": {
        "blocking": 71,
        "changed": 0,
        "findings": 71,
        "late": 8,
        "pct": 11,
        "pre_existing": 0,
        "unchanged": 0,
        "unknown": 8
      },
      "merged": 60,
      "reapprovals": 6,
      "reviewed": 48,
      "rounds": {
        "max": 5,
        "mean": 1.79,
        "median": 1.0,
        "p90": 3
      },
      "size": {
        "code_files": null,
        "code_lines": null,
        "sized": 0,
        "test_files": null,
        "test_lines": null,
        "unknown": 48
      },
      "three_plus": {
        "count": 12,
        "pct": 25
      },
      "verdicts": 86,
      "withdrawn_ignored": {
        "blocking": 71,
        "due": 0,
        "either_pct": null,
        "ignored": 0,
        "ignored_pct": null,
        "not_due": 16,
        "pending": "not yet due",
        "polish": 16,
        "unknown": 0,
        "withdrawn": 2,
        "withdrawn_pct": 3
      }
    },
    "openwizdev/OpenWiz": {
      "approve_first": {
        "count": 6,
        "pct": 55
      },
      "changes": {
        "mean": 0.82,
        "total": 9
      },
      "distribution": {
        "1": 6,
        "2": 0,
        "3": 4,
        "4": 0,
        "5+": 1
      },
      "findings": {
        "first": {
          "Spec": 5,
          "Standards": 0,
          "Sweep": 1,
          "total": 6
        },
        "rechecks": {
          "Spec": 0,
          "Standards": 1,
          "Sweep": 3,
          "count": 12,
          "total": 4,
          "with_new_blocker": 3
        }
      },
      "late": {
        "blocking": 10,
        "changed": 0,
        "findings": 10,
        "late": 4,
        "pct": 40,
        "pre_existing": 0,
        "unchanged": 0,
        "unknown": 4
      },
      "merged": 17,
      "reapprovals": 4,
      "reviewed": 11,
      "rounds": {
        "max": 5,
        "mean": 2.09,
        "median": 1,
        "p90": 3
      },
      "size": {
        "code_files": null,
        "code_lines": null,
        "sized": 0,
        "test_files": null,
        "test_lines": null,
        "unknown": 11
      },
      "three_plus": {
        "count": 5,
        "pct": 45
      },
      "verdicts": 23,
      "withdrawn_ignored": {
        "blocking": 10,
        "due": 0,
        "either_pct": null,
        "ignored": 0,
        "ignored_pct": null,
        "not_due": 1,
        "pending": "not yet due",
        "polish": 1,
        "unknown": 0,
        "withdrawn": 0,
        "withdrawn_pct": 0
      }
    },
    "openwizdev/WizMarket": {
      "approve_first": {
        "count": 0,
        "pct": null
      },
      "changes": {
        "mean": null,
        "total": 0
      },
      "distribution": {
        "1": 0,
        "2": 0,
        "3": 0,
        "4": 0,
        "5+": 0
      },
      "findings": {
        "first": {
          "Spec": 0,
          "Standards": 0,
          "Sweep": 0,
          "total": 0
        },
        "rechecks": {
          "Spec": 0,
          "Standards": 0,
          "Sweep": 0,
          "count": 0,
          "total": 0,
          "with_new_blocker": 0
        }
      },
      "late": {
        "blocking": 0,
        "changed": 0,
        "findings": 0,
        "late": 0,
        "pct": null,
        "pre_existing": 0,
        "unchanged": 0,
        "unknown": 0
      },
      "merged": 5,
      "reapprovals": 0,
      "reviewed": 0,
      "rounds": {
        "max": null,
        "mean": null,
        "median": null,
        "p90": null
      },
      "size": {
        "code_files": null,
        "code_lines": null,
        "sized": 0,
        "test_files": null,
        "test_lines": null,
        "unknown": 0
      },
      "three_plus": {
        "count": 0,
        "pct": null
      },
      "verdicts": 0,
      "withdrawn_ignored": {
        "blocking": 0,
        "due": 0,
        "either_pct": null,
        "ignored": 0,
        "ignored_pct": null,
        "not_due": 0,
        "pending": null,
        "polish": 0,
        "unknown": 0,
        "withdrawn": 0,
        "withdrawn_pct": null
      }
    },
    "openwizdev/WizRoom": {
      "approve_first": {
        "count": 0,
        "pct": null
      },
      "changes": {
        "mean": null,
        "total": 0
      },
      "distribution": {
        "1": 0,
        "2": 0,
        "3": 0,
        "4": 0,
        "5+": 0
      },
      "findings": {
        "first": {
          "Spec": 0,
          "Standards": 0,
          "Sweep": 0,
          "total": 0
        },
        "rechecks": {
          "Spec": 0,
          "Standards": 0,
          "Sweep": 0,
          "count": 0,
          "total": 0,
          "with_new_blocker": 0
        }
      },
      "late": {
        "blocking": 0,
        "changed": 0,
        "findings": 0,
        "late": 0,
        "pct": null,
        "pre_existing": 0,
        "unchanged": 0,
        "unknown": 0
      },
      "merged": 0,
      "reapprovals": 0,
      "reviewed": 0,
      "rounds": {
        "max": null,
        "mean": null,
        "median": null,
        "p90": null
      },
      "size": {
        "code_files": null,
        "code_lines": null,
        "sized": 0,
        "test_files": null,
        "test_lines": null,
        "unknown": 0
      },
      "three_plus": {
        "count": 0,
        "pct": null
      },
      "verdicts": 0,
      "withdrawn_ignored": {
        "blocking": 0,
        "due": 0,
        "either_pct": null,
        "ignored": 0,
        "ignored_pct": null,
        "not_due": 0,
        "pending": null,
        "polish": 0,
        "unknown": 0,
        "withdrawn": 0,
        "withdrawn_pct": null
      }
    },
    "openwizdev/WizSite": {
      "approve_first": {
        "count": 1,
        "pct": 33
      },
      "changes": {
        "mean": 0.67,
        "total": 2
      },
      "distribution": {
        "1": 1,
        "2": 1,
        "3": 1,
        "4": 0,
        "5+": 0
      },
      "findings": {
        "first": {
          "Spec": 3,
          "Standards": 0,
          "Sweep": 1,
          "total": 4
        },
        "rechecks": {
          "Spec": 1,
          "Standards": 0,
          "Sweep": 0,
          "count": 3,
          "total": 1,
          "with_new_blocker": 1
        }
      },
      "late": {
        "blocking": 5,
        "changed": 0,
        "findings": 5,
        "late": 1,
        "pct": 20,
        "pre_existing": 0,
        "unchanged": 0,
        "unknown": 1
      },
      "merged": 4,
      "reapprovals": 1,
      "reviewed": 3,
      "rounds": {
        "max": 3,
        "mean": 2.0,
        "median": 2,
        "p90": 3
      },
      "size": {
        "code_files": null,
        "code_lines": null,
        "sized": 0,
        "test_files": null,
        "test_lines": null,
        "unknown": 3
      },
      "three_plus": {
        "count": 1,
        "pct": 33
      },
      "verdicts": 6,
      "withdrawn_ignored": {
        "blocking": 5,
        "due": 0,
        "either_pct": null,
        "ignored": 0,
        "ignored_pct": null,
        "not_due": 2,
        "pending": "not yet due",
        "polish": 2,
        "unknown": 0,
        "withdrawn": 0,
        "withdrawn_pct": 0
      }
    },
    "openwizdev/WizSkills": {
      "approve_first": {
        "count": 19,
        "pct": 56
      },
      "changes": {
        "mean": 0.74,
        "total": 25
      },
      "distribution": {
        "1": 19,
        "2": 9,
        "3": 4,
        "4": 2,
        "5+": 0
      },
      "findings": {
        "first": {
          "Spec": 36,
          "Standards": 1,
          "Sweep": 16,
          "total": 53
        },
        "rechecks": {
          "Spec": 1,
          "Standards": 0,
          "Sweep": 2,
          "count": 23,
          "total": 3,
          "with_new_blocker": 3
        }
      },
      "late": {
        "blocking": 56,
        "changed": 0,
        "findings": 56,
        "late": 3,
        "pct": 5,
        "pre_existing": 0,
        "unchanged": 0,
        "unknown": 3
      },
      "merged": 34,
      "reapprovals": 1,
      "reviewed": 34,
      "rounds": {
        "max": 4,
        "mean": 1.68,
        "median": 1.0,
        "p90": 3
      },
      "size": {
        "code_files": null,
        "code_lines": null,
        "sized": 0,
        "test_files": null,
        "test_lines": null,
        "unknown": 34
      },
      "three_plus": {
        "count": 6,
        "pct": 18
      },
      "verdicts": 57,
      "withdrawn_ignored": {
        "blocking": 56,
        "due": 0,
        "either_pct": null,
        "ignored": 0,
        "ignored_pct": null,
        "not_due": 13,
        "pending": "not yet due",
        "polish": 13,
        "unknown": 0,
        "withdrawn": 2,
        "withdrawn_pct": 4
      }
    }
  },
  "window": {
    "merged_from": "2026-11-23T01:00:10Z",
    "merged_to": "2026-11-24T06:13:14Z",
    "opened_after": "2026-11-23T01:00:10Z"
  },
  "worst": [
    {
      "changes": 3,
      "diff": 609,
      "files": 5,
      "number": 309,
      "repo": "openwizdev/WizSkills",
      "rounds": 4,
      "size": "S",
      "title": "#2624: 0.1.2 FR7: ghcache.py, conditional REST reads with saved ETags for every Python poller"
    },
    {
      "changes": 3,
      "diff": 214,
      "files": 4,
      "number": 338,
      "repo": "openwizdev/WizSkills",
      "rounds": 4,
      "size": "S",
      "title": "#2843: 0.1.2: with the App identity off, drop inherited token shims and never expand the key (WizSkills#288 R1, R2)"
    },
    {
      "changes": 3,
      "diff": 1103,
      "files": 5,
      "number": 2732,
      "repo": "openwizdev/OpenWiz",
      "rounds": 3,
      "size": "S",
      "title": "#2688: An installation token can always be revoked, even when its folder is gone or unreadable"
    },
    {
      "changes": 3,
      "diff": 698,
      "files": 4,
      "number": 323,
      "repo": "openwizdev/WizSkills",
      "rounds": 3,
      "size": "M",
      "title": "#2450: 0.1.2 FR2: merge.py records a merge-queue drop and queues it again once its cause is gone"
    },
    {
      "changes": 3,
      "diff": 682,
      "files": 5,
      "number": 336,
      "repo": "openwizdev/WizSkills",
      "rounds": 3,
      "size": "S",
      "title": "#2626: 0.1.2 FR10: post.py paces writes under GitHub's secondary limits"
    },
    {
      "changes": 2,
      "diff": 483,
      "files": 12,
      "number": 2701,
      "repo": "openwizdev/OpenWiz",
      "rounds": 5,
      "size": "S",
      "title": "#2565: 0.1.2 EF3: the CloudRoom driver passes effort as `--reasoning-level`"
    },
    {
      "changes": 2,
      "diff": 476,
      "files": 6,
      "number": 2709,
      "repo": "openwizdev/OpenWiz",
      "rounds": 3,
      "size": "S",
      "title": "#2687: The token helper accepts the cloud sandbox's system gh without weakening R12"
    },
    {
      "changes": 2,
      "diff": 1272,
      "files": 9,
      "number": 337,
      "repo": "openwizdev/WizSkills",
      "rounds": 3,
      "size": "S",
      "title": "#2621: 0.1.2 FR5: the BEFORE bench, a gh meter and one hour of who spends the REST allowance"
    },
    {
      "changes": 2,
      "diff": 405,
      "files": 11,
      "number": 161,
      "repo": "openwizdev/WizSite",
      "rounds": 2,
      "size": null,
      "title": "Landing: the two-minute launch video under the hero"
    },
    {
      "changes": 2,
      "diff": 541,
      "files": 9,
      "number": 313,
      "repo": "openwizdev/WizSkills",
      "rounds": 2,
      "size": null,
      "title": "#2594: 0.1.2 EF7: launch-fleet's Roster starts carry the configured effort, or refuse"
    }
  ]
}
```

</details>
