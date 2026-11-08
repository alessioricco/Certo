# The JSON result

`certo "task" --json` prints the run's result as one JSON object on
standard output, and everything else (the agent's steps, Certo's
notices, the summary) on standard error. A script or a CI job reads the
verdict from it instead of parsing the terminal text. `certo-server`
returns the same object as `result` (see [Server API](server-api.md)),
and so does the MCP server.

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
  "certo_version": "0.2.0",
  "task": "Write slug.py with a function slug(text) that lower-cases text and joins its words with '-', and a pytest test for it.",
  "project": "json-check-2",
  "workspace": "/home/me/certo-projects/json-check-2",
  "verdict": "verified",
  "limitations": [],
  "checks": [
    {
      "name": "pytest",
      "command": "/home/me/certo-projects/json-check-2/.venv/bin/python -m pytest -q",
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
  "files_changed": {
    "created": [
      "README.md",
      "slug.py",
      "test_slug.py"
    ],
    "modified": [],
    "deleted": []
  },
  "usage": {
    "duration_seconds": 24.2,
    "total_tokens": 116821,
    "prompt_tokens": 113453,
    "completion_tokens": 3368,
    "cache_read_tokens": 91793,
    "cost": 0.005309,
    "cost_known": true,
    "condensations": 0,
    "blocked_outside_root": 0,
    "models": [
      {
        "model": "anthropic/claude-haiku-5-5",
        "reasoning_effort": null,
        "prompt_tokens": 113453,
        "completion_tokens": 3368,
        "cache_read_tokens": 91793,
        "cost": 0.005309,
        "cost_known": true
      }
    ]
  },
  "rungs": null,
  "model_decisions": null,
  "skills": ["testing-and-verification", "pytest-conventions"],
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
| `tool_call_reminders` | How many times Certo sent the agent back because it wrote a tool call as text or ended its turn on a sentence of plans (see [`CERTO_TOOL_CALL_REMINDERS`](configuration.md)). With `--escalate`, the sum over the rungs. Not in results from before Certo 0.2.1. |
| `independent_tests` | With `--independent-tests`: `status`, `summary`, the `model` that wrote them, `output_tail` (the end of their output), and `sets`, each set's `status` and `summary`. Otherwise `null`. See [Independent tests](../guides/independent-tests.md). |
| `check_file_changes` | Changes the agent made to the files the checks rely on, such as the test files: `path`, `deleted`, and the lines `removed`, `added` and `changed`. |
| `files_changed` | The files the run created, modified and deleted in the project folder, each a list of paths relative to it, compared before and after the run (Certo's own files, `.certo/`, `.git/`, environments, caches and build output such as `dist/` or `target/` left out). `null` when the run stopped with an error. |
| `usage` | Time and tokens for the whole run: `duration_seconds`, `total_tokens`, `prompt_tokens` (cached ones included), `completion_tokens`, `cache_read_tokens`, `cost` in US dollars, `cost_known` (false when a model has no price), `condensations`, `blocked_outside_root` (actions Certo blocked because they reached outside the project root), and the same per model in `models`. `null` when the run stopped with an error. |
| `rungs` | With `--escalate`: one entry per model that ran, with `final: true` on the one whose verdict this is, and the fields listed for `rungs` in [Server API](server-api.md#get-taskstask_id). Otherwise `null`. See [Escalate between models](../guides/escalate-between-models.md). |
| `model_decisions` | With `--escalate` or `--auto-model`: how each model was chosen, as `MODEL_DECISIONS.md` in the project tells it. Each decision has `kind`, `timestamp`, `task_profile` and `weights` (with `--auto-model`), `candidates` (each `name` and `score`), `scored_by` (`score`, a weighted rating, with `--auto-model`; `capability` on a ladder), `chosen` and `reason`. Otherwise `null`. An example follows the table. |
| `skills` | The skills the run had, by name: the always-on ones first, then those its task's words, a file the agent touched, or the agent itself brought in. Empty when none (and when the run stopped with an error). For milestones, the last milestone's; each milestone's own are under `milestones`. |
| `milestones` | With `--milestones`: each milestone's `number`, `title`, `verdict` (`null` if it didn't start), `skills` and `usage` (its own run's time, tokens, cost and models, in the same form as the top-level `usage`; both `null` when it didn't run in this session). Otherwise `null`. |
| `error` | Why the run stopped without a verdict (`interrupted`, or the error), or `null`. |

The result never holds an API key.

A run with `--escalate hard` (a ladder of three cloud models) that ended
`verified` on its first rung has two decisions, the ladder and the stop
(the second shown in part):

```json
"model_decisions": [
  {
    "kind": "ladder",
    "timestamp": "2026-11-01T19:14:33.537743+00:00",
    "task_profile": null,
    "weights": {},
    "scored_by": "capability",
    "candidates": [
      {"name": "claude-sonnet-5-5 (effort high)", "score": 13.0},
      {"name": "claude-opus-5-5 (effort high)", "score": 15.0},
      {"name": "gpt-6.1-sol (effort high)", "score": 13.0}
    ],
    "chosen": "claude-sonnet-5-5 (effort high)",
    "reason": "Explicit ladder 'hard' from escalation.yaml."
  },
  {
    "kind": "escalation_stop",
    "chosen": "claude-sonnet-5-5 (effort high)",
    "reason": "claude-sonnet-5-5 ended verified, which doesn't escalate."
  }
]
```

## Related

- [Commands](commands.md#certo)
- [Verdicts](verdicts.md)
- [Verify in CI](../guides/verify-in-ci.md)
- [Server API](server-api.md)
