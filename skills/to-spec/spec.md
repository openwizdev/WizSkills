# Spec issue

Title the issue `<version> spec: <name>`. Keep the confirmed decisions in the
issue body and progress in comments. Use these sections.

| Section | What goes there |
| --- | --- |
| Problem Statement | The problem in the user's terms |
| Solution | The experience the confirmed design makes possible |
| Changelog headline | One public sentence in the grill's words, or `none` for infra |
| User Stories | Numbered outcomes covering the design |
| Implementation Decisions | Shared shapes, interfaces and expected interactions, using the grill's glossary names |
| Decision tree | The grill's settled decisions, each with its source or question ID |
| Glossary | The grill's agreed names, one line each: the term, its meaning, and the meaning that was rejected |
| Parked | Questions only a prototype can answer; builders leave these unbuilt |
| Testing Decisions | User-facing seams, behavior to prove and prior art |
| Proof | Each claim and the fixture, review or live observation that proves it |
| Checkpoints | The two checkpoint answers ([checkpoints.v1](../../contracts/checkpoints.v1.md)), filled from the grill and confirmed with the spec; early only (`One-way door: yes`, `User-visible: no`) is the default |
| Live check | The smallest real check, when the spec touches the user's machine or account |
| Out of Scope | Boundaries the owner settled |
| Further Notes | Public-safe provenance; the video goes in a comment, not here |

Save the body in a file and pass it to `gh issue create --body-file` with the
confirmed tracker and milestone. The new issue has no ready label. Keep the
issue number for to-tickets and verify its milestone and body.
