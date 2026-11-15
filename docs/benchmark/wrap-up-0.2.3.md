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
- **Local:** `ollama/qwen3.8:27b`, a 10-minute budget per milestone,
  **not run yet**. **File:**
  [bench-0.2.3-wrapup-local.yaml](bench-0.2.3-wrapup-local.yaml).
- **Results folder:** `bench-results/wrapup-0.2.3-cloud`, on the machine
  that ran it.

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
