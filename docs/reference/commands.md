# Commands

Every command, subcommand and flag Certo installs. It is for looking
things up; for a walk-through, see [Getting started](../getting-started.md).

Certo installs three commands: `certo`, `certo-server` and `certo-admin`.
`certo` also has these subcommands: `certo verify`, `certo init`,
`certo check`, `certo models`, `certo skills`, `certo bench`,
`certo checkpoints`, `certo rollback`, `certo report`, `certo ask` and `certo mcp`. Every command and
subcommand accepts `-h` / `--help`; `certo --help` lists the subcommands
under `commands:`, after the options.

All three commands hide the OpenHands SDK's start-up banner. Set
`OPENHANDS_SUPPRESS_BANNER=0` to see it.

## `certo`

Run a task through the agent, then verify the result.

```text
certo TASK [--project NAME] [--execution {local,docker}] [--model MODEL]
           [--api-key KEY] [--base-url URL] [--reasoning-effort LEVEL]
           [--agents-md TEXT] [--independent-tests] [--independent-tests-strict]
           [--interactive] [--verbose] [--max-steps N] [--max-time MINUTES]
           [--auto-model]
           [--json] [--require-verification] [--acceptance-checks JSON_OR_FILE]
           [--escalate [LADDER]] [--milestones] [--from-milestone N]
certo --resume [TASK] [same options]
certo                     # in a terminal: the interactive session
certo -i [TASK] [options] # the session, starting with TASK
```

In a terminal, `certo` with no task and `certo -i` (`--interactive`)
open the interactive session: a header, a prompt where each message is a
task (the next ones continue it), `/` commands, and a status line with
switches. See [The interactive session](../guides/interactive-mode.md#the-interactive-session).
Without a terminal (a pipe, CI) or with `--json`, nothing opens: `certo`
alone is a usage error and `--interactive` keeps the plain prompts.

**`TASK`** (required, except with `--resume`) is one of, checked in this order:

1. an `http://` or `https://` URL: the page is downloaded (15-second
   limit) and used as the task;
2. the path of an existing file: the file is read (UTF-8);
3. anything else: the text itself is the task.

An empty file or page is an error. Only `http` and `https` URLs are
fetched. Note: if your task text is exactly the name of a file in the
current folder, the file is read instead.

| Flag | Default | Effect |
|---|---|---|
| `--version` | | Print the version, e.g. `certo 0.1.5`, and exit. |
| `--project NAME` | none | Work in `CERTO_PROJECTS_DIR/NAME`, created if missing. Without it, Certo works in `CERTO_WORKSPACE` (default: the current folder), except in a Certo workspace, where a new task gets a project named after it (see "The project folder" below). `NAME` must be a relative path with no `..`, and must stay inside `CERTO_PROJECTS_DIR`. |
| `--execution {local,docker}` | `CERTO_EXECUTION` | Where the agent's tools run, for this run. `docker` is [experimental](../README.md#experimental-features). See [Run in Docker](../guides/run-in-docker.md). |
| `--model MODEL` | `CERTO_LLM_MODEL` | Model for this run only. Enough on its own: you do not need `CERTO_LLM_MODEL` set already. |
| `--max-steps N` | `CERTO_MAX_ITERATIONS` (50) | The most steps the agent may take in this run. In milestone mode each milestone gets `N` steps, and so does each fix attempt after a failed check. `N` is 1 or more. |
| `--max-time MINUTES` | `CERTO_MAX_TASK_SECONDS` (30 minutes) | The time budget for this run, in minutes: the first run plus every retry. In milestone mode each milestone gets `MINUTES`. `MINUTES` is 1 or more. |
| `--api-key KEY` | `CERTO_LLM_API_KEY` | API key for this run only. It ends up in your shell history. |
| `--base-url URL` | `CERTO_LLM_BASE_URL` | Server address for this run only. With `--model`, enough for a local model that needs no key. |
| `--reasoning-effort LEVEL` | `CERTO_LLM_REASONING_EFFORT` | Reasoning effort for this run only: `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, or any value the provider accepts. `none` or `off` turns it off. |
| `--agents-md TEXT` | none | Write `TEXT` as the project's `AGENTS.md` before the task. Needs `--project`. |
| `--independent-tests` | off (`CERTO_INDEPENDENT_TESTS`) | Before the build, have tests written from the task and the project as it is; after the verdict, run them and print the result under it. Report only: the verdict and exit code don't change. Local runs, not on `--resume`. See [Independent tests](../guides/independent-tests.md). |
| `--independent-tests-strict` | off (`CERTO_INDEPENDENT_TESTS_STRICT`) | Like `--independent-tests`, but when most sets fail, a `verified` run ends `independent_failed` (exit 1). Other verdicts stay as they are. See [Make them change the verdict](../guides/independent-tests.md#make-them-change-the-verdict). |
| `-i`, `--interactive` | off (`CERTO_INTERACTIVE`) | In a terminal: open the [interactive session](../guides/interactive-mode.md#the-interactive-session) and start `TASK` in it (other flags apply to that first task). Without a terminal: let the agent stop and ask you questions. See [Interactive and confirm mode](../guides/interactive-mode.md). |
| `--verbose` | off (`CERTO_VERBOSE`) | Print the agent's full output: the whole system prompt, the task with the skills Certo adds, and the SDK's own logs. Without it, each of these is one line. |
| `--auto-model` | off (`CERTO_MODEL_SELECTION`) | Pick the model from the model files (`models_list.yaml`, `models.yaml`, and the task profiles in `task_profiles.yaml`). Refused without task profiles (no `task_profiles.yaml`, or one with no profile): every model would rank the same, and the first in `models_list.yaml` would go first. The error names `certo init models --profiles`. A missing or broken model file is a configuration error (the error says which example to copy, or lists the problems): no banner, no resume hint, and no run is recorded. See [Pick models automatically](../guides/pick-models-automatically.md). |
| `--json` | off | Print the run's result as one JSON object on standard output (verdict, checks, acceptance checks, cost, models, milestones), and everything else on standard error. Nothing on standard output when Certo refuses to start. See [The JSON result](json-result.md). |
| `--require-verification` | off | Exit 1 for `inconclusive` and `unchanged` too. |
| `--acceptance-checks JSON_OR_FILE` | none | Extra file checks for this task, as inline JSON or a JSON file. See [Acceptance checks](../guides/acceptance-checks.md). |
| `--escalate [LADDER]` | off (`CERTO_MODEL_SELECTION`) | Start on the first rung of a ladder of models from `escalation.yaml`, and move to the next model only when Certo's verdict shows the model couldn't finish, or its provider fails (outage, rate limit, rejected key). The time budget (`budget_exhausted`) and `CERTO_MAX_TASK_COST` stop the climb. `LADDER` names a ladder; without it, the ladder named `default` is used, else one built from the ratings. With only one value after the flag, as in `certo --escalate "Fix the crash"`, that value is the task. Can't be combined with `--auto-model` or `--model`, nor with `--resume` except after `--milestones`, where it starts the milestone again on the first rung. A missing model file (the error says which example to copy) or an unknown ladder is a configuration error that lists the ladders found. See [Escalate between models](../guides/escalate-between-models.md). |
| `--milestones` | off | Run the task file milestone by milestone: each `## Milestone N: title` heading starts one, run in its own conversation and verified before the next starts; the first that isn't `verified` stops the task with its verdict. A milestone may hold an ` ```acceptance ` block, in the `--acceptance-checks` format. Needs a task file (not text or a URL). With `--escalate`, each milestone climbs its own ladder from the first rung; with `--independent-tests`, each gets its own tests. A task file with no milestone heading, or a broken block, is an error before any model call. A heading may also be short (`## M1 — title`), with `-`, `—`, `–` or `.` instead of `:`, and numbering may start at 0. Without the flag, a task file written in milestones (two or more such headings, numbered 1, 2, 3... or 0, 1, 2... in order, outside code blocks) runs this way too, and Certo says so first. [Experimental](../README.md#experimental-features). See [Run a task in milestones](../guides/run-in-milestones.md). |
| `--from-milestone N` | off | With a task file in milestones: start at milestone `N`, the number Certo shows (`Milestone N of M`), and skip those before it; a later `--resume` keeps skipping them. `--from-milestone 1` runs every milestone again. Without it, a task file run again in the same project, unedited, goes on from the first milestone not `verified` (in a fresh conversation, told how its last try ended), and says so; an edited file starts from the first. Not with `--resume`. |
| `--no-milestones` | off | Send a task file written in milestones as one task, as it is, instead of milestone by milestone. Its acceptance blocks are then part of the text, and not checked. Not with `--milestones`. |
| `--make-milestones` | off | Before the run, a model splits the task into milestones (2 to 8), saved with the task as written as `.certo/milestones.md` in the project, which then runs as with `--milestones`; the plan is printed, and `--interactive` asks to run it, edit it first, or stop. The model: `CERTO_PLANNER_MODEL`, else with `--auto-model` or `--escalate` the first model of the `planning` task profile, else the run's own. A task the model keeps as one milestone, a plan that can't be read, or a model that fails leaves the task to run as one, as it is. Not with `--milestones`, `--no-milestones`, `--resume`, `--from-milestone`, or a task already written in milestones. [Experimental](../README.md#experimental-features). See [Let Certo write the milestones](../guides/run-in-milestones.md#let-certo-write-the-milestones). |
| `--resume` | off | Continue the last run in this folder (or in `--project NAME`) from the state in its `.certo/` folder. `TASK` is optional and is sent as an extra instruction. Errors when there is no saved state; does nothing (exit 0) when the last run ended `verified` and no `TASK` is given, unless a step, time or cost limit stopped the agent before it said it was done (then it continues the task). After `--milestones`, it continues the first milestone not `verified`, reading the task file again; it refuses when the file is gone or was edited, and does nothing (exit 0) when every milestone is `verified`. With `--escalate`, the milestone starts again on the ladder's first rung in a fresh conversation, told how the last try ended. It keeps how the run it continues chose its models (`--auto-model`, or `--escalate` with its ladder), its time budget and its step limit, and so does a milestone file run again; `--model NAME`, another of those flags or `CERTO_MODEL_SELECTION` chooses the models otherwise, and `--max-time`, `--max-steps`, `CERTO_MAX_TASK_SECONDS` or `CERTO_MAX_ITERATIONS` the budget. Its tokens and cost are only the resumed run's own. When it starts on another model than the session it continues, the terminal and the report say so, and why. See [Resume an interrupted run](../guides/resume-a-run.md). |

**Output.** A run starts with a banner: the Certo version, then one
line each for the model (with `--auto-model` or `--escalate`, how it is
chosen, or the ladder), the project folder, where the commands run
(`this computer` or Docker and its image), the checks (`on`, with
`CERTO_MAX_VERIFY_RETRIES`, or `off`) and the limits
(`CERTO_MAX_TASK_SECONDS`, `CERTO_MAX_ITERATIONS`, and
`CERTO_MAX_TASK_COST` when set). A `Mode` line appears with
`--interactive` or `CERTO_CONFIRM_MODE=always`. For a local server, the
model line shows its host and port; the API key is never shown. A run
refused because of a wrong flag or setting prints only the error, no
banner. With `--resume`, a `Resuming:` line follows; with
`--milestones` (or a resume of milestones), a `Milestones: N` line, then
a `Milestone N of M: title` line before each milestone and one with its
verdict after it. A warning about
uncommitted changes may follow (see [Work on an existing project](../guides/work-on-an-existing-project.md)).
Then one line for the agent's system prompt and one for the task (the
whole text with `--verbose`), the agent's actions and their results as
they happen, and Certo's own notes (a failing check, a model switch, a
step limit) as they happen. At the end: the
`Milestones:` list with each milestone's verdict with `--milestones`, the
`Model used:` line with `--auto-model`, then `Verification: <verdict>`,
any limitations as `-` lines, and the run summary. After a failing
verdict, a last line names `.certo/STATUS.md` and the `certo --resume`
command (unless `CERTO_SAVE_STATE` is off). When `CERTO_PROJECTS_DIR` is
not the default, that command starts with `CERTO_PROJECTS_DIR=...` so a
copy-paste resume uses the same projects folder.

**The project folder.** Without `--project` and without `--resume`, when
the current folder is a Certo workspace (it has the `CERTO_PROJECTS_DIR`
folder, `projects/`, and isn't a project itself), Certo names a project
after the task and works in `projects/<name>`, as if `--project <name>`
was given. The name is the task file's or URL's name (`tasks/wordle.md`
gives `wordle`), else the task's Markdown title, else its first words
(`"Build a crypto price dashboard"` gives `crypto-price-dashboard`). If
that folder exists, Certo uses a new one (`wordle-2`) and says so; give
`--project wordle` to work on the existing one. Certo prints the folder
before the run:

```text
Project: projects/wordle, named after the task. The agent works only in that folder.
```

In any other folder, or with `CERTO_WORKSPACE` set to another folder,
Certo works where it always did.

**Project creation.** With `--project`, configuration checks run before
Certo creates a missing project folder or records it as Certo-created.
A configuration error leaves existing project folders and the
`.certo-created-projects` registry unchanged.

**State.** Every run keeps its state in the project's `.certo/` folder,
which git ignores. See [Resume an interrupted run](../guides/resume-a-run.md#the-certo-folder).

**Exit code.** 0 for `verified`, `inconclusive` and `unchanged`; 1 for
every other verdict, for a configuration error (`Configuration error: ...`)
and for a run-time error (`Error: ...`); 130 when you stop it with Ctrl-C.
With `--require-verification`, `inconclusive` and `unchanged` exit 1. See [Verdicts](verdicts.md).

`verify`, `init`, `check` and `bench` are subcommands only when they are
the whole first argument. `certo "verify the login flow"` runs a task. To
run the one-word task `verify`, write `certo -- verify`.

## `certo verify`

Run Certo's verification on a project, with no agent and no model.

```text
certo verify [PATH] [--require-verification]
```

| Argument or flag | Default | Effect |
|---|---|---|
| `PATH` | `.` | The project folder. |
| `--require-verification` | off | Exit 1 for `inconclusive` too. |

It needs no settings and reads no `.env`. It may create the project's
`.venv` and install pytest into it. It always runs locally, once, with no
retries. Exit code: 0 for `verified` and `inconclusive`, 1 for `failed`
and `timed_out`, and 1 if `PATH` is not a folder. See
[Verify in CI](../guides/verify-in-ci.md).

## `certo init`

Save your model settings and create a folder with sample tasks.

```text
certo init [FOLDER] [--provider {openai,anthropic,gemini,deepseek,moonshot,ollama,other}]
                    [--model ID] [--base-url URL] [--global | --local]
                    [--no-samples] [--no-check] [--yes] [--force]
```

| Argument or flag | Effect |
|---|---|
| `FOLDER` | The sample folder to create. Default: `./certo-workspace`. |
| `--provider {openai,anthropic,gemini,deepseek,moonshot,ollama,other}` | Skip the provider question. `moonshot` is Kimi. |
| `--model ID` | Skip the model question. Without `--provider`, the provider comes from the model's prefix. |
| `--base-url URL` | Skip the Ollama address question. Also sets `CERTO_LLM_BASE_URL` for any provider. |
| `--global` | Save for all projects, in the user settings file. Skip the "Save these settings for" question. |
| `--local` | Save in `FOLDER/.env` only. Skip that question. |
| `--no-samples` | With `--global`: don't create the sample folder. |
| `--no-check` | Don't make the test call to the model. |
| `--yes`, `-y` | Ask nothing and accept every default: all projects (unless `--local`), plus the sample folder. A key is used only from the provider's exported variable. |
| `--force` | Write into a folder that isn't empty, or over an existing `FOLDER/.env`. With nothing asked (`--yes`, or no terminal), also needed to replace an existing user settings file. |

**Where settings go.** "All projects on this computer" (the default) writes
the user settings file, `~/.config/certo/.env` (or
`$XDG_CONFIG_HOME/certo/.env`). "This folder only" writes `FOLDER/.env`.
Both are written with permissions `600` on macOS and Linux. On Windows,
access follows the folder's inherited permissions; Certo does not set a
Windows ACL. The file holds your chosen lines,
then every other provider's lines commented out.

**The sample folder** gets an empty `projects/` folder, `.gitignore` (`.env`, `projects/`,
`artifacts/`; an existing file only gains missing lines), `tasks/wordle.md`
and `tasks/hanoi.md` (Python, in the terminal), `tasks/space-rocks.md`,
`tasks/mazeman.md` and `tasks/invaders.md` (browser games, Node 18+),
five bigger samples written in milestones, for
[`certo --milestones`](../guides/run-in-milestones.md):
`tasks/sky-hopper.md` (a platform game with parallax, browser),
`tasks/iron-horizon.md` (a 3D wireframe tank game, browser),
`tasks/team-board.md` (a task board web app with SQLite, Python) and
`tasks/star-swarm.md` (a fixed shooter at production quality, the stack
chosen by the agent, browser), `tasks/alien-trekking.md` (first-person
exploration of a generated alien planet, TypeScript and Three.js,
browser), and a
`README.md` with next steps. The bigger samples aren't in the menu at the
end of `init`. A `README.md`
that `init` didn't write is never replaced. With "All projects", the
folder gets no `.env`, and a folder that already has files is skipped.

**Questions**, on a terminal: provider; model; API key (hidden), or the
Ollama address and installed model (or another model, typed); where to
save; whether to create the sample folder; whether to set up more models
(see below). The choices are arrow-key
menus (↑↓ and Enter). Without a full terminal (output piped, or
`TERM=dumb`), the same questions are numbered, and you type the number. If you already have a user settings file, `init` shows its
provider and model (never the key) and asks before replacing it. Nothing
is written until the last answer, so Ctrl-C leaves everything as it was
(exit 130).

**The sample task.** On a terminal, when the sample folder was created and
the model check passed, `init` ends with a menu of the sample tasks. The
one you pick runs at once, in the sample folder, as a normal run (its
output, verdict and cost as for any run), with `--project` set to its
name: for example `tasks/hanoi.md --project hanoi`. Without Node, the
browser games aren't in the menu. `init` says how long a sample takes (a
few minutes each on a cloud model; on a local one, 10 to 40 minutes,
Wordle and space rocks the least, mazeman the most), that a cloud model
uses your credits, and that the result's
quality depends on the model. It is never offered with `--yes` or
`--no-check`. Under "Next", `init` then prints the command for the Wordle
sample (unless a sample ran) and an example for a project of your own:
`certo "A command-line to-do list in Python, with tests" --project todo`.

**More models.** On a terminal, when the settings are for all projects and
the model check passed, `init` asks "Set up more models now?" before the
sample menu. The default is No. Yes runs
[`certo init models`](#certo-init-models) in the same session, starting
from the model just saved. It is not asked with "This folder only",
`--yes` or `--no-check`. Under "Next", `init` lists `certo init models`
unless that run wrote a `models.yaml`.

**Without a terminal** and without `--provider`, `--model` or `--yes`,
`init` asks nothing and writes `FOLDER/.env` with every provider commented
out. Without a terminal, settings go to `FOLDER/.env` unless `--global` or
`--yes` is given.

There is no `--api-key` flag, on purpose: a key on the command line is
saved in your shell history.

### `certo init models`

Set up more than one model, for `--auto-model` and `--escalate`, without
editing a file. Needs a terminal.

```text
certo init models [--profiles] [--timeout SECONDS]
```

| Flag | Default | Effect |
|---|---|---|
| `--profiles` | off | Only choose the model that goes first for each kind of task (`task_profiles.yaml`), for `--auto-model`, from the models already set up. Your choices go to your own `task_profiles.yaml`, on top of Certo's profiles. Needs `models.yaml`. |
| `--timeout SECONDS` | `120` | How long to wait for each model's test answer. A local model may need time to load. |

It starts from the model `certo init` saved, and offers the models this
computer can reach:

- the Ollama models installed on the server of the saved model (or on
  `localhost`);
- the cloud models of each provider whose key is in your settings or
  environment, including the saved model's own key;
- for every other provider, a line that asks for its key (hidden);
- **Another model**, any LiteLLM model id.

On a terminal the models are a checklist: ↑↓ move, Space turns a model
on or off, Enter on a line under **More** opens it (a key, another model),
and Enter anywhere else ends the choice. Without a full terminal, the
list is numbered: numbers turn a model on or off, and Enter ends the
choice. A model that isn't
in Certo's list needs your ratings (1 to 5, shown next to the list's
ratings of the other models you chose; 0 leaves it out), because Certo
never invents them. Each chosen model is then tested with the same request
as `certo check --models`, and only the ones that pass are written, to the
user settings folder (`~/.config/certo/`):

- `models.yaml`, with the models that passed (permissions `600` on macOS
  and Linux; inherited folder permissions on Windows). An
  existing one is replaced only if you say so, and kept as
  `models.yaml.bak`;
- `models_list.yaml`, only for a model you rated: it is added at the
  end of your own list, on top of Certo's (which is read from the
  package and never copied);
- a key you typed, in the user settings file as the provider's variable
  (`DEEPSEEK_API_KEY='...'`). `models.yaml` names it (`${DEEPSEEK_API_KEY}`)
  and never holds a key.

Then it shows what `--auto-model` would choose for each task profile and
how `--escalate` would climb, and asks which mode to use for every run.
The first answer, the default, is one model without `--auto-model` or
`--escalate`; the choice is saved as `CERTO_MODEL_SELECTION` in the user
settings file. For example, from a real run:

```text
Testing each model with one small request:
  ok  qwen3.8-27b-local (11.9s)
  ok  gemma4-31b-qat-local (21.4s)
  ok  nemotron-3.5-lightning-30b-local (35.1s)

Written to /home/you/.config/certo:
  models.yaml  3 models
  models_list.yaml  1 model(s) rated by you, added
```

**Choosing the model for each kind of task.** After `--auto-model` is
chosen for every run, and with `--profiles` alone, it asks:

- whether `--auto-model` uses your local models too, when you have both
  local and cloud ones. "No" turns the local ones off in `models.yaml`
  (`activated: false`; the old file is kept as `models.yaml.bak`);
- for each task profile, which model goes first: the 3 the ratings rank
  highest, another of your models, or "Let the ratings decide". A model
  you pick is written as the profile's `model:` and always goes first
  for that kind of task; the ratings order the others behind it. Only
  those lines change: the file's comments stay.

With fewer than two models chosen, or fewer than two passing the test,
nothing is written: one model needs no model files. Exit code 0, or 1
when fewer than two models passed; 130 on Ctrl-C. A folder named `models`
is created with `certo init ./models`.

## `certo models`

Manage your model files. Subcommands: `update` and `check` for the list,
`models_list.yaml`; `secure` for the keys in `models.yaml`; `choose` for
the models a project may use; `refresh` for ratings computed from current
benchmark data.

### `certo models update`

Slim your `models_list.yaml` down to your own changes. Certo reads its own
model list from the package, so your file only needs what differs: a full
copy (as Certo wrote before 0.2.3) hides Certo's newer models and
ratings.

```text
certo models update [--project NAME] [--use-certos] [--yes]
```

| Flag | Effect |
|---|---|
| `--project NAME` | Slim that project's own `models_list.yaml`, not the one found first. |
| `--use-certos` | Where Certo can't tell an old value from your change, use Certo's without asking. |
| `--yes`, `-y` | Rewrite without asking, keeping your value wherever Certo can't tell it from an old one. Needed without a terminal. |

For each model in your file, each field and each rating is compared with
Certo's list:

- **the same as Certo's:** dropped (Certo's is read anyway);
- **different, and you never changed it:** dropped, it is just an old
  value. Certo knows from `.models_list.base.yaml`, the list your copy
  came from (saved by `certo init models` before 0.2.3);
- **different, and you changed it:** kept;
- **different, with no `.models_list.base.yaml`:** Certo can't tell, so
  it asks for each model: keep yours, use Certo's, or use Certo's for all
  the rest.

A model Certo's list doesn't have is yours and is kept whole, unless
Certo removed it, you never changed it and `models.yaml` doesn't use it.
When nothing is left, the file is removed. The old file is kept as
`models_list.yaml.bak`. A slimmed file can hold a single model and still
lose none: the others come from Certo's own list, and the command says
how many. `certo check` lists every model and the file each value
comes from. Exit code 0 when the file was rewritten or there
is none, 1 when nothing was written, 130 on Ctrl-C.

A slimmed file needs Certo 0.2.3 or newer: an older Certo doesn't read
Certo's own list and sees only the models left in your file. To go back
to an older version, put `models_list.yaml.bak` back first.

### `certo models choose`

Choose the models a project may use. Certo then proposes how to pick
among them, with both strategies, and writes your choice to
[`certo-models.yaml`](models-yaml.md#certo-modelsyaml) at the project's
top. It calls no model.

```text
certo models choose [--project NAME] [--use NAMES] [--strategy {auto,escalate}] [--yes]
```

| Flag | Effect |
|---|---|
| `--project NAME` | The project, as for a run: a name in `CERTO_PROJECTS_DIR`, or `.` (the default) for the folder a run without `--project` works in. |
| `--use NAMES` | The models, comma-separated (names from your `models.yaml`), instead of ticking them. Needed without a terminal. |
| `--strategy {auto,escalate}` | The strategy to write, instead of choosing. Default: the recommended one. |
| `--yes`, `-y` | Write the file without asking. Needed without a terminal. |

On a terminal it lists your enabled models with what one run of each
costs: free for a local model, else the median of your own last runs
when there are enough, else a guess from the price. You tick at least
two. Then it shows:

- the order `--auto-model` would try them for each kind of task: the
  Certo's task profiles, where each kind of task says what it needs, and
  the least costly model that meets it goes first, then stronger ones;
- the ladder `--escalate` would climb: cheapest first, leaving out a
  model when another is at least as capable and costs no more;
- a recommendation: `--escalate` when the ladder starts at least 2
  `cost` points cheaper than it ends (most tasks then end on the cheap
  model), otherwise `--auto-model`.

You choose the strategy and confirm. Runs in that project then use it,
unless a flag or `CERTO_MODEL_SELECTION` chooses. Running it again
replaces the file, with your earlier models ticked. Exit code 0 when the
file was written, 1 when not, 130 on Ctrl-C.

### `certo models secure`

Move the API keys written out in `models.yaml` into your user settings
file (`~/.config/certo/.env`), and name them in `models.yaml` as
`"${NAME}"`. No key is printed.

```text
certo models secure [--project NAME] [--yes]
```

| Flag | Effect |
|---|---|
| `--project NAME` | Secure that project's own `models.yaml`, not the one found first. |
| `--yes`, `-y` | Move the keys without asking. Needed without a terminal. |

Each key goes under the provider's usual name (`OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`...). When that name already holds a
different key, in the settings file or in your environment, the key
goes to the next numbered name (`OPENAI_API_KEY_2`...), shared by every
model with that same key. The settings file is
written first; then only the key values in `models.yaml` change, so its
comments and layout stay. A model written on one line
(`{name: ..., api_key: ...}`) makes Certo rebuild the file, without its
comments. No backup of `models.yaml` is kept, since it would hold the
keys. `certo check` warns about every key still written out.

Exit code 0 when no key is left written out, 1 when nothing was moved
(no confirmation), 2 when there is no `models.yaml`; 130 on Ctrl-C.

### `certo models check`

Check the prices and `cost` ratings of your `models_list.yaml` against
the price list of the installed LiteLLM. It uses no network, calls no
model and reads no key: only `models_list.yaml`, never `models.yaml`.

```text
certo models check [--file PATH] [--fix]
```

| Flag | Effect |
|---|---|
| `--file PATH` | The list to check. Default: `CERTO_MODELS_LIST_FILE`, else `./models_list.yaml`, else the one in your user settings folder. |
| `--fix` | Set each wrong `cost` rating to what its price gives. Only those numbers change, so your comments and layout stay; the old file is kept with `.bak` added to its name. A `ratings` map written over several lines is left for you to change by hand. |

For each cloud model it reports:

- **an id LiteLLM's price list doesn't know**: often a typo or a retired
  model, sometimes a model newer than your LiteLLM;
- **a price that differs**: the first "$X in / $Y out" in the model's
  description against LiteLLM's;
- **a `cost` that isn't what its price gives**: `cost = 4 − log2(p) / 2`,
  one decimal, between 1 and 4.9, where `p` is the price per 1M tokens
  at 3 input to 1 output. A local model is free, so its cost is 5.

The `reasoning`, `precision` and `code` ratings come from benchmarks and
aren't checked. A price that differs needs a person: the provider's
pricing page says which is right, since LiteLLM's list can lag and a
description can be out of date. On Certo's list in 0.2.3 (then
`src/certo/examples/models_list.yaml.example`), on 7 November 2026, a
price rise and a promotion showed up:

```text
src/certo/examples/models_list.yaml.example: 39 models, against LiteLLM's price list.
  gpt-5.6-sol (openai/gpt-5.6-sol)
    - price $5 / $30 in its description, $4 / $20 in LiteLLM's list
  gemini-4-argon (gemini/gemini-4-argon)
    - price $4 / $20 in its description, $2 / $10 in LiteLLM's list
```

Exit code 0 when everything agrees (or `--fix` fixed all of it), 1 when
something needs a look, 2 when there is no list or it can't be read.


### `certo models refresh`

Rate the models from current benchmark data, list prices and your own
runs (since 0.2.4). The ratings go to `ratings.yaml` in your user
settings folder, and every run reads them from then on. No project file
is changed, and no model is called.

```text
certo models refresh [--project NAME] [--offline]
```

| Flag | Effect |
|---|---|
| `--project NAME` | Rate the models as that project sees them, its own `models_list.yaml` included. Default: the current folder. |
| `--offline` | Use no network: the model data cached or shipped with this version, and the installed LiteLLM's prices. |

Where each number comes from:

- **`code`**: LMArena's web development arena. **`reasoning`**: Epoch
  AI's capabilities index. **`precision`**: LMArena's factuality
  arena, the least certain of the three. **`writing`**: the mean of
  reasoning and precision. Each score maps to 1-5 through fixed points,
  with one decimal.
- **`cost`**: from what a model spent on a typical agent task (LMArena),
  else from its list price. Local models: 5.
- **`speed`**: 4 for a cloud model, 2 for a local one.
- **A local model** loses one point on code, reasoning, precision and
  writing: it runs smaller, with a shorter context, than the version the
  sources measured.
- **Your own runs** (from `run_stats.csv`) move `code` toward the share
  of your runs that ended `verified`: a little after a few runs, at most
  one point. Only verdicts that judge the work count: a run that hit the
  time or cost limit, was stopped, or ended `inconclusive` doesn't.

The model data comes from Certo's latest release when there is newer
data online, else from the one this version ships. Prices come from
LiteLLM's current list. A model no source rates says `no data` and keeps
the ratings in Certo's list. Your own ratings, in `models_list.yaml` or
`models.yaml`, always win over the computed ones. Delete `ratings.yaml`
to go back to the ratings in Certo's list.

It prints the ratings of your enabled models, with prices in $ per 1M
tokens, what changed by half a point or more, and which models fit each
kind of task:

```text
Model data of 2026-11-16, from this Certo version.
Prices: the installed LiteLLM's (offline).

Your enabled models (1-5; $ per 1M tokens in/out):
                          code  reas  prec  writ  cost speed  price
  devstral-small-2-local   2.0*  1.0*  2.0*  2.0*  5.0   2.0  local  (no data)
  qwen3.8-27b-local        2.4   1.8   1.7   1.7   5.0   2.0  local
  gpt-6.1-sol              4.9   5.0   3.6   4.3   3.0   4.0  $2/$10
  claude-haiku-5-5         3.4   3.8   2.4   3.1   4.8   4.0  $0.1/$0.5
  claude-opus-5-5          5.0   5.0   4.8   4.9   2.5   4.0  $4/$20
  * Certo's own rating, kept: no source rates that model on that axis.

Changed by half a point or more from Certo's list:
  qwen3.8-27b-local: reasoning 3 → 1.8, precision 3 → 1.7, writing 3 → 1.7, speed 1 → 2
  gpt-6.1-sol: reasoning 4 → 5, precision 5 → 3.6, writing 5 → 4.3
  claude-haiku-5-5: code 4 → 3.4, reasoning 3 → 3.8, precision 3 → 2.4, speed 5 → 4

Which models fit each kind of task (cheapest first):
  debugging (needs reasoning 4, code 4): claude-sonnet-5-5, gpt-6.1-sol, claude-opus-5-5
  docs (needs writing 3): gpt-6-luna, claude-haiku-5-5, gpt-5.6-luna, claude-sonnet-5-5, gpt-6.1-sol, claude-opus-5-5
```

A project with a `certo-models.yaml` keeps the ladder and profiles it was
made with: run [`certo models choose`](#certo-models-choose) to make them
again from the new ratings. Exit code 0 when the ratings were written,
1 when not.

## `certo skills`

See, add and remove the skills a run gets. **Official** skills come with
Certo and change only with a release. **Third-party** skills are yours:
written by you or downloaded. They go in one of two folders, never where
git sees them:

| Flag | Folder | For |
|---|---|---|
| `--global` | `~/.config/certo/skills/` (`$XDG_CONFIG_HOME/certo/skills/` when set) | every project |
| `--project NAME` | `<project>/.certo/skills/`, in `CERTO_PROJECTS_DIR`; `--project .` is the current folder (`CERTO_WORKSPACE`), where a run without `--project` works | one project |

`add`, `remove`, `enable`, `disable`, `update` and `sync` need one of the
two flags. A third-party skill may replace an official one of the same
name; `list` shows it, and a run prints a line saying so. None of these
commands needs a model. Guide: [Manage skills](../guides/manage-skills.md).

### `certo skills list`

```text
certo skills list [--project NAME] [--task TEXT_OR_FILE]
```

| Flag | Effect |
|---|---|
| `--project NAME` | Also list that project's skills, and its own `.agents/skills/` and `AGENTS.md`. |
| `--task TEXT_OR_FILE` | Say which skills would go into a run of this task (text, or a task file), and why, with their size; and which may come in later. |

Lists official and third-party skills in separate sections. For each:
how it fires, its size in tokens (roughly), `from git` for a downloaded
skill, and `replaced by ...` when a skill of the same name in a later
layer replaces it. A downloaded skill that is off says why and how to
turn it on.

### `certo skills add`

```text
certo skills add FILE_OR_FOLDER_OR_SOURCE [PATH] (--global | --project NAME) [--ref REF] [--yes]
```

| Argument or flag | Effect |
|---|---|
| `FILE_OR_FOLDER_OR_SOURCE` | A `.md` skill file, a folder with a `SKILL.md`, or a git source: `github:owner/repo` or an `https://` git URL. |
| `PATH` | With a git source: the skill's folder in the repository, e.g. `skills/pdf`. It must contain a `SKILL.md`. |
| `--ref REF` | With a git source: a branch, tag or commit. Default: the repository's default branch. |
| `--yes`, `-y` | Replace a skill of the same name in that folder without asking. Needed without a terminal. |

A file or folder is loaded first, as a run would load it; if it can't be,
nothing is copied. Certo prints how it fires and its size. It is **on** at
once. A skill from git is downloaded at an exact commit with its license
checked, and stays **off** until `certo skills enable`.

### `certo skills remove`

```text
certo skills remove NAME (--global | --project NAME)
```

Delete a third-party skill from that folder (a downloaded one with its
lock-file entry). Official skills can't be removed.

### `certo skills enable`

```text
certo skills enable NAME (--global | --project NAME) [--accept-unknown-license]
```

Turn on a skill downloaded from git. Its files must still match their
recorded hash.

| Flag | Effect |
|---|---|
| `--accept-unknown-license` | Needed when the license couldn't be established. Read the license first. |

### `certo skills disable`

```text
certo skills disable NAME (--global | --project NAME)
```

Turn off a skill downloaded from git. The files stay.

### `certo skills update`

```text
certo skills update NAME (--global | --project NAME) [--ref REF]
```

| Flag | Effect |
|---|---|
| `--ref REF` | Default: the ref it was added at. |

Download a git skill again. If its content or license changed, it is
turned off until you enable it again.

### `certo skills sync`

```text
certo skills sync (--global | --project NAME)
```

Restore every downloaded skill in that folder at its recorded commit, and
check its files against the recorded hash. A skill whose files don't match
is not restored (exit 1). Never turns a skill on or off.

### `certo skills assess`

```text
certo skills assess (--global | --project NAME)
```

Check and classify every skill of the repositories you trust. They are
listed in `skill_sources.yaml`, next to the skills folder:
`~/.config/certo/skill_sources.yaml` with `--global`,
`<project>/.certo/skill_sources.yaml` with `--project NAME`.

```yaml
sources:
  - repo: github:OpenHands/extensions
    # A branch, tag or commit; assess records the exact commit.
    ref: main
    # Optional: only the skills under this folder.
    path: skills
    # Optional: only these skill folders.
    skills: [code-review, qa-changes]
```

`repo` is `github:OWNER/REPO` or an `https://` git URL, as for
`certo skills add`. Each repository is downloaded once, at an exact
commit. Every folder with a `SKILL.md` in it (folders starting with a dot
are skipped) is checked with the same rules as `certo skills add` from
git, and gets:

- **what it is for**: the steps (planning, setup, testing, debugging,
  review, refactoring, security, documentation, git, release,
  integration) and ecosystems (python, node, go, rust, java, web) its
  name and description name. The words are matched by fixed rules, with
  no model call.
- **how it fires** and its size, as `certo skills list` shows them.
- **a verdict**:

| Verdict | Meaning |
|---|---|
| `usable` | Passed every check. Its repository is in your list, so it needs no `certo skills enable`. |
| `needs review` | Loads, but the reasons say what to read first: a license Certo can't recognise, scripts its instructions may ask the agent to run, inline `` !`command` `` lines, an MCP server config, more than 8,000 tokens, or no trigger (it would go into every run). |
| `rejected` | Can't be used: it doesn't load, has a link to a file outside its folder, its name is taken (by an official skill or a skill from another listed repository), or it is in `skills:` but not found. |

The checked files of usable skills and skills to review are kept, with
their hash, in the skills folder's `.trusted/` folder, next to
`index.json`, the result. Assessing again replaces both. Exit 1 when a
repository couldn't be downloaded.

A run then adds the usable skills that fit its project and task (see
[`certo skills suggest`](#certo-skills-suggest)).

### `certo skills suggest`

```text
certo skills suggest [--project NAME] [--task TEXT_OR_FILE] [--limit N]
```

| Flag | Default | Effect |
|---|---|---|
| `--project NAME` | `.` | The project to match: a project in `CERTO_PROJECTS_DIR`, or `.` for the current folder. |
| `--task TEXT_OR_FILE` | none | The task to match too: text, or a file. |
| `--limit N` | `10` | Show at most `N` skills. |

Match the skills `certo skills assess` saved, yours for every project
and the project's own (a project skill replaces a global one of the same
name), against the project and the task. Installs nothing. Only kept
copies whose files still match their hash are read.

A skill fits when concrete links tie it to the work. Each link is shown
as a reason:

| Link | Weight |
|---|---|
| Its trigger fires on the task (`the task says "uv"`) | 3 |
| A project file matches one of its path triggers, or a trigger word that is a file name (`the project has uv.lock`) | 2 |
| Its ecosystems include the project's (`for python`); for an empty project, the ecosystems the task names | 2 |
| Each of its steps the task names (`about testing`: "tests"; `about debugging`: "fix", "bug") | 1 |

A skill fits from a weight of 3: its trigger alone, or two links together.
Three rules leave a skill out:

- it is made for another ecosystem, and its trigger didn't fire;
- its author gave it trigger words (not slash commands), and none fired
  and no project file matched: those words say when it applies;
- it is an integration (Slack, Jira, Kubernetes...), and the task doesn't
  name the service.

Usable skills are listed best first, each with what a run in that
folder would do with it: `a run adds it`, or `a run leaves it out` and
why. Skills that fit but need review are listed apart, with the reasons;
a run leaves them out.

**In a run.** At the start of each run (each milestone, with
`--milestones`, and each escalation run), Certo makes the same choice
for the run's folder and task, and adds the skills whole to the agent's
instructions for that run, best first, until
`CERTO_TRUSTED_SKILLS_TOKENS` (default 4000) is used up. It leaves out:

- a skill whose name the run already has (an official skill, one of
  yours, or the project's own): those win;
- a slash-command skill whose command isn't in the task: its author
  meant it to be asked for by name;
- a skill larger than what is left of the budget.

Each skill added is said before the run starts:

```text
Certo: added the trusted skill 'uv' (github:OpenHands/extensions, about 591 tokens): the task says "uv", for python.
```

## `certo check`

Check that the configured model works.

```text
certo check [--timeout SECONDS] [--models] [--project NAME]
certo check --task TASK [--project NAME]
```

| Flag | Default | Effect |
|---|---|---|
| `--timeout SECONDS` | `120` | How long to wait for each answer. A local model may need time to load. |
| `--models` | off | Also send the same test request to every model enabled in `models.yaml`, one line per model. |
| `--project NAME` | none | Check the model files as a run with `--project NAME` reads them: that project's own files on top of the current folder's and yours. Also with `--task`. |
| `--task TASK` | none | Show only how `--auto-model` would route this task, and stop. `TASK` is text, a task file or a URL, as for a run. No model is called. See below. |

It reads the settings like a run does, prints each LLM setting and where
it came from (`environment variable`, `./.env (<path>)` or
`user settings (<path>)`; the key only as `set` or `not set`), then sends
one request that offers the model a tool. It passes only if the model
answers with a tool call. Every message and its fix:
[Troubleshooting](../troubleshooting.md).

**The model files.** When `models_list.yaml` or `models.yaml` exists (see
[where Certo looks](models-yaml.md#where-certo-looks)), `certo check` also
reports them: which files it found (including the optional
`task_profiles.yaml` and `escalation.yaml`, or `none`), the active and inactive models, how
many listed models aren't used, for each task profile the first three
models `--auto-model` would try (with their scores), each ladder with its usable rungs, the
ladder Certo would build from the ratings (and the models it leaves out
of it, with the model that beats each one), and every error and warning
(see [Checks](models-yaml.md#checks)). A missing file is an error with the
command that copies its example. Keys are never printed. For example:

```text
Model files:
  List: .../models_list.yaml
  Personal settings: .../models.yaml
  Task profiles: .../task_profiles.yaml
  Escalation: .../escalation.yaml
  Active models: qwen-local, gpt-luna, claude-sonnet
  Inactive models: gemma-local
  Task profiles (--auto-model), checked in this order:
    debugging, title has: fix, bug
      gpt-luna (named by the profile, score 13), claude-sonnet (score 20), qwen-local (score 9)
    scaffolding, title has: scaffold
      qwen-local (score 10), gpt-luna (score 8), claude-sonnet (score 4)
    default, when no other profile matches
      claude-sonnet (score 12), gpt-luna (score 11), qwen-local (score 10)
  Ladder 'default': qwen-local -> gpt-luna -> claude-sonnet
  Ladder 'local-only': qwen-local (1 rung(s) skipped)
  Derived ladder: qwen-local (capability 5, cost rating 5; effort default) -> gpt-luna (capability 7, cost rating 4; effort default) -> claude-sonnet (capability 10, cost rating 2; effort default)
  Warning: Ladder 'local-only', rung 2: gemma-local has 'activated: false', so this rung is skipped.
  Warning: Ladder 'local-only' has only one usable rung (qwen-local), so it can't escalate.
```

With `--models`, each active model gets a line such as
`qwen-local (ollama/qwen3-coder:30b)... ok: reachable, tool calling works.`
A broken key or a model without tool calling shows up here, before a run.

**One task: `--task`.** `certo check --task "Fix the bugs in the parser"`
shows what `--auto-model` would do with that task, without running it:
the task's title, the profile it matches and why, and every active model
in the order Certo would try it. For a task file written in milestones,
one more line per milestone gives its profile and first model: a
milestone is classified by its own title first, then by the task's. A
`Measured` line says what the first model's recorded runs of this kind
cost and took (see [Measured runs](../guides/run-records-and-costs.md#measured-runs)).
It makes no model call and doesn't check the main model:

```text
Task title: Fix the bugs in the parser
Profile: debugging ("fix" is in the title)
Models, in the order --auto-model tries them (the profile names gpt-luna; fallbacks ranked by weights):
  1. gpt-luna (named by the profile, score 13)
  2. claude-sonnet (score 20)
  3. qwen-local (score 9)
The first model runs the task. The next one takes over if its provider fails, or makes the fix attempt when the current model's work fails Certo's checks.
Measured for gpt-luna: ~$0.02 per run ($0.01-$0.05), ~1m 00s (30s-1m 30s), from your last 3 task runs with profile debugging.
```

With fewer than 3 recorded runs, the line says so: `Measured: fewer
than 3 task runs of gpt-luna recorded, so cost estimates are a fixed
guess.`

**How far off the estimates were.** Once 3 or more recorded runs had a
cost estimate before they started (the benchmark gives one to every
run), `certo check` ends with how their real cost compared, over the
last 20 such runs and the 20 before them:
`Cost estimates, last 20 runs: actual 0.4x the estimate (the 20 before: 0.1x).`
1x is right; under 1 the estimates were too high.

**Exit code.** 0 when the model check passes, the catalog has no error,
and (with `--models`) every model passes; 1 otherwise. `--models` without
the model files is an error. With `--task`: 0 when the model files load,
1 when they can't be found or read.

For an Ollama model, `certo check` also reports the server version, the context window the model will run with, and how long the test request took (loading the model included). A `Speed:` line then gives how fast the model writes, in tokens a second, as Ollama measures it on one short extra request: the request time can't tell you, since it includes loading the model. A `Thinking:` line then says how the model will think with your `CERTO_LLM_REASONING_EFFORT`, from what the server says the model can do: on, off, the model's default, or that the model has no thinking mode (then a set effort makes Ollama refuse the request). For example, `qwen3.8:27b` on another machine of the network, with the window the server gives it:

```text
Checking the model ollama/qwen3.8:27b (a local model may take a minute to load)... 
Ollama 0.40.6 · context window 131,072 tokens (from server) · 2.0s
Speed: 37.8 tokens a second (64 tokens written in 1.7s, measured by Ollama).
Thinking: the model has it, and CERTO_LLM_REASONING_EFFORT is not set, so it thinks as Ollama does by default. high turns it on, minimal turns it off.
ok: reachable, tool calling works.
```

Here the model was already loaded, so the request took 2.0s; when it has
to load first, the same request takes 11s or more, and the speed stays
the same.

The same model with `CERTO_LLM_CONTEXT_TOKENS=20000`, under the window
Certo warns about:

```text
Checking the model ollama/qwen3.8:27b (a local model may take a minute to load)... 
Ollama 0.40.6 · context window 20,000 tokens (from CERTO_LLM_CONTEXT_TOKENS) · 11.3s
Thinking: the model has it, and CERTO_LLM_REASONING_EFFORT is not set, so it thinks as Ollama does by default. high turns it on, minimal turns it off.
ollama/qwen3.8:27b has a context window of 20,000 tokens (CERTO_LLM_CONTEXT_TOKENS), under CERTO_CONTEXT_WARN_TOKENS=32,768: when a long task fills it, older steps are summarized and the run goes on. For more room, set CERTO_LLM_CONTEXT_TOKENS=32768 (Certo then asks Ollama for that size), or start Ollama with OLLAMA_CONTEXT_LENGTH=32768. (CERTO_CONTEXT_WARN_TOKENS=0 turns this warning off.)
ok: reachable, tool calling works.
```

## `certo bench`

Compare models and strategies on tasks graded by hidden tests.

```text
certo bench [--config FILE] [--out DIR] [--resume] [--parallel N]
            [--max-cost USD] [--stop-at HH:MM] [--pause-between SECONDS]
            [--yes] [--list-tasks] [--check-tasks]
```

| Flag | Default | Effect |
|---|---|---|
| `--config FILE` | `bench.yaml` | The benchmark file. See [bench.yaml](bench-yaml.md). |
| `--out DIR` | `./bench-results/<date-time>` | The results folder. A folder that already has results is refused unless `--resume` is given. |
| `--resume` | off | Continue an interrupted benchmark in `--out` (default: the latest folder in `./bench-results`), skipping runs already recorded, except runs that couldn't reach the model server or whose project folder was deleted during the run: those run again. A `--out` folder with no results yet is started, so a restart script can always pass `--resume`. Refused if the tasks, arms, repeats, models or task set changed. |
| `--parallel N` | `1` | Run N at a time. Refused when any arm uses a local model (Ollama, or a server on this machine or network). |
| `--max-cost USD` | none | Stop starting new runs once the recorded cost (all runs in the folder) reaches USD. Runs already started finish; results are kept. Models with no known price count as 0. |
| `--stop-at HH:MM` | none | Stop starting new runs at this local time (24-hour: `07:00`, `23:30`). Today if that time is still ahead, else tomorrow. Runs already started finish, so the benchmark can end a little later; results are kept. Continue with `--resume`. |
| `--pause-between SECONDS` | `0` | Wait SECONDS between two runs, for example to let the machine running a local model cool down. Not with `--parallel`. |
| `--yes`, `-y` | off | Start without asking. Needed when there is no terminal. |
| `--list-tasks` | | List the tasks and exit. Needs no models. |
| `--check-tasks` | | Check every task with no model: its reference solution must pass its hidden tests, and its starter alone must fail them. Exit 1 if any task is broken. |

**When the model server can't be reached.** A run that fails because the
model server couldn't be reached at all (the machine running Ollama is
off, its name doesn't resolve, the connection is refused) says nothing
about the arm: it isn't counted in the summary or `results.md`, which
say how many such runs there were (`results.csv` keeps every run). After
3 such runs in a row the benchmark stops starting new ones. Continue
with `--resume` once the server is back: it runs them again.

It reads only the benchmark file and the models file it names, never
`.env`. Before starting, it prints the plan (tasks × arms × repeats) and a
rough cost estimate: "at most" (every escalation rung runs) and, when
earlier results in the same parent folder cover the lower rungs, "likely"
(see [the cost estimate](../guides/benchmark.md#run-it)). While running, it prints one line per finished run.
At the end it writes `results.md`, `results.csv` and `cost.json`, and
prints a summary per arm and the real total cost next to the estimate. Guide: [Benchmark models and strategies](../guides/benchmark.md).

**Exit code.** 0 when the benchmark ran, whatever the models scored (also
when stopped by `--max-cost` or `--stop-at`); 1 for a configuration error, or when the
plan wasn't confirmed; 130 when interrupted (finished runs are kept).

## `certo checkpoints`

List the checkpoints (snapshots of the project's files) Certo took during
its runs.

```text
certo checkpoints [PATH]
```

| Argument | Default | Effect |
|---|---|---|
| `PATH` | `.` | The project folder. |

One line per checkpoint: its number, when it was taken, and the step
(`before the agent`, `checks 2: failed`, `finished: verified`, ...).
Needs git, no settings and no model. Exit code: 0, or 1 if `PATH` is not
a folder or git isn't installed. Guide:
[Go back to an earlier point](../guides/checkpoints.md).

## `certo rollback`

Put the project's files back as they were at one checkpoint.

```text
certo rollback N [PATH] [--yes]
```

| Argument or flag | Default | Effect |
|---|---|---|
| `N` | | The checkpoint's number, from `certo checkpoints`. |
| `PATH` | `.` | The project folder. |
| `--yes` | off | Don't ask before changing files. Needed when there is no terminal. |

It lists each file it would restore, delete or add back, and asks. Your
files as they are become a checkpoint first, so the rollback can be
undone with another `certo rollback`. Files a checkpoint leaves out
(ignored by `.gitignore`, environments, caches, files over 10 MB) are
never touched. Your own git repository is never touched either. Exit
code: 0 when done or when nothing needed changing; 1 when declined, for a
number that doesn't exist, or without `--yes` and no terminal.

## `certo report`

Write the last run's problems to one Markdown file, to share with Certo's
maintainers (attach it to a GitHub issue).

```text
certo report [PATH] [--note TEXT] [--output FILE]
```

| Argument or flag | Default | Effect |
|---|---|---|
| `PATH` | `.` | The project folder. |
| `--note TEXT` | none | Your own words, at the top of the file. |
| `--output FILE` | `.certo/certo-report.md` | Where to write it. |

It puts together what the project's `.certo/` folder already holds: your
Certo, Python and system; the run's task, model, effort, time budget and
step limit, and how it ended; the errors the SDK recorded (the provider's
and the tools'); and the run's report, with the checks' output, the files
changed, the check files the agent edited, the cost and Certo's notices.
It calls no model. Every value that looks like a key (the keys in your
settings files and `models.yaml`, and the usual key shapes) is replaced
with `[hidden]`, and the terminal says how many. The file still holds
the task and the checks' output: read it before you share it. Exit code:
0, or 1 if `PATH` is not a folder or has no recorded run. Guide:
[Share a run's problems](../guides/run-records-and-costs.md#share-a-runs-problems).

## `certo ask`

Answer a question about Certo from its own docs, with a link to each
section the answer uses.

```text
certo ask QUESTION
```

| Argument | Effect |
|---|---|
| `QUESTION` | The question, in your own words; quotes are optional. |

It reads the docs of your Certo's own version: from a source checkout,
the `docs/` folder; installed, the `docs.zip` of that version's GitHub
Release, downloaded the first time and kept in `~/.cache/certo/docs/`
(offline afterwards; GitHub sees only the version, never the question).
Two calls to the model: the first picks the sections from the docs'
headings, the second answers from those sections only. The model is
`CERTO_ASK_MODEL`, else your configured model. From a real run on
`anthropic/claude-haiku-5-5`, in a checkout (installed, the links are
the pages on GitHub at your version's tag):

```text
$ certo ask "My task gets stopped after half an hour. How do I give it longer?"
Set a longer time budget with `--max-time MINUTES` for one run [1]. The default budget is 1800 seconds (30 minutes) [1]. To change it for all runs, set `CERTO_MAX_TASK_SECONDS` to a number of seconds [1].

The budget covers the first run and every retry together [1]. A resumed run keeps the same time budget unless you give `--max-time` [2].

Sources:
  [1] reference/configuration.md › Limits and verification
      /home/me/certo/docs/reference/configuration.md#limits-and-verification
  [2] guides/resume-a-run.md › Continue where it stopped
      /home/me/certo/docs/guides/resume-a-run.md#continue-where-it-stopped

(Answered by anthropic/claude-haiku-5-5 from 4 section(s) in 7s, $0.0010.)
```

When the docs don't answer it, it says `The docs don't cover this.` and
lists the closest pages. An answer that names no section comes with a
note that it can't be checked against the docs. Exit code: 0, or 1 when
there are no docs to read (a version with no `docs.zip`, or offline with
no copy kept), no model is configured, or the model fails. On 30 test
questions, Haiku answered all right, and said "not covered" for each of
the 6 the docs don't answer ([the record](../benchmark/ask-0.2.4.md)).

## `certo mcp`

Run Certo as an MCP server over stdio, for an editor or an agent. The
client starts this command; you don't run it in a terminal yourself.

```text
certo mcp [--root DIR]...
```

| Flag | Default | Effect |
|---|---|---|
| `--root DIR` | none | A folder the tools may work in, with every folder inside it, besides the projects under `CERTO_PROJECTS_DIR`. Repeat it for more than one. A `DIR` that isn't a folder is an error (exit 1). |

It reads the settings as a run does, but needs no model to start: a tool
can name one. The tools: `run_task` (also with a milestones task file),
`run_status`, `run_events`, `run_cancel`, `run_resume`, `list_runs`,
`verify` (as a run), `checkpoints`, `rollback`, `check_model`,
`list_projects`, `list_models`, `list_skills`, and `search_docs` and
`read_docs` (Certo's docs, as `certo ask` reads them); the resources:
`certo://projects/NAME/status` and `certo://projects/NAME/runs`. Guide:
[Use Certo from an editor or an agent (MCP)](../guides/use-certo-over-mcp.md).

## `certo-server`

Run Certo as an HTTP and WebSocket server. Needs the `server` extra. Its
`/v1/chat/completions` endpoint and every task store except `memory` are
[experimental](../README.md#experimental-features).

```text
certo-server [--host HOST] [--port PORT]
```

| Flag | Default | Effect |
|---|---|---|
| `--version` | | Print the version and exit. |
| `--host HOST` | `127.0.0.1` | Address to listen on. The server has no authentication. |
| `--port PORT` | `8000` | Port to listen on. |

It needs valid settings at start-up. Endpoints: [Server API](server-api.md).
Guide: [Run as a server](../guides/run-as-a-server.md).

## `certo-admin`

Maintenance: server task records and a plain model check. It reads the
same settings as `certo`. Skills are managed with
[`certo skills`](#certo-skills).

| Flag | Effect |
|---|---|
| `--version` | Print the version and exit. |

### `certo-admin list`

```text
certo-admin list [--project PROJECT] [--limit N]
```

List the task records in the task store (`CERTO_TASK_STORE`), newest
first: id, project, status, verdict, when it was created (UTC) and the
start of the task. Use an id with `certo-admin show` or
`certo-admin delete-task`. No records is not an error.

| Flag | Default | Effect |
|---|---|---|
| `--project PROJECT` | all projects | Only the records of this project. |
| `--limit N` | `50` | Show at most `N` records; `0` shows all. When some are left out, the last line says how many. |

### `certo-admin show`

```text
certo-admin show TASK_ID
```

Print one task record's summary from the task store (`CERTO_TASK_STORE`).

### `certo-admin delete-task`

```text
certo-admin delete-task TASK_ID
```

Delete one task record. Exit 1 if it doesn't exist.

### `certo-admin delete-project`

```text
certo-admin delete-project PROJECT
```

Delete every task record for a project. Deleting nothing is not an error.

### `certo-admin purge`

```text
certo-admin purge [--ttl-seconds N]
```

| Flag | Default | Effect |
|---|---|---|
| `--ttl-seconds N` | `CERTO_TASK_TTL_SECONDS` | Delete finished records older than `N` seconds. |

Refuses to run (exit 1, nothing deleted) when the value is `0` or less,
because `0` means "keep forever".

### `certo-admin check-llm`

```text
certo-admin check-llm [--model MODEL] [--base-url URL] [--reasoning-effort LEVEL] [--timeout SECONDS]
```

| Flag | Default | Effect |
|---|---|---|
| `--model MODEL` | `CERTO_LLM_MODEL` | Model to check. |
| `--base-url URL` | `CERTO_LLM_BASE_URL` | Server address to check. |
| `--reasoning-effort LEVEL` | `CERTO_LLM_REASONING_EFFORT` | Reasoning effort for the check. |
| `--timeout SECONDS` | `60` | How long to wait. There are no retries. |

An older, simpler check than `certo check`: it asks for a plain text answer
and passes on any non-empty text, without testing tool calling. On failure
it prints the kind of error (`authentication`, `rate_limit`, `timeout`,
`unavailable`, `model_not_found`, `bad_request`, `setup`, `no_reply` or
`error`) and a hint. The key always comes from `CERTO_LLM_API_KEY` and is
removed from any error text. Exit 0 on success, 1 otherwise.
