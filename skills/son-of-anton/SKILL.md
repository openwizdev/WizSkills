---
name: son-of-anton
description: Attack your own factory on a schedule through huntr's attack mode and file what is proven. Use when the Son of Anton loop fires, or when someone asks to attack or red-team their own factory. Small code fixes are huntr; one known bug is diagnose.
version: 0.1.0
---

# son-of-anton

Thin entry point for [huntr's attack mode](../huntr/attack.md). It adds no scripts or rules of its own: every guard, script and form stays in `huntr`.

1. **Run.** One invocation is one attack run. Read [huntr's attack mode](../huntr/attack.md) and follow it.
2. **Settings.** Before the first run, check the project's `docs/agents/huntr.md`:
   ```sh
   node <installed-son-of-anton>/../huntr/scripts/targets.mjs list docs/agents/huntr.md
   ```
   A refusal (exit 2) means the attack settings are missing or wrong: write them with the user, with only the project's own targets, and never guess.
3. **Loop.** Created once per factory and never from a run:
   ```sh
   room-cli loop create --name "Son of Anton" --cron '0 */6 * * *' --new-thread \
     --provider <controller provider> --model <controller model> --reasoning <effort> \
     --prompt "Run son-of-anton: read <installed-son-of-anton>/SKILL.md and follow it."
   ```
   On another host, use any scheduler that starts a fresh agent with that prompt.
4. **Done when** the run's record is on the attack record issue and the controller has archived itself.

**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.
