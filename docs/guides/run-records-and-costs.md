# Run records and costs

This guide explains the summary Certo prints after every run, and how to
keep a full record of each run on disk: the transcript, the tokens and the
cost.

## The run summary

Every `certo` run ends with a summary after the verdict:

```text
Run summary:
  Total running time: 4m 03s
  Models: openai/gpt-5.6-luna (effort default)
  Total tokens: 801,191 (input 774,063, of which cached 725,104; output 27,128)
  Total cost: $0.0593
```

- **Total running time** covers the whole task: every agent run, Certo's
  checks and retries, and any time waiting for your answers.
- **Models** lists every model that made calls. With
  [automatic model selection](pick-models-automatically.md), a fallback
  adds a second model, and one line per model with its tokens and cost.
- **Total tokens** is input plus output. Cached input is part of the input
  number.
- **Total cost** uses LiteLLM's prices. A local model (an id starting
  with `ollama/`, `ollama_chat/`, `lm_studio/`, `hosted_vllm/` or
  `llamafile/`) costs nothing. When LiteLLM has no price for any other
  model, the line ends with `+ unknown (no pricing data for ...)`. That
  means unknown, not free.
- **Older steps summarized** appears only when the conversation nearly
  filled the model's context window: the agent framework then summarized
  its older steps, keeping the task and the latest steps, and the run
  went on. The summary is written by the same model, and its tokens are
  in the totals. It says how many times, for example
  `Older steps summarized: once (the context window was nearly full)`.

## Limit what a task can spend

Set `CERTO_MAX_TASK_COST` to a number of US dollars:

```bash
CERTO_MAX_TASK_COST=0.50 certo "Add a --json flag to report.py"
```

The limit covers the whole task: every model call, the fix attempts,
escalation rungs and independent tests. The banner shows it on the
`Limits` line. Certo reads the cost every few seconds and stops the agent
at its next step once the cost reaches the limit, with this note:

```text
Certo: the task has cost $0.0065, reaching its limit (CERTO_MAX_TASK_COST=0.004). The agent was stopped.
```

The model calls made since the last reading are paid for, so the total
can end a little over the limit, as here: on a very small limit like
this one, the overshoot is large in proportion. The checks then run once, since they cost
nothing: work that passes is `verified`, anything else ends
[`cost_exhausted`](after-the-verdict.md#cost_exhausted). A model with no
known price counts as 0, so the limit can't stop it. `--resume` starts
with a fresh limit.

## Keep a record of every run

Set `CERTO_ARTIFACTS_DIR` to a folder:

```bash
CERTO_ARTIFACTS_DIR=./artifacts certo "Add a /version endpoint" --project my-api
```

Each run gets its own folder:

```text
artifacts/
  my-api/              the --project name, or _unscoped without one
    <run-id>/
      metadata.json
      transcript.json
      metrics.json
```

The folder sits next to your projects, not inside them, so it never ends up
in a project's git history. Runs are never overwritten. In server mode,
`POST /tasks` runs use the task id as the run id.

| File | What it holds |
|---|---|
| `metadata.json` | The task, project, model and its reasoning effort, execution mode, start and end time, verdict, what was checked and any limitations, acceptance results, the run summary, and the error if the run failed. Written even when the run fails. |
| `transcript.json` | Every message of the run. |
| `metrics.json` | Tokens and cost: `summary` (same as above), `combined`, and `per_model`. |

An escalation run (`--escalate`) also gets a `rungs` list in
`metadata.json`, and one folder per rung under `rungs/` (for example
`rungs/1-qwen-local/`, `rungs/2-gpt-luna/`), each with its own
`metadata.json`, `transcript.json` and `metrics.json`, so every model's
part can be read on its own. The run summary then ends with one line per
rung and the rung that produced the final result:

```text
  Rungs:
    1. local (ollama/q, effort default): no_progress, 1 fix attempt, 1m 00s, 0 tokens, $0.0000
    2. mid (openai/m, effort default): verified, 0 fix attempts, 30.0s, 0 tokens, $0.0000
  Final result from rung 2 (mid).
```

## Which model built this project

Every `certo` run also adds an entry to `.certo/RUNS.md` in the project
folder. `STATUS.md` holds only the last run; `RUNS.md` keeps every run,
oldest first, so you can still tell which model built a project many runs
later:

```text
## 2026-10-19 08:05 UTC · verified

- Task: Build a terminal Wordle game in Python, with pytest tests.
- Certo: 0.1.19
- Model: openai/gpt-5.6-luna (effort default)
- Time: 4m 03s · Tokens: 801,191 · Cost: $0.0593
```

- The heading is when the run started, and how it ended: the verdict,
  `interrupted`, or `error:` with the error. A run stopped by Ctrl-C or
  an error still has its time, tokens and cost up to that point.
- With `--escalate`, there is one line per rung that ran, with its model
  and verdict. With `--auto-model`, the line says so.
- Certo writes the entry after the run, never the agent. It names models,
  never keys.
- `.certo/` is ignored by git (it has its own `.gitignore`), so the file
  stays on your machine. It moves with the folder when you rename or copy
  it.
- `CERTO_SAVE_STATE=false` turns it off, with the rest of `.certo/`.
  Server mode and `certo bench` never write it.

In a project folder Certo created (`--project` with a new name), Certo
also keeps a one-line note at the end of the project's `README.md`, so
the information travels with the code:

```text
<!-- certo:models -->
*Generated with [Certo](https://github.com/alessioricco/certo), using `ollama/qwen3.8:27b`, `anthropic/claude-haiku-5-5`.*
<!-- /certo:models -->
```

It names every model that wrote code in the project, oldest first; an
escalation rung that changed no file isn't named. A later run updates the
same note instead of adding another. Certo adds it only after a run that
finished, and only when the agent wrote a `README.md`. It never edits the
README of a folder you brought. If you delete the note, the next run in
that folder adds it again.

## Model decisions

With automatic model selection, `MODEL_DECISIONS.md` in the project folder
records which model was chosen and why. With escalation it records the
ladder, how it was built, every climb with its reason, and why the climb
stopped. It is written whether or not `CERTO_ARTIFACTS_DIR` is set. See
[Pick models automatically](pick-models-automatically.md).

## Related

- [Configuration](../reference/configuration.md)
- [OpenAI, Claude and Gemini](openai-claude-gemini.md#cost)
