# Benchmark: `semver-order` on qwen3.8, 8 times, with Haiku's independent tests, Certo 0.2.5

In [the 0.2.4 ladder run](ladder-computed-0.2.4.md), qwen3.8 was fooled
on `semver-order`: its code passed Certo's checks but failed a hidden
test. A replay showed that [independent tests](../guides/independent-tests.md)
written by `claude-haiku-5-5` would have caught it, but no live run has
caught one yet ([the 0.2.5 ladder run](ladder-independent-0.2.5.md) was
not fooled). This run repeats the task 8 times on qwen3.8 alone, with
Haiku writing the tests, hoping for a fooled run that they catch.

## The setup

- **Certo:** 0.2.5 (released), commit `4a14279`.
- **Machine running Certo:** Darwin 25.6.0, arm64, Apple M1, 8 CPUs,
  16 GB RAM.
- **Task:** `semver-order` (task set version 2), 8 repeats.
- **Model:** `qwen3.8-27b-local` (`ollama/qwen3.8:27b`) on Ollama 0.40.15
  on another machine, with a 131,072-token window and model digest
  `aaee06c39dcf`. 60 minutes per run, one model (no ladder).
- **Models and ratings:** [models-0.2.4-ratings.yaml](models-0.2.4-ratings.yaml),
  [models_list-0.2.4-computed.yaml](models_list-0.2.4-computed.yaml).
- **Independent tests:** three sets per run, written by
  `claude-haiku-5-5`; a run fails them when 2 of the 3 sets fail. Report
  only.
- **File:** [bench-0.2.5-semver-independent-local.yaml](bench-0.2.5-semver-independent-local.yaml).
- **When:** 2026-11-22, from 21:58 to 23:32 UTC, with 5-minute pauses
  between runs.
- **Results folder:** `bench-results/20261122-semver-independent`, on the
  machine that ran it.

## Results

| Runs | Hidden tests passed | Verified | Fooled | Independent tests failed | Median time | All runs | Tokens in / out | Cost |
|---|---|---|---|---|---|---|---|---|
| 8 | 8/8 | 8/8 | 0 | 0/8 | 6m 21s | 59m 06s | 2,739,363 / 291,717 | $0.1603 |

All the cost is Haiku writing the tests (about $0.020 per run); qwen3.8
costs nothing.

Per run:

| Run | Time | Independent sets passed |
|---|---|---|
| 1 | 7m 25s | 3 of 3 |
| 2 | 5m 22s | 3 of 3 |
| 3 | 5m 28s | 3 of 3 |
| 4 | 9m 46s | 3 of 3 |
| 5 | 5m 46s | 3 of 3 |
| 6 | 5m 43s | 3 of 3 |
| 7 | 6m 56s | 3 of 3 |
| 8 | 12m 41s | 2 of 3 |

In run 8, one set failed its test "numeric prerelease identifiers
compare as numbers". The hidden tests check that case too
(`2.1.0-dev.3` < `2.1.0-dev.20`) and passed. Run 8's code also gives the
same answer as the task's reference solution on 145,161 pairs of
prerelease versions, so the set's test was most likely wrong. The vote
kept it from counting.

## What it shows

- **No fooled run, so still nothing to catch.** The live catch is still
  open. Across the two ladder runs and this one, qwen3.8 has run
  `semver-order` 10 times and was fooled once.
- **No false alarms from the vote.** One wrong set in 24, absorbed by
  the 2-of-3 vote.
- **Waiting for a fooled run by chance is slow.** A task where qwen3.8
  is fooled more often, or a replay on several saved fooled projects as
  in [0.1.24](independent-tests-replay-0.1.24.md), would test the catch
  sooner.
