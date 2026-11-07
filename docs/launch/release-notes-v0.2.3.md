# Certo v0.2.3

Not released yet.

This release makes it easier to set up more than one model:

- **`certo init` offers more models.** After a passing model check, it
  asks whether to set up more models now, and on yes runs
  `certo init models` at once.
- **`certo --help` lists every command**, each in its own section.

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

## Also

- **`certo --help` lists every subcommand** (`init`, `check`, `models`,
  `skills` and the others) in a section of its own, like the options.
- **Troubleshooting:** `pip` from a Python older than 3.12 finds no
  Certo; the page shows how to install it with uv, which brings its own
  Python.
