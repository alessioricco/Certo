# Commands

Every command, subcommand and flag Certo installs. It is for looking
things up; for a walk-through, see [Getting started](../getting-started.md).

Certo installs three commands: `certo`, `certo-server` and `certo-admin`.
`certo` also has these subcommands: `certo verify`, `certo init`,
`certo check`, `certo models`, `certo skills`, `certo bench`,
`certo checkpoints` and `certo rollback`. Every command and subcommand accepts `-h` / `--help`.

All three commands hide the OpenHands SDK's start-up banner. Set
`OPENHANDS_SUPPRESS_BANNER=0` to see it.

## `certo`

Run a task through the agent, then verify the result.

```text
certo TASK [--project NAME] [--execution {local,docker}] [--model MODEL]
           [--api-key KEY] [--base-url URL] [--reasoning-effort LEVEL]
           [--agents-md TEXT] [--independent-tests] [--independent-tests-strict]
           [--interactive] [--verbose]
           [--auto-model]
           [--require-verification] [--acceptance-checks JSON_OR_FILE]
           [--escalate [LADDER]] [--milestones]
certo --resume [TASK] [same options]
```

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
| `--project NAME` | none | Work in `CERTO_PROJECTS_DIR/NAME`, created if missing. Without it, Certo works in `CERTO_WORKSPACE` (default: the current folder). `NAME` must be a relative path with no `..`, and must stay inside `CERTO_PROJECTS_DIR`. |
| `--execution {local,docker}` | `CERTO_EXECUTION` | Where the agent's tools run, for this run. `docker` is [experimental](../README.md#experimental-features). See [Run in Docker](../guides/run-in-docker.md). |
| `--model MODEL` | `CERTO_LLM_MODEL` | Model for this run only. Enough on its own: you do not need `CERTO_LLM_MODEL` set already. |
| `--api-key KEY` | `CERTO_LLM_API_KEY` | API key for this run only. It ends up in your shell history. |
| `--base-url URL` | `CERTO_LLM_BASE_URL` | Server address for this run only. With `--model`, enough for a local model that needs no key. |
| `--reasoning-effort LEVEL` | `CERTO_LLM_REASONING_EFFORT` | Reasoning effort for this run only: `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, or any value the provider accepts. `none` or `off` turns it off. |
| `--agents-md TEXT` | none | Write `TEXT` as the project's `AGENTS.md` before the task. Needs `--project`. |
| `--independent-tests` | off (`CERTO_INDEPENDENT_TESTS`) | Before the build, have tests written from the task and the project as it is; after the verdict, run them and print the result under it. Report only: the verdict and exit code don't change. Local runs, not on `--resume`. See [Independent tests](../guides/independent-tests.md). |
| `--independent-tests-strict` | off (`CERTO_INDEPENDENT_TESTS_STRICT`) | Like `--independent-tests`, but when most sets fail, a `verified` run ends `independent_failed` (exit 1). Other verdicts stay as they are. See [Make them change the verdict](../guides/independent-tests.md#make-them-change-the-verdict). |
| `--interactive` | off (`CERTO_INTERACTIVE`) | Let the agent stop and ask you questions. See [Interactive and confirm mode](../guides/interactive-mode.md). |
| `--verbose` | off (`CERTO_VERBOSE`) | Print the agent's full output: the whole system prompt, the task with the skills Certo adds, and the SDK's own logs. Without it, each of these is one line. |
| `--auto-model` | off (`CERTO_MODEL_SELECTION`) | Pick the model from the model files (`models_list.yaml`, `models.yaml`, and the task profiles in `task_profiles.yaml`). A missing or broken model file is a configuration error (the error says which example to copy, or lists the problems): no banner, no resume hint, and no run is recorded. See [Pick models automatically](../guides/pick-models-automatically.md). |
| `--require-verification` | off | Exit 1 for `inconclusive` and `unchanged` too. |
| `--acceptance-checks JSON_OR_FILE` | none | Extra file checks for this task, as inline JSON or a JSON file. See [Acceptance checks](../guides/acceptance-checks.md). |
| `--escalate [LADDER]` | off (`CERTO_MODEL_SELECTION`) | Start on the first rung of a ladder of models from `escalation.yaml`, and move to the next model only when Certo's verdict shows the model couldn't finish, or its provider fails (outage, rate limit, rejected key). The time budget (`budget_exhausted`) and `CERTO_MAX_TASK_COST` stop the climb. `LADDER` names a ladder; without it, the ladder named `default` is used, else one built from the ratings. With only one value after the flag, as in `certo --escalate "Fix the crash"`, that value is the task. Can't be combined with `--auto-model` or `--model`, nor with `--resume` except after `--milestones`, where it starts the milestone again on the first rung. A missing model file (the error says which example to copy) or an unknown ladder is a configuration error that lists the ladders found. See [Escalate between models](../guides/escalate-between-models.md). |
| `--milestones` | off | Run the task file milestone by milestone: each `## Milestone N: title` heading starts one, run in its own conversation and verified before the next starts; the first that isn't `verified` stops the task with its verdict. A milestone may hold an ` ```acceptance ` block, in the `--acceptance-checks` format. Needs a task file (not text or a URL). With `--escalate`, each milestone climbs its own ladder from the first rung; with `--independent-tests`, each gets its own tests. A task file with no milestone heading, or a broken block, is an error before any model call. [Experimental](../README.md#experimental-features). See [Run a task in milestones](../guides/run-in-milestones.md). |
| `--resume` | off | Continue the last run in this folder (or in `--project NAME`) from the state in its `.certo/` folder. `TASK` is optional and is sent as an extra instruction. Errors when there is no saved state; does nothing (exit 0) when the last run ended `verified` and no `TASK` is given. After `--milestones`, it continues the first milestone not `verified`, reading the task file again; it refuses when the file is gone or was edited, and does nothing (exit 0) when every milestone is `verified`. With `--escalate`, the milestone starts again on the ladder's first rung in a fresh conversation, told how the last try ended. See [Resume an interrupted run](../guides/resume-a-run.md). |

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

**The sample folder** gets `.gitignore` (`.env`, `projects/`,
`artifacts/`; an existing file only gains missing lines), `tasks/wordle.md`
and `tasks/hanoi.md` (Python, in the terminal), `tasks/space-rocks.md`,
`tasks/mazeman.md` and `tasks/invaders.md` (browser games, Node 18+),
and a `README.md` with next steps. A `README.md`
that `init` didn't write is never replaced. With "All projects", the
folder gets no `.env`, and a folder that already has files is skipped.

**Questions**, on a terminal: provider; model; API key (hidden), or the
Ollama address and installed model (or another model, typed); where to
save; whether to create the sample folder. The choices are arrow-key
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
certo init models [--timeout SECONDS]
```

| Flag | Default | Effect |
|---|---|---|
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
- `models_list.yaml` and `task_profiles.yaml`, copied from the examples
  when missing; a model you rated is added at the end of the list;
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
  models_list.yaml  the example list
  models_list.yaml  1 model(s) rated by you, added
  task_profiles.yaml  the example profiles
```

With fewer than two models chosen, or fewer than two passing the test,
nothing is written: one model needs no model files. Exit code 0, or 1
when fewer than two models passed; 130 on Ctrl-C. A folder named `models`
is created with `certo init ./models`.

## `certo models`

Manage your list of models, `models_list.yaml`. One subcommand, `update`.

### `certo models update`

Bring your `models_list.yaml` up to date with the example list of the
installed Certo, keeping your own changes.

```text
certo models update [--yes]
```

| Flag | Effect |
|---|---|
| `--yes`, `-y` | Apply every change without asking, and keep your version of an entry that both you and the example changed. Needed without a terminal. |

It compares three versions of each model entry: your file, the example it
was copied from (saved next to your file as `.models_list.base.yaml` by
`certo init models` and by each update), and the new example. Then:

- **New**: a model the new example has and you don't. Not offered again if
  you removed it yourself.
- **Changed**: an entry the example changed (id, ratings, description)
  and you didn't.
- **Removed**: a model no longer in the example, unchanged by you. Never
  removed while `models.yaml` uses it.
- **Both changed**: you and the example both changed it. Asked one by
  one; `--yes` keeps yours.
- **Kept**: your own models and your edits.

On a terminal, it asks whether to apply all the changes, one by one, or
none. Without the base file (a list you copied by hand, or one from
before 0.1.21), Certo can't tell who changed an entry, so every entry
that differs is asked about, and nothing is removed. For example, a list
copied on 17 October 2026, with one rating changed by its owner and one
model of their own:

```text
  Kept          claude-sonnet-5-5: your changes
  Kept          my-finetune: yours
  New           gpt-oss-20b-local
                ollama/gpt-oss:20b
  Changed       gpt-6-luna
                ratings: precision 3 -> 4
                description changed
```

The file is edited entry by entry, so your comments and layout stay; new
models go after the last entry of the list. The old file is kept as
`models_list.yaml.bak`. If the file's layout isn't the example's (entries
at `  - name:` with their fields indented below), nothing is written and
the message says so. Exit code 0, or 1 when there is no list or it can't
be edited safely.

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
certo skills list [--project NAME] [--task TEXT]
```

| Flag | Effect |
|---|---|
| `--project NAME` | Also list that project's skills, and its own `.agents/skills/` and `AGENTS.md`. |
| `--task TEXT` | Say which skills would go into a run of this task, and why, with their size; and which may come in later. |

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

## `certo check`

Check that the configured model works.

```text
certo check [--timeout SECONDS] [--models]
certo check --task TASK
```

| Flag | Default | Effect |
|---|---|---|
| `--timeout SECONDS` | `120` | How long to wait for each answer. A local model may need time to load. |
| `--models` | off | Also send the same test request to every model enabled in `models.yaml`, one line per model. |
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
in the order Certo would try it. It makes no model call and doesn't check
the main model:

```text
Task title: Fix the bugs in the parser
Profile: debugging ("fix" is in the title)
Models, in the order --auto-model tries them (the profile names gpt-luna; fallbacks ranked by weights):
  1. gpt-luna (named by the profile, score 13)
  2. claude-sonnet (score 20)
  3. qwen-local (score 9)
The first model runs the task. The next one takes over if its provider fails, or if a fix attempt still fails Certo's checks.
```

**Exit code.** 0 when the model check passes, the catalog has no error,
and (with `--models`) every model passes; 1 otherwise. `--models` without
the model files is an error. With `--task`: 0 when the model files load,
1 when they can't be found or read.

For an Ollama model, `certo check` also reports the server version, the context window the model will run with, and the speed of the test request:

```text
Checking the model ollama/qwen3:8b (a local model may take a minute to load)... 
Ollama 0.40.13 · context window 20,000 tokens (from CERTO_LLM_CONTEXT_TOKENS) · 24.5s
Certo: ollama/qwen3:8b has a context window of 20,000 tokens (CERTO_LLM_CONTEXT_TOKENS), under CERTO_CONTEXT_WARN_TOKENS=32,768: when a long task fills it, older steps are summarized and the run goes on. For more room, set CERTO_LLM_CONTEXT_TOKENS=32768 (Certo then asks Ollama for that size), or start Ollama with OLLAMA_CONTEXT_LENGTH=32768. (CERTO_CONTEXT_WARN_TOKENS=0 turns this warning off.)
ok: reachable, tool calling works.
```

## `certo bench`

Compare models and strategies on tasks graded by hidden tests.

```text
certo bench [--config FILE] [--out DIR] [--resume] [--parallel N]
            [--max-cost USD] [--stop-at HH:MM] [--yes] [--list-tasks]
            [--check-tasks]
```

| Flag | Default | Effect |
|---|---|---|
| `--config FILE` | `bench.yaml` | The benchmark file. See [bench.yaml](bench-yaml.md). |
| `--out DIR` | `./bench-results/<date-time>` | The results folder. A folder that already has results is refused unless `--resume` is given. |
| `--resume` | off | Continue an interrupted benchmark in `--out` (default: the latest folder in `./bench-results`), skipping runs already recorded. Refused if the tasks, arms, repeats, models or task set changed. |
| `--parallel N` | `1` | Run N at a time. Refused when any arm uses a local model (Ollama, or a server on this machine or network). |
| `--max-cost USD` | none | Stop starting new runs once the recorded cost (all runs in the folder) reaches USD. Runs already started finish; results are kept. Models with no known price count as 0. |
| `--stop-at HH:MM` | none | Stop starting new runs at this local time (24-hour: `07:00`, `23:30`). Today if that time is still ahead, else tomorrow. Runs already started finish, so the benchmark can end a little later; results are kept. Continue with `--resume`. |
| `--yes`, `-y` | off | Start without asking. Needed when there is no terminal. |
| `--list-tasks` | | List the tasks and exit. Needs no models. |
| `--check-tasks` | | Check every task with no model: its reference solution must pass its hidden tests, and its starter alone must fail them. Exit 1 if any task is broken. |

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
