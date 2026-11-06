# Keep costs down

This guide shows how to spend less on cloud models without getting
worse results. It is for anyone who runs Certo with a paid provider.
Every number here comes from one of Certo's recorded benchmarks, on the
13 bundled tasks; your own tasks may differ, so measure them too (last
section).

## See what you spend

Every run ends with its tokens and cost, and the run's report in
`.certo/reports/` has the same per model. Prices come from LiteLLM's
model list; a model it doesn't know shows `unknown`, and counts as 0 in
every limit below. See [Run records and costs](run-records-and-costs.md).

## Pick the cheapest model that passes your tasks

On the bundled tasks, three cloud models all passed 13 of 13, at very
different prices ([Baseline 0.1.23](../benchmark/baseline-0.1.23.md)):

| Model | Hidden tests passed | Cost per solved task |
|---|---|---|
| `anthropic/claude-sonnet-5-5` | 13/13 | $0.19 |
| `anthropic/claude-haiku-5-5` | 13/13 | $0.020 |
| `openai/gpt-6-luna` | 13/13 | $0.013 |

The strongest model cost about ten times more and solved nothing more.
A stronger model earns its price on harder work, so start with a cheaper
one and move up only for the tasks it can't finish.

## Or a local model, for no money

A model on your own machine costs nothing per task, but it is slower and
solves less: in the same baseline, `qwen3.8:27b` on Ollama passed 32 of
39 runs, with a median of 8m 49s per task against about a minute for
the cloud models. See [Ollama and local models](ollama-and-local-models.md)
and [Choose a local model](choose-a-local-model.md).

## Start cheap, move up only when needed

With escalation, Certo tries a cheaper model first and hands the task to
a stronger one only when the cheaper one's work fails the checks. When
the cheap model succeeds, you pay its price: in
[The Haiku → Sonnet ladder in 0.1.25](../benchmark/ladder-haiku-sonnet-0.1.25.md),
Haiku solved all 13 tasks, so the ladder cost $0.26, against $2.76 for
Sonnet alone. See [Escalate between models](escalate-between-models.md).

## Don't lower the reasoning effort to save money

A lower `CERTO_LLM_REASONING_EFFORT` is cheaper, but it can be wrong in
a way Certo's checks don't catch. On Haiku, `low` cost about half of
`high` ($0.42 against $0.80 for 39 runs), but 2 of its 39 runs passed
every check and were still wrong; `high` had none
([A lower reasoning effort first in 0.2.2](../benchmark/effort-0.2.2.md)).
Escalation can't help there, because it climbs only when the checks fail.
Keep the default, `high`, and save with a cheaper model instead.

## Set a limit per task

`CERTO_MAX_TASK_COST` stops a task once it has spent that many US
dollars, fix attempts, escalation and independent tests included:

```bash
CERTO_MAX_TASK_COST=0.50
```

Certo then runs the checks once on the work so far. Work that fails
them ends `cost_exhausted`; see
[What to do after each verdict](after-the-verdict.md#cost_exhausted).
For a benchmark, `certo bench --max-cost` caps the whole run
([Benchmark models and strategies](benchmark.md)).

## Know what costs extra

- **Independent tests** roughly double the cost of a task: on Haiku,
  $0.57 against $0.26 for one pass over the bundled tasks
  ([Independent tests in live runs](../benchmark/independent-tests-live-0.1.24.md)).
  Use them where a wrong result costs more than the run. See
  [Independent tests](independent-tests.md).
- **Fix attempts** call the model again each time the checks fail
  (up to `CERTO_MAX_VERIFY_RETRIES`, 2 by default). A task that keeps failing is usually a
  task to rewrite: see [Write a task Certo can check](write-a-good-task.md).

## Measure on your own tasks

The bundled tasks are small. Before you settle on a model or a ladder,
run a few of your own tasks on each choice: see
[Compare models on one task](compare-models-on-a-task.md) for a quick
look, or [Benchmark models and strategies](benchmark.md) for hidden
tests and cost per solved task.

## Related

- [Run records and costs](run-records-and-costs.md)
- [Configuration](../reference/configuration.md): `CERTO_MAX_TASK_COST`,
  `CERTO_LLM_REASONING_EFFORT`
- [Auto-model or escalation](../concepts/auto-model-or-escalation.md)
