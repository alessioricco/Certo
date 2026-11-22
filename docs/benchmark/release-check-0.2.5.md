# Benchmark: the 0.2.5 release check

0.2.5 changes what the agent reads and does by default: the
[slow-test note](slow-tests-0.2.5.md), the `.certo/scratch/` folder,
the official `cli-entry-points` skill, a version-range rule for
dependencies added from the terminal, and plans the agent writes run in
milestones. Before the release, the rule is that a run does no worse
than before, on a cloud model and on a local one (`CLAUDE.md`, working
agreement 2). This page is that check.

## The setup

- **Certo:** 0.2.5 from the repository (unreleased), commit `5088499`.
- **Machine running Certo:** Darwin 25.6.0, arm64, Apple M1, 8 CPUs,
  16 GB RAM.
- **Tasks:** the 13 bundled tasks (task set version 2).
- **Cloud:** `anthropic/claude-haiku-5-5`, high effort, 3 runs per
  task, 39 runs, 3 at a time, on 2026-11-22 from 10:34 to 10:55 UTC.
  The same models and tasks as the `haiku-high` arm of
  [the 0.2.2 effort benchmark](effort-0.2.2.md), so the two compare
  directly. **File:**
  [bench-0.2.5-release-cloud.yaml](bench-0.2.5-release-cloud.yaml), with
  [models-0.2.2-effort.yaml](models-0.2.2-effort.yaml) and
  [models_list-0.2.2-effort.yaml](models_list-0.2.2-effort.yaml).
- **Local:** the derived ladder run of
  [ladder-independent-0.2.5.md](ladder-independent-0.2.5.md) (commit
  `d1ffdcf`, which already has every change above), compared with the
  same ladder in 0.2.4.
- **Results folder:** `bench-results/20261122-release-cloud`, on the
  machine that ran it.

## Results

| Run | Hidden tests passed | Verified | Fooled | Median time | Tokens in / out | Tool-call reminders | Cost |
|---|---|---|---|---|---|---|---|
| Haiku, 0.2.5 | 39/39 (100%) | 39/39 | 0 | 48s | 18,091,208 / 751,221 | 0 | $0.7476 |
| Haiku, 0.2.2 ([effort-0.2.2.md](effort-0.2.2.md)) | 39/39 (100%) | 39/39 | 0 | 52s | 20,435,519 / 787,118 | – | $0.7979 |
| qwen3.8 first in the ladder, 0.2.5 ([ladder-independent-0.2.5.md](ladder-independent-0.2.5.md)) | 13/13 (100%) | 13/13 | 0 | 8m 27s | 7,589,468 / 727,133 | 10 | $0.3248 (Terra) |
| qwen3.8 first in the ladder, 0.2.4 ([ladder-computed-0.2.4.md](ladder-computed-0.2.4.md)) | 12/13 (92%) | 13/13 | 1 | 6m 26s | 6,001,546 / 276,943 | – | $0.5104 |

The 0.2.5 ladder's cost leaves out the $0.3432 Haiku spent writing the
independent tests, which the 0.2.4 run didn't have.

## What it shows

- **No worse on the cloud model.** Haiku passed every run, as in 0.2.2,
  a little faster and cheaper.
- **No worse on the local model.** With qwen3.8 first, every task passed
  and qwen3.8 solved 11 of 13 by itself, against 10 in 0.2.4. Its median
  time is longer (8m 27s against 6m 26s); the ladder page has the
  per-task times.
- **Small samples:** 39 cloud runs and 13 local ones. These numbers can
  show harm that is large, not small differences.

## What it doesn't show

What each change does by itself: the slow-test note has
[its own page](slow-tests-0.2.5.md); the scratch folder and the
`cli-entry-points` skill are not measured one by one yet.
