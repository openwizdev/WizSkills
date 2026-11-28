import json
import os
import sys
import tempfile
import unittest
from unittest import mock
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
        return proc, home, support.calls(log), Path(fake["OPENWIZ_STATE_DIR"])

    def test_no_does_not_install(self):
        proc, home, rows, state = self.invoke({"model": "no", "log": "no"})
        self.assertEqual([row["args"] for row in rows],
                         [["ghost", "--help"], ["ghost", "pair"]])
        self.assertNotIn("install", proc.stdout)
        self.assertEqual(proc.stdout,
                         "engine-ok\npaired\npairing-code: SYNTH-PAIR\nlog-off\n")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual((state / "ghost" / "settings.json").read_text(encoding="utf-8"),
                         '{"logging":false}\n')
        self.assertFalse((home / "logging.on").exists())
        self.assertFalse((state / "ghost" / "events.jsonl").exists())

    def test_yes_installs_once(self):
        proc, home, rows, state = self.invoke({"model": "yes", "log": "yes"})
        self.assertEqual([row["args"] for row in rows], [
            ["ghost", "--help"],
            ["ghost", "model", "install"],
            ["ghost", "pair"],
        ])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("installed\n", proc.stdout)
        self.assertEqual((state / "ghost" / "settings.json").read_text(encoding="utf-8"),
                         '{"logging":true}\n')
        self.assertFalse((home / "logging.on").exists())
        self.assertFalse((home / "log.jsonl").exists())

    def test_yes_with_any_other_spelling_does_not_install(self):
        for value in ("Yes", "YES", "yes ", "true", "1"):
            proc, _home, rows, _state = self.invoke({"model": value, "log": "no"})
            self.assertEqual(rows, [], value)
            self.assertEqual(proc.stdout, "answers-refused\n")
            self.assertEqual(proc.returncode, 2)

    def test_a_repeated_yes_after_no_does_not_install(self):
        proc, _home, rows, _state = self.invoke(
            '{"model":"no","log":"no","model":"yes"}\n')
        self.assertEqual(rows, [])
        self.assertEqual(proc.stdout, "answers-refused\n")
        self.assertEqual(proc.returncode, 2)

    def test_a_boolean_yes_does_not_install(self):
        proc, _home, rows, _state = self.invoke('{"model":true,"log":"no"}\n')
        self.assertEqual(rows, [])
        self.assertEqual(proc.stdout, "answers-refused\n")
        self.assertEqual(proc.returncode, 2)

    def test_a_missing_answer_does_not_install(self):
        proc, _home, rows, _state = self.invoke({"log": "no"})
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
        settings = Path(env["OPENWIZ_STATE_DIR"]) / "ghost" / "settings.json"
        self.assertEqual(one.stdout, "engine-ok\npaired\npairing-code: SYNTH-PAIR\nlog-off\n")
        self.assertEqual(two.stdout,
                         "engine-ok\ninstalled\npaired\npairing-code: SYNTH-PAIR\nlog-unchanged\n")
        self.assertEqual(settings.read_text(encoding="utf-8"), '{"logging":false}\n')
        self.assertFalse((home / "logging.on").exists())
        args = [row["args"] for row in support.calls(log)]
        self.assertEqual(args, [
            ["ghost", "--help"], ["ghost", "pair"],
            ["ghost", "--help"], ["ghost", "model", "install"], ["ghost", "pair"],
        ])
        self.assertFalse((home / "logging.on").exists())

    def test_an_existing_log_is_not_deleted_when_the_answer_is_no(self):
        folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        home = folder / "home"
        home.mkdir()
        env, _log = support.fake_env(folder)
        ghost = Path(env["OPENWIZ_STATE_DIR"]) / "ghost"
        ghost.mkdir()
        settings = ghost / "settings.json"
        events = ghost / "events.jsonl"
        settings.write_text('{"logging":true}\n', encoding="utf-8")
        events.write_bytes(b"keep\n")
        answers = folder / "answers.json"
        answers.write_text(json.dumps({"model": "no", "log": "no"}), encoding="utf-8")
        proc = support.run(support.SETUP, ["--home", str(home), "--answers", str(answers)], env)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("log-unchanged\n", proc.stdout)
        self.assertEqual(settings.read_text(encoding="utf-8"), '{"logging":true}\n')
        self.assertEqual(events.read_bytes(), b"keep\n")

    def test_a_missing_engine_installs_nothing(self):
        proc, home, rows, state = self.invoke({"model": "yes", "log": "yes"}, FAKE_HELP="1")
        self.assertEqual([row["args"] for row in rows], [["ghost", "--help"]])
        self.assertEqual(proc.stdout, "engine-missing\n")
        self.assertEqual(proc.returncode, 1)
        self.assertFalse((state / "ghost" / "settings.json").exists())
        self.assertFalse((home / "logging.on").exists())

    def test_a_failed_install_does_not_pair(self):
        proc, _home, rows, state = self.invoke({"model": "yes", "log": "no"}, FAKE_INSTALL="1")
        self.assertEqual([row["args"] for row in rows],
                         [["ghost", "--help"], ["ghost", "model", "install"]])
        self.assertEqual(proc.stdout, "engine-ok\ninstall-failed\n")
        self.assertEqual(proc.returncode, 1)
        self.assertFalse((state / "ghost" / "settings.json").exists())

    def test_a_missing_model_command_falls_back_to_recall(self):
        proc, home, rows, state = self.invoke({"model": "yes", "log": "no"}, FAKE_INSTALL="2")
        self.assertEqual([row["args"] for row in rows], [
            ["ghost", "--help"],
            ["ghost", "model", "install"],
            ["ghost", "pair"],
        ])
        self.assertEqual(proc.stdout,
                         "engine-ok\nmodel-absent\npaired\npairing-code: SYNTH-PAIR\nlog-off\n")
        self.assertEqual(proc.returncode, 0)
        self.assertFalse((home / "logging.on").exists())
        self.assertEqual((state / "ghost" / "settings.json").read_text(encoding="utf-8"),
                         '{"logging":false}\n')

    def test_setup_creates_a_missing_state_directory(self):
        folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        fresh = folder / "fresh" / "openwiz"
        proc, _home, _rows, state = self.invoke({"model": "no", "log": "yes"},
                                                OPENWIZ_STATE_DIR=str(fresh))
        self.assertEqual(state, fresh)
        self.assertEqual(proc.stdout,
                         "engine-ok\npaired\npairing-code: SYNTH-PAIR\nlog-on\n")
        self.assertEqual((fresh / "ghost" / "settings.json").read_text(encoding="utf-8"),
                         '{"logging":true}\n')
        self.assertEqual(proc.returncode, 0)

    def test_setup_does_not_import_a_network_library(self):
        text = (support.ROOT / "scripts" / "setup.py").read_text(encoding="utf-8")
        for name in ("socket", "urllib", "http.client", "requests"):
            self.assertNotIn("import " + name, text)



class StateDirectory(unittest.TestCase):
    def resolve(self, platform, **env):
        sys.path.insert(0, str(support.ROOT / "scripts"))
        try:
            import state
        finally:
            sys.path.pop(0)
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(sys, "platform", platform):
            return state.state_dir()

    def test_macos_uses_application_support_like_the_cli(self):
        self.assertEqual(
            self.resolve("darwin", HOME="/synthetic/home", XDG_STATE_HOME="/synthetic/xdg"),
            Path("/synthetic/home/Library/Application Support/openwiz"))

    def test_linux_uses_the_xdg_state_home(self):
        self.assertEqual(
            self.resolve("linux", HOME="/synthetic/home", XDG_STATE_HOME="/synthetic/xdg"),
            Path("/synthetic/xdg/openwiz"))
        self.assertEqual(self.resolve("linux", HOME="/synthetic/home", XDG_STATE_HOME="rel"),
                         Path("/synthetic/home/.local/state/openwiz"))

    def test_the_override_wins_on_every_platform_and_must_be_absolute(self):
        for platform in ("darwin", "linux"):
            self.assertEqual(self.resolve(platform, HOME="/synthetic/home",
                                          OPENWIZ_STATE_DIR="/synthetic/state"),
                             Path("/synthetic/state"))
            self.assertIsNone(self.resolve(platform, HOME="/synthetic/home",
                                           OPENWIZ_STATE_DIR="relative/state"))
        self.assertIsNone(self.resolve("darwin", HOME="relative"))


if __name__ == "__main__":
    unittest.main()
