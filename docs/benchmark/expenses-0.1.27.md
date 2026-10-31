# Benchmark: a smaller app task in milestones on a local model, Certo 0.1.27

The fifth run of milestone mode on a local model. Four runs on the
spreadsheet task ([the last one](milestones-60min-0.1.27.md)) never
ended `verified` on `qwen3.8:27b`: the best got through 3 of its 5
milestones. This run uses a new, smaller app task, `expenses`, with the
same model and settings as the last spreadsheet run: 60 minutes per
milestone.

## The task

`expenses` (task set `apps-2`, in `app-tasks/`) is an expense ledger in
Python, standard library only, in one file, with pytest tests:

1. **Entries:** add, get, remove and list expenses, with a date, an
   amount in cents, a category and a note; invalid values raise
   `ValueError`.
2. **Totals:** by category, by month, by category in a month, and
   amounts written with two decimals.
3. **Files:** save to JSON and load back, ids included.
4. **The command line:** `python ledger.py FILE COMMAND`, with `add`,
   `remove`, `list` and `report`, errors on standard error and exit
   codes.

It has 80 hidden tests: 35, 23, 6 and 16 for milestones 1 to 4. It is
smaller than the spreadsheet: no formula parser, and no milestone as
big as the spreadsheet's errors and cycles.

## Checking the task on a cloud model first

Before the local run, `claude-haiku-5-5` ran the task once in
milestones and once in one go
([bench-0.1.27-expenses-cloud.yaml](bench-0.1.27-expenses-cloud.yaml)).

- **First version:** both runs passed every hidden test (79 then), but
  the one-go run ended `no_progress`. The task said that the program
  with no arguments exits with code 1. Certo runs `python ledger.py`
  with no arguments as one of its checks, and a program that needs
  arguments passes it only when it prints a `usage:` line and exits
  with code 2 (see
  [Verification by language](../reference/verification-by-language.md)).
  So a correct program failed that check, and Haiku rightly refused to
  break the task to pass it. The task was changed: with no arguments,
  the program prints its usage and exits with code 2, which one more
  hidden test checks.
- **The task as it is now:** both runs `verified`, 80/80 hidden tests,
  in 3m 57s ($0.0499) in milestones and 1m 53s ($0.0224) in one go.

## The setup

- **Certo:** 0.1.27 (not released yet), at commit `1027c51`.
- **Machine running Certo:** Darwin 25.6.0, arm64, Apple M1, 8 CPUs,
  16 GB RAM.
- **Model:** `ollama/qwen3.8:27b` (build `aaee06c39dcf`), on Ollama
  0.40.6 on another machine, with a 65,536-token window and a
  1,200-second limit on each model call.
- **Arm:** `qwen-expenses-milestones`, in milestones, with
  `max_task_seconds: 3600` for each one. 3 repeats, one run at a time,
  on 2026-10-31 from about 17:50 to 19:26 UTC.
  **File:** [bench-0.1.27-expenses-local.yaml](bench-0.1.27-expenses-local.yaml).
- **Results folder:** `bench-results/expenses-local-0.1.27`, on the
  machine that ran it. Grading the saved projects again with
  `scripts/regrade_bench.py` gave the same results.

## Results

| Arm | Hidden tests passed (all 80) | Verified | Fooled | Hidden tests passed, all runs | Median time | Tokens in / out |
|---|---|---|---|---|---|---|
| `qwen-expenses-milestones` | 2/3 | 2/3 | 0 | 226/240 | 29m 04s | 3,036,395 / 145,277 |

Per run:

| Repeat | How it ended | Hidden tests passed | Time |
|---|---|---|---|
| 1 | milestones 1 to 3 `verified`, 4 `unchanged` | 66/80 | 29m 04s |
| 2 | milestones 1 to 4 `verified` | 80/80 | 27m 58s |
| 3 | milestones 1 to 4 `verified` | 80/80 | 37m 41s |

Hidden tests passed per milestone, over the three runs:

| Milestone 1 | Milestone 2 | Milestone 3 | Milestone 4 |
|---|---|---|---|
| 105/105 | 69/69 | 18/18 | 34/48 |

Minutes spent on each milestone (from the saved conversations):

| Repeat | Milestone 1 | Milestone 2 | Milestone 3 | Milestone 4 |
|---|---|---|---|---|
| 1 | 15.6 | 7.6 | 5.0 | 0.9 |
| 2 | 5.7 | 7.8 | 4.5 | 9.9 |
| 3 | 15.9 | 5.0 | 4.0 | 12.8 |

## What the results say

- **A local model built a whole app in milestone mode, and Certo said
  `verified`.** Two of three runs ended `verified`, and in both the 80
  hidden tests, which the agent never saw, all passed. Certo said
  `verified` only when the hidden tests passed: no run fooled it.
- **No milestone came near its 60 minutes.** The longest took 16
  minutes, and a whole run took 28 to 38 minutes. On this smaller task
  the time limit was not what mattered.
- **Repeat 1 ended in under a minute on milestone 4, with 31 minutes
  left.** At the start of milestone 4, qwen wrote a tool call as text
  four times out of five tries: three bare argument objects, then one
  real call, then another one as text. Certo sends at most 3 reminders
  in a conversation (`CERTO_TOOL_CALL_REMINDERS`), so the fourth ended
  the conversation. No file had changed, Certo asked once for a change,
  got one more tool call as text, and reported `unchanged`. The verdict
  was right: milestone 4 was not done (2 of 16 hidden tests, the ones
  milestones 1 to 3 already pass).
- **Repeat 3 also used all three reminders**, in milestone 1, and still
  finished: there, qwen went on with real calls after the third.

## What to try next

- Count the reminders only while the model writes tool calls as text
  in a row, not over the whole conversation: in repeat 1, qwen made a
  real call between them. A change to how Certo behaves, so it needs a
  benchmark on a local and a cloud model first. It is in `TODO.md`.
- More runs on this task, to know the rate better than 2 of 3.

## Related

- [The last spreadsheet run, 60 minutes per milestone](milestones-60min-0.1.27.md)
- [Run a task in milestones](../guides/run-in-milestones.md)
- [Build an app in several tasks](../guides/build-an-app-in-several-tasks.md)
