# Record: models chosen by fit against by weights, Certo 0.2.3

Until 0.2.2, `--auto-model` ranked the models by a weighted sum of their
ratings (`weights:` in each task profile). From 0.2.3 a profile says what
a task needs (`needs: {code: 4}`), and Certo starts with the least costly
model that meets it; the fallbacks climb
([Pick models automatically](../guides/pick-models-automatically.md)).
This page shows which models each rule puts first, with no model called:
the order is decided before the run. A benchmark of the two rules with
live runs hasn't been made yet.

## The setup

- **Certo:** 0.2.3 from the repository (unreleased), commit `05ce4d2`,
  on 2026-11-15.
- **Models:** Certo's own model list (`models_list.yaml.example`) with
  7 models enabled, the ones the Author uses: `qwen3.8-27b-local`,
  `claude-haiku-5-5`, `claude-sonnet-5-5`, `claude-opus-5-5`,
  `gpt-6-luna`, `gpt-6.1-terra`, `gpt-6.1-sol`.
- **Rules:** "weights" is 0.2.2's `task_profiles.yaml.example`; "fit" is
  0.2.3's. The ratings are the same in both.
- **Tasks:** the 10 samples Certo ships (`certo init` puts them in
  `tasks/`), classified as `--auto-model` does.

## By task profile

The first three models of each profile's order:

| Profile | Weights (0.2.2) | Fit (0.2.3) |
|---|---|---|
| debugging | Opus > Sol > Sonnet | Sol > Sonnet > Opus |
| refactor | Opus > Sol > Sonnet | Haiku > Terra > Sonnet |
| architecture | Opus > Sol > Sonnet | Opus > Sol > Sonnet |
| research | Opus > Sol > Sonnet | Sol > Sonnet > Opus |
| agent | Opus > Sol > Sonnet | Sol > Sonnet > Opus |
| extraction | Luna > qwen3.8 > Haiku | Luna > Sonnet > Sol |
| scaffolding | Haiku > Luna > Sol | Haiku > Luna > Terra |
| docs | (none: `default`) | qwen3.8 > Haiku > Terra |
| quick | (none: `default`) | Haiku > Terra > Luna |
| build | (none: `default`) | Haiku > Terra > Sonnet |
| default | Luna > Haiku > qwen3.8 | Haiku > Luna > Terra |

## By sample task

| Sample | Weights: profile, first model | Fit: profile, first model |
|---|---|---|
| alien-trekking, iron-horizon, sky-hopper, star-swarm, team-board | `default`, Luna | `build`, Haiku |
| hanoi, invaders, mazeman, space-rocks, wordle | `default`, Luna | `default`, Haiku |

## What it shows

- **Opus only where it is needed.** With weights, Opus went first for
  five kinds of task out of eight, because its high ratings outweighed
  its cost. By fit it goes first only for architecture, the one profile
  that needs reasoning 5.
- **Builds start on Haiku**, the least costly model with code 4. All
  ten samples now start on Haiku (five as `build`, five as `default`);
  with weights every sample fell to `default`, which started on Luna.
- **Writing starts on the local model** (`docs`, writing 3), and
  precise extraction on Luna, as intended.
- **Hard bugs don't start on Terra.** The goal was Terra for debugging;
  fit starts on Sol, because Terra's reasoning rating (3, an estimate
  with no benchmark behind it) is below the profile's need of 4. With
  the same ratings as Haiku but a higher cost, Terra is second wherever
  code 4 is enough. Which is right is for the ratings to settle, from
  benchmark numbers, not for the rule.
