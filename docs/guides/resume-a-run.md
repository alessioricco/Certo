# Resume an interrupted run

This guide shows how to continue a task after it stopped: you pressed
Ctrl-C, the terminal closed, the time budget ran out, or verification
failed and Certo gave up. It covers the `certo` command; server mode
keeps its tasks differently (see [Run as a server](run-as-a-server.md)).

## Continue where it stopped

```bash
certo "Build a terminal Wordle game in Python, with pytest tests" --project wordle
# ... interrupted, or ends with: Verification: retry_exhausted
certo --resume --project wordle
```

Without `--project`, run `certo --resume` in the folder where the task ran.

You can add an instruction for the agent. It is sent with the resume:

```bash
certo --resume --project wordle "The test for repeated letters is right. Fix the scoring, not the test."
```

The resumed run is a normal run: the agent works, Certo verifies, and you
get a verdict and an exit code. You can resume as many times as you need.

When a run ends with a failing verdict, Certo prints the command to use:

```text
Where it stopped: projects/wordle/.certo/STATUS.md. Continue with: certo --resume --project wordle
```

If that run set `CERTO_PROJECTS_DIR` to something other than the default
`./projects`, the printed command includes it, for example
`CERTO_PROJECTS_DIR=/home/me/work certo --resume --project wordle` (the
path is quoted when it contains spaces).

After Ctrl-C or an error it prints `Continue with: certo --resume ...`
and exits with code 130 (Ctrl-C) or 1 (error).

## What the agent gets back

- **Its earlier conversation**, when Certo saved it: the task, every step
  it took and every command output. It continues with the same context, as
  if it had never stopped.
- **Certo's record of where it stopped**: the last verdict, the checks
  that failed and the end of their output. Certo writes this record itself,
  so it can't contain the agent's own wishful summary.

You can change the model for the resumed run with `--model`. That is
useful when a local model got stuck: resume with a stronger one, which then
reads everything the first model did.

## The `.certo/` folder

Every `certo` run keeps its state in a `.certo/` folder inside the project:

```text
my-project/
  .certo/
    .gitignore       contains *, so git ignores the whole folder
    STATUS.md        the last run, for you to read
    run.json         the same, for Certo
    RUNS.md          every run, oldest first: date, model, verdict, cost
    reports/         one page per run: why the verdict, checks, files, cost
    milestones.json  with --milestones: the task file, titles and verdicts
    conversations/   the agent's saved conversation
```

`STATUS.md` is updated when the run starts, after every verification and
when it ends. Shortened, it looks like this:

````text
# Certo run status

- Status: finished, verdict `retry_exhausted`
- Model: ollama/qwen3-coder:30b (effort default)
- Verification retries used: 2

## Task

Build a terminal Wordle game in Python, with pytest tests.

## Last verification

- `failed` pytest (`.venv/bin/python -m pytest -q`)
- `passed` entrypoint-ordering

### pytest output (end)

```text
FAILED tests/test_wordle.py::test_repeated_letters - AssertionError: ...
1 failed, 7 passed in 0.12s
```
````

Good to know:

- **Only the last run is kept.** A new task in the same folder replaces
  it. To keep every run, use [run records](run-records-and-costs.md#keep-a-record-of-every-run).
- **Git ignores it** without any change to your own `.gitignore`.
  Certo's uncommitted-changes warning ignores it too.
- **No API key is saved.** But the conversation holds every command
  output the agent saw, so if the agent printed a secret from a file, the
  secret is in there. Delete `.certo/` when you no longer need it; it is
  always safe to delete between runs.
- **The folder is never empty during a run.** Certo creates `.certo/`
  before the agent starts, so a tool that wants an empty folder, such as
  `npm create vite .`, refuses or cancels. The agent is told to keep
  `.certo/` and to create the project in a subfolder, then move the files
  up.
- **To turn it off**, set `CERTO_SAVE_STATE=0`. `certo --resume` still
  works when there is a saved state.

## When the conversation can't be resumed

Then the agent starts a new conversation with the task, `STATUS.md` and
the files as they are. It loses its earlier reasoning, not your work.
Certo prints a note saying so. This happens:

- **in Docker mode** (`--execution docker`), where the conversation isn't
  saved;
- when `.certo/conversations/` was deleted;
- when the saved conversation can't be loaded, for example after
  upgrading Certo.

## When resume says no

- `nothing to resume in ...`: there is no `.certo/` state in that folder.
  Check the folder or the `--project` name.
- `The last run here already ended with 'verified'`: there is nothing to
  fix. To keep working on the same project, give an instruction:
  `certo --resume "Now add a --hard mode"`, or start a new task.

- `All N milestones here are already 'verified'`: the milestones are
  done. Run a new task.
- `the task file ... changed since its milestones started` or `can't
  read the task file`: `--resume` reads the milestones' task file again,
  and it was edited, moved or deleted. Put it back, or start again with
  `certo --milestones`. See [Run a task in milestones](run-in-milestones.md).

## Related

- [Commands](../reference/commands.md#certo): `--resume`
- [Configuration](../reference/configuration.md#where-the-agent-works): `CERTO_SAVE_STATE`
- [Verdicts](../reference/verdicts.md)
