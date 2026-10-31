# App tasks

Bigger benchmark tasks, written in milestones, in the same shape as the
bundled task set (`task.md`, `hidden_tests/`, `reference/`). They are
kept apart from the bundled set so its version and results stay
comparable.

Each `task.md` splits into `## Milestone N: title` sections, so the same
task runs two ways: an arm with `milestones: true` runs it milestone by
milestone, as `certo --milestones` does; any other arm gets the whole
task at once, without the acceptance blocks, and all of their checks.
Run them with `tasks_dir: app-tasks` in a bench file.

- `spreadsheet`: a spreadsheet engine in Python, standard library only,
  in five milestones: numbers and arithmetic, references, ranges and
  functions, errors and cycles, CSV files and a command line. Hidden
  test names start with their milestone (`test_m1_` to `test_m5_`).
- `expenses`: an expense ledger in Python, standard library only, in
  four smaller milestones: entries, totals, JSON files and a command
  line. Hidden test names start with their milestone (`test_m1_` to
  `test_m4_`). Added in `apps-2`.
