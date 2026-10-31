# Configuration

Every setting Certo reads: its default, what it does, and where Certo looks
for it. It is for looking things up. To set up a model the easy way, see
[Getting started](../getting-started.md).

## Where Certo looks

All settings are environment variables. Certo looks for each one in three
places, in this order, and uses the first value it finds:

| Order | Place | Written by |
|---|---|---|
| 1 | A variable exported in your shell | you |
| 2 | `.env` in the folder where you run `certo` | you, or `certo init --local` |
| 3 | The user settings file: `$XDG_CONFIG_HOME/certo/.env`, or `~/.config/certo/.env` when `XDG_CONFIG_HOME` is not set or not an absolute path. The same path on macOS, Linux and Windows. | `certo init` (the default, `--global`) |

- Each setting is looked up on its own. A project's `.env` can set only
  `CERTO_LLM_MODEL` and still get `CERTO_LLM_API_KEY` from the user file.
- An empty value (`CERTO_LLM_API_KEY=`) counts as not set, so it doesn't
  hide a value from a later place.
- `${VAR}` inside either file is replaced with the value of `VAR`.
- `certo check` shows where each LLM setting came from.
- `certo verify` reads no settings at all.

Relative paths, such as `./projects`, are relative to the folder where you
run `certo`.

**Value formats.** Yes/no settings accept `1`, `true`, `yes`, `on` and
`0`, `false`, `no`, `off` (any case). Choice settings ignore case. Number
settings must be whole numbers; an invalid value stops Certo with a
`Configuration error` that names the variable.

**Old names.** Before the rename to Certo, settings were called
`HARNESS_*`. An old `HARNESS_` name is still read when the `CERTO_` one is
not set, with a warning to rename it. This does not apply to the LLM
settings: the bare `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL` and
`LLM_REASONING_EFFORT` (used up to version 0.1.1) are never read, so other
tools' variables can't leak in. If one is set while the `CERTO_LLM_` one is
missing, the error message names it.

## Model

| Variable | Default | Meaning |
|---|---|---|
| `CERTO_LLM_MODEL` | **required**, unless the model files pick the model (`--escalate`, `--auto-model`, `CERTO_MODEL_SELECTION`) | The model, as a [LiteLLM model id](https://docs.litellm.ai/docs/providers): `provider/model`, e.g. `anthropic/claude-sonnet-5-5`, `openai/gpt-6.1-sol`, `ollama/qwen3.8:27b`. Changing this is the only thing needed to switch provider. |
| `CERTO_LLM_API_KEY` | required, unless `CERTO_LLM_BASE_URL` is set or the model files pick the model | The key for the provider in `CERTO_LLM_MODEL`. |
| `CERTO_LLM_BASE_URL` | empty | The server address, for a local or self-hosted model, e.g. `http://localhost:11434`. In a `.env` file, leave the line with nothing after `=` when unused: `python-dotenv` keeps a trailing `# comment` on an otherwise empty value as the value itself. |
| `CERTO_LLM_REASONING_EFFORT` | empty | How much the model should think: `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, or any value your provider accepts (not checked by Certo). `none` or `off` sends no reasoning setting. Empty means `high`, except for `ollama/` and `ollama_chat/` models, where empty means none. Run output and records name the effort next to the model, and an empty value as `effort default`. |
| `CERTO_LLM_CONTEXT_TOKENS` | `0` | The model's context window (how much it can see at once), in tokens. `0`: what LiteLLM reports for a cloud model; for an Ollama model, Certo asks the server after loading the model. A set value is used instead, and for Ollama it is also asked from the server, so you don't have to restart Ollama with `OLLAMA_CONTEXT_LENGTH`. A window under 16,384 tokens is refused. See [Give the model a large enough context window](../guides/ollama-and-local-models.md#give-the-model-a-large-enough-context-window). |
| `CERTO_LLM_TIMEOUT_SECONDS` | `300` | How long one call to the model may take, in seconds. A call that takes longer fails and is tried again from the start, up to 5 more times. On local runs a call never waits longer than the time left in `CERTO_MAX_TASK_SECONDS`. `0` means no limit. Raise it for slow local models: `certo init` writes `1200` when you choose Ollama. See [Ollama and local models](../guides/ollama-and-local-models.md#slow-answers-and-the-call-timeout). |

Per-run overrides: `--model`, `--api-key`, `--base-url`,
`--reasoning-effort` (see [Commands](commands.md#certo)). The flags are
applied before the required-field checks, so `--model` alone is enough
when `CERTO_LLM_MODEL` is unset, and `--model` with `--base-url` is
enough for a local model that needs no key.

## Where the agent works

| Variable | Default | Meaning |
|---|---|---|
| `CERTO_WORKSPACE` | `.` | The folder the agent works in when `--project` is not given. |
| `CERTO_PROJECTS_DIR` | `./projects` | The parent folder for `--project NAME`, which becomes `CERTO_PROJECTS_DIR/NAME`. |
| `CERTO_NO_WORKTREE_WARNING` | `false` | `true` turns off the warning printed before the agent edits a folder with uncommitted changes, or a folder outside git. |
| `CERTO_CONTEXT_WARN_TOKENS` | `32768` | Warn at the start of a run (and of each escalation rung) when the model's context window is smaller than this, in tokens. The run still starts. Certo knows the window when `CERTO_LLM_CONTEXT_TOKENS` or `context_tokens` sets it, or by asking Ollama; a cloud model's window isn't checked. `0` turns the warning off. Under 16,384 tokens the run is refused instead. See [Give the model a large enough context window](../guides/ollama-and-local-models.md#give-the-model-a-large-enough-context-window). |
| `CERTO_CONDENSE` | `true` | When the conversation nearly fills the model's context window, let the agent framework summarize the older steps (with the same model), keeping the task and the latest steps, instead of failing or, with Ollama, silently losing the start. It only acts near the window (`CERTO_LLM_CONTEXT_TOKENS`), so a run that fits is unchanged. `false` turns it off. See [Run records and costs](../guides/run-records-and-costs.md). |
| `CERTO_CHECKPOINTS` | `true` | During a run, snapshot the project's files into `.certo/checkpoints/` (before the agent, at every check run, at the end), for `certo checkpoints` and `certo rollback`. Needs git; never touches the project's own git repository. Only when the run keeps state (`CERTO_SAVE_STATE`). See [Go back to an earlier point](../guides/checkpoints.md). |
| `CERTO_SAVE_STATE` | `true` | The `certo` command keeps the last run's state in the project's `.certo/` folder, for `certo --resume`, and adds the run to `.certo/RUNS.md`. `false` turns both off (`--resume` still saves). Server mode and `certo bench` never write it. See [Resume an interrupted run](../guides/resume-a-run.md). |

## Limits and verification

| Variable | Default | Meaning |
|---|---|---|
| `CERTO_MAX_ITERATIONS` | `50` | The most steps the agent may take in one run. Each retry after a failed check is a new run with the same limit. A run that uses all its steps is checked like a finished one: passing checks give `verified`, failing checks get the fix attempts (with `--auto-model`, on the next model), and nothing to check gives `stuck`. |
| `CERTO_MAX_TASK_SECONDS` | `1800` | The time budget for the whole task, in seconds: the first run plus every retry. When it runs out, the verdict is `budget_exhausted`. When it runs out during a run, the agent is stopped after its current step. On local runs, neither a terminal command nor a call to the model can wait longer than the time left, and a model call that fails after the budget isn't tried again, so a task ends within a few seconds of its budget. When the agent's last run ends after the budget, Certo still runs the project's checks once, with no fix attempt: passing work is `verified`. |
| `CERTO_TOOL_CALL_REMINDERS` | `3` | When the agent ends with a tool call written as text instead of making it, which some local models do, Certo tells it to make the call and lets it go on, at most this many times per run (each model on an escalation ladder counts its own). A model that makes real tool calls is never sent one. `0` turns this off. See [Troubleshooting](../troubleshooting.md#the-run-ends-at-once-with-a-tool-call-as-the-agents-last-message). |
| `CERTO_VERIFY_TESTS` | `always` | `always` or `never`. With `never`, Certo doesn't check the result, and the verdict is always `inconclusive`. |
| `CERTO_MAX_VERIFY_RETRIES` | `2` | How many times a failure is sent back to the agent to fix. Must be at least 1. Also used for unfinished to-do items. |
| `CERTO_CONFIRM_MODE` | `never` | `never` or `always`. `always` asks you to approve every action. See [Interactive and confirm mode](../guides/interactive-mode.md). |
| `CERTO_INTERACTIVE` | `false` | Let the agent stop and ask you questions. The same as `--interactive`. Has no useful effect in server mode. |
| `CERTO_INDEPENDENT_TESTS` | `false` | Before the build, separate conversations with the same model write sets of tests from the task and the project as it is then; after the verdict, Certo runs them and prints the result under it. Report only: the verdict and exit code don't change (unless `CERTO_INDEPENDENT_TESTS_STRICT`). Local runs only, not on `--resume`. The same as `--independent-tests`. See [Independent tests](../guides/independent-tests.md). |
| `CERTO_INDEPENDENT_TESTS_STRICT` | `false` | When most sets of independent tests fail, a `verified` run ends `independent_failed` (exit 1) instead. Turns the tests on. The same as `--independent-tests-strict`. See [Make them change the verdict](../guides/independent-tests.md#make-them-change-the-verdict). |
| `CERTO_INDEPENDENT_TESTS_SETS` | `3` | How many sets of independent tests are written, each by its own conversation, from 1 to 5. The result is `failed` only when most sets fail (2 of 3), `split` when fewer do. |
| `CERTO_VERBOSE` | `false` | Print the agent's full output: the whole system prompt, the task with the skills Certo adds, and the SDK's `INFO` logs. By default the system prompt and the task are one line each and the `INFO` logs are hidden (the SDK's own `LOG_LEVEL`, when set, still applies). The same as `--verbose`. |

## Execution

| Variable | Default | Meaning |
|---|---|---|
| `CERTO_EXECUTION` | `local` | `local` or `docker`: where the agent's tools run. `docker` is [experimental](../README.md#experimental-features). See [Run in Docker](../guides/run-in-docker.md). |
| `CERTO_DOCKER_IMAGE` | `certo/agent-server:local` | The image for Docker mode. Built on first use from a source checkout. |
| `CERTO_DOCKER_PLATFORM` | `linux/arm64` on ARM machines, `linux/amd64` otherwise | `linux/amd64` or `linux/arm64`. Leave empty to detect. |

## Automatic model selection

| Variable | Default | Meaning |
|---|---|---|
| `CERTO_MODEL_SELECTION` | `manual` | `manual`, `auto` or `escalate`. `auto` is the same as `--auto-model`, `escalate` the same as `--escalate`. |
| `CERTO_MODELS_FILE` | empty | Your personal `models.yaml` (keys, addresses, which models you use). Empty: `./models.yaml`, else `~/.config/certo/models.yaml`. Read when selection is `auto` or `escalate`, and by `certo check`. See [The model files](models-yaml.md). |
| `CERTO_MODELS_LIST_FILE` | empty | The model catalog, `models_list.yaml` (the models and their ratings). Empty: `./models_list.yaml`, else `~/.config/certo/models_list.yaml`. |
| `CERTO_TASK_PROFILES_FILE` | empty | The task profiles for `--auto-model`, `task_profiles.yaml`. Optional. Empty: `./task_profiles.yaml`, else `~/.config/certo/task_profiles.yaml`, else none. |
| `CERTO_ESCALATION_FILE` | empty | The ladders for `--escalate` (and `certo bench`), `escalation.yaml`. Optional. Empty: `./escalation.yaml`, else `~/.config/certo/escalation.yaml`, else none, and `--escalate` derives a ladder from the ratings. |
| `CERTO_MAX_TASK_COST` | empty | A limit, in US dollars, on what one task may spend: every model call, fix attempts, escalation rungs and [independent tests](../guides/independent-tests.md) included. Certo checks the cost every few seconds and stops the agent at its next step once the cost reaches the limit, so a run can end a little over it (the calls made since the last reading are paid for). The checks then run once, and work that fails them ends `cost_exhausted`. With escalation, no rung starts past the limit either. Models with no known price count as 0. `--resume` starts a fresh limit. Empty means no limit. |
| `CERTO_ESCALATION_LADDER` | empty | With `escalate`: the ladder in `escalation.yaml` to climb. Empty uses the ladder named `default`, or one built from the ratings. |
| `CERTO_ESCALATION_HANDOFF` | `continue` | With `escalate`: what the next model starts from. `continue`: the files as the previous model left them. `restart`: the files as they were before the first model, restored from a [checkpoint](../guides/checkpoints.md) (the previous model's work is kept in one). Needs git. See [Start each rung from the original files](../guides/escalate-between-models.md#start-each-rung-from-the-original-files). |

## Skills

Skills are managed with [`certo skills`](commands.md#certo-skills), in
`~/.config/certo/skills/` and `<project>/.certo/skills/`; no setting is
needed. The old folders' settings (`CERTO_SKILLS_DIR`,
`CERTO_THIRD_PARTY_SKILLS_DIR`, `CERTO_THIRD_PARTY_SKILLS_LOCK`) were
removed in 0.1.23; Certo warns while one is still set. See
[Moving from the old folders](../guides/manage-skills.md#moving-from-the-old-folders).

## Run records

| Variable | Default | Meaning |
|---|---|---|
| `CERTO_ARTIFACTS_DIR` | empty (off) | A folder where each run writes `metadata.json`, `transcript.json` and `metrics.json`. See [Run records and costs](../guides/run-records-and-costs.md). |

## Update check

| Variable | Default | Meaning |
|---|---|---|
| `CERTO_UPDATE_CHECK` | on | When a newer Certo is on PyPI, `certo` prints one line at the end of a command, such as `Certo 0.1.28 is out (you have 0.1.27). To update: uv tool upgrade certo`, with the command that matches how Certo was installed (`uv tool`, `pipx` or `pip`). It asks pypi.org at most once a day, in the background, and keeps the answer in `~/.cache/certo/update-check.json` (or under `XDG_CACHE_HOME`). Only in a terminal: never when the output goes to a file or a pipe, in CI (when `CI` is set), or in `certo bench`. `0` turns it off. |

## Server task records

Read only by `certo-server` and `certo-admin`. See
[Run as a server](../guides/run-as-a-server.md#keep-task-records). Every
store except `memory` is [experimental](../README.md#experimental-features).

| Variable | Default | Meaning |
|---|---|---|
| `CERTO_TASK_STORE` | `memory` | `memory`, `sqlite`, `mysql`, `postgres` or `redis`. |
| `CERTO_TASK_TTL_SECONDS` | `0` | Seconds to keep a finished task record. `0` keeps records forever. |
| `CERTO_TASK_STORE_SQLITE_PATH` | `./certo_tasks.db` | sqlite: the database file. |
| `CERTO_TASK_STORE_MYSQL_HOST` | `localhost` | mysql: host. |
| `CERTO_TASK_STORE_MYSQL_PORT` | `3306` | mysql: port. |
| `CERTO_TASK_STORE_MYSQL_USER` | `root` | mysql: user. |
| `CERTO_TASK_STORE_MYSQL_PASSWORD` | empty | mysql: password. |
| `CERTO_TASK_STORE_MYSQL_DATABASE` | `certo` | mysql: database. |
| `CERTO_TASK_STORE_POSTGRES_HOST` | `localhost` | postgres: host. |
| `CERTO_TASK_STORE_POSTGRES_PORT` | `5432` | postgres: port. |
| `CERTO_TASK_STORE_POSTGRES_USER` | `postgres` | postgres: user. |
| `CERTO_TASK_STORE_POSTGRES_PASSWORD` | empty | postgres: password. |
| `CERTO_TASK_STORE_POSTGRES_DATABASE` | `certo` | postgres: database. |
| `CERTO_TASK_STORE_REDIS_HOST` | `localhost` | redis: host. |
| `CERTO_TASK_STORE_REDIS_PORT` | `6379` | redis: port. |
| `CERTO_TASK_STORE_REDIS_DB` | `0` | redis: database number. |
| `CERTO_TASK_STORE_REDIS_PASSWORD` | empty | redis: password. |
| `CERTO_TASK_STORE_REDIS_USE_TLS` | `false` | redis: connect with TLS. |

**Stores created before the rename to Certo** keep working:

- sqlite: if the path is left at its default, `./certo_tasks.db` doesn't
  exist and `./harness_tasks.db` does, the old file is used, with a
  warning.
- SQL table: an old `harness_tasks` table is used (with a warning) when
  there is no `certo_tasks` table. Rename it when convenient:
  `ALTER TABLE harness_tasks RENAME TO certo_tasks`.
- mysql/postgres database: the default name changed from `harness` to
  `certo`, with no automatic fallback. To keep an old database, set
  `CERTO_TASK_STORE_MYSQL_DATABASE=harness` (or the `POSTGRES` one).
- redis: keys moved from `harness:` to `certo:`. Old keys are still read
  and move to the new name when a record is saved.

## Other variables Certo uses

| Variable | Meaning |
|---|---|
| `XDG_CONFIG_HOME` | Changes where the user settings file is (see the table at the top). |
| `XDG_CACHE_HOME` | Changes where the [update check](#update-check) keeps its answer. |
| `CI` | When set, there is no [update check](#update-check). |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `DEEPSEEK_API_KEY`, `MOONSHOT_API_KEY` | Read only by `certo init`, which offers to reuse them (and then writes `CERTO_LLM_API_KEY=${...}`). |
| `OPENHANDS_SUPPRESS_BANNER` | Certo sets it to `1` unless you set it, to hide the OpenHands start-up banner. |
| `LITELLM_MODE` | Certo sets it to `PRODUCTION` unless you set it. Otherwise LiteLLM loads a `.env` file of its own, found from its install folder, which could override your settings. |
