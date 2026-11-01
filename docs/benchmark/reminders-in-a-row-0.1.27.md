# Benchmark: tool-call reminders counted in a row, Certo 0.1.27

When a model writes a tool call as text, Certo reminds it to make the
call, up to `CERTO_TOOL_CALL_REMINDERS` times (default 3). Until commit
`bf9e5cd`, the limit counted every reminder in a conversation. In
[the expenses run](expenses-0.1.27.md), that stopped `qwen3.8:27b`
with 31 minutes left, though it had made a real call between the
reminders. Now the limit counts only the reminders in a row: a real
tool call after a reminder starts the count again.

This run measures the change: the same task and settings as the
expenses run, on the local model with 5 repeats, and on a cloud model
to show that its runs don't change.

## The setup

- **Certo:** 0.1.27 (not released yet), at commit `bf9e5cd`.
- **Machine running Certo:** Darwin 25.6.0, arm64, Apple M1, 8 CPUs,
  16 GB RAM.
- **Task:** `expenses` (task set `apps-2`), in milestones: an expense
  ledger in 4 milestones, 80 hidden tests. See
  [the expenses run](expenses-0.1.27.md#the-task).
- **Local arm:** `qwen-expenses-in-a-row`, `ollama/qwen3.8:27b` (build
  `aaee06c39dcf`) on Ollama 0.40.6 on another machine, a 65,536-token
  window, 60 minutes per milestone, a 1,200-second limit on each model
  call. 5 repeats, one at a time, on 2026-10-31 from 23:20 to
  2026-11-01 01:30 UTC.
  **File:** [bench-0.1.27-reminders-in-a-row-local.yaml](bench-0.1.27-reminders-in-a-row-local.yaml).
- **Cloud arm:** `haiku-expenses-in-a-row`, `claude-haiku-5-5`, in
  milestones, 3 repeats, on 2026-10-31.
  **File:** [bench-0.1.27-reminders-in-a-row-cloud.yaml](bench-0.1.27-reminders-in-a-row-cloud.yaml).
- **Results folders:** `bench-results/reminders-in-a-row-local-0.1.27`
  and `bench-results/reminders-in-a-row-cloud-0.1.27`, on the machine
  that ran them. Grading the saved local projects again with
  `scripts/regrade_bench.py` gave the same results.

## Results

| Arm | Hidden tests passed (all 80) | Verified | Fooled | Median time | Tokens in / out | Cost |
|---|---|---|---|---|---|---|
| `qwen-expenses-in-a-row` | 2/5 | 2/5 | 0 | 27m 41s | 4,293,783 / 151,432 | $0 (local) |
| `haiku-expenses-in-a-row` | 3/3 | 3/3 | 0 | 4m 54s | 4,235,166 / 158,886 | $0.1655 |

The local runs, one by one:

| Repeat | How it ended | Hidden tests passed | Reminders | Time |
|---|---|---|---|---|
| 1 | milestones 1 and 2 `verified`, 3 `unchanged` | 60/80 | 3, in milestone 3 | 27m 41s |
| 2 | milestones 1 to 4 `verified` | 80/80 | 17, in milestone 2 | 40m 45s |
| 3 | milestone 1 `verified`, 2 `unchanged` | 2/80 | 3, in milestone 2 | 7m 41s |
| 4 | milestones 1 and 2 `verified`, 3 `acceptance_failed` | 60/80 | 0 | 19m 27s |
| 5 | milestones 1 to 4 `verified` | 80/80 | 0 | 34m 09s |

Repeat 3 stopped before milestone 2 was written, so the hidden tests
of milestones 1 to 3 could not even load (`format_cents` is missing);
only the 2 tests of milestone 4 that need no new code passed.

Haiku passed every hidden test in all 3 runs (240/240) and got no
reminder.

## What the results say

- **The change kept one run alive, and that run was verified.** In
  repeat 2, milestone 2, qwen got 17 reminders, never more than 3 in a
  row, with real tool calls between them. Counted over the whole
  conversation, as before, it would have got no reminder after the
  third, and the next tool call as text after Certo's one request for a
  change would have ended the milestone. Counted in a row, it went on,
  and milestones 2 to 4 ended `verified` with 80/80 hidden tests.
- **The change made no run worse.** In repeats 1 and 3, qwen wrote the
  same tool call, with the same arguments, as text four times in a
  row: from the first reply of the milestone (repeat 3), or after some
  work (repeat 1). Both counts stop it at the same point. After Certo's
  one request for a change, it wrote a tool call as text again.
- **Repeat 4 failed for another reason.** In milestone 3, qwen twice
  ended its turn with a sentence of plans ("Now let me add the `save`
  and `load` methods"), written as text, without a tool call. That is
  not a tool call, so no reminder was sent; Certo's one request for a
  change got one real edit, then the same kind of sentence. Milestone 3
  had no `load`, and its acceptance check failed. This is now in
  `TODO.md`.
- **Cloud runs did not change.** Haiku makes real tool calls, so it
  got no reminder, and all three runs were verified as before.
- **2 of 5 here, 2 of 3 before:** over the 8 local runs on this task,
  4 were verified. With so few runs, the two rates can't be told apart;
  what can be seen is which runs the change touched (repeat 2 only).

## Related

- [The expenses run, where the per-conversation count stopped a run](expenses-0.1.27.md)
- [Tool-call reminders in 0.1.26](reminders-0.1.26.md)
- [Troubleshooting: a tool call as the agent's last message](../troubleshooting.md#the-run-ends-at-once-with-a-tool-call-as-the-agents-last-message)
