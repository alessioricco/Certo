# Certo v0.2.0

Not released yet.

## New: Certo as an MCP server

`certo mcp` lets an editor or an agent that speaks MCP, such as Claude
Code, hand a coding task to Certo and get back Certo's verdict:

```bash
claude mcp add certo -- uvx certo mcp
```

Its tools start a task and return at once (`run_task`, also with a task
file in milestones), follow it (`run_status`, `run_events`), stop it
(`run_cancel`) and continue it later (`run_resume`, as `certo --resume`
does), check a project without an agent (`verify`), list its
checkpoints and go back to one (`checkpoints`, `rollback`, which only
says what it would change until it's confirmed), test the model
(`check_model`), and list the projects, the models and ladders, and
the skills a run gets (`list_projects`, `list_models`, `list_skills`). `run_task` can also ask for
[independent tests](../guides/independent-tests.md), and so can a
`certo-server` task, with `independent_tests`: before, server mode
couldn't report them. A finished run's result is the same
object `certo --json` prints. Each project's `STATUS.md` and `RUNS.md`
are resources a client can show, and runs started over MCP are added to
`RUNS.md` like any other. The tools work only in projects under
`CERTO_PROJECTS_DIR` or in folders given with `--root`. It runs over
stdio, with no login, and doesn't use the MCP features the 2026-07-28
specification deprecates. See
[Use Certo from an editor or an agent](../guides/use-certo-over-mcp.md).

## New: `certo --json`

`certo "task" --json` prints the run's result as one JSON object on
standard output, and everything else on standard error: the verdict,
each check with the end of its output, the files the run created,
modified and deleted, the acceptance checks, the time,
tokens and cost per model, the ladder's rungs, how each model was
chosen (with `--escalate` or `--auto-model`) and the milestones. A
script or a CI job reads it instead of the terminal text.
`certo-server` returns the same object as `result`, in
`GET /tasks/{task_id}` and in the last message of `WS /tasks/stream`,
and the MCP server will too. See
[The JSON result](../reference/json-result.md).

## Changed: one way to start a run

The command line and `certo-server` now prepare a run with the same
code, the first step toward the MCP server. Two small differences
between them are gone:

- A project folder that `certo-server` creates for a task's `project`
  is remembered as created by Certo, as one from `--project` is, so a
  later run there doesn't warn that the folder isn't a clean git
  repository.
- `--escalate` with `--model` now says `--escalate can't be combined
  with --model`; with `--auto-model`, the message is as before.
