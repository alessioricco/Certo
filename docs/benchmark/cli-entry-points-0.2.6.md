# Benchmark: the `cli-entry-points` skill, local and cloud, Certo 0.2.5

`cli-entry-points` is one of Certo's own skills, new in 0.2.5. It is
used when a task describes a command-line program. It asks for one
entry point that takes its arguments, exit codes that tests can check,
and no prompts that wait for someone to type. This benchmark runs
`todo-deps` with and without the skill, on a local model and a cloud
one. `todo-deps` asks for a to-do list in Rust, with exit code 2 for bad
usage. Then independent tests written by `claude-haiku-5-5` were
replayed on the local runs' saved projects, one of which had fooled
Certo.

## The setup

- **Certo:** 0.2.5 (released), commit `3f834f7`.
- **Machine running Certo:** Darwin 25.6.0, arm64, Apple M1, 8 CPUs,
  16 GB RAM.
- **Task:** `todo-deps` (task set version 2). The two arms differ only
  in `skills_off: [cli-entry-points]`.
- **Local:** `qwen3.8-27b-local` (`ollama/qwen3.8:27b`) on Ollama 0.40.15
  on another machine, 131,072-token window, model digest
  `aaee06c39dcf`. 60 minutes per run, 2 runs per arm, with 10-minute
  pauses between runs. 2026-11-23 from 23:02 to 02:44 UTC.
  [bench-0.2.6-cli-entry-points-local.yaml](bench-0.2.6-cli-entry-points-local.yaml),
  with [models-0.2.4-ratings.yaml](models-0.2.4-ratings.yaml) and
  [models_list-0.2.4-computed.yaml](models_list-0.2.4-computed.yaml).
- **Cloud:** `claude-haiku-5-5` at high effort, 5 runs per arm, 3 at a
  time. 2026-11-24 from 07:22 UTC.
  [bench-0.2.6-cli-entry-points-cloud.yaml](bench-0.2.6-cli-entry-points-cloud.yaml),
  with [models-0.2.2-effort.yaml](models-0.2.2-effort.yaml) and
  [models_list-0.2.2-effort.yaml](models_list-0.2.2-effort.yaml).
- **Replay:** `scripts/replay_independent_tests.py --model claude-haiku-5-5
  --tasks todo-deps` on the 4 local projects (build folders left out),
  3 test sets.
- **Results folders:** `bench-results/20261123-cli-entry-points-local`,
  `bench-results/20261124-cli-entry-points-cloud` and
  `bench-results/20261124-todo-deps-replay`, on the machine that ran
  them.

## Results

| Arm | Hidden tests passed | Verified | Fooled | Median time | Tokens in / out | Cost |
|---|---|---|---|---|---|---|
| qwen3.8, skill | 2/2 | 1/2 | 0 | 53m 07s | 2,056,164 / 132,932 | $0 |
| qwen3.8, no skill | 1/2 | 2/2 | 1 | 42m 42s | 1,006,448 / 118,856 | $0 |
| Haiku, skill | 5/5 | 5/5 | 0 | 4m 06s | 6,386,140 / 290,842 | $0.2585 |
| Haiku, no skill | 5/5 | 5/5 | 0 | 3m 51s | 6,538,719 / 269,961 | $0.2463 |

The qwen3.8 runs, one by one:

| Arm | Run | Verdict | Hidden tests | Time |
|---|---|---|---|---|
| skill | 1 | `verified` | passed | 46m 04s |
| skill | 2 | `budget_exhausted` | passed | 60m 11s |
| no skill | 1 | `verified` | failed (fooled) | 59m 36s |
| no skill | 2 | `verified` | passed | 25m 48s |

The fooled run failed one hidden test, `hidden_ids_are_never_reused`: a
new task took the number of a removed one. That is the program's own
logic, not something the skill covers.

## The replay: a fooled run caught, and a gap in the hidden tests

Haiku wrote 3 test sets ($0.044) and they ran on the 4 saved projects,
the task's reference solution and its starter.

- **The fooled project failed all 3 sets.** Two sets failed it for
  reusing a number, as the hidden tests did. So the 2-of-3 vote would
  have caught it. This is the second fooled run caught in a replay,
  after `semver-order` in 0.2.4. It is not yet a live catch.
- **Two of the three projects that passed the hidden tests failed 2 of
  3 sets too.** Every set passed the reference solution. Each failing
  test ran the program with bad usage, and one case failed:
  `todo list --bogus`. Three of the four qwen3.8 programs (both with
  the skill and the fooled one) ignore the unknown option, print the
  list and exit 0. The task says an unknown option exits with code 2.
  So those programs are wrong on that point. The independent tests
  caught it, but the hidden tests have no unknown-option case. All 10
  Haiku programs exit 2 on it.

## What it shows

- **No measurable effect of the skill on `todo-deps`.** Haiku passes
  either way, at about the same time and cost. On qwen3.8, 4 runs are
  too few to read, and the one difference, a fooled run without the
  skill, comes from a bug the skill doesn't cover. The skill also
  didn't stop qwen3.8 from ignoring an unknown option. It says nothing
  about unknown options.
- **The skill stays on by default.** It cost nothing measurable on
  either model.
- **The `todo-deps` hidden tests miss unknown options.** Adding the case
  changes the task set's hash, so it waits for the next task-set change.
