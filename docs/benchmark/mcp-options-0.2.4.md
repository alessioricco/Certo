# Every run option over MCP: two live runs (0.2.4)

`run_task` over MCP took only some of a run's options until 0.2.4
(commit 72ebcd9). These two runs check the new path end to end with a
real model: a task read from `task_file`, planned with
`make_milestones`, limited with `max_minutes`, and judged with
`require_verification`, followed with `run_events` and `run_status`.

- **Date:** 2026-11-18, from a checkout of 0.2.4 (72ebcd9).
- **Model:** `anthropic/claude-haiku-5-5`, for the plan and the work.
- **How:** [`mcp-options-live.py`](mcp-options-live.py) starts the MCP
  server in process and calls it with the `mcp` package's client, as an
  editor would.
- **Tasks:** [`mcp-temperature-tools.task.md`](mcp-temperature-tools.task.md)
  (small) and [`mcp-library-loans.task.md`](mcp-library-loans.task.md)
  (five parts).

## Results

| Task | Plan | Verdict | `passed` | Time | Cost |
|---|---|---|---|---|---|
| Temperature tools | kept as one task: "small enough to build in one go" | `verified` | `true` | 34s | $0.0071 |
| Library loans | 5 milestones, in 7s, $0.0008 | `verified` (5 of 5) | `true` | 5m 48s | $0.0745 |

Time and cost are the run's, from its result; the plan's cost is
separate, as on the command line.

The library-loans plan, as `run_events` showed it:

```text
Plan: 5 milestones, written by anthropic/claude-haiku-5-5 in 7s, $0.0008. Saved as .../loans/.certo/milestones.md
  1. Project setup and book catalogue
  2. Member registration
  3. Lending and returning copies
  4. Due dates, overdue list and fines
  5. Saving and loading to JSON
```

Each milestone ended `verified`. Per milestone, from the run's report:

| Milestone | Tokens in / out | Cost |
|---|---|---|
| 1. Project setup and book catalogue | 308,452 / 9,029 | $0.0111 |
| 2. Member registration | 122,984 / 4,253 | $0.0052 |
| 3. Lending and returning copies | 591,359 / 15,616 | $0.0177 |
| 4. Due dates, overdue list and fines | 457,861 / 16,188 | $0.0169 |
| 5. Saving and loading to JSON | 841,563 / 19,660 | $0.0235 |

## What this shows, and what it doesn't

- Over MCP, the plan runs in the run's thread: `run_task` returned at
  once, and the plan came as events, as designed.
- One run each, on one cloud model: it shows the path works, not that
  planning helps. The milestone benchmark
  ([make-milestones-0.2.4.md](make-milestones-0.2.4.md)) found no gain
  over one go on tasks of this size.
- `require_verification` was on, but both runs ended `verified`, so
  `passed: false` for an unproven verdict was checked only in tests.
