#!/usr/bin/env python3
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jsontext

ANSWERS = ("yes", "no")
CODE = re.compile(r"^[A-Za-z0-9-]{4,80}$")
LIMIT = 1_048_576


def fail(word, code):
    sys.stdout.write(word + "\n")
    raise SystemExit(code)


def take(argv):
    home = answers = None
    index = 1
    while index < len(argv):
        flag, index = argv[index], index + 1
        if flag not in ("--home", "--answers") or index >= len(argv):
            fail("usage", 2)
        value = argv[index]
        index += 1
        if flag == "--home":
            if home is not None:
                fail("usage", 2)
            home = value
        else:
            if answers is not None:
                fail("usage", 2)
            answers = value
    if home is None or answers is None:
        fail("usage", 2)
    return home, answers


def directory(text):
    path = Path(text)
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        real = path.resolve(strict=True)
    except OSError:
        fail("home-refused", 2)
    if not real.is_dir() or real.is_symlink():
        fail("home-refused", 2)
    return real


def regular(path):
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if not os.path.stat.S_ISREG(info.st_mode) or info.st_size > LIMIT:
            return None
        return os.read(fd, info.st_size).decode("utf-8")
    except (OSError, UnicodeError):
        return None
    finally:
        os.close(fd)


def answers_of(path):
    text = regular(path)
    if text is None:
        fail("answers-refused", 2)
    try:
        value = jsontext.load(text)
    except ValueError:
        fail("answers-refused", 2)
    if not isinstance(value, dict) or set(value) != {"model", "log"}:
        fail("answers-refused", 2)
    if value["model"] not in ANSWERS or value["log"] not in ANSWERS:
        fail("answers-refused", 2)
    return value["model"], value["log"]


def openwiz():
    found = shutil.which("openwiz")
    if not found:
        return None
    return found


def run(binary, args, home):
    env = os.environ.copy()
    env["OPENWIZ_GHOST_HOME"] = str(home)
    try:
        return subprocess.run([binary, *args], capture_output=True, text=True,
                              timeout=30, env=env, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None


def marker(home, name):
    path = home / name
    if path.is_symlink():
        fail("home-refused", 2)
    return path


def main(argv):
    home_text, answers_text = take(argv)
    model, log = answers_of(Path(answers_text))
    home = directory(home_text)
    binary = openwiz()
    if binary is None:
        fail("engine-missing", 1)
    helped = run(binary, ["ghost", "--help"], home)
    if helped is None or helped.returncode != 0:
        fail("engine-missing", 1)
    sys.stdout.write("engine-ok\n")
    if model == "yes":
        installed = run(binary, ["ghost", "model", "install"], home)
        if installed is None or installed.returncode != 0:
            fail("install-failed", 1)
        sys.stdout.write("installed\n")
    paired = run(binary, ["ghost", "pair"], home)
    if paired is None or paired.returncode != 0:
        fail("pair-failed", 1)
    code = paired.stdout.strip()
    if not CODE.fullmatch(code) or "\n" in paired.stdout.strip("\n"):
        fail("pair-failed", 1)
    sys.stdout.write("paired\n")
    sys.stdout.write("pairing-code: " + code + "\n")
    asked = marker(home, "log-asked")
    flag = marker(home, "logging.on")
    if flag.is_symlink() or (flag.exists() and not flag.is_file()):
        fail("home-refused", 2)
    if asked.exists():
        sys.stdout.write("log-unchanged\n")
        return 0
    if log == "yes" and not flag.exists():
        fd = os.open(flag, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
    asked_fd = os.open(asked, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(asked_fd)
    sys.stdout.write("log-on\n" if log == "yes" else "log-off\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except BrokenPipeError:
        raise SystemExit(1)
