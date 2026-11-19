# Benchmark: the ladder Certo derives from the computed ratings, Certo 0.2.4

[The auto-model benchmark](ratings-0.2.4.md) put 11 of the 13 bundled
tasks on `qwen3.8`, and a run that ran out of time there stayed there.
This run uses the same models and ratings with `--escalate` and no
ladder file, so Certo derives the ladder from the ratings. When the local
model's time share runs out, or its work doesn't pass the checks, the task
goes up to the next model.

## The setup

- **Certo:** 0.2.4 from the repository (unreleased), commit `149af84`.
- **Machine running Certo:** Darwin 25.6.0, arm64, Apple M1, 8 CPUs,
  16 GB RAM.
- **Tasks:** the 13 bundled tasks (task set version 2), 1 run each.
- **Models and ratings:** as in the computed arm of
  [ratings-0.2.4.md](ratings-0.2.4.md):
  [models-0.2.4-ratings.yaml](models-0.2.4-ratings.yaml),
  [models_list-0.2.4-computed.yaml](models_list-0.2.4-computed.yaml).
  `ollama/qwen3.8:27b` ran on Ollama 0.40.15 on another machine, with a
  131,072-token window and model digest `aaee06c39dcf`.
- **The derived ladder:** `qwen3.8-27b-local` → `gpt-6.1-terra` →
  `claude-sonnet-5-5`.
- **Time:** 60 minutes per task. Each rung but the last gets half of the
  time left, so qwen3.8 has 30 minutes and Terra 15, and Sonnet gets the
  rest.
- **File:** [bench-0.2.4-ladder-computed.yaml](bench-0.2.4-ladder-computed.yaml).
- **When:** 2026-11-18. The first 3 tasks ran from 15:37 UTC. The
  machine running Ollama shut down from heat during the third task, so
  the benchmark was stopped. The other 10 tasks ran with `--resume`
  from 19:00 to 23:32 UTC, with 15-minute pauses between tasks.
- **Results folder:** `bench-results/20261118-153753`, on the machine
  that ran it.

## Results

| Arm | Hidden tests passed | Verified | Fooled | Final rung | Median time | All runs | Tokens in / out | Cost | Cost per solved task |
|---|---|---|---|---|---|---|---|---|---|
| Ladder | 12/13 (92%) | 13/13 | 1 | qwen3.8 10×, Terra 3× | 6m 26s | 3h 03m | 6,001,546 / 276,943 | $0.5104 | $0.0425 |
| Auto-model, for comparison ([ratings-0.2.4.md](ratings-0.2.4.md)) | 12/13 (92%) | 11/13 | 0 | qwen3.8 11×, Terra 2× | 5m 43s | 2h 19m | 3,863,839 / 235,630 | $0.2078 | $0.0173 |

Per task:

| Task | Rungs | Time | Cost | Hidden tests |
|---|---|---|---|---|
| duration-parser | qwen3.8 `verified` | 6m 06s | $0 | passed |
| inventory-fix | qwen3.8 `verified` | 3m 39s | $0 | passed |
| ledger-transfers | qwen3.8 `stuck` (30m) → Terra `verified` (6m 27s) | 36m 31s | $0.1593 | passed |
| library-loans (Go) | qwen3.8 `budget_exhausted` (30m) → Terra `verified` (5m 13s) | 35m 16s | $0.1972 | passed |
| page-ranges | qwen3.8 `verified` | 6m 26s | $0 | passed |
| pedestrian-crossing | qwen3.8 `verified` | 6m 44s | $0 | passed |
| room-bookings | qwen3.8 `verified` | 23m 55s | $0 | passed |
| semver-order (Node) | qwen3.8 `verified` | 6m 26s | $0 | **failed**, 5 of 6 |
| slugify | qwen3.8 `verified` | 10m 32s | $0 | passed |
| temperature-table | qwen3.8 `verified` | 2m 40s | $0 | passed |
| todo-deps (Rust) | qwen3.8 `budget_exhausted` (30m) → Terra `verified` (4m 13s) | 34m 19s | $0.1538 | passed |
| token-bucket | qwen3.8 `verified` | 6m 17s | $0 | passed |
| wordle-score | qwen3.8 `verified` | 3m 50s | $0 | passed |

Sonnet, the last rung, was never needed.

## What it shows

- **The ladder hands on the tasks auto-model left on qwen3.8.** Go and
  Rust ran out of time on qwen3.8 in both benchmarks. Here Terra finished
  each of them in 4 to 6 minutes. `todo-deps`, the task auto-model
  didn't solve, passed.
- **The price is time.** Each of the three climbs spent the full
  30 minutes on qwen3.8 before handing on, so a climb takes about
  35 minutes, where a task that starts on Terra takes about 5. The
  three climbs cost $0.51 in all.
- **One fooled run:** on `semver-order`, Certo said `verified` but one
  hidden test failed. qwen3.8's code accepts `1.2.3+`, a version with an
  empty build part, which the task says must throw. The agent's own
  tests didn't try that case, so Certo's checks passed. The same task
  passed on qwen3.8 in the auto-model benchmark. A ladder only climbs
  when Certo's checks fail, so it can't catch this.
- **`ledger-transfers` may be unfair to qwen3.8.** The machine running
  Ollama shut down during that rung, and a request waited 1,125 seconds
  before timing out. The rung ended `stuck` and the task climbed, so
  qwen3.8's result on this task says little.
- **Small sample:** one run per task. The ladder and auto-model both
  solved 12 of 13, and which task failed differs. That can be chance.

## Would independent tests have caught it?

Yes, on this one. On 2026-11-19, `scripts/replay_independent_tests.py`
had `claude-haiku-5-5` write tests from the `semver-order` task three
times, as [`--independent-tests`](../guides/independent-tests.md) does
before a build, and ran them on qwen3.8's saved project. All 3 sets
failed it, each on a test that `1.0.0+` must throw (pass 13, fail 1),
and all 3 passed the task's reference solution. Writing them cost
$0.020. With `--independent-tests-strict`, the run would have ended
`independent_failed` instead of `verified`. One task, one project: the
guide has the larger measurements.

## What it doesn't show

Whether a shorter first share (for example 15 minutes on qwen3.8) would
save time without losing tasks that qwen3.8 finishes late, such as
`room-bookings` at 24 minutes.
