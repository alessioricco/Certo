# Certo v0.2.2

Not released yet.

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

## Fixed: the report's path on Windows

On Windows, the path of the run report that Certo prints at the end of a
run mixed `\` and `/`. It now uses `\` only.
