"""Setup installs a model server only after an explicit yes."""

import json
import tempfile
import unittest
from pathlib import Path

import support


class Setup(unittest.TestCase):
    def invoke(self, answers, **env):
        folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        home = folder / "home"
        home.mkdir()
        path = folder / "answers.json"
        if answers is not None:
            path.write_text(answers if isinstance(answers, str) else json.dumps(answers),
                            encoding="utf-8")
        fake, log = support.fake_env(folder, **env)
        proc = support.run(support.SETUP, ["--home", str(home), "--answers", str(path)], fake)
        return proc, home, support.calls(log)

    def test_no_does_not_install(self):
        proc, home, rows = self.invoke({"model": "no", "log": "no"})
        self.assertEqual([row["args"] for row in rows],
                         [["ghost", "--help"], ["ghost", "pair"]])
        self.assertNotIn("install", proc.stdout)
        self.assertEqual(proc.stdout,
                         "engine-ok\npaired\npairing-code: SYNTH-PAIR\nlog-off\n")
        self.assertEqual(proc.returncode, 0)
        self.assertFalse((home / "logging.on").exists())
        self.assertTrue((home / "log-asked").is_file())

    def test_yes_installs_once(self):
        proc, home, rows = self.invoke({"model": "yes", "log": "yes"})
        self.assertEqual([row["args"] for row in rows], [
            ["ghost", "--help"],
            ["ghost", "model", "install"],
            ["ghost", "pair"],
        ])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("installed\n", proc.stdout)
        self.assertTrue((home / "logging.on").is_file())

    def test_yes_with_any_other_spelling_does_not_install(self):
        for value in ("Yes", "YES", "yes ", "true", "1"):
            proc, _home, rows = self.invoke({"model": value, "log": "no"})
            self.assertEqual(rows, [], value)
            self.assertEqual(proc.stdout, "answers-refused\n")
            self.assertEqual(proc.returncode, 2)

    def test_a_repeated_yes_after_no_does_not_install(self):
        proc, _home, rows = self.invoke(
            '{"model":"no","log":"no","model":"yes"}\n')
        self.assertEqual(rows, [])
        self.assertEqual(proc.stdout, "answers-refused\n")
        self.assertEqual(proc.returncode, 2)

    def test_a_boolean_yes_does_not_install(self):
        proc, _home, rows = self.invoke('{"model":true,"log":"no"}\n')
        self.assertEqual(rows, [])
        self.assertEqual(proc.stdout, "answers-refused\n")
        self.assertEqual(proc.returncode, 2)

    def test_a_missing_answer_does_not_install(self):
        proc, _home, rows = self.invoke({"log": "no"})
        self.assertEqual(rows, [])
        self.assertEqual(proc.returncode, 2)

    def test_the_log_question_is_asked_once(self):
        folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        home = folder / "home"
        home.mkdir()
        env, log = support.fake_env(folder)
        first = folder / "first.json"
        second = folder / "second.json"
        first.write_text(json.dumps({"model": "no", "log": "no"}), encoding="utf-8")
        second.write_text(json.dumps({"model": "yes", "log": "yes"}), encoding="utf-8")
        one = support.run(support.SETUP, ["--home", str(home), "--answers", str(first)], env)
        two = support.run(support.SETUP, ["--home", str(home), "--answers", str(second)], env)
        self.assertEqual(one.stdout, "engine-ok\npaired\npairing-code: SYNTH-PAIR\nlog-off\n")
        self.assertEqual(two.stdout,
                         "engine-ok\ninstalled\npaired\npairing-code: SYNTH-PAIR\nlog-unchanged\n")
        self.assertFalse((home / "logging.on").exists())
        args = [row["args"] for row in support.calls(log)]
        self.assertEqual(args, [
            ["ghost", "--help"], ["ghost", "pair"],
            ["ghost", "--help"], ["ghost", "model", "install"], ["ghost", "pair"],
        ])
        self.assertFalse((home / "logging.on").exists())

    def test_an_existing_log_flag_is_not_deleted_when_the_answer_is_no(self):
        folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        home = folder / "home"
        home.mkdir()
        flag = home / "logging.on"
        flag.write_bytes(b"user")
        env, _log = support.fake_env(folder)
        answers = folder / "answers.json"
        answers.write_text(json.dumps({"model": "no", "log": "no"}), encoding="utf-8")
        proc = support.run(support.SETUP, ["--home", str(home), "--answers", str(answers)], env)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(flag.read_bytes(), b"user")

    def test_a_missing_engine_installs_nothing(self):
        proc, home, rows = self.invoke({"model": "yes", "log": "yes"}, FAKE_HELP="1")
        self.assertEqual([row["args"] for row in rows], [["ghost", "--help"]])
        self.assertEqual(proc.stdout, "engine-missing\n")
        self.assertEqual(proc.returncode, 1)
        self.assertFalse((home / "logging.on").exists())
        self.assertFalse((home / "log-asked").exists())

    def test_a_failed_install_does_not_pair(self):
        proc, _home, rows = self.invoke({"model": "yes", "log": "no"}, FAKE_INSTALL="1")
        self.assertEqual([row["args"] for row in rows],
                         [["ghost", "--help"], ["ghost", "model", "install"]])
        self.assertEqual(proc.stdout, "engine-ok\ninstall-failed\n")
        self.assertEqual(proc.returncode, 1)

    def test_setup_does_not_import_a_network_library(self):
        text = (support.ROOT / "scripts" / "setup.py").read_text(encoding="utf-8")
        for name in ("socket", "urllib", "http.client", "requests"):
            self.assertNotIn("import " + name, text)


if __name__ == "__main__":
    unittest.main()
