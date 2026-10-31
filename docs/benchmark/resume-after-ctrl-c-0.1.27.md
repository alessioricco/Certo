# Live check: `certo --resume` after Ctrl-C, Certo 0.1.27

`certo --resume` continues a run from the state in the project's
`.certo/` folder. It had been tested with unit tests, and resumed after
runs that ended on their own, but never after a run stopped with Ctrl-C
in the middle of its work. These runs do that.

## The setup

- **Certo:** 0.1.27 (not released yet), 2026-10-31, the `certo` command
  as installed (`.venv/bin/certo`), not through `uv run`.
- **Model:** `anthropic/claude-haiku-5-5`, `CERTO_MAX_TASK_COST=0.5`.
- **Project:** an empty folder.
- **Task:** `Create a small Python package textstats in this folder with
  three modules: words.py (word_count), chars.py (char_frequency,
  returning a dict), and longest.py (longest_word, ties go to the
  first). Add pytest tests for each module in tests/, and a
  pyproject.toml with pytest as a dev dependency.`
- **The interrupt:** a small script started `certo` in its own process
  group and, 3 seconds after the agent wrote its first `.py` file, sent
  `SIGINT` to the whole group, which is what Ctrl-C in a terminal does.

## Results

| Step | What happened | Exit code | Cost |
|---|---|---|---|
| The run, stopped after 41 s | Seven `.py` files written, the tests not yet run | 130 | $0.0080 |
| `certo --resume` | Same conversation; the agent ran the tests (16 passed) and finished | 0 | $0.1272 |

The interrupted run ended with:

```
Interrupted.
Continue with: certo --resume
```

and `.certo/run.json` said `"status": "interrupted"`. The resume
printed `Resuming: Create a small Python package textstats …`, told the
agent how the last run had ended, and ended `Verification: verified`.
`.certo/conversations/` still held one conversation, and `run.json`
then said `"status": "finished"`, `"verdict": "verified"`,
`"resumes": 1`.

## What the results say

- **Ctrl-C and `--resume` work as [documented](../guides/resume-a-run.md):**
  exit code 130 and the resume hint, then the same conversation
  continued to `verified`.
- **Through `uv run`, one more traceback.** In a first try the same
  interrupt was sent to `uv run certo`, which passes the signal on to
  Certo again; the second one arrived while the SDK was closing its
  terminal at exit and printed an `Exception ignored in atexit callback`
  traceback after the resume hint. The exit code and the saved state
  were the same. The installed command gets the signal once and printed
  no traceback.
- **Not recorded: the cost before Ctrl-C.** The `interrupted` entry in
  `.certo/RUNS.md` has no time, tokens or cost line, so the $0.0080
  isn't written anywhere. Added to TODO.

## Related

- [Resume an interrupted run](../guides/resume-a-run.md)
- [Run records and costs](../guides/run-records-and-costs.md)
