# Escalate between models

This guide shows how to run each task on the cheapest model that can
actually do it: start on a free local model, and move to a stronger
(usually paid) model only when Certo's verification shows the cheap one
couldn't finish.

```bash
certo "Build a terminal Wordle game in Python, with pytest tests" --escalate
```

## What escalation is

You give Certo a **ladder**: a list of models from your model files,
cheapest first. Certo runs the task on rung 1, the normal way: the agent
works, Certo runs the project's checks, sends failures back, and gives a
verdict. Then:

- if the verdict is `verified`, it stops: the cheap model did the job;
- if the verdict shows the model couldn't finish (for example
  `no_progress`), the task goes to rung 2, a stronger model, in the same
  folder;
- and so on, until a verdict doesn't call for a climb, the ladder ends, or
  a limit is reached.

Escalation works **per task**: one model at a time, climbing when that
model's whole run fails verification. It doesn't switch models step by
step inside a run.

**When it pays off.** When many of your tasks are within reach of a local
model and some aren't. The easy ones cost nothing; only the hard ones reach
the paid model. If your local model almost never succeeds, escalation only
adds its time to every task: run the cloud model directly. Use
[`certo bench`](#prove-it-with-certo-bench) to find out which case you're
in.

Escalation is off unless you ask for it. Without `--escalate`, Certo runs
exactly as before. To compare it with `--auto-model`, see
[Auto-model or escalation](../concepts/auto-model-or-escalation.md).

## Set up a ladder

Escalation uses three model files (see
[The model files](../reference/models-yaml.md)):
`models_list.yaml` describes the models; `models.yaml` holds your keys and
says which models you use; `escalation.yaml` holds your ladders. The last
one is optional: without it, Certo builds a ladder from the ratings. Copy
the example Certo ships to start one; `certo check` prints the command:

```bash
cp <examples>/escalation.yaml.example ~/.config/certo/escalation.yaml
```

Only models enabled in `models.yaml` are ever used; a rung whose model
isn't enabled there is skipped.

With `--project NAME`, a model-file configuration error leaves no new
project folder or registry entry. An existing project folder is kept.

### An explicit ladder

Write the order yourself, under `escalation.ladders` in
`escalation.yaml`:

```yaml
# escalation.yaml
escalation:
  ladders:
    default:
      - model: qwen-local
        retries: 1          # fix attempts on this rung
      - model: gpt-luna
      - model: claude-sonnet
    local-only:
      - model: qwen-local
      - model: gemma-local
        reasoning_effort: max
```

- `certo ... --escalate` uses the ladder named `default`.
- `certo ... --escalate local-only` uses that ladder.
- `retries` sets how many fix attempts that rung gets after a failed check
  (default: `CERTO_MAX_VERIFY_RETRIES`). One attempt is often enough for a
  local model before handing over.
- `reasoning_effort` sets that rung's reasoning effort, instead of the
  model entry's own. Some local models do much better with `max`.
  One model may be listed twice with different efforts, for example
  `low` and then `high`. Everything Certo prints and records names the
  effort next to the model (`default` when none is set), so the two rungs
  can be told apart.

An explicit ladder always wins over a derived one.

### A derived ladder

With no `escalation.yaml`, or no ladder named `default` in it, Certo builds
the ladder from your ratings. It is the same for every task, and printed
before the run starts.

1. **Capability.** A model's capability is the sum of its ratings on
   every axis **except the cost axis** (`cost`, or `escalation.cost_axis`).
   With the usual axes that is `reasoning + precision + code`. Task
   profiles are not used: they only steer `--auto-model`. If your cost
   rating has another name, set `escalation.cost_axis` to it, or it counts
   as capability.
2. **The best of the cheapest.** Certo starts from the cheapest models
   (in Certo's ratings, a higher `cost` means cheaper) and takes the most
   capable of them. Then it moves to more expensive models, and keeps one
   only when it is more capable than every model already kept. A model
   that another model beats at the same price or less is left out: paying
   more must buy more. When two models tie on cost and capability, the
   one whose name comes first is kept. A model with no cost rating counts
   as the most expensive. If no model has a cost rating, there is no price
   to compare, and Certo keeps every model, least capable first.
3. **Length.** At most `escalation.max_rungs` rungs (default 3). With *n*
   kept models and *k* rungs, rung *j* (counting from 0) is model number
   floor(*j* × (*n* − 1) / (*k* − 1) + 0.5) in that order. So the first
   rung is always the best of the cheapest models, the last rung the most
   capable one, and the rungs between are spread evenly.

**A worked example.** Five active models, rated like this:

| Model | reasoning | precision | code | cost |
|---|---|---|---|---|
| qwen-local | 2 | 2 | 3 | 5 |
| gemma-local | 3 | 2 | 2 | 5 |
| gpt-luna | 3 | 3 | 3 | 5 |
| claude-sonnet | 4 | 4 | 5 | 3 |
| claude-opus | 5 | 5 | 5 | 1 |

Capabilities (reasoning + precision + code) are qwen 7, gemma 7, luna 9,
sonnet 13, opus 15. qwen, gemma and luna all have cost 5, and luna is the
most capable of them, so qwen and gemma are left out. sonnet and opus each
beat every cheaper model, so both stay:

```text
Escalation: derived ladder (from the ratings), 3 rung(s):
  1. gpt-luna (capability 9, cost rating 5; effort default)
  2. claude-sonnet (capability 13, cost rating 3; effort default)
  3. claude-opus (capability 15, cost rating 1; effort default)
  Skipped: gemma-local (gpt-luna is at least as capable and costs no more), qwen-local (gpt-luna is at least as capable and costs no more)
```

The ratings know nothing about speed. If you would rather start on a
faster or more specialised model (for example qwen-local, the coding
model), write an explicit ladder.

## What makes Certo climb

| Verdict of a rung | What happens |
|---|---|
| `verified` | Stop. The task is done. |
| `retry_exhausted`, `no_progress`, `timed_out`, `incomplete`, `stuck` | Climb to the next rung. |
| The model used all its steps (`CERTO_MAX_ITERATIONS`) | The checks run first. If they pass, stop: `verified`. If they fail, the rung gets its fix attempts, then climbs like any failure. |
| `acceptance_failed` | Stop, unless the ladder sets `escalate_on_acceptance_failed: true`. |
| `inconclusive` | Climb, unless the rung before also ended `inconclusive`, or both changed no file: then stop. |
| `unchanged` | Climb, unless the rung before also changed no file: then stop. |
| `budget_exhausted`, `confirmation_required` | Stop: these are your own limits. |
| A provider failure (outage, rate limit, rejected key) | Climb, recorded as a provider failure rather than a quality failure. |

**Why `inconclusive` climbs, but only once in a row.** It means nothing
could be checked: no test ran, or no check could run. Often the model
wrote the code and not the tests, for example because it wrote its last
tool call as text. The next model gets the files and a note asking it to
finish the task and add tests that check it. If that model also ends
`inconclusive`, the project most likely has nothing Certo can check (a
plain HTML page, a missing tool such as `npm`), and Certo stops instead of
paying for every rung. Asking for tests in the task ("with pytest tests")
avoids this.

**Why a model that changed nothing climbs, but only once in a row.** The
model did no work: it ended `unchanged` (see
[`unchanged`](../reference/verdicts.md#unchanged-in-more-detail)), or
`inconclusive` without writing a file, as when a local model writes its
tool calls as text and the run ends at once. A model that stops too early
is replaced by a stronger one. If that one also changes nothing, two
models agree that the task needs no change, and Certo stops instead of
climbing to the most expensive model.

The final verdict is the verdict of the last rung that ran.

## What the next model receives

Each rung starts a **fresh conversation** in the **same folder**. The next
model doesn't get the previous model's conversation: that can be huge (one
local run sent 344,000 input tokens for a hello-world task), and replaying
it to an expensive model costs money and adds noise. It gets:

- the files, exactly as the previous rung left them;
- the original task;
- the real output of the checks that were failing (the same output Certo
  sends on a retry);
- a short note written by Certo from what it recorded, never by a model.

A real handoff message looks like this:

```text
Another model already worked on this task in this folder and couldn't finish it. Its files are still here, exactly as it left them: look at them first, keep what works, and complete the task. This summary was written by Certo from what it recorded, not by a model.

- Model: qwen-local (ollama/qwen3-coder:30b, effort default)
- Result: no_progress
- Fix attempts after failed checks: 1
- Files it created: tests/test_wordle.py, wordle.py
- Files it changed: README.md
- Files it deleted: none
- Checks failing when it stopped: pytest (`.venv/bin/python -m pytest -q`)

The task:

Build a terminal Wordle game in Python, with pytest tests.

Output of the checks that were failing:

### pytest (`.venv/bin/python -m pytest -q`) — pytest failed (exit 1)

FAILED tests/test_wordle.py::test_repeated_letters - AssertionError: assert ['present', 'present'] == ['correct', 'absent']
1 failed, 7 passed in 0.12s
...
```

When the previous model ended `inconclusive` after writing files, the
note says so instead, and asks the next model to keep what works, finish
the task and add tests that check it.

The file lists come from a listing of the folder before and after the
rung, leaving out caches, environments (`.venv`, `node_modules`) and
`.certo/`.

## Limits

- **Time.** `CERTO_MAX_TASK_SECONDS` covers every rung together, as it
  covers every retry. Each rung has its own fix attempts.
- **Cost.** Set `CERTO_MAX_TASK_COST` (US dollars) to cap a run. Before
  each rung starts, Certo adds up the cost recorded so far; once it reaches
  the cap, the climb stops with the verdict it has, and a note says so.
  A local model costs nothing. A cloud model with no known price (newer
  than your LiteLLM) counts as 0, and the note names it.

## What you see

Before the run, the ladder (above). When a rung ends and the next starts,
one line:

```text
Certo: qwen-local ended no_progress after 1 fix attempt; escalating to gpt-luna (rung 2 of 3).
```

When a rung fails at the provider, the line says why in plain words, with
the error's name; the full error is in `MODEL_DECISIONS.md`:

```text
Certo: claude-sonnet-5-5 failed: the provider rejected its API key (LLMAuthenticationError); escalating to gpt-5.6-luna (rung 2 of 2).
```

When the same model climbs to a higher effort, the line names both:

```text
Certo: local (effort low) ended no_progress after 1 fix attempt; escalating to local (effort high) (rung 2 of 2).
```

The reasons Certo knows are a rejected key, a refused request (no credit,
or rate limited), no answer in time and a provider that can't be reached.
Any other error is shown as it is.

At the end, the run summary has one line per rung and the rung that gave
the final result:

```text
  Rungs:
    1. local (ollama/q, effort default): no_progress, 1 fix attempt, 1m 00s, 0 tokens, $0.0000
    2. mid (openai/m, effort default): verified, 0 fix attempts, 30.0s, 0 tokens, $0.0000
  Final result from rung 2 (mid).
```

`MODEL_DECISIONS.md` in the project records the ladder, how it was built,
every climb with its reason and why the climb stopped. With
`CERTO_ARTIFACTS_DIR`, each rung also gets its own folder of records (see
[Run records and costs](run-records-and-costs.md#keep-a-record-of-every-run)).
In server mode, results carry a `rungs` list (see
[Server API](../reference/server-api.md)).

## Confirm each climb

With `--interactive`, Certo asks before moving to the next rung, with the
cost so far and a rough price for the next model:

```text
qwen-local couldn't finish (no_progress). Try gpt-luna next? Cost so far: $0.0000. gpt-luna: roughly $0.24 for a run, from LiteLLM's prices. [Y/n]
```

Enter climbs; `n` stops with the current verdict. Without `--interactive`
escalation is automatic, and in server mode it is always automatic.

## Docker

Escalation works with `--execution docker`: every rung runs as a new
conversation in the same container, so it sees the same files and the
same Python environment. In Docker mode Certo can't tell a provider
failure from another run error, so any run error ends the rung and the
task moves to the next one, recorded as a "provider or run failure".

## Settings and requests

- **CLI:** `--escalate [LADDER]`. It can't be combined with
  `--auto-model`, `--model` or `--resume`.
- **Settings:** `CERTO_MODEL_SELECTION=escalate`, and optionally
  `CERTO_ESCALATION_LADDER=NAME` (see [Configuration](../reference/configuration.md)).
- **Server:** an `escalate` field on `POST /tasks` and the WebSocket:
  `true`, or a ladder name.

## Check the configuration first

```bash
certo check --models
```

`certo check` lists your active and inactive models, each ladder with its
usable rungs, the derived ladder, and every error and warning in the model
files (for example a rung that names a model that doesn't exist). `--models` also sends a real test request to every
active model, so a broken key or a model without tool calling shows up
now, not halfway up a ladder. See [Commands](../reference/commands.md#certo-check).

## Prove it with `certo bench`

Measure escalation on your own models before relying on it. A benchmark
with four arms compares it fairly:

```yaml
arms:
  - {name: local, strategy: single, model: qwen-local}
  - {name: cloud, strategy: single, model: gpt-luna}
  - name: local-then-cloud
    strategy: escalate
    models: [qwen-local, gpt-luna]
  - name: derived
    strategy: escalate
```

What to look for in `results.md`: escalation should pass at least as many
hidden tests as the local model alone, come close to the cloud model, and
cost less than the cloud model. **Cost per solved task** and **which rung
produced the final result** show where the money went. See
[Benchmark models and strategies](benchmark.md).

Certo's own run of two ladders, with the numbers, is
[Escalation in 0.1.17](../benchmark/escalation-0.1.17.md).
A recorded run where the first model's provider fails (its key was
rejected on purpose) and the next model finishes the task is
[Escalation past a provider failure](../benchmark/escalation-provider-failure-0.1.22.md).

## Related

- [The model files](../reference/models-yaml.md#escalationyaml)
- [Pick models automatically](pick-models-automatically.md)
- [Auto-model or escalation](../concepts/auto-model-or-escalation.md):
  how the two differ, and when to use which
- [How verification works](../concepts/how-verification-works.md)
- [Troubleshooting](../troubleshooting.md#model-files-and-escalation)
