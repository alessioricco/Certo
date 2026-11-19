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
