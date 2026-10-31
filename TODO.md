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

- **A longer time budget from `certo init` for Ollama?** The mazeman
  sample took 41 minutes on `qwen3.8:27b` (2026-10-22), past the default
  30-minute `CERTO_MAX_TASK_SECONDS`; it ended `verified` only because the
  checks now run once after the budget, with no time left for a fix
  attempt. Decide whether init writes a longer budget for Ollama (as it
  does the 1200s call timeout). Measured 2026-10-26
  (`docs/benchmark/budget-0.1.25.md`): 60 minutes solved 2/8 of the
  larger tasks against 3/8 with 30; the only right work the budget
  stopped had no tests. Not shown to help; the Author decides.
- **Baselines, when the Author chooses.** `docs/benchmark/baseline-<version>.md`
  (local vs cloud, fooled rate, cost per solved task), run when the
  Author decides; minor releases may skip it (2026-10-23). Also a README
  badge. 0.1.13, 0.1.15, 0.1.18 (local only), 0.1.22 and 0.1.23 (the
  first on task set v2) exist; no badge yet. A `qwen2.5-coder:7b` arm would replace "unmeasured" for the
  small-machine suggestion ([#18](https://github.com/alessioricco/certo/issues/18) asks contributors for local runs).
- **Bench tasks that separate cloud models.** Task set v2 separates
  `qwen3.8` from the cloud models (7 of 12 on the four larger tasks,
  against 4 of 4 each) but not the cloud models from each other: all
  three passed 13 of 13 (`docs/benchmark/baseline-0.1.23.md`). Harder
  tasks would. They are also what a cloud ladder needs to show its
  worth: in the 0.1.25 Haiku → Sonnet run Haiku solved all 13, so the
  ladder never climbed (`docs/benchmark/ladder-haiku-sonnet-0.1.25.md`). Contributed tasks in the current format help:
  [#3](https://github.com/alessioricco/certo/issues/3).
- **Escalation after a `failed` rung is unmeasured.** The 0.1.17
  escalation run climbed 10 times, all past a model that did no work.
  Climbing after a failed verification, the handoff of half-done work and
  derived-ladder ordering are still unmeasured as a benchmark; one
  recorded run of a half-done handoff exists
  (`docs/benchmark/escalation-handoff-0.1.23.md`, tests in the folder
  from the start). Needs task set v2. Candidate ladder from the
  0.1.15 local benchmark: `qwen3.8-27b-local` → `gemma4-31b-qat-local` →
  a cloud model (qwen3.8 is about 3× faster; gemma never wrote tool calls
  as text, qwen3.8's only failure mode). Bench it as three arms: each
  model alone, and the ladder.
- **Re-verify the "confident but wrong" fixes live**: #1, #3, #5, #10
  and #6 for Java in `ARCHITECTURE.md` say "not re-verified live" (#2, #4
  and #6 for Go/Rust were, 2026-10-19). #1 and #5 are hard to trigger on
  purpose; #10 is reachable from a benchmark task. Also never seen live:
  a climb inside a milestone (`--milestones --escalate`), and
  `--resume` after Ctrl-C mid-run.
- **Move the historical planning docs into `docs/history/`**
  (`docs/KICKOFF.md`, `docs/SPEC.md`, `docs/ROADMAP.txt`), so readers
  don't take them for current docs; fix every reference. Starter issue:
  [#4](https://github.com/alessioricco/certo/issues/4).
- **Docker verification has never run against a real container**, and
  neither has escalation under Docker. Fake-workspace tests only. Open
  for a report: [#34](https://github.com/alessioricco/certo/issues/34).

## 2. Complex tasks

- **Milestone mode.** Split a big task into milestones, each with its own
  acceptance checks, run and verified one at a time, building on
  `--resume`/`STATUS.md`. The main step from "small task" to "app". The
  Author's decisions and the design are in DECISIONS.md (2026-10-25,
  2026-10-29). Steps 1 and 2 are built (0.1.27,
  `--milestones`, with `--escalate` and independent tests per milestone;
  live Haiku runs only, no climb inside a milestone seen live yet).
  Step 3 is built (bench arm `milestones: true`, `app-tasks/spreadsheet`);
  its first local run (`docs/benchmark/milestones-0.1.27.md`) solved
  neither arm: in one go qwen3.8 gave only empty replies, in milestones
  it built milestone 1 and ran out of time on milestone 2. The second
  run (`docs/benchmark/milestones-64k-0.1.27.md`, 64K window, 40 min per
  milestone): milestones 1-2 `verified` in 2/3 runs, then out of time
  planning milestone 3; one go wrote the whole engine in 2/3 runs (87
  and 100/111 hidden) but no tests. Next: carry a short summary of the
  code into each new milestone (done 2026-10-30: the handover; its qwen
  run, `docs/benchmark/milestones-handover-0.1.27.md`: milestones 1-2
  `verified` in 3/3, 127/333 hidden against 85; milestone 3 failed by
  time once and twice on tool calls written as text in shapes the
  detector missed, now recognised), and
  a longer per-call limit for this model (7 calls hit 1200 s); with the
  next `apps-` version, say in the task that a chain of 200 cells must
  work (hidden `test_m2_a_long_chain` is stricter than the text). The
  docs article is written (`docs/guides/build-an-app-in-several-tasks.md`,
  Haiku 5/5 verified, 111/111 hidden). Then (5) Certo planning the
  milestones itself.
  A fourth run, 60 minutes per milestone and the new tool-call shapes,
  started 2026-10-31 09:12 (`bench-results/milestones-60min-0.1.27`,
  config `docs/benchmark/bench-0.1.27-milestones-60min-local.yaml`).
  Done when an app-sized task ends `verified` in milestone mode on a
  local model, with a published record. Closing it closes the project
  review's plan; the next release is then 0.2 (the Author, 2026-10-31).
- **A harder app task** (`app-tasks`, next `apps-` version). Haiku and
  Sonnet both pass the spreadsheet 111/111 in one go, so it doesn't
  separate cloud models: a task that does would show the ladder climbing
  for a reason and the fooled rate on app-scale work. Done when one
  cloud model fails it in one go and another passes.
- **Independent tests: the rest** (0.1.24: `--independent-tests`, three
  sets by default with a 2-of-3 vote, report only; replay in
  `docs/benchmark/independent-tests-replay-0.1.24.md`). Live Haiku arm
  done 2026-10-25 (`docs/benchmark/independent-tests-live-0.1.24.md`: 1
  of 38 right runs failed, by a wrong test; ~34 s to write per run; cost
  about doubled). The writer's wrong sums are fixed (0.1.25: it writes
  the calculation in the test; `docs/benchmark/writer-arithmetic-0.1.25.md`).
  Left: (1) tests that misread the task still turn up in some runs (0
  to 7 of 65 sets); (2) server mode; (3) maybe an option for a different
  writer model than the build's. (A 2-of-3
  failure changes the verdict only with `--independent-tests-strict`,
  0.1.25.) The `qwen3.8` replay
  (2026-10-25) caught 2 of 8 fooled runs with the vote (Haiku: 7 of 8),
  and the Author keeps qwen away from high-effort work, so its own tests
  aren't the answer for local users.
- **`room-bookings` hidden test is stricter than the task** (2026-10-25,
  live Haiku arm). A `204` sent with `Content-Type: application/json`
  and no body fails the hidden tests (they parse any JSON-marked
  response), though the task only says "`204` with no body". One fooled
  run of 39 came from it. Either say it in the task or skip parsing an
  empty body in the hidden test; both change the task set's hash, so do
  it with the next task-set change.
- **Find the best use of local models for coding.** The Author doesn't
  know yet what `qwen3.8` is best at among Certo's coding activities
  (not high-effort ones such as writing independent tests). Look for it
  in the benchmark results before building more local-only features.
- **Changed check files: decide again with new data** (0.1.24 lists
  them after a `verified` run, report only). On 379 saved bench runs
  (2026-10-25, `scripts/count_check_file_changes.py`) no run removed a
  test line or deleted a test, and the 8 fooled runs changed no check
  file, so there is nothing yet to justify a verdict change. Re-run the
  count after each baseline; also give some starters a test to break.
- **Measure escalation's restart mode.** `CERTO_ESCALATION_HANDOFF=restart`
  exists (0.1.25, off by default). Bench two escalate arms that differ only
  in `handoff`, on tasks where the first rung fails (task set v2's larger
  tasks with `qwen3.8` first), then decide whether it becomes a ladder
  option or the default.
- **Automatic use of checkpoints.** Undo a fix attempt that left more
  checks failing than before. Changes agent behaviour, so benchmark it
  on a local and a cloud model first (the Author chose manual rollback
  only for 0.1.25).

## 3. Languages and verification

- **Run-the-app verification.** Start a server and probe an HTTP
  endpoint; build a frontend and load it in a headless browser (the SDK
  ships a browser tool) for a blank page or console errors.
- **Node: detect jest/vitest/mocha.** Today `build`/`test` scripts run as
  opaque commands; the runner and its results aren't parsed.
- **Node: infer ESLint/`tsc` from config**, as `_ruff_configured()` does
  for Python. Flat-config variants make this harder than the Python case.
  Open for contributors: [#33](https://github.com/alessioricco/certo/issues/33).
- **Java: a Maven/Gradle toolchain** in the Docker image and the dev
  environment. Java is detection-only in both today.
- **Java: no tests probably counts as `verified`.** `mvn test` and
  `gradle test` succeed with no tests, and Certo doesn't count the tests
  that ran, as it does for Node, Go and Rust. Unconfirmed live. Open for
  contributors: [#32](https://github.com/alessioricco/certo/issues/32).
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
- **Escalate on reasoning effort, not only on the model.** Explicit
  ladders already can (one model on two rungs, each with its own
  `reasoning_effort`). Not yet: a derived ladder that tries a lower effort
  before a stronger model, and `--auto-model` choosing the effort per task
  profile as it chooses the model. Measure first: a bench arm with one
  model at low then high effort against the same model at high only, on a
  local and a cloud model (time, cost, hidden tests). Build the
  strategies only if the cheaper effort is much faster and rarely fails.
  Needs, per model in `models_list.yaml`, the effort levels it accepts:
  some models ignore the setting or name the levels differently, and a
  wrong level fails only when the model is called.
- **Benchmark `--auto-model` for the README.** The bench `auto` arm
  exists (0.1.25); a two-task live check picked Sonnet for a `debugging`
  task and Haiku for a `default` one, both verified. Left: a full run of
  an `auto` arm next to its models alone (cloud, or local plus cloud at
  night), so the README can show a number instead of "unmeasured".
- **Why `qwen3.8` writes tool calls as text in some runs.** The
  reminder doesn't fix it (`docs/benchmark/reminders-0.1.26.md`: one
  real call, then back to text). Open: Ollama's template or parser, or
  the model's build (bench results record the digest from 0.1.26 on).
  Done when the cause is known, or a setting that avoids it is
  measured.
- **Bench estimates from recorded cost.** The plan prices every run at a
  fixed ~500k input / ~20k output tokens (far too high: a cloud run used
  ~124k in the baseline). Use the per-model average from earlier
  `cost.json` files in the same parent folder; guess only for models with
  no history. Starter issue: [#10](https://github.com/alessioricco/certo/issues/10).
- **Bench strategy `best_of`**: N attempts, the verifier picks. Next entry
  in `bench_strategies.STRATEGIES`. Benchmark on local and cloud before
  release.
- **Per-tier tuning for small models.** Shorter prompts and stricter
  tool-call repair, gated by model tier and measured on both tiers.
- **`certo doctor` for Ollama**: model pulled, context size, thinking
  mode, measured tokens per second. Open for contributors, as part of
  `certo check`: [#35](https://github.com/alessioricco/certo/issues/35).
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
- **Docs articles still to write** (ideas from 2026-10-18): review the agent's work safely;
  share your benchmark results (with the benchmark file, as `docs/benchmark/` does); keep costs down; use `certo verify`
  without the agent (pre-commit: done in #16; any AI tool: [#31](https://github.com/alessioricco/certo/issues/31)).
- **Prebuilt Docker image.** Docker execution from a pip install fails:
  `workspace.py` builds from `docker/agent-server.Dockerfile` relative to
  the repo, which isn't in the wheel. Ship the Dockerfile and tool source
  as package data, or publish an image. Documented in
  `docs/guides/run-in-docker.md`.
- **A secret manager for keys** (an idea, 2026-10-20). Keys live only in
  the settings file for now. Later, read them from the system keychain
  or a secret manager (1Password, Bitwarden, a cloud vault) instead.
  Decide which, and how a key is named, when someone asks for it.
- **MCP server with every Certo command** (the Author, 2026-10-31: all
  the commands, so a client can build a wrapper on top; 0.2 work, after
  the Phase 3 exit). Design in DECISIONS.md ("The MCP server: every
  command, on a shared core"). In order: (0) `certo.api`, one typed
  function per command, with the CLI and `certo-server` moved onto it;
  (1) the JSON result and `certo --json`; (2) `certo-mcp` over stdio,
  `--tools core` then `--tools all`, runs as start/status/events/cancel,
  resources, roots and elicitation; (3) a guide and the test that every
  command has a tool. Done when every command in
  `docs/reference/commands.md` has a tool, a guide shows a client
  running a task to `verified`, and that test passes. Later: the
  client's model through MCP sampling.
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
Today there are 15 (eight `lifecycle/`, `git/commit-conventions`,
`python-web/fastapi-conventions` and `pin-dependencies`,
`testing/pytest-conventions` and `testable-interactive-apps`,
`python/python-environment`, `node/node-project-setup`).

**`pin-dependencies` fires only when the file editor edits a dependency
file** (2026-10-31, ARCHITECTURE.md): a `pip install` or `uv add` in the
terminal never fires it. Decide whether it becomes keyword-triggered
too, or folds into `python-environment`. Done when its rule reaches the
agent before a dependency is added from the terminal.

**Measure the two new skills before 0.1.27 is released.**
`python-environment` and `node-project-setup` (2026-10-31) are written
but not measured. `node-project-setup` fires on the Node benchmark
tasks (`slugify`, `semver-order`, `room-bookings`, `token-bucket`;
keyword-triggered since its path trigger never fired): a `skills_off` arm
against the default on those, Haiku and qwen3.8. `python-environment`
fires on no bundled task: it needs a task with a third-party package
first. Done when both are measured, or the unmeasured one is left out
of the release.

**Make a project verifiable** (first; suggested order: the first two):
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

- **`certo skills`: turn an official skill off**, globally or for one
  project (later, agreed 2026-10-22). Today a third-party skill can only
  replace one.
- **The OpenHands skill catalog from `certo skills`** (agreed
  2026-10-24). `OpenHands/extensions` holds about 70 MIT skills, a few
  about code quality (`code-review`, `code-simplifier`, `security`,
  `qa-changes`, `iterate`), and since 0.1.23 they download (links inside a
  skill are skipped). Two steps: (1) A shortcut on the existing git path,
  e.g. `certo skills browse openhands` and `certo skills add
  openhands:NAME`: pinned, license step, off until enabled, third-party
  in commands, folders and output. Not the SDK's `load_public_skills`
  (unpinned, everything at once, no license step). (2) Benchmark two or
  three code-quality skills against none, local and cloud, before
  claiming they improve code; most fire only on a slash command
  (`/qa-changes`) and are large (about 4,200 tokens). Done when a
  catalog skill installs and runs from one command and the benchmark
  says whether it helps.
- **Plugins with safeguards** (agreed 2026-10-24, after the independent
  tests bench arm; DECISIONS.md "Plugins: chosen by Certo, copied into the
  project"). Steps: (1) verify-first: that hooks can't fire during
  Certo's checks (they run outside the conversation), and how plugins
  load under `--execution docker`. (2) `certo plugins add|list|remove`,
  a library apart from `~/.agents/plugins`, pinned by source and hash,
  with `copy_regular_files`; on `add`, show the parts; skills, commands
  and agents install directly, hooks and MCP servers need `--allow-code`
  after their commands are printed. (3) Chosen per project and copied
  into its `.agents/plugins/`, so the SDK loads them as the project's
  own and the current check keeps refusing everything else; hashes
  checked before each run; names, hashes and parts in the run summary
  and metadata. (4) The independent-tests writer reads a copy without
  `.agents/plugins`, so no hook fires there. (5) A bench arm with and
  without, local and cloud, before claiming plugins improve results.
  Reference catalog: `plugins/` in OpenHands/extensions (skills,
  commands, Actions scripts; no hooks or MCP today). Done when a chosen
  plugin runs in a project with the safeguards tested, and the user
  folders are still refused.
- **`certo skills suggest`** (later, agreed 2026-10-22): match a
  project's files against an index of vetted third-party skills shipped
  with Certo, and print `add` commands; never install by itself.
- **Third-party skills: narrow license detection, `SKILL.md` only.** Eight
  permissive licenses are recognised; anything else is `unknown` and needs
  acknowledgement. Legacy single-file upstream skills can't be installed.
  Fine for now; revisit if people use the feature.
