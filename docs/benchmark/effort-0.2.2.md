# Benchmark: a lower reasoning effort first, Certo 0.2.2

An escalation ladder can already put one model on two rungs, each with
its own `reasoning_effort`. Before Certo builds a ladder that tries a
lower effort first on its own, or lets `--auto-model` choose the
effort, TODO.md asks for a measurement: the same model at a low effort,
then high when the low effort fails, against high only, on a cloud and
a local model. The rule: build it only if the lower effort is much
faster and rarely fails.

## The setup

- **Certo:** 0.2.1 at commit `ad4a616`. 0.2.2 adds only the progress
  line, which a benchmark run doesn't print, so the runs are the same.
- **Machine running Certo:** Darwin 25.6.0, arm64, Apple M1, 8 CPUs,
  16 GB RAM.
- **Tasks:** the 13 bundled tasks (task set version 2, `6ed42dae4bca`).
- **Models:** each model is listed twice under two names, one per
  effort, because an arm can't name the same model twice.
  **Files:** [models_list-0.2.2-effort.yaml](models_list-0.2.2-effort.yaml),
  [models-0.2.2-effort.yaml](models-0.2.2-effort.yaml).
- **Cloud:** `anthropic/claude-haiku-5-5`, three arms (`high` only,
  `low` only, `low` then `high`), 3 repeats, 117 runs, on 2026-11-04
  from 09:31 UTC, 47 minutes in all.
  **File:** [bench-0.2.2-effort-cloud.yaml](bench-0.2.2-effort-cloud.yaml).
- **Local:** `ollama/qwen3.8:27b` on Ollama on another machine, a
  65,536-token window, two arms (thinking on only, thinking off then
  on), 1 repeat, 26 runs, from the night of 2026-11-04 to the evening
  of 2026-11-05 (Ollama 0.40.6, model digest `aaee06c39dcf`).
  **File:** [bench-0.2.2-effort-local.yaml](bench-0.2.2-effort-local.yaml).
- **Results folders:** `bench-results/effort-cloud-0.2.2` and
  `bench-results/effort-local-0.2.2`, on the machine that ran them.

## Why the local arms use thinking off, not low

On Ollama, qwen3.8 has no effort levels, only thinking on or off.
LiteLLM sends `low`, `medium` and `high` all as `think: true` (only
gpt-oss models get the level itself), and any other value, such as
`minimal`, as `think: false`. A `low` arm would have run the same model
the same way as the `high` one. So the local "cheaper first" rung is
`minimal`, thinking off.

## Cloud results

| Arm | Hidden tests passed | Verified | Fooled | Median time | Tokens in / out | Cost |
|---|---|---|---|---|---|---|
| `haiku-high` (today's default) | 39/39 | 39/39 | 0 | 52s | 20,435,519 / 787,118 | $0.7979 |
| `haiku-low` | 37/39 | 39/39 | 2 | 26s | 8,452,461 / 388,711 | $0.4215 |
| `haiku-low-then-high` | 37/39 | 39/39 | 2 | 30s | 7,959,781 / 394,178 | $0.4217 |

In the escalation arm, the first rung (`low`) gave the final result in
all 39 runs: the ladder never climbed.

The four runs where Certo was fooled, with the hidden tests graded
again on a copy of their workspaces:

| Arm | Task | Repeat | Hidden test that fails |
|---|---|---|---|
| `haiku-low` | `room-bookings` | 2 | overlaps in the same room only |
| `haiku-low` | `todo-deps` | 3 | `hidden_next` |
| `haiku-low-then-high` | `room-bookings` | 2 | overlaps in the same room only |
| `haiku-low-then-high` | `room-bookings` | 3 | overlaps in the same room only |

All four are bugs in the code the agent wrote, not a hidden test that
is too strict. The `room-bookings` test checks that only bookings in
the same room count as overlapping.

## Local results

The 26 runs took three sittings: the night of 2026-11-04 (the Mac went
to sleep after the first run; the second run was lost and run again),
the morning of 2026-11-05, and the evening of 2026-11-05.

| Arm | Hidden tests passed | Verified | Fooled | Median time | Tokens in / out | Tool-call reminders |
|---|---|---|---|---|---|---|
| `qwen-high` (thinking on) | 11/13 | 12/13 | 1 | 7m 57s | 3,817,405 / 222,132 | 0 |
| `qwen-nothink-then-high` | 12/13 | 12/13 | 0 | 4m 52s | 4,534,891 / 132,691 | 17 |

Both arms cost nothing: the model runs on a local server.

- **Which rung gave the final result:** thinking off in 11 of 13 runs.
  The ladder climbed twice, on `ledger-transfers` and `todo-deps`, and
  both passed the hidden tests on the second rung.
- **Time:** thinking off first was faster on 10 of the 13 tasks, slower
  on 2 (`inventory-fix`, and `todo-deps`, where it climbed) and the same
  on `library-loans`.
- **Fooled:** one run, `qwen-high` on `todo-deps` (hidden tests: 4
  passed, 7 failed). The same task passed in the other arm, after
  the climb.
- **`library-loans` failed in both arms, for different reasons.**
  `qwen-high` worked until the 30-minute run budget ran out. In the
  other arm, Ollama stopped answering: one call timed out after 1,200
  seconds and its retry after 484, so the budget ran out after 455
  output tokens, before the ladder could climb. That run says nothing
  about thinking off.
- **Tool-call reminders:** all 17 were in the thinking-off arm (6 on
  `ledger-transfers`, 4 on `room-bookings`, 7 on `todo-deps`). With
  thinking off, qwen3.8 more often writes a tool call as text.

| Task | `qwen-high` | `qwen-nothink-then-high` | Rung that ended it |
|---|---|---|---|
| `duration-parser` | 24m 59s | 3m 43s | 1 |
| `inventory-fix` | 2m 45s | 3m 21s | 1 |
| `ledger-transfers` | 24m 45s | 23m 22s | 2 |
| `library-loans` | 30m 03s, budget | 30m 05s, budget | 1 |
| `page-ranges` | 5m 41s | 5m 00s | 1 |
| `pedestrian-crossing` | 7m 57s | 2m 07s | 1 |
| `room-bookings` | 17m 47s | 11m 03s | 1 |
| `semver-order` | 6m 20s | 4m 52s | 1 |
| `slugify` | 2m 19s | 1m 56s | 1 |
| `temperature-table` | 2m 48s | 1m 39s | 1 |
| `todo-deps` | 18m 02s, fooled | 30m 05s | 2 |
| `token-bucket` | 4m 20s | 3m 10s | 1 |
| `wordle-score` | 15m 10s | 6m 11s | 1 |

## What the results say

- **On Haiku, low effort is twice as fast and half the cost:** median
  26s against 52s, $0.42 against $0.80.
- **But it fails without Certo noticing.** 4 of the 78 low-effort runs
  passed every check Certo ran and were still wrong; high had none in
  39. Certo's own checks can't tell these apart.
- **Escalation can't help with that.** A ladder climbs only when the
  checks fail. Here they passed, so starting low adds the fooled runs
  and saves the money, and never reaches the high rung.
- **For a cloud model, the rule says don't build it:** low is much
  faster, but it doesn't rarely fail, and it fails the way Certo
  exists to prevent.
- **On qwen3.8, thinking off first looks like the opposite:** median
  4m 52s against 7m 57s, no fooled run, and one more hidden-test pass.
  Here the ladder did climb when the checks failed, and both climbs
  ended in a pass.
- **But it is one repeat of 13 tasks.** A difference of one run, in
  passes or in fooled runs, can be chance. Thinking off also needs more
  tool-call reminders. Before building a local-only "thinking off
  first" ladder, repeat the local arms (3 repeats, at night) to see if
  the result holds.

## Related

- [Escalation: the first benchmark](escalation-0.1.17.md)
- [Escalation with a handoff](escalation-handoff-0.1.23.md)
