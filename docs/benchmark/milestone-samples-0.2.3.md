# The three milestone samples, first runs (Certo 0.2.3)

The first runs of the bigger samples `certo init` puts in `tasks/`:
whether each builds, milestone by milestone, on a cheap cloud model,
and what it costs. One run each, not a benchmark.

## The setup

- **Certo:** 0.2.3 from the repository (unreleased), local execution.
- **Machine:** Darwin 25.6.0, arm64, Apple M1.
- **Run:** 2026-11-07, from 15:28 UTC, one sample after the other.
- **Models:** a ladder, `claude-haiku-5-5` then `claude-sonnet-5-5`, both
  at effort `high`: each milestone starts on Haiku and moves to Sonnet
  only when Haiku can't pass its checks. `CERTO_MAX_TASK_COST=1` per
  milestone.
- **Tasks:** the samples as shipped,
  [`sky-hopper.md`](../../src/certo/starter/tasks/sky-hopper.md),
  [`iron-horizon.md`](../../src/certo/starter/tasks/iron-horizon.md) and
  [`team-board.md`](../../src/certo/starter/tasks/team-board.md).
- **How they were started:** as a user would, from a workspace with
  `tasks/` and `projects/`, with no `--milestones` and no `--project`:

  ```bash
  certo tasks/sky-hopper.md
  ```

  Each printed, before it began:

  ```text
  Certo: tasks/sky-hopper.md is written in 4 milestones, so it runs milestone by milestone (--no-milestones runs it as one task).
  Project: projects/sky-hopper, named after the task. The agent works only in that folder.
  ```

## Results

| Sample | Milestones `verified` | Model used | Tests at the end | Time | Tokens | Cost |
|---|---|---|---|---|---|---|
| `sky-hopper` | 4/4 | Haiku only | 42 passing (`npm test`) | 22m 41s | 11,385,318 | $0.8349 |
| `iron-horizon` | 4/4 | Haiku only | 84 passing (`npm test`) | 14m 20s | 5,909,460 | $0.3427 |
| `team-board` (second run) | 5/5 | Haiku only | 136 passing (pytest) | 47m 06s | 17,146,056 | $1.1074 |

The ladder never climbed: every milestone passed on Haiku with no fix
attempt. Per milestone:

| Sample | Milestone | Time | Cost |
|---|---|---|---|
| `sky-hopper` | 1. The level and the camera | 1m 57s | $0.0244 |
| | 2. Running and jumping | 3m 46s | $0.0410 |
| | 3. Parallax, coins and blocks | 3m 56s | $0.0543 |
| | 4. Enemies, the flag and the next level | 13m 01s | $0.7152 |
| `iron-horizon` | 1. The 3D view and driving | 2m 18s | $0.0310 |
| | 2. The horizon and collisions | 3m 38s | $0.0453 |
| | 3. Shells and enemy tanks | 4m 49s | $0.1571 |
| | 4. Radar, waves and game over | 3m 33s | $0.1093 |
| `team-board` | 1. Accounts and sessions | 2m 49s | $0.0369 |
| | 2. Projects, members and roles | 5m 04s | $0.0426 |
| | 3. Columns and cards | 5m 28s | $0.1168 |
| | 4. Comments, history and search | 14m 42s | $0.3064 |
| | 5. The web interface | 19m 03s | $0.6046 |

## What the runs found

- **A mistake in the `team-board` task, fixed.** The first run stopped at
  milestone 2 with `acceptance_failed` (5m 22s, $0.0530): the agent put
  the members routes in `taskboard/projects.py`, as the task's "one
  module per area" allowed, and its tests passed, but the milestone's
  acceptance check looked only in `app.py`. The task now names
  `projects.py` and the check looks there; the second run, above, used
  the fixed task.
- **The agent looked for a browser.** Two actions were blocked outside
  the project root, both in `/Applications`: once while building the
  board's interface, once looking for Chromium to check the tank game in
  a real browser. The runs went on. `/Applications` is to become an
  allowed system folder (TODO.md).

## What this doesn't show

`verified` means each milestone's checks and the project's tests passed:
the game rules, the 3D maths, the API and its permissions. It doesn't say
how the games look or play, or how pleasant the board is to use; that
needs a person to open them. One run each, on one model.
