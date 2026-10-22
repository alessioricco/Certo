# Decisions log

Why key choices were made: each entry is the decision plus the
load-bearing reason, so a future session doesn't re-litigate or
rediscover it. Append-only: a later decision that changes an earlier one
says so ("supersedes ...") rather than editing it away.

> **Full history:** every entry through 2026-09-20 is a compressed
> summary. The complete narrative (alternatives considered,
> live-verification transcripts, exact quotes) lives in
> `docs/ROADMAP.txt` (a frozen snapshot) and in git history.

Each entry is the decision plus the load-bearing reason. Full alternatives
considered and live-verification detail: `docs/ROADMAP.txt`.

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
  since 0.1.0; `docs/launch/github-rename.md` is the historical checklist. `docs/ROADMAP.txt` is a
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
