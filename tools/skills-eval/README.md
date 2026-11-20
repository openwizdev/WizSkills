# Skills eval (CF4, #1361)

A behaviour eval of every shipped skill: synthetic cases, the actual skill
text, fake GitHub, CloudRoom and process tools, and a scorer that checks the
agent's actions, their order and its records. The rules are in
[contract.md](contract.md). Python 3 standard library only; no new dependency.

## Commands

```sh
python3 -I tools/skills-eval/test_openrouter.py       # OpenRouter shape, cap, isolation, crash and usage (free)
python3 -I tools/skills-eval/test.py                  # offline proofs: boundary, scorer, records, driver, tokens, contract (free)
python3 -I tools/skills-eval/eval.py check            # every case valid, synthetic, covered, its controls scored as declared (free)
python3 -I tools/skills-eval/eval.py coverage         # the skill-to-case map (free)
python3 -I tools/skills-eval/eval.py run --out DIR --env-file FILE     # paid role runs, resumable, capped by settings.json
python3 -I tools/skills-eval/eval.py score DIR        # exit 0 only if every case passed every repeat
python3 -I tools/skills-eval/eval.py compare A B      # refuses sets with different settings or cases
python3 -I tools/skills-eval/eval.py tokens --results DIR --out FILE       # recorded DeepSeek usage, free
python3 -I tools/skills-eval/eval.py tokens --offline --out FILE   # required-text bytes, never tokens
python3 -I tools/skills-eval/eval.py token-diff BEFORE AFTER
```

`run` needs `OPENROUTER_API_KEY` from the environment or a dotenv file outside
Git. Without it, paid runs stop as not run. The frozen actor and judge are
`deepseek/deepseek-v4.1-flash`, high effort, 3 repeats, 40 turns, 16000 actor
and 4000 judge output tokens. The total cap is $20. Every actor/judge attempt
reserves its maximum cost first, and sends a provider price ceiling. An
interrupted request retains its reservation durably; resuming skips it as an
incomplete run. One writer per results directory is enforced.

`tokens --results DIR` makes no request: it reports the provider's input,
output and cached input usage for every run, including the judge. These are
DeepSeek tokens, not Claude tokens. Cached input is a subset of total input.
This does not measure per-skill required-text tokens or text savings. The
separate `--offline` report still records required-text bytes and hashes.
No Anthropic key or token-count request is used by these commands.

For a long run, stop the sequential runner between cases, then resume the same
frozen set with four independent cases at once:

```sh
python3 -I tools/skills-eval/test_parallel.py
python3 -I tools/skills-eval/parallel.py --out DIR --env-file FILE
```

This preserves existing records and the core driver/settings manifest. The
scheduler pins its own SHA-256 and worker count in `DIR/execution.json` and
shares a serialized durable $20 budget across all in-flight requests. It
holds the same directory lock; never run two schedulers in one results set.

## Files

| File | What |
| --- | --- |
| `contract.md` | The shared contract (E1 owns it; E2 and E3 use it) |
| `cases/` | One synthetic case per file |
| `provenance.json` | Each case's source; incident links live only here |
| `required-text.json` | The files one load of each skill requires |
| `settings.json` | The frozen run settings |
| `fakeworld.py` | The fake-tool boundary |
| `score.py`, `records.py`, `cases.py` | Scoring, record validators, case checks |
| `driver.py` | The paid role run: OpenRouter chat completions and the fake shell |
| `tokens.py` | Required-text byte accounting and recorded provider token usage |
| `test.py` | Offline proofs |

Results and token reports for E1 are in `private/evidence/skills-eval/e1/`.
