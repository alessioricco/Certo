# Benchmark: milestones Certo writes, against hand-written ones and one go, Certo 0.2.4

From 0.2.4, `--make-milestones` has a model split a task written in one
piece into milestones before the run
([Let Certo write the milestones](../guides/run-in-milestones.md#let-certo-write-the-milestones)).
This run checks it before it could be more than an experiment
(`CLAUDE.md`, working agreement 2). It uses the app tasks, which are
written in milestones, in three arms:

- **hand:** the task's own milestones (`milestones: true`);
- **planned:** the planner gets the task with its milestones taken out
  (no headings, no acceptance blocks) and Certo runs the milestones it
  writes (`make_milestones: true`). The task's acceptance checks apply
  to the last planned milestone;
- **whole:** the task in one go, without its acceptance blocks, with all
  of their checks.

## The setup

- **Certo:** 0.2.4 from the repository (unreleased), commit `4cc4f5c`.
- **Machine running Certo:** Darwin 25.6.0, arm64, Apple M1, 8 CPUs,
  16 GB RAM.
- **Tasks:** `expenses` (an expense ledger in 4 milestones, 80 hidden
  tests) and `spreadsheet` (a spreadsheet engine in 5 milestones, 111
  hidden tests), task set `apps-2` in `app-tasks/`.
- **Time budget:** 15 minutes per milestone (hand and planned), 60
  minutes for one go.
- **Cloud:** `anthropic/claude-haiku-5-5`, both tasks, 3 repeats per
  arm, 18 runs, three at a time, on 2026-11-17 from 19:59 UTC. Haiku
  also wrote the plans. **File:**
  [bench-0.2.4-make-milestones-cloud.yaml](bench-0.2.4-make-milestones-cloud.yaml).
- **Local:** `ollama/qwen3.8:27b` (on Ollama 0.40.15 on another machine,
  a 131,072-token window, model digest `aaee06c39dcf`), `expenses` only
  (the spreadsheet is too big for it: [milestones-0.1.27.md](milestones-0.1.27.md)),
  3 repeats per arm, 9 runs, one at a time. qwen3.8 also wrote the
  plans. The first run started at 19:59 UTC; the Ollama machine shut
  down at 20:28 (heat), and the other 8 runs went on from 20:49 to
  01:20 with 10-minute pauses (`--resume`). **File:**
  [bench-0.2.4-make-milestones-local.yaml](bench-0.2.4-make-milestones-local.yaml).
- **Models file:** [models-0.2.4-ratings.yaml](models-0.2.4-ratings.yaml),
  with [models_list-0.2.4-hand.yaml](models_list-0.2.4-hand.yaml).
- **Results folders:** `bench-results/make-milestones-0.2.4-cloud` and
  `bench-results/make-milestones-0.2.4-local`, on the machine that ran
  them.

## Results

| Arm | Hidden tests passed | Verified | Fooled | Median time | Tokens in / out | Cost |
|---|---|---|---|---|---|---|
| Haiku, hand | 6/6 | 6/6 | 0 | 8m 47s | 18,823,081 / 716,734 | $1.0057 |
| Haiku, planned | 4/6 | 6/6 | 2 | 8m 10s | 15,685,528 / 623,723 | $0.6529 |
| Haiku, whole | 6/6 | 6/6 | 0 | 3m 49s | 6,787,556 / 308,087 | $0.3039 |
| qwen3.8, hand | 1/3 | 2/3 | 1 | 25m 20s | 2,092,235 / 78,871 | $0 |
| qwen3.8, planned | 3/3 | 2/3 | 0 | 28m 20s | 4,741,677 / 132,044 | $0 |
| qwen3.8, whole | 3/3 | 2/3 | 0 | 22m 14s | 1,569,423 / 104,037 | $0 |

Hidden tests passed per task, Haiku:

| Task | hand | planned | whole |
|---|---|---|---|
| expenses | 3/3 | 3/3 | 3/3 |
| spreadsheet | 3/3 | 1/3 | 3/3 |

Per local run (verdict, hidden tests, time):

| Repeat | qwen3.8, hand | qwen3.8, planned | qwen3.8, whole |
|---|---|---|---|
| 1 | `verified`, 80/80, 29m 02s | `verified`, 80/80, 25m 38s | `verified`, 80/80, 22m 14s |
| 2 | `verified`, 74/80, 25m 20s | `verified`, 80/80, 28m 20s | `verified`, 80/80, 14m 39s |
| 3 | `budget_exhausted` at milestone 3, 60/80, 24m 30s | `budget_exhausted` at milestone 4, 80/80, 37m 34s | `no_progress`, 80/80, 23m 26s |

The plans:

- **Haiku** split `expenses` into 5 or 6 milestones and `spreadsheet`
  into 7 or 8, in 9 to 32 seconds, for $0.001 to $0.004 a plan.
- **qwen3.8** split `expenses` into 4 milestones each time, close to the
  hand-written ones (entries, totals, files, the command line), in 53
  to 64 seconds.

## What it shows

- **On Haiku, one go is best on these tasks:** every run solved, in less
  than half the time, at under a third of the cost of either milestone
  arm. Milestones haven't helped cloud models on tasks of this size
  before either ([expenses-0.1.27.md](expenses-0.1.27.md)).
- **Planned milestones lost two spreadsheet runs on Haiku.** Both were
  `verified` but failed hidden tests. Both failed `test_m2_a_long_chain`:
  a chain of 200 references hit Python's recursion limit, which the
  task doesn't mention. One also failed
  `test_m4_a_cell_that_uses_a_cycle_gets_the_error`: `=1/0+A1`, with
  `A1` in a cycle, gave `#CYCLE!` instead of `#DIV/0!`, against the
  task's "the first error met, left to right, wins". The spreadsheet's
  acceptance checks are thin (the errors milestone checks only that the
  file mentions `#CYCLE!`), so Certo couldn't catch either. The planner
  split references and errors across more, smaller milestones than the
  hand-written plan; on 3 runs that can be chance.
- **On qwen3.8, planned milestones did as well as one go and better
  than the hand-written ones,** 3/3 against 1/3. The hand arm's misses
  were the command line (repeat 2, `verified` but 6 command-line hidden
  tests failed, among them `list` output and `report`) and running out
  of time on saving and loading (repeat 3). The planned milestones were
  nearly the same as the hand-written ones, so this is more likely
  chance than a better plan. On 3 runs per arm, the three arms can't be
  told apart.
- **One go was the fastest on qwen3.8 too** (median 22 minutes), and
  used the fewest tokens.
- **Planning is cheap:** about a minute on qwen3.8, a few seconds and a
  fraction of a cent on Haiku.

## Decision

`--make-milestones` stays opt-in and experimental: it lost two runs on
Haiku against both other arms and gained nothing measurable on
qwen3.8, so it can't be turned on by default (working agreement 2).
Recorded in `DECISIONS.md`.
