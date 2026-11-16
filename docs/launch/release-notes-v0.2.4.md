# Certo v0.2.4

Not released yet.

This release makes it easier to tell Certo's maintainers what went wrong:

- **`certo report`** writes the last run's problems to one file, with
  keys hidden, to attach to a GitHub issue.
- **The run report lists Certo's notices**, and so does `certo --json`
  (a new `notices` field).

## New: `certo report`

When a run goes wrong in a way Certo should handle better, the facts
were spread over `.certo/` (`run.json`, `STATUS.md`, `RUNS.md`, the run
report, the saved conversation) and the terminal's scrollback. Now, in
the project folder:

```text
$ certo report --note "It stopped halfway; the model server was busy."
Report: /home/me/certo-projects/projects/ledger/.certo/certo-report.md
Read it before you share it: it holds the task and the checks' output.
```

The file has your Certo, Python and system; the run's task, model,
effort, time budget, step limit and how it ended; the errors the SDK
recorded (a provider timeout, a tool error, a rejected action); and the
run's report, with the checks' output, the files changed, the check
files the agent edited, the cost and Certo's notices. Every value that
looks like a key, from your settings files, `models.yaml` or by its
shape, is replaced with `[hidden]`. It calls no model and sends nothing.
See [Share a run's problems](../guides/run-records-and-costs.md#share-a-runs-problems).

## Also

- **Certo's notices are kept.** The run report gets a "Certo's notices"
  section (a blocked action, a limit coming up, failing checks sent
  back), and the JSON result a `notices` list. They used to be only on
  the screen.
