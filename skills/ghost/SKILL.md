---
name: ghost
description: Set up ghost text on this machine and learn phrases from what you send, keeping a change only when the bench does not drop.
version: 0.1.0
---

# Ghost

The per-user brain for ghost text. Setup runs on this machine. The learn pass runs while the user's own agent is idle. A fixture run is not a live bench and not a live pairing.

**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.

## Guards

- Install a model server only when the answers file says `model` is exactly `yes`. Any other value, including a repeated key, installs nothing. If `openwiz ghost model install` exits 2, that command is absent: continue, and ghost text stays on recall.
- The opt-in log is `ghost/events.jsonl` under the state directory (`OPENWIZ_STATE_DIR`, else `$XDG_STATE_HOME/openwiz` or `~/.local/state/openwiz`). Read it only when `ghost/settings.json` is exactly `{"logging":true}`. `openwiz ghost forget` deletes that events file and nothing else. Do not open the network, and do not delete an events file yourself.
- After rewriting `skill.json` and `lexicon.json`, keep them only when a second bench report does not drop `acceptance_rate` or `chars_saved_per_message`. Otherwise restore the previous bytes.
- A bench that fails, or a report that is not a ghost.v1 bench report with `source` `sent`, restores those bytes. One key twice is a bad report.

## Setup

Ask once, write the answers, then run this from the skill folder. The file has exactly the keys `model` and `log`, each `yes` or `no`.

```sh
python3 -I scripts/setup.py --home <home> --answers <answers.json>
```

The script checks `openwiz ghost --help`, tries `openwiz ghost model install` only for `yes` (exit 2 means recall and setup continues), runs `openwiz ghost pair`, and writes `ghost/settings.json` once under the state directory.

## Learn

Put the user's own sent messages in `sent.jsonl` (one `{"text":"..."}` line each), the skill file in `skill.json`, the lexicon in `lexicon.json`, and a held-out replay in `replay.json`, all inside the home. Then:

```sh
python3 -I scripts/learn.py --home <home>
```

The script runs `openwiz ghost bench --source sent --replay` on `replay.json` before the rewrite and again after it, with `OPENWIZ_GHOST_HOME` set to that home. The report is the ghost.v1 bench report. `skill.json` holds `phrases`, `codes`, `tone` and `never_suggest`. A dismissal or typed-over line in `ghost/events.jsonl` adds its suggestion id to `never_suggest` only while settings say logging is on. After `forget`, that file is gone and those rejections are not read again.

## Verify

```sh
python3 -I -m unittest discover -s skills/ghost/tests -v
```

Fixtures prove the keep-or-restore gate and that setup installs only on an explicit yes. They do not prove a live model, a live bench, or a real pairing code.
