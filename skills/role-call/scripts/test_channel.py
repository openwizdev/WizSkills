#!/usr/bin/env python3
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHANNEL = HERE.parent / "channel.json"
SCRIPT = HERE / "channel.py"
DEFAULTS = {
    "channel_id": "C0CBXQSD6MR",
    "channel_name": "openwiz",
    "mentions": [
        {"id": "U0CBYN8JRJ9", "name": "Jake Parker"},
        {"id": "U0CEB217ZPT", "name": "jake-parker-wiz"},
    ],
}
ONE = "**G1 - Where should the draft live?** The draft contains exact replies.\n➡️ Keep it private.\n"


class Channel(unittest.TestCase):
    def run_py(self, *args, config=None):
        cmd = [sys.executable, "-I", str(SCRIPT)]
        if config is not None:
            cmd += ["--config", config]
        return subprocess.run(cmd + list(args), capture_output=True, text=True)

    def test_defaults_are_the_openwiz_channel_and_two_mentions(self):
        self.assertEqual(json.loads(CHANNEL.read_text()), DEFAULTS)

    def test_role_call_is_one_message_naming_the_config(self):
        result = self.run_py("role-call")
        self.assertEqual(result.returncode, 0, result.stderr)
        post = json.loads(result.stdout)
        self.assertEqual(post["schema"], "openwiz.channel-post.v1")
        self.assertEqual(post["kind"], "role-call")
        self.assertEqual(post["channel"], "C0CBXQSD6MR")
        self.assertIn("<@U0CBYN8JRJ9>", post["text"])
        self.assertIn("<@U0CEB217ZPT>", post["text"])
        self.assertIn("present", post["text"])
        self.assertNotIn("➡️", post["text"])

    def test_one_question_is_one_message_and_a_second_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = Path(tmp) / "q.md"
            body.write_text(ONE)
            result = self.run_py("question", "--id", "G1", "--body-file", str(body))
            self.assertEqual(result.returncode, 0, result.stderr)
            post = json.loads(result.stdout)
            self.assertEqual(post["kind"], "question")
            self.assertEqual(post["question_id"], "G1")
            self.assertEqual(post["answers_from"], "thread")
            self.assertEqual(post["text"].count("➡️"), 1)
            self.assertTrue(post["text"].startswith("<@U0CBYN8JRJ9> <@U0CEB217ZPT>\n"))
            body.write_text(ONE + "**G2 - Export?** Two formats.\n➡️ Use text.\n")
            refused = self.run_py("question", "--id", "G1", "--body-file", str(body))
            self.assertEqual(refused.returncode, 1)
            self.assertIn("one question", refused.stderr)

    def test_fleet_posts_the_question_and_does_not_take_the_thread_as_the_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = Path(tmp) / "q.md"
            body.write_text(ONE)
            result = self.run_py("question", "--id", "G1", "--body-file", str(body),
                                 "--answers", "counterpart")
            self.assertEqual(result.returncode, 0, result.stderr)
            post = json.loads(result.stdout)
            self.assertEqual(post["answers_from"], "counterpart")
            self.assertIn("visibility", post["text"])
            self.assertNotIn("Reply in this thread.", post["text"])

    def test_roster_records_who_is_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            replies = Path(tmp) / "replies.json"
            replies.write_text(json.dumps([
                {"user": "U0CBYN8JRJ9", "text": "Present."},
                {"user": "U0CEB217ZPT", "text": "later"},
                {"user": "U0000000000", "text": "present"},
            ]))
            result = self.run_py("roster", "--replies", str(replies))
            self.assertEqual(result.returncode, 0, result.stderr)
            roster = json.loads(result.stdout)
            self.assertEqual(roster["present"], ["U0CBYN8JRJ9"])
            self.assertEqual(roster["absent"], ["U0CEB217ZPT"])

    def test_summary_is_one_message_and_a_question_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = Path(tmp) / "s.md"
            body.write_text("1. Keep the draft private.\n")
            result = self.run_py("summary", "--body-file", str(body))
            self.assertEqual(result.returncode, 0, result.stderr)
            post = json.loads(result.stdout)
            self.assertEqual(post["kind"], "summary")
            self.assertEqual(post["answers_from"], "thread")
            self.assertEqual(post["text"].count("➡️"), 0)
            body.write_text(ONE)
            refused = self.run_py("summary", "--body-file", str(body))
            self.assertEqual(refused.returncode, 1)
            self.assertIn("no question", refused.stderr)

    def test_another_config_replaces_the_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "channel.json"
            cfg.write_text(json.dumps({
                "channel_id": "C0OTHER123",
                "channel_name": "other",
                "mentions": [{"id": "U0OTHER1234", "name": "Other"}],
            }))
            result = self.run_py("role-call", config=str(cfg))
            self.assertEqual(result.returncode, 0, result.stderr)
            post = json.loads(result.stdout)
            self.assertEqual(post["channel"], "C0OTHER123")
            self.assertIn("<@U0OTHER1234>", post["text"])
            self.assertNotIn("U0CBYN8JRJ9", post["text"])


if __name__ == "__main__":
    unittest.main()
