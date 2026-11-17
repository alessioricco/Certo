# Benchmark: auto-model on hand ratings and on computed ratings, Certo 0.2.4

From 0.2.4 `certo models refresh` computes model ratings from public
evaluation data (LMArena, Epoch AI), list prices and Certo's own run
results, instead of ratings written by hand
([Pick models automatically](../guides/pick-models-automatically.md)).
The ratings decide which model `--auto-model` starts each task on, so
they are checked before the release (`CLAUDE.md`, working agreement 2):
the same five models, the same tasks and the same task profiles, once
with the hand ratings of 0.2.3 and once with the computed ones.

## The setup

- **Certo:** 0.2.4 from the repository (unreleased), commit `b3103bd`.
- **Machine running Certo:** Darwin 25.6.0, arm64, Apple M1, 8 CPUs,
  16 GB RAM.
- **Tasks:** the 13 bundled tasks (task set version 2), 1 run each.
- **Models (both arms):** `ollama/qwen3.8:27b` (on Ollama 0.40.15 on
  another machine, a 131,072-token window, model digest `aaee06c39dcf`),
  `openai/gpt-6-luna`, `openai/gpt-6.1-terra`,
  `anthropic/claude-haiku-5-5` and `anthropic/claude-sonnet-5-5`.
  **File:** [models-0.2.4-ratings.yaml](models-0.2.4-ratings.yaml).
- **Task profiles:** Certo's built-in `task_profiles.yaml`.
- **Hand arm:** the built-in model list of 0.2.3 as written. **Files:**
  [bench-0.2.4-ratings-hand.yaml](bench-0.2.4-ratings-hand.yaml),
  [models_list-0.2.4-hand.yaml](models_list-0.2.4-hand.yaml).
- **Computed arm:** the same list with the ratings from
  `certo models refresh` (model data of 2026-11-16, own results from 67
  earlier runs of `qwen3.8`), pinned in a file so a later refresh
  doesn't change the run. **Files:**
  [bench-0.2.4-ratings-computed.yaml](bench-0.2.4-ratings-computed.yaml),
  [models_list-0.2.4-computed.yaml](models_list-0.2.4-computed.yaml).
- **When:** both on 2026-11-16 from 21:29 UTC. The hand arm ran one run
  at a time; the computed arm one run at a time with 3-minute pauses,
  until 23:23 UTC.
- **Results folders:** `bench-results/ratings-0.2.4-hand` and
  `bench-results/ratings-0.2.4-computed`, on the machine that ran them.

The ratings that changed what ran:

| Model | Hand ratings | Computed ratings |
|---|---|---|
| qwen3.8-27b-local | code 2, precision 3 | code 3.4, precision 1.7 |
| gpt-6.1-terra | reasoning 3, code 4, cost 3.5 | reasoning 4.9, code 4.4, cost 4.3 |

The `default` profile (a task that matches no other profile) needs
`code: 3`. With the hand ratings `qwen3.8` doesn't fit it and Haiku is
the cheapest model that does; with the computed ones `qwen3.8` fits and,
being free, comes first.

## Results

| Arm | Started on | Hidden tests passed | Verified | Fooled | Budget used up | Median time | All runs | Tokens in / out | Cost | Cost per solved task |
|---|---|---|---|---|---|---|---|---|---|---|
| Hand | Haiku 11×, Sonnet 2× | 13/13 (100%) | 13/13 | 0 | 0 | 48s | 18m 39s | 5,424,310 / 225,716 | $0.6650 | $0.0512 |
| Computed | qwen3.8 11×, Terra 2× | 12/13 (92%) | 11/13 | 0 | 2 | 5m 43s | 2h 18m 41s | 3,863,839 / 235,630 | $0.2078 | $0.0173 |

Per task:

| Task | Hand: model, time, cost | Computed: model, time, cost |
|---|---|---|
| duration-parser | Haiku, 38s, $0.0083 | qwen3.8, 6m 34s |
| inventory-fix | Sonnet, 42s, $0.1394 | Terra, 1m 30s, $0.0572 |
| ledger-transfers | Sonnet, 1m 44s, $0.3253 | Terra, 3m 21s, $0.1507 |
| library-loans (Go) | Haiku, 3m 16s, $0.0377 | qwen3.8, 30m 14s, `budget_exhausted`, hidden tests passed |
| page-ranges | Haiku, 49s, $0.0102 | qwen3.8, 8m 16s |
| pedestrian-crossing | Haiku, 39s, $0.0088 | qwen3.8, 10m 54s |
| room-bookings (Node) | Haiku, 2m 59s, $0.0369 | qwen3.8, 26m 06s |
| semver-order | Haiku, 48s, $0.0114 | qwen3.8, 3m 52s |
| slugify | Haiku, 36s, $0.0080 | qwen3.8, 4m 44s |
| temperature-table | Haiku, 54s, $0.0112 | qwen3.8, 4m 13s |
| todo-deps (Rust) | Haiku, 4m 11s, $0.0497 | qwen3.8, 30m 04s, `budget_exhausted`, hidden tests failed |
| token-bucket | Haiku, 43s, $0.0097 | qwen3.8, 3m 10s |
| wordle-score | Haiku, 40s, $0.0084 | qwen3.8, 5m 43s |

Every run not marked otherwise ended `verified` with its hidden tests
passed.

## What it shows

- **The computed ratings move the default tasks to the local model.**
  11 of 13 tasks start on `qwen3.8` instead of Haiku. That is what the
  ratings say (its own 67 runs pushed its code rating to 3.4, above the
  `default` profile's 3), not a bug.
- **Nearly as good, a third of the cost, seven times slower.** One task
  fewer solved (`todo-deps`, Rust), which on 13 runs can be chance, but
  it is the task `qwen3.8` has failed before
  ([baseline-0.1.23.md](baseline-0.1.23.md)). The median run went from
  48 seconds to almost 6 minutes, and the Go, Rust and Node tasks took
  26 to 30 minutes each; two of them used up the 30-minute budget.
- **Auto-model doesn't retry on a bigger model.** A run that ends
  `budget_exhausted` on `qwen3.8` stays there; only an escalation ladder
  would hand it on.
- **The two harder tasks went to Terra instead of Sonnet**, both
  verified, for $0.21 instead of $0.46. Their profile needs
  `reasoning: 4` and `code: 4`; Terra's hand reasoning (3) kept it out,
  its computed one (4.9, from Epoch AI) lets it in, and it is cheaper
  than Sonnet.
- **On cloud models alone nothing got worse:** the two runs that started
  on a cloud model passed in both arms.

## Decision

The Author's call, 2026-11-17: keep it. A free local model takes the
`default` tasks when its ratings fit them. Listing a local model means
you want it used; to keep it out, leave it out of `models.yaml` or of a
project's `use`, or add `speed: 4` to a profile's needs. Recorded in
`DECISIONS.md`.
