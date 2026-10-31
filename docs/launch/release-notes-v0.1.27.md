# Certo v0.1.27

Not released yet.

This release is about bigger tasks, and about setting Certo up:

- **Run a task in milestones** (experimental): a task file split into
  milestones, each checked before the next starts, and resumed from the
  one that failed.
- **Two official skills** for project setup, in Python and in Node, so
  a project's dependencies and tests work on the next machine too.
- **`certo check` shows Ollama's details**: the server version and the
  context window a run will get, thanks to @Tusharkanda.
- **The model files are enough** for `--escalate` and `--auto-model`,
  and Certo says when a newer version is out.
- **Also:** the old planning documents moved to `docs/history/`, thanks
  to @jiangyuer018, and five fixes.

## New (experimental): run a task in milestones

`certo --milestones task.md` splits a task file at its
`## Milestone N: title` headings and runs the milestones one at a time,
each in its own conversation. Each one must be `verified` before the
next starts: its own work, the project's tests, and the acceptance
checks of every milestone so far, written in an ` ```acceptance ` block
inside the milestone. When one fails, Certo stops there and keeps the
earlier work; `certo --resume` continues that milestone, then the rest.

```text
Milestones:
  1. Celsius and Fahrenheit: verified
  2. Kelvin: verified

Verification: verified
```

Each milestone after the first also gets what the last one left: the
project's files with their sizes, and the agent's own summary when it
finished, so it doesn't start by exploring the folder from nothing.

The time, cost and step limits apply to each milestone. Certo keeps only
the milestones' titles and verdicts in `.certo/`, never their acceptance
checks, because the agent can read that folder.

With `--escalate`, each milestone climbs its own ladder from the first
rung, and `certo --resume --escalate` starts a failed milestone again on
the first rung, told how the last try ended. With `--independent-tests`,
each milestone gets its own tests, written before it starts. See
[Run a task in milestones](../guides/run-in-milestones.md).

**In the benchmark**, an arm with `milestones: true` runs a task written
in milestones milestone by milestone; any other arm gets the same task
in one go, so one task compares the two ways. For a task whose hidden
tests are named by milestone (`test_m1_...`), `results.md` shows the
hidden tests passed per milestone. See
[the benchmark file reference](../reference/bench-yaml.md#arms).

## New: two official skills

- `python-environment`, when a task mentions pip, a virtual environment
  or the dependency files: declare each dependency in the project's file
  and install from it, into the project's own environment, with test
  tools as development dependencies.
- `node-project-setup`, when a task mentions Node, npm, JavaScript or
  TypeScript: a real `test` script, a `build` script when there is a
  build step, the lockfile kept, and scaffolders run without prompts.

See [Manage skills](../guides/manage-skills.md).

## New: Ollama details in `certo check`

For an Ollama model, `certo check` now also prints the server version,
the context window a run will get and where that number comes from
(`CERTO_LLM_CONTEXT_TOKENS` or the server), and how long the test
request took. When the window is below `CERTO_CONTEXT_WARN_TOKENS`, it
prints the same warning a run does. Cloud models print what they did
before. Thanks to [@Tusharkanda](https://github.com/Tusharkanda)
([#40](https://github.com/alessioricco/certo/pull/40)). See
[Commands](../reference/commands.md#certo-check).

## Changed: the model files are enough for `--escalate` and `--auto-model`

With `--escalate`, `--auto-model` or `CERTO_MODEL_SELECTION`, Certo no
longer asks for `CERTO_LLM_MODEL` and `CERTO_LLM_API_KEY`: the model
files name every model and its key. A plain `certo "task"` still needs
them; `.env.example` now says which key goes with which model.

## New: a line when a newer Certo is out

When a newer version is on PyPI, `certo` says so in one line at the end
of a command, with the command that updates it:

```text
Certo 0.1.28 is out (you have 0.1.27). To update: uv tool upgrade certo
```

It checks at most once a day, in the background, so it never slows a
run, and only in a terminal: not in CI, a pipe or `certo bench`.
`CERTO_UPDATE_CHECK=0` turns it off. See
[Configuration](../reference/configuration.md#update-check).

## Docs: the old planning documents moved

The original build plan, kickoff prompt and roadmap snapshot are now in
`docs/history/`, so they aren't taken for current docs. Thanks to
[@jiangyuer018](https://github.com/jiangyuer018)
([#42](https://github.com/alessioricco/certo/pull/42)).

## Fixed

- **Out of time with nothing changed.** When the time or cost limit ran
  out during the agent's last step and the agent had changed no file,
  Certo printed "the work is verified" and then asked the agent again
  with no time left. It now says the checks pass but nothing changed,
  and the verdict stays `budget_exhausted` (or `cost_exhausted`).
- **Two more shapes of a tool call written as text** are recognised, so
  Certo sends its reminder instead of ending the run: a `{"command":
  "file_editor", "arguments": {...}}` object, and a tool-use or
  tool-result block. `qwen3.8:27b` ended two of three milestone runs
  this way in the local benchmark.
- **Milestones with a ladder** listed only the last milestone's models
  and costs at the end, under the whole run's totals. Each milestone's
  are now listed under its verdict.
- **An interrupted run's cost.** A run stopped by Ctrl-C or an error now
  has its time, tokens and cost up to the stop in `.certo/RUNS.md`.
- **Security updates** in the lock file: authlib 1.9.1, dnspython 2.9.1,
  litellm 1.100.4, joserfc 1.7.7, pyasn1 0.6.5 and pypdf 6.21.4.
