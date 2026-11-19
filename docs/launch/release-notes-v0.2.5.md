# Certo v0.2.5

Not released yet.

## New: choose the model that writes the independent tests

[Independent tests](../guides/independent-tests.md) are written from the
task by separate conversations before the build, and run on the work
after it. Until now the run's own model wrote them, and with `--escalate`
the ladder's first model: often a cheap or local one, whose tests are
milder and catch less. `CERTO_INDEPENDENT_TESTS_MODEL` names the model
that writes them instead, by its name in `models.yaml`:

```dotenv
CERTO_INDEPENDENT_TESTS_MODEL=claude-haiku-5-5
```

A wrong name stops the run before it starts. In the benchmark, an arm
takes `independent_tests_model`. See
[Choose the model that writes them](../guides/independent-tests.md#choose-the-model-that-writes-them).

## New: choose how many milestones

`--make-milestones` lets a model split a task into milestones, and the
model chose how many. Now you can choose:

```bash
certo --milestone-count 5 task.md --project ledger
```

The model is told to write exactly that many, from 2 to 20.
`--milestone-count` turns on `--make-milestones` by itself. A plan with
another number is asked for once more; if it still has another number,
it runs as written, and Certo says so. Also `/make-milestones 5 TASK` in
the interactive session, `milestone_count` over MCP and in the
benchmark. See
[Choose how many](../guides/run-in-milestones.md#choose-how-many).
