# Certo v0.1.27

Not released yet.

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

## New: two official skills

- `python-environment`, when a task mentions pip, a virtual environment
  or the dependency files: declare each dependency in the project's file
  and install from it, into the project's own environment, with test
  tools as development dependencies.
- `node-project-setup`, when a task mentions Node, npm, JavaScript or
  TypeScript: a real `test` script, a `build` script when there is a
  build step, the lockfile kept, and scaffolders run without prompts.

Both help the project pass Certo's checks on the next machine too. See
[Manage skills](../guides/manage-skills.md).

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

## New: Ollama details in `certo check`

For an Ollama model, `certo check` now also prints the server version,
the context window a run will get and where that number comes from
(`CERTO_LLM_CONTEXT_TOKENS` or the server), and how long the test
request took. When the window is below `CERTO_CONTEXT_WARN_TOKENS`, it
prints the same warning a run does. Cloud models print what they did
before. Thanks to [@Tusharkanda](https://github.com/Tusharkanda)
([#40](https://github.com/alessioricco/certo/pull/40)). See
[Commands](../reference/commands.md#certo-check).

## Benchmark: tasks in milestones

A benchmark arm with `milestones: true` runs a task written in
milestones milestone by milestone; any other arm gets the same task in
one go, so one task compares the two ways. Each run's record lists the
milestones' verdicts. For a task whose hidden tests are named by
milestone (`test_m1_...`), `results.md` shows the hidden tests passed
per milestone. See
[the benchmark file reference](../reference/bench-yaml.md#arms) and
[Benchmark models and strategies](../guides/benchmark.md).

## Fixed

- When the time budget or cost limit ran out during the agent's last
  step, the checks passed, and the agent had changed no file, Certo
  printed "the work is verified", then asked the agent once more with
  no time left, and ended `budget_exhausted`. It now says in one notice
  that the checks pass but nothing changed, and the verdict stays
  `budget_exhausted` (or `cost_exhausted`).
- Two more shapes of a tool call written as text are now recognised,
  so Certo sends its reminder instead of ending the run:
  `{"command": "file_editor", "arguments": {...}}`, and a tool-use or
  tool-result block such as `{"type": "tool_result", "tool_use_id":
  "call_1", ...}`. `qwen3.8:27b` ended two of three milestone runs this
  way in the local benchmark.
- With `--milestones --escalate`, the run summary at the end listed only
  the last milestone's rungs, under the totals of the whole run, and the
  README note in a project Certo created named only the models of the
  last milestone. Each milestone's rungs are now listed under its
  verdict, and the note names every model that wrote code.
- Security updates in the lock file: authlib 1.9.1, dnspython 2.9.1,
  litellm 1.100.4, joserfc 1.7.7, pyasn1 0.6.5 and pypdf 6.21.4.
