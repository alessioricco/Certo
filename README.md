# Certo

**Your coding agent shouldn't depend on one model, or one provider.**

[![PyPI](https://img.shields.io/pypi/v/certo.svg)](https://pypi.org/project/certo/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/alessioricco/certo/blob/main/LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://github.com/alessioricco/certo/blob/main/pyproject.toml)
[![Built on OpenHands SDK](https://img.shields.io/badge/built%20on-OpenHands%20SDK-6f42c1.svg)](https://docs.openhands.dev/sdk)

**[Documentation](https://github.com/alessioricco/certo/blob/main/docs/README.md)** · [Getting started](https://github.com/alessioricco/certo/blob/main/docs/getting-started.md) · [Troubleshooting](https://github.com/alessioricco/certo/blob/main/docs/troubleshooting.md)

Certo is a **coding-agent harness**: the layer around the model that runs the agent, gives it its tools, chooses the model, sets the limits, and checks the result. The model writes the code; the harness decides what counts as done. The agent loop and the basic tools come from the [OpenHands SDK](https://docs.openhands.dev/sdk); Certo adds the model choice, the limits and the verification.

Certo runs coding tasks on any model, local or cloud. It can pick the best model for each task. When a model can't finish, or its provider goes down, it hands the task to the next one, with a note on where things stand.

It knows when to switch because it doesn't take the agent's word for it: when the agent says it's done, Certo runs your real tests and build itself, with no AI involved, and ends with one verdict and an exit code a script can rely on. *Certo* is Italian for "sure".

[![A task moves from claude-sonnet-5-5 to gpt-5.6-luna when Anthropic rejects the key, and still ends verified](https://raw.githubusercontent.com/alessioricco/Certo/main/docs/assets/escalation-provider-failure-0.1.22.gif)](https://github.com/alessioricco/Certo/blob/main/docs/benchmark/escalation-provider-failure-0.1.22.md)

*A real run: the first model's key was rejected (invalid on purpose, for the demo), so Certo handed the task to the next model, which passed the checks. 1m 32s, $0.02. [The record of this run](https://github.com/alessioricco/Certo/blob/main/docs/benchmark/escalation-provider-failure-0.1.22.md).*

```bash
uv tool install certo           # or: pip install certo
certo init                      # pick Ollama for a local model, or a cloud provider
cd certo-workspace && certo tasks/wordle.md --project wordle
```

## One task, more than one model

With `--escalate`, Certo runs a task on the first model of a ladder you write, and hands it to the next model only when the verdict shows the model couldn't finish, or when its provider fails. Three ladders, three uses. Each goes in `escalation.yaml`; `certo ... --escalate NAME` picks one by name, and `--escalate` alone uses the one called `default`.

### Local first, cloud when needed

Keep the code on your machine, and pay for a cloud model only for the tasks the local one can't do.

```yaml
# escalation.yaml
escalation:
  ladders:
    default:
      - model: qwen3.8-27b-local
        retries: 1          # one fix attempt locally, then hand over
      - model: claude-haiku-5-5
```

```bash
certo "Add a --verbose flag, with a test" --escalate
```

This is the ladder Certo has measured. On its 9 benchmark tasks, graded by **hidden tests the agent never sees**:

| | Hidden tests passed | Solved on the local model | Median time per task | Cloud cost |
| --- | --- | --- | --- | --- |
| `qwen3.8:27b` → `claude-haiku-5-5` | **9/9** | **7 of 9** | 7m 44s | $0.019 |
| `claude-haiku-5-5` alone | 9/9 | none | 45s | $0.085 |

Seven tasks stayed on the machine. In the other two the local model did no work, and haiku solved both. The price is time: minutes per task locally, seconds in the cloud. On nine small tasks the saving is a few cents; the point is that the cloud became the exception. Details: [Escalation in 0.1.17](https://github.com/alessioricco/certo/blob/main/docs/benchmark/escalation-0.1.17.md) (haiku alone is from the [0.1.15 baseline](https://github.com/alessioricco/certo/blob/main/docs/benchmark/baseline-0.1.15.md)).

One real run of the quickstart's Wordle task with a six-model ladder, where the local model finished and no cloud model was called (the folder path is shortened and the agent's work is left out; the full record: [One escalation run](https://github.com/alessioricco/certo/blob/main/docs/benchmark/escalation-wordle-0.1.19.md)):

```text
── Certo 0.1.19 ────────────────────────────────────────────
  Model    escalate: qwen3.8-27b-local → claude-haiku-5-5 → claude-sonnet-5-5 → gpt-6-luna → claude-opus-5-5 → gpt-6.1-sol
  Folder   …/projects/wordle (project wordle)
  Runs on  this computer
  Checks   on, up to 2 fix attempts
  Limits   30 min · 50 steps · $0.50
────────────────────────────────────────────────────────────
[… 16 minutes of agent work …]
Verification: verified

Run summary:
  Total running time: 16m 00s
  Models: ollama/qwen3.8:27b (effort default)
  Total tokens: 554,997 (input 536,968, of which cached 0; output 18,029)
  Total cost: $0.0000
  Rungs:
    1. qwen3.8-27b-local (ollama/qwen3.8:27b): verified, 0 fix attempts, 16m 00s, 554,997 tokens, $0.0000
  Final result from rung 1 (qwen3.8-27b-local).
```

### Cheap cloud first, frontier when needed

Start on a fast, cheap cloud model, and move to a stronger one when it can't finish.

```yaml
# escalation.yaml
escalation:
  ladders:
    cheap-first:
      - model: claude-haiku-5-5
        retries: 1
      - model: claude-sonnet-5-5
```

```bash
certo "Fix the failing test in payments.py" --escalate cheap-first
```

On Certo's 13 benchmark tasks, Haiku alone solved all 13, so this ladder never climbed: it cost what Haiku costs, about a tenth of Sonnet alone, for the same results ([the run](https://github.com/alessioricco/certo/blob/main/docs/benchmark/ladder-haiku-sonnet-0.1.25.md)). Where it pays off, on tasks Haiku fails, hasn't been measured yet.

### Another provider when one is down

Two models from different providers, so an outage doesn't stop the task.

```yaml
# escalation.yaml
escalation:
  ladders:
    other-provider:
      - model: claude-sonnet-5-5
      - model: gpt-6.1-sol
```

```bash
certo "Fix the failing test in payments.py" --escalate other-provider
```

When the first provider fails (an outage, a rate limit, a rejected key), the task climbs to the next model, and Certo records it as a provider failure, not as a model that couldn't do the work. This ladder hasn't been benchmarked yet.

On every ladder, your own limits stop the climb instead: a task that runs out of time (`budget_exhausted`), or reaches `CERTO_MAX_TASK_COST`, keeps the verdict it has. What makes Certo climb, rung by rung: [Escalate between models](https://github.com/alessioricco/certo/blob/main/docs/guides/escalate-between-models.md).

## Any model, and the right one for each task

Certo isn't tied to any provider: the model is one setting, and the same task runs on Ollama, Anthropic, OpenAI, Gemini, DeepSeek or any [LiteLLM model](https://docs.litellm.ai/docs/providers). The same task, run with only that setting changed, was `verified` on both OpenAI and Anthropic ([provider swap](https://github.com/alessioricco/certo/blob/main/docs/benchmark/provider-swap-0.1.19.md)). Because Certo checks the result itself, it can also decide *which* model to use:

| | What Certo does | Add |
| --- | --- | --- |
| **Best model per task** | Reads the task, matches it to a profile you write (in the shipped example, "debugging" weighs reasoning and precision, "scaffolding" favours cheap models), and picks the best-rated model you enabled. One choice per task, not per step, with no extra model call to decide. Falls back to the next model when a provider fails or a fix attempt still fails the checks. | `--auto-model` |
| **Escalation** | Runs the task on the first model of your ladder, and moves to the next one when the verdict shows the model couldn't finish, or its provider fails (see above). The next model is told what the last one left. | `--escalate` |
| **Measure it** | Runs the same tasks on your models and strategies, graded by hidden tests, so you choose from your own numbers. | `certo bench` |

`--auto-model` and `--escalate` are two ways to choose, and can't be combined in one run. You describe your models once, in `models_list.yaml` (ids and ratings) and `models.yaml` (the ones you enabled, with keys), and your choices in one file per mode: `task_profiles.yaml` for `--auto-model`, `escalation.yaml` for `--escalate`. Every choice is written down: `MODEL_DECISIONS.md` says why each model was picked, and `.certo/RUNS.md` which models worked on the project. Of the ladders, only local first, cloud when needed has been measured; auto-model has no benchmark yet. Guides: [Escalate between models](https://github.com/alessioricco/certo/blob/main/docs/guides/escalate-between-models.md), [Pick models automatically](https://github.com/alessioricco/certo/blob/main/docs/guides/pick-models-automatically.md), [Auto-model or escalation](https://github.com/alessioricco/certo/blob/main/docs/concepts/auto-model-or-escalation.md).

### Measured

Each model alone, from the 0.1.15 baseline (135 runs):

| Model | Hidden tests passed | Median time per task |
| --- | --- | --- |
| `claude-sonnet-5-5` (cloud) | 9/9 | 31s |
| `claude-haiku-5-5` (cloud) | 9/9 | 45s |
| `gemma4:31b-it-qat` (local) | 26/27 | 12m 40s |
| `qwen3.8:27b` (local) | 24/27 | 4m 37s |

A later local run, on Certo 0.1.18, set the default local model: `qwen3.8:27b` passed **27 of 27**, and `qwen3-coder:30b`, the old default, 18 of 27 ([details](https://github.com/alessioricco/certo/blob/main/docs/benchmark/baseline-0.1.18-local.md)).

In the 0.1.15 runs, Certo was fooled **3 times in 135**: it said `verified` while the hidden tests failed, each time because the code broke a rule the task stated and the agent's own tests never tried it. Of the 54 runs that failed the hidden tests, it caught all the others. These are small tasks with few repeats, and escalation has so far been measured only after a local model did no work, not after it wrote wrong code. All the numbers and their limits: [Benchmark results](https://github.com/alessioricco/certo/tree/main/docs/benchmark).

## Why the verdict can be trusted

Agents say "done", and sometimes they're wrong. Two real runs from building Certo, both asking a model for a Tower of Hanoi game:

- **"There are errors in the tests around sequence handling and state transitions."** The truth: the file didn't even run. An `IndentationError` stopped every test before it started. The agent never re-ran the tests; the diagnosis was made up.
- **Every unit test passed, and the game crashed the moment a user picked "solve".** The agent said success, and so did pytest.

The agent's report is a claim, not evidence. Certo looks at the evidence, and its verdict is also what decides when a model's work is good enough to keep:

| When the agent... | Certo... | Verdict |
| --- | --- | --- |
| says it's done | runs the project's own tests, build, lint and typecheck | `verified` or a failure |
| left a check failing | sends the real error back and lets it try again | `retry_exhausted` if it never gets there |
| tries a fix that changes nothing | stops early instead of burning tokens | `no_progress` |
| "fixes" a bug without touching a file | asks once more, then refuses to call it verified | `unchanged` |
| leaves its own to-do list half done | doesn't run the checks at all | `incomplete` |
| builds something with no tests | never counts "nothing to check" as a pass | `inconclusive` |

With `--escalate`, the failing verdicts are what move a task to the next model. Eight cases, and how each one changed Certo: [Why agents lie](https://github.com/alessioricco/certo/blob/main/docs/concepts/why-agents-lie.md).

## Quickstart

```bash
uv tool install certo
certo init
cd certo-workspace
certo tasks/wordle.md --project wordle
```

[uv](https://docs.astral.sh/uv/) installs Certo as a command in its own environment. With pip, install it inside a virtual environment: `python3 -m venv ~/.venvs/certo`, then `~/.venvs/certo/bin/pip install certo` (on systems that protect their Python, `pip install` outside one fails). Upgrade with `uv tool upgrade certo` or `pip install -U certo`. See [Getting started](https://github.com/alessioricco/certo/blob/main/docs/getting-started.md#1-install).

`certo init` asks which provider you use (OpenAI, Anthropic, Gemini, a local Ollama, or any LiteLLM model), takes your API key at a hidden prompt, saves the settings, and makes one real call to check the model works. It also leaves five sample tasks in `tasks/`: Wordle and the Tower of Hanoi in the terminal, in Python, and three browser games (a space-rocks shooter, a maze chase and an alien-fleet shooter), which need Node 18+. With a cloud model a run uses your credits, and Certo prints the cost at the end. The generated project lands in `projects/wordle`.

### More than one model

`--escalate` and `--auto-model` read the model files. The first time, Certo prints the `cp` commands that copy the examples it ships:

- `models_list.yaml`, the catalog: every model's id and ratings.
- `models.yaml`, your settings: the models you enabled, with their key or server address.
- `escalation.yaml`, your ladders, for `--escalate`; optional: without it, Certo builds a ladder from the ratings.
- `task_profiles.yaml`, the kinds of task and what matters for each, for `--auto-model`, which needs it (`certo init models --profiles` writes it and asks which model you want for each).

Then add `--escalate` (with a ladder from [One task, more than one model](https://github.com/alessioricco/certo#one-task-more-than-one-model)) or `--auto-model` to a run. `certo check --models` tests every model you enabled before you rely on it.

Or work on one project at a time, new or existing:

```bash
cd any-project && certo "Add a --verbose flag, with a test"
```

This works in any folder when `certo init` saved your settings for "all projects on this computer", its default. Before the agent edits a folder that already has files, Certo prints a one-line warning if it has uncommitted git changes, or isn't a git repository. `certo check` shows where each setting comes from and re-runs the model check.

Already have a project? Check it with no agent and no model, for free:

```bash
certo verify ./my-project
```

### Without `certo init`

Set two variables instead, in your shell, in a `.env` in the folder you run `certo` from, or in `~/.config/certo/.env` for every folder ([details](https://github.com/alessioricco/certo/blob/main/docs/reference/configuration.md#where-certo-looks)):

```bash
export CERTO_LLM_MODEL=anthropic/claude-sonnet-5-5   # or openai/..., gemini/..., deepseek/...
export CERTO_LLM_API_KEY=sk-...

certo "Build a CLI todo app in Python, with tests" --project todo
```

With a local model (no API key):

```bash
ollama pull qwen3.8:27b
export CERTO_LLM_MODEL=ollama/qwen3.8:27b
export CERTO_LLM_BASE_URL=http://localhost:11434
```

`qwen3.8:27b` passed all 27 runs of Certo's [local benchmark](https://github.com/alessioricco/certo/blob/main/docs/benchmark/baseline-0.1.18-local.md) and needs roughly 20 GB of GPU or unified memory. With less, try a smaller coder model such as `qwen2.5-coder:7b` (`CERTO_LLM_MODEL=ollama/qwen2.5-coder:7b`); Certo hasn't benchmarked it, so expect weaker results on multi-step tasks.

## What the verdict means

The last line of every run is the verdict:

| State | Meaning |
| --- | --- |
| `verified` | The project's own tests or build ran and passed. |
| `inconclusive` | Nothing could be checked (no tests yet, unknown project type, missing toolchain). |
| `unchanged` | The checks passed, but the agent changed no file, so they don't show the task was done. |
| `retry_exhausted` | A check kept failing after the automatic fix attempts. |
| `no_progress` | A fix attempt changed nothing in the failing output, so Certo stopped early. |
| `incomplete` | The agent left items on its own to-do list unfinished. |
| `budget_exhausted` | The task ran out of its time budget. |

The exit code is nonzero for every failure state, so Certo works in scripts and CI. Add `--require-verification` to make `inconclusive` and `unchanged` fail too. Every state and its exit code: [Verdicts](https://github.com/alessioricco/certo/blob/main/docs/reference/verdicts.md). What to do next, verdict by verdict: [After the verdict](https://github.com/alessioricco/certo/blob/main/docs/guides/after-the-verdict.md).

## Features

**Any model**

- **Any model, one setting.** Ollama, Anthropic, OpenAI, Gemini, DeepSeek, Moonshot or any LiteLLM model, local or cloud. Switching is one environment variable, never a code change.

**Model choice and escalation**

- **Picks the best model per task.** Rate your models in `models_list.yaml`, enable the ones you have keys for in `models.yaml`, describe your kinds of task in `task_profiles.yaml`, and Certo routes each task to the best fit, with fallback when a provider fails. No extra LLM call to decide. Add `--auto-model`.
- **Hands over when a model fails.** Give Certo a ladder of models. Each task starts on the first, and moves to the next when verification shows the model couldn't finish, or its provider fails. Add `--escalate`. See [Escalate between models](https://github.com/alessioricco/certo/blob/main/docs/guides/escalate-between-models.md).
- **A benchmark.** `certo bench` compares models and strategies on tasks graded by hidden tests, and counts how often Certo itself was fooled. See [Benchmark models and strategies](https://github.com/alessioricco/certo/blob/main/docs/guides/benchmark.md).
- **Compare models on your own task.** A small script runs one task on a list of models, each in its own folder, and ends with a table of verdicts, times and costs. See [Compare models on one task](https://github.com/alessioricco/certo/blob/main/docs/guides/compare-models-on-a-task.md), and a real example with screenshots: [five models build an Asteroids-style game](https://github.com/alessioricco/certo/blob/main/docs/benchmark/compare-asteroids-0.1.19.md), where the cheapest cloud model, GPT-5.6 Luna, built a verified game for $0.07.

**Checks you can trust**

- **Independent verification.** Re-runs the project's real test, build, lint and typecheck commands after the agent finishes. It never invents a command the project doesn't configure.
- **Works across languages.** Detects and verifies Python, Node/JS/TS, Go, Rust and Java (Maven/Gradle) projects. Each Python project gets its own virtual environment, used by both the agent and the checks.
- **Verify without an agent.** `certo verify [PATH]` runs the same checks on any project, with no model needed.
- **Hard limits.** An iteration cap, a wall-clock budget across all retries, and an optional approve-every-action mode.

**Fits how you work**

- **Resume.** `certo --resume "hint"` continues a run with its earlier conversation, or with a stronger `--model`.
- **Run records.** Full transcript, token counts and cost per run, plus a log of which model was picked and why.
- **Sandboxed runs** ([experimental](https://github.com/alessioricco/certo/blob/main/docs/README.md#experimental-features)). Add `--execution docker` to run the agent in a container.
- **Server mode.** REST and WebSocket streaming. The OpenAI-compatible `/v1/chat/completions` endpoint and the SQL and Redis task stores are [experimental](https://github.com/alessioricco/certo/blob/main/docs/README.md#experimental-features).
- **Skills and custom tools.** `certo skills add` gives the agent your conventions, for every project or one, kept out of git; `certo skills list --task "..."` shows what a task would get. Downloading skills from git is [experimental](https://github.com/alessioricco/certo/blob/main/docs/README.md#experimental-features). See [Manage skills](https://github.com/alessioricco/certo/blob/main/docs/guides/manage-skills.md).

## More ways to run it

```bash
# Work inside a sandbox
certo "Add a /version endpoint" --project my-api --execution docker

# Hand the task to the next model of your ladder if one can't finish
certo "Fix the failing test in payments.py" --project my-api --escalate

# Let Certo choose the model for the task
certo "Fix the failing test in payments.py" --project my-api --auto-model

# Run one task on several models, side by side (examples/compare-models.sh.example)
./compare-models.sh tasks/spec.md

# Take the task from a file or URL
certo ./tasks/spec.md --project my-api

# Pause and ask you questions instead of guessing
certo "Scaffold a FastAPI service" --project my-api --interactive

# Check a project with Certo's verification only: no agent, no model
certo verify ./projects/my-api
```

## How it works

Certo is built on the [OpenHands Software Agent SDK](https://docs.openhands.dev/sdk), which runs the agent loop and tools. Certo adds the parts the SDK leaves open: what counts as verified, which model runs and when to fall back, the budgets, and the CLI and server you talk to. The details: [How verification works](https://github.com/alessioricco/certo/blob/main/docs/concepts/how-verification-works.md).

## Known limits

- Server mode has no authentication. Run it on localhost or behind your own gateway.
- Java projects are detected, but verification needs Maven or Gradle installed.
- Docker execution, the OpenAI-compatible endpoint, the SQL and Redis task stores and skills downloaded from git are [experimental](https://github.com/alessioricco/certo/blob/main/docs/README.md#experimental-features): tested, not yet proven in real use. Under Docker, automatic model selection makes the initial pick but does not fall back mid-task.
- Some local models, on some Ollama setups, write their tool calls as plain text and end the run with no work done. `certo check` tests for it; with `--escalate`, such a task goes to the next model. Which models worked in Certo's benchmark: [Choose a local model](https://github.com/alessioricco/certo/blob/main/docs/guides/choose-a-local-model.md).
- `verified` proves what the project's tests test, and nothing more. Read the tests: [Write a task Certo can check](https://github.com/alessioricco/certo/blob/main/docs/guides/write-a-good-task.md).

The full list is in the [documentation](https://github.com/alessioricco/certo/blob/main/docs/README.md#known-limitations).

## Documentation

- [Documentation home](https://github.com/alessioricco/certo/blob/main/docs/README.md): guides, reference and concepts, organised by what you want to do
- [Getting started](https://github.com/alessioricco/certo/blob/main/docs/getting-started.md): install, `certo init`, your first task, and reading the verdict
- [Write a task Certo can check](https://github.com/alessioricco/certo/blob/main/docs/guides/write-a-good-task.md): the habits that turn a vague request into a verified result
- [Troubleshooting](https://github.com/alessioricco/certo/blob/main/docs/troubleshooting.md): the problems people actually hit, with their fix
- [Questions and answers](https://github.com/alessioricco/certo/blob/main/docs/questions-and-answers.md): how Certo decides to hand a task to another model, what that model gets, and verdicts in CI
- [Why agents lie](https://github.com/alessioricco/certo/blob/main/docs/concepts/why-agents-lie.md): the real cases of agents claiming "done", and how Certo catches each one
- [ROADMAP.md](https://github.com/alessioricco/certo/blob/main/ROADMAP.md): where Certo is going; [TODO.md](https://github.com/alessioricco/certo/blob/main/TODO.md): what's left to do

## Contributing

Issues and pull requests are welcome. Issues labelled [good first issue](https://github.com/alessioricco/certo/labels/good%20first%20issue) are a good place to start, and so is [adding a benchmark task](https://github.com/alessioricco/certo/blob/main/docs/guides/contribute-a-benchmark-task.md). Questions and ideas go in [Discussions](https://github.com/alessioricco/certo/discussions). To work on the code:

```bash
git clone https://github.com/alessioricco/certo.git
cd certo
uv pip install -e ".[dev]"
uv run pytest -q     # no API key needed
```

## License

[MIT](https://github.com/alessioricco/certo/blob/main/LICENSE). Built and maintained by [Alessio Ricco](https://github.com/alessioricco) ([LinkedIn](https://www.linkedin.com/in/alessioricco/), [Medium](https://medium.com/@alessioricco)).
