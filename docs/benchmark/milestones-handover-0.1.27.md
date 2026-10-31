# Benchmark: milestones with a handover on a local model, Certo 0.1.27

The third run of [milestone mode on a local model](milestones-0.1.27.md),
and the milestone arm of [the second run](milestones-64k-0.1.27.md)
again, with one change: each new milestone now gets what the last one
left. That is the project's files with their sizes, and the agent's own
summary at the end of the last milestone, marked as not checked. The
second run spent most of its time planning at the start of each new
milestone; this run measures whether the handover helps.

## The setup

- **Certo:** 0.1.27 (not released yet), at commit `9ba08bc`.
- **Machine running Certo:** Darwin 25.6.0, arm64, Apple M1, 8 CPUs,
  16 GB RAM.
- **Task `spreadsheet`** (task set `apps-1`, `5b5cd2015e1e`): the same
  as before, with 111 hidden tests: 37, 6, 26, 29 and 13 for
  milestones 1 to 5.
- **Model:** `ollama/qwen3.8:27b` (build `aaee06c39dcf`), on Ollama
  0.40.6 on another machine, with a 65,536-token window and a
  1,200-second limit on each model call.
- **Arm:** `qwen-milestones-handover`, in milestones, with
  `max_task_seconds: 2400` for each one, as `qwen-milestones-64k` in
  the second run. 3 repeats, one run at a time, on 2026-10-30 and 31
  from 23:22 to 02:31 UTC.
  **File:** [bench-0.1.27-milestones-handover-local.yaml](bench-0.1.27-milestones-handover-local.yaml).
- **Results folder:** `bench-results/milestones-handover-0.1.27`, on
  the machine that ran it.

## Results

| Arm | Hidden tests passed (all 111) | Verified | Hidden tests passed, all runs | Median time | Tokens out |
|---|---|---|---|---|---|
| `qwen-milestones-64k` (second run, no handover) | 0/3 | 0/3 | 85/333 | 77m 38s | 239,324 |
| `qwen-milestones-handover` | 0/3 | 0/3 | 127/333 | 58m 44s | 301,773 |

Per run (how far it got, hidden tests passed):

| Repeat | `qwen-milestones-64k` | `qwen-milestones-handover` |
|---|---|---|
| 1 | milestones 1 and 2 `verified`, out of time on 3; 43/111 | milestones 1 and 2 `verified`, 3 `unchanged`; 43/111 |
| 2 | milestones 1 and 2 `verified`, out of time on 3; 42/111 | milestones 1 and 2 `verified`, 3 `unchanged`; 42/111 |
| 3 | out of time on milestone 1, no file; 0/111 | milestones 1 and 2 `verified`, out of time on 3; 42/111 |

Hidden tests passed per milestone, over the three runs:

| Arm | Milestone 1 | Milestone 2 | Milestone 3 | Milestone 4 | Milestone 5 |
|---|---|---|---|---|---|
| `qwen-milestones-64k` | 73/111 | 10/18 | 0/78 | 0/87 | 2/39 |
| `qwen-milestones-handover` | 109/111 | 15/18 | 0/78 | 0/87 | 3/39 |

Minutes spent on each milestone (from the saved conversations; the
last one ends at the run's last message):

| Repeat | `qwen-milestones-64k` | `qwen-milestones-handover` |
|---|---|---|
| 1 | 12.8, 32.2, 40.0 | 24.8, 33.3, 0.6 |
| 2 | 21.4, 16.1, 40.0 | 21.2, 17.4, 6.0 |
| 3 | 38.3 | 15.2, 30.2, 40.0 |

## What the results say

- **Every run had milestones 1 and 2 `verified`**, against two of three
  before. The difference is one run, which can be chance with 3 runs
  per arm: the handover only reaches milestone 2 onwards, and the run
  that failed before failed on milestone 1.
- **No run got through milestone 3, for two different reasons.**
  - Repeat 3 read the project, ran the tests, planned, and ran out of
    its 40 minutes before its first edit, as both runs in the second
    run did. With the handover in its task, it still read `sheet.py`,
    the tests and the README first: 8 tool calls in 40 minutes.
  - Repeats 1 and 2 ended milestone 3 within minutes with no change.
    In both, qwen wrote a tool call as text instead of making it, so
    the agent framework took it as the final answer. Certo already
    sends a reminder for that, but these two messages had shapes it
    didn't recognise: `{"command": "file_editor", "arguments": {...}}`
    in repeat 1, and `{"type": "tool_result", "tool_use_id": "call_1",
    "content": "Let me continue viewing the rest of the test file..."}`
    in repeat 2. Certo then asked once for a change (no file had
    changed), got the same kind of text again, and reported
    `unchanged`.
- **No model call hit the 1,200-second limit**, against seven in the
  second run. The only time-out was the call cut off when repeat 3's
  time ran out.

## What to try next

- Recognise both shapes above as tool calls written as text, so the
  reminder is sent and the run goes on. Done after this run: Certo now
  recognises both.
- Give each milestone more time, or ask the model to plan less before
  its first edit: on milestone 3, qwen still spends more than 40
  minutes before editing.

## Related

- [The first run, at 32,768 tokens](milestones-0.1.27.md)
- [The second run, with a 65,536-token window](milestones-64k-0.1.27.md)
- [The fourth run, with 60 minutes per milestone](milestones-60min-0.1.27.md)
- [Run a task in milestones](../guides/run-in-milestones.md)
- [Build an app in several tasks](../guides/build-an-app-in-several-tasks.md)
