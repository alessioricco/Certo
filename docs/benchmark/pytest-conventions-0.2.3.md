# Benchmark: the narrower pytest skill, Certo 0.2.3

Until 0.2.2 the official skill `testing/pytest-conventions` fired on the
word "test", so every task that asked for tests got Python test advice,
also in Go, Rust or Node projects. From 0.2.3 it fires on `pytest`,
`python`, `unittest` or `conftest`, and is left out of a project whose
folder is clearly another language. That changes what the agent reads,
so it is checked before the release (`CLAUDE.md`, working agreement 2):
the narrower skill does no worse than the old one.

Only tasks in other languages can differ. On the 7 Python tasks the
skill still fires, as before, so they are left out.

## The setup

- **Certo:** 0.2.3 from the repository (unreleased).
- **Machine running Certo:** Darwin 25.6.0, arm64, Apple M1, 8 CPUs,
  16 GB RAM.
- **Tasks:** `library-loans` (Go), `room-bookings` (Node and React),
  `semver-order`, `slugify`, `token-bucket` (Node), `todo-deps` (Rust);
  task set version 2, `6ed42dae4bca`.
- **Arms:** the same model twice: "narrow" with Certo's skill as it is
  now, "old" with the skill as it was in 0.2.2, given as a global skill
  that replaces the official one (`skills_dir:`
  [skills-0.2.3-pytest-old](skills-0.2.3-pytest-old)).
- **Cloud:** `anthropic/claude-haiku-5-5`, high effort, 3 repeats, 36
  runs, 3 at a time, on 2026-11-15 from 11:08 UTC, commit `0369279`.
  **File:** [bench-0.2.3-pytest-cloud.yaml](bench-0.2.3-pytest-cloud.yaml).
- **Local:** `ollama/qwen3.8:27b`, thinking on, on Ollama 0.40.15 on
  another machine, a 65,536-token window, model digest `aaee06c39dcf`,
  1 repeat, 12 runs, 3-minute pauses between runs, on the night of
  2026-11-14 (23:31 to 04:24), commit `3c939c1`. **File:**
  [bench-0.2.3-pytest-local.yaml](bench-0.2.3-pytest-local.yaml), with
  [models_list-0.2.2-effort.yaml](models_list-0.2.2-effort.yaml) and
  [models-0.2.2-effort.yaml](models-0.2.2-effort.yaml).
- **Results folders:** `bench-results/pytest-0.2.3-cloud` and
  `bench-results/pytest-0.2.3-local`, on the machine that ran them.

## Results

| Arm | Hidden tests passed | Verified | Fooled | Caught | Median time | Tokens in / out | Cost |
|---|---|---|---|---|---|---|---|
| Haiku, narrow | 18/18 (100%) | 18/18 (100%) | 0 | 0 | 1m 50s | 13,087,089 / 549,517 | $0.5183 |
| Haiku, old | 18/18 (100%) | 18/18 (100%) | 0 | 0 | 2m 05s | 11,735,876 / 545,270 | $0.5028 |
| qwen3.8, narrow | 4/5 (80%) | 3/5 (60%) | 0 | 0 | 29m 06s | 1,472,392 / 143,502 | $0 |
| qwen3.8, old | 4/6 (67%) | 4/6 (67%) | 0 | 0 | 27m 52s | 1,944,272 / 149,733 | $0 |

Hidden tests passed, per task, on qwen3.8 (Haiku passed every task in
every run). The narrow arm counts 5 runs (see below):

| Task | Narrow | Old |
|---|---|---|
| library-loans | 0/1 | 0/1 |
| room-bookings | 1/1 | 0/1 |
| semver-order | 1/1 | 1/1 |
| slugify | 1/1 | 1/1 |
| todo-deps | 0/1 | 1/1 |
| token-bucket | not counted | 1/1 |

- **No worse.** Haiku is the same in both arms, at the same cost. On
  qwen3.8 each arm failed two tasks, by running out of its 30 minutes
  (`budget_exhausted`); with one run per task, which tasks fail is
  chance.
- **One local run doesn't count.** In the narrow `token-bucket` run,
  the starter `package.json` disappeared mid-run, though the agent never
  touched it, and Certo had nothing to check (`inconclusive`; its hidden
  tests passed). The run went from 03:27 to 03:53; at 03:35 macOS
  deletes files in the temporary folder that look older than 3 days, and
  the benchmark copied task files with their own old dates. Fixed in
  `0369279`: the copies get the time of the copy. That run is run again
  on the next night.
- **The local runs are slow on these tasks:** about 22 minutes a run,
  5 of 12 at the 30-minute limit.
