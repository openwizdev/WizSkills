#!/usr/bin/env python3
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jsontext
import state

LIMIT = 1_048_576
SCHEMA = "openwiz.ghost.v1"
SURFACES = {"openwiz-app", "t3-code", "bb-plugin", "cli", "other"}
TIERS = {"recall", "small_model", "draft"}
OUTCOMES = {"shown", "accepted_all", "accepted_word", "typed_through", "dismissed", "typed_over"}
ZERO_CHARS = {"shown", "dismissed", "typed_over"}
WHEN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
CODE = re.compile(r"#[0-9]+|J[0-9]+")
EVENT_KEYS = {"schema", "kind", "at", "suggestion_id", "session_id", "surface",
              "outcome", "tier", "confidence", "latency_ms", "chars_accepted"}
METRIC_KEYS = {"shown", "accepted", "acceptance_rate", "chars_saved_per_message",
               "suggestions_per_message", "p50_latency_ms", "p90_latency_ms"}
REPORT_KEYS = {"schema", "kind", "source", "messages", "overall", "per_tier", "per_surface"}
SKILL_KEYS = {"phrases", "codes", "tone", "never_suggest"}


class Refuse(Exception):
    pass


def say(word, code):
    sys.stdout.write(word + "\n")
    raise SystemExit(code)


def home_of(argv):
    if argv[1:] and argv[1] == "--home" and len(argv) == 3:
        text = argv[2]
    else:
        say("usage", 2)
    path = Path(text)
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        real = path.resolve(strict=True)
    except OSError as error:
        raise Refuse from error
    if not real.is_dir() or real.is_symlink():
        raise Refuse
    return real


def child(home, name):
    path = home / name
    if path.parent != home or path.is_symlink():
        raise Refuse
    return path


def read_file(path, required):
    if not path.exists():
        if required:
            raise Refuse
        return None
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
    except OSError as error:
        raise Refuse from error
    try:
        info = os.fstat(fd)
        if not os.path.stat.S_ISREG(info.st_mode) or info.st_size > LIMIT:
            raise Refuse
        data = os.read(fd, info.st_size)
    except OSError as error:
        raise Refuse from error
    finally:
        os.close(fd)
    try:
        return data.decode("utf-8")
    except UnicodeError as error:
        raise Refuse from error


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("not a number")
    return value


def whole(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("not a count")
    return value


def strings(value):
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError("not strings")
    if len(value) != len(set(value)):
        raise ValueError("repeated")
    return value


def skill_of(text):
    value = jsontext.load(text)
    if not isinstance(value, dict) or set(value) != SKILL_KEYS:
        raise ValueError("skill")
    strings(value["phrases"])
    strings(value["codes"])
    strings(value["never_suggest"])
    if not isinstance(value["tone"], str):
        raise ValueError("tone")
    return value


def lexicon_of(text):
    value = jsontext.load(text)
    if not isinstance(value, dict) or set(value) != {"terms"} or not isinstance(value["terms"], list):
        raise ValueError("lexicon")
    seen = set()
    for term in value["terms"]:
        if (not isinstance(term, dict) or set(term) != {"term", "meaning"}
                or not isinstance(term["term"], str) or not term["term"]
                or not isinstance(term["meaning"], str) or not term["meaning"]
                or term["term"] in seen):
            raise ValueError("term")
        seen.add(term["term"])
    return value


def messages_of(text):
    rows = []
    for line in text.splitlines():
        if not line:
            raise ValueError("blank")
        value = jsontext.load(line)
        if not isinstance(value, dict) or set(value) != {"text"} or not isinstance(value["text"], str) or not value["text"]:
            raise ValueError("message")
        rows.append(value["text"])
    if not rows:
        raise ValueError("empty")
    return rows


def event_of(line):
    value = jsontext.load(line)
    if not isinstance(value, dict) or set(value) != EVENT_KEYS:
        raise ValueError("event")
    if value["schema"] != SCHEMA or value["kind"] != "event" or not WHEN.fullmatch(value["at"]):
        raise ValueError("event")
    for key in ("suggestion_id", "session_id"):
        if not isinstance(value[key], str) or not value[key]:
            raise ValueError("event")
    if value["surface"] not in SURFACES or value["outcome"] not in OUTCOMES or value["tier"] not in TIERS:
        raise ValueError("event")
    confidence = number(value["confidence"])
    latency = number(value["latency_ms"])
    chars = whole(value["chars_accepted"])
    if not 0 <= confidence <= 1 or latency < 0:
        raise ValueError("event")
    if value["outcome"] in ZERO_CHARS and chars != 0:
        raise ValueError("event")
    return value


def rejected_of(text):
    found = []
    for line in text.splitlines():
        if not line:
            raise ValueError("blank")
        event = event_of(line)
        if event["outcome"] in {"dismissed", "typed_over"} and event["suggestion_id"] not in found:
            found.append(event["suggestion_id"])
    return found


def metrics_of(value):
    if not isinstance(value, dict) or set(value) != METRIC_KEYS:
        raise ValueError("metrics")
    shown = whole(value["shown"])
    accepted = whole(value["accepted"])
    rate = number(value["acceptance_rate"])
    saved = number(value["chars_saved_per_message"])
    each = number(value["suggestions_per_message"])
    if accepted > shown or not 0 <= rate <= 1 or saved < 0 or each < 0:
        raise ValueError("metrics")
    if shown == 0:
        if rate != 0 or value["p50_latency_ms"] is not None or value["p90_latency_ms"] is not None:
            raise ValueError("metrics")
    else:
        number(value["p50_latency_ms"])
        number(value["p90_latency_ms"])
        if value["p50_latency_ms"] < 0 or value["p90_latency_ms"] < 0:
            raise ValueError("metrics")
    return value


def report_of(text):
    value = jsontext.load(text)
    if not isinstance(value, dict) or set(value) != REPORT_KEYS:
        raise ValueError("report")
    if value["schema"] != SCHEMA or value["kind"] != "bench_report" or value["source"] != "sent":
        raise ValueError("report")
    whole(value["messages"])
    overall = metrics_of(value["overall"])
    for key, label in (("per_tier", "tier"), ("per_surface", "surface")):
        rows = value[key]
        if not isinstance(rows, list):
            raise ValueError("report")
        allowed = TIERS if label == "tier" else SURFACES
        for row in rows:
            if not isinstance(row, dict) or set(row) != {label, "metrics"} or row[label] not in allowed:
                raise ValueError("report")
            metrics_of(row["metrics"])
    return overall


def phrases_of(messages, blocked):
    counts = {}
    for text in messages:
        words = text.lower().split()
        for size in (2, 3):
            for index in range(len(words) - size + 1):
                phrase = " ".join(words[index:index + size])
                counts[phrase] = counts.get(phrase, 0) + 1
    learned = [phrase for phrase, count in counts.items() if count >= 2 and phrase not in blocked]
    return sorted(learned)[:8]


def rewrite(skill, lexicon, messages, rejected):
    blocked = set(skill["never_suggest"]) | set(rejected)
    phrases = phrases_of(messages, blocked)
    codes = list(skill["codes"])
    for text in messages:
        for code in CODE.findall(text):
            if code not in codes:
                codes.append(code)
    never = list(skill["never_suggest"])
    for item in rejected:
        if item not in never:
            never.append(item)
    tone = "short" if max(len(text) for text in messages) <= 80 else "plain"
    terms = {term["term"]: term for term in lexicon["terms"]}
    for code in codes:
        term = code[1:] if code.startswith("#") else code
        terms.setdefault(term, {"term": term, "meaning": code})
    new_skill = {"phrases": phrases, "codes": codes, "tone": tone, "never_suggest": never}
    new_lexicon = {"terms": [terms[key] for key in sorted(terms)]}
    return new_skill, new_lexicon


def dump(value):
    return (json.dumps(value, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")


def atomic(path, data):
    tmp = path.with_name("." + path.name + "." + str(os.getpid()) + ".tmp")
    if tmp.exists() or tmp.is_symlink():
        raise OSError("temp exists")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.replace(tmp, path)
    except OSError:
        os.unlink(tmp)
        raise


def bench(binary, home, replay):
    env = os.environ.copy()
    env["OPENWIZ_GHOST_HOME"] = str(home)
    try:
        proc = subprocess.run(
            [binary, "ghost", "bench", "--source", "sent", "--replay", str(replay)],
            capture_output=True, timeout=30, env=env, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Refuse from error
    if proc.returncode != 0:
        raise Refuse
    try:
        return report_of(proc.stdout.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise Refuse from error


def read_settings(root):
    path = state.settings_path(root)
    if not path.exists() or path.is_symlink() or not path.is_file():
        return ""
    try:
        return read_file(path, True) or ""
    except Refuse:
        return ""


def publish(files):
    done = []
    try:
        for path, old, new in files:
            if new != old:
                atomic(path, new)
                done.append((path, old))
    except BaseException:
        for path, old in reversed(done):
            atomic(path, old)
        raise


def dropped(before, after):
    return (after["acceptance_rate"] < before["acceptance_rate"]
            or after["chars_saved_per_message"] < before["chars_saved_per_message"])


def main(argv):
    home = home_of(argv)
    skill_path = child(home, "skill.json")
    lexicon_path = child(home, "lexicon.json")
    sent_path = child(home, "sent.jsonl")
    replay_path = child(home, "replay.json")
    skill_text = read_file(skill_path, True)
    lexicon_text = read_file(lexicon_path, True)
    sent_text = read_file(sent_path, True)
    if read_file(replay_path, True) is None:
        raise Refuse
    root = state.state_dir()
    if root is None:
        raise Refuse
    log_text = None
    if state.logging_value(read_settings(root) or "") is True:
        log_text = read_file(state.events_path(root), False)
    try:
        skill = skill_of(skill_text)
        lexicon = lexicon_of(lexicon_text)
        messages = messages_of(sent_text)
        rejected = rejected_of(log_text) if log_text is not None else []
    except ValueError as error:
        raise Refuse from error
    binary = shutil.which("openwiz")
    if not binary:
        raise Refuse
    before = bench(binary, home, replay_path)
    new_skill, new_lexicon = rewrite(skill, lexicon, messages, rejected)
    skill_bytes = skill_text.encode("utf-8")
    lexicon_bytes = lexicon_text.encode("utf-8")
    new_skill_bytes = dump(new_skill)
    new_lexicon_bytes = dump(new_lexicon)
    stage = Path(tempfile.mkdtemp(prefix=".learn-", dir=home))
    try:
        try:
            atomic(stage / "skill.json", new_skill_bytes)
            atomic(stage / "lexicon.json", new_lexicon_bytes)
            after = bench(binary, stage, replay_path)
        except (Refuse, OSError):
            say("restored", 0)
        if dropped(before, after):
            say("restored", 0)
        if (read_file(skill_path, True) != skill_text
                or read_file(lexicon_path, True) != lexicon_text):
            raise Refuse
        publish([(skill_path, skill_bytes, new_skill_bytes),
                 (lexicon_path, lexicon_bytes, new_lexicon_bytes)])
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    say("kept", 0)


if __name__ == "__main__":
    try:
        main(sys.argv)
    except (Refuse, OSError):
        say("refused", 1)
    except KeyboardInterrupt:
        say("cancelled", 130)
    except BrokenPipeError:
        raise SystemExit(1)
