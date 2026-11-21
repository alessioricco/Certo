# Benchmark: the derived ladder with Haiku writing the independent tests, Certo 0.2.5

[The ladder benchmark in 0.2.4](ladder-computed-0.2.4.md) ran the ladder
Certo derives from the computed ratings (`qwen3.8` → Terra → Sonnet) and
was fooled once: on `semver-order`, qwen3.8's code passed Certo's checks
but failed a hidden test. A replay showed that independent tests written
by `claude-haiku-5-5` would have caught it. This run repeats the ladder
with [independent tests](../guides/independent-tests.md) on, written by
Haiku (`CERTO_INDEPENDENT_TESTS_MODEL`, new in 0.2.5) while the ladder
builds. They report only, so the verdicts compare with the 0.2.4 run.

## The setup

- **Certo:** 0.2.5 from the repository (unreleased), commit `d1ffdcf`.
- **Machine running Certo:** Darwin 25.6.0, arm64, Apple M1, 8 CPUs,
  16 GB RAM.
- **Tasks:** the 13 bundled tasks (task set version 2), 1 run each.
- **Models and ratings:** as in [ladder-computed-0.2.4.md](ladder-computed-0.2.4.md):
  [models-0.2.4-ratings.yaml](models-0.2.4-ratings.yaml),
  [models_list-0.2.4-computed.yaml](models_list-0.2.4-computed.yaml).
  `ollama/qwen3.8:27b` ran on Ollama 0.40.15 on another machine, with a
  131,072-token window and model digest `aaee06c39dcf`.
- **The derived ladder:** `qwen3.8-27b-local` → `gpt-6.1-terra` →
  `claude-sonnet-5-5`, 60 minutes per task (qwen3.8 has 30 of them,
  Terra half of what is left, Sonnet the rest).
- **Independent tests:** three sets per task, written by
  `claude-haiku-5-5` from the task before the build, run on the work
  after the verdict; a task fails them when 2 of the 3 sets fail.
- **Files:** [bench-0.2.5-ladder-independent.yaml](bench-0.2.5-ladder-independent.yaml)
  (all 13 tasks) and
  [bench-0.2.5-ladder-independent-rerun.yaml](bench-0.2.5-ladder-independent-rerun.yaml)
  (the last 9).
- **When:** two nights, with 15-minute pauses between tasks. On
  2026-11-19 from 21:19 UTC, the first 4 tasks ran as planned. The
  machine running Ollama shut down during the fourth, so the ladder
  found qwen3.8 unreachable for the other 9 and started them on Terra.
  Those 9 ran again on 2026-11-20 from 19:56 to 23:57 UTC, with qwen3.8
  reachable all night. The tables below use the first 4 runs of the
  first night and the 9 runs of the second.
- **Results folders:** `bench-results/20261119-211947` and
  `bench-results/20261120-rerun9`, on the machine that ran them.

## Results

| Run | Hidden tests passed | Verified | Fooled | Independent tests failed | Final rung | Median time | All runs | Tokens in / out | Cost | Cost per solved task |
|---|---|---|---|---|---|---|---|---|---|---|
| Ladder + Haiku's tests (this run) | 13/13 (100%) | 13/13 | 0 | 0/13 | qwen3.8 11×, Terra 2× | 8m 27s | 3h 20m | 7,589,468 / 727,133 | $0.6680 | $0.0514 |
| Ladder alone, 0.2.4 ([ladder-computed-0.2.4.md](ladder-computed-0.2.4.md)) | 12/13 (92%) | 13/13 | 1 | – | qwen3.8 10×, Terra 3× | 6m 26s | 3h 03m | 6,001,546 / 276,943 | $0.5104 | $0.0425 |

Of this run's $0.6680, writing the tests cost $0.3432 (Haiku, about
$0.026 per task) and Terra's two climbs $0.3248. qwen3.8 costs nothing.

Per task:

| Task | Rungs | Time | Cost | Independent sets passed | Hidden tests |
|---|---|---|---|---|---|
| duration-parser | qwen3.8 `verified` | 8m 27s | $0.0113 | 3 of 3 | passed |
| inventory-fix | qwen3.8 `verified` | 5m 07s | $0.0132 | 3 of 3 | passed |
| ledger-transfers | qwen3.8 `verified` | 26m 50s | $0.0452 | 3 of 3 | passed |
| library-loans (Go) | qwen3.8 `budget_exhausted` (30m) → Terra `verified` (6m 22s) | 38m 57s | $0.2423 | 3 of 3 | passed |
| page-ranges | qwen3.8 `verified` | 3m 23s | $0.0114 | 3 of 3 | passed |
| pedestrian-crossing | qwen3.8 `verified` | 29m 18s | $0.0186 | 3 of 3 | passed |
| room-bookings | qwen3.8 `verified` | 24m 56s | $0.0473 | 2 of 3 | passed |
| semver-order (Node) | qwen3.8 `verified` | 6m 36s | $0.0215 | 2 of 3 | passed |
| slugify | qwen3.8 `verified` | 5m 36s | $0.0163 | 3 of 3 | passed |
| temperature-table | qwen3.8 `verified` | 3m 23s | $0.0143 | 3 of 3 | passed |
| todo-deps (Rust) | qwen3.8 `stuck` (30m) → Terra `verified` (3m 50s) | 35m 19s | $0.1923 | 3 of 3 | passed |
| token-bucket | qwen3.8 `verified` | 3m 09s | $0.0189 | 3 of 3 | passed |
| wordle-score | qwen3.8 `verified` | 9m 30s | $0.0153 | 3 of 3 | passed |

Sonnet, the last rung, was never needed.

## What it shows

- **No fooled run this time, so the catch wasn't tested live.**
  qwen3.8's `semver-order` passed the hidden tests on this run, so there
  was nothing for Haiku's tests to catch. That they would have caught the
  0.2.4 run is still shown only by
  [the replay](ladder-computed-0.2.4.md#would-independent-tests-have-caught-it).
- **No false alarms.** Every run was right by the hidden tests, and no
  task failed the independent tests. Two tasks had one set of three fail,
  and the 2-of-3 vote kept it from counting. On `semver-order`, the
  failing test compares versions with very large numbers, which the task
  doesn't ask for. On `room-bookings`, two tests about boundary times and
  overlaps failed in one set; the hidden tests passed.
- **Writing the tests is cheap next to a climb.** Haiku's three sets
  cost about $0.026 per task, $0.34 for all 13. One climb to Terra costs
  $0.15 to $0.24.
- **qwen3.8 solved 11 of 13 by itself**, one more than in 0.2.4.
  `ledger-transfers` (`stuck` there, while the Ollama machine was
  failing) passed on qwen3.8 this time. Go (`library-loans`) and Rust
  (`todo-deps`) climbed in both runs.
- **Reasoning effort follows the model.** qwen3.8's runs ran at the
  default effort and Terra's at `high`, as their entries in the model
  list file say.
- **Small sample:** one run per task. One fooled run in 0.2.4 and none
  here can be chance.

## What it doesn't show

- Whether Haiku's tests catch a fooled run in a live benchmark. That
  needs a run that fools Certo's checks; more repeats of `semver-order`
  on qwen3.8 would be the cheapest way to get one.
- `library-loans`: the Ollama machine shut down during this task's
  qwen3.8 rung, so how qwen3.8 does on it says little.
