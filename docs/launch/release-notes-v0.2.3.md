# Certo v0.2.3

Not released yet.

This release keeps the agent in its project, and makes it easier to set
up more than one model:

- **A task gets its own project folder.** In a Certo workspace, a task
  run without `--project` gets `projects/<name>`, named after the task.
- **The agent stays in its project root.** It is told its root, and
  Certo blocks an action that reaches outside it.
- **`certo init` offers more models.** After a passing model check, it
  asks whether to set up more models now, and on yes runs
  `certo init models` at once.
- **Trusted skill repositories (first step).** List the repositories you
  trust in `skill_sources.yaml`; `certo skills assess` checks and
  classifies every skill in them.
- **`certo --help` lists every command**, each in its own section.

## New: the agent stays in its project root

Run from a Certo workspace (the folder `certo init` makes, with
`projects/` in it) without `--project`, a task used to get the whole
workspace as its folder. The agent then chose a subfolder itself, read
the other projects, and Certo's checks found several projects and ended
`stuck`. Now:

- **A task gets its own project folder**, named after the task file, its
  title or its first words, and Certo says which before the run:

  ```text
  Project: projects/farewell, named after the task. The agent works only in that folder.
  ```

  A folder that already exists isn't reused: the new task gets
  `farewell-2`, and `--project farewell` works on the old one.
- **The agent is told its project root**, and that nothing above or
  beside it is part of the task.
- **Certo blocks an action that reaches outside the root** before it
  runs: the file editor outside the root, or a command like `ls ..`,
  `cat ../other/file` or `cd ~`. The agent is told why and carries on:

  ```text
  Certo blocked an action outside the project root: <workspace>/projects is outside the project root <workspace>/projects/farewell-3. Work only inside the project root: nothing outside it is part of the task.
  ```

  It is a guard rail, not a sandbox; `--execution docker` is the
  sandbox. Three live runs are in
  [The project root in 0.2.3](../benchmark/project-root-0.2.3.md).

See [Safety](../concepts/safety.md#what-the-agent-can-do) and
[`certo`](../reference/commands.md#certo).

## New: `certo init` offers more models

`certo init` sets up one model. Setting up more of them, with keys for
other providers, and choosing `--auto-model` or `--escalate` for every
run, was a separate command, `certo init models`, which the setup never
named. Now, when the model check passed and the settings are for all
projects, `certo init` asks:

```text
Set up more models now?
▸  1. No, one model is enough for now
   2. Yes: add models and keys, then choose how Certo uses them
```

The default is No: one model is all you need to start. Yes runs
`certo init models` in the same session, starting from the model you
just saved. Under "Next", `certo init` now also lists
`certo init models`, so you can do it later. See
[`certo init`](../reference/commands.md#certo-init).

## New: trusted skill repositories, first step

Instead of adding skills one by one, list the git repositories you trust
in `skill_sources.yaml` (`~/.config/certo/` for every project, or
`<project>/.certo/` for one), then run:

```bash
certo skills assess --global
```

Certo downloads each repository at an exact commit and checks every skill
in it with the same rules as `certo skills add`: license, scripts, size,
how it fires. Each skill is classified (testing, review, setup...;
python, node...) by fixed rules, with no model call, and gets a verdict:
`usable`, `needs review` or `rejected`. On `OpenHands/extensions`, 73
skills: 52 usable, 15 to review, 6 rejected.

Runs don't use these skills yet; that is the next step. See
[Trust a whole repository](../guides/manage-skills.md#trust-a-whole-repository).

## Also

- **`certo --help` lists every subcommand** (`init`, `check`, `models`,
  `skills` and the others) in a section of its own, like the options.
- **Troubleshooting:** `pip` from a Python older than 3.12 finds no
  Certo; the page shows how to install it with uv, which brings its own
  Python.
