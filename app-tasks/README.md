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
- `job-runner`: an existing project to extend, a job runner in Python
  (`starter/`), in three milestones: priorities, retries and cancelling
  jobs. Its own test suite runs real jobs and takes about 2.5 minutes,
  like a real project's slow suite; the task doesn't say so. It is for
  measuring how a run spends its budget on a slow suite (the slow-test
  note, 0.2.5). The hidden tests are fast. Hidden test names start with
  their milestone (`test_m1_` to `test_m3_`; `test_m1_starter_` is what
  the starter already did). Added in `apps-3`.
