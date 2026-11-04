# Roadmap

Where Certo is going and why. This is the strategy: themes, goals and
how we will know they worked. The concrete items are in `TODO.md`, the
reasons behind past choices in `DECISIONS.md`, and how the code is built
in `ARCHITECTURE.md`. User documentation is in `docs/`.

> **Maintenance note:** this file changes rarely: when a theme is
> finished, the priorities change, or a goal is met or dropped. It names
> no files or functions; those belong in `TODO.md`. See `CLAUDE.md`.

## Vision

**Certo doesn't depend on one model or one provider.** It runs coding
tasks on any model, local or cloud, picks the best one for each task, and
hands a task to the next model when one can't finish or its provider
fails.

It can switch because it checks the work. A coding agent says "done";
Certo doesn't take its word for it. It runs the project's own checks with
no AI involved, gives one bounded verdict, and exits with a code a script
can use. That verdict is what tells Certo when a model's work is good
enough, and when to hand over.

The name means "certain", and the plan is to earn it with numbers. Certo
can say how often it would have been fooled: the benchmark grades every
run with hidden tests the agent never saw, and counts the runs where
Certo said `verified` and the hidden tests failed. No other harness
reports that number. It is the proof behind every claim the project
makes.

The goal: people use Certo for real, multi-language applications, and
trust its verdicts, whether the model runs on their own machine or in the
cloud.

## Principles

These shape every theme below. The full rules are the golden rules and
working agreements in `CLAUDE.md`.

- **Model-agnostic.** Switching model or provider is one setting, never
  a code change, and no feature may tie Certo to one model or one
  provider.
- **Never trust "done".** A verdict comes from checks Certo runs itself.
  Where a rule can only be a prompt instruction, the docs say so.
- **Measure before claiming.** A quality change counts when the benchmark
  shows it, on a local and a cloud model, not after a good single run.
- **Better on local models, never worse on cloud ones.** Better results
  from local models, without making mainstream cloud models worse.
  Strategies for weaker models are opt-in or gated by tier.
- **Build on the OpenHands SDK.** The agent loop, tools and providers are
  the SDK's job. Certo adds configuration, verification, policy and an
  interface.
- **Honest output.** A verdict never claims more than its checks prove;
  docs never show output that wasn't produced by a real run.

## Where we are (October 2026)

- Every milestone of the original build plan is done, including the live
  provider-swap proof: one task, verified on an OpenAI and an Anthropic
  model with only the model id changed.
- Certo verifies Python, Node, Go, Rust and Java projects, with
  escalation between models, automatic model choice, resume, Docker and
  server modes, and a benchmark. 0.1.19 is on PyPI.
- Published runs: baselines for 0.1.13 and 0.1.15 (135 runs, Certo fooled
  3 times), escalation in 0.1.17 (a local-then-cloud ladder solved all 9
  tasks, 7 of them on the local model), and a local baseline for 0.1.18
  that chose the default local model. The tasks are too small to separate
  a good local model from a cloud one; escalation has only climbed past a
  model that did no work, and automatic model choice has never been
  measured.

The main risk: Certo is broader than it is proven. Several features have
never run outside unit tests, and "verified" mostly means "passes the
agent's own tests". So the next phase favours proof and depth over new
breadth.

## Themes

In priority order. Each says what success looks like.

### 1. Prove it publicly

Publish numbers regularly: local against cloud, the fooled rate, the
cost per solved task. A full baseline takes hours on a local model, so
the Author decides per release whether to run one; minor releases may
skip it. Grow the benchmark from small single-file tasks
to app-scale, multi-language ones, so it can tell models and strategies
apart and show whether escalation pays off. Re-check, with live runs, the
fixes that so far are only unit-tested.

*Success:* a recent published baseline, and one before any release that
changes how results are reached; a fooled rate close
to zero on app-scale tasks; no feature described as working without a run
that shows it.

### 2. Make "verified" mean more

Today the strongest evidence is the agent's own tests, which share its
misunderstandings. Close that gap: tests written from the task by a
separate conversation, which the builder may not edit; protection against
an agent weakening the checks; and verification that runs the app itself
(a server answering, a page that renders), not only its tests.

*Success:* `verified` on the benchmark agrees with the hidden tests, also
on tasks where the agent's own tests would have passed wrong code.

### 3. From small tasks to applications

Split big work into milestones, each verified before the next, with
checkpoints that can be rolled back, and context management for long
runs. This is the step from "a small task" to "an app".

*Success:* an app-scale benchmark task completed and verified in
milestones, on a cloud model and on a local one.

*Reached* (0.1.27, 2026-10-31): Haiku verified both app tasks in
milestones, and `qwen3.8:27b` verified the smaller one in 2 of 3 runs.
What's left (Certo planning the milestones itself, a larger app on a
local model) is in `TODO.md`.

### 4. Every common language and framework

Close the known gaps in today's languages, then add new ecosystems (.NET,
PHP, Ruby, Kotlin, C/C++, Swift), each with skills that tell the agent
how to make that kind of project checkable.

*Success:* a project in any listed ecosystem ends `verified` or with a
precise reason why it can't be, never a silent pass.

### 5. The best harness for local models

Make small and mid-size local models deliver: tuning per model tier,
checks of the local setup (context size, speed), and real measured speed
in the model catalog, so ladders can start on the fastest model that is
good enough.

*Success:* on the benchmark, a local model solves a growing share of the
tasks a cloud model solves, at no cost.

### 6. Easy to adopt

The first run needs one model and a few minutes, with no catalog or
ladders; those come later, for people who want them. Then reach people
where they work: a GitHub Action that turns an issue into a verified pull
request, an MCP server for editors, readable run reports.

*Success:* a new user reaches a first verified project without reading
about ladders, profiles or the benchmark; time from install to first
`verified` is measured and short.

## Now, next, later

- **Now:** 0.2, which starts the MCP server with every Certo command
  (0.1.27, with milestone mode, was released on 2026-11-01).
- **Next:** independent tests from the spec; the pull-request CI; more
  "make it verifiable" skills; the simple first run.
- **Later:** run-the-app verification, new ecosystems, the GitHub Action,
  local-model tuning.
- **Possible:** an integration with Jev, TypeSafe's model for fast,
  typed decisions (choose one of a list, score, yes or no, with a
  confidence). It would be optional and off unless the user turns it
  on, with their own TypeSafe API key; without it Certo works exactly as
  today. Which decisions it would take is still to be designed. Using it
  to choose models or skills would change the "no LLM-based router"
  choice below, so that would need its own decision first.

Meanwhile, keep the less central parts (the server's SQL and Redis
stores, the OpenAI-compatible endpoint, third-party skills, Docker mode)
working and documented, but marked experimental: they don't set the pace.

## Not planned

Choices made on purpose, each with its reason in `DECISIONS.md`:

- **No LLM-based router** for models or skills: selection stays
  deterministic, with no extra model call.
- **No command-running acceptance checks**: an unauthenticated server
  caller could run commands on the host.
- **No auto-approval** in confirm mode, and no guessing input to drive
  interactive programs.
- **No trust in the agent's own report** as proof, ever; no use of
  Certo's own Python environment for a project's checks.
- **No reimplementing the SDK**: agent loop, tool protocol, provider
  routing and sandboxing stay upstream.
