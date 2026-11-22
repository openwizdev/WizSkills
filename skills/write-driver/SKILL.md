---
name: write-driver
description: Take a user from one pasted line to an OpenWiz driver of their own that passes 5 of 5 on their real host, as fast as possible. Reads the host's own help first, grills in rounds of three, writes the driver from OpenWiz's template, runs the five-check kit and the three live lessons with the user, opens a pull request in their repository, stops everything it started, reports the time from paste, and shares it only on the user's yes. Use when the user pastes "Write an OpenWiz driver for my host with the write-driver skill" or asks to write a driver for a host.
version: 0.3.0
---

# Write a driver

The user pasted this line into their agent:

> Write an OpenWiz driver for my host with the write-driver skill: https://github.com/openwizdev/WizSkills/tree/main/skills/write-driver

Take them from it to a driver that passes, end to end. Every exact text you say or write comes from the [write-driver contract](../../contracts/write-driver.v1.md), through this skill's script; never type one by hand. Pin a private state folder outside any repository (`<state>`), then:

`W="python3 -I <this skill's folder>/scripts/write_driver.py"`. Exit 1 is a refusal whose last line says why, or a failed kit check; exit 2, the kit could not run; exit 3, a step skipped on the user's no.

**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.

## Guards

- **Never a login or key.** Never ask for, read, print, store or pass a login, token, key, password, secret or cookie, for the host, the harness or GitHub. Use only the user's own signed-in tools (`gh`, the host's CLI, the harness). `$W ask` refuses an ask that names one.
- **Sign-in is the user's.** When a real first turn ends on an expired sign-in, say what `$W sign-in --state <state> --harness <harness>` prints, wait for `done`, and never handle the sign-in yourself.
- **Ask before every step that could cost money or start a machine**: each host command that creates a machine, sandbox or paid run, each kit run against such a host, each lesson that starts one. Say what `$W ask --state <state> --operation <kit|expired-login|host> [--step "<the one host step, plain words>"] --effect "<cost money|start a machine|cost money and start a machine>"` prints, end your turn, write the user's next message to a private file and run `$W reply --state <state> --file <file>`; pass the ask's id as `--asked` to that same step (`kit` and `expired-login` refuse an ask for another step; a `host` step you run yourself only after `reply` printed `yes`). One ask covers one step. Only a plain yes goes ahead; on anything else the step is skipped and reads `not run`. A step that can do neither runs without asking.
- **Stop everything you start.** Record each driver run (`$W started run --state <state> --driver <driver> --run <id>`) and each machine, sandbox or process (`$W started add --state <state> --what "<what>" -- <its stop command>`) as you start it.

## 1. Paste and grill

1. At paste, before anything else: `$W begin --state <state>`. The clock starts now.
2. Read before asking: the host's own `--help` for each command it has, and its docs. Ask only what you can't find.
3. Grill in rounds of three questions, each with your recommendation, until the driver is clear; no cap, never a padded question. Settle: the host's folder name; how a turn starts, how you tell it still runs, and how it ends; which steps cost money or start a machine; the harness the user runs; the user's own repository for the driver.
4. `$W host --state <state> --host <host> --costly <yes|no>`: `yes` when any step costs money or starts a machine.

## 2. Write

1. Clone OpenWiz into a private temporary folder: `git clone --depth 1 https://github.com/openwizdev/OpenWiz <openwiz>`.
2. `$W copy --state <state> --openwiz <openwiz> --into <the user's repository> --login <machine|host> [--key-variable <NAME>]`: `adapters/<host>/`, renamed for the host. It never overwrites. Its `README.md` opens, right under its title, with driver v1's login line: `--login machine` writes `Login: stays on your machine` (the host's signed-in tools run on the user's machine), `--login host` writes `Login: held by <host>` (a cloud host holds the login). For a cloud host that takes an API key, add `--key-variable <NAME>`: the README then names the variable the user sets for it, under that line. Pass its name only, never a value: 2 to 6 words of 1 to 16 capitals or digits joined by `_`, the first starting with a letter (`EXAMPLEHOST_API_KEY`). `copy` refuses anything else, and anything the kit's credential check flags, without repeating what it was given.

   **A key host.** When the host can be driven only through an API that takes the user's key (driver v1 N4), the driver makes every call to the host's API through the kit's key helper, never by itself. It runs `python3 -I kernel/driver-kit/hostkey.py`, finding it at `../../kernel/driver-kit/hostkey.py` from its own folder. On stdin it sends one JSON object with exactly `host`, `method` (`GET`, `POST` or `DELETE`), `path` and an optional `body` (an object). It reads back exactly `status` and `body`, or, on exit 1, a D3 error. It sends a method and a path only: never a key, a header or an address. Tell the user three things:
   - Adding their host is one reviewed row in `kernel/driver-kit/hosts.json`, made through an issue or pull request on openwizdev/OpenWiz. Until that row merges, the helper refuses the host, so the kit can't pass.
   - The key stays in the user's system keychain or in an environment variable they set. The helper alone reads it, and the driver never sees it.
   - When you run the kit, the kit's token check covers the key.

   You never ask for, read, print, store or pass the key. Run the kit on a copy of the driver's folder at `<openwiz>/adapters/<host>/`, so the driver runs the kit's own helper. A host that can't wake the same run or stop it gets no driver, because driver v1 needs all five checks: say so plainly, run `$W stop-all`, and stop.
3. Adapt `command`, `launch`, `running` and `end`, as `<openwiz>/adapters/template/README.md` says, keeping its four rules. Keep the four words and `schema` exactly as driver v1 defines them; `schema.json` stays byte for byte.
4. **live-shape**, before the driver reads any reply from the host's own tool: run that command live (ask first if it costs), save the reply with its values replaced by synthetic ones of the same type, and run `$W lesson live-shape --state <state> --live <reply file> --fixture <the reply the driver's tests feed it>`. On `fail`, fix the driver or its tests and check again.
5. Run the driver's own tests until they pass.

## 3. Prove

1. **The throwaway ticket.** `$W ticket --host <host> --account <the signed-in gh's own login, from gh api user --jq .login> --out <folder>`. Through the user's `gh`: make the private repository `<host>-driver-kit` with `<folder>/docs/agents/fleet.md`, make the `ready-for-agent` label, open the ticket from `ticket.json` (exactly its title, body and label), then post `start-record.md` as one comment on it. Record its closing: `$W started add --state <state> --what "the throwaway ticket" -- gh issue close <n> --repo <owner>/<host>-driver-kit`.
2. **The kit.** `$W kit --state <state> --openwiz <openwiz> --driver <the user's repository>/adapters/<host>/driver --repo <owner>/<host>-driver-kit --ticket <n> --harness <h> --model <m> [--asked <id>]`, with the user. Read its live output, not the docs. Every run the kit starts is recorded for `stop-all`, even when a check fails; a rerun clears the last kit result until it reads.
3. **wake-after-turn.** Start a run (ask first if it costs; record it), confirm on the host that its first turn has ended, then `wake` it and read the throwaway ticket. `$W lesson wake-after-turn --state <state> --turn-ended <yes|no> --wake <answered|error> --note-edited <yes|no> --second-note <yes|no>`. A wake while the turn still runs proves nothing.
4. **expired-login.** `$W lesson expired-login --state <state> --driver <driver> --harness <h> [--asked <id>]` runs the driver's `start` with a stand-in harness that ends its first turn on a sign-in line, against the driver's own test fixtures: an empty home, nothing of your environment, and a `PATH` of the stand-in, the driver's `fixtures/` folder and the system's programs. The kernel isolates it (Linux Landlock and a seccomp filter): it runs from a throwaway box holding only a copy of the driver's executable and the plain files of its `fixtures/` folder (a link there is refused), reads and runs only that box and the system's programs and libraries (no system configuration), writes only that box, and opens no socket, so no network, host socket, file of yours or other process's environment is reachable, and a host tool missing from `fixtures/` fails instead of reaching the host. Where a Linux kernel can't isolate it, the probe refuses and runs nothing. On macOS, which has none of these, only this probe is skipped: it says so in one line and the lesson reads `not run`; check it on Linux to claim passing. So keep a fake of the host's own tool in `adapters/<host>/fixtures/`, as the driver's tests use; it never reaches the real host or signs the user out. The driver must fail `start` with `next` exactly the contract's `sign_in_next` for that harness and host.
5. Fix and rerun the failing check or lesson until the kit reads 5 of 5 and every lesson `pass`.

## 4. Ship and report

1. Open a pull request in the user's own repository with the driver and the passing kit output. Then offer, once, to contribute it to OpenWiz as a community driver (`adapters/<host>/`, with that kit run on its pull request); do it only on their yes, from their own fork.
2. `$W stop-all --state <state>`; for anything it can't stop, tell the user how.
3. `$W report --state <state> [--pr <url>]` and say its output exactly, as your final report: passing or not, it starts with the time from paste.

## 5. Share, only on yes

After a passing report whose fourth line starts `Stopped:`, run `$W share offer --state <state>`. On exit 0, show its output exactly, end your turn, write the user's next message to a private file and run `$W share reply --state <state> --file <file>`: it posts that one line once, through the user's own `gh`, as a comment on openwizdev/OpenWiz#1966 (Driver times), only on a plain yes, and only if the account, the pinned issue and the report still match the preview (otherwise it posts nothing and needs a fresh `share offer`). On anything else it posts nothing; say nothing more about sharing. On exit 1, say its last line and never post another way. Never retry a post.

Its tests: `python3 -I <this skill's folder>/tests/test_write_driver.py`.
