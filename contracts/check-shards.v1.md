# WizSkills check shards contract, version 1 (`openwiz.check-shards.v1`)

WizSkills' check (`python3 check/run.py`) can list and run named slices of itself, so CI can spread it over parallel jobs without losing a suite. This contract fixes what a shard is, the `--list` output, the `--shard` run and what a plain run still does.

**Contract first** (WQ1, openwizdev/OpenWiz#2270, of spec openwizdev/OpenWiz#2134). WQ2 (#2271) adds numbered part shards for the long `test.sh` suites, WQ3 (#2272) runs one CI job per listed shard, and WQ4 (#2274) selects a pull request's shards. Each builds on the words and shapes below.

## Words

| Word | Meaning here |
| --- | --- |
| **Suite** | One command in `SUITES` in `check/run.py`: a skill's (or the check's own) test entrypoint, run from the tree's root. |
| **Shard** | A named slice of the check: `rules`, `standalone`, one skill's suites, or a numbered part of one long suite. |
| **Plain run** | `python3 check/run.py` with no arguments: every shard, in list order. |
| **Inventory guard** | The check that every test file in the tree is run by some suite; an unlisted one fails the run. |

## The shards

In list order:

1. `rules`: the skill rules, run inside `check/run.py`. Its `commands` is empty.
2. `standalone`: `python3 -I check/standalone.py --tree .`.
3. One shard for each `SUITES` row, in `SUITES` order, named after the row (a skill's name, or `check` for the check's own tests), holding that row's commands in order.

A **part shard** (WQ2) replaces one suite in its row's shard: it is named `<row>.<n>`, `n` counting from 1, and carries the part in `env` (launch-fleet's `TEST_SHARD`, for example). A dot never appears in a skill name, so a part name never collides with a row name. Together the parts of a suite run exactly the cases the whole suite runs. No part shard exists in version 1's code.

**Coverage.** Every suite (a command's `suite`) is in exactly one shard, apart from a split suite, which is in each of its part shards, and only there. A test (`check/test_suites.py`) compares `--list` with `SUITES` and fails when a suite is in no shard or in two.

## `--list`

`python3 check/run.py --list` prints the shards as one JSON array on stdout and exits 0. It runs no suite, but it runs the inventory guard first: while a test file is unlisted, or a listed suite's file or the huntr consumer is missing, it prints each guard line a run would print (`suite inventory: <path>: unlisted`, `suite <row>: <suite>: missing`, `suite huntr: synthetic consumer missing`) on stderr, prints no JSON and exits 1, so a job matrix never builds from a list that misses a test. Each element is an object with exactly these keys:

| Key | Value |
| --- | --- |
| `name` | The shard's name: `rules`, `standalone`, a `SUITES` row, or `<row>.<n>` |
| `skill` | The `SUITES` row the shard belongs to, or `null` for `rules` and `standalone` |
| `commands` | The commands it runs, in order, each a command object (below) |
| `env` | Extra environment for every command in the shard, a string-to-string object; `{}` unless it is a part shard |

```json
[
  {"name": "rules", "skill": null, "commands": [], "env": {}},
  {"name": "standalone", "skill": null, "commands": [{"suite": ["python3", "-I", "check/standalone.py", "--tree", "."], "argv": ["python3", "-I", "check/standalone.py", "--tree", "."], "cwd": "."}], "env": {}},
  {"name": "alpha", "skill": "alpha", "commands": [{"suite": ["python3", "-I", "skills/alpha/test/test_alpha.py"], "argv": ["python3", "-I", "-c", "<runner>", "skills/alpha/test", "test_alpha.py"], "cwd": "."}], "env": {}},
  {"name": "huntr", "skill": "huntr", "commands": [{"suite": ["sh", "skills/huntr/scripts/test.sh"], "argv": ["sh", "../../../skills/huntr/scripts/test.sh"], "cwd": "check/fixtures/huntr-project"}], "env": {}}
]
```

Each command object has exactly these keys:

| Key | Value |
| --- | --- |
| `suite` | The suite as written in its `SUITES` row (for `standalone`, the same as `argv`) |
| `argv` | The exact command `run.py` executes for it, an array of strings, runnable verbatim from `cwd`; `python3` stands for a Python 3.11+ interpreter (standalone's `--tree .` names the same tree as the absolute root `run.py` passes) |
| `cwd` | The folder it runs in, relative to the tree's root: `.` for every suite but huntr's, which runs from its synthetic consumer `check/fixtures/huntr-project` with its script path relative to that folder |

`argv` differs from `suite` where `run.py` adds context: a Python file holding `unittest` test cases, and a `-m unittest discover` folder, run through the check's collection runner (`python3 -I -c <runner> <folder> <pattern>`), which fails a file that collects no test; huntr's script runs from its consumer folder. Both a plain run and `--list` build `argv` and `cwd` with the same function, so what `--list` shows is what a run executes. `run.py` runs every command with `GH_TOKEN`, `GITHUB_TOKEN`, `TEST_ONLY`, `TEST_EXPECTED`, `TEST_PASS`, `TEST_WORKER` and `LIST_CASES` removed from the environment, plus the shard's `env`.

(Synthetic: `alpha` stands for any skill; `<runner>` for the collection runner's code.)

## `--shard`

`python3 check/run.py --shard <name>[,<name>...]` runs only the named shards, in list order whatever order they are given in, each once.

- Its output lines are a plain run's lines for those shards: `rules:` lines only with `rules`, the `standalone:` line only with `standalone`, and each selected suite's `running` and result lines.
- The inventory guard runs in every mode, `--list` included, whichever shards are named: an unlisted test file fails the run.
- The last line is `check: pass` or `check: fail`; it exits 0 when everything it ran passed and the guard found nothing, else 1.
- Running every shard by name runs the same commands, in the same order, with the same lines, as a plain run.

## A plain run

Unchanged, apart from each suite's result line, which now ends with that suite's elapsed seconds, to one decimal place:

```text
suite alpha: python3 -I skills/alpha/test/test_alpha.py: running
suite alpha: python3 -I skills/alpha/test/test_alpha.py: pass in 12.3s
suite alpha: python3 -I skills/alpha/test/test_beta.py: fail (1) in 0.4s
```

The `rules:`, `standalone:`, inventory, `missing`, `cannot start` and `check:` lines are as before.

## Exit codes and refusals

| Exit | When |
| --- | --- |
| 0 | `--list`, or a run where everything selected passed |
| 1 | A run where something failed or is missing, or the inventory guard found an unlisted test (in `--list` too) |
| 2 | Bad arguments: an unknown shard name, an empty name (`--shard ''`, `--shard a,`), `--shard` with no value, `--list` with anything else, or any other argument. It prints the reason on stderr and runs nothing. |

## Versioning

A change to a key, a name form, the list order, an output line or an exit code is a new version of this contract. Adding, removing or splitting shards is not: `--list` is the source of truth for which shards exist.
