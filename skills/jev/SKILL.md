---
name: jev
description: "Reach for TypeSafe Jev for a typed judgment: prompt-and-parse, keyword or regex matching, brittle heuristics, routing, classification, or a done, safe, or which-one call."
version: 0.1.0
---

# Jev

Jev is TypeSafe's System One model. Send a state and typed questions; the response is structured answers your code can branch on. It does not write text. The live docs are the API: [docs](https://docs.typesafe.ai), [models](https://docs.typesafe.ai/models), and the index at [llms.txt](https://docs.typesafe.ai/llms.txt) (append `.md` to a page path for Markdown). Where this skill and the docs disagree, follow the docs, and leave out any request or response field they do not list.

Call `POST https://api.typesafe.ai/v1/systemone` with `Authorization: Bearer` the key and `Content-Type: application/json`. The body is `model`, `state`, and `questions`. `GET https://api.typesafe.ai/v1/models` lists the names this key can send. Send `jev-latest` unless thresholds were tuned on one release; then send that version id, such as `jev-1.14.0`, and change it when you mean to. Log the response `model`, which is the version that answered.

## When to use it

Use Jev when the step is a judgment over language or an image and the code will branch on a typed answer:

- a prompt whose reply you then parse
- keyword or regex matching on what the words mean
- a heuristic that breaks when the wording changes
- routing or classification into a list you already have
- which model should handle this ticket, from a list you supply
- whether something is done, whether it is safe, or which one of a fixed set it is

Choice returns `choice`, `probabilities`, and `confidence`. Score returns `score`, `legend`, `probabilities`, and `confidence`. Noul returns `noul`, the probability the statement is true, from 0 to 1, and no separate confidence. Box returns `box.top`, `box.bottom`, `box.left`, and `box.right`, each a fraction from 0 to 1, plus `confidence`. Box needs a model that lists it (Jev 1.14) and the header `TypeSafe-Danger-Zone-Images: true`.

## When not to use it

Leave the step in ordinary code when the code can already decide: arithmetic, an exact lookup, dates, or a policy applied as written. Leave it to an LLM when you need text, code, or an explanation. Jev is not the model that drives a coding agent.

Ask Jev for the judgments, and write the decision in code. "Should this be escalated?" is the decision. "Does the customer ask for a refund?" and "How urgent is `message`?" are the judgments.

A Choice always returns one option, and a Box always returns a box. When nothing may fit, add a Noul in the same request that asks whether anything fits, and read the Choice or the Box only when that Noul says yes.

Audio and video are not inputs. Images are PNG or JPEG assets, and those requests send `TypeSafe-Danger-Zone-Images: true`. The API rejects WebP and GIF.

## Questions and state

One question is one snap judgment: a person with only this state could answer it in a few seconds. Put the whole question in `instructions`. The question id is for your code; it is not sent to the model.

`state` is a string, an object, or an array. Use an object with named fields when there is more than one part. Point a question at a field with its path in backticks, such as `ticket.messages[0].text`. Include the facts a person would need, including facts the code already computed. Leave out fields no question uses.

Choice `criteria` is a map of option name to a description, or `null`. The name should say what the option is (`billing`, `technical`), and each description should stand on its own. Score `criteria` is an ordered list of levels, each a situation. Phrase a Noul so that yes is the case you care about.

Send every question that shares a state in one request. They run in parallel, each against that state alone, and they do not see each other's answers. Make a second request when the next state or the next options depend on an answer. Long context is the header `TypeSafe-Danger-Zone-Long-Context: true` on the requests that need it; the models page has the limits, and the header is slower and less accurate, so leave it off unless the state needs it.

Keep the question text, the criteria, and the thresholds in one module.

## Integrate

Hide the client behind a small interface that returns the decision the rest of the code needs. The TypeSafe client is one implementation. Tests pass a fake of that interface, including the low-probability case. Those tests do not open a socket and do not read a key.

The Python SDK is `typesafe-sdk` (`TypeSafeClient` and `AsyncTypeSafeClient` in `typesafe_sdk`). The JavaScript SDK is `@typesafe-ai/sdk` (`TypeSafeClient`, `choice`, `noul`, `score`, `box`). Construct the client with no key argument so it reads `TYPESAFE_API_KEY`. When that variable is missing or empty, call the old logic and skip the client. Never write the key, the `Authorization` header, or the client config into logs, errors, traces, or fixtures. On a failed call, surface the error (`TypeSafeAPIError` in Python, with `status` and `request_id`). A failure is not a "no", and it does not silently run the old logic.

```python
import os
from typesafe_sdk import Choice, TypeSafeClient

class Router:
    def team(self, ticket: str) -> str:
        raise NotImplementedError

class JevRouter:
    def team(self, ticket: str) -> str:
        with TypeSafeClient(model="jev-latest") as client:
            response = client.system_one(
                state=ticket,
                questions={
                    "team": Choice(
                        instructions="Which team should handle this ticket?",
                        criteria={
                            "billing": "Payment or a subscription",
                            "technical": "A bug or an integration",
                        },
                    ),
                },
            )
        chosen = response.answers["team"]
        if chosen.probabilities[chosen.choice] < 0.67:
            return "unsure"
        return chosen.choice

def router() -> Router:
    if not os.environ.get("TYPESAFE_API_KEY", "").strip():
        return LegacyRouter()
    return JevRouter()

class FakeRouter:
    def __init__(self, team: str) -> None:
        self.team_name = team

    def team(self, ticket: str) -> str:
        return self.team_name
```

The same body over HTTP is `{"model":"jev-latest","state":"<ticket>","questions":{"team":{"type":"choice","instructions":"Which team should handle this ticket?","criteria":{"billing":"Payment or a subscription","technical":"A bug or an integration"}}}}`. In JavaScript, `new TypeSafeClient({ defaultModel: "jev-latest" })` and `client.systemOne({ state, questions })`, then `response.answers.team.choice`.

`0.67` is the confidence page's example of a floor under which the chosen option goes to a person. Raise it when the action is costly; that page's high-stakes example waits for a probability above `0.93`. A Noul starts at above `0.7` for yes and below `0.3` for no, and the band between has its own outcome. A Score whose `confidence` is below `0.5` is that page's example of an unclear score. Each number is a starting point to measure on your cases.

## Measure

Keep the old path. Label a set of cases with the decision you want, including cases the old path gets wrong and cases it gets right, and hold some back while you write the questions. Run both paths on the held-out cases. Count wrong actions, and count the abstain band on its own. Record the response `model`. Change one of the wording, the state, or a threshold, then run the held-out cases again. The step is better when those cases have fewer wrong actions and the band is handled on purpose. A test of your code uses the fake. It does not assert an exact live probability.

**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.
