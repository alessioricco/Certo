# Certo v0.2.2

This release shows more while a run goes, and measures whether a lower
reasoning effort first saves time without hurting results:

- **A progress line during the run**: the milestone, rung, fix attempt,
  last check, time and cost so far.
- **`certo check` says how an Ollama model will think** with your
  reasoning effort: on, off, Ollama's default, or no thinking mode.
- **A lower effort first doesn't pay off**, on Haiku or on a local
  `qwen3.8`: it is faster, but fools Certo's checks more often, so
  Certo doesn't build that ladder.
- **Two new guides:** keep costs down, built only from recorded
  benchmark numbers, and review the agent's work safely.

## New: a progress line during the run

While a run goes, Certo now prints one line that says where it is: the
milestone, the escalation rung's model, the fix attempt, the last check
run, the time and the cost so far. It comes every two minutes while the
agent works, and once more after each check run and when a fix attempt
starts:

```text
Progress: checks verified · 30.3s · $0.0066
```

`CERTO_PROGRESS_SECONDS` sets how often, and `0` turns it off. Only a run
in the terminal prints it. See
[Run records and costs](../guides/run-records-and-costs.md#the-progress-line).

## New: `certo check` says how an Ollama model will think

For an Ollama model, `certo check` now prints a `Thinking:` line, from
what the server says the model can do:

```text
Thinking: the model has it, and CERTO_LLM_REASONING_EFFORT is not set, so it thinks as Ollama does by default. high turns it on, minimal turns it off.
```

It matters because Ollama has no effort levels for most models, only
thinking on or off: `low`, `medium` and `high` all turn it on, and any
other value turns it off. So `xhigh` and `max` turn thinking off, not
up. (`gpt-oss` models are the exception: they get the level itself.)
The line also warns when you set an effort on a model with no thinking
mode, which Ollama refuses. See
[Ollama and local models](../guides/ollama-and-local-models.md#thinking-reasoning-with-ollama)
and [Commands](../reference/commands.md#certo-check).

## Benchmark: a lower reasoning effort first

An escalation ladder can put one model on two rungs, a lower effort
first and `high` when the checks fail. Before Certo builds such a
ladder on its own, [the benchmark](../benchmark/effort-0.2.2.md)
measured it on the 13 bundled tasks:

- **Haiku, `low` then `high`** (3 repeats): twice as fast and half the
  cost, but 2 of 39 runs passed every check and were still wrong;
  `high` alone had none. The ladder never climbed, because a ladder
  climbs only when the checks fail.
- **`qwen3.8:27b` on Ollama, thinking off then on** (4 repeats): median
  3m 52s against 6m 13s, and both arms passed 43 of 52, but thinking
  off first fooled the checks 4 times against 2.

So Certo keeps one effort per model. You can still write that ladder by
hand. See
[Escalate between models](../guides/escalate-between-models.md).

## New guide: keep costs down

[Keep costs down](../guides/keep-costs-down.md) shows how to spend less
on cloud models without worse results: the cheapest model that passes
your tasks, a local model, a cheap model first with escalation, a cost
limit per task, and what costs extra. Every number in it comes from a
recorded benchmark.

## New guide: review the agent's work safely

[Review the agent's work safely](../guides/review-the-agents-work.md)
is a routine for code you care about: what to set up before a run
(commit first, confirm mode or Docker, independent tests), what to read
after it (the report, the diff, any change to the tests), and how to
undo it with git or Certo's checkpoints.

## Fixed: a benchmark file with its own models

A benchmark file that names its own `models_file`, like the ones in
`docs/benchmark/`, also picked up your own `escalation.yaml` and
`task_profiles.yaml` from the current folder or `~/.config/certo`.
Their models aren't in the file's models, so the benchmark stopped with
a list of problems. It now uses only the files it names; a benchmark
file without its own `models_file` still finds yours, as before. See
[The benchmark file](../reference/bench-yaml.md).

## Fixed: the report's path on Windows

On Windows, the path of the run report that Certo prints at the end of a
run mixed `\` and `/`. It now uses `\` only.

## Security: oauthlib 4.0.1

The lock file now pins `oauthlib` 4.0.1, which fixes the issue in
Dependabot alert #84. It is a dependency of a dependency; Certo's own
code doesn't use it.
