# TODO

Everything still to do, so nothing is forgotten. One entry per item: what,
why, and when it counts as done. Where Certo is going, and why these
items, is in `ROADMAP.md`; why past choices were made is in `DECISIONS.md`.

> **Maintenance note:** add an item the moment it is found (a bug, a
> deferred step, an idea). When it is done, delete it in the same change,
> and record the decision in `DECISIONS.md` if it was a non-obvious one.
> Git history and the release notes keep what was done. See `CLAUDE.md`.

Sections follow the themes in `ROADMAP.md`. Inside each section, the
first item is the suggested next one.

## Before the next release

- **A small `certo bench` run of the Haiku → Sonnet ladder**, so the
  README can drop one "not benchmarked yet"
  ([#24](https://github.com/alessioricco/certo/issues/24), open for
  contributors).
- **Run the new sample tasks on a local model.** `hanoi.md`,
  `mazeman.md`, `invaders.md` and `space-rocks.md` each ended `verified`
  once on `claude-sonnet-5-5` (2026-10-21, 37s to 2m34s, $0.11 to $0.43),
  but were never run on a local model, so on Ollama the menu quotes only
  Wordle's time. Run each on `qwen3.8:27b`, fix any spec that doesn't end
  `verified`, and record the times in `init_cmd.py`. Done when each one
  has ended `verified` locally and the menu quotes a local time.
- **Check the arrow-key menus by hand in a real terminal.** The tests
  drive them through a pipe, and a pseudo-terminal run worked, but
  neither shows what a person sees. In `certo init` and `certo init
  models`, check by hand:
  - the ▸ symbol, the highlight and the grey notes look right with your
    font and colours (light and dark theme);
  - the checklist redraws cleanly when it's taller than the window, and
    after the window is resized;
  - the keys work over SSH (for example on turing.local) and inside
    tmux;
  - no "your terminal doesn't support cursor position requests (CPR)"
    warning. A pseudo-terminal that doesn't answer CPR prints it; if a
    real terminal does too, hide it (prompt_toolkit's
    `PROMPT_TOOLKIT_NO_CPR=1`).

  Done when each is checked, or fixed.
- **A baseline per release.** `docs/benchmark/baseline-<version>.md` for
  every release (local vs cloud, fooled rate, cost per solved task), and
  a README badge. 0.1.13, 0.1.15 and 0.1.18 (local only) exist; no badge
  yet. A `qwen2.5-coder:7b` arm would replace "unmeasured" for the
  small-machine suggestion ([#18](https://github.com/alessioricco/certo/issues/18) asks contributors for local runs).
- **Bench task set v2: app-scale tasks.** Multi-file, multi-language: Go
  REST API with a database, React frontend + API, Rust CLI with
  subcommands, a fix inside an existing mid-size repo. Grading supports
  only Python and Node, with no packages, so Go/Rust tasks need grading
  support first. Bump the task-set `VERSION`. Today's 9 tasks don't
  separate a local 27B model from a cloud one. Contributed tasks in the
  current format help meanwhile: [#3](https://github.com/alessioricco/certo/issues/3).
- **Escalation after a `failed` rung is unmeasured.** The 0.1.17
  escalation run climbed 10 times, all past a model that did no work.
  Climbing after a failed verification, the handoff of half-done work and
  derived-ladder ordering are still unmeasured. Needs task set v2. Candidate ladder from the
  0.1.15 local benchmark: `qwen3.8-27b-local` → `gemma4-31b-qat-local` →
  a cloud model (qwen3.8 is about 3× faster; gemma never wrote tool calls
  as text, qwen3.8's only failure mode). Bench it as three arms: each
  model alone, and the ladder.
- **Re-verify the "confident but wrong" fixes live**: #1, #3, #5, #10
  and #6 for Java in `ARCHITECTURE.md` say "not re-verified live" (#2, #4
  and #6 for Go/Rust were, 2026-10-19). #1 and #5 are hard to trigger on
  purpose; #10 is reachable from a benchmark task.
- **Move the historical planning docs into `docs/history/`**
  (`docs/KICKOFF.md`, `docs/SPEC.md`, `docs/ROADMAP.txt`), so readers
  don't take them for current docs; fix every reference. Starter issue:
  [#4](https://github.com/alessioricco/certo/issues/4).
- **Docker verification has never run against a real container**, and
  neither has escalation under Docker. Fake-workspace tests only.

## 2. Complex tasks

- **Milestone mode.** Split a big task into milestones, each with its own
  acceptance checks, run and verified one at a time, building on
  `--resume`/`STATUS.md`. The main step from "small task" to "app".
- **Independent acceptance tests from the spec.** Before building, a
  separate conversation (optionally another model) writes tests from the
  task text only; the builder may not edit them. Brings the benchmark's
  hidden-test idea to real runs. Agreed 2026-10-22: the first version is
  opt-in and report-only (the results are shown next to the verdict but
  don't change it), written by the same model by default, another model
  as an option. The verdict rule is decided later from the benchmark:
  how often these tests catch a real bug, and how often they are wrong.
- **Protect verification files from silent agent changes.** The agent can
  weaken or delete tests, build scripts or lint config before Certo
  verifies; only prompts discourage it (golden rule 6 gap). Record those
  files before the run, compare after, and report or reject changes the
  task didn't ask for. Needs a policy for legitimate test changes.
- **Context management for long runs.** The SDK's own condensing
  (verify-first), plus a warning when a local model's context window is
  too small for the task (qwen3.8 at 32K).
- **Checkpoints and rollback.** A git snapshot per fix attempt and per
  escalation rung, so a bad attempt can be undone.
- **Escalation "restart" mode.** Copy the original files back before the
  next rung, instead of continuing in the same files.
  `_stream_escalation` already lists the workspace before each rung.

## 3. Languages and verification

- **Finish Windows test-suite support** ([#7](https://github.com/alessioricco/certo/issues/7),
  reported in #6). Python environment discovery, dependency installation
  and verification now handle Windows virtual environments. The suite still
  has Windows failures involving path comparisons, Unix permissions,
  symlink privileges and shell wrappers. Done when the suite passes on
  Windows and the Known limitations line in `docs/README.md` can go.
- **Run-the-app verification.** Start a server and probe an HTTP
  endpoint; build a frontend and load it in a headless browser (the SDK
  ships a browser tool) for a blank page or console errors.
- **Node: "no tests" counts as verified.** `node --test` exits 0 with no
  test files, so `npm test` passes. Found by the first bench integration
  run (2026-10-16). Documented, not fixed. Open for contributors:
  [#23](https://github.com/alessioricco/certo/issues/23).
- **Node: detect jest/vitest/mocha.** Today `build`/`test` scripts run as
  opaque commands; the runner and its results aren't parsed.
- **Node: infer ESLint/`tsc` from config**, as `_ruff_configured()` does
  for Python. Flat-config variants make this harder than the Python case.
- **Java: a Maven/Gradle toolchain** in the Docker image and the dev
  environment. Java is detection-only in both today.
- **New ecosystems**, in order: C#/.NET, PHP (Composer), Ruby, Kotlin/
  Android (Gradle), C/C++ (CMake), Swift. Open for contributors: Ruby
  [#19](https://github.com/alessioricco/certo/issues/19), PHP [#20](https://github.com/alessioricco/certo/issues/20), .NET [#21](https://github.com/alessioricco/certo/issues/21), Swift [#22](https://github.com/alessioricco/certo/issues/22).
- **Interactive programs can't be driven** (menus, `SOLVE`-style choices).
  Deliberately not built: no safe general way to guess input. Would need
  the agent to declare an interaction script. Keep as a known gap unless
  a design appears.

## 4. Models and strategies

- **Live check of the auto-model quality fallback.** The provider-failure
  switch ran live on 2026-10-19 (ARCHITECTURE.md). The other path, a fix
  attempt that still fails the checks, has only run against a fake; it
  needs a model that fails on purpose, so it may take a few tries.
- **A `certo bench` strategy for `--auto-model`.** Only `single` and
  `escalate` exist (`bench_strategies.py`), so the README can say auto-model
  is unmeasured but not show a number. Add an `auto` strategy (task
  profiles plus fallback, as the CLI runs it) and bench it next to the
  single models and a ladder.
- **Tool calls written as text.** In the 0.1.15 local benchmark, every
  failed `qwen3.6` and `qwen3.8` run and 18 of 22 failed `devstral` runs
  ended because the model wrote its tool call as JSON in a text answer;
  the SDK took it as the final message. First find the cause (Ollama chat
  template, or context too small for the tool definitions): rerun one
  task with a known `OLLAMA_CONTEXT_LENGTH`. Then consider a harness fix:
  when the final message parses as a tool call, send it back once as a
  correction. Gated by tier or opt-in, and benchmarked local and cloud.
- **Record the Ollama setup in bench results.** `meta.json` has no Ollama
  version or context length, so a local result can't be traced to the
  setup (`/api/version`, `/api/ps`). Done when the report shows both.
  Starter issue: [#5](https://github.com/alessioricco/certo/issues/5).
- **Slow local models lose correct work to the time budget.** Three runs
  in the 0.1.15 local benchmark passed the hidden tests but ended
  `budget_exhausted`. Since 0.1.22 the checks run once when the last run
  ends after the budget, so passing work is `verified`. Left:
  - **The budget can't stop a run in progress.** It is checked only
    before each `.run()`; one run makes up to 50 model calls, each up to
    `CERTO_LLM_TIMEOUT_SECONDS` × 6 attempts (the SDK retries timeouts 5
    times). `devstral` `token-bucket` r3 (timeout 1200s) wrote its files
    in the first 6 minutes, then spent ~50 on 4 calls: 57 minutes in all.
    Unproven: bench transcripts have arrival times since 0.1.22, so the
    next slow run will show where the time went.
    Fix by pausing the conversation at the deadline (SDK
    `conversation.pause()`, verify first) and capping the per-call
    timeout at the time left.
  Also consider a per-arm budget in `bench.yaml`.
- **Bench estimates from recorded cost.** The plan prices every run at a
  fixed ~500k input / ~20k output tokens (far too high: a cloud run used
  ~124k in the baseline). Use the per-model average from earlier
  `cost.json` files in the same parent folder; guess only for models with
  no history. Starter issue: [#10](https://github.com/alessioricco/certo/issues/10).
- **A cost ceiling for single-model runs.** `CERTO_MAX_TASK_COST`
  applies to escalation only (checked before each rung), and bench has
  `--max-cost`; a plain run is bounded by time and iterations, not money.
  The conversation's metrics carry the running cost, so it could be
  checked between retries, ending in a new verdict.
- **Bench strategy `best_of`**: N attempts, the verifier picks. Next entry
  in `bench_strategies.STRATEGIES`. Benchmark on local and cloud before
  release.
- **Per-tier tuning for small models.** Shorter prompts and stricter
  tool-call repair, gated by model tier and measured on both tiers.
- **`certo doctor` for Ollama**: model pulled, context size, thinking
  mode, measured tokens per second.
- **Measured speed and context in the catalog**, filled from real runs,
  so ladders can weigh speed. A `speed` rating would count as capability
  today.
- **Auto-model: a quality failure falls back to the next-best fit, not a
  more capable model.** Escalation (0.1.9) answers this for `--escalate`;
  `--auto-model`'s chain still walks one ranked-by-fit list. Decide
  whether auto-model should climb by capability on a verification
  failure, or point users to `--escalate`.
- **Auto-model: no mid-task fallback under Docker.** `RemoteConversation`
  has no public `switch_llm`. Revisit when the SDK adds one.
- **Auto-model: switching to a model with a smaller context window**
  surfaces as a context-overflow error (which then falls through to the
  next candidate). A condenser, or ordering to avoid it, would be cleaner.
- **Auto-model: per-sub-step model choice** (a cheap model for
  scaffolding, a strong one for the hard part), hooked on `task_tracker`
  items. Needs interrupting a run mid-call; open design.
- **Other SDK reasoning fields** (`reasoning_summary`,
  `extended_thinking_budget`, `enable_encrypted_reasoning`): left unwired
  on purpose (provider-specific). Only if a provider needs one.

## 5. Adoption

Walked through as a new user on 2026-10-20 (certo 0.1.20 from PyPI, an
empty home folder, Ollama on another machine). `certo init` took 16s and
the first task, Wordle, ended `verified` in 11m 49s. What got in the way
is in the first item and in "Smaller bugs". (The quieter run, 0.1.21,
cut that first run's output from 2,949 lines to 1,021.)

- **A first run in minutes, with one model.** No catalog, no ladders:
  `certo init`, then a first verified project. Getting started shows only
  that path. Measured 2026-10-19 in an empty home folder: 88.5s from
  `uv tool install` to `verified` (`docs/benchmark/first-run-0.1.19.md`).
  Still to do: a truly clean machine (no Python, no uv).
- **GitHub Action**: an issue labelled `certo` becomes a pull request with
  the verdict and checks in its description.
- **Docs articles still to write** (ideas from 2026-10-18): build an
  app in several tasks (needs real runs); review the agent's work safely;
  share your benchmark results (with the benchmark file, as `docs/benchmark/` does); keep costs down; use `certo verify`
  without the agent (pre-commit, any AI tool: starter issue
  [#13](https://github.com/alessioricco/certo/issues/13)).
- **Prebuilt Docker image.** Docker execution from a pip install fails:
  `workspace.py` builds from `docker/agent-server.Dockerfile` relative to
  the repo, which isn't in the wheel. Ship the Dockerfile and tool source
  as package data, or publish an image. Documented in
  `docs/guides/run-in-docker.md`.
- **A secret manager for keys** (an idea, 2026-10-20). Keys live only in
  the settings file for now. Later, read them from the system keychain
  or a secret manager (1Password, Bitwarden, a cloud vault) instead.
  Decide which, and how a key is named, when someone asks for it.
- **MCP server**, so Claude Desktop, Cursor, Zed and others can call Certo
  as a tool and get the verdict back.
- **Run report**: an HTML/Markdown summary per run (what changed, which
  checks ran, cost, why the verdict), from the existing artifacts.
- **Live progress view** in the terminal: current milestone, last check,
  cost so far.
- **Docs website and gallery**: a site generator for `docs/`, a gallery of
  apps built with Certo (verdict and cost each), a short demo video.

## 6. Server mode

- **No authentication.** Bound to `127.0.0.1` by default, but with
  `--host` every endpoint is open: `POST /tasks` runs an agent with a
  terminal (shell access on the host), and requests may override
  `api_key`/`base_url` with no validation. Minimal fix: a shared-secret
  header (e.g. `CERTO_SERVER_API_KEY`) checked on every task route, and a
  loud docs warning against a public `--host` without it.
- **`/v1/chat/completions` has no verdict.** Its wire format has no field
  for `verification_state`, so a caller gets the agent's own claim only.
  Needs a deliberate wire-format choice (a custom field, or a trailing
  message).
- **`/v1/chat/completions` always reports zero token usage**, although
  the conversation's metrics have the counts.
- **`model_decisions` isn't on `GET /tasks/{id}`.** The SQL stores need a
  new column; the `rungs` column (0.1.9) already shows how
  (`ALTER TABLE ... ADD COLUMN` on startup).
- **No way to list tasks or projects** in a task store (`certo-admin`,
  REST): every operation needs a known id or project name.
- **ECS/EC2 or other remote execution backends.** `build_workspace()` is
  the single dispatch point. No concrete need yet.

## 7. Built-in skills to make

Rules for every new skill: short and narrowly triggered (prefer `paths:`
triggers; every skill that fires costs context a 32K local model can't
spare); measured with `certo bench` on a local and a cloud model before
release; authored for Certo in the legacy `triggers:`/`paths:` format.
Today there are 12 (eight `lifecycle/`, `git/commit-conventions`,
`python-web/fastapi-conventions` and `pin-dependencies`,
`testing/pytest-conventions`).

**Make a project verifiable** (first; suggested order: the first three):
- `testable-interactive-apps`: logic apart from input/output, so games
  and menus are testable. Triggers: game, interactive, menu, terminal.
- `python-environment`: use the project's `.venv`; never install into
  Certo's interpreter or with `pip install --user`; declare dependencies
  in `pyproject.toml` first.
- `node-project-setup`: a real `test` script with at least one test, a
  `build` script, a committed lockfile, no interactive scaffolders.
- `cli-entry-points`: `__main__` guard last, a closed stdin doesn't hang,
  `--help` and non-interactive flags work.
- `test-oracles`: derive expected values independently, never from the
  implementation's output; check a suspicious test against its own setup
  before re-editing correct code. Maybe a section of
  `lifecycle/testing-and-verification` instead.

**Languages** (path-triggered, one per verified ecosystem): Go (`go.mod`),
Rust (`Cargo.toml`), Java (commit the wrapper),
TypeScript (`tsc --noEmit` as a `typecheck` script), Python (extend
`pytest-conventions` with ruff/mypy setup); new ecosystems get one when
their verification lands.

**Frameworks** (each with a recipe to build, test and smoke-check):
Vite/React, Next.js, Express, Django, FastAPI (extend
`fastapi-conventions`), Spring, Rails, Laravel.

**App building blocks**: `http-api-testing` (the framework's test client,
no real network), `database-basics` (SQLite, migrations, an isolated test
database).

## Smaller bugs

- **Stop reading `task_profiles:` / `escalation:` in `models_list.yaml`.**
  Since 0.1.20 they have their own files; the old sections are still read
  with a warning. Remove that path (and the tests that use the old layout
  through `write_model_files`) a version or two later.
- **Third-party skills: narrow license detection, `SKILL.md` only.** Eight
  permissive licenses are recognised; anything else is `unknown` and needs
  acknowledgement. Legacy single-file upstream skills can't be installed.
  Fine for now; revisit if people use the feature.
