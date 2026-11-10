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
  stopped had no tests. Not shown to help. The Author agreed
  (2026-11-06) that a longer budget can be chosen later: pick the value
  from data. The 3-repeat effort run (`docs/benchmark/effort-0.2.2.md`)
  hit the 30 minutes in 10 of 78 runs on the small bundled tasks; 5 of
  them were `library-loans`, which never passed, and only 1 run that
  hit it had right work.
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
- **Re-verify the "confident but wrong" fixes live**: #1, #3, #5 and #6
  for Java in `ARCHITECTURE.md` say "not re-verified live" (#2, #4 and #6
  for Go/Rust were, 2026-10-19; #10, 2026-10-31). #1 and #5 are hard to
  trigger on purpose. A climb inside a milestone (`--milestones
  --escalate`) and `--resume` after Ctrl-C were seen live, 2026-10-31.
- **Docker verification has never run against a real container**, and
  neither has escalation under Docker. Fake-workspace tests only. Open
  for a report: [#34](https://github.com/alessioricco/certo/issues/34).

## 2. Complex tasks

- **Certo writes the milestones when the task has none** (the Author,
  2026-11-10; already decided 2026-10-25, DECISIONS.md "Milestone mode:
  the Author's three decisions": "otherwise Certo plans them"). Before a
  run, a cheap model good at reasoning rewrites a task with no
  milestones as a milestone task (`## Milestone N: title` sections, the
  format `certo --milestones` already runs), saved in the project's
  `.certo/` (beside `milestones.json` and `STATUS.md`); the run then goes
  milestone by milestone, and `--resume` continues that plan. Points to
  settle in the design:
  - *When:* only for tasks big enough to gain; the planner may answer
    "one milestone" and the task runs as it is. A rule (length, number
    of features) or the planner's own call; never for `verify`, a fix in
    an existing project, or `--no-milestones`.
  - *Which model:* chosen from the catalog, never named in code (golden
    rule 3): a planning profile for `--auto-model`'s ratings, or a
    setting such as `CERTO_PLANNER_MODEL`; default the build's model
    when nothing better is configured.
  - *Checks:* the plan is parsed with the milestone parser before use;
    an unreadable plan falls back to one task. Acceptance checks written
    by the planner can be wrong (as independent tests can): start
    without them, or report-only, until measured.
  - *The user:* with `--interactive` Certo shows the plan and asks (the
    2026-10-25 decision); the saved plan is a task file the user can
    edit and run again.
  - *A plan the agent wrote:* live 2026-11-10 (latticewake), the agent
    wrote a `PLAN.md` in milestones (`## 1. ...` headings, not
    `## Milestone N:`), the user approved it with "go ahead", and the
    whole plan ran as one task on one budget of 50 steps. Certo could
    spot such a plan file in the project and offer to run it milestone
    by milestone (each with its own steps and checks), or the planner
    above could rewrite it in the milestone format.
  - *Stop for approval:* a task file written for a person who approves
    each milestone ("STOP and wait for my approval", latticewake
    2026-11-10). `--interactive` doesn't pause between milestones today;
    it could show each verified milestone's summary and ask before the
    next. A milestone with nothing to check (a plan only) ends
    `inconclusive` and stops the run, which works as a pause, by
    accident: `certo --resume "approved"` continues it.
  - *Level-1 headings after the milestones* (`# Definition of done`,
    `# Begin`) belong to the last milestone's text; they could go to
    every milestone, as context.
  - *Run `star-swarm.md` once* (the sample from the latticewake task,
    10 milestones) and add it to `milestone-samples-0.2.3.md`.
  - *Measure* (working agreement 2): the app tasks and the milestone
    samples with their milestones removed, three arms (the hand-written
    milestones, the planned ones, one go), on qwen3.8 and Haiku. On the
    spreadsheet, milestones haven't helped qwen yet
    (`milestones-0.1.27.md`: stopped at milestone 2), so the gain isn't
    a given. Opt-in until the benchmark shows no loss on either model.
  Done when a task with no milestones runs on a plan Certo wrote, saved
  in `.certo/`, and the benchmark shows no loss. Supersedes the "then
  Certo planning the milestones itself" item below and area (5) of the
  agent-loop study.
- **Study and improve the agent loop** (the Author's prompt, 2026-11-07,
  "a big activity, not now"; kept as written in
  `docs/history/agent-loop-prompt.md`). Trace the run, verification,
  retry, escalation, checkpoint, independent-test and milestone flows;
  give a prioritized plan; implement one improvement at a time, only
  the one the Author picks. Five areas: (1) undo a fix attempt that
  makes the checks worse (see "Automatic use of checkpoints" below);
  (2) tell legitimate test changes from ones that weaken the evidence
  (see "Changed check files"); (3) fewer misread independent tests,
  maybe a separate writer model (see "Independent tests: the rest");
  (4) bounded smoke checks of the app (an HTTP endpoint, a page that
  renders), within the existing security decisions; (5) Certo proposes
  milestones with acceptance criteria for the user to approve (now its
  own item: "Certo writes the milestones when the task has none"). Sky
  Hopper is the candidate evaluation task. Benchmark on a local and a cloud model before claiming a gain; no live
  calls without the Author's OK. Done item by item.
- **The three milestone samples: the menu?** First runs done
  (`docs/benchmark/milestone-samples-0.2.3.md`): all `verified` on Haiku
  alone, $0.34 to $1.11 and 14 to 47 minutes each. Left: the Author
  judges how they look and play; then decide whether they join the menu
  at the end of `certo init` (with those times) and the benchmark task
  set. A run on a local model is still to try (at night).
- **The milestone samples on other models** (the Author's wish,
  2026-11-07, "not now"). Same three tasks, same way, one model each, to
  compare by eye and by numbers: `gpt-6.1-sol` first (the Author's
  choice; the November 2026 discount is on `gpt-5.6-sol`, but 6.1 Sol is
  cheaper at list price and stronger), then maybe Sonnet 5.5 and qwen3.8
  at night. `examples/compare-models.sh.example` already runs one task per
  model and tabulates verdict, time and cost (a milestone file now runs
  in milestones without the flag). Estimate first: Haiku took $2.28 for
  all three; Sonnet costs 20x per token. Start with `iron-horizon`, the
  cheapest. Done when each model's projects can be opened side by side,
  with a record page.
- **Milestone mode: what's left.** Phase 3 closed on 2026-10-31 (the
  Author): `app-tasks/expenses` (apps-2), qwen3.8 `verified` in 2/3
  runs, 80/80 hidden (`docs/benchmark/expenses-0.1.27.md`). The
  spreadsheet still
  stops at milestone 4 on qwen3.8 (`milestones-60min-0.1.27.md`). Left:
  a climb inside a milestone seen in a benchmark (only one live run,
  `milestones-escalate-0.1.27.md`); with the next `apps-` version, say
  in the spreadsheet task that a chain of 200 cells must work (hidden
  `test_m2_a_long_chain` is stricter than the text). Certo planning the
  milestones itself: its own item above.
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
  to 7 of 65 sets); (2) maybe an option for a different
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
- **Bench estimates from recorded cost: the rest.** Since 0.2.3 the plan
  uses the measured bench runs in `run_stats.csv` (run_stats.py), but a
  computer with no recorded runs still gets the fixed ~500k/~20k guess.
  Earlier `cost.json` files in the same results folder could fill in for
  models with no recorded runs. Starter issue:
  [#10](https://github.com/alessioricco/certo/issues/10) (say on it that
  the first part is done before someone picks it up).
- **Bench strategy `best_of`**: N attempts, the verifier picks. Next entry
  in `bench_strategies.STRATEGIES`. Benchmark on local and cloud before
  release.
- **Per-tier tuning for small models.** Shorter prompts and stricter
  tool-call repair, gated by model tier and measured on both tiers.
- **Measured speed and context in the catalog**, filled from real runs,
  so ladders can weigh speed. A `speed` rating would count as capability
  today.
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

- **A text UI for interactive mode** (the Author, 2026-11-08; for the
  version after 0.2.3, not before). Today `--interactive` prints the
  agent's stream and asks questions on plain stdin lines. Give it a
  classic terminal UI like other coding-agent harnesses (Claude Code,
  Copilot CLI): a scrolling transcript, an input box at the bottom, the
  progress line and run summary in a status area, and confirm-mode
  approvals as prompts in it. Two steps: (1) design it: what it shows,
  the keys, how it falls back when the terminal can't do it (pipes, CI,
  `--json`), and which library, if any (a heavy dependency needs the
  Author's OK); write the design in `docs/history/` and a DECISIONS
  entry; (2) implement it behind `--interactive`, leaving the plain
  output for non-interactive runs, with docs and tests (rendering tested
  without a real terminal). Done when an interactive run of a sample
  task works end to end in the new UI, and plain runs are unchanged.
- **A first run in minutes, with one model.** No catalog, no ladders:
  `certo init`, then a first verified project. Getting started shows only
  that path. Measured 2026-10-19 in an empty home folder: 88.5s from
  `uv tool install` to `verified` (`docs/benchmark/first-run-0.1.19.md`).
  Still to do: a truly clean machine (no Python, no uv).
- **One menu at the start of `certo init` for one or several models?**
  (Author's request, 2026-11-07.) 0.2.3 asks "Set up more models now?"
  after a passing check and runs `certo init models` on yes. If users
  still miss it: ask "one model / several" first, and explain the three
  modes (one model, `--auto-model`, `--escalate`) in plain words, with
  what each costs. Also open: offering it with "This folder only".
  Done when a new user reaches the mode choice without reading the docs.
- **GitHub Action**: an issue labelled `certo` becomes a pull request with
  the verdict and checks in its description.
- **Docs articles still to write** (ideas from 2026-10-18):
  share your benchmark results (with the benchmark file, as `docs/benchmark/` does).
- **Prebuilt Docker image.** Docker execution from a pip install fails:
  `workspace.py` builds from `docker/agent-server.Dockerfile` relative to
  the repo, which isn't in the wheel. Ship the Dockerfile and tool source
  as package data, or publish an image. Documented in
  `docs/guides/run-in-docker.md`.
- **A secret manager for keys** (an idea, 2026-10-20). Keys live only in
  the settings file for now. Later, read them from the system keychain
  or a secret manager (1Password, Bitwarden, a cloud vault) instead.
  Decide which, and how a key is named, when someone asks for it.
- **MCP tools for `certo skills remove` and `disable`** (on request
  only). They only take skills away, so a tool is safe, with
  `rollback`'s confirm step; nobody has asked. Every other command has
  a tool or a lasting reason (`NO_TOOL`, DECISIONS.md).
- **An MCP tool for `certo skills add` with a local file or folder**
  (on request only): for a skill just written in the editor. It refuses
  a git source, and replaces a skill of the same name only with a
  confirm step, like `rollback`. Done when the tool exists and
  `NO_TOOL` no longer lists `certo skills add` for local files.
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
- **No way to list tasks over REST** (`GET /tasks`): `certo-admin list`
  does it locally (0.2.1). Waits for server authentication, since the
  list would show every client's tasks.
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

**Trusted skill repositories** (Author's request, 2026-11-07; merges
the earlier "OpenHands skill catalog" and "`certo skills suggest`"
items, agreed 2026-10-22/24). An archive of trusted skills Certo draws
on when it builds projects, instead of adding skills one by one
(`certo skills add` + `enable` today). One pipeline, in steps:
1. *Sources.* `skill_sources.yaml` in `~/.config/certo/`, replaced or
   extended by `<project>/.certo/skill_sources.yaml` (the project file
   wins, as the skill layers do). Each entry: a git repo pinned to a
   commit, with an optional allowlist of skill paths. First source:
   `OpenHands/extensions` (about 70 MIT skills; a few on code quality:
   `code-review`, `code-simplifier`, `security`, `qa-changes`,
   `iterate`). Not the SDK's `load_public_skills` (unpinned, everything
   at once, no license step).
2. *Assess* (`certo skills assess`): fetch the sources and check and
   classify every skill once. Per skill: license (as `enable` does),
   format and size, the `` !`command` `` lines and scripts it asks the
   agent to run, ecosystem and lifecycle step (setup, testing,
   framework, git...), and when it fires: its triggers, or ones derived
   from its description and paths (most OpenHands skills fire only on a
   slash command such as `/qa-changes`, and are large, about 4,200
   tokens). Writes an index (commit, hash, class, verdict: usable /
   needs review / rejected); a run reads the index, never the repos. A
   skill changed by `update` is assessed again.
3. *Suggest* (`certo skills suggest`): match a project's files and a
   task against the index and print what fits and why, with the
   commands to use it; never installs by itself. A safe first use of the
   index before any automatic loading.
4. *Use at run time:* the index is matched against the task, the
   milestone/step and the project's files; a matching skill is loaded
   for that step only. Official and hand-added skills keep precedence.
5. *Measure:* two or three code-quality skills against none, with
   `certo bench` on a local and a cloud model, before claiming they help
   (every skill that fires costs context a 32K local model can't spare).

*Decisions (settled 2026-11-07, DECISIONS.md):* listing a repo plus a
`usable` verdict is the opt-in; classification by rules now, maybe a
model-assisted pass during `assess` later; the run-time choice stays
rule-based.

*Done when:* a project's sources file and one `assess` give a run skills
from a trusted repo with no `add`/`enable`, and the benchmark shows no
loss. Docs: `manage-skills.md`, `reference/commands.md`,
`concepts/safety.md`.

*Progress:* steps 1-4 done (0.2.3: `skill_sources.yaml`,
`certo skills assess`, index in `<skills folder>/.trusted/`;
`certo skills suggest` and `skill_match.py`; runs add the fits as
always-on context within `CERTO_TRUSTED_SKILLS_TOKENS`, default 4000).
Both decisions settled (DECISIONS.md). On `OpenHands/extensions`
(2026-11-07): 73 skills, 52 usable, 15 to review, 6 rejected (links
outside their folder). Matching needed two links or the skill's own
trigger: one link alone suggested `npm`/`deno` for every Node project.
The repo has little for building apps (`frontend-design` names only an
ecosystem), so better sources matter as much as the matching. One live
Haiku run (`docs/benchmark/trusted-skills-0.2.3.md`) shows a skill
reaching a run, not that it helps. **Step 5, the release check (no
loss), 2026-11-10:** bench arm option `skills_dir` (benchmark runs had no
third-party skills at all). On the 13 bundled tasks only the 4 Node ones
get a trusted skill, always `npm` (~56 tokens), so the check runs those 4
with and without (`bench-0.2.3-trusted-{cloud,local}.yaml`); it can show
no harm, not a benefit.

- **Do trusted skills help? (after 0.2.3, option B agreed 2026-11-10).**
  The release check above can't tell: almost nothing fits the bundled
  tasks. Measure on tasks where substantial skills fire: tasks naming a
  framework or tool a trusted skill covers, or the milestone samples,
  with the Author's other skill repositories added to the sources.
  First list which skills fit which task (`certo skills suggest`), so
  the arms really differ. Also decide the default
  `CERTO_TRUSTED_SKILLS_TOKENS` from it. Done when a benchmark shows
  whether they help, on a local and a cloud model.

## Smaller bugs

- **`pytest-conventions` goes into non-Python runs.** Its trigger is the
  word "test" (and "tests", "unit test"), so a browser JavaScript game
  (Iron Horizon, 2026-11-08) gets it from "test" in the task. Narrow it
  to Python projects (a Python file or `pyproject.toml` in the folder, or
  "pytest"/"python" in the task). It changes what runs get, so bench it
  with `skills_off` on a Python and a Node task before release. Done when
  `certo skills list --task` on a Node game leaves it out and a Python
  task still gets it.

- **`certo skills`: turn an official skill off**, globally or for one
  project (later, agreed 2026-10-22). Today a third-party skill can only
  replace one.
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
- **Third-party skills: narrow license detection, `SKILL.md` only.** Eight
  permissive licenses are recognised; anything else is `unknown` and needs
  acknowledgement. Legacy single-file upstream skills can't be installed.
  Fine for now; revisit if people use the feature.
