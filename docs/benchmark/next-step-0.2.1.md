# Benchmark: a turn that ends on a sentence of plans, Certo 0.2.1

Some local models end their turn with a sentence that only says what
they will do next, such as "Now let me add the `save` and `load`
methods", and no tool call. In
[the last expenses runs](reminders-in-a-row-0.1.27.md), that ended
repeat 4 with milestone 3 half done. Since commit `71d85b3`, Certo
sends such a turn back, as it does for a tool call written as text,
within the same `CERTO_TOOL_CALL_REMINDERS` limit.

This run repeats the same task and settings on the local model with 5
repeats, and on a cloud model to show that its runs don't change.

## The setup

- **Certo:** 0.2.1 (not released yet), at commit `71d85b3`.
- **Machine running Certo:** Darwin 25.6.0, arm64, Apple M1, 8 CPUs,
  16 GB RAM.
- **Task:** `expenses` (task set `apps-2`), in milestones: an expense
  ledger in 4 milestones, 80 hidden tests. See
  [the expenses run](expenses-0.1.27.md#the-task).
- **Local arm:** `qwen-expenses-next-step`, `ollama/qwen3.8:27b` (build
  `aaee06c39dcf`) on Ollama 0.40.6 on another machine, a 65,536-token
  window, 60 minutes per milestone. 5 repeats, one at a time, started
  on 2026-11-01 at 22:53 UTC, 2 hours 8 minutes in all.
  **File:** [bench-0.2.1-next-step-local.yaml](bench-0.2.1-next-step-local.yaml).
- **Cloud arm:** `haiku-expenses-next-step`, `claude-haiku-5-5`, in
  milestones, 3 repeats, on 2026-11-01.
  **File:** [bench-0.2.1-next-step-cloud.yaml](bench-0.2.1-next-step-cloud.yaml).
- **Results folders:** `bench-results/next-step-local-0.2.1` and
  `bench-results/next-step-cloud-0.2.1`, on the machine that ran them.

## Results

| Arm | Hidden tests passed (all 80) | Verified | Fooled | Median time | Tokens in / out | Cost |
|---|---|---|---|---|---|---|
| `qwen-expenses-next-step` | 5/5 | 5/5 | 0 | 24m 32s | 6,353,258 / 191,797 | $0 (local) |
| `haiku-expenses-next-step` | 3/3 | 3/3 | 0 | 4m 41s | 4,088,955 / 159,493 | $0.1646 |

The same arms before the change, in
[0.1.27](reminders-in-a-row-0.1.27.md): qwen 2/5 verified, median
27m 41s; Haiku 3/3 verified, median 4m 54s, $0.1655.

The local runs, one by one:

| Repeat | How it ended | Hidden tests passed | Reminders | Time |
|---|---|---|---|---|
| 1 | milestones 1 to 4 `verified` | 80/80 | 0 | 26m 41s |
| 2 | milestones 1 to 4 `verified` | 80/80 | 0 | 24m 32s |
| 3 | milestones 1 to 4 `verified` | 80/80 | 0 | 31m 14s |
| 4 | milestones 1 to 4 `verified` | 80/80 | 0 | 21m 50s |
| 5 | milestones 1 to 4 `verified` | 80/80 | 7 for a tool call as text, in milestone 1 | 23m 43s |

Haiku passed every hidden test in all 3 runs (240/240) and got no
reminder of either kind.

## What the results say

- **The new reminder was never sent.** No run, local or cloud, ended
  a turn on a sentence of plans, so this run can't show what the
  reminder does when it fires. The 5/5 is not its doing: the runs
  that failed in 0.1.27 failed on tool calls written as text (repeats
  1 and 3) or on a sentence of plans (repeat 4), and this time neither
  happened enough to stop a run.
- **The only reminders were for tool calls as text.** In repeat 5,
  milestone 1, qwen got 7 of them, never more than 2 in a row, with
  real tool calls between them, and the milestone ended `verified`.
- **The change made no run worse.** All 5 local runs and all 3 cloud
  runs were verified, with all hidden tests passed.
- **Cloud runs did not change.** Haiku got no reminder, as in 0.1.27,
  with about the same time and cost.
- **5 of 5 here, 4 of 8 before:** over the 13 local runs on this task
  (3 in [the expenses run](expenses-0.1.27.md), 5 in 0.1.27, 5 here),
  9 were verified. With so few runs, and the reminder never sent, the
  rates can't be credited to the change. The
  [replay of saved endings](#the-replay-of-saved-endings) is what shows
  which endings it catches.

## The replay of saved endings

Before this run, the check was run on the last agent message of every
saved benchmark conversation: 426 endings. It found the sentence of
plans 4 times, all among the 198 endings from local models, and none
among the 210 from cloud models.

## Related

- [The run before: tool-call reminders counted in a row](reminders-in-a-row-0.1.27.md)
- [The expenses run](expenses-0.1.27.md)
- [Troubleshooting: the run ends on a sentence of plans](../troubleshooting.md#the-run-ends-on-a-sentence-of-plans)
