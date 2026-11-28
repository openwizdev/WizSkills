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
- The state directory is the CLI's: `OPENWIZ_STATE_DIR`, else `~/Library/Application Support/openwiz` on macOS, else `$XDG_STATE_HOME/openwiz` or `~/.local/state/openwiz`. The opt-in log is `ghost/events.jsonl` under it. Read it only when `ghost/settings.json` is exactly `{"logging":true}`. `openwiz ghost forget` deletes that events file and nothing else. Do not open the network, and do not delete an events file yourself.
- Bench the rewritten `skill.json` and `lexicon.json` in a private folder beside them, and replace the live files only when that second report does not drop `acceptance_rate` or `chars_saved_per_message`. Until then the live files stay as they were; a cancelled bench leaves them too.
- A bench that fails, unreadable output, or a report that is not a ghost.v1 bench report with `source` `sent`, keeps the previous files. One key twice is a bad report.

## Setup

Ask once, write the answers, then run this from the skill folder. The file has exactly the keys `model` and `log`, each `yes` or `no`.

```sh
python3 -I scripts/setup.py --home <home> --answers <answers.json>
```

The script checks `openwiz ghost --help`, tries `openwiz ghost model install` only for `yes` (exit 2 means recall and setup continues), runs `openwiz ghost pair`, and writes `ghost/settings.json` once under the state directory.

## Learn

The skill file is the engine's: `ghost/skill.json` under the state directory, exactly `{"phrases":[...],"tone":"...","never_suggest":[...]}`, the context pack's `skill`. The lexicon is `ghost/lexicon.json` beside it, `{"terms":[{"term":"...","meaning":"..."}]}`; learned codes such as `J12` or `#42` go there. On a first run, write those two files empty. Put the user's own sent messages in `sent.jsonl` (one `{"text":"..."}` line each) and a held-out replay in `replay.json`, inside the home. Then:

```sh
python3 -I scripts/learn.py --home <home>
```

The script runs `openwiz ghost bench --source sent --replay` on `replay.json` with `OPENWIZ_GHOST_HOME` set to the live `ghost` folder, then again with it set to the staged candidate. `never_suggest` holds suggestion text: the engine drops any suggestion containing an entry, ignoring case, and the learn pass drops learned phrases the same way and keeps every entry. A ghost.v1 event line carries a suggestion id, not its text, so the learn pass checks the log only while settings say logging is on and writes nothing from it. After `forget`, the skill file holds nothing from that log.

## Verify

```sh
python3 -I -m unittest discover -s skills/ghost/tests -v
```

Fixtures prove the keep-or-restore gate and that setup installs only on an explicit yes. They do not prove a live model, a live bench, or a real pairing code.
