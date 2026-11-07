# Questions and answers

Questions people have asked about Certo, with short answers and links to
the pages that explain each one in full.

## Choosing models

### Do I have to rate the models myself?

No, there is a default to start from. Certo's example model list,
`models_list.yaml`, rates each model from 1 to 5 on reasoning,
precision, code and cost (on every rating, higher is better, so `cost: 5`
means cheapest). The ratings are based on public benchmarks that compare
providers; `cost` comes from the list price by a formula, to one decimal,
so a model twice as expensive is always rated lower. They are not measured on your projects. `certo init models`
uses them as they are.

You rate a model only when it isn't in the list: `certo init models`
asks for its ratings and shows the ratings of your other models next to
them, so you use the same scale. Certo never makes up a rating. To
change a rating for yourself, override it in `models.yaml`
(`ratings: {code: 4}`).

To check the ratings against your own work, give the same task to
several models ([Compare models on one task](guides/compare-models-on-a-task.md)),
or run the [benchmark](guides/benchmark.md) with tasks of your own. If
you would rather not use ratings for escalation, write the order
yourself as a ladder in `escalation.yaml`. See
[Pick models automatically](guides/pick-models-automatically.md) and
[Escalate between models](guides/escalate-between-models.md).

## Handing a task to another model

### How does Certo decide a model can't finish?

From what it can check, not from how the model feels about its work, and
not from how long it takes. With
[`--escalate`](guides/escalate-between-models.md), a task moves to the
next model when the model's whole run ends with a verdict that shows it
couldn't finish, or when its provider fails:

- **The checks kept failing.** When a check fails, Certo sends the real
  failure output back to the model for a fix. If the next attempt gives
  exactly the same failure, Certo stops at once with `no_progress`. If
  the failure keeps changing but never passes, the result is
  `retry_exhausted` after the fix attempts. Both hand the task on.
- **The run got stuck.** The agent's run ended in a stuck or error state
  (`stuck`), its to-do list still had open items (`incomplete`), or a
  check hung (`timed_out`).
- **The provider failed.** A rejected key, a refused request (no credit,
  or rate limited), a provider that can't be reached, or no answer in
  time. This is recorded as a provider failure, not a quality failure.
- **The model did no work, or nothing could be checked** (`unchanged`,
  `inconclusive`). These hand on only once in a row: if the next model
  ends the same way, Certo stops instead of paying for every model on
  the list.

The full table: [What makes Certo climb](guides/escalate-between-models.md#what-makes-certo-climb).
What each verdict means: [Verdicts](reference/verdicts.md).

### Does a failed test send the task to another model straight away?

No. A failed test first goes back to the **same** model, with the real
failure output, for another attempt. Each model gets up to
`CERTO_MAX_VERIFY_RETRIES` fix attempts (2 by default), or the number set
by `retries` on its step of the ladder. Only when those attempts run out
(`retry_exhausted`), or one of them changes nothing (`no_progress`), does
the task move to the next model. The order is: try, fix, fix again, then
hand over.

A recorded run where the first model's provider fails and the next model
passes the checks:
[Escalation past a provider failure](benchmark/escalation-provider-failure-0.1.22.md).
One where the local model finishes and no other model is called:
[One escalation run](benchmark/escalation-wordle-0.1.19.md).

### Does a tool error make Certo switch models?

No. A command that fails inside a run is output like any other: the model
sees the error and can fix it. Only the verdict at the end of the run, or
a provider failure, moves the task.

### Can Certo tell a stuck model from a slow one, on local models?

Certo never switches because a model is slow. A slow local model is
handled with limits you set:

- **One model call.** `timeout_seconds` in the model files, or
  `CERTO_LLM_TIMEOUT_SECONDS`, sets how long one call may take
  (`certo init` sets 1200 seconds for Ollama). A call that takes longer
  is tried again, up to 5 more times. Only when every try fails does it
  count as a provider failure ("the provider didn't answer in time"), and
  the task moves on.
- **The whole task.** `CERTO_MAX_TASK_SECONDS` and `CERTO_MAX_TASK_COST`
  cover every model together. When one runs out, Certo stops with
  `budget_exhausted` or `cost_exhausted` instead of moving on: these are
  your limits, not a sign that the model was too weak.
- **Steps.** A model that uses all its steps (`CERTO_MAX_ITERATIONS`) is
  checked like one that finished: passing checks give `verified`, failing
  checks get the fix attempts.

A stuck model is caught in two ways. The agent SDK under Certo
(OpenHands) ends a run that repeats itself in a loop; the verdict is
`stuck`. And `no_progress` catches a model whose fix attempts change
nothing in the check output, even when what it writes sounds sensible.

When the time budget runs out, the agent stops after its current step.
On local runs that step can't outlast the budget by more than a few
seconds: a call to the model or a terminal command can't wait longer
than the time left. The SDK's loop detection
only catches exact repetition; a model that writes new but useless text
is caught at the next check, or by the step and time limits.

### What does the next model get: the conversation, a summary, or the diff?

Each model starts a **fresh conversation** in the **same folder**. It
gets:

- the files exactly as the previous model left them;
- the original task;
- the real output of the checks that were still failing;
- a short note written by Certo from what it recorded, never by a model:
  which model tried, how it ended, how many fix attempts it used, the
  files it created, changed or deleted, and which checks were failing.

It doesn't get the previous model's conversation or reasoning. A
conversation can be huge, and replaying it to a more expensive model
costs money and adds noise. A summary written by the model that just
failed would be the least reliable part to pass on. The files and the
failing check output are the state that matters.

An example note: [What the next model receives](guides/escalate-between-models.md#what-the-next-model-receives).

### What if a model leaves half-finished work or a messy folder?

Certo doesn't clean up or roll back between models. The next model gets
the folder as it is, half-finished work included, and the note asks it
to look at the files first, keep what works and finish the task. The
file lists in the note come from comparing the folder before and after
the previous model's turn; they are a list of files, not a full diff.

You can still go back yourself: Certo takes a checkpoint at every check
run, for every model, and `certo rollback N` puts the files back as they
were at one. See [Go back to an earlier point](guides/checkpoints.md).

A recorded run where a local model leaves the task half done (45 of 46
tests passing) and a cloud model finishes it, keeping the local model's
fixes: [Escalation past failing tests](benchmark/escalation-handoff-0.1.23.md).

### What if the provider drops in the middle of a model's work?

The model's turn ends there, and the task moves to the next model. A
provider fails during a call to the model, between tool calls, so each
file edit the model made either happened or didn't. Certo runs no
checks on that turn: there is no failing check output to pass on. The
next model's note says the turn ended with a provider failure, names the
error, and lists the files the model had created, changed or deleted by
then. Then the next model works on the files as they are.

A recorded run where the first model's provider fails:
[Escalation past a provider failure](benchmark/escalation-provider-failure-0.1.22.md).

### Is the final result reproducible if several models touched the files?

The verdict is. It comes from Certo running the project's own checks on
the folder as it is at the end, with no model involved. So whichever
models worked on it, and in whatever order, `certo verify` on the same
folder runs the same checks again, at no cost. In the benchmark, the
hidden tests also run on the final folder only.

The path that led there is not reproducible: models don't give the same
answer twice, and a provider failure can come at any point. To see what
each model did, keep the run records (next question).

### Does `--auto-model` hand off the same way?

No. [`--auto-model`](guides/pick-models-automatically.md) keeps the
**same conversation** and swaps only the model, so the next model sees
the full history as well as the files. It switches when the provider
fails, or when a fix attempt still fails the checks. Under
`--execution docker` it can't switch in the middle of a task.
`--escalate` starts a fresh conversation for each model, as described
above. Which to use: [Auto model or escalation](concepts/auto-model-or-escalation.md).

### Can I see what each model did, to debug a handoff?

Yes. `MODEL_DECISIONS.md` in the project records every handoff and its
reason. With `CERTO_ARTIFACTS_DIR` set, each model also gets its own
folder with its full transcript, tokens, cost and verdict. See
[Run records and costs](guides/run-records-and-costs.md#keep-a-record-of-every-run).

## CI and exit codes

### Can CI tell "tests failed" from "the agent couldn't finish"?

Not from the exit code: it is 0 for `verified` and 1 for every failure.
The difference is in the verdict, which you can read in three places:

- the `Verification: <verdict>` line Certo prints;
- `verification_state` in the run's `metadata.json` (with
  `CERTO_ARTIFACTS_DIR`);
- the result of the [server API](reference/server-api.md).

For example, `retry_exhausted` means the tests still fail after the fix
attempts; `no_progress` that a fix attempt changed nothing; `stuck` or
`incomplete` that the agent didn't finish; `budget_exhausted` that it ran
out of time.

`inconclusive` (nothing could be checked) and `unchanged` exit 0 by
default. Add `--require-verification` in CI to make them fail too. See
[Verdicts](reference/verdicts.md) and [Verify in CI](guides/verify-in-ci.md).

## The verdict

### Why not trust the model when it says the work is done?

Because agents are often wrong about being finished. Certo runs the
project's own tests and build itself, with no AI involved, after the
agent stops. "The model said it worked" never counts as `verified`. The
real cases behind this are in [Why agents lie](concepts/why-agents-lie.md),
and how the checks work in
[How verification works](concepts/how-verification-works.md).

## How Certo is built

### Why is Certo built on the OpenHands SDK?

So that Certo's own code can be about checking the work, not about
running the agent. The [OpenHands Software Agent SDK](https://docs.openhands.dev/sdk)
already runs the agent loop, gives the agent its terminal and file
tools, talks to every provider through LiteLLM, and can run the work in
Docker. Certo adds the rest: when a task counts as done, which model
runs and when to hand over, the time and cost limits, and the CLI and
server you use.

The SDK gives Certo what it needs:

- **Any model, with no code change.** Moving between Claude, GPT,
  Gemini and a local Ollama model is one setting, `CERTO_LLM_MODEL`.
  See [OpenAI, Claude and Gemini](guides/openai-claude-gemini.md) and
  [Ollama and local models](guides/ollama-and-local-models.md).
- **Tools you can test without a model.** Each custom tool is a small
  class that unit tests can call directly, with no model call. See
  [Add custom tools](guides/add-custom-tools.md).
- **Parts Certo uses as they are:** asking before each tool call
  (`CERTO_CONFIRM_MODE`), summarizing older steps when a small context
  window fills up (`CERTO_CONDENSE`), token and cost counts per run, and
  [running in Docker](guides/run-in-docker.md).

The SDK is young and its API still changes, so Certo pins one exact
version and moves to a new one only after its tests pass with it.
