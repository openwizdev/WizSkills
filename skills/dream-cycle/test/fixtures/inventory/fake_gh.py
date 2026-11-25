#!/usr/bin/env python3
import json
import os
import subprocess
import sys

args = sys.argv[1:]
if os.environ.get("FAKE_GH_LOG"):
    with open(os.environ["FAKE_GH_LOG"], "a", encoding="utf-8") as log:
        log.write(" ".join(args) + "\n")
if args[:2] == ["repo", "clone"] and os.environ.get("FAKE_GH_CLONE_SOURCE"):
    dest = args[3]
    extra = args[5:] if len(args) > 4 and args[4] == "--" else []
    res = subprocess.run(["git", "clone", *extra, os.environ["FAKE_GH_CLONE_SOURCE"], dest],
                         capture_output=True, text=True)
    if res.returncode != 0:
        sys.stderr.write(res.stderr)
        sys.exit(res.returncode)
    sys.exit(0)
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
half = len(answer) // 2
print(json.dumps(answer[:half]))
print(json.dumps(answer[half:]))
