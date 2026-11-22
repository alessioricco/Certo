# Certo v0.2.5

Not released yet.

## New: choose the model that writes the independent tests

[Independent tests](../guides/independent-tests.md) are written from the
task by separate conversations before the build, and run on the work
after it. Until now the run's own model wrote them, and with `--escalate`
the ladder's first model: often a cheap or local one, whose tests are
milder and catch less. `CERTO_INDEPENDENT_TESTS_MODEL` names the model
that writes them instead, by its name in `models.yaml`:

```dotenv
CERTO_INDEPENDENT_TESTS_MODEL=claude-haiku-5-5
```

A wrong name stops the run before it starts. In the benchmark, an arm
takes `independent_tests_model`. See
[Choose the model that writes them](../guides/independent-tests.md#choose-the-model-that-writes-them).
On the benchmark, with a ladder that starts on `qwen3.8` and Haiku writing, all 13
tasks passed with no false alarms, for about $0.026 per task
([the benchmark](../benchmark/ladder-independent-0.2.5.md)).

## New: choose how many milestones

`--make-milestones` lets a model split a task into milestones, and the
model chose how many. Now you can choose:

```bash
certo --milestone-count 5 task.md --project ledger
```

The model is told to write exactly that many, from 2 to 20.
`--milestone-count` turns on `--make-milestones` by itself. A plan with
another number is asked for once more; if it still has another number,
it runs as written, and Certo says so. Also `/make-milestones 5 TASK` in
the interactive session, `milestone_count` over MCP and in the
benchmark. See
[Choose how many](../guides/run-in-milestones.md#choose-how-many).

## New: an official skill for command-line programs

`cli-entry-points` fires when a task mentions a command line (cli,
command line, command-line, argparse, exit code). It tells the agent to
make a program that tests can run unattended: one entry point that
takes its arguments (in Python, the `__main__` block last), no prompts
and no waiting for input that may not come, `--help`, results and
errors on their own streams with the task's exit codes, and tests that
run the command line itself. Not measured yet in the benchmark. See
[Manage skills](../guides/manage-skills.md#official-skills).

## New: a launcher for the MCP server's own settings

`examples/certo-mcp-launcher.sh.example` starts `certo mcp` for one
client with its own model, time budget and folder, for example a model
served by Ollama on another machine, without changing your other Certo
commands. See [One server with its own settings](../guides/use-certo-over-mcp.md#one-server-with-its-own-settings).
Certo on another machine, over SSH, has its own guide:
[Use Certo's MCP server on another machine](../guides/use-certo-mcp-on-another-machine.md).

## Changed: the planner thinks harder

The planning call of `--make-milestones` now runs at reasoning effort
`xhigh`, whatever the planner model's own effort, local models
included: one call, so a better split costs little. Planning the same
five-part task, Haiku took 26 seconds and $0.003 at `xhigh` against 12
seconds and $0.001 at `high`. `CERTO_PLANNER_REASONING_EFFORT` changes
it (`max`, or `default` for the model's own). A model that refuses the
effort, as GPT-6 Luna refuses `max`, plans at its own, and Certo says
so. Whether the plans are better is still to be measured.

## Changed: closing sections reach every milestone

In a task file written in milestones, sections after the last milestone
that start with a level-1 heading, such as `# Definition of done`, used
to belong to the last milestone only. Now every milestone gets them,
after its own text. A `#` heading between two milestones stays with the
one before it. See [Run a task in milestones](../guides/run-in-milestones.md).

## Changed: scratch output goes in `.certo/scratch/`

The agent is now told to keep logs and other saved command output, and
throwaway scripts, in `.certo/scratch/`, which Certo makes, never at the
project's top. In one user's project the agent had left 38 log files at
the top over five milestones; elsewhere a scratch script left there broke
the project's lint. The folder is git-ignored with the rest of `.certo/`.
Runs that keep no state in `.certo/` (the Python library's default, the
benchmark) don't get it.

## Changed: a note when the agent's own test run is slow

When one of the agent's test runs takes a tenth of the time budget or
more (at least a minute), Certo tells it once: while working, run only
the tests for what changed, run the whole suite once at the end, and fix
or narrow a test that fails on a timeout before running the suite again.
In one user's milestone project a browser test suite took 9 minutes of a
30-minute budget, and the agent ran it more than once per milestone. The
note names only the command the agent ran. The app tasks gain one to
measure it with, `job-runner` (task set `apps-3`): an existing project
whose own test suite takes about 2.5 minutes, extended in three
milestones. Measured on it, the note saved no time: no milestone ran
short of time with or without it, and Haiku already narrows its test
runs by itself ([the benchmark](../benchmark/slow-tests-0.2.5.md)). It
stays on: it did no harm, and it is meant for a suite that eats the
budget, which this task doesn't.

The whole release was checked against earlier versions on Haiku (39 of
39 runs passed, as in 0.2.2) and on a ladder that starts on `qwen3.8`
(13 of 13): [the release check](../benchmark/release-check-0.2.5.md).

## New: turn an official skill off

`certo skills disable NAME --global` turns an official skill off for every
project, `--project NAME` for one project; `certo skills enable` turns it
on again. Runs print a line for each official skill that is off. Before,
the only way to stop one was to replace it with a skill of your own. See
[Manage skills](../guides/manage-skills.md#turn-an-official-skill-off).

## Changed: plans the agent writes run in milestones

`## Step N`, `## Phase N` and `## Stage N` headings now start a milestone,
like `## Milestone N`, so a file written that way runs in milestones on
its own. With `--milestones` (or `/milestones` in the session), a file
whose `##` headings are only numbered (`## 1. Data model`) is split at
them; without the flag it still runs whole, since many task files number
their sections. When a run ends and the agent wrote or changed a plan in
milestones, Certo names it and the command that runs it milestone by
milestone. In one user's project the agent wrote such a `PLAN.md`, the
user replied "go ahead", and the whole plan ran as one task on one
budget. See [Run a task in milestones](../guides/run-in-milestones.md#write-the-task-file).

## Changed: version ranges for dependencies added from the terminal

The rule to give each new Python dependency a version range was only in
`pin-dependencies`, which fires when the agent edits `pyproject.toml` or
`requirements*.txt` with the file editor, never for `pip install` or
`uv add` in the terminal. It is now in `python-environment` too, which
also fires on poetry, uv add and uv sync. A task that names none of the
trigger words still gets the rule only when the agent edits the
dependency file.

## Fixed

- **`certo mcp` named a folder twice** when it refused one outside the
  folders it may use and the projects folder was also a `--root`
  (`CERTO_PROJECTS_DIR=DIR` with `--root DIR`). Each folder is now
  listed once.
- **`certo bench` and keys from a `.env` file.** A key written as
  `${NAME}` in the benchmark's models file was read only from the
  shell, so a key kept in `.env` or the user settings file left the
  model out ("isn't set in your settings file or the environment"). Now
  `certo bench` reads the settings files first, as every other command
  does.
- **The benchmark's cost per model** charged the model that writes
  independent tests, and the planner, to the arm's model. Each now has
  its own row. In a run where GPT-6 Luna built and Haiku wrote the
  tests, Haiku's tests were $0.0169 of the run's $0.0214 and Luna's
  build $0.0044; the old table charged all of it to Luna. Totals were
  right.
