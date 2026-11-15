# Benchmark: the acceptance brief and the wrap-up message, Certo 0.2.3

From 0.2.3 the agent is told each milestone's acceptance checks with the
task (the acceptance brief), and gets one message a margin before its
time budget ends, naming the checks that don't hold yet (the wrap-up
message; [Acceptance checks](../guides/acceptance-checks.md)). Both
change what the agent reads, so they are checked before the release
(`CLAUDE.md`, working agreement 2): with them, the same model does no
worse than without.

## The setup

- **Certo:** 0.2.3 from the repository (unreleased).
- **Machine running Certo:** Darwin 25.6.0, arm64, Apple M1, 8 CPUs,
  16 GB RAM.
- **Tasks:** `expenses` (4 milestones) and `spreadsheet` (5 milestones),
  Python tasks with acceptance checks, from `app-tasks/`; each runs
  milestone by milestone (`milestones: true`).
- **Arms:** the same model twice: with the brief and the wrap-up message
  (as Certo runs by default), and with both off (`wrap_up: false`).
- **Cloud:** `anthropic/claude-haiku-5-5`, high effort, 3 repeats, 12
  runs, 3 at a time, a 5-minute budget per milestone, so the wrap-up
  message is due after 3 minutes and long milestones really reach it. On
  2026-11-15 from 11:37 UTC, commit `0369279`. **File:**
  [bench-0.2.3-wrapup-cloud.yaml](bench-0.2.3-wrapup-cloud.yaml).
- **Local:** `ollama/qwen3.8:27b`, thinking on, on Ollama 0.40.15 on
  another machine, a 65,536-token window, model digest `aaee06c39dcf`;
  `expenses` only, a 10-minute budget per milestone (the message is due
  after 8 minutes), 3 repeats, 6 runs, one at a time with 3-minute
  pauses, on 2026-11-15 from 21:06 UTC, commit `bd62af9`. **File:**
  [bench-0.2.3-wrapup-local.yaml](bench-0.2.3-wrapup-local.yaml).
- **Results folders:** `bench-results/wrapup-0.2.3-cloud` and
  `bench-results/wrapup-0.2.3-local`, on the machine that ran them.

## Results (cloud)

| Arm | Hidden tests passed | Verified | Fooled | Caught | Median time | Tokens in / out | Cost |
|---|---|---|---|---|---|---|---|
| Haiku, brief and wrap-up | 5/6 (83%) | 6/6 (100%) | 1 | 0 | 8m 21s | 13,246,274 / 626,091 | $0.6389 |
| Haiku, neither | 5/6 (83%) | 5/6 (83%) | 0 | 0 | 9m 15s | 17,083,614 / 700,533 | $0.8659 |

Hidden tests passed per milestone, the arm's runs added up:

| Task | Arm | M1 | M2 | M3 | M4 | M5 |
|---|---|---|---|---|---|---|
| expenses | brief and wrap-up | 105/105 | 69/69 | 18/18 | 48/48 | |
| expenses | neither | 105/105 | 69/69 | 18/18 | 48/48 | |
| spreadsheet | brief and wrap-up | 111/111 | 17/18 | 78/78 | 87/87 | 39/39 |
| spreadsheet | neither | 111/111 | 18/18 | 78/78 | 87/87 | 27/39 |

- **The message reached the agent** 4 times, in the 3 `spreadsheet` runs
  of the first arm; `expenses` milestones end before the margin. The
  brief was in every milestone of that arm.
- **No milestone ran out of time with them.** Without them, one
  `spreadsheet` run used up its budget on milestone 4 and never reached
  milestone 5 (`budget_exhausted`).
- **The fooled run** (`spreadsheet`, round 3, with them) passed 110 of
  111 hidden tests: a chain of 200 cells referring to each other hits
  Python's recursion limit (`test_m2_a_long_chain`), and neither the
  task's checks nor the agent's tests try a chain that long. Nothing
  shows the brief or the message caused it.
- **Cheaper:** about a quarter fewer tokens in and $0.64 against $0.87.
  With 6 runs an arm, these differences can be chance.
- **One run ran twice.** In round 1 another run's agent, cleaning up a
  demo file, ran `rm -rf "$(python -c '...print(tempfile.gettempdir())')"`
  and deleted the whole temporary folder, with the project of the
  `spreadsheet` run going on beside it; the benchmark stopped. Both were
  fixed (`6ab5604`: the root guard blocks such deletes; `c3f9eb6`: the
  benchmark records such a run and goes on), and that run was run again
  at commit `c3f9eb6` (verified, every hidden test passed, $0.15).

## Results (local)

| Arm | Hidden tests passed | Verified | Fooled | Caught | Median time | Tokens in / out | Cost |
|---|---|---|---|---|---|---|---|
| qwen3.8, brief and wrap-up | 3/3 (100%) | 2/3 (67%) | 0 | 0 | 23m 27s | 2,744,184 / 108,586 | $0 |
| qwen3.8, neither | 1/3 (33%) | 2/3 (67%) | 1 | 0 | 23m 15s | 2,449,636 / 90,249 | $0 |

Hidden tests passed per milestone of `expenses`, the arm's runs added up:

| Arm | M1 | M2 | M3 | M4 |
|---|---|---|---|---|
| brief and wrap-up | 105/105 | 69/69 | 18/18 | 48/48 |
| neither | 70/70 | 46/46 | 12/12 | 33/48 |

- **No worse; better on this sample.** With the brief and the message
  every run's work passed the hidden tests; without them one did. With
  3 runs an arm, this can be chance.
- **The message reached the agent** 3 times: once in round 2 and twice
  in round 3 of the first arm. Round 3 then ran out of time on
  milestone 4 (`budget_exhausted`; Certo had sent the agent back 11
  times for a tool call written as text or a turn that ended on plans),
  but its work passed every hidden test.
- **Without them**, round 1 ran out of time on milestone 1 and never
  reached the others.
- **The fooled run** (`expenses`, round 3, neither) passed 79 of 80
  hidden tests. The task says a `FILE` with no command is an error with
  exit code 1; the program printed its usage and exited with 2, the code
  for no arguments at all. The agent tried that very case, accepted the
  2, and its own tests don't cover it; neither do the task's acceptance
  checks. It ran without the brief and the message, so they didn't
  cause it.
