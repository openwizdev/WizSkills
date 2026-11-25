import os
from pathlib import Path

ON = '{"logging":true}'
OFF = '{"logging":false}'


def _absolute(path):
    return path.is_absolute() and ".." not in path.parts


def state_dir():
    raw = os.environ.get("OPENWIZ_STATE_DIR", "")
    if raw:
        path = Path(raw)
        return path if _absolute(path) else None
    home = os.environ.get("HOME", "")
    if not home or not _absolute(Path(home)):
        return None
    xdg = os.environ.get("XDG_STATE_HOME", "")
    if xdg and _absolute(Path(xdg)):
        base = Path(xdg)
    else:
        base = Path(home) / ".local" / "state"
    return base / "openwiz"


def settings_path(state):
    return state / "ghost" / "settings.json"


def events_path(state):
    return state / "ghost" / "events.jsonl"


def logging_value(text):
    compact = "".join(text.split())
    if compact == ON:
        return True
    if compact == OFF:
        return False
    return None
