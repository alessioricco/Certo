# Benchmark: the slow-test note, Certo 0.2.5

From 0.2.5, when one of the agent's own test runs takes a tenth of the
time budget or more, Certo tells it once: run only the tests for what
you changed while you work, and the whole suite once at the end. The
idea came from a user's milestone project where a 9-minute browser suite
ran again and again inside a 30-minute budget. This benchmark checks
whether the note saves time, on a local model and on a cloud model.

## The setup

- **Certo:** 0.2.5 from the repository (unreleased), commit `0e69a70`.
- **Machine running Certo:** Darwin 25.6.0, arm64, Apple M1, 8 CPUs,
  16 GB RAM.
- **Task:** `app-tasks/job-runner` (task set apps-3), in milestones:
  three features added to a small Python job runner. Its starter suite
  takes about 2.5 minutes, almost all of it in one file,
  `tests/test_jobs.py`, whose tests wait on a worker thread.
- **Arms:** the same model with the note (the default) and without it
  (`slow_test_note: false`).
- **Local:** `ollama/qwen3.8:27b` on Ollama 0.40.15 on another machine,
  20 minutes per milestone (the suite is 12% of it), 2 runs per arm, one
  at a time, on 2026-11-22 from 00:00 to 03:38 UTC. **File:**
  [bench-0.2.5-slow-tests-local.yaml](bench-0.2.5-slow-tests-local.yaml).
- **Cloud:** `anthropic/claude-haiku-5-5`, 15 minutes per milestone
  (16%), 3 runs per arm, 3 at a time, on 2026-11-22 from 09:49 to
  10:34 UTC. **File:**
  [bench-0.2.5-slow-tests-cloud.yaml](bench-0.2.5-slow-tests-cloud.yaml).
- Both use [models-0.2.4-ratings.yaml](models-0.2.4-ratings.yaml) and
  [models_list-0.2.4-computed.yaml](models_list-0.2.4-computed.yaml).
- **Results folders:** `bench-results/20261122-slow-tests-local` and
  `bench-results/20261122-slow-tests-cloud`, on the machine that ran
  them.

## Results

| Arm | Hidden tests passed | Verified | Median time | Tokens in / out | Tool-call reminders | Cost |
|---|---|---|---|---|---|---|
| qwen3.8, note | 2/2 | 2/2 | 46m 35s | 2,438,080 / 72,184 | 0 | $0 |
| qwen3.8, no note | 2/2 | 2/2 | 47m 25s | 2,953,635 / 84,211 | 15 | $0 |
| Haiku, note | 3/3 | 3/3 | 22m 09s | 3,293,325 / 90,506 | 0 | $0.1091 |
| Haiku, no note | 3/3 | 3/3 | 19m 47s | 2,632,343 / 85,145 | 0 | $0.0984 |

Every milestone of every run ended `verified`; none ran out of time.

The agent's own test runs, counted from the transcripts. "Full" is
the whole suite, "narrowed" one file or one test; a run is counted when
pytest printed its summary. "Waits" are the times the agent was told the
command was still running and waited for it.

| Run | Notes | Full runs (time) | Narrowed runs (time) | Waits |
|---|---|---|---|---|
| qwen3.8, note, 1 | 3 | 2 (4.9 min) | 6 (4.9 min) | 0 |
| qwen3.8, note, 2 | 3 | 3 (7.5 min) | 2 (2.5 min) | 3 |
| qwen3.8, no note, 1 | – | 2 (5.0 min) | 0 | 1 |
| qwen3.8, no note, 2 | – | 3 (7.3 min) | 2 (under a minute) | 4 |
| Haiku, note, 1 | 1 | 1 (2.4 min) | 5 (under a minute) | 0 |
| Haiku, note, 2 | 2 | 4 (9.7 min) | 2 (under a minute) | 3 |
| Haiku, note, 3 | 1 | 2 (4.8 min) | 3 (under a minute) | 1 |
| Haiku, no note, 1 | – | 1 (2.4 min) | 6 (2.4 min) | 0 |
| Haiku, no note, 2 | – | 1 (2.4 min) | 5 (under a minute) | 0 |
| Haiku, no note, 3 | – | 2 (4.8 min) | 1 (under a minute) | 0 |

## What it shows

- **No time saved on this task.** qwen3.8 took the same time with and
  without the note (46m 35s against 47m 25s). Haiku was slower with it
  (22m 09s against 19m 47s), mostly from one run that ran the full suite
  four times. With 2 and 3 runs per arm, neither difference is more than
  chance.
- **Haiku already narrows its runs.** Without the note it ran the full
  suite once or twice per job and single tests otherwise, so the note
  had little to change. It fired only 1 or 2 times per Haiku job.
- **qwen3.8 followed the note, but narrowing by file didn't help.**
  With the note it ran more narrowed runs (8 against 2), but the slow
  tests are all in one file, so a run of that file took as long as the
  whole suite.
- **The budget was never short.** Each milestone finished inside its
  time, in both arms, so this task doesn't put the note where it
  matters most: a suite that eats the budget.
- **Fewer reminders with the note on qwen3.8** (0 against 15), and
  fewer tokens (17% less). The 15 come from one run, so this can be
  chance too.

## What it doesn't show

Whether the note helps when the suite really eats the budget, as in the
project that suggested it (a 9-minute suite in 30 minutes). That needs a
task with a slower suite, or a shorter budget per milestone.
