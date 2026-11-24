#!/usr/bin/env python3
"""Synthetic `gh` for the inventory tests: answers `gh api` from a JSON file.

FAKE_GH_DATA names a JSON object mapping an endpoint word (`pulls`,
`milestones`, `issues`) to the list it returns, or to the string "FAIL" for a
failed read. FAKE_GH_LOG, when set, gets one line per call.
"""
import json
import os
import sys

args = sys.argv[1:]
if os.environ.get("FAKE_GH_LOG"):
    with open(os.environ["FAKE_GH_LOG"], "a", encoding="utf-8") as log:
        log.write(" ".join(args) + "\n")
with open(os.environ["FAKE_GH_DATA"], encoding="utf-8") as fh:
    data = json.load(fh)
endpoint = next((a for a in args if a.startswith("repos/")), "")
for word in ("pulls", "milestones", "issues"):
    if f"/{word}" in endpoint:
        answer = data.get(word, [])
        break
else:
    answer = []
if answer == "FAIL":
    print("gh api error: simulated offline failure", file=sys.stderr)
    sys.exit(1)
# Two pages, the way `gh api --paginate` prints them: concatenated arrays.
half = len(answer) // 2
print(json.dumps(answer[:half]))
print(json.dumps(answer[half:]))
