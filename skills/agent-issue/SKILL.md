---
name: agent-issue
description: File an agent-native issue any repository can execute. Use when creating or updating an issue agents will carry; not for a pull request or a human conversation.
version: 0.1.0
---

# Agent issue

File one issue an agent can execute in any repository, on any forge. The fenced record is the issue. A person only needs the title.

## Guards

- One issue is one outcome. `owned_paths` is the only write boundary.
- Start work only when `ready` is `ready-for-agent`. `needs-grill` stops for a design decision. `blocked` waits on `depends`.
- `effort: large` is not `ready-for-agent`. Split it first.
- A non-empty `gates` list is a human gate. Do not pass it.
- No secrets, tokens, credentials, or private data in any field.
- A pull request is [agent-pr](../agent-pr/SKILL.md). Do not open one here.

## 1. Write

Read [spec.md](spec.md) and copy [template.md](template.md). Replace every value. Read [forges.md](forges.md) when you have not filed on this forge before.

Done when `goal` is one sentence and every acceptance item has a command.

## 2. Lint

```sh
python3 -I <installed-agent-issue>/scripts/lint.py issue --body-file body.md
```

Exit 0 prints `agent-record: ok`. Exit 1 lists findings; fix the body and run it again. Exit 2 is a bad invocation, not a bad record. Add `--json` for one JSON object on stdout.

## 3. File

Set the title to `#<id>: <summary>` when `id` is a number, otherwise `<id>: <summary>`. Use `goal` when `summary` is absent. Put the linted body in the issue description. When the forge assigns a number, set `id` to that number, lint again, and update the title.

```sh
python3 -I <installed-agent-issue>/scripts/lint.py title --title "<title>" --issue-id <id> --expect "<summary or goal>"
```

Done when the filed body lints and `ready` is the state you mean.

**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.
