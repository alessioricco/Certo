# Server API

Every endpoint of `certo-server`, with its fields and responses. It is for
looking things up; the guide is [Run as a server](../guides/run-as-a-server.md).

> **No endpoint has authentication.** Run the server on `127.0.0.1`, or
> behind a gateway that checks callers.

All request and response bodies are JSON. A configuration error in a
request (an unknown execution mode, an invalid project name,
`agents_md` without `project`, an invalid acceptance check) returns `400`
before any task starts.

## Task request fields

`POST /tasks` and `WS /tasks/stream` take the same fields:

| Field | Type | Required | Meaning |
|---|---|---|---|
| `task` | string | yes | The task text. URLs and file paths are **not** resolved, unlike the `certo` command. |
| `project` | string | no | As `--project`: work in `CERTO_PROJECTS_DIR/<project>`. Must be relative, with no `..`. |
| `execution` | string | no | `local` or `docker`, as `--execution`. |
| `agents_md` | string | no | As `--agents-md`. Needs `project`. |
| `model` | string | no | As `--model`, for this task only. |
| `api_key` | string | no | As `--api-key`, for this task only. |
| `base_url` | string | no | As `--base-url`, for this task only. |
| `reasoning_effort` | string | no | As `--reasoning-effort`, for this task only. |
| `require_verification` | boolean | no | Default `false`. When `true`, an `inconclusive` or `unchanged` verdict counts as a failure (see below). |
| `acceptance_checks` | list | no | A list of check objects, as `--acceptance-checks`, always inline JSON. See [Acceptance checks](../guides/acceptance-checks.md). |
| `independent_tests` | boolean | no | Default `false`. As `--independent-tests`: tests written from the task before the build, run on the result, reported in `result.independent_tests`. `CERTO_INDEPENDENT_TESTS` turns them on for every task. See [Independent tests](../guides/independent-tests.md). |
| `independent_tests_strict` | boolean | no | Default `false`. As `--independent-tests-strict`: a `verified` task whose independent tests mostly fail ends `independent_failed`. |
| `escalate` | boolean or string | no | As `--escalate`: `true` climbs the ladder named `default` (or one built from the ratings), a string names a ladder in `escalation.yaml`. Can't be combined with `model`. A missing model file or an unknown ladder is a `400`. |

## `GET /health`

```json
{"status": "ok"}
```

## `POST /tasks`

Starts a task in the background and returns at once with `202 Accepted`:

```json
{"task_id": "f4fe313c-...", "status": "pending"}
```

## `GET /tasks/{task_id}`

```json
{
  "task_id": "f4fe313c-...",
  "status": "completed",
  "final_message": "...",
  "verification_state": "verified",
  "completion_contract": {
    "goal": "...",
    "acceptance_criteria": ["..."],
    "verification_checks": ["/path/.venv/bin/python -m pytest -q"],
    "limitations": []
  },
  "acceptance_results": null,
  "rungs": null,
  "result": {"result_version": 1, "verdict": "verified", "...": "..."},
  "messages": [],
  "error": null
}
```

| Field | Meaning |
|---|---|
| `status` | `pending`, `running`, `completed` or `failed`. **`completed` only means the run didn't crash.** |
| `final_message` | The agent's final text, once `completed`. |
| `verification_state` | The verdict. See [Verdicts](verdicts.md). Set when the task ends. |
| `completion_contract` | What the task was checked against: the goal, the acceptance criteria, the exact commands run (`verification_checks`) and what couldn't be checked (`limitations`). |
| `acceptance_results` | One result per acceptance check, or `null` when none were given. |
| `rungs` | With `escalate`: one object per rung that ran, in order, else `null`. Each has `rung`, `name`, `model`, `reasoning_effort` (`null` when none is set), `verdict` (`null` after a provider or run failure), `failure`, `fix_attempts`, `duration_seconds`, `tokens`, `cost`, `cost_known`, `files_created`, `files_modified`, `files_deleted`, `failing_checks`, and `final` (`true` on the rung whose verdict is the task's). |
| `result` | The run's result in the same format as `certo --json` (see [The JSON result](json-result.md)), once the task ends, else `null`. When the run fails with an error, its `verdict` is `null` and its `error` says why. |
| `messages` | Every message so far, growing while the task runs. |
| `error` | Why the task failed, once `failed`. |

With `require_verification: true`, an `inconclusive` or `unchanged` task ends with
`status: "failed"` and `error` explains why. Unknown `task_id`: `404`.

## `DELETE /tasks/{task_id}`

Deletes one task record.

```json
{"task_id": "f4fe313c-...", "deleted": true}
```

Unknown `task_id`: `404`.

## `DELETE /tasks?project=NAME`

Deletes every task record of a project. `deleted` is the number removed;
`0` is not an error.

```json
{"project": "my-api", "deleted": 3}
```

## `WS /tasks/stream`

Send one task request (the fields above) as the first message. The server
then sends messages until the task ends, and closes the connection (code
1000):

| `type` | Meaning |
|---|---|
| `message` | One agent message, with all its fields. |
| `result` | The last message on success: `verification_state`, `completion_contract`, `acceptance_results`, `rungs`, and `result`, the run's [JSON result](json-result.md). |
| `error` | `detail` explains the problem: an invalid request, a run-time error, or an `inconclusive` or `unchanged` verdict with `require_verification: true`. Once the run has started, it also has `result`. |

## `POST /v1/chat/completions`

An OpenAI-compatible endpoint for tools that only speak that format. It
runs the same agent and checks, but returns only the agent's text.

| Field | Meaning |
|---|---|
| `model` | Required by the format, echoed back, **never used** to pick a model. |
| `messages` | Every `system` message is joined in front as context; the **last** `user` message is the task. Earlier assistant messages are ignored. |
| `stream` | `true` for Server-Sent Events, one event per agent message (not per token), ending with `data: [DONE]`. |
| `stream_options` | `{"include_usage": true}` adds a last chunk before `[DONE]` with empty `choices` and the `usage`, as OpenAI does. |
| `project`, `execution` | Certo extensions, as above. No `agents_md` here. |
| `llm_model`, `llm_api_key`, `llm_base_url`, `llm_reasoning_effort` | Certo extensions: the real per-request model settings. |

The response has the usual `chat.completion` shape. It has no verdict, and
an `Authorization` header is ignored. `usage` counts the whole task: every
model call of the agent loop, all models together (the run summary's
tokens), so it is much larger than one chat answer. A
run-time error returns `500`.

## `GET /v1/models`

Lists one model: the configured `CERTO_LLM_MODEL`. It is informative only;
nothing can be selected.

```json
{"object": "list", "data": [{"id": "anthropic/claude-sonnet-5-5", "object": "model", "owned_by": "certo"}]}
```

## Not supported over the API

Interactive mode and confirm mode need a terminal. With
`CERTO_CONFIRM_MODE=always`, a task stops with `confirmation_required`.
