# Acceptance checks

This guide shows how to add your own pass or fail rules to one task, on
top of the project's tests. For example: "the task is only done if
`README.md` exists and has a `## Usage` section".

## Write the checks

Acceptance checks are a JSON list. Each item checks one file in the
task's folder:

```json
[
  {"kind": "file_exists", "path": "README.md"},
  {
    "kind": "file_contains",
    "path": "README.md",
    "contains": "## Usage",
    "required": false,
    "description": "README documents usage"
  }
]
```

| Field | Required | Meaning |
|---|---|---|
| `kind` | yes | `file_exists` or `file_contains`. There are no other kinds. |
| `path` | yes | A path inside the task's folder. Absolute paths and `..` are rejected, and so is a symlink that leads outside the folder. |
| `contains` | for `file_contains` | Text that must appear in the file. Not allowed for `file_exists`. Only the first 1 MB of the file is read. |
| `required` | no | `true` by default. See below. |
| `description` | no | A label used in reports instead of the kind and path. |

## Use them

Pass the JSON inline, or the path to a file that holds it:

```bash
certo "Write a README for this tool" --acceptance-checks checks.json
certo "Write a README for this tool" --acceptance-checks '[{"kind": "file_exists", "path": "README.md"}]'
```

In server mode, send the list in the `acceptance_checks` field of
`POST /tasks` or the WebSocket request. See
[Server API](../reference/server-api.md).

## What happens to the verdict

All checks run at the end of every task, whatever the verdict.

- If a **required** check fails and the verdict would have been
  `verified`, it becomes `acceptance_failed` (exit code 1).
- Any other verdict stays as it was: the task already failed in another
  way.
- A failing **optional** check (`"required": false`) is listed under the
  verdict but never changes it.

Failed acceptance checks are not sent back to the agent for another try.
Instead, the agent knows them from the start: Certo adds them to the
task, in plain words, for example:

```text
When you finish, Certo checks that each of these holds; the task isn't done until the required ones do:
- NOTES.md contains the text "## Part 2"
- the file dist/index.html exists
```

And when the time budget is nearly used up, Certo's wrap-up message (see
[`CERTO_MAX_TASK_SECONDS`](../reference/configuration.md)) names the
required checks that don't hold yet.

## Why there is no "run this command" check

A command check would let whoever sends the task run any command on the
machine, outside the agent and outside confirm mode. Server mode has no
login, so that would be dangerous. File checks, limited to the task's
folder, don't have this problem.

## Related

- [Run a task in milestones](run-in-milestones.md): an `acceptance` block per milestone
- [Verdicts](../reference/verdicts.md)
- [Safety](../concepts/safety.md)
