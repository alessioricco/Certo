# Decisions log

Why key choices were made: each entry is the decision plus the
load-bearing reason, so a future session doesn't re-litigate or
rediscover it. Append-only: a later decision that changes an earlier one
says so ("supersedes ...") rather than editing it away.

> **Full history:** every entry through 2026-09-20 is a compressed
> summary. The complete narrative (alternatives considered,
> live-verification transcripts, exact quotes) lives in
> `docs/history/ROADMAP.txt` (a frozen snapshot) and in git history.

Each entry is the decision plus the load-bearing reason. Full alternatives
considered and live-verification detail: `docs/history/ROADMAP.txt`.

- **Acceptance criteria: `file_exists`/`file_contains` only, no
  command-exec kind.** An unauthenticated server caller triggering
  harness-run commands would be a strictly worse surface than the agent's
  own gated terminal tool. Own path-containment impl (mirrors
  `resolve_project_dir`, kept separate — different error-message
  contracts). 1MB read cap on `file_contains`. New `"acceptance_failed"`
  state applied once at the end of `stream_task`, not retried, not on
  `/v1/chat/completions` (no field for it there).
- **Global task budget: wall-clock (`CERTO_MAX_TASK_SECONDS`), not
  iteration counting.** The SDK resets its iteration counter on every
  `conversation.run()` call (confirmed in source) and exposes no way to
  read back consumed iterations; event-counting is provably inexact (a
  plain-text finish produces no `ActionEvent`). Checked in
  `_run_with_confirmation()` before every `.run()` call, and once at entry
  to both retry-loop functions. Default `1800`s, on by default (a safety
  backstop, not a behavior fork).
- **`--require-verification`: opt-in, default unchanged.** Flipping the
  default (`inconclusive` exits `0`) would break existing scripts/CI.
  Threaded through CLI + native REST/WS, not `/v1/chat/completions` (no
  `verification_state` field there to act on).
- **`resolve_project_dir()` closed a real security bug**, not just added
  hardening: `os.path.join(a, b)` silently discards `a` when `b` is
  absolute, so `--project /etc/cron.d` (or the same field in an
  unauthenticated `POST /tasks`) redirected the whole workspace to an
  arbitrary host path; `..` had the same effect. Fixed with string-level
  rejection *and* a resolved-path (`realpath`) containment check — the
  second layer is needed because a plain name with no `..` can still be a
  symlink escaping `projects_dir` (verified live with a real symlink).
  Deliberately doesn't defend against a TOCTOU race (no realistic threat
  here).
- **`CERTO_CONFIRM_MODE=always`**: mechanics (`AlwaysConfirm`,
  `get_unmatched_actions`, `reject_pending_actions`) verified against SDK
  source before wiring. `_run_with_confirmation()` wraps all three
  `conversation.run()` call sites. No handler (server mode) rejects once
  and returns a new `"confirmation_required"` state rather than
  auto-approving or looping. Known accepted gap: each resumed `run()` call
  gets a fresh iteration budget from the SDK.
- **Task-tracker completion enforcement reads live `conversation.state.events`,
  not the tool's `TASKS.json`** — confirmed the harness's `Conversation(...)`
  call never enables persistence, so that file is never written in normal
  operation. New `"incomplete"` state short-circuits *before* project
  verification (an unresolved tracker means completion was never
  established). Reuses `cfg.max_verify_retries` rather than a new knob. An
  unused or already-`done` tracker is not a violation.
- **Pinned `openhands-sdk`/`openhands-tools` to `==1.47.0` exactly**, not a
  range — this project's verify-first posture depends on not trusting SDK
  symbols we haven't re-checked; a floating range would silently
  reintroduce that risk on a routine install.
- **Docker execution: custom Dockerfile**, not the SDK's `DockerDevWorkspace`
  (scoped to the SDK's own dev environment) or a raw pass-through
  (`register_tool()` only affects the calling process, not the container's
  separate agent-server process).
- **Server mode: both async submit+poll and WS streaming** — a single
  blocking `POST` forces clients to hold an unbounded connection open. Both
  share one background-thread+callback pattern.
- **Skills: two separate mechanisms, not one "smart" one.** Rejected an
  LLM-based skill picker — the SDK's own `KeywordTrigger`/`PathTrigger`
  matching already does this deterministically for free. Kept the shared
  catalog (reusable expertise) and per-project `AGENTS.md` (one project's
  facts) as genuinely different concerns.
- **CLI `task` stays one positional with content-sniffing** (URL/file/literal),
  deliberately not extended to the server — a CLI user benefits from
  avoiding shell tricks; a REST/WS caller is already writing code and can
  fetch content itself.
- **Per-request LLM override on the OpenAI adapter uses separate
  `llm_model`/`llm_api_key`/`llm_base_url` fields**, not the wire-mandated
  `model` field — a strict client may set `model` to an arbitrary
  non-LiteLLM string. `TaskRequest` uses plain `model`/`api_key`/`base_url`
  directly. Both end in one shared `config.override_llm()`.
- **Autonomous-behavior fixes are `system_message_suffix` policies, not
  `runner.py` control flow** — a control-flow "auto-continue" treats the
  symptom (the run stopped) without the cause (model uncertainty), and
  would likely just loop into another clarifying question.
- **Per-project `README.md` requirement is a prompt instruction
  (`_README_SUFFIX`), not a harness-generated template** — the harness has
  no idea what's about to be built; the agent is the only party that knows.
  No harness-side check that a README was actually written (soft
  instruction, like the autonomous fix).
- **Harness-side test verification was built together with its prompt fix**,
  unlike the other autonomy fixes — this symptom (an invented, plausible
  wrong diagnosis) is the model being factually wrong about its own state,
  which a "please verify" prompt cannot fix; only re-running the code can.
  Reuses the SDK's `send_message()`-then-`run()` re-entry (confirmed this
  resets `FINISHED`/`STUCK` back to `IDLE`) so retries keep prior context.
  Bounded by `CERTO_MAX_VERIFY_RETRIES` (default `2`).
- **Five SDLC skills were downloaded, not authored**, from
  `addyosmani/agent-skills`, per explicit instruction to source real
  content — each renamed (dir + frontmatter) to satisfy the SDK's
  strict-mode validation. **Superseded** by the 8-skill lifecycle set below.
- **`run_tests` v1 generalization: detect pytest vs. Node `npm run build`**,
  not a full test-runner-detection rewrite — `npm run build` catches
  "doesn't compile" bugs a project's actual test runner might not cover,
  with no per-framework parsing needed. Defaults to pytest when neither
  marker is found, to avoid changing behavior for this repo's own tests.
- **Verification loop rework: five-state model + `CompletionContract` +
  `TaskOutcome`/`TaskResult`**, not another incremental patch — needed to
  represent `"inconclusive"` as distinct from `"verified"` (no tests ≠
  proof of correctness) and to aggregate multiple checks. `TaskResult`
  subclasses `list` so every existing caller keeps working unchanged.
  `"failed"` is a transient internal state only, never a final
  `verification_state`. Surfaced through CLI exit codes and server
  TaskRecord/WS, deliberately not `/v1/chat/completions`. Lint/typecheck/
  npm-test are opt-in by project config, never invented; a configured-but-
  not-installed tool is a limitation, not a failure.
- **Language-neutral verification (4 stages + `CheckOutcome` enum)**
  replaces a hardcoded 2-outcome tuple, because "checkable but tool not
  installed" is the *common* case for 3 of 6 languages, not an edge case.
  `timed_out` is a genuinely new terminal state, retried like a failure but
  distinguished from `retry_exhausted` if still timing out after retries.
  Go/Rust/Java got unconditional standard commands only where the
  ecosystem has one true convention; Java has no secondary checks (no one
  standard lint/typecheck tool). Java is honestly detection-only here and
  in the Docker image.
- **Lifecycle skills (8, legacy `triggers:`/`paths:` format) replace the
  earlier 5 downloaded `SKILL.md` skills** — legacy format was required
  because `SKILL.md` has no trigger frontmatter at all (confirmed in
  source: it's always menu-listed, `invoke_skill` is the only access
  path), and a legacy skill with a trigger is *also* still menu-listed, so
  switching cost nothing on discoverability while adding real triggering.
  Content authored fresh, not downloaded, because it states this harness's
  own architecture directly (AGENTS.md mechanism, sibling skill names,
  this project's `TaskOutcome` vocabulary) — no external generic skill
  could state these correctly; the "download, don't invent" rule applies
  to generic reusable expertise, not project-specific facts. Old `SKILL.md`
  dirs for the 4 overlapping names were deleted, not left alongside —
  confirmed live that leaving both caused `load_skill_catalog()`'s
  dict-merge to silently drop the new content. Known limitation:
  `KeywordTrigger` matching is approximate (relevant-but-unworded tasks
  miss the trigger; broad shared words fire incidentally).
- **`no_progress` detection compares structured verification output across
  retries**, not the agent's own message text — no reliable cheap way
  exists to score "does this text still make sense," and output comparison
  also catches a *coherent* agent stuck on an ineffective fix. Fires after
  exactly one no-progress retry (given the default budget of 2, requiring
  two would be nearly vacuous). New terminal state, not folded into
  `retry_exhausted` — "kept changing" and "provably changed nothing" are
  differently-actionable signals.
- **Entry-point checks: both a static AST check and a real smoke-run**
  (user's explicit choice) — static-only misses non-ordering startup
  crashes; smoke-run-only can't see *why* it crashed and (stdin closed)
  can't even reach an interactive branch. Explicitly rejected guessing
  input to drive the interactive session — no general safe way to guess
  what an arbitrary generated program expects. `CheckSpec.precomputed`
  added as a general, reusable extension, not a one-off bypass.
  `stdin=DEVNULL` made the default for every check, closing a latent hang
  risk globally. Entry-point discovery was later made recursive, reusing
  `detect_project()`'s own `_SKIP_DIRS`/depth-limit walk plus one new
  `tests`/`test`-excluding set (a test file's own `__main__` guard isn't
  the program's real entry point).
- **`reasoning_effort` added as a 5th per-request override field**, reusing
  `override_llm()` — the SDK's own field is documented provider-neutral and
  forward-compatible, unlike the other reasoning knobs considered
  (OpenAI-specific, or legacy-Anthropic-only). Deliberately not validated
  against a fixed choice list (the field is intentionally open-ended).
  `build_llm()` only passes it when set, since an explicit `None` would
  silently override the SDK's own `"high"` default.
- **Task-store persistence: pluggable `TaskStore` ABC, 5 backends**, not
  just a TTL purge — scope expanded per user request. SQLAlchemy Core for
  all 3 SQL backends (one shared implementation, upsert via
  try-UPDATE-then-INSERT). Delete-by-project exposed via both REST and CLI
  (different callers need different access). Redis uses native per-key
  TTL, not a purge sweep. `MemoryTaskStore` deep-copies on save/get (a real
  bug self-caught once the coarse lock was replaced by per-backend
  locking). `create_app()` builds the store once at startup — deliberate
  fail-fast over a broken `.env` silently 500ing on first request.
  mysql/postgres verified live against real Docker containers but excluded
  from the automated suite (too heavy a CI requirement); sqlite/redis are
  tested for real.
- **Monorepo ambiguity: new `"ambiguous"` `ProjectDetection` state**,
  fixing a real bug — `detect_project()`'s claimed "shallowest wins" wasn't
  actually true across different DFS branches (`os.walk` fully explores a
  first-visited branch before a shallower sibling). Fixed by grouping
  matches by depth during one walk. The workspace root (depth 0) is always
  returned immediately and never "ambiguous" — an explicit `--project`
  already told the harness what the project is. Resolves to the same
  synthetic `"unavailable"` shape already used for `"unknown"` — no
  `runner.py`/`CompletionContract` changes needed.
- **Interactive mode (`CERTO_INTERACTIVE`): checkpoint wraps only the
  initial run**, not the task_tracker/verify retry loops — the smallest
  change covering the two failure modes already on record, without the
  real design question of how a human reply should interleave with the
  harness's own automated retry follow-ups. `CERTO_MAX_TASK_SECONDS` is
  paused (not spent) while blocked on a human reply. No new suffix added —
  only `_AUTONOMOUS_SUFFIX` is dropped when interactive. Has no effect
  without a caller-supplied callback (`server.py` never supplies one).
- **Deterministic auto model selection (`CERTO_MODEL_SELECTION=auto`)**:
  deterministic weighted scoring, not an LLM router — no extra model call,
  consistent with the earlier skills decision. One static ranked list
  computed once per task, walked forward under failure, never re-scored
  (the resulting caveat — fallback picks next-best-fit, not necessarily
  more capable — is documented, not solved). Real API keys live directly
  in `models.yaml` (gitignored like `.env`). Visibility:
  `MODEL_DECISIONS.md` in the project workspace plus
  `TaskOutcome.model_decisions`. Docker gets the initial pick but not
  mid-task fallback — `RemoteConversation`'s Python client doesn't expose
  `switch_llm` even though the remote agent-server's REST API does;
  documented rather than built against private SDK internals. The
  retriable exception type is the SDK's own `LLMError` hierarchy — took two
  rounds of live verification to find (not `litellm.exceptions.APIError`,
  not `openai.OpenAIError`, both invisible once the SDK wraps LLM-call
  failures itself). `write_model_decisions()` runs in the whole task's
  `finally` block after a live-caught bug: an exhausted fallback chain
  previously raised before the file was ever written.
- **Per-run artifacts directory (`CERTO_ARTIFACTS_DIR`): a separate
  sibling top-level directory**, not nested inside each project — mirrors
  `CERTO_PROJECTS_DIR`'s shape. `conversation.conversation_stats`/
  `usage_to_metrics` (confirmed in SDK source) gives a full per-model
  cost/token breakdown for free, since model-selection candidates already
  have distinct `usage_id`s. `MODEL_DECISIONS.md` stays put (not moved
  here). A run ID is minted by `stream_task` when none is given;
  `server.py` passes its own `TaskRecord.id` instead. A live-caught bug:
  artifact-writing was moved into the same `finally` block as
  `write_model_decisions()` after an exhausted model chain was found to
  raise before anything was written.
- **`models.yaml` gained a per-model `activated` (bool, default `true`)
  field**, filtered in `rank_candidates()` (not at load time, so a
  deactivated entry still gets schema validation and the duplicate-name
  check). Raises a specific error if every model ends up deactivated.
- **Excluded the 3 third-party `SKILL.md` directories** (`frontend-design`/
  `webapp-testing`/`web-artifacts-builder`) via `.gitignore` + `git rm
  --cached` (untracked, not deleted) — each actually carries Apache-2.0,
  not MIT as MANUAL.md had claimed (fixed in the same change). Scoped only
  to the 3 directories with their own `LICENSE.txt` — the lifecycle/git/
  python-web/testing skills are authored for this project.
- **Project renamed ARICode → Certo, deep and final** (supersedes the
  earlier `coding-agent-harness` → ARICode rename, which deliberately
  changed branding only and kept `import certo`/`CERTO_*`/
  `certo-admin`). This one renames the brand (docs, `pyproject.toml`
  name, `server.py` title/`owned_by`, Docker image tag
  `certo/agent-server:local`) and links (GitHub redirects the old repo URL).
  Console scripts are `certo`/`certo-server`/`certo-admin`; the old
  `harness*` aliases were later removed (see the entry below).
  The package moved `src/harness/` → `src/certo/` (`import certo`,
  `python -m certo`, Docker `--import-modules certo.custom_tools` with
  `OH_EXTRA_PYTHON_PATH=/certo_src`); no import shim for `harness` — the
  package was never published, so nothing outside this repo imports it.
  Env vars `HARNESS_*` → `CERTO_*`, all read through `config._read()`:
  a non-blank `CERTO_` value wins, else a non-blank `HARNESS_` value is used
  with one `logging` warning per variable per process. Blank = unset on
  both sides, so blank `CERTO_` lines from a fresh `.env.example` can't
  mask an old setting. Error messages quote the variable actually read.
  Storage names: sqlite default `certo_tasks.db`, table `certo_tasks`,
  Redis prefix `certo:`, mysql/postgres default DB `certo`, LLM `usage_id`
  `certo`/`certo:<model>`, and agent-facing notices say `Certo …:`. Compat
  reads exist only where a user may have data: legacy sqlite default file
  (only when the path is the default), legacy table (used as-is, never
  auto-renamed — that's the operator's call), legacy Redis keys (read
  fallback, migrated on save). No fallback for the DB name: a wrong DB
  fails loudly and the fix is one env var. `usage_id` changes are
  unversioned, since they're only per-run telemetry keys. The
  third-party skills lockfile never carried the old name.
  The GitHub repo is renamed (`alessioricco/certo`) and Certo is on PyPI
  since 0.1.0; `docs/launch/github-rename.md` is the historical checklist. `docs/history/ROADMAP.txt` is a
  frozen snapshot, so it keeps the old names on purpose.
- **Live entrypoint-ordering/smoke-run test built its own throwaway
  `tmp_path` fixture, not `projects/hanoi/` or anything under `projects/`**
  — that directory is user-managed runtime state the harness must stay
  agnostic to, not a stable test fixture (a standing project convention,
  not new to this change). The task explicitly instructs the agent not to
  touch the pre-planted buggy `app.py`, so the test's decisive assertion
  (`retries_used >= 1`) reliably comes from the harness's own automated
  verification catching it, not from the agent noticing it unprompted.
  Verified live: the agent left the fixture untouched, the harness's
  post-hoc verification caught the entrypoint-ordering failure (pytest
  alone had already passed), sent the automated follow-up, and the agent
  fixed it — final state `verified` after exactly 1 retry.
- **Third-party skills: own lockfile + SDK fetch, not the SDK's
  `InstallationManager`.** The SDK manager marks a new install
  `enabled=True`, and its `discover_untracked()` auto-enables any directory
  dropped into the install root. Both contradict the explicit-opt-in rule.
  It also records no license or integrity. Its
  `fetch_skill_with_resolution` (subpath containment, SHA resolution, full
  clone for a pinned SHA) and `Skill.load` are reused as-is. Enablement is
  enforced twice: at `enable` (CLI) and again at load (the lockfile is
  hand-editable). `update` disables on any content/license change. `sync`
  refuses a hash mismatch. Commands live under `certo-admin skills`,
  the existing argparse subcommand CLI, rather than a new entry point. The
  lockfile is JSON beside the gitignored dir, not in it, so it can be
  committed for reproducibility. Existing hand-placed
  `skills/frontend-design/` etc. are deliberately left loading as before
  (no silent behavior change); `install` refuses those names instead.
- **Run summary uses per-`usage_id` metrics, not the SDK's combined
  metrics** — the combined entry's model is `"default"`; each per-usage
  entry carries the real model name. Always computed (not gated on
  `CERTO_ARTIFACTS_DIR`), and read defensively in the `finally` so a
  metrics failure can't mask the run's own outcome or exception.
- **sdist is an explicit allowlist (`src/certo`, `tests`, the Dockerfile,
  README/MANUAL/LICENSE, `.env.example`, `bench.yaml.example`; the model
  examples ship inside `src/certo/examples/` since 0.1.10) plus
  explicit secret/state/cache excludes on both targets** — hatchling's
  default sdist relied on `.gitignore` alone to keep `.env`/`models.yaml`/
  `projects/` out, and shipped dev-only files (`.claude/`, `CLAUDE.md`,
  `todo.md`, `docs/`, `uv.lock`). Verified by building a copy with no
  `.gitignore` and planted decoys: none shipped. `tests/test_packaging.py`
  enforces the allowlist and the forbidden patterns.
- **First-party skills moved into the package (`src/certo/builtin_skills/`)
  and always load; `CERTO_SKILLS_DIR` (still `./skills`) became an
  additive user catalog that overrides built-ins by name.** A clean-venv
  wheel install proved the old cwd-relative `./skills` default loaded zero
  skills outside a repo checkout (nothing outside `src/certo` is in the
  wheel). Named `builtin_skills`, not `skills`, so it doesn't sit beside
  `skills.py`. Additive rather than "one dir replaces the other" so the
  README's drop-a-file workflow and hand-placed `skills/frontend-design/`
  copies keep working unchanged. `tests/test_packaging.py` builds the real
  sdist→wheel and checks the catalog ships.
- **`harness`/`harness-server`/`harness-admin` console aliases removed
  before the first PyPI release** (supersedes "they cost nothing" in the
  rename entry). There are no external users, and a globally installed
  `harness` could shadow another tool on a user's PATH. The `HARNESS_*`
  env-var fallback and legacy storage reads are unaffected — those protect
  local data, not command names. `tests/test_cli.py` asserts the declared
  and installed scripts are exactly the three `certo*` commands.
- **Release workflow: `verify` → `build` → `publish` jobs, trusted
  publishing only.** A PyPI version can never be reused, so the tag must
  equal `pyproject.toml`'s version and the suite must pass before anything
  is built; only the `publish` job (environment `pypi`) gets `id-token:
  write`, and it uploads exactly the artifact the `build` job checked with
  `twine check`. No ruff gate yet: `main` currently has lint/format
  findings. Tests asserting a tool is *absent* (`mvn`, `mypy`) now skip
  when it's installed, since GitHub's Ubuntu runner ships Maven.
- **`sqlalchemy` is in the `dev` extra, not `importorskip`-guarded** — the
  sqlite `SQLTaskStore` tests are the only automated coverage of the code
  path shared with mysql/postgres, so a plain `.[dev]` install must run
  them rather than silently skip them.
- **An unset reasoning effort means none for Ollama models; `none`/`off`
  pass an explicit `None`.** The SDK default `"high"` reaches Ollama as
  `think: true`, and Ollama rejects it for any model without a thinking
  mode (`qwen3-coder:30b`, the README quickstart model), failing the first
  call. Passing the string `"none"` through still sends `think: false`, so
  it becomes `None`, which the SDK's chat options skip entirely. That
  gives up OpenAI's literal `reasoning_effort="none"`: that request now
  gets the API's own default instead (accepted, per the user's request).
  Matched on the `ollama`/`ollama_chat` model prefix: only the default
  changes, never the provider. `tests/test_llm.py` asserts the wire request
  against a local fake Ollama that returns the real 400. The bug reproduces
  there with the old `build_llm`.
- **A Python project gets its own environment, shared by the agent's
  terminal and verification; Certo's own environment is never used.**
  Verification used `sys.executable`, which only had pytest in the dev
  venv (see "confident but wrong" #9). An existing environment is always
  reused before one is created: `uv.lock` through `uv run`, then
  `.venv`/`venv`. Only Certo-made venvs (marker file) are ever rebuilt; a
  broken user venv makes pytest `unavailable`, never deleted. pytest is
  auto-installed into the project environment only when test files exist,
  and a failed install is `unavailable`, not `failed`: a missing runner is
  a limitation, not a test failure. ruff/mypy are not auto-installed. They
  count only when installed in the project environment, since one on PATH
  says nothing about the project's own config. An empty workspace gets an
  environment up front only if the task names Python: creating one for
  every empty workspace would litter Node/Go projects.
- **Under `--execution docker`, verification runs inside the container
  (user's choice), not on the host.** A venv is tied to the OS that made
  it (interpreter symlinks, binary format), and the agent installs
  dependencies into the container's. Host-side verification could never
  see them: it already used Certo's own host interpreter before this
  change, so Docker verification of any project with dependencies was
  broken. Rejected: a separate host venv (same blindness) and local-only
  (leaves Docker broken). Detection/planning still read files on the host
  via the bind mount; commands go through `WorkspaceRunner` →
  `execute_command`. **Not run against a real container yet**: the Docker
  daemon wasn't usable in the session that built it. Covered by fake-
  workspace unit tests only.
- **`certo verify` is dispatched on `argv[0] == "verify"` exactly, before
  argparse** (user-approved). Subparsers would make a task positional and
  a subcommand compete, and argparse would reject or misroute existing
  task invocations. A task is one argument, so "verify the login flow"
  can't match. The only input whose meaning changed is the one-word task
  `verify`, still reachable as `certo -- verify`. It lives in `certo`, not
  `certo-admin`, because it's the user-facing check, not store
  maintenance.
- **Release check installs the wheel like a user (`scripts/release_check.sh`)
  and gates publishing on it**, because the pytest suite runs inside the dev
  venv and structurally can't see "works only in the dev venv" bugs. Bash,
  not Python: it must not run inside any Certo-related interpreter. It runs
  in the release workflow's `build` job against the exact `dist/*.whl`
  that `publish` uploads. There is no pull-request CI workflow to attach it
  to yet. The dependency fixture asserts its package is *not* importable
  from Certo's tool env, so a pass can't come from Certo's own packages.
  Since 0.1.4 it also runs `certo init --yes --no-check` (provider keys
  unset) and checks the files, the overwrite refusal, `certo check`'s
  missing-key message and the no-terminal `.env`: `init` reads package
  data, which only an installed wheel proves is shipped. Since 0.1.5 the
  whole script runs with a throwaway `XDG_CONFIG_HOME`; `init --yes` must
  write the user file and `certo check` from another folder must name it
  as the source, and `init --yes --local` covers `FOLDER/.env`.
- **Versioning: every feature bumps the third digit, in the same commit**
  (user's rule; full text in CLAUDE.md). The first two digits move only on
  the user's decision. The version is written literally in
  `pyproject.toml` and `certo/__init__.py`, not read from installed
  metadata, because the Docker image imports `certo` from source with no
  dist-info. `tests/test_version.py` keeps those two and `uv.lock` equal.
  `--version` is on all three commands. `certo-server` parses its
  arguments before importing uvicorn, so `--version` works without the
  `server` extra. `--version` was the first feature under this rule
  (0.1.1 → 0.1.2), and the `CERTO_LLM_` rename made it 0.1.3. 0.1.2 was
  never published on its own.
- **LLM settings renamed `LLM_*` → `CERTO_LLM_*`, with no fallback** (user's
  choice, 0.1.3). The bare names are generic, and other tools set them too.
  Unlike the `HARNESS_*` rename, the old names are never read, because a
  fallback would still let another app's `LLM_MODEL` leak in. They are only
  named, never echoed, in the "required" `ConfigError`s
  (`config._old_llm_names_hint`), so a 0.1.0/0.1.1 setup gets told what to
  rename. The SDK itself never reads `LLM_*` (checked: no reference in
  `openhands/`), so `config.py` is the only reader.
- **`certo init` is interactive, with no `--api-key` flag, and keeps model
  defaults in one data file** (0.1.4). Most first-run failures were model
  setup (wrong address, missing key, a rejected setting), so init asks only
  what `.env` needs and ends with a real tool call, which is what the agent
  needs; a plain text reply would pass a model that then stalls the agent.
  The check goes through `make_llm_completion`, the agent's own call, so
  Responses vs Chat Completions and prompt-based tool calling match a run.
  A key comes from `getpass` or the provider's own exported variable, never
  argv (shell history), and an exported key is written as `${VAR}` rather
  than copied. Without a TTY nothing is asked, so scripts and CI never hang.
  Defaults live only in `starter/providers.toml`, each with its `source`
  and `checked` date. They were picked from each provider's model page and
  confirmed in LiteLLM's model map; re-check both before each release. All
  three cloud defaults need LiteLLM >= 1.105 for pricing, which a fresh
  install gets. The dev lock (1.100.1) runs them with an unknown cost.
  `init` and `check` dispatch on `argv[0]` exactly, like `verify`.
- **`LITELLM_MODE` defaults to `PRODUCTION`** (0.1.4). LiteLLM's import
  calls `load_dotenv()` with no path when it is `DEV`, and python-dotenv
  then searches upward from LiteLLM's own install folder: a venv inside the
  checkout loaded the repo's `.env` from any directory, and a tool install
  can load `~/.env`. Those values beat `./.env`, which config.py loads
  without overriding. Found when `certo check` passed in an empty folder.
  The variable gates nothing else in LiteLLM (checked).
- **`check-llm` lives in `certo-admin`, not the `certo` CLI** — `certo`
  requires a task positional, while `certo-admin` is already the
  subcommand-based maintenance CLI. There's no `--api-key` flag, so a key
  never lands in shell history; use `CERTO_LLM_API_KEY=... certo-admin check-llm`.
  Retries are disabled so a bad key/endpoint fails in seconds, not after
  the SDK's 5 backoff retries.
- **A user-level settings file, `$XDG_CONFIG_HOME/certo/.env`** (0.1.5).
  Without it, working one project at a time meant copying a `.env` with
  the key into every project, which is how keys end up committed, or
  exporting variables in every terminal. XDG with a `~/.config` fallback
  on every platform, not each OS's own config folder, so there is one
  path to document and to type. `certo init` saves there by default and
  `--yes` picks it; without a terminal it still writes `FOLDER/.env`, as
  before.
- **Precedence: environment, then `./.env`, then the user file, each
  variable on its own** (0.1.5). Specific beats general, so one project
  can change only `CERTO_LLM_MODEL` and keep the shared key. Implemented
  as fill-only (a source never replaces a value an earlier one set),
  which is also `load_dotenv(override=False)`'s rule, so nothing can
  silently win over a higher source. A blank value counts as unset, as in
  `_read`: `init` writes `CERTO_LLM_API_KEY=` as a placeholder, and that
  mustn't hide the user file's key. Tests set `XDG_CONFIG_HOME` in
  `conftest.py` at import time (some modules call `load_config()` at
  collection) and restore `os.environ` after each test, since loading
  writes to it.
- **The "existing folder" warning never blocks or asks** (0.1.5). It runs
  before every CLI task, including scripts and CI where nobody can
  answer, and a question there would hang or fail a run that was fine.
  The decision to commit first is the user's; Certo only says when there's
  no way back. Only changes under the task's folder count. Certo-created
  `--project` folders are listed beside the projects, in
  `CERTO_PROJECTS_DIR/.certo-created-projects`, rather than marked inside
  them, so a generated project carries no Certo file. Silenced with
  `CERTO_NO_WORKTREE_WARNING`, a setting rather than a flag, so the user
  file can turn it off everywhere.
- **User docs moved from one `MANUAL.md` to a `docs/` folder in the repo,
  not a GitHub wiki.** The manual had grown to ~2,300 lines mixing three
  readers: newcomers, people looking up a flag, and maintainers. A wiki is
  versioned apart from the code, can't be changed in the same commit as
  the behaviour it describes, and can't be tested; `docs/` can. Structure:
  one getting-started path, task guides, exact reference pages, and
  concept pages, kept separate so each page has one reader (a
  "Diátaxis"-style split), plus troubleshooting written as symptom →
  cause → fix. Plain GitHub Markdown, no site generator yet. Staleness:
  `tests/test_docs.py` derives the lists from the code (settings recorded
  while `load_config()` runs, argparse parsers walked for every flag and
  subcommand, `VERIFICATION_STATES` and `_FAILING_STATES` for the verdict
  table) and fails on a missing entry or a broken relative link or
  heading anchor; prose correctness is still a review duty (CLAUDE.md).
  Maintainer-only notes ("verified live", SDK line references) stay here,
  not in `docs/`. `MANUAL.md` became a redirect table so old links and
  code comments that name a manual section still lead somewhere.
- **The model-call timeout is a setting: `CERTO_LLM_TIMEOUT_SECONDS`
  and per-entry `timeout_seconds` in `models.yaml`, both default 300**
  (0.1.8, user request: local models went past 300 s). It is the SDK's own
  `LLM.timeout` (default 300, `None` = no limit, which `0` maps to). It
  matters more than it looks: the SDK retries `litellm.Timeout` (in
  `LLM_RETRY_EXCEPTIONS`, `num_retries=5`) and each retry restarts the
  generation, so a model needing 400 s per answer never gets one and spends
  ~30 min, the whole default task budget. A catalog entry doesn't inherit
  the `.env` value (entries are complete specs, like `api_key`). The
  verification checks' own 300-second limit is unrelated and unchanged.
  `certo check`/`check-llm` keep their short timeout.
- **Command-line resume state lives in the project's `.certo/`, built on
  the SDK's own conversation persistence** (0.1.7, user's choice of
  location). The task store was server-only, so an interrupted CLI run
  lost the agent's context whatever backend was configured. Reusing
  `Conversation(persistence_dir=, conversation_id=)` (golden rule 1)
  gives exact context back; verified in-session that a second
  `Conversation` with the same id reloads the events, accepts a different
  model, and writes no API key (secrets are redacted without a cipher).
  `STATUS.md` is written by Certo, not the agent, so it is trustworthy and
  doubles as the fallback memory when the conversation can't be reopened.
  Supersedes, for this one folder, the 0.1.5 "a generated project carries
  no Certo file" rule: `.certo/` holds a `.gitignore` of `*`, so git (and
  the worktree warning, which also skips it when checking for an empty
  folder) ignores it without editing the user's `.gitignore`. Only the
  last run is kept (each conversation can be megabytes; artifacts keep
  history). The server keeps its `TaskStore`: concurrent tasks, queries
  and TTLs need a real store, not Markdown files. Not done: a resume
  after a kill mid-tool-call relies on the SDK handling the unmatched
  action; not exercised against a live model.
- **Escalation (0.1.9): start cheap, climb only when verification fails.**
  Per task, not per step: the signal is Certo's own verdict, which only
  exists at the end of a run. Opt-in (`--escalate`,
  `CERTO_MODEL_SELECTION=escalate`, server `escalate`); single-model runs
  and `--auto-model` ranking are untouched (working agreement 2).
  `--escalate` with `--auto-model`, `--model` or `--resume` is an error:
  the ladder decides the models, and resume continues one conversation.
- **`activated: false` means never used, everywhere** (0.1.9, supersedes
  the bench entry below that ignored it): not in `--auto-model` (already
  so), escalation or `certo bench`. A bench arm naming an inactive model
  is an error with how to reactivate; a ladder rung on one is skipped with
  a warning; a ladder left empty is an error.
- **Ladders are explicit or derived.** Explicit (`escalation.ladders`)
  always wins; `--escalate` with no name uses `default`, else derives.
  Derived: capability = the plain sum of a model's ratings except the cost
  axis (`cost`, configurable), i.e. reasoning + precision + code with the
  usual axes; capped at `max_rungs` (default 3, minimum 2) by
  floor(j(n-1)/(k-1)+0.5), which keeps the first and last kept model
  and spreads the rest. Deterministic, printed, written to
  MODEL_DECISIONS.md.
- **Derived ladders start from the best of the cheapest, not the weakest**
  (0.1.11, user's call; supersedes "ascending capability, ties to the
  higher cost rating" from 0.1.9). Weakest-first put a model on the first
  rung that another one beat at the same price (a real catalog: devstral 5
  ahead of qwen3.8 8, both free, and the 3-rung spread then cut qwen3.8
  entirely). Now: cheapest cost rating first, most capable within it, then
  keep a model only if it beats every model kept before it (the Pareto
  front of cost against capability); the beaten ones go in
  `ResolvedLadder.skipped` with the model that beats them, shown by
  `certo check` and before a run. No cost rating = most expensive; no cost
  rating anywhere = the old capability order (no price to compare, else
  only one rung would be left). Speed was considered for the first rung
  but the catalog has no speed data, and a `speed` rating would count as
  capability. Changes the derived ladder of a bench `escalate` arm with no
  `models:`. **Not benchmarked** on a local and a cloud model yet
  (working agreement 2): no session with both has run it.
- **Bench plan prices a derived escalate arm on its real ladder, and adds
  a "likely" cost** (0.1.12, user's question). The plan priced every
  active model for a derived arm (`Arm.models` holds them all), while a run
  uses only `derive_ladder()`'s ≤ `max_rungs` rungs: $58.95 shown against
  $24.30 worst case on a real file. The plan now derives the ladder;
  `Arm.models` is unchanged because it feeds the `--resume` fingerprint.
  "At most" stays (every rung runs), since it is the safe bound. "Likely"
  = Σ rung cost × P(reaching it), the climb rates taken from earlier
  results under the same parent folder: single-arm runs and escalation
  rungs, an escalating verdict or an error/provider failure counting as a
  climb, matched by name *and* model id. Shown only when every rung but
  the last has history, rather than guessing. Token counts per run are
  still the fixed 500k/20k guess (see the backlog item on recorded cost).
- **Bench records its real cost per model, beside the estimate** (0.1.13,
  user request). Per-run and per-arm cost already existed; missing were a
  total, a per-model split and a comparison. `bench_report.cost_summary`
  builds them from the run records alone (escalation split by rung via
  each rung's own `cost`), written to `results.md` (## Cost), a new
  `cost.json`, and printed at the end. The plan's estimate is stored in
  `meta.json` (`estimate`) when the folder is created, outside
  `config`, so the `--resume` fingerprint is unaffected; older folders
  simply have none.
- **Bench keeps each run's conversation** (0.1.15, user request): the
  fooled run behind `unchanged` couldn't be explained, since bench passed
  no `on_message` and set no `CERTO_ARTIFACTS_DIR`. `execute_run` wraps the
  stream to collect messages (strategies unchanged) and writes
  `runs/transcripts/<run_id>.json` before grading, also when the strategy
  raises. A subfolder, not `runs/<id>.transcript.json`, because
  `load_records` globs `runs/*.json`. Not artifacts (`write_run_artifacts`):
  that adds per-rung folders and metadata the run record already holds.
- **A `verified` run that changed no file becomes `unchanged`, after one
  follow-up** (0.1.14, user's choice among: always `inconclusive`, always
  a failure, follow-up only). The checks then only prove the starting
  folder passed, which was true before the agent ran ("confident but
  wrong" #10). Certo can't tell "nothing to do" from a lazy or misdirected
  model, so it asks once (cheap, catches stopping early and edits written
  outside the folder, and the message names the folder), then refuses to
  take the agent's reason as proof (golden rule 7). Not `inconclusive`:
  that never climbs, and "nothing to check" differs from "did nothing".
  Not a failure: "check the tests pass" is a legitimate no-change task, so
  it exits 0 like `inconclusive` (`runner.UNPROVEN_STATES`, which
  `--require-verification` / `require_verification` fail). Escalation
  climbs on it, but two consecutive `unchanged` rungs stop the climb: two
  models agreeing is evidence, and climbing on would send a genuine
  no-change task to the most expensive model. Only after `verified` (every
  other verdict already isn't success); never on `--resume` (changes may
  predate the session). A change is the escalation before/after listing
  (`workspace_listing`, which now also skips `target`/`.gradle`, written
  by verification itself) minus `MODEL_DECISIONS.md`. The follow-up counts
  as one fix attempt in `retries_used`. A Rust project with no
  `Cargo.lock` gets one from `cargo test`, which counts as a change: a
  miss toward the old behaviour, accepted.
- **A local model's cost is zero, not unknown** (2026-10-18, found by the
  first complete benchmark: every total said "+ unknown" because the local
  arm's 27 runs had tokens and no price). `run_summary.ModelUsage.cost_known`
  is true for an id with a local prefix (`model_pricing.is_local_model_id`,
  the prefixes `is_local` already used); the metrics carry only the model
  id, so an `openai/` model on a local `base_url` is still "unknown".
  `bench_report` applies the same rule to older records, so a regenerated
  report is right. Same day: `meta.json` gained `ladders` (a derived
  escalate arm's real ladder, outside `config` so the `--resume`
  fingerprint is unchanged), shown in the Models column instead of every
  active model.
- **The model catalog is split from personal settings (0.1.10, user's
  design):** `models_list.yaml` (model ids, descriptions, ratings,
  `reasoning_effort`, `timeout_seconds`, task profiles, escalation
  ladders) and `models.yaml` (by name: `api_key`, `base_url`,
  `activated`, overrides of ratings per axis, `reasoning_effort`,
  `timeout_seconds`, `description`). So the catalog can be shared and
  updated without touching keys. Both ship only as `.example` files in
  the package and are never read from there: a release must never
  overwrite a user's customised list, and using the example silently
  would hide that the user has no keys configured. `models.yaml` may only
  name models the list has; new models go into the list. Personal fields
  in the list and the old single-file `models.yaml` are errors that say
  what to move (no compatibility reader: the user migrates by hand).
  Lookup mirrors `.env` (project folder before user folder) but takes the
  first file found whole rather than merging entries, so what runs is one
  file you can open. Tests never look in the repository root
  (`conftest.py`), where a developer's real `models.yaml` lives.
- **Capability ignores task profiles** (changed before release, user's
  call, with `models.yaml.example`'s rating comments as the source of
  truth). The brief first had the matched profile's weighted sum; the
  ratings are now anchored to cross-provider benchmarks, and a ladder
  climbs by general capability, so the same ladder serves every task and
  the ladder printed by `certo check` is the one a run uses. The sum is
  over every axis but the cost axis (not hard-coded to the three names),
  so a catalog with other axis names still orders; a cost rating under
  another name must be named by `escalation.cost_axis`.
- **What climbs:** `retry_exhausted`, `no_progress`, `timed_out`,
  `incomplete`, `stuck`, `unchanged` (0.1.14, see below);
  `acceptance_failed` only when the ladder opts in.
  Never `inconclusive` (no signal: a stronger model faces the same blank),
  `budget_exhausted` or `confirmation_required` (the user's limits). A
  provider failure climbs too, recorded as such; on the last rung it is
  raised like in a single-model run.
- **A fresh conversation per rung, same workspace, handoff from facts.**
  Replaying the previous conversation would cost money and add noise (a
  real local run sent 344k input tokens for hello-world). The next rung
  gets the files, the task, the bounded failing-check output Certo sends
  on a retry, and a note Certo writes from recorded facts (model, verdict,
  fix attempts, files from a before/after listing, failing checks). The
  listing is used rather than `git status`, because it is exact to the
  rung even when the folder already had uncommitted changes. Continue-only
  for now (restart is in the backlog).
- **Budgets:** `CERTO_MAX_TASK_SECONDS` spans every rung; each rung has its
  own `retries` (default `CERTO_MAX_VERIFY_RETRIES`). New
  `CERTO_MAX_TASK_COST` (USD, unset) is checked before each rung against
  the recorded per-model cost; unknown prices count as 0 and are named. It
  applies to escalation only.
- **Escalation under Docker is supported.** Each rung is a new
  `Conversation` on the same `DockerWorkspace` (public API: the SDK opens
  a new conversation on the same agent-server, same container and bind
  mount). The remote conversation wraps every failure in a server error,
  so under Docker any `ConversationRunError` ends the rung ("provider or
  run failure"); locally only the SDK's `LLMError` does, and any other
  error is raised at once.
- **One consistency check for `models.yaml`** (`catalog_check.py`), shared
  by every command that reads it, so `certo check` reports exactly what a
  run would refuse. Two readings of the brief: a "duplicate rung" is the
  same model with the same settings (the same model at another
  `reasoning_effort` is a legitimate rung); an unknown `cost_axis` is an
  error only when written explicitly, since the default `cost` must not
  break catalogs without cost ratings.
- **`certo check --models` builds each model's config from its entry
  alone** (nothing from `.env`), as runs do, and rewrites
  `llm_check.explain()`'s `.env` field names into the `models.yaml` ones.
- **Server rungs in the SQL store: a nullable `rungs` column added on
  startup** with `ALTER TABLE ... ADD COLUMN` when missing (user's choice
  over hiding it in `completion_contract` or leaving SQL stores without
  it). Old rows read as `None`.
- **Bench `strategy: escalate`:** `models: [...]` (at least two, active, no
  repeats) or derived; `escalation.ladders` in `models.yaml` are
  not used (in `models_list.yaml` since 0.1.10), so an arm states its
  ladder in `bench.yaml`. "Cost per solved
  task" is added for every arm (also meaningful for `single`); rung
  shares only for escalate arms; existing columns unchanged.
- **`certo bench` grades with hidden tests, takes models from
  `models.yaml` by name (since 0.1.10 the ratings are in `models_list.yaml`), and puts strategies in a registry** (0.1.6).
  Hidden tests, because the agent's own tests share its misunderstandings
  (the Hanoi and Wordle cases): only tests it never saw can show whether
  Certo was fooled, which is the number Certo exists to keep at zero.
  `models.yaml` names, not `.env`: `.env` holds one model by design,
  while a benchmark compares several; the catalog already holds keys,
  gitignored, so `bench.yaml` stays key-free and committable, and each arm
  says exactly which model runs (no `--auto-model` ranking; `activated`
  was ignored until 0.1.9, superseded above). A registry, because the next strategies (`cascade`,
  `best_of`) must be measurable the moment they exist: each is one class
  that parses its own arm keys and runs one task, and the runner, grader
  and report never change. "Caught" follows the spec literally (agent
  finished, not `verified`); `unconfirmed_pass` is recorded beside it
  because a correct project with no tests also lands there. Runs are
  repeat-major so a stopped benchmark has some of every arm and task.
- **An `inconclusive` rung that changed no file climbs** (0.1.16; refines
  "`inconclusive` never climbs", 0.1.9). In the 0.1.15 local benchmark,
  models that wrote their tool calls as text ended with an empty folder
  (qwen3.8 once, qwen3.6 14 of 27 times), and a ladder stopped on rung 1.
  "A stronger model would face the same blank" holds only when files were
  written and none can be checked. `RungResult.did_no_work` (`unchanged`,
  or `inconclusive` with an empty `FileChanges`) both climbs and drives
  the stop rule, which is now "two rungs in a row that did no work",
  whatever their verdicts. The facts come from the rung's own before/after
  listing, never from the model. The handoff tells the next model that no
  file was written.
- **`bench.yaml.example` ships in the wheel, in `certo/examples/`**
  (0.1.17; supersedes the sdist-only copy at the repo root). After a pip
  install the docs had to send users to a download URL. Now a missing
  `bench.yaml` prints the `cp` command for the installed example, as the
  model files do since 0.1.10, and the sdist allowlist no longer lists
  it. The examples (and the example `models.yaml`) name
  `qwen3.8-27b-local` instead of `qwen3.6-35b-local`, which scored 0/27 in
  the 0.1.15 local benchmark.
- **Run history goes in `.certo/RUNS.md`, appended by the CLI** (0.1.19).
  `STATUS.md` keeps only the last run, so "which model built this?" had no
  answer a few runs later (a user's `asteroids.2`). The history stays
  inside the self-ignoring `.certo/` rather than at the project root: Certo
  adds no file to the user's project, and nothing new can look like an
  agent change. Written by `cli.py`, which alone knows the run was a CLI
  run with state saving on; server and bench never write it.
  The one exception to "no file in the user's project": a marked note in
  `README.md` naming the models, the Author's request, written only in a
  folder Certo created, so it never edits a README the user brought.
- **`.certo/` stays created at the start; the agent is told to keep it**
  (0.1.19). It makes a new project folder non-empty, which broke
  `npm create vite .` live (cancelled, exit 0) and whose `--overwrite`
  deletes it. Creating it later was rejected: the SDK saves the
  conversation there from the first step, and `--resume` after a Ctrl-C
  needs it. Instead `agent._CERTO_STATE_SUFFIX` tells every model to
  leave `.certo/` alone and scaffold into a subfolder. Not gated by tier:
  it is a fact about the folder, not a strategy for weaker models.
- **The local default is `ollama/qwen3.8:27b`, not `qwen3-coder:30b`**
  (0.1.19). Measured, not assumed: in `baseline-0.1.18-local.md` (27 runs
  each, same Ollama server) qwen3.8 passed 27/27 hidden tests and fooled
  Certo 0 times; qwen3-coder 18/27 and 3. Supersedes the earlier choice of
  qwen3-coder, which had never been benchmarked. `certo init` also offers
  the recommended model first when it is installed, before any "coder"
  model. `qwen2.5-coder:7b` stays the small-machine suggestion, marked
  unmeasured. Catalog ratings were left unchanged: they drive
  `--auto-model` and derived ladders, so changing them needs its own
  benchmark.
- **Task profiles match whole words in the task's first line** (after
  0.1.19). Whole-text substring matching sent 12 of 14 bundled tasks to
  `debugging`, because a spec says "raise ValueError" or "fix all build
  failures"; checked with the shipped example catalog, no model call. The
  title says what kind of work a task is; its body is the spec. Whole
  words (plus a plain `s`/`es` plural) match how skill triggers work.
  `MODEL_DECISIONS.md` now names the matched word. Supersedes the
  substring rule of the original auto-model design.
- **A task profile can pin one model (`model:`), not a list** (0.1.20).
  The Author's request: say "debugging runs on Sonnet" directly instead
  of tuning weights until it wins. The pinned model runs first only when
  enabled; the weights order the fallbacks, so a failure still has
  somewhere to go. A single name, not a list: an ordered list would be a
  second kind of ladder; add one only if someone needs it.
- **Task profiles and ladders get their own files** (0.1.20), the Author's
  call: `task_profiles.yaml` (`--auto-model`) and `escalation.yaml`
  (`--escalate`, bench), each optional and found like the other two. One
  file per mode, so `models_list.yaml` holds only model data that a
  release can update without touching the user's choices. Supersedes the
  TODO idea of a single `model_policy.yaml`. Same top-level key as the old
  section, so moving is cut and paste. The old sections are still read,
  with a warning, rather than an error or an automatic rewrite: nothing
  breaks, and Certo never edits a user's file. When both exist, the file
  wins.
- **A step-limit stop is checked, and failing checks switch model**
  (0.1.20), the Author's option (a). Using all of `CERTO_MAX_ITERATIONS`
  isn't a failure in itself: twice on 2026-10-19 Haiku stopped there, once
  with all 116 tests passing. So the checks run first; failing checks go
  through the normal fix loop, where `--auto-model` already moves to the
  next model, and escalation climbs once the rung's fix attempts are used.
  Nothing to check stays `stuck`. The next model is the next by weights,
  not necessarily a stronger one (option (b), "only to a model at least as
  capable", was not chosen: one rule for every failed attempt). Runaway
  loops stay bounded by the per-run step limit, the finite model list,
  the time budget and the cost cap.
- **Ruff's rules are named, not inherited** (2026-10-20). Ruff 0.16 raised
  its default rule set from 59 rules to 413, and with no `select` the
  project silently inherited them (13 findings, all style). `select` pins
  the pre-0.16 defaults (`E4`, `E7`, `E9`, `F`) so an upgrade can't change
  what is checked; widening it is a separate, deliberate change. Markdown
  is left out of `ruff format` (0.17 formats code blocks in `.md`), so
  docs samples stay as written. The release workflow now runs both checks,
  so a lint failure blocks a release.
- **A run is quiet by default** (0.1.21). The system prompt and the task
  with its skills are one line each, the SDK's INFO logs are hidden, and
  Certo's notices print as they happen; `--verbose` / `CERTO_VERBOSE`
  restores the full output. The first Wordle run of a new user printed
  2,949 lines with Certo's own lines lost in them; the same run now
  prints 1,021, every agent step still shown. Done by subclassing the
  SDK's default visualizer (only `on_event`), not by replacing it, so the
  agent's steps keep the SDK's rendering. The CLI no longer reprints the
  agent's last message at the end: the visualizer already printed it,
  and it was the duplicate.
- **API keys live only in the settings file** (2026-10-20, the Author).
  `models.yaml` refers to a key as `${VAR}` (for example
  `${ANTHROPIC_API_KEY}`) instead of holding a copy, so each key is in
  one place and `certo init` never writes a key into a second file
  (`${VAR}` expansion added in 0.1.21; an unset variable leaves the model
  out instead of sending the literal text). A secret manager may replace the settings file later (TODO.md).
- **Python environment paths follow the execution platform.** Local
  Windows environments use `Scripts/python.exe`, `pip.exe` and a semicolon
  on PATH. Docker keeps Linux paths and a colon even on a Windows host.
  Existing Windows layouts can also be identified from their interpreter
  file, so portable tests exercise both layouts without replacing `os.name`.
  The test helper uses Python's installation scheme to locate site-packages.
- **A run that ends after its time budget is still checked** (0.1.22,
  the Author). The budget is checked only between runs, so the last run
  can end past it; the checks need no model, so they run once, with no
  fix attempt, and passing work is `verified` (with a limitation line).
  Failing or missing checks stay `budget_exhausted`, now with the check
  results; a run that ended in an error, or with checks off, is not
  checked. The task-list gate leaves a late finish with no open items to
  the checks. Why: three runs in the 0.1.15 local benchmark passed the
  hidden tests and were reported `budget_exhausted` unchecked.
- **An `inconclusive` rung climbs** (0.1.22, the Author; supersedes the
  0.1.17 rule that it climbs only when the rung changed no file). A model
  that wrote code but no tests (in the 0.1.17 escalation run, its test
  file was a tool call written as text) leaves the next model something
  to finish; the handoff asks it to add the missing tests. Of the two
  options (just climb, or climb and ask for tests first), the simpler was
  chosen; the handoff note covers the second. Two `inconclusive` rungs in
  a row stop the climb, so a project with nothing to check doesn't pay
  for every rung.
- **CLI LLM flags are checked after they are applied** (issue #11).
  `load_config()` used to require a model (and a key unless a base URL was
  set) before `override_llm()` saw `--model` / `--base-url`, so the flags
  alone could not start a run. `defer_llm_check()` skips those checks for
  the load; `ensure_llm_configured()` then checks the final values after
  `override_llm()`. Validation stays out of `override_llm` itself so
  catalog swaps that clear a key can still set a base URL in the same
  call. No flag and no setting still yields the same error as before.
- **Skills: official and third-party kept apart, managed by `certo
  skills`** (2026-10-22, the Author; supersedes `CERTO_SKILLS_DIR` and
  `./third_party_skills/` as places to keep skills). Official skills are
  Certo's own guidance, shipped in the package and checked with the
  benchmark; third-party skills are the user's choice, written or
  downloaded. They live in separate folders, and third-party ones only
  where git never sees them: `~/.config/certo/skills/` or
  `<project>/.certo/skills/`, not `.agents/skills/`, which a project may
  commit. Why: skills kept in folders relative to where `certo` runs ended
  up inside repositories (three downloaded skills in Certo's own `./skills`),
  protected only by `.gitignore` lines. `add` and `remove` need
  `--global` or `--project`: a skill landing in the wrong scope is easy
  to miss. A third-party skill may still replace an official one of the
  same name (that is how a project adapts `pytest-conventions`), but never
  silently. Skills are never suggested or installed by a model or
  automatically: a downloaded skill is untrusted text that goes into the
  agent's instructions, and each one that fires costs a local model
  context; selection at run time stays the SDK's deterministic matching.
- **The reasoning effort is shown as configured, `default` when unset**
  (0.1.22). Not the value the SDK ends up sending (`high` for most
  providers, nothing for Ollama), because that depends on the provider
  and on LiteLLM, and a guessed value in a record would be worse than an
  honest "default". Two rungs of one model at two efforts are told apart
  by the effort, so it is part of the merge key in the run summary and
  the benchmark's cost table. Results written before 0.1.22 say `not
  recorded`, never `default`.
- **`certo skills`: how a third-party folder is laid out** (0.1.22).
  Skills sit at the folder's top level only (`<name>.md`,
  `<name>/SKILL.md`) and are loaded item by item: the SDK's
  `load_skills_from_dir` `rglob`s, and the git cache in the same folder
  holds whole repositories. A skill added from a file or folder is on at
  once (the user chose it, as with the old `./skills`); one from git keeps
  the old rules, off until enabled, in the folder's own
  `skills.lock.json`. Both kinds are treated as untrusted text (inline
  commands escaped, `.mcp.json` ignored). `--project NAME` means a project
  in `CERTO_PROJECTS_DIR`, as for a run. The old folders are read between
  the official skills and the global ones, as before; a downloaded skill
  there still can't replace an official one.
- **`certo skills --project .` is the current folder** (the Author,
  2026-10-22): the folder a run without `--project` works in
  (`CERTO_WORKSPACE`), so its `.certo/skills/` can be managed too. Any
  other name is still a project in `CERTO_PROJECTS_DIR`.
- **Select a project path before checking configuration; create it only
  after the checks pass** (issue #26). Model files may live in an existing
  project folder. Deferring creation avoids rollback and leaves existing
  folders and the Certo-created registry untouched on configuration errors.
- **The old skill folders are gone, their settings warn** (after 0.1.22,
  as announced in its release notes; supersedes "the old folders are
  read" above). `./skills`, `./third_party_skills/` and `certo-admin
  skills` are removed. A `CERTO_`/`HARNESS_` setting for them that is
  still set logs one warning naming it, so a user's skills don't drop out
  of a run unnoticed; the folders themselves aren't looked for, since a
  project's own `./skills` may be unrelated. `.gitignore` still ignores
  both folders (the Author, 2026-10-23): users may still drop skills
  there, and the rule from "Skills: official and third-party kept apart"
  stands, that only the official skills in `builtin_skills/` are ever in
  git.
- **Benchmark grading for Go, Rust and Node with packages** (0.1.23,
  Phase 1.1 of the plan). The language comes from the hidden test files'
  names, as before. Go hidden tests are a package of their own in
  `.certo_hidden_tests/`, importing the solution by module path: black-box,
  and no clash with the agent's test names. Rust ones must sit in
  `tests/` (Cargo finds test targets nowhere else), so they are copied
  there with a `certo_hidden_` prefix. Only hidden tests run, so the
  agent's own failing tests never change the score. A package install
  that fails, and hidden tests that run nothing, are `error` (could not
  grade), as a failed pytest install already was: a network outage must
  not read as the model's failure.
- **Task set version 2 grows in place** (2026-10-23, Phase 1.2). The
  larger tasks join the nine small ones in `benchmark_tasks/`, and
  `VERSION` went to 2 with the first of them, `ledger-transfers`; the
  set's hash pins its exact content until baseline v2. Version-1
  baselines are reproduced by listing their nine tasks, not by keeping
  a second folder. A larger task is original code written for the
  benchmark (no copied repository, so no license question), and its
  hidden tests are checked against wrong variants of the reference
  before it ships.
- **A program that stops with its usage line has started** (2026-10-23,
  found by the `ledger-transfers` cloud run). The no-argument run of each
  Python entry point passes on exit 2 with a line starting `usage:`
  (argparse, click). Only that check allows it, and only that pair: exit
  1, or exit 2 with no usage line, still fails. Why: the check proves the
  program starts; failing a correct CLI made the fix attempt change
  correct behaviour, the opposite of golden rule 6's intent.
- **The Rust v2 task uses the standard library only** (2026-10-23). The
  plan's "Rust CLI with subcommands" is `todo-deps`, with no crates: the
  agent's run and the grading stay offline and deterministic, and Rust
  1.58 (the oldest toolchain it is checked on) builds it. Its hidden
  tests run only the built binary (`CARGO_BIN_EXE_todo`) with their own
  `TODO_FILE`, so they don't constrain the code's structure. Tasks that
  need packages (React, Go with SQLite) come later, when grading's
  network use is decided.
- **Task set v2: one networked task, the rest offline** (the Author,
  2026-10-23). Of the last two v2 tasks, React + API uses packages, with
  a lock file in the starter so grading installs exact versions
  (`npm ci`); the Go REST API uses the standard library only. Why: one
  realistic task with packages, while most of the set stays offline and
  deterministic. A failed download is a grading `error`, never the
  model's failure.
- **`room-bookings`: React without JSX, two pinned packages** (2026-10-23).
  `react` and `react-dom` 19.0.0 only (three packages with `scheduler`,
  none with install scripts), in a lock file with integrity hashes;
  components use `React.createElement`, so there is no build step and no
  Babel, Vite or jsdom tree of hundreds of packages. Hidden tests render
  with `react-dom/server` and call the API on `127.0.0.1`. The lock file
  was made in a throwaway `node:22.11.0-alpine` container with
  `--ignore-scripts`, mounting only a scratch folder.
- **Go and Rust: zero tests is `skipped`, by counting** (2026-10-23, found
  building `todo-deps`). Unlike `node --test` (PR #28: one zero-test
  summary line), "no tests" is a fact about the whole output: `go test`
  prints a line per package, and `[no test files]` next to an `ok` line
  is normal (`cmd/server`); `cargo test` prints a result line per target.
  So `CheckSpec.count_tests` counts what ran, packages with an `ok` line
  for Go and passed + failed over every `test result:` line for Cargo,
  and 0 makes a successful run `skipped`. Kept apart from #28's
  `no_work_markers` (and away from its lines) so both merge.
- **A baseline per release is optional** (the Author, 2026-10-23;
  supersedes "a baseline for every release" in ROADMAP and the project
  review). A full baseline takes hours on a local model, so the Author
  decides per release whether to run it, and minor releases may skip it.
  Unchanged: working agreement 2 in CLAUDE.md, so a change aimed at weaker
  models is still benchmarked on a local and a cloud model before
  release; a session never starts a long or costly benchmark run without
  the Author's go-ahead.
- **Windows portability follows the execution platform** (2026-10-24,
  PR #29). Local Java verification uses `mvnw.cmd` and `gradlew.bat`;
  Docker keeps the Unix wrappers. A failed run on another Windows drive prints an absolute
  status path when a relative one cannot be formed. Tests compare native
  paths, read UTF-8 reports explicitly, and control tool availability when
  testing plan discovery. Symlink tests skip only Windows privilege error
  1314; directory-containment checks also exercise Windows junctions. Unix
  mode assertions stay on macOS/Linux because `chmod` does not set Windows
  ACLs; the docs now state that limit instead of promising mode `600` there.
- **Claude Code skills for developing Certo come from `anthropics/skills`,
  pinned, by a script** (2026-10-24). `scripts/fetch_claude_skills.py`
  (in git) lists the skills and a commit; the downloaded files go to
  `.claude/skills/` (git-ignored), so contributors get the same skills
  and the repo carries no third-party skill copies. Only skills the
  current work needs: `skill-creator` (built-in skills) and
  `webapp-testing` (web tasks, run-the-app verification); `mcp-builder`
  waits for the MCP server. Separate from Certo's own built-in skills.
- **When a full baseline is worth it, and running it in slices** (the
  Author, 2026-10-24; refines "a baseline per release is optional"). A
  full baseline when something changes how the agent works in general:
  prompts or built-in skills, verification rules, escalation, a new model
  or SDK version, a new task set version. Otherwise a targeted run (the
  tasks the change touches, one or two repeats, a cost cap) is enough,
  including for working agreement 2. The 0.1.23 baseline took 3h10m in
  the cloud and about 10-11 hours locally, so a full one is run in
  slices, one night each: the same benchmark file and `--out`, stopped
  in the morning and continued with `--resume`, so one report covers
  every night.
- **A generated project's agent files are only the ones inside its
  folder** (the Author, 2026-10-24). Certo's own `CLAUDE.md` and skills
  are for developing Certo; a generated project gets the skills Certo
  chooses and copies into it. So for a workspace inside
  `CERTO_PROJECTS_DIR`, the `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`,
  `.cursorrules` and skill folders the SDK finds at the root of a git
  repository around it are turned off (`disabled_skills`); its own files
  still count. An existing folder outside `CERTO_PROJECTS_DIR` keeps the
  SDK's behaviour: there the repository's files describe the code being
  worked on (as other coding agents read them).

- **A downloaded skill's links: skip the ones inside, refuse the ones
  that leave** (the Author, 2026-10-24). Every link used to be refused,
  which blocked most of OpenHands' catalog (`.claude-plugin` and
  `.codex-plugin` link to the skill's own `.plugin`). A link that resolves
  inside the skill folder adds nothing (its target is copied on its own),
  so it is skipped and named; one that resolves outside could pull in
  files the user never saw, so it still stops the install. Installed
  skills still contain no links, so the integrity check is unchanged.
- **Independent tests (Phase 1.5), first version** (the Author,
  2026-10-24). Opt-in (`--independent-tests`, `CERTO_INDEPENDENT_TESTS`).
  Written **before the build**, from the task text only, by a separate
  short conversation in an empty scratch folder (file editor only): it
  can't copy the builder's mistakes. **The same model** as the builder
  writes them by default (rung 1 with `--escalate`; one set judges every
  rung); an option names another. The writer tests only what the task
  states and writes nothing when the task names no interface or no
  language, so vague tasks report "none" instead of false alarms. The
  tests stay outside the project during the build (the run folder, not
  `.certo/`, which the agent can read); after the verdict they are copied
  in, run with the bench graders (Python, Node, Go, Rust; other languages
  "not available"), and removed. **Report only:** a line under the
  verdict and the run record; verdict and exit code unchanged (the
  2026-10-22 rule). Measured by a bench arm option against hidden tests:
  catch rate on runs that fooled Certo, false alarms on correct ones,
  cloud no worse (Phase 1's exit).
- **OpenHands plugins: check and stop, not filter** (the Author,
  2026-10-24). The SDK loads ambient plugins (skills, MCP, hooks) into
  every local conversation with no switch. Filtering would mean patching
  an SDK function; warning would leave hooks running. So Certo calls the
  SDK's own discovery before a local run (CLI, server, bench) and doesn't
  start on a user plugin (`~/.agents/plugins`, `~/.openhands/plugins`,
  installed) or a project plugin from outside a generated project's
  folder. An existing folder keeps its repository's plugins, as it keeps
  its `AGENTS.md`. Docker runs aren't checked (no user plugins in the
  container). Cost: a user of OpenHands' own plugins moves them aside
  while using Certo.
- **The independent-tests writer also reads the project before the build**
  (the Author, 2026-10-24; supersedes "from the task text only" in the
  Phase 1.5 entry). Seen live: on `ledger-transfers`, a writer with the
  task text alone rightly refused (the task refers to existing code it
  couldn't see). It now gets a read-only copy of the project as it is
  before the builder starts (`project_before/`: no `.git`, environments,
  packages, build output or `.certo/`; 200 KB per file, 5 MB in all),
  which keeps it independent of the builder's work. Absolute paths in
  its instructions: with a relative `tests/` it wrote into the copy's own
  `tests/` folder. First live result with `claude-haiku-5-5`: 15 tests,
  15/15 on the reference solution, failing on the starter, $0.014.
- **Independent tests in runs: what a first version leaves out** (2026-10-24,
  within the Phase 1.5 decisions). Not on `--resume` (the project already
  holds earlier work, so it isn't "before the build"); not under Docker
  (the tests run on this computer); not in server mode (a stored task
  result has no field for it: five storage backends). Failing tests are
  named under the report line, and with `CERTO_ARTIFACTS_DIR` the tests
  are kept in the run's records folder, never in the project, where a
  later task's agent could read them. Both came from the first live runs:
  two false alarms nobody could have checked otherwise.
- **Plugins: chosen by Certo, copied into the project** (the Author,
  2026-10-24; plan, not built yet; extends "Certo doesn't start while
  OpenHands plugins would load"). Plugins come in through Certo's own
  library, like third-party skills, never from ambient folders: pinned
  by source and hash, copied into the project's `.agents/plugins/`,
  where the SDK already loads them as the project's own, so there's no
  SDK patch and the existing check still refuses the rest. Guidance
  parts (skills, commands, agents) install directly; parts that run code
  (hooks: shell commands on agent events; `.mcp.json`: started server
  processes) need explicit consent at install. No blanket "trust my
  user plugins" setting: the SDK reads those folders for every run and
  they can't be scoped or pinned. Each run names the plugins and hashes
  that shaped it.
- **Independent tests are measured by replaying saved bench projects**
  (2026-10-24; replaces the planned bench arm as the first measurement).
  Fooled runs are rare (0 in 78 in the 0.1.23 baseline), so new builds
  would mostly measure false alarms. The writer writes from task and
  starter as in a real run; its tests run on every saved project whose
  hidden-test result is known (379), plus reference and starter. Only
  writing costs (Haiku, 39 sets: $0.32). Result: wrong tests appear in
  one set of three, real bugs in all three, so the next step is voting
  over three sets, not one set's verdict.
- **Independent tests: three sets, 2 of 3 to fail** (the Author asked for
  three writers, 2026-10-24; from the replay). Default
  `CERTO_INDEPENDENT_TESTS_SETS=3` (1 to 5); `failed` needs most sets,
  one failing set of three is `split`, a set that can't run doesn't count
  as failing. Writers run at the same time for a cloud model, one by one
  for a local one (a local server answers one request at a time). Still
  report only: a live `ledger-transfers` run showed all three sets
  sharing one misreading invited by the task's wording, so the vote
  removes random wrong tests, not shared ones.
- **`ledger-transfers`: the sign alone decides the side** (the Author,
  2026-10-25). The task's sentence "the outgoing amount is negative" led
  most independent-test writers to treat "outgoing" as a role given by
  name. The rule is unchanged, so the task set stays version 2; its hash
  changes, so runs from before this aren't compared with later ones
  automatically.
- **The budget stops a run in progress** (2026-10-25, from the 0.1.23
  baseline's 2h53m run). A watcher thread pauses the conversation at the
  deadline and sets the SDK's own foreground terminal cap
  (`OH_RUNTIME_IDLE_TIMEOUT_SECONDS`) to the time left, instead of
  wrapping the terminal tool: no copy of SDK code, and the SDK already
  tells the agent how to work under the cap. A bug fix, so no version
  bump; the cap is process-wide, so concurrent server runs share the
  nearest deadline (stricter, never looser).
- **Changed check files are reported, not judged** (2026-10-25, from a
  Reddit comment that `verified` overstates what passing checks show).
  Kept the name `verified` (exit codes, scripts, reports) and closed the
  gap instead: test files and check settings are copied before the run,
  and a `verified` run lists those the agent changed or deleted, with
  lines removed and added. New files aren't listed. The verdict stays,
  because tasks often ask for test changes; deciding when a change
  should downgrade it needs bench numbers first.
- **Changed check files stay report only, with rewritten lines counted
  apart** (2026-10-25, from the count on 379 saved bench runs). No run
  removed a test line or deleted a test; the 8 fooled runs changed no
  check file. 30 `inventory-fix` runs showed "1 line removed" only
  because they extended the test file's import, so a line rewritten in
  place is now "changed", and "removed" means lines really gone.
- **`certo bench --stop-at` takes a local clock time** (2026-10-25).
  `--stop-at HH:MM` (24-hour; tomorrow if already past today) stops
  starting new runs, and the run in progress finishes. A clock time
  fits the use (a baseline in nightly slices with `--resume`) better
  than a duration or a run count, and killing the run in progress
  would waste it.
- **Phase 1's live measurement is one cloud arm; local arms run at night**
  (2026-10-25, the Author). The catch rate of independent tests rests on
  the replay over saved projects (7 of 8 fooled runs, from five models).
  A new `qwen3.8` arm would add almost nothing: 2 fooled in 154 saved
  runs, 0 of 39 on task set v2, and it would write its own tests, which
  is high-effort work it's kept off. `qwen3-coder` is dropped. The live
  run is Haiku with independent tests on, 13 tasks × 3, for extra time,
  cost and false alarms on live builds. Local models are slow: their
  runs go into night slots (`--stop-at`, `--resume`), never the day.
- **Independent tests change the verdict only when asked** (the Author,
  2026-10-25, from the 0.1.24 numbers: 7 of 8 fooled runs caught on saved
  projects, 1 of 38 right live runs failed by a wrong test). Default
  stays report only; `--independent-tests-strict`
  (`CERTO_INDEPENDENT_TESTS_STRICT`, turns the tests on) makes a
  `verified` run with a `failed` result (most sets) end
  `independent_failed`, exit 1. A new verdict, not `failed` or
  `acceptance_failed`, so scripts can tell it apart. `split`, `none` and
  errors never change it. Applied last, after the acceptance checks.
  Not sent back to the agent as a fix attempt: that would show the
  builder the tests, and a wrong test would push it to break right work.
  With `--escalate` it doesn't climb (the tests run once, after the last
  rung).
- **The model call is capped at the time left** (2026-10-25; finishes
  "The budget stops a run in progress"). The SDK reads `LLM.timeout` on
  every attempt, so the deadline watcher lowers it to the time left
  (plus one second) and, past the deadline, sets a `retry_listener` that
  re-raises, ending the SDK's retries. Mutating the conversation's own
  LLM (restored after) instead of wrapping its calls: no copy of SDK
  code. A call cut this way past the deadline is the budget's doing, not
  a provider failure: it ends the run without a model switch, and the
  work is still checked once (`verified` or `budget_exhausted`, never
  `stuck`). A bug fix, no version bump.
- **Checkpoints: Certo's own git repository in `.certo/checkpoints/`,
  rollback by hand only** (the Author, 2026-10-25; Phase 2.3). A
  repository whose work tree is the project, with its own index and no
  global or system git config, works in any folder and never touches the
  user's repository (no commit, branch, stash or index change), which a
  ref inside the user's repository couldn't promise. Snapshots before the
  agent, at every check run (the `on_verification` hook, so every fix
  attempt and rung) and at the end, skipped when nothing changed; the
  project's `.gitignore`, environments, caches and files over 10 MB are
  left out, so a snapshot stays small. Only when the run keeps state
  (CLI), like the rest of `.certo/`. `certo rollback N` snapshots the
  current files first, so it can be undone. No automatic rollback and
  no restart mode yet: both change agent behaviour and need benchmark
  numbers first.
- **Certo learns the context window, from Ollama itself when needed**
  (2026-10-25, Phase 2.4). LiteLLM reports no window for an Ollama model
  (verified: `None` for `ollama/qwen3.8:27b`, though `/api/show` says
  262,144), and Ollama cuts an overlong prompt silently, so neither the
  SDK's 16K check nor its token-based condensing could work locally.
  Certo loads the model with an empty `/api/generate` and reads
  `context_length` from `/api/ps` (the window the server really gives,
  131,072 on the benchmark machine), cached 10 minutes.
  `CERTO_LLM_CONTEXT_TOKENS` / `context_tokens` set it instead; for
  Ollama it is sent as `litellm_extra_body={"options": {"num_ctx": N}}`
  (verified live: the server loaded the model at that size), so a user
  needn't restart Ollama. The SDK gets `max_input_tokens` = the window
  less a quarter (at least 4,096) for the answer, never under 16,384.
- **The SDK's condenser, for every model, only near the window**
  (2026-10-25, Phase 2.4). `LLMSummarizingCondenser` with the agent's own
  LLM (as the SDK's presets do, so its cost is counted), `keep_first=4`
  and `max_size` out of reach, so only its token trigger (the SDK's
  `max_input_tokens`) and a provider's context-exceeded error make it
  summarize. A run that fits keeps its whole history: nothing changes on
  a cloud model with room to spare, which is why it isn't gated by tier.
  The SDK allows a changed condenser on resume (only removed tools
  break it). Each condensation is announced and counted in the run
  summary and the bench record. `CERTO_CONDENSE=no` turns it off.
- **`npm test` that ran no tests is `skipped`, read from its summary**
  (2026-10-25, #23). The same `count_tests` hook as Go and Cargo:
  `# tests N` / `ℹ tests N` (`node --test`, TAP and spec reporters) and
  Jest's or Vitest's `No tests found, exiting with code 0`. Output it
  doesn't recognise returns -1, so the exit code decides as before: a
  custom script is never turned into "no tests" by a guess.
- **`CERTO_MAX_TASK_COST` limits every run, during the run, ending
  `cost_exhausted`** (2026-10-25). The Author chose to reuse the
  escalation setting (one limit, not two near-duplicates), a new verdict
  (a script can tell money from time; escalation doesn't climb on it) and
  a watcher during the run rather than a check between retries (one long
  agent run could otherwise spend without bound). `cost_limit.py` reads
  the conversation's SDK metrics every 2 s and calls `pause()`, like
  `deadline.py`; the call under way is paid, so it is let finish (overshoot:
  the calls since the last reading; live, $0.0065 on a $0.004 limit). The limit counts the independent tests and earlier
  rungs; a resume starts from the conversation's own spent cost, so it
  gets a fresh limit, like the time budget. Checks still run once after
  it, as after the time budget: they cost nothing.
- **A bench `auto` strategy, the Phase 1.3 hold lifted** (2026-10-25,
  the Author). It runs `stream_task` with `model_selection="auto"` and the
  benchmark's own catalog, narrowed to the arm's `models` (a new
  `model_catalog` argument, so the files aren't read again and an arm can
  limit the candidates). The plan's likely cost counts only the model
  each task's profile ranks first. `ModelDecisionRecord` gained
  `chosen_name` (the plain catalog name; `chosen` is a label with the
  effort), because the benchmark looks the model up.
- **Milestone mode: the Author's three decisions** (2026-10-25, before
  the design). (1) Who splits: both. Milestones written in the task file
  are used as they are; otherwise Certo plans them. With `--interactive`
  it shows the plan and asks; without it, Certo decides alone (as
  `--auto-model` does), saves the plan in `.certo/` beside `STATUS.md`,
  and `--resume` continues that plan. The task-file form is built first.
  (2) Each milestone passes the project's checks plus the acceptance
  checks written in it; independent tests per milestone only with
  `--independent-tests`. (3) A failed milestone gets the usual fix
  attempts, then escalation when a ladder is set, then stops; earlier
  milestones are kept, `--resume` continues, and the failed milestone's
  changes stay in the folder with a checkpoint before it, so
  `certo rollback` can undo them by hand (manual rollback, as decided
  for checkpoints).
- **Escalation restart mode is a setting, off by default**
  (2026-10-25). `CERTO_ESCALATION_HANDOFF=continue|restart`, and
  `handoff:` on a bench escalate arm, so the two can be compared before
  either becomes a per-ladder option or the default (unmeasured). Restart
  takes an `always` "before the agent" checkpoint even when checkpoints
  are off (library, bench), then before each later rung that changed
  files calls `checkpoints.rollback`, which keeps the previous rung's work
  as "before rollback". The handoff note still lists what the previous
  model did and its failing output, marked as undone. Without git it
  continues, with a notice. Bench workspaces leave out
  `.certo/checkpoints`.
- **Bench arms can set `max_task_seconds`** (2026-10-26). Any strategy;
  an escalate arm's budget covers all its rungs, as
  `CERTO_MAX_TASK_SECONDS` does. Left out of params at the default, for
  `--resume`. Needed to give a slow local arm more time than the cloud
  arms in one benchmark (Phase 2 exit proof).
- **The test writer writes calculations, not computed numbers**
  (2026-10-26). One rule in `WRITER_INSTRUCTIONS`, measured on a replay
  (`writer-arithmetic-0.1.25.md`): wrong sets 11/65 → 0/65, no real catch
  lost. Its example must not be any bundled task's answer: the first
  version used `2 * 3600 + 5 * 60 + 10` (`duration-parser`'s) and every
  set copied it, so that run was discarded; the example is now
  `12 * 4 + 3`. Behaviour changes only with `--independent-tests`.
- **A small context window is a warning set by the user**
  (2026-10-26, the Author). `CERTO_CONTEXT_WARN_TOKENS` (default 32768,
  the window the context benchmark ran well at with condensing; `0` =
  off): a notice at the start of a run and of each rung when the known
  window (set, or asked from Ollama) is smaller; the run goes on. Certo
  can't tell a task's size in advance, so a threshold the user sets is
  more honest than a guess. Cloud windows aren't checked (unknown to
  Certo, and far larger). The 16,384 refusal stays (the SDK's minimum).
- **Tool calls written as text get a reminder, on by default**
  (2026-10-27). When a run FINISHES on a text message that is a call to
  one of the agent's tools, Certo sends it back (`CERTO_TOOL_CALL_REMINDERS`,
  default 3, `0` = off; bench arm option `tool_call_reminders`). Gated by
  the model's own behaviour rather than a tier: the detector, replayed on
  every saved transcript, fires on 68 final messages, all from qwen3.8,
  qwen3.6 and devstral, and on none of 178 cloud runs, so a model that
  makes real calls never pays for it. Chosen over the SDK's prompt-based
  tool calling (`LLM.native_tool_calling=False`), which would change every
  call of a model that mostly makes real ones, and add tool examples to
  a 32K context. Cause not settled (Ollama's template or parser vs the
  model): the reminder works either way. Benchmark before release: a
  local arm with and without, and a cloud check.
- **Old `task_profiles:` / `escalation:` sections in `models_list.yaml`
  are refused, not ignored** (2026-10-27, as planned at 0.1.20: read with
  a warning "a version or two"). Ignoring them would silently change a
  user's ladders and profiles; an error names the file to move them to.
  Refused even when the section's own file exists, so there is one place
  for each.
- **Bench arms can turn official skills off (`skills_off`), with no
  setting** (2026-10-27). Every new skill must be measured on a local
  and a cloud model, and nothing could run "without it" before. Names
  are checked against the official catalog (a typo would silently
  measure nothing). Only the official layer is filtered: a third-party
  skill of the same name replaces it and stays. Not a user setting yet:
  turning official skills off for users is a separate TODO item with
  its own design (globally or per project).

- **The tool-call reminder stays on by default, though it saved no run**
  (2026-10-27, after `docs/benchmark/reminders-0.1.26.md`). qwen3.8 made
  one real call after 4 of 6 reminders, then went back to text: both
  runs still ended `inconclusive`, only later. Haiku got none and passed
  13/13. Kept on because it costs a model that makes real calls nothing
  and shows the failure in the conversation; not raised above 3, since
  more reminders only add time. The "works either way" hope in the
  entry above didn't hold for qwen3.8.

- **`testable-interactive-apps` is keyword-triggered, and asks for tests
  the task didn't** (2026-10-27). An interactive program has no path to
  trigger on, and the gap is the agent's: qwen3.8 solved `hangman-cli`
  3/3 but wrote no tests, so 0/3 `verified`. Asking for tests is what
  "verifiable" needs (golden rule 7). Triggers kept to six words; on the
  bundled set only `wordle-score` matches ("game").

- **Milestone mode: the design** (2026-10-29, the Author chose the four
  open points; builds on the 2026-10-25 entry above).
  - *Form, opt-in:* `certo --milestones task.md`. Each `## Milestone N:
    title` heading starts a milestone; text before the first is shared
    context. A milestone may hold one fenced `acceptance` block with the
    same JSON as `--acceptance-checks`. Without the flag a task file is
    sent as it is, so no existing task changes meaning. A file with no
    milestone heading, or a malformed block, is refused before any model
    call.
  - *A fresh conversation per milestone:* the agent gets the shared
    context, the titles of the milestones done, and the current one in
    full. Keeps a 32K local model's context small; the agent reads the
    files for the rest.
  - *Limits per milestone:* `CERTO_MAX_TASK_SECONDS`, `CERTO_MAX_TASK_COST`
    and `CERTO_MAX_ITERATIONS` apply to each milestone, as to a task
    today. The run summary gives the total.
  - *Checks:* each milestone runs the project's checks plus the
    acceptance checks of every milestone so far (file checks are cheap;
    an earlier one breaking is a regression). `--acceptance-checks`
    applies to the last milestone.
  - *Order of a milestone:* checkpoint "before milestone N", the run with
    the usual fix attempts, verdict. Only `verified` starts the next
    one. Any other verdict stops the task with that verdict and exit
    code, reported as "milestone N of M"; earlier work is kept and
    nothing is rolled back.
  - *State:* `.certo/milestones.json` keeps the plan (parsed from the
    file at the start) and each milestone's verdict; `run.json` stays
    the current milestone's run; `STATUS.md` gains a milestones list.
    `--resume` continues the first milestone not `verified`, from its
    saved conversation, using the saved plan: an edited task file doesn't
    change a plan in progress (start again to change it).
  - *Verdict of the task:* `verified` only when every milestone is; no
    new verdict or exit code.
  - *Later steps, before Phase 3 counts as done:* escalation per
    milestone (today `--resume` refuses `--escalate`); independent tests
    per milestone; a bench arm option so one task runs as milestones
    against the same task in one go. Certo planning the milestones
    itself (decision 1) comes after the task-file form. Server mode: not
    now.

- **Milestone plan file keeps no milestone text or checks** (2026-10-29,
  the Author's choice after a live Haiku run read `.certo/milestones.json`
  and reasoned from its acceptance checks). The file holds the task
  file's path, a fingerprint, titles and verdicts; `--resume` reads the
  task file again and refuses it when gone or edited. Supersedes the
  "keeps the plan" line of the design entry above. So `--milestones`
  needs a local file (no text, no URL). The loop lives in the CLI, one
  `run_task` per milestone, so the runner stays unchanged.

- **Milestones with a ladder and independent tests** (2026-10-29, the
  Author's three choices). Each milestone starts on rung 1 (climb only
  when that milestone needs it). `--resume --escalate` is allowed after
  `--milestones`: the milestone restarts on rung 1 in a fresh
  conversation with `STATUS.md`'s record, since a resume continues one
  model's conversation and can't climb; a single run's resume still
  refuses `--escalate`. Independent tests are written per milestone from
  its text; earlier milestones' sets aren't re-run (they'd need keeping);
  a resumed milestone gets none, as any resume.

- **A new milestone gets what the last one left** (2026-10-30). Each
  milestone after the first gets the project's file list with sizes
  (Certo's) and the agent's last `finish` summary (marked not checked),
  instead of only the titles. Reason: in the 64K local benchmark, new
  milestones spent their 40 minutes reading the folder and planning
  again (docs/benchmark/milestones-64k-0.1.27.md). Deterministic and
  free (no model call to summarize); a fresh conversation stays, so the
  context doesn't grow with each milestone. On by default in milestone
  mode, which is experimental; measured on a cloud and a local model
  before release (working agreement 2).

- **A newer version is announced in one line, never asked about**
  (2026-10-31). `certo` prints "Certo X is out (you have Y). To update:
  <command>" at the end of a command, with the command for how it was
  installed (`uv tool`, `pipx`, `pip`); it doesn't offer to update.
  Reason: a question would block unattended runs, and Certo can't know
  for sure which installer to run (pip does the same). At most one
  PyPI request a day, in the background, only on a terminal, not in CI
  or `certo bench`; `CERTO_UPDATE_CHECK=0` turns it off.

- **`python-environment` by keyword, `node-project-setup` by path**
  (2026-10-31, the Author's call to add both now, before a task shows
  their gap). The Python rules matter before any file is edited (the
  first `pip install`), so they fire on packaging words in the task;
  the words chosen match none of the bundled benchmark tasks
  ("dependencies" left out: three Node tasks say "no dependencies").
  The Node rules are about `package.json` itself, so they fire when the
  agent touches it, which the Node benchmark tasks do. Both are measured
  with a `skills_off` arm on a local and a cloud model before 0.1.27 is
  released (working agreement 2).

- **The MCP server: every command, on a shared core** (the Author,
  2026-10-31; built in 0.2, after the Phase 3 exit). Supersedes the
  one-line "MCP server for editors" idea. The design:
  1. **A shared core first (step 0).** A `certo.api` layer: one function
     per command, a typed request in, a typed result out, no printing
     and no prompts. The CLI, `certo-server` and the MCP server become
     thin layers over it. Reason: `cli.main` mixes flag parsing, logic
     and printing, and `server.py` has its own run path; an MCP server
     on top would either parse terminal text or be a third copy.
  2. **One result format, also as `certo --json`.** A versioned JSON
     result (verdict, checks, failing tests, files changed, cost,
     models, milestone states) returned by MCP, REST and a new `--json`
     flag. Reason: a wrapper, a CI script or the GitHub Action can use
     the CLI without MCP, and the three never disagree.
  3. **Two tool sets.** `certo-mcp --tools core` (run a task, run
     status, verify, check) and `--tools all` (every command, for
     wrappers). Reason: a client puts every tool's description in its
     model's context; ~25 tools crowd an editor's model, local ones
     most. Every tool carries MCP's read-only/destructive hints, so a
     client confirms `rollback`, `delete_project` and `purge`.
  4. **Long commands are runs.** `run_task`, `verify` and `bench` return
     a run id at once; `run_status`, `run_events` (since a cursor) and
     `run_cancel` follow it, with progress also as MCP notifications
     (polling always works). Cancel stops the agent cleanly and keeps
     the checkpoint, so `--resume` works after it. One run per project
     folder at a time (a lock), different folders in parallel, one
     `bench` at a time.
  5. **What is read is a resource, not a tool.** A project's
     `STATUS.md`, `RUNS.md`, run transcripts and bench `results.md` as
     MCP resources (`certo://projects/<name>/status`), which clients
     can show and watch.
  6. **The client limits the folders.** Certo works only inside the
     client's MCP roots (or `CERTO_PROJECTS_DIR` when it sends none).
     Questions Certo asks a person (confirm mode, escalation choice,
     `init`) are arguments or MCP elicitation; a client that can't
     answer gets the default that needs no answer. stdio first; HTTP
     only with authentication, which is the Author's item (server
     authentication).
  7. **Later, to check first: the client's model as Certo's model**,
     through MCP sampling: Certo would run on the editor's model with
     no key of its own. Needs a model adapter beside LiteLLM, and
     sampling with tool calls verified in clients; not in the first
     version.
  Kept from the earlier plan: every command in
  `docs/reference/commands.md` has a tool, and a test fails when one
  doesn't. Verify the MCP Python SDK (and spec features such as
  elicitation, roots and long-running tasks) before use (golden rule 2).

- **`node-project-setup` fires on words, not on `package.json`**
  (2026-10-31; supersedes "by path" in the entry above). Path rules fire
  only when the file editor touches the file (ARCHITECTURE.md), and in 9
  Haiku runs on the Node tasks it never did: the agent read
  `package.json` with `cat`, and `npm init`/`npm install` change it from
  the terminal. Triggers: node, node.js, nodejs, npm, javascript,
  typescript; they match the four Node benchmark tasks and nothing else
  bundled. "node" can also match an unrelated "node" (a tree's); kept,
  since a stray Node rule costs a few hundred tokens.
