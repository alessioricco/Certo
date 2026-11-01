# Use Certo from an editor or an agent (MCP)

`certo mcp` runs Certo as an [MCP](https://modelcontextprotocol.io)
server ([experimental](../README.md#experimental-features)). An editor or an agent that speaks MCP, such as Claude Code, can
then hand a coding task to Certo and get back Certo's verdict: whether
the project's own tests and checks pass, not only the agent's word.

The server runs on your machine, started by the client, and talks to it
over stdio. It uses the model and keys in your Certo settings, not the
client's model.

## Add it to a client

The client starts the command itself, so Certo must find its settings
without a terminal. The simplest place is the user settings file that
`certo init` writes (`~/.config/certo/.env`, see
[Configuration](../reference/configuration.md)).

**Claude Code:**

```bash
claude mcp add certo -- uvx certo mcp
```

**Any other client** takes the same command in its MCP settings, usually
as JSON:

```json
{
  "mcpServers": {
    "certo": {
      "command": "uvx",
      "args": ["certo", "mcp"]
    }
  }
}
```

With Certo installed (`uv tool install certo`), the command can be
`certo` with the arguments `["mcp"]`.

## Where the tools may work

A tool works only in:

- a **project**, by name: a folder under `CERTO_PROJECTS_DIR`, created
  when it doesn't exist yet, as with `certo --project NAME`;
- a **folder**, by full path, inside one of the folders given with
  `--root` when the server starts (or inside `CERTO_PROJECTS_DIR`).

Anything else is refused:

```text
Error executing tool run_task: /etc is outside the folders this server may use: ...
```

To let it work on your own code, add the folder that holds it:

```bash
claude mcp add certo -- uvx certo mcp --root /home/me/code
```

The limit is in the command the client runs, where you can see it. MCP
once had a way for the client to tell the server its folders ("roots");
the MCP specification of 2026-07-28 deprecates it, together with sampling
and logging ([SEP-2577](https://modelcontextprotocol.info/seps/2577-deprecate-roots-sampling-and-logging/),
and the
[Python SDK's list of deprecated features](https://py.sdk.modelcontextprotocol.io/v2/deprecated/)),
so Certo doesn't use it.

## The tools

| Tool | What it does |
|---|---|
| `run_task` | Start a task in a `project` or `folder`. Returns at once with a `run_id`. Optional: `model`, `escalate` (a ladder name, `""` for the default), `acceptance_checks` (as in `--acceptance-checks`). |
| `run_status` | A run's `state` (`running`, `finished`, `cancelled` or `error`) and, once it ended, its `result`: the same object `certo --json` prints. See [The JSON result](../reference/json-result.md). |
| `run_events` | The agent's messages and Certo's notices so far, numbered. Pass the last call's `next` as `since` to get only the new ones. |
| `run_cancel` | Stop a run at the agent's next step. The work is kept; `certo --resume` in its folder continues it. |
| `list_runs` | The runs this server started. |
| `verify` | Run Certo's checks on a project or folder without an agent, as `certo verify` does. |
| `check_model` | One small call to the configured model, as `certo check` does. |

`run_task` is marked as able to change files, since the agent can
change any file in the folder and run commands there, so a client asks
you before it runs. One run per folder at a time; runs in different
folders go in parallel.

## A real run

A client (the `mcp` Python package's own) started `certo mcp`, ran a
task on `claude-haiku-5-5`, followed it, and checked the project again:

```text
tools: ['run_task', 'run_status', 'run_events', 'run_cancel', 'list_runs', 'verify', 'check_model']
started: running 766f6259a122
ended: finished verified events 18 cost 0.005232
verify: verified [('pytest', 'passed')]
outside: True Error executing tool run_task: /etc is outside the folders t
```

## Good to know

- **The server has no login.** Over stdio only the client that started
  it can reach it. There is no HTTP mode yet: it will come with
  authentication.
- **Runs live as long as the server.** When the client closes, the
  server stops and a run still going stops with it. Its state is in the
  project's `.certo/` folder, so `certo --resume` continues it.
- **A run never waits for a person.** Interactive mode has no effect
  over MCP. With `CERTO_CONFIRM_MODE=always`, the first action that needs
  an approval is rejected and the run ends `confirmation_required` (see
  [Verdicts](../reference/verdicts.md)), as in server mode.
- **Nothing on standard output but the protocol.** The agent's steps
  and the checks' output go to standard error, which most clients keep
  in their MCP log.

## Related

- [Commands](../reference/commands.md#certo-mcp)
- [The JSON result](../reference/json-result.md)
- [Resume an interrupted run](resume-a-run.md)
- [Run as a server](run-as-a-server.md) (HTTP, for scripts and dashboards)
