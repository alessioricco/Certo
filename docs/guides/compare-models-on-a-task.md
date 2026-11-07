# Compare models on one task

This guide shows how to give the same task to several models, one after
the other, and see side by side what each one built, its verdict, how
long it took and what it cost. It is the quick way to try models on a
task of your own. To measure models properly, with hidden tests and
repeats, use the [benchmark](benchmark.md) instead.

## What you get

A script runs Certo once per model, each in its own project folder, and
ends with a table. This one is from a real run, on a small task (a
leap-year function with tests):

```text
| Model | Verdict | Time | Cost | Exit |
|---|---|---|---|---|
| `anthropic/claude-haiku-5-5` | verified | 27.6s | $0.0053 | 0 |
| `openai/gpt-5.6-luna` | verified | 36.2s | $0.0077 | 0 |
| `gemini/gemini-3.8-flash` | skipped: GEMINI_API_KEY not set | | | |
```

Then you can open each model's project and compare the code, the tests
and the README it wrote. A full example, five models building an
Asteroids-style game, with screenshots and what each verdict meant:
[Five models build an Asteroids-style game](../benchmark/compare-asteroids-0.1.19.md).

## 1. Get the script

From a checkout of Certo, it is `examples/compare-models.sh.example`.
With Certo installed from PyPI, download it:

```bash
curl -o compare-models.sh https://raw.githubusercontent.com/alessioricco/certo/main/examples/compare-models.sh.example
chmod +x compare-models.sh
```

From a checkout, copy it instead, so you can edit your copy and keep the
template as it is:

```bash
cp examples/compare-models.sh.example compare-models.sh
chmod +x compare-models.sh
```

## 2. List the models

Open `compare-models.sh` and edit the lines between the two `# ----`
markers. Each line is one model:

```bash
run anthropic/claude-sonnet-5-5   ANTHROPIC_API_KEY
run openai/gpt-5.6-luna           OPENAI_API_KEY
run ollama/qwen3.8:27b            ""  http://localhost:11434
```

1. **The model**, the same value you would put in `CERTO_LLM_MODEL`.
2. **The name of the environment variable that holds its key**, such as
   `ANTHROPIC_API_KEY`. Write the variable's name, never the key. For a
   local model, write `""`.
3. **The server address**, only for a local or self-hosted model.

Add as many lines as you like, and delete the ones you don't need.

## 3. Set the keys

Export each key in the shell you run the script from:

```bash
export ANTHROPIC_API_KEY=...
export OPENAI_API_KEY=...
```

A line whose key variable isn't set is skipped, and the table says so.
The script passes each key to Certo in the environment, never on the
command line, so it doesn't appear in the list of running processes.

## 4. Run it

Give it the task file:

```bash
./compare-models.sh my-task.md
```

Any task file works, for example one of the samples in your workspace's
`tasks/` folder (made by `certo init`; in a checkout of Certo they are in
[`src/certo/starter/tasks/`](https://github.com/alessioricco/certo/tree/main/src/certo/starter/tasks)).
For each model it prints the model and its log file when the run starts,
and the verdict, time and cost when it ends. The table comes last.

Everything goes in a new folder, `./compare-results/<task>-<date>-<time>/`:

| Path | What it is |
|---|---|
| `projects/<model>/` | The project that model built |
| `<model>.log` | Everything Certo printed for that model |
| `summary.md` | The table |

Two settings change how it runs:

| Variable | Default | Meaning |
|---|---|---|
| `CERTO` | `certo` | How to start Certo. From a source checkout: `CERTO="uv run certo"`. |
| `OUT` | `./compare-results/<task>-<date>-<time>` | Where the results go. |

## Read the results

- **The verdict comes first.** A model that ends `verified` passed the
  project's own checks; one that ends `retry_exhausted` or `no_progress`
  didn't get there. See [Verdicts](../reference/verdicts.md).
- **Then read the tests.** Each model wrote its own tests, so `verified`
  means "passes the tests this model wrote". Two models can both be
  `verified` and still disagree. To check, run one model's tests on the
  other's code; differences show where the task left room for two
  readings. See
  [Write a task Certo can check](write-a-good-task.md#3-give-the-expected-answers-yourself).
- **One run is one sample.** The same model can do better or worse on
  the next try. Before choosing a model from this table, run it again, or
  use the [benchmark](benchmark.md), which repeats each run and grades it
  with tests the agent never saw.

## Good to know

- **The models run one after the other**, so the times are comparable
  and a local model has the machine to itself. Expect seconds to minutes
  per cloud model on a small task, and more for a local one.
- **Cloud models cost money.** The table shows what each run cost. Try a
  big task on one cheap model first.
- **Each line sets its own model, key and server address**, so the model
  in your settings file doesn't matter. Your other settings, such as the
  time budget and the number of fix attempts, apply to every run.
- **To continue one model's run**, for example after `stuck` or
  `budget_exhausted`, give Certo the same projects folder the script
  used, from the folder you ran it in. The command printed at the end of
  the log already includes `CERTO_PROJECTS_DIR=...` when the run used a
  non-default projects folder:
  `CERTO_PROJECTS_DIR=compare-results/<task>-<date>-<time>/projects certo --resume --project <model>`.
- **The `compare-results/` folder is yours.** In a checkout of Certo, git
  ignores it and your `compare-models.sh`.

## Related

- [Benchmark models and strategies](benchmark.md): the measured way to
  compare models, with hidden tests and repeats
- [Choose a local model](choose-a-local-model.md): which local models did
  best in Certo's benchmark
- [OpenAI, Claude and Gemini](openai-claude-gemini.md#try-another-model-for-one-run):
  change the model for a single run
- [Five models build an Asteroids-style game](../benchmark/compare-asteroids-0.1.19.md):
  a real comparison made with this script
- [Provider swap in 0.1.19](../benchmark/provider-swap-0.1.19.md): the
  same task on an OpenAI and an Anthropic model, and what running each
  one's tests on the other's code showed
