# Architecture and internals

How Certo is built, module by module, and the traps found while building
it: SDK gotchas and the "confident but wrong agent" cases. For
maintainers. It is not user documentation (that is `docs/`); why each
choice was made is in `DECISIONS.md`, and what's left to do is in
`TODO.md`.

> **Maintenance note:** update this file in the same change when a
> module's role changes, or when a new SDK gotcha or internal limitation is
> found. Keep entries terse. See `CLAUDE.md`.

## Modules

Per-module reference. See `docs/` for user-facing behavior; see `DECISIONS.md` for *why* a
given design was chosen.

- **`config.py`** — env parsing, model-agnostic (`CERTO_LLM_MODEL` prefix selects
  provider). `override_llm(cfg, model=, api_key=, base_url=,
  reasoning_effort=)` is the per-request override mechanism shared by
  `cli.py`/`server.py`. `resolve_project_dir(projects_dir, project)` is the
  shared resolver both `--project` and the server's `project` field go
  through: rejects an absolute/`..`-containing name outright, then rejects a
  symlink-resolved (`os.path.realpath`) path that escapes `projects_dir` —
  closes a real path-escape bug (`os.path.join` silently discards the first
  arg when the second is absolute). `max_task_seconds` (`CERTO_MAX_TASK_SECONDS`,
  default `1800`) is the task-level wall-clock budget `runner.py` enforces
  across every phase. `interactive` (`CERTO_INTERACTIVE`) opts into the
  initial-run interactive checkpoint and drops `_AUTONOMOUS_SUFFIX`.
  `load_settings_files()` fills `os.environ` from `./.env`, then the user
  file (`user_settings_path()`: `$XDG_CONFIG_HOME/certo/.env`, else
  `~/.config/certo/.env`), and returns each variable's `SettingSource`;
  `load_config()` calls it when no `env` mapping is passed.
  `no_worktree_warning` (`CERTO_NO_WORKTREE_WARNING`) silences `worktree.py`.
- **`acceptance.py`** — optional, caller-supplied machine-checkable
  acceptance criteria, scoped to `file_exists`/`file_contains` only (no
  command-exec kind — see decisions log). Own path-containment check
  (mirrors `resolve_project_dir`'s logic, separate implementation). 1MB read
  cap on `file_contains`. Wired via a new `"acceptance_failed"` terminal
  state, applied once at the very end of `stream_task`, downgrading what
  would otherwise be `"verified"` only.
- **`llm.py` / `tools.py` / `agent.py`** — SDK wiring; default preset tools +
  `run_tests`. `build_llm()` passes `reasoning_effort` through when set;
  `none`/`off` (config folds `off` into `none`) and an unset Ollama model
  pass an explicit `None` (no reasoning param sent); any other unset model
  omits the kwarg so the SDK's own `"high"` default applies. `AgentContext.system_message_suffix` carries five
  behavioral policies: `_AUTONOMOUS_SUFFIX` (omitted when `cfg.interactive`),
  `_README_SUFFIX` (leave a real `README.md`), `_NONINTERACTIVE_TOOLING_SUFFIX`
  (use CI/non-interactive flags, don't blindly retry a no-op command),
  `_VERIFY_BEFORE_FINISH_SUFFIX` (run tests before claiming success), and
  `_LIFECYCLE_SKILLS_SUFFIX` (apply lifecycle-skill discipline even
  off-trigger, skip for trivial changes, never substitute for actually
  verifying). `build_agent()`/`build_llm()` take an optional `usage_id` so
  auto model selection's candidates each get a distinct SDK LLM-registry key.
- **`runner.py`** — `stream_task()`/`run_task()` are the core primitives;
  wires `cfg.max_iterations` into `Conversation(max_iteration_per_run=...)`
  (previously unset, silently defaulting to the SDK's `500`). Both return a
  `TaskOutcome` — a bounded verification verdict (`VERIFICATION_STATES`) from
  `_verify_and_report()` (harness-side, no-LLM re-run of the project's own
  checks; doesn't trust the agent's self-report), checking
  `conversation.state.execution_status` for `STUCK`/`ERROR` before verifying
  and after every retry. `_enforce_task_tracker_completion()` runs first: if
  the most recent `task_tracker` observation shows unresolved items, resends
  a follow-up and retries (bounded by `CERTO_MAX_VERIFY_RETRIES`); an
  unresolved list becomes a terminal `"incomplete"` state, short-circuiting
  verification entirely (an unused or already-`done` tracker is not a
  violation). `CERTO_CONFIRM_MODE=always` is wired via
  `_run_with_confirmation()`, wrapping every `conversation.run()` call site
  and returning `"ok"`/`"confirmation_required"`/`"budget_exhausted"`; no
  `on_confirm` handler (server mode) rejects the pending action once and
  stops rather than auto-approving or hanging. `CERTO_MAX_TASK_SECONDS` is
  checked before every `.run()` call across all three call sites, and
  `deadline.stop_at_deadline` keeps each `.run()` inside it: a watcher
  thread calls `conversation.pause()` at the deadline (takes effect
  between steps) and keeps the SDK's foreground terminal cap and the
  model's per-call timeout at the time left. The model cap sets
  `conversation.agent.llm.timeout` (read on every attempt, v1.47.0; one
  second over the time left, so a cut call ends after the deadline) and
  after the deadline a `retry_listener` that re-raises, which stops the
  SDK's tenacity retries (`before_sleep` runs it); both are put back
  when the run ends. The cut call's `ConversationRunError(LLMError)` past
  the deadline is swallowed in `_run_conversation_once` and the
  conversation added to `_CUT_AT_DEADLINE`, so its ERROR status doesn't
  stop the checks after the budget. Docker runs call the model in the
  agent server, so only local runs are capped. That cap is the SDK's
  `OH_RUNTIME_IDLE_TIMEOUT_SECONDS` (cap = 90% of it), read from
  `os.environ` on every terminal command (`terminal_session.execute`,
  v1.47.0); a longer `timeout` is refused with an SDK message about
  "idle cleanup", which the agent follows anyway (live 2026-10-25). It's
  process-wide, so concurrent runs share the nearest deadline, and it
  doesn't reach a Docker terminal. `CERTO_INTERACTIVE`
  wires an `OnAwaitingInput` checkpoint around the *initial* run only (`cli.py`
  supplies a terminal handler, `server.py` doesn't); the deadline is paused,
  not spent, while waiting on a human reply. The runner
  treats an `ERROR` whose last `ConversationErrorEvent` has code
  `MaxIterationsReached` (the SDK's step-limit stop, v1.47.0; `run()`
  returns normally and a later `run()` resets the step count) as a finish
  to check, not `stuck`: `_hit_step_limit()`, in both the task-tracker and
  the verify phases (0.1.20). Failing checks then go through the normal
  retry loop, which is where auto-model's quality switch happens.
  `CERTO_MODEL_SELECTION=auto`
  wires a `ModelChain` (see `model_selection.py`) with automatic fallback on
  a `ConversationRunError` wrapping the SDK's own `LLMError` hierarchy
  (the provider-failure path, through the real `switch_llm`, confirmed
  live 2026-10-19: a wrong OpenAI key on the first pick switched to
  `claude-haiku-5-5`, `verified`, $0.0054; the quality-failure path is
  still fake-tested only);
  `write_model_decisions()`/artifact-writing both run in a `finally` block
  around the whole task so they still fire when every candidate fails.
  `CERTO_ARTIFACTS_DIR` mints a `run_id` (or uses the caller's, e.g.
  `server.py`'s `TaskRecord.id`) and writes `metadata.json`/`transcript.json`/
  `metrics.json` via `artifacts.py`.
- **`verification.py`** — language-neutral verification in four stages,
  with no SDK import (so `certo verify` starts without loading it; the
  agent's `run_tests` tool in `custom_tools/run_tests_tool.py` builds on
  it): **detection** (`detect_project()` — Python/Node/Go/Rust/
  Java-Maven/Java-Gradle marker walk, plus an `"ambiguous"` state for
  monorepos with sibling manifests at the same shallowest depth), **plan
  discovery** (`discover_verification_plan()`, pure), **execution**
  (`execute_check()`, the only subprocess-spawning stage; `stdin=DEVNULL` by
  default on every check), and **aggregation** (`VerificationRun.state`,
  which a secondary check can only ever pull down from `verified`, never
  promote up to it). `CheckOutcome.status` is a five-value enum
  (`passed`/`failed`/`skipped`/`unavailable`/`timed_out`) so "should be
  checkable but isn't" (missing toolchain) is never confused with "not
  configured" or "ran, nothing to check." `CheckSpec.precomputed` supports a
  pure, no-subprocess static check — used by `entrypoint-ordering`, an
  AST-based check (recursive discovery, root always included) that a Python
  entry point's `if __name__ == "__main__":` guard is its last top-level
  statement. The agent-facing `run_tests` tool keeps its original rich
  Python/Node contract and reuses stages 1–3 for Go/Rust/Java. Python adds
  a setup stage, `prepare_python_env()`: find or create the project
  environment, probe which of pytest/ruff/mypy it can import, and install
  pytest into it when tests exist but pytest doesn't. Planning stays
  subprocess-free by reading that result. Every check runs through a
  `CommandRunner` (`execute_check(..., runner=)`). `CheckSpec.env` holds
  extra variables only, never a copy of `os.environ`. Java is
  detection-only in this dev environment and the Docker image (neither ships
  a Maven/Gradle toolchain).
- **`cli.py`** — `python -m certo "<task>" [--execution] [--project]
  [--agents-md] [--model] [--api-key] [--base-url] [--reasoning-effort]
  [--interactive] [--require-verification] [--acceptance-checks]
  [--auto-model]`, plus `certo verify [PATH] [--require-verification]`
  (`verify_main()`: `run_full_verification` with no agent/LLM, same verdict
  line and `_FAILING_STATES` exit codes). `task` resolves via `resolve_task_source()` (http(s) URL,
  then existing local file, then literal text — CLI-only). `--require-verification`
  makes an `inconclusive` result exit nonzero too (default behavior
  unchanged otherwise). `--auto-model` sets `cfg.model_selection="auto"`;
  prompts for a choice only when `--interactive` is also set. Before
  `run_task` it prints `banner.format_banner()` (version and run
  settings; after every check that can refuse the run, never the key or a
  URL's userinfo), then `worktree.worktree_warning()` to stderr, unless
  silenced or the `--project` folder is one Certo created.
- **`worktree.py`** — stdlib only. `worktree_warning(path)`: None for an
  empty folder or a clean repository, a warning for uncommitted changes
  under `path` (`git status --porcelain -- .`, untracked included), a note
  outside git. `record_created_project`/`was_created_by_certo` keep
  `CERTO_PROJECTS_DIR/.certo-created-projects`, one name per line.
- **`model_catalog.py`** — pure data/scoring for `models.yaml`, no SDK
  imports: `load_model_catalog()`, `classify_task()` (keyword triggers, same
  pattern as skills), `score_entry`/`rank_candidates` (weighted sum over a
  profile's declared axes, skips `activated: false` entries entirely).
- **`model_selection.py`** — the SDK-touching layer: `ModelChain` is a
  forward-only cursor over one task's ranked candidates (scored once, never
  re-scored mid-task), `.advance()` logs a `ModelDecisionRecord` (never
  carries secrets). `config_for_entry()` passes `""` (not `None`) for an
  unset field so a keyless local model can't inherit a stale API key.
  `write_model_decisions()` rewrites `MODEL_DECISIONS.md` from the full list
  every time (never appends).
- **`artifacts.py`** — pure file-writing for `CERTO_ARTIFACTS_DIR`:
  `<artifacts_dir>/<project-or-"_unscoped">/<run_id>/`, own path-containment
  check. No SDK dependency. A sibling top-level directory (mirrors
  `CERTO_PROJECTS_DIR`'s shape), not nested inside a project.
- **`bench_tasks.py` / `bench_config.py` / `bench_strategies.py` /
  `bench.py` / `bench_report.py`** — `certo bench`. The task set ships in
  `src/certo/benchmark_tasks/` (`VERSION` file; 9 tasks, each `task.md`,
  optional `starter/`, `hidden_tests/`, `reference/`). `grade()` copies the
  hidden tests into `.certo_hidden_tests/` and runs them in the project's
  own environment (pytest with its own ini and `PYTHONPATH=workspace`;
  `node --test`, after `npm ci`/`npm install --ignore-scripts` when `package.json` declares
  packages; `go test -v ./.certo_hidden_tests`, an explicit path because
  `./...` skips dot folders). Rust is the exception: Cargo finds test
  targets only in `tests/`, so they are copied there as
  `certo_hidden_<name>.rs` and run with `cargo test --test`. Only hidden
  tests run, and a run of zero tests is an `error`. `bench_config.py` validates `bench.yaml` against
  `models.yaml` names; `bench_strategies.STRATEGIES` is the registry
  (`single`, `escalate`), each strategy building an explicit `Config` from the
  catalog entry (`run_config`, Certo defaults, isolated skill dirs, no
  `.env`; `arm_config` adds the arm-level `independent_tests`, which
  `bench_config` keeps out of params when off so old fingerprints still
  match). `bench.py` runs repeat-major, one JSON per run (atomic write),
  workspace snapshots, `--max-cost`, `--stop-at`, `--parallel` (cloud-only),
  `--resume` (fingerprint + task-set hash must match), each run's
  conversation in `runs/transcripts/<run_id>.json` (0.1.15). `bench_report.py`
  renders `results.md`/`results.csv` from the folder alone. The task
  prompt is passed to `stream_task`, not copied into the workspace, so an
  empty-starter Python task keeps the normal "empty folder + task names
  Python → environment up front" behaviour.
- **`model_files.py`** — where `models_list.yaml` and `models.yaml` are
  found (0.1.10): an explicit setting (`CERTO_MODELS_LIST_FILE` /
  `CERTO_MODELS_FILE`, or `models_list_file` / `models_file` in a bench
  file), else the current folder, else the user settings folder; first
  found wins, per file. Since 0.1.20, `resolve_optional()` finds the two
  optional files the same way (`task_profiles.yaml`,
  `CERTO_TASK_PROFILES_FILE`; `escalation.yaml`, `CERTO_ESCALATION_FILE` or
  a bench file's `escalation_file`), returning None for one that isn't
  there. `load_model_catalog()` takes them as `profiles_path` /
  `escalation_path`; a section left in the list is still parsed when its
  file is absent (and ignored when present), with a `load_warnings` entry
  that `check_catalog()` passes on. `missing_message()` prints the `cp` command for
  the shipped example in `certo/examples/`; `bench_config` does the same
  for a missing `bench.yaml` with `example_path("bench.yaml")` (0.1.17). `model_catalog.load_model_catalog
  (list_path, models_path)` merges the two into the same `ModelCatalog`
  as before (entries gain `configured`), so ranking, ladders and checks
  are unchanged; a model only in the list is `configured=False,
  activated=False`.
- **`catalog_check.py` / `escalation.py` / `catalog_report.py` /
  `model_pricing.py`** — escalation (0.1.9). `model_catalog.py` parses
  the optional `escalation:` section (`EscalationSettings`, `Ladder`,
  `LadderRung`) and gained `capability()` (score without the cost axis).
  `catalog_check.check_catalog` is the one consistency check (errors and
  warnings as plain sentences); `load_checked_catalog` is how
  `--auto-model`, `--escalate` and `certo bench` load the file.
  `escalation.py` (pure) resolves a `ResolvedLadder` (explicit, or derived
  from the ratings), defines `ESCALATING_VERDICTS`, `RungResult` (with
  `did_no_work`: `unchanged`, or `inconclusive` with no file changed, which
  also climbs, 0.1.16), the before/after `workspace_listing`/`FileChanges`
  and `handoff_message`.
  `runner._stream_escalation` is the loop: one fresh `Conversation` per
  rung in the same workspace, reusing `_run_stream_task_phases` and
  `_apply_acceptance_checks`; `TaskOutcome.rungs`/`final_rung`.
  `catalog_report.py` is `certo check`'s catalog part and `--models`.
  `model_pricing.py` holds `is_local`/`estimate_run_cost` (moved from
  `bench.py`). `bench_strategies.EscalateStrategy` is `strategy: escalate`.
- **`project_state.py`** + `certo --resume` — stdlib only. The CLI
  passes `save_state=True` (`CERTO_SAVE_STATE`, default on) to
  `stream_task`, which then builds the `Conversation` with
  `persistence_dir=<workspace>/.certo/conversations` and its own
  `conversation_id` (local runs only: the SDK raises for a remote one) and
  keeps `run.json`/`STATUS.md` current via `_ProjectStateWriter` (start,
  each verification pass through a new `on_verification` hook, the final
  outcome after acceptance checks, or `interrupted`/`error` from the
  `finally`). `--resume` loads `run.json`, reopens the same conversation
  id (the SDK's `ConversationState.create` resumes it; tools may only be
  added, everything else, LLM included, may change) and sends
  `resume_message()` as the first message while `task` stays the goal for
  verification. When the conversation can't be reopened (Docker, folder
  gone, SDK refuses), a fresh conversation gets the task and `STATUS.md`
  instead. Server and bench never pass `save_state`.
- **`milestones.py`** + `certo --milestones` — stdlib only. Parses a task
  file into a `MilestonePlan` (`## Milestone N: title` headings outside
  code fences; ` ```acceptance ` blocks taken out of the agent's text).
  The loop is `cli._run_milestones`, not the runner: one ordinary
  `run_task` per milestone, so each gets a fresh conversation, the usual
  limits and `.certo/run.json` (always the current milestone's run);
  acceptance checks of milestones 1..N are passed as `acceptance_checks`.
  `.certo/milestones.json` holds only the source path, a sha256 of the
  text, titles and verdicts, because the agent reads `.certo/` (seen
  live: Haiku `cat`-ed the first version, checks included); `--resume`
  calls `reopen()`, which re-reads and re-checks the file, and resumes
  `run.json` only when its `task` is that milestone's text
  (`is_milestone_task`, which ignores the handover). Milestone N+1's text
  includes `handover()`: the folder's files with sizes and milestone N's
  last `finish` result; both loops build it after a `verified` milestone
  (bench from the messages of that milestone only), and a resume past
  milestone 1 gets the file list alone.
  `project_state.save_record` adds `status_lines()` to `STATUS.md`
  (lazy import: milestones.py imports project_state). Checkpoints `before
  milestone N` use `always=True`, or an unchanged folder would skip them.
  `--escalate` passes the ladder to each `run_task` (rung 1 every
  milestone). `--resume --escalate` is checked right after
  `load_state`: with a saved plan it becomes `restart=` (fresh run whose
  text ends with `render_status(record)`), without one it is refused.
  Independent tests need nothing extra: each `run_task` writes them from
  that milestone's text. `certo bench` has its own small loop in
  `bench.execute_run` (`milestones: true`): `strategy.run` once per
  milestone with a `RunContext` whose text is `milestone_task()`, the
  checks injected by `recording_stream`; `_combined_attempt` adds up the
  results. A one-go arm on such a task gets `whole_task()` and every
  check. `_default_stream` must forward `acceptance_checks` (it didn't at
  first: the fakes in the tests took it, the real stream raised).
- **`console.py`** — what a run prints. `QuietVisualizer` subclasses the
  SDK's `DefaultConversationVisualizer` and overrides only `on_event`:
  the `SystemPromptEvent` and the first user `MessageEvent` (the task
  with its skills) become one line each; every other event, Certo's
  later user messages included, goes to the SDK's rendering unchanged.
  `visualizer_for(cfg)` returns a new one per conversation (it remembers
  the task line) or, with `CERTO_VERBOSE`, the SDK's class. Certo's
  notices carry `Message.name == "certo"` (`runner.NOTICE_NAME`), which
  `run_task(on_notice=)` uses to print them live; the CLI no longer
  reprints the last message, which the visualizer already showed.
- **`run_history.py`** — stdlib only. `.certo/RUNS.md`, appended by
  `cli.py` (not the runner) once per run when state saving is on: after
  the outcome, or from the `KeyboardInterrupt`/error branches. Models come
  from `outcome.rungs`, else `run_summary.models` (what really made
  calls), else the settings. A failed write is a stderr warning, never a
  failed run. `tests/test_cli.py` stubs `append_run` (its workspace is the
  checkout). `note_models_in_readme()` keeps one marked
  `<!-- certo:models -->` block at the end of `README.md`, merging model
  ids; the CLI calls it after a finished run only when
  `was_created_by_certo` (rungs that `did_no_work` are left out).
- **`run_summary.py`** — pure: `summarize_run(duration, {usage_id:
  Metrics.get()})` → `RunSummary` (wall-clock time, models that actually
  made calls, tokens, cost; zero cost with nonzero tokens = "unknown",
  not free, except for a local-prefix model id, which is free). Built in `stream_task`'s `finally` on every run, attached to
  `TaskOutcome.run_summary`, printed by `cli.py`, written to
  `metadata.json`/`metrics.json`.
- **`llm_check.py`** + `certo-admin check-llm` — one direct
  `LLM.completion()` built via `build_llm()` (same config path as a real
  run), `num_retries=0` plus a short timeout, pass = non-empty text.
  Construction happens inside the try, since the SDK validates at build
  time. Errors are classified, with the API key scrubbed.
  `check_tool_calling()` is the variant behind `certo init`/`certo check`:
  the same build, but sent through the SDK's `make_llm_completion` with
  `FinishTool`, passing only on a tool call; `explain()` turns a result
  into one plain sentence with the fix.
- **`init_cmd.py`** — `certo init [FOLDER]` and `certo check`. Questions
  go through an injectable `Prompter`; `gather_settings()` returns
  `Settings` (key never in its repr) or `None` (no terminal, no flags:
  every preset commented out). `render_env()` writes the chosen lines
  plus the other providers' presets, to the user file
  (`write_user_settings`) or `FOLDER/.env`, as the scope question
  (`--global`/`--local`) decides. `check_main()` prints
  `print_setting_sources()` before `run_check()`. On a terminal, after a
  passing check with the sample folder, `_offer_sample()` offers a menu of
  `SAMPLES` (the browser games only when `node` is on PATH);
  `run_sample_task(folder, sample)` runs `python -m certo` in the folder as
  its own process. `init_main(run_sample=)` is None by default
  (so tests never run it); the CLI passes `run_sample_task`. Package data in
  `src/certo/starter/`: `providers.toml` (menu order, default models),
  the workspace `README.md`, `gitignore`, and the sample tasks in `tasks/`.
- **`menus.py`** — arrow-key menus for `init` and `init models`:
  prompt_toolkit's `choice()` for one choice, and `checklist()`, an
  inline Application (prompt_toolkit's only multi-select is a full-screen
  dialog). Its state, `ChecklistState`, is plain Python and tested
  without a terminal. `Prompter` uses the menus only with its default
  input and output on a real terminal (`menus.available()`: both ends a
  TTY, `TERM` not empty or `dumb`); tests and pipes get the numbered
  questions. Checked in a pseudo-terminal with real key presses.
- **`init_models.py`** — `certo init models` (`init_main` hands over when
  the first argument is `models`). `_gather()` builds the candidates from
  the saved `CERTO_LLM_*` model, the Ollama server's `/api/tags`, and the
  list's models for every provider whose key variable is set (the saved
  model's provider reuses `${CERTO_LLM_API_KEY}`); every other provider
  is an action that asks for its key. Names made up for unlisted models
  never collide with the list's (`_unique_name`). Each chosen model is
  tested with `check_tool_calling` on `catalog_report.entry_config`, its
  `${VAR}` resolved from the environment; only passing models are
  written. Typed keys go to the user settings file only
  (`_set_setting`, mode 600); user-rated models are appended to the
  list's `models:`, refused (nothing written) when the result wouldn't parse
  as part of that list.
- **`models_cmd.py`** — `certo models update`. `plan()` is a three-way
  merge per entry (user file, `.models_list.base.yaml` saved when the
  example was copied, new example), compared as parsed YAML; `apply()`
  edits the text block by block (`  - name:` plus the lines indented four
  or more spaces), so comments stay, inserts new entries after the last
  block (a pre-0.1.20 list has sections after it), then `_check()`
  re-parses and compares with the plan; any mismatch raises and nothing
  is written.
- **`project_env.py`** — each Python project's own environment (stdlib
  only, since the Docker image imports it next to `custom_tools`).
  `ensure_project_env()` reuses a `uv.lock` project (through `uv run`), or a
  working `.venv`/`venv`, searching up to the workspace root. Otherwise it
  creates `.venv` with `uv venv --seed`, then plain `uv venv`, then
  `python3 -m venv`; the base interpreter is never `sys.executable`.
  `CREATED_MARKER` lets Certo rebuild only venvs it made. `LocalRunner`
  (host subprocess, stdin closed, Certo's own `bin/` stripped from PATH)
  and `WorkspaceRunner` (the Docker container via
  `workspace.execute_command`, host↔`/workspace` path mapping) are the two
  `CommandRunner`s. `terminal_env()` builds the agent terminal's extra
  variables, and `wants_python_env()` decides about a workspace before the
  agent starts. `runner.py`'s `_prepare_agent_env()` calls it, then passes
  `project_env`/`terminal_env` to `build_agent()`. `tools.py` puts them in
  the terminal `Tool`'s `params` (`env` plus `terminal_type="subprocess"`).
- **`workspace.py`** — `build_workspace(cfg)` single dispatch point;
  `local` returns a path, `docker` returns a `DockerWorkspace`, both context
  managers.
- **`docker/agent-server.Dockerfile`** — layers our tool source onto
  `ghcr.io/openhands/agent-server`.
- **`server.py`** — `GET /health`, `POST /tasks`, `GET /tasks/{id}`,
  `WS /tasks/stream`, `GET /v1/models` + `POST /v1/chat/completions`
  (OpenAI-compatible, streaming and non-streaming). All task-facing
  endpoints share one background-thread+callback pattern. Accepts the same
  per-request LLM overrides as the CLI (the OpenAI adapter uses distinct
  `llm_*`-prefixed fields since `model` is wire-mandated and echo-only).
  `require_verification`/`acceptance_checks` are supported on the native
  REST/WS API only — not `/v1/chat/completions`, which never surfaces
  `verification_state` at all. `DELETE /tasks/{id}` and
  `DELETE /tasks?project=NAME` back the task-store persistence feature.
- **`task_store.py`** — pluggable persistence (`CERTO_TASK_STORE`:
  `memory`/`redis`/`sqlite`/`mysql`/`postgres`), one `TaskStore` ABC.
  `sqlite`/`mysql`/`postgres` share one `SQLTaskStore` via SQLAlchemy Core.
  `redis` uses native per-key `EX` expiration instead of a purge sweep.
  `CERTO_TASK_TTL_SECONDS` (default `0` = forever) governs retention;
  `server.py` runs a 60s sweep only when a TTL is configured.
  `build_task_store(cfg)` is the one factory both `server.py` and
  `admin_cli.py` use.
- **`admin_cli.py`** (`certo-admin`) — maintenance CLI talking directly to
  the store, no running server needed: `show`, `delete-task`,
  `delete-project`, `purge [--ttl-seconds N]` (refuses at `<= 0`).
- **`skills.py`** — two mechanisms: `load_skill_catalog()` reads a
  shared, trigger-based catalog, such as the official
  `src/certo/builtin_skills/` (ships in the wheel; layers are
  `skill_library.py`);
  `write_project_context()` writes a caller-supplied, per-project
  `AGENTS.md` (requires `AgentContext.load_project_skills=True`, which is
  consumed lazily by `LocalConversation`, not validated by `AgentContext`
  itself — easy to silently omit). The catalog includes eight authored,
  legacy-format (`triggers:`/`paths:`) lifecycle skills under
  `builtin_skills/lifecycle/` — `repository-discovery`, `requirements-analysis`,
  `implementation-planning`, `testing-and-verification`,
  `debugging-and-failure-repair`, `security-review`,
  `documentation-and-operational-readiness`,
  `completion-and-release-readiness` — which supersede an earlier
  downloaded five-skill `SKILL.md` set (see decisions log).
- **`third_party_skills.py`** — local-only, license-aware downloaded
  `SKILL.md` skills, for one third-party folder (global or project, see
  `skill_library.py`), one level deep. Provenance lives in the folder's
  JSON lockfile (`skills.lock.json`: repo, path, commit SHA, license id or
  `unknown`, URLs, `sha256-` integrity, enabled/acknowledged flags, never
  content). `load_enabled_skills()` re-checks enabled, license
  acknowledgement and hash. The old folders (`CERTO_SKILLS_DIR`,
  `CERTO_THIRD_PARTY_SKILLS_DIR`) and `certo-admin skills` were removed
  after 0.1.22; `config.py` warns while one of their settings is set.
- **`skill_library.py`** + **`skills_cmd.py`** (`certo skills
  list|add|remove|enable|disable|update|sync`) — where a run's skills come
  from: official (`builtin_skills/`), third-party global
  (`~/.config/certo/skills/`), third-party project
  (`<project>/.certo/skills/`), and the project's own `.agents/skills/` +
  `AGENTS.md` (loaded by the SDK, listed only). `collect()` returns one
  row per skill per layer, marks what a later layer replaces (one skill
  per name, since `AgentContext` rejects duplicates), and the notices a
  run prints (`cli.py`, before the run). `build_agent()` takes
  `collect(cfg, cfg.workspace, own=False).skills`. A third-party folder is
  read at its top level only, item by item (`<name>.md`, `<name>/SKILL.md`),
  never with `load_skills_from_dir`: its `rglob` would load the git cache
  (`.cache/`, whole repositories). Downloaded skills reuse
  `third_party_skills.py` with the folder's own `skills.lock.json`.
  `certo skills` loads config under `defer_llm_check()`: it needs no model.
- **`independent_tests.py`** — Phase 1.5's test writer and runner, wired
  into `stream_task` by `runner._write_independent_tests` (before the
  build: single path after the auto-model pick, escalation before rung 1
  with its model; not on resume or under Docker) and
  `_apply_independent_tests` (after the phases, inside the `try`, so the
  run records have it; the tests are copied to the run's artifacts folder
  when there is one, then the scratch folder is removed in the `finally`).
  Server mode forces it off (`server._resolve_cfg`). `write_tests(task, cfg, scratch, project=)` copies
  the project before the build into `scratch/project_before/` and runs a
  separate conversation (file editor + finish only, no `AgentContext`,
  `persistence_dir=None`, usage id `certo:test-writer`) that writes into
  `scratch/new_tests/` or leaves `NO_TESTS.txt`. `run_independent_tests()`
  checks the files' hashes and runs them with `bench_tasks.run_test_folder
  (clean_up=True)`; `report_line()` is the line under the verdict. The
  runner uses the set layer: `write_test_sets(count=)` writes each set in
  `scratch/set<k>/` with usage id `certo:test-writer`, `-2`, `-3`
  (threads unless the model is local), and `run_test_sets()` votes
  (`failed` at `failing_sets_needed(n)` = most sets, else `split`;
  one set returns its own result unchanged); `set_lines()` lists each set.
  `_apply_strict_independent_tests` (CERTO_INDEPENDENT_TESTS_STRICT) turns
  `verified` + `failed` into `independent_failed`, after the acceptance
  checks: single path after `_apply_acceptance_checks`, escalation after
  the final rung (it calls `state_writer.finish` again so STATUS.md has
  the final verdict; the rung record keeps the rung's own verdict).
- **`context_window.py`** — stdlib only. `ollama_context_tokens()`
  (empty `/api/generate` to load, then `/api/ps` `context_length`; cached
  per server and model, 10 minutes; `None` on any error) and
  `input_limit()`. `llm._context_kwargs` turns `cfg.llm_context_tokens`
  or the detected window into the SDK's `max_input_tokens` (read by the
  condenser's token trigger and the SDK's 16K check), sends a set window
  to Ollama as `litellm_extra_body.options.num_ctx`, and raises the SDK's
  `LLMContextWindowTooSmallError` with Certo's message under 16,384.
  Tests: `conftest.no_ollama_server` stubs the detection.
  `agent._condenser` attaches the SDK's `LLMSummarizingCondenser` (same
  LLM object, `max_size=CONDENSER_MAX_EVENTS` so only tokens or a
  context-exceeded error trigger it); `stream_task.on_event` counts
  `Condensation` events into `RunSummary.condensations` (also in each
  bench record) and emits a notice.
- **`checkpoints.py`** — stdlib only. A git repository at
  `.certo/checkpoints/` (`GIT_DIR`) with the project as work tree, its
  own `GIT_INDEX_FILE`, `GIT_CONFIG_GLOBAL=/dev/null` and
  `GIT_CONFIG_NOSYSTEM` (no user hooks or signing). `snapshot()` rewrites
  `info/exclude` (`SKIP_DIRS`, files over `MAX_FILE_BYTES`), `add --all`,
  commits unless the index matches HEAD. `rollback()` snapshots, then
  `read-tree --reset -u <commit>` (tracked files missing from the target
  are deleted; excluded files untouched), then commits the result.
  Numbers are positions in `git log --reverse`. The runner calls
  `safe_snapshot` through `_checkpoint` (before the agent, after
  `_write_independent_tests`; `_on_verification` per check run, prefixed
  with the rung under escalation; `finished:` at the end); `stream_task`
  turns `cfg.checkpoints` off when it keeps no state. Commands in
  `checkpoints_cmd.py`.
- **`check_files.py`** — stdlib only. `snapshot_check_files()` copies
  test files and check settings (`is_check_file`, by path) before the
  run; `runner._run_stream_task_phases` compares after a `verified`
  outcome (`check_file_changes`, line counts via `SequenceMatcher`) and
  adds `changes_note()` to the contract's limitations, plus
  `TaskOutcome.check_file_changes`. Pre-existing files only; report only.
- **`deadline.py`** — `stop_at_deadline()`, see `runner.py` above.
- **Path-triggered skills fire only on the file editor** (SDK
  `LocalConversation._touched_rule_path`, openhands-sdk 1.47): a rule
  fires when an `ObservationEvent`'s action has a `path` field matching
  the glob, i.e. `file_editor` view/create/edit. `cat package.json` or
  `npm install` in the terminal never fires it. Found 2026-10-31: the
  path-triggered `node-project-setup` fired in 0 of 9 Haiku runs on the
  Node tasks (the agent read `package.json` with `cat` and never edited
  it), so it became keyword-triggered. `pin-dependencies` has the same
  gap for `pip install`.
- **`update_check.py`** — stdlib only. `cli.main` wraps `_main`: it
  starts `update_check.start()` before the command (not for `bench`;
  `certo-server` and `certo-admin` don't call it) and prints
  `UpdateCheck.notice()` to stderr after it, waiting at most 0.5 s. The
  check reads the settings files into a copy of the environment, so
  `CERTO_UPDATE_CHECK=0` in a `.env` counts before `load_config` runs.
  PyPI's JSON API in a daemon thread (2 s timeout), cached a day in
  `update-check.json`; any failure means no line. Not a `Config` field:
  it isn't run policy, and every subcommand would have to pass it.
- **`text_tool_calls.py`** — stdlib only. `looks_like_tool_call(text,
  tools)` recognises a final message that is, as a whole, a tool call
  written as JSON (shapes from saved transcripts: bare arguments, the
  tool named under `name`/`tool_name`/`tool`/`tool_use`, OpenAI's
  `function` object, the tool's name as the key, the name under
  `command` next to `arguments`, a `tool_use`/`tool_result` block,
  cut-off JSON).
  `runner._remind_text_tool_call`, called in `_run_conversation_once`
  after each `conversation.run()`, sends `REMINDER` and runs again when
  the run FINISHED on such a `MessageEvent`: at most
  `CERTO_TOOL_CALL_REMINDERS` per conversation (`_TOOL_CALL_REMINDERS`,
  weak-keyed), once per event id, never past the deadline or the cost
  limit. Tool parameters come from `agent.tools_map[*].action_type`
  (initialized after a run), `DEFAULT_TOOLS` when unreadable.
- **`cost_limit.py`** — `CERTO_MAX_TASK_COST` during a run: a per-conversation
  limit (`set_cost_limit`, counting what was spent before), and
  `pause_at_cost_limit()`, a watcher that reads the SDK's
  `usage_to_metrics[*].accumulated_cost` every 2 s and pauses the
  conversation. `runner._budget_spent` turns it into `cost_exhausted` at
  the same points as the time budget.
- **`plugins.py`** — `foreign_plugins(workspace, projects_dir)`: the
  OpenHands plugins the SDK would load into a local run that don't belong
  to it (every user plugin; a project plugin from outside a generated
  project's folder), via the SDK's public discovery functions.
  `refusal()` is the error text. Called before a local run by `cli.py`,
  `server._resolve_cfg` and `bench_main` (user plugins only), which refuse
  to start; see the SDK gotcha below.

## Known limitations and traps

Internal and architectural; the user-facing ones are in `docs/`.

**SDK/tooling gotchas** (re-verify on any SDK upgrade — see CLAUDE.md golden
rule 2):
- **Every `LocalConversation` loads "ambient plugins", with no switch**
  (SDK 1.47.0, `conversation/impl/local_conversation.py`
  `_ensure_plugins_loaded`, about line 1111: `load_available_plugins(work_dir,
  include_user=True, include_project=True)`). User plugins come from
  `~/.agents/plugins/`, `~/.openhands/plugins/` (or `OH_PERSISTENCE_DIR`)
  and the installed store; project plugins from `.agents/plugins/` and
  `.openhands/plugins/` in the workspace **and at the git repo root**
  (`plugin/discovery.py:128-148`). A plugin can add skills, MCP servers and
  hooks. Found 2026-10-24 while verifying the test-writer conversation
  for independent tests. **Handled (check and stop):** `plugins.py` calls
  the SDK's public `load_user_plugins()` / `load_project_plugins()` before
  a local run (`cli.py`, `server._resolve_cfg`, `bench_main`) and refuses
  to start on a user plugin, or a project plugin from outside a generated
  project's folder. Nothing is patched. The discovery folders are module
  constants fixed at import (`discovery.USER_PLUGINS_DIRS`,
  `installed.DEFAULT_INSTALLED_PLUGINS_DIR`), so tests redirect them
  (`conftest.py`); a real-`Conversation` test checks that what the check
  finds is what the SDK loads.
- **`load_project_skills=True` also reads the git repo root's
  `AGENTS.md`/`CLAUDE.md`/`GEMINI.md`/`.cursorrules`**, not only the
  workspace's (SDK 1.47.0, `skills/skill.py` `load_project_skills`, via
  `_find_git_repo_root`), and `CLAUDE.md` only for Claude models,
  `GEMINI.md` only for Gemini (`context/agent_context.py`, vendor gating).
  So a project inside another repo gets that repo's file. Found
  2026-10-24: a `--escalate` run in this repo's `projects/` gave
  `claude-haiku-5-5` Certo's own `CLAUDE.md` (278 extra system-prompt
  lines); `qwen3-coder` on rung 1 got nothing. `certo bench` is not
  affected (workspaces in `tempfile.mkdtemp`). It also reads the repo
  root's `.agents/skills/`, `.openhands/skills/` and
  `.openhands/microagents/`. **Handled:** for a workspace inside `CERTO_PROJECTS_DIR`
  (a generated project; an existing folder keeps the SDK's behaviour),
  `skill_library.disabled_project_skills` lists every project skill whose
  `source` is outside the workspace, and
  `build_agent` passes it as `AgentContext.disabled_skills`, which the
  SDK applies after the lazy project load too (pinned by a real
  `Conversation` test). Name-based: the SDK prefers the workspace's
  same-named skill, so a foreign skill never has a local twin, but a
  repo-root skill named like one of Certo's own would turn Certo's off as
  well (no public way around it).
- **The terminal tool's `timeout` is in seconds, with no upper limit**
  (SDK 1.47.0, `openhands/tools/terminal/definition.py`). A model that
  means milliseconds waits hours: in the 0.1.23 baseline, `gpt-6-luna`
  sent `timeout: 10000` to wait on a shell it had closed with `exit`, and
  waited 2h47m. Certo neither caps it nor checks `CERTO_MAX_TASK_SECONDS`
  during a run (TODO.md, Smaller bugs).
- **Importing the SDK takes about 2 seconds.** `cli.py`, `verification.py`
  and everything they import at module level must not import `openhands`
  (or `runner`, `init_cmd`, `skills`, which do), so `certo --version`,
  `--help` and `certo verify` start in about 0.1s instead of 3s.
  `cli.py` reaches those modules through small wrappers (`run_task`,
  `init_main`, `check_main`, `run_sample_task`) that tests can still
  replace. `tests/test_cli.py::test_help_and_version_do_not_load_the_sdk`
  fails when a top-level import brings the SDK back.
- **Skill content can execute code.** `invoke_skill` runs
  `render_content_with_commands()` on a skill body, which executes every
  unescaped ``!`cmd` `` in a shell (confirmed live against v1.47.0). A
  `SKILL.md` directory's `.mcp.json` becomes MCP server config unless it is
  loaded with `skip_mcp=True`. `third_party_skills.py` and
  `skill_library.py` neutralize both for every third-party skill, added
  from a file or downloaded. Official skills are left as-is.
- `ConversationVisualizerBase.initialize` is `@final` (v1.47.0), so a
  visualizer that wraps another can't hand it the state its metrics line
  needs: `console.py` subclasses the default visualizer instead. The SDK
  reads `LOG_LEVEL` once, at import, and its loggers inherit from
  `openhands`; `quiet_sdk_logs` sets that logger to WARNING per run
  (not when `LOG_LEVEL` is set).
- `SubprocessTerminal.close()` closes the PTY master fd while the reader
  thread may sit in `select()` on it; the thread then logs `PTY reader
  thread error: [Errno 9]` with a traceback (v1.47.0). Harmless. runner.py
  filters exactly that record (EBADF only) on the SDK terminal's logger.
- `find_skill_md_directories()` only checks direct children of a skills dir
  (`SKILL.md` one level deep), while `find_regular_md_files()` `rglob`s.
  So any `.md` under a folder given to `load_skill_catalog()` loads as a
  legacy skill; third-party folders are therefore read item by item.
- `CERTO_MAX_ITERATIONS` was parsed but never wired to `Conversation` until
  caught while adding the verification retry loop — **closed**, with a
  regression test asserting `Conversation(max_iteration_per_run=...)` is
  actually called (confirmed it fails without the fix).
- Spec's original custom-tool template didn't match the installed SDK
  (v1.47.0, now pinned exactly): `ToolDefinition` is subclassed with a
  `create(cls, conv_state, **params)` classmethod, not built via a factory
  returning instances.
- `get_default_tools()` lives at `openhands.tools.preset.default`, not
  re-exported from `openhands.tools.preset`.
- **The terminal's extra environment is `Tool(name="terminal",
  params={"env": {...}})`**, passed to `TerminalTool.create(conv_state,
  env=...)` and merged over the inherited environment by
  `build_terminal_env` (`openhands/tools/terminal/definition.py`, `env.py`,
  `terminal/subprocess_terminal.py`). `sanitized_env` keeps `PATH` and
  `VIRTUAL_ENV`. **Under tmux, `PATH` from `env` is ignored**: the pane
  pool sets it as session environment, but a new window takes `PATH` from
  the tmux client, Certo's own process. Confirmed live on macOS: a marker
  added to Certo's own PATH appeared in the pane, the venv's `bin/` didn't.
  Certo therefore forces `terminal_type="subprocess"` whenever it passes an
  env.
- `file_editor` requires absolute paths; does not resolve relative to the
  workspace.
- The SDK's `LLM(...)` constructor raises `LLMContextWindowTooSmallError`
  when LiteLLM reports a context window under 16K (e.g. `ollama/llama3`).
  This happens at build time, not call time. A direct `completion()` lets
  LiteLLM's `NotFoundError` (unknown model id) through unmapped: it is not
  an `LLMError`.
- `python-dotenv` does not strip a trailing `# comment` from an otherwise-blank value.
- `sys.executable` inside the PyInstaller-frozen Docker image resolves to
  the frozen binary itself, not a Python interpreter (`_python_command()`
  works around this).
- **A `Message`'s `role` does not indicate where its text lives** — an
  `assistant`-role tool-call message has empty `content`; the actual text
  (including the final "finish" message) comes back as a `tool`-role
  message. Caught only by a live run, not by tests built on the same wrong
  assumption. Any future code reading `Message.role` to find "the answer"
  should exclude only `system`/`user`, not filter to `assistant`.

**The "confident but wrong agent" family** — variants found live (plus
one requested proactively), each root-caused and fixed; see `docs/ROADMAP.txt`
for full transcripts if a fix needs revisiting:

1. **Plain-text reply ends a run exactly like `finish`, no error** — the SDK
   sets `FINISHED` whenever the LLM replies with text and no tool call,
   indistinguishable from a real `finish` (confirmed by reading
   `response_dispatch.py`). Confirmed live twice (asked for confirmation
   instead of building; declared 1-of-6 tracker items "done"). Fix:
   `_AUTONOMOUS_SUFFIX`. `CERTO_INTERACTIVE=yes` is the opt-in escape
   hatch. **Status: fix applied, not re-verified live since.**
2. **Agent runs an interactive CLI tool, the prompt silently auto-cancels
   with no TTY, agent doesn't notice and re-runs the identical command** —
   confirmed live (`npm create vite` interactive prompt, 200K+ tokens
   burned re-running it). Fix: `_NONINTERACTIVE_TOOLING_SUFFIX`. **Status:
   re-verified live 2026-10-19 (0.1.19, claude-sonnet-4-5, a Vite React
   task): `npm create vite@latest . -- --template react` auto-cancelled
   twice (the second time piped through `yes`, a changed command, not a
   repeat); the agent then named the cause and wrote the files by hand.
   `verified` in 6m27s, $0.54. The cause it named was Certo's own `.certo/`
   making the folder non-empty (see TODO).**
3. **Agent called `finish` admitting known failures, with an invented wrong
   diagnosis** — confirmed live (Hanoi: blamed "sequence handling," the file
   actually had a literal `IndentationError` and never parsed). Fix (two,
   since prompt-only looked insufficient): `_VERIFY_BEFORE_FINISH_SUFFIX`
   plus `runner.py`'s harness-side `_verify_tests_and_retry()` (real,
   no-LLM re-run). **Status: both applied; the harness-side fix confirmed
   against the actual broken repro; not re-verified as a full live run.**
4. **Same pattern, non-Python project, pytest-based verification blind to
   it** — a Vite/React JSX parse error; pytest reported "no tests
   collected" as a false pass. Fix: generalized to run `npm run build` for
   a detected Node project. **Status: re-verified 2026-10-19 against the
   original repro's shape: a live-built Vite React app (`npm run build` +
   `npm test`, `verified`), then one closing `</div>` removed from
   `App.jsx` — `npm test` still passed, `npm run build` failed with
   esbuild's "Unexpected end of file before a closing \"div\" tag", and
   `certo verify` said `failed`, exit 1.**
5. **The verification loop couldn't tell "confirmed working" from "found
   nothing to check," and had no visibility into a `STUCK`/`ERROR` run** —
   fixed with the five-state model (`verified`/`failed`/`inconclusive`/
   `retry_exhausted`/`stuck`) and checking `execution_status`. **Status:
   applied, unit-tested with a fake `Conversation` forcing the real SDK's
   `STUCK`/`ERROR` enum values; not re-verified against a real stuck run.**
6. **Every verification concept was implicitly Python/Node-only** — rebuilt
   around the four named stages and the five-value `CheckOutcome.status`
   enum described above, covering Go/Rust/Java. **Status: applied,
   unit-tested per stage plus real-subprocess runs for every toolchain
   installed in this dev environment. Go and Rust re-verified live end to
   end 2026-10-19 (claude-sonnet-4-5): a `wordfreq` CLI ran `go test ./...`
   + `go vet ./...`, a `tempconv` CLI ran `cargo test`/`check`/`clippy`,
   both `verified` (2m33s $0.37, 2m37s $0.39), and both programs behaved
   as asked when run by hand. Java still not run end to end (no Maven or
   Gradle installed here).**
7. **Agent repeatedly re-edited already-correct code chasing a wrong test**
   (Hanoi: the test's own state assumption was wrong, not the
   implementation) **and its diagnostic prose degraded into fluent but
   empty text**, which the SDK's `stuck_detection` didn't catch (it only
   flags exact repetition). Fix: (a) lifecycle skills now say to prove a
   test wrong against its own captured state trace before a second
   re-edit; (b) a new `no_progress` terminal state stops the retry loop the
   moment a fix attempt provably changes nothing in the verification
   output. **Status: (b) applied and verified against the actual on-disk
   repro; (a) is prompt-level, not mechanically testable.**
8. **A generated Hanoi program passed every unit test genuinely, but
   crashed the instant a user picked the interactive `SOLVE` option** —
   `solve()` was defined *after* the `__main__` guard, so `import`ing it
   (what the test does) never hit the `NameError` a direct run does
   immediately; pytest structurally cannot see this bug. Fix: a static
   AST `entrypoint-ordering` check plus a `python <entry point>` smoke-run
   (closed stdin) — the smoke-run alone can't reach `SOLVE` itself;
   `entrypoint-ordering` is what actually catches this bug class. **Status:
   applied; verified against the actual repro (entrypoint-ordering fails
   with the precise diagnosis while pytest passes) plus a synthetic
   regression fixture; now also re-verified against a fresh live agent run
   end to end (`test_run_task_catches_entrypoint_ordering_bug_live`,
   `tests/test_runner.py`) — closes the "not yet re-verified live" caveat.**
9. **The harness's own verification depended on the dev environment.**
   Repro: Certo 0.1.0 from `uv tool install certo`, `ollama/qwen3-coder:30b`,
   `certo "Create hello.py that prints hello, plus a pytest test for it"
   --project smoke`. Verification ran pytest with Certo's own interpreter
   (`~/.local/share/uv/tools/certo/bin/python`), which has no pytest. The
   agent then ran `<that python> -m pip install pytest`, an attempt to
   install into Certo's own environment that failed only because there was
   no pip. It then hacked the code around the problem, and the run ended
   `no_progress`. Invisible from the dev venv, where pytest is a dev
   dependency. Fix: `project_env.py`, a per-project environment shared by
   the agent's terminal and verification, with pytest installed into it
   when tests need it, and nothing ever run with or installed into
   `sys.executable`. Plus `scripts/release_check.sh`, which installs the
   built wheel with `uv tool install` and runs `certo verify` on fixtures
   before every release. **Status: applied. Unit-tested, terminal
   resolution checked against the real SDK terminal, and the release check
   passes against a real tool install. The live task is re-run only by
   `release_check.sh --with-llm`.**
10. **A run that changed nothing was `verified`.** Found by the first
   complete `certo bench` (2026-10-17, 0.1.13): the `ladder` arm's
   `inventory-fix` run on `ollama/qwen3.8:27b` ran 4.6 minutes, 117k input
   tokens, and left the workspace byte-for-byte the starter; the starter's
   own tests pass, so Certo said `verified` and the hidden tests failed
   (`ImportError: OutOfStock`). Not known whether the agent stopped early
   or wrote elsewhere: bench kept no transcript. Fix (0.1.14): the
   `unchanged` verdict (`runner._require_a_change`), one follow-up first.
   **Status: applied and unit-tested; not re-run live.**

