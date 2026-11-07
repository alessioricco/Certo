# Getting started

This page takes you from nothing to your first verified project, in about
ten minutes. It is for anyone trying Certo for the first time. Follow the
steps in order.

## What you need

- **Python 3.12 or newer.**
- **A model.** Either [Ollama](https://ollama.com) running on your own
  machine, or an API key for a cloud provider (OpenAI, Anthropic,
  Google Gemini, DeepSeek or Kimi). A local model keeps your code on your machine and costs
  nothing per run; a cloud model is faster and costs money per run, and
  Certo prints the cost at the end. Later you can use more than one: for
  example a local model first, and a cloud model only for the tasks it
  couldn't finish (see [Next steps](#next-steps)).
- **Node 18 or newer**, only for the browser sample tasks. The Python
  samples need nothing else.

## 1. Install

The easiest way is [uv](https://docs.astral.sh/uv/), which installs Certo
as a command in its own environment:

```bash
uv tool install certo
```

Or with pip, inside a virtual environment:

```bash
python3 -m venv ~/.venvs/certo
~/.venvs/certo/bin/pip install certo
export PATH="$HOME/.venvs/certo/bin:$PATH"
```

Check that it works:

```console
$ certo --version
certo 0.1.19
```

This page needs version 0.1.19 or newer. If you see an older version, run
`uv tool install --upgrade certo`, or `pip install -U certo` with the
`pip` of the environment Certo is in.

## 2. Save your settings: `certo init`

```bash
certo init
```

`certo init` asks a few questions. Choose with ↑↓ and Enter, or type an
answer; Enter alone accepts the default shown in `[brackets]`:

```console
$ certo init
Certo setup. Press Enter to accept the default in [brackets].

Which model provider do you want to use?
▸  1. OpenAI
   2. Anthropic (Claude)
   3. Google Gemini
   4. DeepSeek
   5. Kimi (Moonshot AI)
   6. Ollama (local models, no API key)
   7. Other (any LiteLLM model id)

Model [openai/gpt-6.1-sol]:
API key (hidden):
Save these settings for:
▸  1. All projects on this computer (recommended)
   2. This folder only
Create a folder with sample tasks to try?
▸  1. Yes
   2. No
```

Without a full terminal (output piped, or `TERM=dumb`), the same questions
are numbered and you type the number.

- The API key is typed at a hidden prompt. It is never shown or printed.
  There is no command-line flag for it on purpose, so it can't end up in
  your shell history.
- **All projects on this computer** saves the settings in
  `~/.config/certo/.env` (readable only by you). Then `certo` works in any
  folder.
- For Ollama, `init` asks for the server address and lets you pick one of
  the models installed there. See
  [Ollama and local models](guides/ollama-and-local-models.md).

When you gave a key, `init` makes one small real call to check that the
model works and can call tools, which Certo's agent needs:

```text
Checking the model openai/gpt-6.1-sol... ok: reachable, tool calling works.
```

It also creates `certo-workspace/`, with five sample tasks in `tasks/` and
a `README.md` with these next steps.

When the check passed and the settings are for all projects, `init` then
asks whether to set up more models:

```text
Set up more models now?
▸  1. No, one model is enough for now
   2. Yes: add models and keys, then choose how Certo uses them
```

One model is all you need to start, so the default is No. Yes runs
[`certo init models`](reference/commands.md#certo-init-models) at once:
you pick more models, add keys for other providers, and choose to use one
model, `--auto-model` or `--escalate` for every run. You can also run it
later.

## 3. Check the model: `certo check`

You can run the same model check at any time, from any folder:

```bash
certo check
```

It first shows each setting and where it came from. The key is only shown
as `set` or `not set`. Here is what it prints when the key is missing:

```console
$ certo check
Settings:
  CERTO_LLM_MODEL             openai/gpt-6.1-sol, from user settings (/home/me/.config/certo/.env)
  CERTO_LLM_API_KEY           not set
  CERTO_LLM_BASE_URL          not set

Checking the model... not configured: CERTO_LLM_API_KEY is required unless CERTO_LLM_BASE_URL is set (e.g. a local Ollama/vLLM/LM Studio endpoint that needs no key).
Fix the settings as described, then run: certo check
```

Open the settings file it names, paste your key after `CERTO_LLM_API_KEY=`,
and run `certo check` again. Every message `certo check` can print, with
its fix, is in [Troubleshooting](troubleshooting.md).

## 4. Run your first task

When the model check passed, `certo init` ends with a menu of the sample
tasks, and runs the one you pick. This page follows Wordle, the first.
Otherwise, or later, run it yourself:

```bash
cd certo-workspace
certo tasks/wordle.md --project wordle
```

- `tasks/wordle.md` is a plain text file that describes a terminal Wordle
  game in Python. A task can be a file, a URL, or text in quotes.
- `--project wordle` puts the result in its own folder,
  `projects/wordle/`.

Certo first prints a banner with its version and the settings for this
run, so you can stop it (Ctrl-C) if the model or the folder is wrong:

```text
── Certo 0.1.19 ────────────────────────────────────────────
  Model    openai/gpt-5.6-luna
  Folder   /home/you/certo-workspace/projects/wordle (project wordle)
  Runs on  this computer
  Checks   on, up to 2 fix attempts
  Limits   30 min · 50 steps
────────────────────────────────────────────────────────────
```

Two lines follow, one for the agent's instructions and one for your task
(`certo --verbose ...` prints them in full):

```text
System prompt: 270 lines (--verbose shows it)
Task: Wordle in the terminal (210 lines with the skills; --verbose shows them)
```

The agent now works for a few minutes. Each step it takes is printed as
it happens: it writes files, runs commands and runs the tests. When it says it is done, Certo checks the result itself.
The end of the output looks like this:

```text
Verification: verified

Run summary:
  Total running time: 4m 03s
  Models: openai/gpt-5.6-luna (effort default)
  Total tokens: 801,191 (input 774,063, of which cached 725,104; output 27,128)
  Total cost: $0.0593
```

Your time, model, tokens and cost will be different.

## 5. Read the verdict

The `Verification:` line is Certo's verdict. It doesn't come from the
agent: Certo ran the project's own checks after the agent finished.

| Verdict | What it means | Exit code |
|---|---|---|
| `verified` | The project's tests (or build) ran and passed. | 0 |
| `inconclusive` | Nothing could be checked, for example no tests yet. Not a failure, but not a pass either. | 0 |
| `unchanged` | The checks passed, but the agent changed no file, even when Certo asked it to. | 0 |
| `retry_exhausted` | A check kept failing after the automatic fix attempts. | 1 |
| `no_progress` | A fix attempt changed nothing, so Certo stopped early. | 1 |

When a check fails, Certo sends the real error back to the agent and lets
it try again (twice, by default). If it still fails, you see a message like
this before the verdict:

```text
Certo verification: the project's checks are still failing after 2 automated fix attempt(s) (pytest failed (exit 1)). Giving up — this project needs manual attention.

Verification: retry_exhausted
```

Lines starting with `-` under the verdict list what Certo could not check.
All verdicts are in [Verdicts](reference/verdicts.md).

## 6. Find the result

The project is in `projects/wordle/`. The agent is asked to leave a
`README.md` there that says how to run it. For Wordle:

```bash
cd projects/wordle
python3 wordle.py
```

Run the task again with the same `--project` name to keep working on the
same project.

## Work on a project you already have

You don't need the workspace or `--project`. Go to any folder and give the
task in quotes:

```bash
cd any-project
certo "Add a --verbose flag, with a test"
```

This works in any folder when `init` saved your settings for all projects.
The agent edits the files in that folder directly. If the folder has
uncommitted git changes, or isn't a git repository, Certo prints one line
first, so you know whether you can roll back:

```text
Warning: /home/me/any-project has uncommitted changes (1 file). The agent will edit files here; commit or stash first if you want to be able to roll back.
```

Certo never stops or asks here; it is only a warning. More in
[Work on an existing project](guides/work-on-an-existing-project.md).

## Check a project without an agent

`certo verify` runs the same checks with no agent and no model. It costs
nothing:

```console
$ certo verify todo
Project: /home/me/todo (python)
Certo: Created the project environment /home/me/todo/.venv (/usr/local/bin/uv venv).
Certo: Installed pytest into the project environment /home/me/todo/.venv (the project's tests need it and it wasn't there).
  passed      pytest  (/home/me/todo/.venv/bin/python -m pytest -q)

Verification: verified
```

The first run creates a virtual environment for the project and installs
pytest into it. Certo never installs anything into its own environment.
See [Verify in CI](guides/verify-in-ci.md).

## If no model is configured

Any command that needs a model stops with an error that says what to do.
Nothing is created. With no settings at all:

```console
$ certo "Build a CLI todo app" --project todo
Configuration error: CERTO_LLM_MODEL is required (e.g. 'anthropic/claude-sonnet-5-5' or 'ollama/qwen3.8:27b'), and it isn't set in any of the three places Certo looks, in this order: 1. the environment (export CERTO_LLM_MODEL=...); 2. .env in the current folder (/home/me/.env); 3. the user settings file (/home/me/.config/certo/.env). Run certo init to write it, or set it in one of these. Switching provider = changing only this value.
```

Run `certo init`, or set the two variables yourself:

```bash
export CERTO_LLM_MODEL=anthropic/claude-sonnet-5-5
export CERTO_LLM_API_KEY=sk-...
```

## Next steps

- Use more than one model: `certo init models` sets them up and tests
  them. Then let Certo pick one per task
  ([Pick models automatically](guides/pick-models-automatically.md)), or
  hand a task to the next model when one can't finish or its provider
  fails ([Escalate between models](guides/escalate-between-models.md)).
  For example a local model first, then a cloud one; which local model to
  start with: [Choose a local model](guides/choose-a-local-model.md).
- Write tasks Certo can check: [Write a task Certo can check](guides/write-a-good-task.md).
- Teach the agent your conventions, for every project or one:
  [Manage skills](guides/manage-skills.md) (`certo skills`).
- What to do after each verdict: [What to do after each verdict](guides/after-the-verdict.md).
- Use a different provider: [OpenAI, Claude and Gemini](guides/openai-claude-gemini.md)
  or [Ollama and local models](guides/ollama-and-local-models.md).
- Every flag: [Commands](reference/commands.md).
- Every setting: [Configuration](reference/configuration.md).
- How Certo decides a verdict: [How verification works](concepts/how-verification-works.md).
