# The JSON result

`certo "task" --json` prints the run's result as one JSON object on
standard output, and everything else (the agent's steps, Certo's
notices, the summary) on standard error. A script or a CI job reads the
verdict from it instead of parsing the terminal text. `certo-server`
returns the same object as `result` (see [Server API](server-api.md)),
and so will the MCP server.

```bash
certo "Write slug.py with a function slug(text) ..." --project json-check --json > result.json
```

The exit code is the same as without `--json` (see
[Verdicts](verdicts.md)).

## When there is no result

When Certo refuses to start (a wrong setting, options that don't go
together), nothing is printed on standard output: the error is on
standard error, and the exit code is 1. Once the run has started, the
result is always printed, also when the run stops with an error or is
interrupted.

## A real result

From a run on `anthropic/claude-haiku-5-5` (the folder paths are
shortened):

```json
{
  "result_version": 1,
  "certo_version": "0.1.27",
  "task": "Write slug.py with a function slug(text) that lower-cases text and joins its words with '-', and a pytest test for it.",
  "project": "json-check",
  "workspace": "/home/me/certo-projects/json-check",
  "verdict": "verified",
  "limitations": [],
  "checks": [
    {
      "name": "pytest",
      "command": "/home/me/certo-projects/json-check/.venv/bin/python -m pytest -q",
      "primary": true,
      "status": "passed",
      "exit_code": 0,
      "summary": "pytest passed",
      "output_tail": "....                                                                     [100%]\n4 passed in 0.01s\n"
    }
  ],
  "acceptance": [],
  "retries_used": 0,
  "independent_tests": null,
  "check_file_changes": [],
  "usage": {
    "duration_seconds": 20.2,
    "total_tokens": 93731,
    "prompt_tokens": 91249,
    "completion_tokens": 2482,
    "cache_read_tokens": 70610,
    "cost": 0.004527,
    "cost_known": true,
    "condensations": 0,
    "models": [
      {
        "model": "anthropic/claude-haiku-5-5",
        "reasoning_effort": null,
        "prompt_tokens": 91249,
        "completion_tokens": 2482,
        "cache_read_tokens": 70610,
        "cost": 0.004527,
        "cost_known": true
      }
    ]
  },
  "rungs": null,
  "milestones": null,
  "error": null
}
```

## The fields

| Field | What it is |
|---|---|
| `result_version` | The format's version, now `1`. It goes up only when a field is renamed, removed or changes meaning; a new field doesn't change it, so ignore fields you don't know. |
| `certo_version` | The Certo that ran. |
| `task` | The task text. On `--resume`, the task of the run that was resumed. |
| `project` | The `--project` name, or `null`. |
| `workspace` | The project folder, as a full path. |
| `verdict` | The verification state (see [Verdicts](verdicts.md)), or `null` when the run stopped before it had one. |
| `limitations` | What Certo couldn't check, one sentence each. |
| `checks` | The last verification's checks. Each has `name`, `command`, `primary` (the project's main test or build check), `status` (`passed`, `failed`, `skipped`, `unavailable` or `timed_out`), `exit_code`, `summary`, and `output_tail`: the last 4,000 characters of its output. |
| `acceptance` | The [acceptance checks](../guides/acceptance-checks.md): each check's fields, `passed` and `detail`. Empty when there were none. |
| `retries_used` | How many times Certo sent the agent back to fix failing checks. |
| `independent_tests` | With `--independent-tests`: `status`, `summary` and the `model` that wrote them. Otherwise `null`. See [Independent tests](../guides/independent-tests.md). |
| `check_file_changes` | Changes the agent made to the files the checks rely on, such as the test files: `path`, `deleted`, and the lines `removed`, `added` and `changed`. |
| `usage` | Time and tokens for the whole run: `duration_seconds`, `total_tokens`, `prompt_tokens` (cached ones included), `completion_tokens`, `cache_read_tokens`, `cost` in US dollars, `cost_known` (false when a model has no price), `condensations`, and the same per model in `models`. `null` when the run stopped with an error. |
| `rungs` | With `--escalate`: one entry per model that ran, with `final: true` on the one whose verdict this is. Otherwise `null`. See [Escalate between models](../guides/escalate-between-models.md). |
| `milestones` | With `--milestones`: each milestone's `number`, `title` and `verdict` (`null` if it didn't start). Otherwise `null`. |
| `error` | Why the run stopped without a verdict (`interrupted`, or the error), or `null`. |

The result never holds an API key.

## Related

- [Commands](commands.md#certo)
- [Verdicts](verdicts.md)
- [Verify in CI](../guides/verify-in-ci.md)
- [Server API](server-api.md)
