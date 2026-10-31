# Live check: a ladder of models inside milestones, Certo 0.1.27

With `--milestones --escalate`, each milestone climbs its own ladder of
models, starting again on the first rung. This had unit tests only.
These runs show it, and found a bug in what the end of the run prints.

## The setup

- **Certo:** 0.1.27 (not released yet), 2026-10-31, the installed
  `certo` command.
- **Task file:** [milestones-temperature.task.md](milestones-temperature.task.md),
  the two-milestone example from the
  [milestones guide](../guides/run-in-milestones.md).
- **Ladder:** `claude-haiku-5-5`, then `claude-sonnet-5-5`, in model
  files of their own (`XDG_CONFIG_HOME` pointed at a scratch folder):

  `models.yaml`:

  ```yaml
  models:
    # A wrong key on purpose: the first rung's provider rejects it.
    - name: claude-haiku-5-5
      api_key: "not-a-real-key"
    - name: claude-sonnet-5-5
      api_key: "${ANTHROPIC_API_KEY}"
  ```

  `escalation.yaml`:

  ```yaml
  escalation:
    ladders:
      default:
        - model: claude-haiku-5-5
        - model: claude-sonnet-5-5
  ```

  `models_list.yaml` is a copy of the example Certo ships.
- **Why a wrong key:** a rejected key is a provider failure, which always
  climbs, so every milestone is sure to need the second rung. Whether
  Haiku would fail a milestone on its own is left to chance otherwise.
- **Command:** `certo --milestones --escalate milestones-temperature.task.md`,
  with `CERTO_MAX_TASK_COST=1`.

## Results

Run twice: before and after the fix below. Both ended `verified`, exit
code 0.

| Milestone | First rung | Second rung | Cost (second run) |
|---|---|---|---|
| 1: Celsius and Fahrenheit | Haiku: the provider rejected its API key | Sonnet: `verified` | $0.0687 |
| 2: Kelvin | Haiku again, rejected again | Sonnet: `verified` | $0.1047 |

Each milestone started on Haiku, even though milestone 1 had needed
Sonnet:

```
Certo: claude-haiku-5-5 failed: the provider rejected its API key (LLMAuthenticationError); escalating to claude-sonnet-5-5 (rung 2 of 2).
```

`.certo/RUNS.md` had one entry per milestone, each with both rungs and
its own cost. The run summary at the end gave the total: 59.0s, 313,555
tokens, $0.1734.

## What the results say

- **The ladder works per milestone, as [documented](../guides/run-in-milestones.md#with-a-ladder-of-models):**
  each milestone climbed its own ladder from the first rung.
- **Fixed: the rungs at the end were the last milestone's only.** In
  the first run the end-of-run summary showed the whole run's totals
  ($0.2286), then a `Rungs:` list with milestone 2's rungs alone
  (Sonnet $0.1048), as if that were all Sonnet cost. The README note
  Certo adds in a project it created used the same list. Now each
  milestone's rungs are printed under its verdict, and the note gets
  every milestone's models. The table above is from the second run.
- **`--escalate` still needed `CERTO_LLM_MODEL` and a key**, though the
  ladder picks every model: the first try stopped with a configuration
  error. Changed the same day: with `--escalate` or `--auto-model`
  neither is needed now.
- **Not tested here:** a climb because the first model's work failed its
  checks, inside a milestone. That path is the same as without
  milestones, which has run live before
  ([escalation past failing tests](escalation-handoff-0.1.23.md)).

## Related

- [Run a task in milestones](../guides/run-in-milestones.md)
- [Escalate between models](../guides/escalate-between-models.md)
