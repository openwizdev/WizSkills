---
name: hill-climb
description: Improve one thing in autonomous rounds with fresh CloudRoom branches, a council of model families scoring each category against reference products (pairwise Bradley-Terry ranking as an option) and human checkpoints. Use for iterative improvement, exploring design directions, or a hill-climb run; design rounds use the image skill for targets and real-page screenshots.
version: 0.2.0
---

# Hill-climb one thing

Change, score, keep or undo. Improve one outcome through autonomous rounds;
keep the best so far, including an earlier round. A judge helps search; Jake's
checkpoint picks are the ground truth for his taste. Never call a fixture run a
live climb, a generated target a working page, or the last candidate the best.

## Set up the run

Read the ticket, spec, confirmed grill, project instructions and owned paths.
Record one outcome, the starting commit and baseline candidate, allowed changes,
required functional checks, and the evidence that would demonstrate improvement.
Use synthetic content in saved artifacts. Keep exact checkpoint answers, thread
ids and evaluation state in the configured private repository or private state.
Public ledgers record a choice in your own words, its date and the verified
private-record comment pointer, never exact user words or links to private files.
This skill gives no new permission to
read live accounts, publish, deploy, merge or spend through a new service.
Unresolved scope or approval questions go to the ticket's orchestrator.

For design runs, complete the image skill's [UI brief](../image/references/ui-brief.md)
before the baseline target. Pin the approved project profile and mood-board
commit in a public taste brief: hard rules, explicit preferences and observed
patterns stay separate. Give builders and judge the same public taste brief,
surface brief, design specification and synthetic content packet; keep hidden
checks and controller evaluation material private. Freeze these public inputs
for the stretch. A changed preference starts a new rubric version at the next
stretch; preserve earlier briefs and comparisons rather than pooling them.

Record a **fixed schedule** before starting: how often a round starts, the few
branches in each round, checkpoint cadence, and a positive stall window measured
in completed unchanged rounds. These are run parameters, not a total round,
time, token or dollar budget. Do not introduce an artificial cap. Use CloudRoom
Loops for scheduled work, never a shell sleep loop; inspect the installed
`room-cli` help for the available schedule flags. At most one round owns a run's
state at a time; a repeated wake resumes it, rather than starting duplicate work.

Pin builder and judge routes and the rubric for a stretch. Cheap builders are
Codex **`gpt-6.1-terra`** and Claude **Haiku 5.5**; they iterate freely. Big builders
are Codex **`gpt-6.1-sol`** and Claude **Opus 5.5**; they make the checkpoint
candidates Jake judges. Verify the harness's model IDs instead of guessing.
For pairwise judging, the judge must be from a **different model family from both
authors of every pair**, not merely a different size. With only OpenAI and Anthropic available,
use one builder family per comparison pool and the other as judge. A mixed pool
needs an independent third family; if none is available, report the blocker,
never let either family judge its own work. A council (below) instead seats at
least two families and needs every family to agree. Record the authors of
inherited candidates too. A model's name in a JSON file is not proof of which model ran.

## Put the judge outside the climbers' reach

The controller owns an evaluation workspace with the judge, frozen judge brief,
scoring scripts, candidate-to-artifact map, raw verdicts and a **held-out check
that climbers never see**. Candidate sandboxes get only their scoped source,
baseline artifacts, public goal and one concrete change. Do not copy the judge
workspace, its credentials, hidden check or controller history into them.

Use separate filesystem and credential boundaries: a writable checkout with the
judge files merely chmod'd read-only under the same user is not isolation. A
CloudRoom child copies its parent's workspace, including uncommitted files, so
keep evaluation material outside the copied project and verify the child's
accessible files and tools before it works. If the filesystem boundary cannot be
enforced, stop setup and report it; a prompt saying "do not edit" is not a guard.
For a skill installed in the candidate repo, provide climbers a scoped source
export that excludes the judge scripts and private evaluation material. Run the
pinned scripts only in the controller's evaluation workspace.

When the runtime cannot enforce a credential boundary between climbers and the
judge, the controller must audit each climber's complete command log and tool
calls after every round, before judging any candidate. Allow only
`room-cli files wait`, CloudRoom's startup step; any other `room-cli` command, or
any use of the bridge to the user's machines, including indirect calls through
commands, scripts or tools, disqualifies the climber. Drop that climber's candidate
from judging and selection, and record the finding in the controller ledger.
If any climber's command log or tool-call record cannot be read completely,
stop the run and report the blocker; never treat an unreadable log as clean.
Climbers' briefs must never mention `room-cli`.

Verify isolation with a harmless denied read/write probe. In the controller,
plant one known-bad candidate and prove the held-out check rejects it. Keep that
check's content and specific feedback private from climbers; expose only pass or
fail. Save these observations separately. The fixture tests below prove neither
sandbox isolation nor the judge's taste.

## Run a round

1. Evaluate the unchanged baseline first (round 0). Preserve its commit and
   artifacts. Maintain a controller ledger of immutable candidates: blind label,
   parent, source commit, builder family/model, one concrete change, round,
   picture/prompt, screenshot paths, checks, verdicts, ranking and keep/undo/crash.
2. On each scheduled round, start a **few fresh CloudRoom threads**, each on its
   own branch copied from the best so far. Use the project's thread workflow and
   `room-cli thread spawn`, never a harness's hidden agents or shared sandbox.
   Commit the selected parent first and pin it in every brief. Each brief stands
   alone: outcome, owned paths, parent commit, public constraints, evidence to
   return and **one concrete change to try**. No inherited chat, long history or
   judge reasoning. Assign distinct concrete directions, rather than "be different".
3. Cheap builders try their changes, run the required functional checks and
   return a candidate commit and artifacts. Preserve failed and discarded tries
   too. The controller checks the actual diff and reads the results. A failed
   check, missing screenshot or absent judge reply is not a win. Do not send a
   failed candidate to taste judging as if it worked.
4. Judge eligible candidates beside the incumbent: by the council (the default
   for design), with the references in the same round, or pairwise with each
   other and the incumbent. Pairwise, refit Bradley-Terry over **all** recorded
   comparisons for the unchanged rubric, including historical candidates. Store
   the raw scores or verdicts and the complete council result or fit, not a
   running Elo update.
5. Keep a newly ranked best only after the functional and unseen checks pass.
   On a top tie keep the incumbent if tied; otherwise record an unresolved tie,
   without choosing by alphabetical order. "Undo" means leave the selected
   incumbent unchanged and retain the losing branch as evidence. Never force-push
   or reset a shared branch. Keep one round record even if every try crashes.
6. Save the round's picture, screenshot, score/ranking and decision; update its
   chart and the completed-round history. Check for Jake's stop and for a stall.
   Archive finished candidate threads after their artifacts have been collected.
   Continue at the next scheduled round without asking whether to keep going.

The controller, not a candidate, advances the best-so-far pointer. Resume from
that ledger after an interruption. Never silently repeat a verdict to get a
nicer result or change the rubric mid-stretch.

## Council judging

The council is the default for design work. Pairwise judging with Bradley-Terry
ranking stays available as an option (next section): use it when the ticket asks
for it, for work with no category rubric, or to settle a council's tie. A single
judge, or one pairwise vote, can tie on position bias; a council of families
scoring each category gives a reason per category and a relative stop.

**The panel.** Seat three judges from at least two model families, each a pinned
route (harness, model, effort) in a fresh context for every round. Judges score
every artifact from 1 to 10 in each category of the frozen rubric, with a short
reason for each score. A ticket may name its own categories; otherwise use the
defaults for its kind of work:

- **Design:** hierarchy, typography, color and contrast, consistency, clarity.
- **Copy:** clarity, accuracy, tone, brevity.

With only OpenAI and Anthropic available, the council includes the builders'
family. That is why every seated family's mean must agree before a candidate
leads: a family that favours its own work cannot carry the result alone.
Record each judge's route and family; a family label is not proof of the model.

**References in the panel.** Named reference products are scored in the same
round, with the same rubric, as the candidates: real screenshots at the same
viewports, under blind labels like the candidates'. The aim is relative: a
candidate that beats every reference in every category, consistently. There is
no absolute target number.

**Hidden target.** Judges never see the score being aimed for. A judge's brief
holds the frozen rubric, the 1–10 scale, the categories and the blind artifacts;
never the stop condition, an earlier score, another judge's score or which
artifacts are references. Vary the artifacts' order between judges.

**Cheapest judge first.** Run the cheapest judge alone until it is satisfied, then
seat the whole council for every later round. It is satisfied when some candidate
beats every reference in every category on its scores. Give each judge a cost
rank (a positive integer; the cheapest rank must belong to one family). Record
each judge's scores for every round in the controller ledger, cheap-only rounds
and discarded candidates included.

**Stop.** A candidate **leads** a round when it beats every reference in every
category in every seated family's mean. The run stops on the references when the
same single candidate leads, and is also the round's `best`, for `--window`
consecutive full-council rounds. A cheap-only round never counts; a round with no
leader, two leaders, or a `best` that does not lead resets the count, so a
reference stop always certifies the candidate the run keeps. Rescore the leader
each round in fresh contexts; never carry a score forward. The stall rule below
still applies, with each round's `best` as its winner, and so does Jake's stop.

Write `council.json`; a real round holds a score for every seated judge,
artifact and category (one row is shown here):

```json
{"categories":["hierarchy","clarity"],"artifacts":[{"id":"A","family":"openai"},{"id":"R","reference":"Synthetic Reference One"}],"judges":[{"id":"J1","family":"anthropic","cost":1},{"id":"J2","family":"openai","cost":2},{"id":"J3","family":"anthropic","cost":3}],"rounds":[{"round":0,"judges":["J1"],"scores":[{"judge":"J1","artifact":"A","category":"hierarchy","score":7,"reason":"The next action reads first"}]}]}
```

```sh
python3 skills/hill-climb/scripts/climb.py council council.json --window 2 > council-result.json
python3 skills/hill-climb/scripts/climb.py table council.json > scores.md
```

`council` checks the panel, the seat of every round (the cheapest judge until
satisfied, then all), complete integer scores and every reference in every round,
and refuses anything else (exit 2). For each round it gives the `phase` (`cheap`
or `full`), seated `judges`, the council `means` and `family_means` per artifact
and category, `references`, `leaders`, the `top` set and its `best` candidate by
mean over categories (`null` on a tie); then `next_phase`, `next_judges`,
`consistent_rounds`, `leader`, `stop` and `reason` (`references` or `continue`).
`table` prints Markdown, not JSON: each judge's scores and the council mean per
round, with the leader marked. Means hold only for this rubric and panel: never
pool them across rubrics or panels, or call one an absolute quality score.

## Pairwise judging and ranking

The offline [CLI](scripts/climb.py) uses Python 3's standard library. It reads
UTF-8 JSON, writes one JSON result to stdout and touches no input file. Exit 2
means refusal, with no result on stdout. It plans comparisons and fits returned
verdicts; it does **not** call models or authenticate the supplied family labels.
The controller verifies actual model routes and executes the tasks in an isolated
judge thread. Use blind artifact labels and hide builder names, prompts and code
from the visual judge; provide the frozen brief and the two artifacts only.

Write `pool.json` (canonical lowercase family tokens; unique ASCII labels):

```json
{"candidates":[{"id":"A","family":"openai"},{"id":"B","family":"openai"}],"judge_family":"anthropic"}
```

```sh
python3 skills/hill-climb/scripts/climb.py pairs pool.json > tasks.json
```

`tasks` contains each unordered pair exactly twice: `{left:A,right:B}`, then
`{left:B,right:A}`. Present each order in a fresh judge context with no previous
verdict. Judge two at a time against the same brief, returning exactly
`{"winner":"left|right|tie","reason":"concrete comparison"}` (choose one enum
value, not that placeholder string). Map the result back through the task's
labels. Preserve both calls and their original order, reason, rubric version,
model and artifacts in the controller ledger. A missing or malformed result
leaves that pair incomplete; do not treat it as a tie or silently omit it.

For `rank`, add `comparisons` to the pool object:

```json
{"candidates":[{"id":"A","family":"openai"},{"id":"B","family":"openai"}],"judge_family":"anthropic","comparisons":[{"left":"A","right":"B","winner":"left","reason":"Clearer hierarchy"},{"left":"B","right":"A","winner":"right","reason":"Clearer hierarchy"}]}
```

```sh
python3 skills/hill-climb/scripts/climb.py rank results.json > ranking.json
```

Append every completed pair of calls to `results.json`; include every candidate
in that stretch, even discarded ones. Connect each new candidate to the incumbent
and the current pool; a disconnected graph or unequal counts of the two orders
is refused. Never aggregate only the latest round. Preserve the per-call ledger
so counts alone cannot disguise a duplicate response or missing task.

The fit uses `P(A beats B) = strength_A / (strength_A + strength_B)`, ties as half
a win, and a disclosed symmetric **half-win prior per observed unordered pair**.
This is a smoothed Bradley-Terry fit: the prior keeps unanimous wins finite,
rather than fabricating infinite confidence. Strengths sum to one; they are
relative estimates, not absolute quality scores or uncertainty intervals. The
output gives each normalized `strength` and its natural `log_strength`, the
tied `top` set and a `winner` only for a unique top. Ordering and ties use log
strengths; a display strength may underflow to zero in a long history without
losing its finite log strength. A log gap within 1e-8 is unresolved. `position_splits` is
the minimum count of disagreements between the two orientation histograms,
not a measure of human agreement; inspect the individual verdicts too. Both
orders contribute equally to the likelihood, including conflicting preferences.

The solver takes damped Newton steps in log space, pins one coordinate and solves
the weighted graph Laplacian with standard-library Gaussian elimination. It
converges when the largest likelihood-gradient entry is below 1e-9, without a
fixed iteration or round count. Singular/nonfinite steps or numerical stagnation
are refused instead of publishing a ranking. All source JSON objects have exact
keys; duplicate keys, wrong types, unknown enum values and non-JSON numeric
constants are refused. Candidate and judge family labels must differ, but their
truth still requires the controller's route evidence.

## Checkpoints: Jake chooses

On the fixed checkpoint schedule, have the **big models** produce candidates
from the strongest cheap-model directions, with the same one-change discipline.
Judge those candidates against the incumbent before selecting the **best three**
for Jake; do not just rename cheap outputs as big-model work. Show actual rendered
artifacts, stable letter labels, the changes, ranking and judge reasons. Retain
older candidates so a middle round can win. If fewer than three valid candidates
exist, show that gap and collect more; do not pad the shortlist with failed work.

Jake may pick one or mix parts of several candidates. Save the exact answer
privately; publicly record the chosen parts and the private-record pointer;
make a mixed choice a new candidate with its contributing parents and test/render
it before continuing. His pick becomes the next stretch's direction and parent.
Compare his explicit pairwise preferences among the shown candidates with the
judge's **pre-pick** ordering: agreed pairs / comparable pairs, with numerator,
denominator and ties reported. A mix is not a fabricated pairwise vote; ask which
parts he prefers and record agreement as unmeasured until comparable picks exist.

Show him **before and after images with arrows and short notes on what changed,
plus the per-round score table**: the incumbent's and each shortlisted candidate's
real screenshots side by side, an arrow to each changed region with a one-line
note, drawn over the real screenshots with the image skill (never a generated
picture of a page), and the `table` output for the stretch's rounds.

Use paraphrases of his reasons, with the date and private-record pointer, as
calibration examples for the next stretch; keep the exact reasons private.
Freeze a new brief
version there, keep the previous one and its rankings, and start a new comparison
ledger if the rubric or judge changes; never pool incompatible measurements.
Preserve the chosen parent and its lineage across stretches. A pending checkpoint
is a wait for Jake's pick, not a completed climb. Continue independent authorised
exploration while waiting, without overriding the checkpoint's choice.

## Stall and stop

A stall is **the same resolved selected winner for the configured number of
completed rounds after it was selected**. It is not a total experiment count.
The window is required; this skill invents no universal threshold. A new winner
resets the counter; an unknown or unresolved tied winner breaks the streak and
must not manufacture convergence. If a tied ranking keeps the incumbent by the
rule above, it is still a resolved selected winner. Checkpoint picks and new
rubric stretches start a fresh history at round 0. Do not mark waiting or
unfinished rounds completed.

```json
{"rounds":[{"round":0,"winner":"A"},{"round":1,"winner":"A"},{"round":2,"winner":"A"}],"stopped_by_jake":false}
```

```sh
python3 skills/hill-climb/scripts/climb.py stall history.json --window 2
```

That example stops after two unchanged completed rounds. Histories must be
contiguous from baseline 0; a missing round is refused. `winner:null` records an
unresolved result and resets the streak. Set `stopped_by_jake:true` only for his
explicit stop: it ends the run even with empty history. The output names
`continue`, `stall` or `jake`. When stalled or stopped, stop the run's scheduled
loop, collect artifacts and archive its workers. Report the best candidate,
lineage, completed rounds, measurements and gaps. Broken infrastructure pauses
work with a blocker; it is neither a stall nor success. Never declare a win
because an account limit, timeout or missing reply stopped progress.

## Design rounds and the chart

Use the [image skill](../image/SKILL.md): Codex Sol generates pictures to set the
look through the built-in image tool. Inspect the target; keep its prompt,
references and generation route. Those pictures set mood; **build real HTML**
and judge what it renders. Follow the image skill's target approval rules before
implementing a big visual change; checkpoints do not grant a deployment or merge.

For **every round**, including discarded candidates, retain the target picture,
prompt, code commit, both real-page screenshots, capture manifest, comparisons
and ranking in one round folder. Include the pinned taste brief, surface brief,
design specification, content packet and written screenshot critique described
below. Use its [screenshot script](../image/scripts/screenshot.py)
on the settled state at **390 × 844** and **1440 × 900** CSS pixels, in fresh output
folders with a visible readiness selector. Open both PNGs. Never resize one shot
and call it the other viewport. Judge the phone and desktop pair together on
**design, originality, craft and function**. Test interactions and accessibility
separately: a screenshot does not prove that a button works. Record unavailable
artifacts explicitly for a crashed round; never invent them. For nonvisual work,
save the artifact preview and screenshot of its measured results instead.

### Screenshot critique

After inspecting both real-page images, write separate passes in the round's
critique record. Cite the screenshot filename and region in each pass, including
passes with no defect found; do not substitute a generic polish score.

| Pass | What to inspect |
| --- | --- |
| First-visible answer | Can the person find the screen's answer and next action, or the page's promise and evidence? |
| Visual masses and hierarchy | Which regions dominate before reading? Does that order serve the brief? |
| Alignment and accidental voids | Shared edges, grouping and deliberate space; locate empty regions that disrupt the work. |
| Type and contrast | Loaded fonts, readable roles and measured colour pairs; use the shared dark craft checks. |
| Content fullness | Reconcile the packet and visible facts; distinguish purposeful space from missing content. |
| Phone composition | Inspect the actual phone image for action order, wrapping, readable fields and overflow. |
| Detailed defects | Locate clipped copy, weak control edges, icons and state cues needing correction. |

For each issue, fill this record; keep the most consequential issues first:

| Viewport | Screenshot region | Observation | Impact | One proposed change |
| --- | --- | --- | --- | --- |
| 390 × 844 | `phone.png`, queue header, x:16–374 y:96–156 | Long label wraps over the count | The count cannot be read | Put the count on a separate aligned row |

That row is a synthetic example, not an observation of a current page. Give a
real issue an exact region or annotated marker so another reader can locate it.
Use the image skill's [dark craft checklist](../image/references/ui-craft.md) for
target and real-page inspection; retain the actual contrast pairs and metric.
Turn a chosen issue into one concrete change per candidate, keeping other brief
decisions fixed. Keep this diagnostic record separate from raw pairwise verdicts;
it adds no score, scoring formula or stopping rule of its own.

Jake, 2026-11-02: add separate screenshot critiques and dark craft from design
research proposals 5–6
([private record](https://github.com/jparker2006/ClosedWiz/issues/640#issuecomment-6573915029)).
These passes summarise [TasteSkill's critique](https://github.com/Leonxlnx/taste-skill/blob/12af471f627f866411b4bd785b19646d3672784c/skills/taste-skill/references/critique.md)
and [OneRedOak's evidence-based review](https://github.com/OneRedOak/claude-code-workflows/blob/29a34c725313c7621f426f838ed31cf482473fb4/design-review/design-review-agent.md).
They do not establish better visual taste or replace functional eligibility.

### Chart evidence

Keep a **chart of the climb**, backed by a table: round, selected candidate,
rubric version, raw comparisons, BT strength, and predicted win probability
against the fixed baseline in that stretch. Plot that baseline-relative
probability (unit: probability, 0–1) and label each mark; retain the complete fit
at each round since adding opponents can rescale strengths. Do not imply that
relative strength or a refitted probability is absolute quality. Mark ties,
crashes and checkpoint picks; do not join different rubrics as a single metric.
Compute pair probabilities from the **log-strength difference**, never by
dividing display strengths that may both be zero. For difference `d`, use
`1 / (1 + exp(-d))` when `d >= 0`, and `exp(d) / (1 + exp(d))` otherwise.

For a council run, chart each category's council mean per round (unit: score,
1–10) for the round's best candidate and for each reference, from the `council`
output; mark cheap-only rounds and keep the per-judge table behind it.

Apply the image skill's **chart rules**: one colour-blind-safe palette validated
on the actual colours/chart for protanopia, deuteranopia and tritanopia, labels on
marks, and the table of plotted values and units behind the chart. Keep validator
name, inputs and results; without one, report the palette as unverified. Render
marks from recorded numbers and screenshot the real chart; image generation must
not invent measurements. Use labels/shapes as well as colour.

## Verify this skill

Run the fixture proofs below, then the consumer project's own static skills
check, if its settings name one.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s skills/hill-climb/tests -v
```

Fixtures prove pair planning, fitting, council scoring, seating and stopping,
not live judging, a hidden target, isolation, model quality, human agreement,
image generation or a real design climb.
First use follows the confirmed **U1 amendment**: OpenWiz's web UI as the
power-user cockpit for controlling the factory; the landing page is second.
The skill's build does not itself start either run.

## Sources and decisions

**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.

Jake, 2026-11-01: autonomous rounds, fresh branches, frozen independent judging,
checkpoint picks and mixes, complete evidence, and a stall or explicit stop govern
the climb; U1 makes the factory cockpit its first use, landing page second
([private record](https://github.com/jparker2006/ClosedWiz/issues/1278#issuecomment-6704791158)).

Jake, 2026-11-06: a council is the default for design, with pairwise judging and
Bradley–Terry ranking retained as an option
([private record](https://github.com/jparker2006/ClosedWiz/issues/1278#issuecomment-6704794292)).
Research recommendations supply evidence, not additional requirements.

Concepts adapted, with original prose and code here:

- [Karpathy's autoresearch](https://github.com/karpathy/autoresearch): one change,
  fixed external evaluator, keep/undo and logging discarded tries. We preserve
  branches instead of adopting its destructive reset or fixed experiment budget.
- [Anthropic's frontend generator/evaluator](https://www.anthropic.com/engineering/harness-design-long-running-apps):
  judge real rendered pages on design, originality, craft and function, and retain
  middle rounds. Its 5–15 rounds are not a cap here.
- [Theo Browne's council](https://github.com/t3dotgg/tstack/tree/1085050/skills/council):
  independent model feedback and honest reporting. The lettered-mock mixing story
  was secondary in the research; Jake independently confirmed mixing here. Theo
  did not publish a hill-climb skill in the pack the research read.
- Theo Browne's video "Agents Sucked At UI (Until Today)" (T3 Code, 2026-11-03):
  a council of model families scoring per category, reference products in the
  panel, a relative stop, a hidden target, the cheapest judge first and annotated
  before and after images. Jake chose it after a single pairwise judge tied on
  position bias (#1331).
- [Simon Willison's pairwise image Elo](https://simonwillison.net/2025/Jun/6/six-months-in-llms/):
  two-at-a-time image comparisons with structured reasons. Here we add swapped
  orders and fit Bradley-Terry over history, rather than use online Elo.
- [LMSYS's Bradley-Terry explanation](https://lmsys.org/blog/2023-12-07-leaderboard/):
  centralized fitting independent of game order and half-win ties. Symmetric
  smoothing and the standard-library solver here are our implementation choices.

No third-party source text or code is copied. None of these sources adds a
round/spend cap, oscillation stop, complexity penalty or hidden design limit to
the confirmed grill.
