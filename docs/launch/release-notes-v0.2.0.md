# Certo v0.2.0

Not released yet.

## New: `certo --json`

`certo "task" --json` prints the run's result as one JSON object on
standard output, and everything else on standard error: the verdict,
each check with the end of its output, the acceptance checks, the time,
tokens and cost per model, the ladder's rungs and the milestones. A
script or a CI job reads it instead of the terminal text. The MCP
server will return the same object. See
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
