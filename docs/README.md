# Certo documentation

Certo is a coding-agent harness that doesn't depend on one model or one
provider. It runs coding tasks on any model, local or cloud, can pick the
best model for each task, and hands a task to the next model when one
can't finish or its provider goes down. You give it a task. An agent
plans, edits files and runs commands until it says it is done. Then Certo
runs your project's real tests and build itself, with no AI involved, and
tells you if the work is really verified. That verdict is also how Certo
knows when to switch: it decides when a model's work is good enough, and
when to hand over.

This page explains what Certo is and where to read next.

## Why Certo exists

Models differ, and they change. One is cheap and good enough for most
tasks, another is needed for the hard ones, a third runs on your own
machine and keeps your code there. Providers go down, rate-limit you, or
reject a key. An agent built around one model or one provider inherits all
of that. Certo treats the model as one setting, and can move a task to
another model when the first one fails. For example, in Certo's own
[escalation benchmark](benchmark/escalation-0.1.17.md), a local
`qwen3.8:27b` with `claude-haiku-5-5` as the next model passed all 9
tasks, and 7 of them never left the machine.

Switching only works if something reliable says when a model failed, and
that can't be the agent itself. Coding agents are confident,
and often wrong about being finished. While
building Certo, an agent wrote a Tower of Hanoi game. Every unit test
passed. The game crashed the moment a player chose "solve". The agent said
the work was done, and so did the test runner.

Certo is built to catch that. When the agent stops, Certo:

1. runs the project's own checks (tests, build, lint, type checks) itself;
2. sends real failures back to the agent for another attempt;
3. stops early when a fix attempt changes nothing;
4. prints one verdict, such as `verified` or `retry_exhausted`, and exits
   with a code that scripts and CI can use.

The stories behind each of these checks are in
[Why agents lie](concepts/why-agents-lie.md).

## What Certo can do

- Work with almost any model: OpenAI, Anthropic, Google Gemini, DeepSeek, Kimi, Ollama on
  your own machine, or any model that [LiteLLM](https://docs.litellm.ai/docs/providers)
  supports. Switching is one setting.
- Pick the best model for each task from a list you write, and fall back to
  the next one when a provider fails: `--auto-model`.
- Move a task to the next model of a ladder when Certo's verification
  shows the model couldn't finish, or when its provider fails:
  `--escalate`.
- Verify Python, Node/JavaScript/TypeScript, Go, Rust and Java projects.
- Check a project with no agent and no model at all: `certo verify`.
- Enforce limits: an iteration cap, a time budget, and an optional "approve
  every action" mode.
- Run the agent in a Docker container, or as an HTTP server.
- Keep a record of each run: the full transcript, tokens and cost.
- Resume a task that was interrupted or failed, with the agent's earlier
  conversation: `certo --resume`.
- Go back to an earlier point of a run, before the agent or after any fix
  attempt: `certo rollback`.
- Benchmark models on bundled tasks graded by hidden tests: `certo bench`.

## Where to go next

**New to Certo?** Start with [Getting started](getting-started.md). It
takes you from install to your first verified project.

**Want to do one specific thing?** Pick a guide:

| I want to... | Guide |
|---|---|
| Write a task the agent gets right, and Certo can check | [Write a task Certo can check](guides/write-a-good-task.md) |
| Know what to do after a verdict | [What to do after each verdict](guides/after-the-verdict.md) |
| Use OpenAI, Claude or Gemini | [OpenAI, Claude and Gemini](guides/openai-claude-gemini.md) |
| Use a model on my own machine | [Ollama and local models](guides/ollama-and-local-models.md) |
| Pick which local model to use | [Choose a local model](guides/choose-a-local-model.md) |
| Let the agent work on a project I already have | [Work on an existing project](guides/work-on-an-existing-project.md) |
| Answer the agent's questions, or approve each action | [Interactive and confirm mode](guides/interactive-mode.md) |
| Let Certo choose the model for each task | [Pick models automatically](guides/pick-models-automatically.md) |
| Hand a task to the next model when one can't finish, or its provider fails | [Escalate between models](guides/escalate-between-models.md) |
| Decide between automatic model choice and escalation | [Auto-model or escalation](concepts/auto-model-or-escalation.md) |
| Set up my project so Certo can check it | [Make your project checkable](guides/make-a-project-checkable.md) |
| Check projects in CI | [Verify in CI](guides/verify-in-ci.md) |
| Check my work before each commit | [Verify before every commit](guides/verify-before-commit.md) |
| Add my own pass/fail rules for a task | [Acceptance checks](guides/acceptance-checks.md) |
| Check the work with tests written before the build | [Independent tests](guides/independent-tests.md) |
| Run the agent inside a container | [Run in Docker](guides/run-in-docker.md) |
| Call Certo over HTTP | [Run as a server](guides/run-as-a-server.md) |
| See what a run did and what it cost | [Run records and costs](guides/run-records-and-costs.md) |
| Continue a task after an interruption or a failed verdict | [Resume an interrupted run](guides/resume-a-run.md) |
| Build something bigger in steps, each checked before the next | [Run a task in milestones](guides/run-in-milestones.md) |
| See a whole app built that way, step by step | [Build an app in several tasks](guides/build-an-app-in-several-tasks.md) |
| Undo what the agent did, back to an earlier point | [Go back to an earlier point](guides/checkpoints.md) |
| Teach the agent my conventions, for every project or one | [Manage skills](guides/manage-skills.md) |
| Give the agent a new action, in Python | [Add custom tools](guides/add-custom-tools.md) |
| Try the same task on several models, side by side | [Compare models on one task](guides/compare-models-on-a-task.md) |
| Measure which models and strategies really deliver | [Benchmark models and strategies](guides/benchmark.md) |
| Set up my own benchmark file | [Write a benchmark file](guides/write-a-benchmark-file.md) |
| Benchmark my own tasks, or add one to Certo's set | [Write or contribute a benchmark task](guides/contribute-a-benchmark-task.md) |
| See how Certo did on its own benchmark | [Baseline 0.1.23](benchmark/baseline-0.1.23.md), [0.1.22](benchmark/baseline-0.1.22.md), [0.1.18, local](benchmark/baseline-0.1.18-local.md), [0.1.15](benchmark/baseline-0.1.15.md) (and [0.1.13](benchmark/baseline-0.1.13.md)), [escalation in 0.1.17](benchmark/escalation-0.1.17.md), [one escalation run](benchmark/escalation-wordle-0.1.19.md), [escalation past a provider failure](benchmark/escalation-provider-failure-0.1.22.md), [escalation past failing tests](benchmark/escalation-handoff-0.1.23.md), [the Haiku → Sonnet ladder in 0.1.25](benchmark/ladder-haiku-sonnet-0.1.25.md), [condensing on a local model at 32K in 0.1.25](benchmark/context-0.1.25.md), [the testable-interactive-apps skill in 0.1.26](benchmark/interactive-0.1.26.md), [the python-environment and node-project-setup skills in 0.1.27](benchmark/setup-skills-0.1.27.md), [the `unchanged` verdict live in 0.1.27](benchmark/unchanged-live-0.1.27.md), [`--resume` after Ctrl-C in 0.1.27](benchmark/resume-after-ctrl-c-0.1.27.md), [the first milestone runs in 0.1.27](benchmark/milestones-live-0.1.27.md), [milestones against one go on a local model in 0.1.27](benchmark/milestones-0.1.27.md) ([with a larger window](benchmark/milestones-64k-0.1.27.md), [with a handover between milestones](benchmark/milestones-handover-0.1.27.md)), [tool-call reminders in 0.1.26](benchmark/reminders-0.1.26.md), [independent tests on saved projects](benchmark/independent-tests-replay-0.1.24.md), [the test writer's expected values in 0.1.25](benchmark/writer-arithmetic-0.1.25.md), [independent tests in live runs](benchmark/independent-tests-live-0.1.24.md), [check files changed by benchmark runs](benchmark/check-file-changes-0.1.24.md), [provider swap in 0.1.19](benchmark/provider-swap-0.1.19.md), [first run with two models in 0.1.21](benchmark/first-run-auto-model-0.1.21.md), [five models build an Asteroids-style game](benchmark/compare-asteroids-0.1.19.md) |

**Looking something up?** The reference pages are complete and exact:

- [Commands](reference/commands.md): every command, subcommand and flag.
- [Configuration](reference/configuration.md): every setting, its default,
  and where Certo reads it from.
- [Verdicts](reference/verdicts.md): every verification state and its exit
  code.
- [Verification by language](reference/verification-by-language.md): what
  Certo runs for each kind of project.
- [The model files](reference/models-yaml.md): the model
  list, your personal model settings, the task profiles and the
  escalation ladders, for automatic model selection, escalation and the
  benchmark.
- [bench.yaml](reference/bench-yaml.md): the benchmark file.
- [Server API](reference/server-api.md): every HTTP and WebSocket endpoint.

**Curious how it works?**

- [How verification works](concepts/how-verification-works.md)
- [Auto-model or escalation](concepts/auto-model-or-escalation.md)
- [Why agents lie](concepts/why-agents-lie.md)
- [Safety](concepts/safety.md)

**Have a question?** See [Questions and answers](questions-and-answers.md):
how handoff decides, what the next model gets, and verdicts in CI.

**Something went wrong?** See [Troubleshooting](troubleshooting.md).

## Experimental features

Five features are **experimental**: they work and have tests, but haven't
been proven in real use the way the core has (verification, escalation and
the benchmark). Use them, report what breaks, and expect them to change
between minor versions. Fixes to the core come first.

| Feature | What isn't proven yet |
|---|---|
| [Docker execution](guides/run-in-docker.md) (`--execution docker`) | Verification has never run inside a real container, only in tests with a fake workspace. The image must be built from a source checkout. Automatic model selection can't switch models during a run. |
| [Server task stores](guides/run-as-a-server.md#keep-task-records) other than `memory` (`sqlite`, `mysql`, `postgres`, `redis`) | `sqlite` is tested on a real file. `mysql` and `postgres` share its code and were checked live once, not in the test suite. `redis` is tested only where `redis-server` is installed. |
| [The OpenAI-compatible endpoint](guides/run-as-a-server.md#use-it-from-an-openai-compatible-client) (`/v1/chat/completions`) | The answer has no verdict, and earlier messages aren't replayed. |
| [Milestone mode](guides/run-in-milestones.md) (`--milestones`) | Not benchmarked yet, not in server mode or `certo bench`, and Certo doesn't plan the milestones itself. A climb inside a milestone hasn't been seen live. |
| [Skills downloaded from git](guides/manage-skills.md#download-a-skill-from-git) (`certo skills add github:...`) | Licenses are detected with a text match, only `SKILL.md` folders can be installed, and no third-party skill has been benchmarked. |

The rest of server mode (`POST /tasks`, the WebSocket stream, the memory
store) is not experimental, but has no authentication: see the first
limitation below.

## Known limitations

- **Server mode has no authentication.** Run it on `127.0.0.1` or behind
  your own gateway. See [Safety](concepts/safety.md#server-mode).
- **Verification only knows what the checks test.** Untested features can
  be broken and still `verified`, and interactive menus are never
  exercised. See [How verification works](concepts/how-verification-works.md#what-verification-cant-do).
- **Some rules are only instructions to the model**, such as writing a
  `README.md` or not asking questions. A model can ignore them.
- **Covered languages:** Python, Node, Go, Rust and Java. Other projects,
  and standalone HTML pages, end `inconclusive`. Java needs Maven or Gradle
  installed. See [Verification by language](reference/verification-by-language.md).
- **Windows file permissions:** settings files inherit the folder's access
  permissions. Certo does not set Windows ACLs; Unix permission `600` applies
  only on macOS and Linux. See [Safety](concepts/safety.md#secrets).
- **Docker mode is experimental** (see above): it needs an image built
  from a source checkout, and automatic model selection can't switch
  models in the middle of a Docker run. See [Run in Docker](guides/run-in-docker.md).
- **Some local models do no work on some setups**: they write their tool
  calls as plain text, and the run ends at once. `certo check` tests for
  it. Which models worked in Certo's benchmark:
  [Choose a local model](guides/choose-a-local-model.md).
- **Certo doesn't run while OpenHands plugins would load.** If you use
  OpenHands itself and keep plugins in `~/.agents/plugins/` or
  `~/.openhands/plugins/`, move them aside while you use Certo. See
  [OpenHands plugins](guides/manage-skills.md#openhands-plugins).
- **Costs show as unknown** for models newer than your installed LiteLLM.
- **New, empty folders:** the agent starts with a Python environment only
  if the task mentions Python (or a Python tool such as pytest). Otherwise
  packages the agent installs may land outside the project's environment,
  and imports can fail during verification until they are installed again.
- **A test runner Certo doesn't recognise counts "no tests" as a pass**
  when it exits successfully. `node --test`, Jest, Vitest, pytest, Go and
  Cargo are recognised. See
  [Verification by language](reference/verification-by-language.md#node-in-detail).
- **Escalation climbs only on a verification signal or a provider
  failure.** In a project with nothing to check, each rung ends
  `inconclusive`: the task moves to one more model, then the climb stops.
  In Docker mode a provider failure can't be told apart from another run
  error. See [Escalate between models](guides/escalate-between-models.md).
- **Resume in Docker mode starts a new conversation**: the agent gets the
  task, Certo's status record and the files, but not its earlier
  conversation. See [Resume an interrupted run](guides/resume-a-run.md#when-the-conversation-cant-be-resumed).
- **A task that is exactly the name of an existing file** in the current
  folder is read from that file.
- **Interactive mode covers only the first part of a task**, and neither it
  nor confirm mode works in server mode. See
  [Interactive and confirm mode](guides/interactive-mode.md).
- **The OpenAI-compatible endpoint** is experimental: it returns no
  verdict and doesn't replay chat history. See [Run as a server](guides/run-as-a-server.md#use-it-from-an-openai-compatible-client).
- **Skills downloaded from git** are experimental. Their licenses are
  detected with a simple text match, and only `SKILL.md` folders can be
  downloaded. See
  [Manage skills](guides/manage-skills.md#download-a-skill-from-git).

## For contributors

How to work on Certo itself, run its tests and make a release is in
[CONTRIBUTING.md](../CONTRIBUTING.md). Where the project is going is in
[ROADMAP.md](../ROADMAP.md), what's left to do in [TODO.md](../TODO.md),
and the reasons behind design decisions in
[DECISIONS.md](../DECISIONS.md). The
original build plan is [SPEC.md](SPEC.md).
