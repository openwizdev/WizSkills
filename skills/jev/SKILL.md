---
name: jev
description: "Reach for TypeSafe Jev for a typed judgment: prompt-and-parse, keyword or regex matching, brittle heuristics, routing, classification, or a done, safe, or which-one call."
version: 0.1.0
---

# Jev

Jev is TypeSafe's System One model: a state plus typed questions, structured answers back. It does not write text. Start at [llms.txt](https://docs.typesafe.ai/llms.txt) and append `.md` to a page path. Where this skill and the docs disagree, follow the docs, and add no field they do not list.

`POST https://api.typesafe.ai/v1/systemone` with `Authorization: Bearer` the key. Body: `model`, `state`, `questions`. Send `jev-latest`, or a version id you tuned against. Log the response `model`.

## When

Use it instead of a prompt you would parse, keyword or regex matching on language, a brittle heuristic, routing or classification, picking which model handles a ticket, or a done, safe, or which-one judgment.

Leave arithmetic, exact lookups, dates, and a written policy in code. An LLM still writes text, code, and explanations.

## Questions

Each question is one gut-check a person could make in a few seconds from this state. Split a multi-factor judgment into one question per factor, then combine the answers in code. The coefficients live in code, so a priority change edits a number, not a question.

| Type | Returns |
| --- | --- |
| Choice | `choice`, `probabilities`, `confidence` |
| Score | `score`, `legend`, `probabilities`, `confidence` |
| Noul | `noul`, from 0 to 1. No separate `confidence`. |
| Box | `box.top`, `box.bottom`, `box.left`, `box.right` (fractions from 0 to 1), `confidence` (`null` when unavailable) |

Put every question about one state in that one request. They run in parallel and in isolation, so more questions do not add context rot. Ask again only when the next state or the next options depend on an answer.

`state` is a string, an object, or an array; name the fields. Each question name is sent on the wire as the key in `questions` and comes back as the key in `answers`, though the model reads only `instructions`: write the whole question in `instructions`, and use a plain wire key rather than an internal identifier. Choice `criteria` maps a name to a description. Score `criteria` is an ordered list of levels. Box and images need the header `TypeSafe-Danger-Zone-Images: true`.

## Act

Before calling the API, verify external processing is authorized for the record and send only the minimum approved fields in `state`; keep the local deterministic route for private records or anything that cannot be shared.

Act when `confidence` is available and high; check for `null` or unavailable `confidence` (such as on a Box answer) before comparing it with a threshold. A Noul has no `confidence`; use `noul`. On unavailable or low confidence, and when `TYPESAFE_API_KEY` is missing or empty, run the deterministic logic you already had. Never log the key, the `Authorization` header, or the client config.

The client sits behind a small interface. Python is `typesafe-sdk` (`TypeSafeClient` in `typesafe_sdk`); JavaScript is `@typesafe-ai/sdk` (`new TypeSafeClient()`). Pass no key: the client reads `TYPESAFE_API_KEY`. Tests use a fake of the interface and open no socket. A failed call is an error (`TypeSafeAPIError`, `status`, `request_id`), not a low-confidence answer.

```python
import os
from typesafe_sdk import Choice, TypeSafeClient

MIN_CONFIDENCE = 0.5  # tune on held-out cases

def approved_state(ticket):
    if ticket.get("allow_external") is not True:
        return None
    fields = {k: ticket[k] for k in ("title", "category") if k in ticket}
    return fields or None

class JevRouter:
    def team(self, ticket):
        state = approved_state(ticket)
        if state is None:
            return LegacyRouter().team(ticket)
        with TypeSafeClient(model="jev-latest") as client:
            answer = client.system_one(state=state, questions={
                "team": Choice(instructions="Which team should handle this ticket?",
                               criteria={"billing": "Payment", "technical": "A bug"}),
            }).answers["team"]
        if answer.confidence is None or answer.confidence < MIN_CONFIDENCE:
            return LegacyRouter().team(ticket)
        return answer.choice

def router():
    if not os.environ.get("TYPESAFE_API_KEY", "").strip():
        return LegacyRouter()
    return JevRouter()

class FakeRouter:
    def __init__(self, team): self.team_name = team
    def team(self, ticket): return self.team_name
```

## Measure

Keep the old path. On cases you did not use to write the questions, count wrong actions for both. Jev is better when that count falls. A test uses `FakeRouter` and does not assert a live probability.

**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.
