import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEARN = ROOT / "scripts" / "learn.py"
SETUP = ROOT / "scripts" / "setup.py"

FAKE = r"""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path

log = Path(os.environ["FAKE_LOG"])
args = sys.argv[1:]
skill = "absent"
home = os.environ.get("OPENWIZ_GHOST_HOME")
if home:
    path = Path(home) / "skill.json"
    try:
        skill = "new" if b"all recs" in path.read_bytes() else "old"
    except OSError:
        skill = "unreadable"
with log.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({"args": args, "skill": skill}) + "\n")
if args[:2] == ["ghost", "--help"]:
    raise SystemExit(int(os.environ.get("FAKE_HELP", "0")))
if args[:3] == ["ghost", "model", "install"]:
    raise SystemExit(int(os.environ.get("FAKE_INSTALL", "0")))
if args[:2] == ["ghost", "pair"]:
    sys.stdout.write(os.environ.get("FAKE_CODE", "SYNTH-PAIR") + "\n")
    raise SystemExit(int(os.environ.get("FAKE_PAIR", "0")))
if args[:4] == ["ghost", "bench", "--source", "sent"]:
    state = Path(os.environ["FAKE_STATE"])
    count = int(state.read_text(encoding="utf-8") or "0")
    state.write_text(str(count + 1), encoding="utf-8")
    reports = json.loads(Path(os.environ["FAKE_REPORTS"]).read_text(encoding="utf-8"))
    report = reports[count] if count < len(reports) else reports[-1]
    if isinstance(report, dict) and "exit" in report:
        raise SystemExit(int(report["exit"]))
    if isinstance(report, str):
        sys.stdout.write(report)
    else:
        sys.stdout.write(json.dumps(report) + "\n")
    raise SystemExit(0)
raise SystemExit(2)
"""

SKILL = b'{"phrases":[],"codes":[],"tone":"","never_suggest":[]}\n'
LEXICON = b'{"terms":[]}\n'
SENT = b'{"text":"J381 all recs"}\n{"text":"J381 all recs"}\n'


def report(rate, chars, source="sent"):
    shown = 10
    return {
        "schema": "openwiz.ghost.v1",
        "kind": "bench_report",
        "source": source,
        "messages": 2,
        "overall": {
            "shown": shown,
            "accepted": int(round(rate * shown)),
            "acceptance_rate": rate,
            "chars_saved_per_message": chars,
            "suggestions_per_message": 1,
            "p50_latency_ms": 4,
            "p90_latency_ms": 9,
        },
        "per_tier": [],
        "per_surface": [],
    }


def state_of(tmp):
    state = Path(tmp) / "state"
    state.mkdir(exist_ok=True)
    return state


def make_home(tmp, sent=SENT, skill=SKILL, lexicon=LEXICON, log=None, logging=False):
    home = Path(tmp) / "home"
    home.mkdir()
    (home / "skill.json").write_bytes(skill)
    (home / "lexicon.json").write_bytes(lexicon)
    (home / "sent.jsonl").write_bytes(sent)
    (home / "replay.json").write_bytes(b'{"schema":"openwiz.ghost.v1"}\n')
    ghost = state_of(tmp) / "ghost"
    ghost.mkdir(exist_ok=True)
    if logging:
        (ghost / "settings.json").write_text('{"logging":true}\n', encoding="utf-8")
    if log is not None:
        (ghost / "events.jsonl").write_bytes(log)
    return home


def fake_env(tmp, reports=None, **extra):
    folder = Path(tmp) / "bin"
    folder.mkdir()
    program = folder / "openwiz"
    program.write_text(FAKE, encoding="utf-8")
    program.chmod(0o755)
    (Path(tmp) / "reports.json").write_text(json.dumps(reports or []), encoding="utf-8")
    (Path(tmp) / "bench-count").write_text("0", encoding="utf-8")
    log = Path(tmp) / "calls.jsonl"
    log.write_text("", encoding="utf-8")
    env = os.environ.copy()
    env["PATH"] = str(folder) + os.pathsep + env.get("PATH", "")
    env["FAKE_LOG"] = str(log)
    env["FAKE_STATE"] = str(Path(tmp) / "bench-count")
    env["FAKE_REPORTS"] = str(Path(tmp) / "reports.json")
    env["OPENWIZ_STATE_DIR"] = str(state_of(tmp).resolve())
    env.update(extra)
    return env, log


def calls(log):
    text = log.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line]


def run(script, args, env):
    return subprocess.run([sys.executable, "-I", str(script), *args],
                          capture_output=True, text=True, env=env, check=False)
