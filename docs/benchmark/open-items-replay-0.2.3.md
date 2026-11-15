# Replay: an open to-do item no longer ends the run, Certo 0.2.3

Until 0.2.2, a run whose agent left an item of its own to-do list open
after Certo's follow-ups ended `incomplete`, and the project's checks
never ran; the follow-up also moved to the next model. From 0.2.3 the
follow-up stays on the same model and the checks decide; a `verified`
run with items still open says so and counts as maybe unfinished
([Verdicts](../reference/verdicts.md)). That changes a Certo decision,
so before the release it is checked against the runs Certo recorded:
no run that ended `incomplete` for a real reason may now be `verified`.

## What was replayed

Every run recorded with the verdict `incomplete`: in every benchmark
results table kept on the machine that runs the benchmarks (Certo 0.1.13
to 0.2.3), and in the run reports of the 8 projects in the Author's
Certo workspace. For each, the project's checks were run
again on the files the run left (`certo verify`, Certo 0.2.3 at commit
`9f6225e`, on 2026-11-15), which is what the new rule decides on.

## Results

| Run | Model | Hidden tests | Checks now | New verdict |
|---|---|---|---|---|
| `semver-order`, round 1 (2026-10-18, Certo 0.1.15) | `devstral` (local) | failed | `npm test` skipped, nothing to run | `inconclusive` |
| `temperature-table`, round 3 (2026-10-18, Certo 0.1.15) | `qwen3.6` (local) | failed | the folder is empty | `inconclusive` |
| alien-trekking, milestone 6 (2026-11-15, Certo 0.2.3, ended `cost_exhausted` after the climb) | Haiku, then the ladder | none | not replayed: the climb changed the files; when Haiku left the item open, every check had passed | under the new rule Haiku's work is checked, with no climb |

- **No wrong `verified`.** Both benchmark runs that failed their hidden
  tests stay away from `verified`: their checks can't show the task
  done.
- **The run that led to the change** passed every check while one item
  stayed open; under the old rule it climbed three models to its $2 cost
  limit (`cost_exhausted`). A resume of it then finished the milestone,
  `verified`, and the six other milestones were `verified` too.
- **Few runs to go on.** Two recorded runs ended `incomplete`, and one more
  climbed because of an open item. A live run with `--escalate` on a milestone task, where
  an item stays open, hasn't happened yet; the release notes don't claim
  more than this replay.
