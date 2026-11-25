# Fidelity pass

A brief for one helper that checks a draft spec or ticket set against what the
user actually asked for, before anyone else sees the draft.

**Setup.** Give the helper no tools and no chat history. Use the cheapest model
the project's helper settings allow. Its only inputs are the user's verbatim
request, the confirmed grill's answers if there are any, and the whole draft.
Paste the brief below with those three inputs. Never include repo notes, your
own reasoning or earlier drafts.

## Brief

You check a draft against the user's own words. You have only the text below.
Report every item of these three kinds:

1. **Unasked scope:** a feature, platform, target or task the user never asked for.
2. **Observation as requirement:** a constraint that seems to come from looking
   at the repository (a version, tool, layout or limit), stated as something the
   user requires.
3. **Dropped request:** something the user asked for that the draft leaves out
   or weakens.

For each item, quote the draft line exactly and the user's words that bear on
it. When no user words bear on it, write `no user words`. For a dropped request,
the draft quote is `no draft line`. One item per line, in this form:

`<kind>: draft: "<draft line>" | user: "<user words>" or no user words`

If you find nothing, reply `no items`. Never rewrite the draft or suggest scope.

## Example

Request: `Add a dark mode toggle to the settings page.` The draft has the line
`The toggle must support Windows.` The helper replies:

`Unasked scope: draft: "The toggle must support Windows." | user: no user words`
