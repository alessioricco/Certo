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
note names only the command the agent ran. Not measured yet in the
benchmark.

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

## Fixed

- **The benchmark's cost per model** charged the model that writes
  independent tests, and the planner, to the arm's model. Each now has
  its own row. In a run where GPT-6 Luna built and Haiku wrote the
  tests, Haiku's tests were $0.0169 of the run's $0.0214 and Luna's
  build $0.0044; the old table charged all of it to Luna. Totals were
  right.
