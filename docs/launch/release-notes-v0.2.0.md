# Certo v0.2.0

Not released yet.

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
