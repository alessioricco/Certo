# Run as a server

This guide shows how to run Certo as an HTTP server, so an editor plugin,
a dashboard or a script can send tasks over the network. It covers
starting the server, the three ways to send a task, and keeping task
records.

> **The server has no authentication.** Anyone who can reach it can make
> the agent run commands on the machine. Run it on `127.0.0.1` (the
> default), or behind your own gateway that checks who is calling.

## Start the server

```bash
uv tool install "certo[server]"      # or: pip install "certo[server]"
certo-server --host 127.0.0.1 --port 8000
```

The server reads the same settings as the `certo` command, and refuses to
start if they are invalid (for example, no `CERTO_LLM_MODEL`).

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok"}
```

## Send a task and check on it later

`POST /tasks` starts the task and returns at once with a task id:

```bash
curl -X POST http://127.0.0.1:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"task": "Create HELLO.txt with the line: hi.", "project": "my-api"}'
# {"task_id": "f4fe313c-...", "status": "pending"}
```

Then ask for its state with `GET /tasks/{task_id}`:

```bash
curl http://127.0.0.1:8000/tasks/f4fe313c-...
```

`status` goes `pending` → `running` → `completed` or `failed`.

**`completed` only means the run didn't crash. It doesn't mean the work is
correct.** Read `verification_state` for that: it holds the same verdict
the `certo` command prints, such as `verified` or `retry_exhausted`.

To make `inconclusive` count as a failure, send
`"require_verification": true`. An `inconclusive` task then ends with
`status: "failed"` and an explanation in `error`.

## Stream a task live

`WS /tasks/stream` takes the same request as the first WebSocket message
and sends every message of the agent as it happens:

```python
import json
from websockets.sync.client import connect

with connect("ws://127.0.0.1:8000/tasks/stream") as ws:
    ws.send(json.dumps({"task": "Create HELLO.txt with the line: hi.", "project": "my-api"}))
    while True:
        print(json.loads(ws.recv()))   # raises ConnectionClosedOK when the run ends
```

The last message before the server closes the connection has
`"type": "result"` and the verdict.

## Use it from an OpenAI-compatible client

> **Experimental.** This endpoint works and is tested, but isn't yet proven in real use, and may change between minor versions. See [Experimental features](../README.md#experimental-features).

Tools that can only talk to an OpenAI-style API can use
`POST /v1/chat/completions`:

```bash
curl -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "certo", "messages": [{"role": "user", "content": "Create HELLO.txt with the line: hi."}]}'
```

Know its limits:

- `model` is required by the format but ignored: Certo uses its configured
  model. To change it per request, send `llm_model` (and `llm_api_key`,
  `llm_base_url`, `llm_reasoning_effort`).
- Only the last user message becomes the task. Earlier answers are not
  replayed.
- The answer doesn't include Certo's verdict. Use `POST /tasks` when you
  need it.
- `usage` counts the tokens of the whole task, every model call of the
  agent and every model it used, not one answer. Streaming sends whole
  messages, not tokens.
- An `Authorization` header is ignored, not checked.

## Keep task records

By default, task records live in the server's memory and are lost on
restart. For records that survive restarts or are shared between several
server processes, set `CERTO_TASK_STORE`:

> **Experimental.** Every store except `memory` works and is tested, but isn't yet proven in real use, and may change between minor versions. See [Experimental features](../README.md#experimental-features).

| Store | Install | Good for |
|---|---|---|
| `memory` (default) | nothing | One process; records lost on restart. |
| `sqlite` | `certo[store-sqlite]` | One process; one local file. |
| `mysql` | `certo[store-mysql]` | Several processes. |
| `postgres` | `certo[store-postgres]` | Several processes. |
| `redis` | `certo[store-redis]` | Several processes. |

The connection settings for each store are in
[Configuration](../reference/configuration.md#server-task-records).

To delete old records automatically, set `CERTO_TASK_TTL_SECONDS` (default
`0`, keep forever). Finished tasks older than that are removed; running
tasks never are.

To see the records, or delete them by hand, use `certo-admin`, which
talks to the store directly, without a running server, or the API for
deleting:

```bash
certo-admin list --project my-api
curl -X DELETE "http://127.0.0.1:8000/tasks?project=my-api"
certo-admin delete-project my-api
certo-admin delete-task f4fe313c-...
certo-admin purge --ttl-seconds 86400
```

## Not available in server mode

Interactive mode and confirm mode need a terminal. See
[Interactive and confirm mode](interactive-mode.md#in-server-mode).

## Related

- Every endpoint and field: [Server API](../reference/server-api.md)
- [Safety](../concepts/safety.md)
