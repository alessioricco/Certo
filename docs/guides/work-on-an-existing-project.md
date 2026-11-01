# Work on an existing project

This guide is for using Certo on code you already have: a repository on
your disk. It covers running a task in place, the warning about
uncommitted changes, settings for one project, and the project's own
environment.

## Run a task in place

Go to the project folder and give the task in quotes:

```bash
cd ~/code/my-api
certo "Fix the failing test in payments.py"
```

The agent works directly on the files in this folder. With no `--project`,
Certo uses the folder you run it from (the `CERTO_WORKSPACE` setting,
default `.`).

`--project NAME` is different: it puts the work in
`CERTO_PROJECTS_DIR/NAME` (default `./projects/NAME`) and creates that
folder if needed. Use it for new projects, not for an existing repository.

## Commit first: the warning about uncommitted changes

The agent edits files in place. Certo keeps
[checkpoints](checkpoints.md) you can go back to, but they leave out
ignored and large files, so your own git history is the safer undo. Before
the task starts, Certo checks the folder and prints one line to the error
output if you could lose work:

```text
Warning: /home/me/code/my-api has uncommitted changes (1 file). The agent will edit files here; commit or stash first if you want to be able to roll back.
```

```text
Note: /home/me/notes isn't a git repository, so the agent's changes there can't be rolled back with git.
```

- A clean git repository gets no line.
- An empty folder, or a `--project` folder Certo created itself (also
  one `certo-server` created for a task's `project`), gets no line
  either.
- Certo's own `.certo/` state folder never counts: git ignores it (see
  [Resume an interrupted run](resume-a-run.md#the-certo-folder)).
- It never asks and never stops the task, so scripts and CI are not
  blocked.

The simplest habit: commit (or `git stash`) before each task, then review
the agent's changes with `git diff`.

To turn the warning off, set `CERTO_NO_WORKTREE_WARNING=1`. Put it in
`~/.config/certo/.env` to turn it off everywhere.

## Settings for one project

Certo reads each setting from the first place that has it:

1. a variable exported in your shell;
2. `.env` in the folder where you run `certo`;
3. the user settings file, `~/.config/certo/.env`.

Each setting is looked up on its own. So a project's `.env` can change only
the model and still use the key from your user settings file:

```bash
# ~/code/my-api/.env
CERTO_LLM_MODEL=anthropic/claude-sonnet-5-5
```

An empty value (`CERTO_LLM_API_KEY=`) counts as not set, so it doesn't hide
a value from a later place. `certo check` shows where each setting came
from. To write a project's `.env` with questions, run
`certo init --local` there. Add `.env` to the project's `.gitignore` if it
holds a key. All settings are in [Configuration](../reference/configuration.md).

## Tell the agent about the project: `AGENTS.md`

An `AGENTS.md` file at the top of the folder is read by the agent on every
task. Use it for facts the agent should always know, such as "this project
uses FastAPI and Poetry; run tests with `make test`".

With `--project`, Certo can write it for you:

```bash
certo "Add a /health endpoint" --project my-api --agents-md "This project uses FastAPI + Poetry."
```

This replaces `AGENTS.md` in that project folder. `--agents-md` needs
`--project`. More in [Manage skills](manage-skills.md).

## Python projects get their own environment

For a Python project, the agent and Certo's checks both use the project's
own environment, never Certo's. Certo looks in the project folder, then
each parent folder up to the folder you started from, and uses the first
of:

1. a `uv.lock` project (when `uv` is installed): commands run through
   `uv run`;
2. a `.venv/` or `venv/` folder that works.

If there is none, Certo creates `.venv` in the project folder, with
`uv venv` if available, else `python3 -m venv`. If the project has tests
but no pytest, Certo installs pytest into that environment and says so.

Certo never deletes or repairs a virtual environment it didn't create. If
yours is broken, pytest is reported as unavailable and the verdict is
`inconclusive`.

In the agent's terminal, `python`, `pip` and `pytest` already point to the
project environment, with no activation step.

## Projects with several parts

If the folder holds several projects side by side, for example
`frontend/package.json` and `backend/pyproject.toml` and nothing at the
top, Certo can't tell which one to verify. The verdict is `inconclusive`
and the message names every candidate. Run Certo from the sub-project
folder instead.

## Related

- [Getting started](../getting-started.md)
- What Certo checks for each language: [Verification by language](../reference/verification-by-language.md)
- [Safety](../concepts/safety.md)
