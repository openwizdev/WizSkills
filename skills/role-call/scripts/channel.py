#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path

SCHEMA = "openwiz.channel-post.v1"
QUESTION = re.compile(r"[A-Z]{1,2}[1-9][0-9]*")
HEAD = re.compile(r"\*\*([A-Z]{1,2}[1-9][0-9]*) - ")
ARROW = "➡️ "


def fail(reason):
    raise SystemExit("channel: " + reason)


def load(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        fail("config is unreadable")
    if not isinstance(data, dict):
        fail("config is not an object")
    channel = data.get("channel_id")
    mentions = data.get("mentions")
    if not isinstance(channel, str) or not re.fullmatch(r"C[A-Z0-9]+", channel):
        fail("channel_id is missing")
    if not isinstance(mentions, list) or not mentions:
        fail("mentions are missing")
    ids = []
    for item in mentions:
        if not isinstance(item, dict):
            fail("a mention is not an object")
        uid, name = item.get("id"), item.get("name")
        if not isinstance(uid, str) or not re.fullmatch(r"U[A-Z0-9]+", uid):
            fail("a mention id is missing")
        if not isinstance(name, str) or not name.strip():
            fail("a mention name is missing")
        if uid in ids:
            fail("a mention is repeated")
        ids.append(uid)
    return channel, ids


def emit(payload):
    json.dump(payload, sys.stdout, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write("\n")


def question(channel, ids, args):
    if not QUESTION.fullmatch(args.id):
        fail("question id is unreadable")
    if args.answers not in ("thread", "counterpart"):
        fail("answers must be thread or counterpart")
    try:
        body = Path(args.body_file).read_text(encoding="utf-8").strip("\n")
    except (OSError, UnicodeError):
        fail("question is unreadable")
    if not body.strip():
        fail("question is empty")
    if body.count(ARROW) != 1 or HEAD.findall(body) != [args.id]:
        fail("a message holds one question")
    tail = ("Reply in this thread." if args.answers == "thread"
            else "Posted for visibility. The counterpart answers this question.")
    text = " ".join(f"<@{uid}>" for uid in ids) + "\n" + body + "\n" + tail
    emit({"schema": SCHEMA, "kind": "question", "channel": channel,
          "question_id": args.id, "answers_from": args.answers, "text": text})


def summary(channel, ids, body_file):
    try:
        body = Path(body_file).read_text(encoding="utf-8").strip("\n")
    except (OSError, UnicodeError):
        fail("summary is unreadable")
    if not body.strip() or ARROW in body or HEAD.search(body):
        fail("summary is one message and holds no question")
    text = " ".join(f"<@{uid}>" for uid in ids) + "\n" + body + "\nReply in this thread if this is aligned."
    emit({"schema": SCHEMA, "kind": "summary", "channel": channel,
          "answers_from": "thread", "text": text})


def role_call(channel, ids):
    text = " ".join(f"<@{uid}>" for uid in ids) + "\nRole call. Reply to this message with present."
    emit({"schema": SCHEMA, "kind": "role-call", "channel": channel, "text": text})


def present_word(text):
    return text.strip().lower().removesuffix(".") == "present"


def roster(ids, path):
    try:
        rows = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        fail("replies are unreadable")
    if not isinstance(rows, list):
        fail("replies are not a list")
    present = []
    for row in rows:
        if not isinstance(row, dict):
            fail("a reply is not an object")
        user, text = row.get("user"), row.get("text")
        if not isinstance(user, str) or not isinstance(text, str):
            fail("a reply needs user and text")
        if user in ids and present_word(text) and user not in present:
            present.append(user)
    emit({"schema": SCHEMA, "kind": "roster", "present": present,
          "absent": [uid for uid in ids if uid not in present]})


def main(argv):
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(prog="channel.py")
    parser.add_argument("--config", default=str(here.parent / "channel.json"))
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("role-call")
    ask = sub.add_parser("question")
    ask.add_argument("--id", required=True)
    ask.add_argument("--body-file", required=True)
    ask.add_argument("--answers", default="thread")
    done = sub.add_parser("summary")
    done.add_argument("--body-file", required=True)
    listed = sub.add_parser("roster")
    listed.add_argument("--replies", required=True)
    args = parser.parse_args(argv)
    channel, ids = load(args.config)
    if args.cmd == "role-call":
        role_call(channel, ids)
    elif args.cmd == "question":
        question(channel, ids, args)
    elif args.cmd == "summary":
        summary(channel, ids, args.body_file)
    else:
        roster(ids, args.replies)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
