---
name: role-call
description: Ping the configured channel and record who replies present. Use at the start of a grill, before any question.
version: 0.1.0
---

# Role call

Ping the people and bots in [channel.json](channel.json) and record who replies present. This skill sends nothing. The host posts.

1. Run `python3 -I "<this skill's folder>/scripts/channel.py" role-call`. Post its `text` as one message in its `channel`. Add no mention the post does not already contain.
2. Read replies to that message. Write them as a JSON list of `{"user","text"}` and run `python3 -I "<this skill's folder>/scripts/channel.py" roster --replies <file>`. A reply of `present` counts. Any other reply does not.
3. Wait while `absent` is non-empty, unless the caller marks one absent. Write the roster into the grill file under `## Present`. No grill question is asked before that section exists.

**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.
