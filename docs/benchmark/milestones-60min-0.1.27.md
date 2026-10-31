# Benchmark: milestones with 60 minutes each on a local model, Certo 0.1.27

The fourth run of [milestone mode on a local model](milestones-0.1.27.md).
It is [the third run](milestones-handover-0.1.27.md) again with two
changes. Each milestone now gets 60 minutes instead of 40, because in
the third run qwen ran out of time on milestone 3 before its first
edit. And Certo now recognises the two shapes of a tool call written
as text that ended two runs of the third run.

## The setup

- **Certo:** 0.1.27 (not released yet), at commit `2391b11`.
- **Machine running Certo:** Darwin 25.6.0, arm64, Apple M1, 8 CPUs,
  16 GB RAM.
- **Task `spreadsheet`** (task set `apps-1`, `5b5cd2015e1e`): the same
  as before, with 111 hidden tests: 37, 6, 26, 29 and 13 for
  milestones 1 to 5.
- **Model:** `ollama/qwen3.8:27b` (build `aaee06c39dcf`), on Ollama
  0.40.6 on another machine, with a 65,536-token window and a
  1,200-second limit on each model call.
- **Arm:** `qwen-milestones-60min`, in milestones, with
  `max_task_seconds: 3600` for each one. 3 repeats, one run at a time,
  on 2026-10-31 from 09:12 to 17:10 UTC.
  **File:** [bench-0.1.27-milestones-60min-local.yaml](bench-0.1.27-milestones-60min-local.yaml).
- **Results folder:** `bench-results/milestones-60min-0.1.27`, on the
  machine that ran it. Grading the saved projects again with
  `scripts/regrade_bench.py` gave the same results.

## Results

| Arm | Minutes per milestone | Hidden tests passed (all 111) | Verified | Hidden tests passed, all runs | Median time | Tokens out |
|---|---|---|---|---|---|---|
| `qwen-milestones-64k` (second run) | 40 | 0/3 | 0/3 | 85/333 | 77m 38s | 239,324 |
| `qwen-milestones-handover` (third run) | 40 | 0/3 | 0/3 | 127/333 | 58m 44s | 301,773 |
| `qwen-milestones-60min` | 60 | 0/3 | 0/3 | 249/333 | 173m 25s | 684,922 |

The tokens of repeat 3 are added up from the run's log, because its
record has only milestone 4's (see the last section).

Per run (how far it got, hidden tests passed):

| Repeat | `qwen-milestones-handover` (third run) | `qwen-milestones-60min` |
|---|---|---|
| 1 | milestones 1 and 2 `verified`, 3 `unchanged`; 43/111 | milestones 1 to 3 `verified`, 4 `retry_exhausted`; 94/111 |
| 2 | milestones 1 and 2 `verified`, 3 `unchanged`; 42/111 | milestones 1 to 3 `verified`, out of time on 4; 88/111 |
| 3 | milestones 1 and 2 `verified`, out of time on 3; 42/111 | milestones 1 to 3 `verified`, the model server lost on 4 (error); 67/111 |

Hidden tests passed per milestone, over the three runs:

| Arm | Milestone 1 | Milestone 2 | Milestone 3 | Milestone 4 | Milestone 5 |
|---|---|---|---|---|---|
| `qwen-milestones-64k` | 73/111 | 10/18 | 0/78 | 0/87 | 2/39 |
| `qwen-milestones-handover` | 109/111 | 15/18 | 0/78 | 0/87 | 3/39 |
| `qwen-milestones-60min` | 109/111 | 15/18 | 73/78 | 49/87 | 3/39 |

Minutes spent on each milestone (from the saved conversations; the
last one ends at the run's last message):

| Repeat | Milestone 1 | Milestone 2 | Milestone 3 | Milestone 4 |
|---|---|---|---|---|
| 1 | 23.9 | 48.8 | 60.1 | 42.1 |
| 2 | 26.0 | 27.3 | 60.1 | 59.8 |
| 3 | 34.6 | 13.2 | 31.9 | 27.1 |

## What the results say

- **Every run got through milestone 3**, which no run of the second or
  third run did. Hidden tests passed went from 127/333 to 249/333, and
  milestone 3's from 0/78 to 73/78. With 3 runs per arm the size of the
  gain is uncertain, but every run moved the same way.
- **Two of the three milestone 3s needed the whole hour.** In repeats 1
  and 2, the time ran out during qwen's last step; the project's tests
  and the acceptance checks of milestones 1 to 3 passed, so Certo said
  `verified`. Repeat 3 finished milestone 3 in 32 minutes.
- **Milestone 4 is where it stops now.**
  - Repeat 1 finished milestone 4 in 27 minutes. Its own tests still
    failed after two fix attempts, so the verdict was
    `retry_exhausted`. The hidden tests passed 27 of 29 for that
    milestone.
  - Repeat 2 ran out of its 60 minutes on milestone 4, with 22 of 29
    hidden tests passing.
  - In repeat 3, after 27 minutes on milestone 4, qwen gave an empty
    reply. The next model call reached its 1,200-second limit, and then
    the Ollama machine was no longer on the network. The run ended in
    an error with nothing of milestone 4 in place (0 of 29).
- **The new tool-call shapes were caught.** qwen wrote a tool call as
  text six times: three `tool_use` blocks in repeat 1, milestone 4, and
  three bare argument objects in repeat 3, milestone 1. Each time
  Certo sent its reminder and the run went on. In the third run, the
  same shapes had ended two runs as `unchanged`.
- **Five model calls hit the 1,200-second limit**, two each in repeats 1
  and 2 and one in repeat 3, against none in the third run.
- **Milestone 5 was never reached.** Its 3/39 are hidden tests that the
  code from earlier milestones already passes.

## A bug this run found

Repeat 3's record has 69,006 tokens in and 44,392 out, only what
milestone 4 used before the error. Milestones 1 to 3 used about
1,384,000 in and 129,000 out (from the log). When a milestone stops on
an error, the benchmark record keeps only that milestone's usage. The
cost is $0 on this local model, but on a paid model the record would
show too little. Fixed after this run: the record now adds up every
milestone that ran.

## What to try next

- Phase 3 is not closed: no run ended `verified`. The next step is
  either more time again (milestone 4 used all 60 minutes once) or a
  smaller app task, as planned.
- A run on a machine that doesn't sleep or lose its network: repeat 3
  may have reached milestone 5.

## Related

- [The first run, at 32,768 tokens](milestones-0.1.27.md)
- [The second run, with a 65,536-token window](milestones-64k-0.1.27.md)
- [The third run, with a handover between milestones](milestones-handover-0.1.27.md)
- [Run a task in milestones](../guides/run-in-milestones.md)
- [Build an app in several tasks](../guides/build-an-app-in-several-tasks.md)
