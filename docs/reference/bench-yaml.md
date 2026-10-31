# bench.yaml

The format of the benchmark file read by `certo bench`. It is for looking
things up; the guides are [Benchmark models and strategies](../guides/benchmark.md)
and [Write a benchmark file](../guides/write-a-benchmark-file.md).

The default file is `./bench.yaml`; `certo bench --config FILE` reads
another. It holds no keys: models are named from the model files. A commented
example ships as [bench.yaml.example](../../src/certo/examples/bench.yaml.example), inside the
package (`certo/examples/`).

## Layout

```yaml
models_file: ./models.yaml             # optional
models_list_file: ./models_list.yaml   # optional
escalation_file: ./escalation.yaml     # optional
task_profiles_file: ./task_profiles.yaml   # optional
tasks_dir: ./my-tasks        # optional
tasks: all                   # or a list of task names
repeats: 3
arms:
  - name: qwen-local
    strategy: single
    model: qwen3-coder-local
```

## Top-level keys

| Key | Default | Meaning |
|---|---|---|
| `arms` | **required** | A non-empty list of arms (below). |
| `tasks` | `all` | `all`, or a list of task names. `certo bench --list-tasks` shows the names. |
| `repeats` | `1` | Runs per task per arm, a whole number of at least 1. Results vary between runs, so more repeats give a fairer comparison. |
| `models_file` | looked up | Your personal `models.yaml`. Without it: `./models.yaml`, else `~/.config/certo/models.yaml`. `CERTO_MODELS_FILE` is not read. |
| `models_list_file` | looked up | The model catalog, `models_list.yaml`, the same way. `CERTO_MODELS_LIST_FILE` is not read. |
| `escalation_file` | looked up | `escalation.yaml`, the same way, for the `cost_axis` and `max_rungs` of a derived `escalate` arm. Optional: without one, the defaults apply. `CERTO_ESCALATION_FILE` is not read. |
| `task_profiles_file` | looked up | `task_profiles.yaml`, the same way, for `auto` arms: how a task is classified and which ratings count. Optional: without one, every task gets the `default` profile. `CERTO_TASK_PROFILES_FILE` is not read. |
| `tasks_dir` | the bundled task set | A folder of your own tasks, in the same shape. |

Any other key is an error. Relative paths are relative to the folder where
you run `certo bench`.

## Arms

Every arm has:

| Key | Meaning |
|---|---|
| `name` | A unique name, made of letters, digits, `.`, `_` and `-`. It appears in the results and in file names. |
| `strategy` | How the arm runs a task. See below. |

Every arm can also have:

| Key | Meaning |
|---|---|
| `independent_tests` | Optional, `true` or `false` (default). With `true`, each run writes [independent tests](../guides/independent-tests.md) before the build, as `--independent-tests` does, and records their result. Report only: the verdict and the score don't change. Their writing isn't in the plan's cost estimate. |
| `condense` | Optional, `true` (default) or `false`. With `false`, the run doesn't summarize older steps when the context window nearly fills (`CERTO_CONDENSE=no`), to measure what condensing changes. Each run's record counts its condensations. |
| `max_task_seconds` | Optional, any strategy: each run's time budget in seconds, as `CERTO_MAX_TASK_SECONDS` (default 1800, 30 minutes). Give a slow local model more time without changing it for the cloud arms. For an `escalate` arm it is one budget for all the rungs together. |
| `tool_call_reminders` | Optional, any strategy: how many times in a row a run that ends on a tool call written as text is sent back, as `CERTO_TOOL_CALL_REMINDERS` (default 3). `0` turns it off, to measure what the reminders change. |
| `skills_off` | Optional, any strategy: a list of Certo's own skills this arm's runs don't get, such as `[security-review]`. Next to an arm without it, it measures what those skills change. A name that isn't one of Certo's skills stops the benchmark before it starts; `certo skills` lists them. Your own skills are never loaded in a benchmark anyway. |
| `milestones` | Optional, any strategy, `true` or `false` (default). With `true`, a task written in milestones (`## Milestone N: title` sections) runs milestone by milestone, as [`certo --milestones`](../guides/run-in-milestones.md) does: the strategy once per milestone, in the same folder, until one isn't `verified`. The time budget and limits apply to each milestone; the plan's cost estimate is for one milestone. Each run's record lists every milestone's verdict under `milestones`. Every task of the benchmark must then be written in milestones, or the benchmark stops before it starts. An arm without it gets such a task whole, without its acceptance blocks, and all of their checks. |
| `context_tokens` | Optional, strategy `single` only: the model's context window for this arm, at least 16,384, as `CERTO_LLM_CONTEXT_TOKENS`. For an Ollama model it is asked from the server, so one machine can benchmark a small window without restarting Ollama. |

The other keys depend on the strategy. An unknown strategy, or a key the
strategy doesn't take, is an error that lists what is allowed.

### `strategy: single`

One model, the normal Certo run: exactly what `certo "<task>"` does.

| Key | Meaning |
|---|---|
| `model` | The `name` of an entry in the models file. An unknown name is an error that lists the names the file has. |

### `strategy: escalate`

Escalation, as `certo --escalate` does it: start on the first model, and
move to the next one only when Certo's verdict shows the model couldn't
finish, or its provider fails.

| Key | Meaning |
|---|---|
| `models` | Optional. A list of at least two model names, in the order to climb. Without it, the arm uses the ladder Certo builds from the active models' ratings: the same ladder for every task, printed in the plan. |
| `handoff` | Optional, `continue` (default) or `restart`: what each rung after the first starts from, as `CERTO_ESCALATION_HANDOFF`. Two arms that differ only in this compare the two. |

```yaml
arms:
  - name: local-then-cloud
    strategy: escalate
    models: [qwen-local, gpt-luna]
  - name: derived
    strategy: escalate
```

Grading is the same as for every arm: the hidden tests decide. Each run
records every rung that ran and which one gave the final verdict.
The named ladders in `escalation.yaml` are not used here: an arm's ladder
is its `models` list, or a derived one.

### `strategy: auto`

What `certo --auto-model` does: Certo classifies each task by its first
line, using the task profiles, starts on the model whose ratings fit that
profile best, and moves to the next only when the provider fails or a fix
attempt still fails the checks.

| Key | Meaning |
|---|---|
| `models` | Optional. The models to choose from, at least one. Without it, every active model is a candidate. |

```yaml
arms:
  - name: picked
    strategy: auto
    models: [qwen-local, claude-haiku-5-5, claude-sonnet-5-5]
```

The plan says which model each task will start on, and its likely cost
counts only that model. Each run's record has its `task_profile` and the
models it used, first the one it started on; `results.md` counts how many
runs started on each model.

## How models are used

- The arm's model is taken from the model files: its id, ratings,
  `reasoning_effort` and `timeout_seconds` from the list, its `api_key`,
  `base_url` and overrides from `models.yaml`. An empty field stays empty;
  it is never filled from `.env` or the environment's `CERTO_LLM_*`
  settings.
- An arm can only name a model that `models.yaml` enables. A model that is
  only in the list, or has `activated: false`, is an error that says how
  to enable it. (Before version 0.1.9 `activated` was ignored here.)
- Problems in the model files are checked as for every command (see
  [Checks](models-yaml.md#checks)): errors stop the benchmark,
  warnings are printed with the plan.
- `task_profiles.yaml` is used only by `auto` arms. The `escalation`
  settings (`cost_axis`, `max_rungs`) are used only by a derived
  `escalate` arm, to build its ladder.

## Strategies to come

Strategies are a small registry in Certo's code, so new ones can be added
without changing how the benchmark runs, for example `best_of` (several
attempts, the verifier picks). `single`, `escalate` and `auto` exist today.
