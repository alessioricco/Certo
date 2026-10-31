# Benchmark models and strategies

This guide shows how to measure which models really deliver with Certo,
using `certo bench`: a set of small coding tasks, each graded by tests the
agent never sees. It is for anyone choosing a model, or checking that a
change to Certo makes results better and not worse.

## What it measures

`certo bench` runs the normal Certo pipeline on every task, for every arm
you compare (an arm is a model, used in a certain way), several times.
After each run it grades the result with the task's **hidden tests**.

The tests are hidden because the agent writes its own tests, and Certo
checks the work with them. An agent that misunderstands a rule usually
writes tests with the same misunderstanding, so its own tests pass. Hidden
tests, written with the task, don't share that mistake. They answer two
questions:

1. **How often does each model produce correct code?** The hidden-test
   pass rate.
2. **How often is Certo itself right?**
   - *Fooled:* Certo said `verified`, but the hidden tests failed.
   - *Caught:* the agent claimed it was done, and Certo did not say
     `verified`.

## The tasks

Thirteen tasks ship with Certo (task set version 2). Nine are small:
each takes a few minutes for a capable model, and the tricky ones are
where smaller models often go wrong. Four are larger: `ledger-transfers`,
work inside an existing package of several modules; `todo-deps`, a
command-line program in Rust; `library-loans`, an HTTP API in Go; and
`room-bookings`, an API and a React page in Node.

| Task | Language | What it tests |
|---|---|---|
| `temperature-table` | Python | An inclusive range with negative steps and a direction check: off-by-one traps. |
| `wordle-score` | Python | Wordle scoring with repeated letters: "correct" first, then "present" only while copies remain. |
| `pedestrian-crossing` | Python | A traffic-light state machine: minimum green time, presses during yellow or red, exact tick counts. |
| `duration-parser` | Python | Parsing `1h30m`-style durations strictly (order, no spaces inside a part) and formatting them back. |
| `page-ranges` | Python | Print page ranges (`1-3,5,7-`) with open ends, overlaps and bounds, and the shortest spec back. |
| `inventory-fix` | Python | Fixing and extending existing code without breaking its tests: validation, a custom exception, no partial changes. |
| `slugify` | Node | URL slugs: removing accents, and shortening without cutting a word. |
| `token-bucket` | Node | A rate limiter with a fake clock: fractional refill, the cap, a clock going backwards. |
| `semver-order` | Node | Version ordering with prereleases: numbers compared as numbers, numeric before text, shorter first. |
| `ledger-transfers` | Python | Two bugs whose cause is in another module than the symptom, and a feature with exact matching rules, in an existing package with its own tests. |
| `library-loans` | Go | An HTTP API with a clock passed in: ISBN-13 check digits, due dates and capped fines, loan limits, exact status codes and JSON errors, safe for concurrent requests. Standard library only. |
| `room-bookings` | Node | An HTTP API and its page rendered with React (no JSX): booking rules on quarter hours, overlaps, free time between bookings, titles shown as text. Uses `react` and `react-dom` from a lock file. |
| `todo-deps` | Rust | A to-do CLI with subcommands, where tasks wait for other tasks: a list kept in a file, cycles refused, exact output and exit codes. Standard library only. |

Task set version 1 was the nine small tasks; the baselines up to 0.1.22
used it. To compare with them, list those nine under `tasks:` in the
benchmark file: `tasks: all` now includes the larger tasks too. The Go
task needs `go` (1.22 or newer) and the Rust task `cargo` on the machine
running the benchmark. `room-bookings` is the only task that needs the
network: the agent and grading install its two packages with `npm ci`.

`certo bench --list-tasks` lists them. Node tasks need Node 18 or newer.
Grading also supports Go (`go test`) and Rust (`cargo test`) tasks, and
Node tasks with packages; see
[Contribute a benchmark task](contribute-a-benchmark-task.md).

## How the model files and `bench.yaml` relate

- **`models_list.yaml`** describes the models and **`models.yaml`** holds
  your keys and the models you use: the same files `--auto-model` and
  `--escalate` use. **`escalation.yaml`**, when you have one, sets
  `cost_axis` and `max_rungs` for the ladder an `escalate` arm derives.
  See [The model files](../reference/models-yaml.md).
- **`bench.yaml`** says what to compare. Each arm names a strategy and
  models **by their `name`**. It holds no keys, so you can commit it.

The benchmark never reads `.env`. An
arm can only name a model that `models.yaml` enables: a model missing
there, or with `activated: false`, is an error. (Before version 0.1.9 the
benchmark ignored `activated`.)

```yaml
# bench.yaml
tasks: all
repeats: 3
arms:
  - name: local
    strategy: single
    model: qwen3.8-27b-local      # a model name
  - name: cloud
    strategy: single
    model: gpt-6-luna
```

`strategy: single` means one model and the normal Certo run, exactly what
`certo "<task>"` does. `strategy: escalate` climbs a ladder of models,
like `certo --escalate`: give it `models: [a, b]` for a fixed ladder, or no
`models` for the ladder Certo derives from the ratings. `strategy: auto`
picks a model for each task from your task profiles, like
`certo --auto-model`: give it `models: [a, b, c]` to choose from those, or
no `models` to choose from every active model. Start from
[bench.yaml.example](../../src/certo/examples/bench.yaml.example) (when
`bench.yaml` is missing, `certo bench` prints the command that copies it); how to choose the arms for
your question is in [Write a benchmark file](write-a-benchmark-file.md),
and every field is in the [bench.yaml reference](../reference/bench-yaml.md).

## Run it

```bash
certo bench                     # reads ./bench.yaml and the model files
```

Before anything runs, Certo prints the plan: tasks × arms × repeats, and a
rough cost estimate for paid models where LiteLLM knows the price. Answer
`y` to start, or pass `--yes` (needed when there is no terminal).

**The cost estimate.** Each run is priced at about 500k input and 20k
output tokens, from LiteLLM's price list; local models cost nothing. It is
rough: real runs vary a lot.

- An `escalate` arm is shown with **at most** the cost of every rung
  running. A derived arm lists only the ladder it will use (the same for
  every task), not every active model.
- Most escalation runs stop before the top rung. When earlier results in
  the same parent folder (`bench-results/` by default) include the lower
  rungs' models, the plan also shows a **likely** cost: each rung's cost
  times the share of earlier runs that climbed past the rungs below it. A
  model counts only with the same model id, and both single-model arms and
  escalation rungs count.
- With no such results, only "at most" is shown, with the models that have
  no history.

For example (no earlier results yet):

```text
  derived: escalate, qwen3.8-27b-local (ollama/qwen3.8:27b, local, no cost); claude-haiku-5-5 (anthropic/claude-haiku-5-5, ~$0.30 per run); claude-opus-5-5 (anthropic/claude-opus-5-5, ~$2.40 per run), 9 run(s) (derived from the ratings, the same for every task; at most ~$2.70 per run if every rung runs; no earlier results for qwen3.8-27b-local, claude-haiku-5-5 to say more)
  Estimated cost: at most ~$70.20 (rough: assumes ~500k input and ~20k output tokens per run)
```

`--max-cost` (below) works on the recorded cost, not on the estimate.

**A local model.** Make one arm with an Ollama model enabled in `models.yaml`.
Runs go one at a time, because a local server serves one model at a time.
Give Ollama a large context window first; see
[Ollama and local models](ollama-and-local-models.md).

**A cloud model.** Make one arm with a cloud entry. To keep spending in
check, add a cap; Certo stops starting new runs once the recorded cost
reaches it, and keeps the results so far:

```bash
certo bench --max-cost 5
```

When every arm uses cloud models, runs can go in parallel:
`certo bench --parallel 4`. Certo refuses `--parallel` if any arm runs
locally.

**Both.** Put a local arm and a cloud arm in the same file. This is how to
check the project's rule that changes for local models must not make cloud
models worse.

**Interrupted?** Finished runs are kept. Continue with:

```bash
certo bench --resume            # the latest results folder
certo bench --resume --out bench-results/20261016-101500
```

`--resume` refuses a folder made with different tasks, arms, repeats or
models.

**Over several nights.** A long benchmark, like a full baseline on a
local model, can run in slices: one each night. Give each night an end
time with `--stop-at`, and Certo stops starting new runs then. The run
in progress finishes and is saved, so nothing is lost:

```bash
certo bench --out bench-results/baseline --stop-at 07:00            # first night
certo bench --resume --out bench-results/baseline --stop-at 07:00   # the next nights
```

The time is local and 24-hour; started at 23:00, `--stop-at 07:00`
means 07:00 the next morning. A run already started can go past it: a
run's time limit is 30 minutes by default (an arm can change it with
`max_task_seconds`), and a slow local model can end a little after that. Leave room if the machine is needed at 07:00. At the end Certo prints how many runs are left.

### What each run does

1. A fresh temporary folder gets only the task's starter files. The task
   text is the prompt; `task.md`, the hidden tests and the reference
   solution are never in the folder.
2. The arm's strategy runs the normal Certo pipeline there, with the arm's
   model, including Certo's checks and retries. Certo's default limits
   apply (50 steps per run, 2 fix attempts, 30 minutes, or the arm's
   `max_task_seconds`), and only its
   built-in skills load, so your own skills can't change the result.
3. The hidden tests are copied in and run in the project's own
   environment. Only they decide the score.
4. The result is saved at once, with a copy of the final folder and the
   run's conversation.

## Read the results

Each benchmark writes a folder, by default `bench-results/<date-time>/`:

| File | What it holds |
|---|---|
| `results.md` | The summary to read and share. |
| `results.csv` | One row per run, for a spreadsheet, with each model's reasoning effort (`reasoning_efforts`). |
| `cost.json` | The real total cost, the cost per model and reasoning effort, and the plan's estimate. |
| `runs/*.json` | Every detail of each run. A run that ends with an error keeps its `error` and still records the tokens, cost and condensations it used up to the error (0 when it failed before any model call), so a long run that lost its server doesn't look free. |
| `runs/transcripts/<run>.json` | The run's whole conversation: the agent's messages, the tools' output and Certo's notes. Read it to see why a run ended as it did. `seconds` says when each message arrived, counted from `started_at`: it shows where a long run spent its time. |
| `workspaces/<run>/` | The code each run left behind (without `.venv` and `node_modules`). |
| `meta.json` | Certo version, date, hardware, task set, the benchmark itself, the plan's cost estimate, and the Ollama setup (below). |

For each Ollama model, `meta.json` (`model_servers`) and the top of
`results.md` record the server's address (host and port only), its Ollama
version, the digest of the model's build (`results.md` shows its first
12 digits, as `ollama list` does) and the context window the server
gives the model, so a local result can be traced to how the model was
served, and two benchmarks with the same model name can be told apart
when the model was pulled again in between. Certo loads the model to
read the window. A server that doesn't answer is recorded as unknown and
doesn't stop the benchmark; its runs then fail on their own.

In `results.md`, per arm:

- **Hidden tests passed:** the score, as `passed/total` and a percentage.
- **Verified:** how often Certo said `verified`.
- **Fooled:** Certo said `verified`, but the hidden tests failed. This
  should be close to zero; each one is worth a look.
- **Caught:** the agent claimed it was done, and Certo did not say
  `verified`. Without Certo, each of these would have looked finished.
- **Unconfirmed passes:** Certo did not say `verified`, but the hidden
  tests passed, for example because the agent wrote no tests. Some
  "caught" runs are in fact unconfirmed passes.
- **Median time, tokens and cost.**
- **Tool-call reminders:** how often the agent wrote a tool call as text
  instead of making it, and Certo sent it back
  ([`CERTO_TOOL_CALL_REMINDERS`](../reference/configuration.md), see also
  [Troubleshooting](../troubleshooting.md#the-run-ends-at-once-with-a-tool-call-as-the-agents-last-message)),
  added up over the arm's runs. An escalation run counts every rung's own.
  Each run's count is also in `runs/*.json` and in the
  `tool_call_reminders` column of `results.csv`.
- **Cost per solved task:** the arm's total cost divided by the runs whose
  hidden tests passed. The fair way to compare a cheap model that solves
  less with an expensive one that solves more.
- **Independent tests failed** (only when an arm sets
  `independent_tests: true`): runs where most sets of
  [independent tests](independent-tests.md) failed, then the same count
  among runs whose hidden tests passed (a wrong independent test, or a
  bug the hidden tests miss) and among runs that fooled Certo (caught).
  Each run's result is also in `runs/*.json` and in the
  `independent_status` column of `results.csv`.

For an `escalate` arm with no `models:`, the **Models** column shows the
ladder derived from the ratings. (A results folder from before version
0.1.14 doesn't record that ladder, so it shows the models the runs used.)

A per-task table shows where each arm passes and fails. For `escalate`
arms, a section shows how often each rung produced the final result,
for example `rung 1 (qwen-local): 4/9, rung 2 (gpt-luna): 5/9`.

For a Python task whose hidden tests are named by milestone
(`test_m1_...`, as in a [task in milestones](contribute-a-benchmark-task.md#a-bigger-task-in-milestones)),
a table shows the hidden tests passed per milestone, added up over each
arm's runs, such as `37/37` for milestone 1 and `12/29` for milestone 4.
Each run's counts are in `runs/*.json`, under `hidden_tests.by_milestone`.
A results folder made before Certo 0.1.27 can get them with
`uv run python scripts/regrade_bench.py <results folder>`, from a
checkout: it grades the saved projects again, with no model.

**The real cost.** The **Cost** section of `results.md` (and `cost.json`)
gives what the benchmark really spent, from the recorded runs, next to what
the plan estimated, and one row per model: its runs, its cost, and its
average per run. An escalation run is split by rung, so each model is
charged only for what it ran. The same total is printed at the end:

```text
Total cost: $1.5000 (the plan estimated at most ~$9.00, likely ~$3.50), for 3 of 12 runs
```

Costs come from LiteLLM's prices, and a local model costs nothing;
`+ unknown` means a cloud model had no price.
When the benchmark is not finished, the line says how many runs it covers,
as above.
A results folder from before version 0.1.13 has no estimate to compare.

**Keep the numbers in proportion.** With 10 tasks and 3 repeats, an arm
has 30 runs; a difference of two or three runs can be chance. Compare results
only when the task set version and hash in the header match.

## Add a task

You can benchmark your own tasks: a task is a folder with a prompt
(`task.md`), optional starter files, hidden tests and a reference
solution. Point `tasks_dir` in `bench.yaml` at a folder of them, and
check them with no model:

```bash
certo bench --check-tasks
```

Every reference solution must pass its hidden tests, and every starter
alone must fail them. How to write a fair task, try it, and send it to the
bundled set: [Write or contribute a benchmark task](contribute-a-benchmark-task.md).

## Related

- [Compare models on one task](compare-models-on-a-task.md): a quicker,
  rougher look: one of your own tasks, once per model, no hidden tests
  (example: [five models build an Asteroids-style game](../benchmark/compare-asteroids-0.1.19.md))
- [Write a benchmark file](write-a-benchmark-file.md)
- [Write or contribute a benchmark task](contribute-a-benchmark-task.md)
- [bench.yaml reference](../reference/bench-yaml.md)
- [Baseline 0.1.13](../benchmark/baseline-0.1.13.md): the first complete
  results
- [Baseline 0.1.15](../benchmark/baseline-0.1.15.md): four local and
  three cloud models compared
- [Baseline 0.1.18, local](../benchmark/baseline-0.1.18-local.md):
  `qwen3.8:27b` against `qwen3-coder:30b`, which set the local default
- [Baseline 0.1.22](../benchmark/baseline-0.1.22.md): `qwen3.8:27b`
  and three cloud models, checking 0.1.22 made nothing worse
- [Baseline 0.1.23](../benchmark/baseline-0.1.23.md): the first on task
  set version 2, with Go, Rust and React tasks; `qwen3.8:27b` and three
  cloud models
- [Escalation in 0.1.17](../benchmark/escalation-0.1.17.md): two
  local-then-cloud ladders
- [Provider swap in 0.1.19](../benchmark/provider-swap-0.1.19.md): one
  task with an OpenAI and an Anthropic model, only the model id changed
- [First run in 0.1.19](../benchmark/first-run-0.1.19.md): 88.5s from
  install to the first `verified` project
- [First run with two models in 0.1.21](../benchmark/first-run-auto-model-0.1.21.md):
  2m 42s from install to a `verified` `--auto-model` run, with no file
  edited
- [Commands: certo bench](../reference/commands.md#certo-bench)
- [How verification works](../concepts/how-verification-works.md)
