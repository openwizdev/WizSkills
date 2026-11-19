---
name: image
description: Generate or edit pictures, make target pictures before visible UI changes, and capture real pages at phone and desktop widths. Use for image generation, UI design and review, diagrams, charts, and every hill-climb round's picture and screenshot.
version: 0.2.0
---

# Pictures and UI

Use this skill for a standalone picture, a ticket's target picture, or screenshots
of a real page. The hill-climb skill calls it for **every round's picture and
screenshot**. A generated picture is a design target; a screenshot is evidence of
what HTML actually renders. Keep that distinction in every claim.

## Prepare a UI design

For app screens and marketing pages, complete the [UI brief](references/ui-brief.md)
before generating a target. Load the project's approved taste profile and pin its
mood-board commit; keep hard rules, explicit preferences and observed patterns
separate. Give builders and judge the same public, synthetic taste brief, without
private evaluation material. Summarize owner preferences in your own words,
with the decision date and verified private-record comment pointer; never copy
exact owner words or private source file links into the public brief. A changed preference starts a new rubric version
at the next hill-climb stretch; keep the previous brief and evidence.

Choose the app or marketing template for the surface. Write the compact design
specification and keep it beside the prompt: type and loaded fonts, colour roles,
spacing/radius steps, composition, density, phone changes, product-specific
element and what stays fixed. Critique those decisions against the brief before
making the target. Reuse the project's design system; this adds no dependency,
token file or new approval stage.

Prepare one synthetic content packet per design, including empty, zero, long,
sparse and missing cases. Give the target prompt and implementation fixtures the
same packet; reconcile repeated facts, units, totals, dates and chart annotations.
Correct image transcription mistakes or record them explicitly. Invented user
counts, adoption claims and testimonials are not design filler.

## Generate or edit a picture

1. Read the request and references. Identify the deliverable, exact copy, intended
   use, composition, dimensions, style and things to preserve. For an edit, inspect
   the original and state what changes and what stays. Keep private content out of
   prompts, saved artifacts and evidence; use synthetic UI data.
2. **Generate through OpenAI's built-in image tool in Codex, without a separate
   API key.** Generally use a Codex agent on `gpt-6.1-sol` at **medium** effort;
   this is the agent model, not an image-model argument. In another harness, route
   generation to Codex using the project's agent/helper workflow. Discover the
   available image tool and follow its installed imagegen instructions. If that
   route is unavailable, report the blocker on the ticket; never silently switch
   to an API-key runner or substitute an HTML rendering for a generated target.
3. Give the tool a focused prompt: purpose; subject or UI state; reference roles;
   layout and intended viewport; style; exact text; constraints. Pass references
   as references and edit targets as targets. Ask for transparency when required.
   For UI targets, describe the layout at **390 CSS px** and at the desktop width
   (default **1440 CSS px**). Do not squeeze a desktop picture into a phone frame.
4. Inspect the result as an image: composition, legibility, exact copy, preserved
   details, clipping and requested transparency. For UI targets, compare with the
   brief and packet; use the [dark craft checklist](references/ui-craft.md) when
   applicable. A target cannot prove browser contrast or native-control behaviour.
   Correct the specific defect and
   inspect again. Save the selected artifact in the workspace, in an owned path;
   keep the prompt, reference roles and generation route beside it. Preserve
   earlier versions when iterating, so a later comparison has a stable target.

## Target before implementation

**Every ticket that changes something the user sees gets a target picture on the
ticket before it is built.** This includes small visible changes. Read its spec,
confirmed grill, existing design and owned paths first; show the intended state
at phone and desktop widths.

- Save the targets in the ticket's owned evidence path, commit and push them, then
  post a ticket comment embedding the images with immutable URLs to that commit
  (for GitHub, a raw image URL pinned to the commit). Include intended viewports,
  UI state, prompt and constraints. Verify the links render. Do not edit the
  approved ticket body. If no artifact path is owned, ask on the ticket for one.
- **The user approves the picture only for big changes**, such as a new screen, a new
  flow or the landing page's look. Get that approval recorded on the ticket before
  implementing it. For small changes, proceed; the reviewer judges the picture.
  Route an unclear approval decision through the ticket's orchestrator.
- Build the real page as **HTML**, following the project's UI patterns. The target
  guides the build; a generated picture does not prove that page works.
- The reviewer compares screenshots of the real page with the target at **both
  phone and desktop widths**, in the same state. Record differences in hierarchy,
  spacing, type, colour, content, wrapping and clipping; fix unexplained drift.
  Use the [dark craft checklist](references/ui-craft.md) on the actual page too,
  recording measured colour pairs and annotated screenshot regions. Behaviour
  and accessibility still need their own proofs.

## Screenshot a real page

Use the callable [screenshot script](scripts/screenshot.py), also from other
skills, including hill-climb. It needs Python 3, Cloudroom's `browser-harness` and
its Chromium connection; it adds no Python or Node packages. Read the installed
browser-harness skill before browser work. Use only pages you are authorised to
view; a screenshot command never authorises live account reads or writes.

```sh
python3 skills/image/scripts/screenshot.py \
  http://127.0.0.1:3000/fixture \
  --ready-selector '[data-ready="true"]' \
  --out /tmp/image-round-1
```

The URL and selector are examples: choose a **visible selector that marks the
intended settled state**, after the page's data and interactions are ready. For a
non-initial state, provide a fixture URL that opens it, or use browser-harness to
prepare and capture that state explicitly. Do not claim the CLI captures a state
that requires interactions it did not perform.

For each width, the script opens and activates a fresh tab (background pages can
pause rendering),
sets a 1× CSS pixel scale and reduced motion, and visits the URL at **390 × 844**
and **1440 × 900**. These are viewport sizes, not physical phone emulation. It
waits for page load, the visible ready selector, fonts, image decoding (including
lazy images, skipping empty placeholders) and two animation frames, then saves full-page PNGs at those widths:

```text
<new output folder>/
  phone.png
  desktop.png
  capture.json
```

`capture.json` records URL, selector, viewports, page sizes and filenames. It is
written only after both captures complete. Navigation errors, non-success HTTP
status, absent readiness, failed image decoding or other browser failures exit
nonzero. `--timeout SECONDS` changes the positive finite per-step timeout (default
30); it is not a fixed sleep. Each invocation requires a **new output folder**;
failed captures can leave partial files, which are not a completed pair. The
script closes its own tab in success and failure.

Open **both** PNGs before handing them back. Check actual content, fonts, image
loading, overlays, overflow and the intended state. `contentWidth` greater than
the viewport in the manifest flags horizontal overflow to inspect; full-page
images do not excuse it. A selector and a completed pair do not prove visual
quality, touch behaviour, accessibility or correctness of canvas/video/CSS
background assets. If those matter, wait for their explicit readiness with
browser-harness and inspect the result. Never replace a real screenshot with a
mockup or resize an image and call it a second viewport.

For every hill-climb round, keep that round's target, prompt, both real-page
screenshots, capture manifest and comparison together. Use a fresh output path
and record the code commit; let hill-climb decide what to change next. Copy only
reviewed, synthetic evidence into the ticket's owned paths; do not commit a real
page's personal content, account URLs or credentials.

## Diagrams

Explanations and architecture pictures use a **hand-drawn Excalidraw look**:
**Virgil font**, **off-white background**, **coloured rounded frames for where
things run**, **bold black boxes with one grey line under the name**, **few boxes**
and **lots of space**. Keep labels short and connections clear. Check that the
frames correctly show where things run. Do not use default Mermaid architecture
drawings; simple left-to-right ticket graphs are fine. Apply these constraints in
the image prompt and inspect the result; when rendering editable diagram sources,
use Virgil rather than silently substituting another font.

## Charts

Use **one colour-blind-safe palette checked by a validator**, **labels on the
marks**, and **a table behind the chart** containing the plotted values and units.
Do not trust a palette's name as validation: run an available colour-blindness
validator against the actual colours and chart (including protanopia,
deuteranopia and tritanopia views), inspect that series remain distinguishable,
and keep its name, inputs and result in the evidence. If no validator is available,
report that gap; do not call the palette checked. Respect the project's approval
rules before adding a validator dependency.

Render quantitative marks and labels from the table using the project's chart
or HTML tools, then screenshot the real chart. Image generation may explore its
look, but never invent measurements or serve as proof of plotted values. Check
labels, scale, units and plotted values against the table; use labels or shapes
as well as colour so the chart remains understandable without colour.

## Verify

Run the public CLI fixture proofs below, then the consumer project's own
static skills check, if its settings name one:

The screenshot proofs prefer an installed `browser-harness` and use the test-only CI bridge only when no installed harness exists.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s skills/image/tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s skills/image/references -p 'test_*.py' -v
```

The fixture proves responsive screenshot capture and failure handling, not live
pages or image generation. Hand back saved paths, the target/prompt or capture
manifest, what you inspected, comparison results and any unverified part.

## Source and trace

**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.

Jake, 2026-11-01: the image skill uses built-in OpenAI generation through Codex
(generally Sol at medium effort), target pictures before visible UI changes,
owner approval for big changes, phone/desktop screenshots for hill-climb, and
the stated diagram/chart rules
([private record](https://github.com/jparker2006/ClosedWiz/issues/1278#issuecomment-6704791158)).

Prior art: OpenAI's [imagegen](https://github.com/openai/skills/tree/main/skills/.system/imagegen)
(built-in generation and inspecting outputs); GitHub's
[generate-image](https://github.com/github/awesome-copilot/blob/main/skills/generate-image/SKILL.md)
(image generation); Matt Pocock's [prototype](https://github.com/mattpocock/skills)
(real HTML UI explorations). This skill's workflow and screenshot code are
original; no source text or code is adapted from those projects.

Jake, 2026-11-02: UI briefing and dark craft add the six approved design-research
methods: pinned taste briefs, surface-specific templates, design specifications,
one synthetic content packet, separate screenshot critiques and dark craft
([private record](https://github.com/jparker2006/ClosedWiz/issues/640#issuecomment-6573915029)). The references cite the pinned primary sources beside the original
summaries. These methods have not demonstrated an improvement in Jake's taste
judgments; preserve the existing target approvals and independent judging.
