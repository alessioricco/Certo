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
| `run_task` | Start a task in a `project` or `folder`. Returns at once with a `run_id`. Optional: `model`, `escalate` (a ladder name, `""` for the default), `acceptance_checks` (as in `--acceptance-checks`), and `milestones_file`: the full path of a task file in milestones, as in `certo --milestones` (it must be inside the same folders; keep it outside the project, so the agent can't read its acceptance checks), and `independent_tests` / `independent_tests_strict`, as `--independent-tests` and `--independent-tests-strict` (see [Independent tests](independent-tests.md)). |
| `run_resume` | Continue the last run in a `project` or `folder`, as `certo --resume` does: a cancelled or failed run from where it stopped, or a milestones run from the first milestone not `verified`. Optional: `instruction` (an extra message to the agent), `model`, `escalate`. When everything there is already `verified`, it answers `nothing_to_do` instead of starting a run. |
| `run_status` | A run's `state` (`running`, `finished`, `cancelled` or `error`) and, once it ended, its `result`: the same object `certo --json` prints. See [The JSON result](../reference/json-result.md). |
| `run_events` | The agent's messages and Certo's notices so far, numbered. Pass the last call's `next` as `since` to get only the new ones. |
| `run_cancel` | Stop a run at the agent's next step. The work is kept; `run_resume` (or `certo --resume` in its folder) continues it. |
| `list_runs` | The runs this server started. |
| `verify` | Run Certo's checks on a project or folder without an agent, as `certo verify` does. Returns a `run_id` at once, like `run_task`, so a long test suite doesn't hit the client's time limit; `run_status` then gives the verdict and the checks. It can't be cancelled: each check has its own time limit. |
| `checkpoints` | The snapshots Certo took of a project during its runs, as `certo checkpoints` lists them. See [Go back to an earlier point](checkpoints.md). |
| `rollback` | Put a project's files back as they were at a checkpoint `number`, as `certo rollback` does. Without `confirm: true` it only lists what would be restored, added back or deleted. With it, the files are rolled back, and the answer's `undo_with` is the checkpoint that undoes it. Refused while a run works in that folder. |
| `check_model` | One small call to the configured model, as `certo check` does. |
| `list_projects` | The projects under `CERTO_PROJECTS_DIR`, each with its last run (task, status, verdict, model, time) and the `run_id` of a run working there now. |
| `list_models` | The configured model and, when you have [model files](../reference/models-yaml.md), each model with its id, whether it is active, its ratings and description, the ladders `escalate` takes by name, and the files' problems. Never a key. `run_task`'s `model` takes a model id from it. |
| `list_skills` | The skills a run gets, as `certo skills list` shows them: official and yours, and with `project` or `folder` that project's too. Each says how it fires, its size in tokens, and whether it is on. With `task`, which skills would go into a run of that task. |

Some commands have no tool: those that ask you questions (`certo init`,
`certo models update`), `certo bench`, which runs for hours, and the
commands of `certo-server` and `certo-admin`. Run them in a terminal.
The skills commands that download or turn on code (`certo skills add`,
`update`, `sync` and `enable`) never get a tool: accepting a skill's
license, or running code someone else wrote, is for you to decide, not
an agent. `certo skills remove` and `disable` have no tool yet; ask if
you need one.

Each project also has two resources, which a client can show or read:

| Resource | What it holds |
|---|---|
| `certo://projects/NAME/status` | The project's `.certo/STATUS.md`: the last run's task, verdict and checks, and how to continue it. |
| `certo://projects/NAME/runs` | The project's `.certo/RUNS.md`: every run in it, with its verdict, models, time and cost. Runs started over MCP are added too. |

A project with no run yet has neither: reading one is a "not found"
error. See [Run records and costs](run-records-and-costs.md).

`run_task`, `run_resume` and `rollback` are marked as able to change
or delete files, so a client asks you before it runs them: the agent
can change any file in the folder and run commands there. `rollback`
also asks for `confirm: true` itself. One run per folder at a time; runs in different
folders go in parallel.

## A real run

**From Claude Code.** Claude Code was given `certo mcp` as its only MCP
server and asked to start a task in the project `claude-code-check` (a
`fib(n)` function with pytest tests), poll `run_status` until it ended,
and report. Certo ran the task on `claude-haiku-5-5`. Claude Code's
report:

```text
The run finished and was verified.

- run_id: 385209a10416
- Final state: finished
- Verdict: verified
- Checks:
  - pytest: passed (exit 0), "10 passed in 0.01s"
  - No acceptance checks were configured, and there were no limitations or retries.
- Cost: $0.005617 (known), using anthropic/claude-haiku-5-5. Total tokens were
  136,815 (133,361 prompt, 3,454 completion, 111,124 cache read), over 27.5 seconds.

I polled run_status about every 5 seconds, and the state changed from running to
finished on the sixth poll.
```

**Milestones, cancel and resume.** The same client ran a task file in
two milestones (Celsius and Fahrenheit, then Kelvin), then started a
task, cancelled it, continued it with `run_resume`, and asked to continue
it once more:

```text
milestones: finished verified [(1, 'verified'), (2, 'verified')] cost 0.0167
cancelled: cancelled cancelled 2.0s
resumed task: Write a Python module `shapes.py` with a
resumed: finished verified {'created': ['README.md', 'shapes.py', 'test_shapes.py'], 'modified': [], 'deleted': []}
again: nothing_to_do The last run here already ended with 'verified'. To continue
```

**Verify, checkpoints and rollback.** The same client checked a
project, listed its checkpoints, asked what a rollback to checkpoint 1
would do, did it, and undid it:

```text
verify: finished verified [('pytest', 'passed')]
checkpoints: [(1, 'before the agent'), (2, 'checks 1: verified')]
preview: False [{'change': 'deleted', 'path': 'README.md'}, {'change': 'deleted', 'path': 'sub.py'}, {'change': 'deleted', 'path': 'test_sub.py'}]
rolled back: True undo_with 2 files now: ['.certo', '.pytest_cache', '.venv', '__pycache__']
undone: True files now: ['.certo', '.pytest_cache', '.venv', 'README.md', '__pycache__', 'sub.py', 'test_sub.py']
```

**What there is to work with.** The `mcp` package's client listed the
projects, the models and a project's skills for a task, with the
Author's settings:

```text
tools: 13
projects: [('decisions-check', 'verified', None)]
configured: anthropic/claude-sonnet-5-5
ladders: [('default', ['qwen3.8-27b-local', 'claude-haiku-5-5', 'claude-sonnet-5-5', 'gpt-6-luna', 'claude-opus-5-5', 'gpt-6.1-sol']), ('hard', ['claude-sonnet-5-5', 'claude-opus-5-5', 'gpt-6.1-sol']), ('local-only', ['qwen3.6-35b-local', 'qwen3.8-27b-local'])]
derived: ['qwen3.8-27b-local', 'claude-haiku-5-5', 'claude-opus-5-5'] errors: [] warnings: 3
now: [{'name': 'pytest-conventions', 'layer': 'official', 'why': '"pytest" is in the task'}]
later: ['pin-dependencies']
```

**From a script.** The `mcp` Python package's own client started
`certo mcp`, ran a task on `claude-haiku-5-5`, followed it, checked the
project again, and tried a folder it may not use:

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
  project's `.certo/` folder, so `run_resume` (next time) or
  `certo --resume` continues it.
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
