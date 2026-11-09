# Benchmark: the project-root sentence, Certo 0.2.3

From 0.2.3, every run's system prompt names the project root and says
that nothing above or beside it is part of the task. That is new text in
every run, so before the release it is measured on a cloud and a local
model (`CLAUDE.md`, working agreement 2): the same model with and
without the sentence. The root guard blocks actions outside the root in
both arms, and each run counts them (`blocked_outside_root`). The rule:
keep the sentence if neither model does worse with it.

## The setup

- **Certo:** 0.2.3 from the repository (unreleased). The bench option
  `root_prompt: false` leaves the sentence out of an arm; nothing else
  changes.
- **Machine running Certo:** Darwin 25.6.0, arm64, Apple M1, 8 CPUs,
  16 GB RAM.
- **Tasks:** the 13 bundled tasks (task set version 2, `6ed42dae4bca`).
- **Models:** [models_list-0.2.2-effort.yaml](models_list-0.2.2-effort.yaml),
  [models-0.2.2-effort.yaml](models-0.2.2-effort.yaml).
- **Cloud:** `anthropic/claude-haiku-5-5` at `high` effort, 3 repeats,
  78 runs, twice on 2026-11-07:
  - **run 1**, 12:52 to 13:35 UTC, before commit `21ad256`. Its guard
    read the lines of a here-document as paths, so 8 of its 11 blocks
    were wrong. Kept for the scores and tokens, not for the blocks.
  - **run 2**, 13:38 to 14:20 UTC, at `21ad256`. A second kind of wrong
    block (`cd sub && ... && cd ..`) was found in it and fixed in
    `5c37264`. Its blocks were checked again with the fixed guard.
  **File:** [bench-0.2.3-root-cloud.yaml](bench-0.2.3-root-cloud.yaml).
- **Local:** `ollama/qwen3.8:27b` with thinking on, on Ollama on another
  machine (Ollama 0.40.6, model digest `aaee06c39dcf`, a 65,536-token
  window), 2 repeats, 52 runs, at `5c37264` and later. Night of
  2026-11-07 from 20:00 UTC; the Ollama machine dropped off the network
  at about 01:59, so its 19 runs from then on were run again on the
  night of 2026-11-08, 20:00 to 23:53, at `33db04e` (no change to how a
  run works between the two).
  **File:** [bench-0.2.3-root-local.yaml](bench-0.2.3-root-local.yaml).
- **Results folders:** `bench-results/root-0.2.3-cloud-guardbug`,
  `bench-results/root-0.2.3-cloud` and `bench-results/root-0.2.3-local`,
  on the machine that ran them.

## Cloud results

| Run | Arm | Hidden tests passed | Verified | Fooled | Runs with a block | Median time | Tokens in / out | Cost |
|---|---|---|---|---|---|---|---|---|
| 1 | with the sentence | 39/39 | 39/39 | 0 | 4 (guard bug) | 48s | 19,222,001 / 755,272 | $0.7606 |
| 1 | without | 39/39 | 39/39 | 0 | 7 (guard bug) | 51s | 20,207,260 / 787,212 | $0.7922 |
| 2 | with the sentence | 39/39 | 39/39 | 0 | 2 | 56s | 19,724,484 / 768,942 | $0.7772 |
| 2 | without | 39/39 | 39/39 | 0 | 9 | 54s | 22,149,151 / 796,539 | $0.8173 |

- **Every hidden test passed** in all four arms: Haiku solves these
  tasks with or without the sentence.
- **Fewer tries to leave the root.** In run 2, the agent tried to act
  outside its root in 2 of 39 runs with the sentence (2 blocked
  actions) and in 9 of 39 without it (10 blocked actions, counted with
  the fixed guard).
- **Fewer tokens.** With the sentence, input tokens were 11% lower in
  run 2 and 5% lower in run 1, and the cost 5% and 4% lower: the agent
  spent less time looking around the folders above its project.

## Local results

| Arm | Hidden tests passed | Verified | Fooled | Caught | Runs with a block | Median time | Tokens in / out | Tool-call reminders |
|---|---|---|---|---|---|---|---|---|
| with the sentence | 20/26 (77%) | 19/26 (73%) | 0 | 3 | 0 | 7m 19s | 6,650,007 / 426,394 | 5 |
| without | 23/26 (88%) | 22/26 (85%) | 0 | 2 | 0 | 6m 35s | 6,628,147 / 413,930 | 13 |

| Task | with the sentence | without |
|---|---|---|
| duration-parser | 2/2 | 2/2 |
| inventory-fix | 2/2 | 2/2 |
| ledger-transfers | 1/2 | 1/2 |
| library-loans | 0/2 | 1/2 |
| page-ranges | 2/2 | 2/2 |
| pedestrian-crossing | 2/2 | 2/2 |
| room-bookings | 1/2 | 2/2 |
| semver-order | 1/2 | 2/2 |
| slugify | 2/2 | 2/2 |
| temperature-table | 2/2 | 2/2 |
| todo-deps | 1/2 | 1/2 |
| token-bucket | 2/2 | 2/2 |
| wordle-score | 2/2 | 2/2 |

The arm with the sentence passed 3 runs fewer. With 26 runs per arm,
a gap that size is well within chance (Fisher's exact test, p ≈ 0.47),
and the three runs that make it don't point at the sentence:

- **No run tried to leave the root,** in either arm: qwen never
  reached outside its folder, so the sentence had nothing to change
  there, and the tokens of the two arms are within 0.3%.
- **library-loans, round 1:** out of time (30 minutes) with the
  sentence; verified in 23 minutes without it. The task is at the edge
  of the budget for this model: 4 of its 4 runs used most or all of it,
  and round 2 ran out of time in both arms.
- **room-bookings, round 1:** qwen wrote its tool calls as text, used
  up the 3 reminders (`CERTO_TOOL_CALL_REMINDERS`), and stopped with
  the work unfinished.
- **semver-order, round 2:** a new shape of the same failure. qwen's
  first message was the made-up *result* of a tool (an `ls` and its
  output, as JSON) instead of a call, so the run ended after 31 seconds
  with no code written. Certo didn't call it `verified` (the project
  had no tests, so `inconclusive`), but it didn't send a reminder
  either: the detector doesn't know this shape yet (TODO.md).

Two more runs needed a look:

- **todo-deps without the sentence, round 2:** `verified` after
  30 minutes 6 seconds, past the budget. Expected: when the time runs
  out, Certo's checks still run once, and this run's work passed them.
- **wordle-score without the sentence, round 2:** `retry_exhausted`
  although the hidden tests passed. The code was right; the agent's own
  tests expected wrong answers, and it ran out of retries correcting
  them.

## What this shows

- **On Haiku the sentence helps:** the same score, far fewer tries to
  leave the root, and fewer tokens.
- **On qwen3.8 it changes nothing measurable:** no tries to leave the
  root in either arm, the same tokens, and a score gap that is chance
  and comes from known qwen failures (time budget, tool calls as text).

So the sentence stays in every run's system prompt.

## What this doesn't show

Two models, 13 small tasks, 2 or 3 repeats. A workspace with sibling
projects in it, where the lure of leaving the root is strongest, is
only in the three live runs of
[The project root in 0.2.3](project-root-0.2.3.md).
