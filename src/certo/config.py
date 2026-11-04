"""Configuration for Certo.

Pure environment parsing — deliberately free of any OpenHands SDK import so it can
be unit-tested with no network and no SDK installed. `llm.py` consumes the
CERTO_LLM_* values (wrapping the key in SecretStr when it builds the SDK's LLM);
everything else is harness policy.

The model-agnostic invariant lives here: the provider/model is entirely a function
of the CERTO_LLM_MODEL env var. Nothing in this module (or anywhere in src/) hardcodes a
provider, model, or base URL.
"""

from __future__ import annotations

import contextvars
import logging
import math
import os
import platform as _platform
from collections.abc import Iterator, Mapping, MutableMapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

CONFIRM_MODES = ("never", "always")
EXECUTION_MODES = ("local", "docker")
DOCKER_PLATFORMS = ("linux/amd64", "linux/arm64")
VERIFY_TESTS_MODES = ("always", "never")
TASK_STORE_BACKENDS = ("memory", "redis", "sqlite", "mysql", "postgres")
MODEL_SELECTION_MODES = ("manual", "auto", "escalate")
ESCALATION_HANDOFFS = ("continue", "restart")

logger = logging.getLogger(__name__)

DEFAULT_WORKSPACE = "."
DEFAULT_MAX_ITERATIONS = 50
DEFAULT_CONFIRM_MODE = "never"
DEFAULT_EXECUTION = "local"
DEFAULT_PROJECTS_DIR = "./projects"
MAX_INDEPENDENT_TESTS_SETS = 5
# First-party catalog shipped inside the package, so it loads from any cwd
# and from an installed wheel, not only from a repo checkout.
BUILTIN_SKILLS_DIR = str(Path(__file__).resolve().parent / "builtin_skills")
DEFAULT_VERIFY_TESTS = "always"
DEFAULT_MAX_VERIFY_RETRIES = 2
DEFAULT_MAX_TASK_SECONDS = 1800
# The SDK's own default for one model call (`LLM.timeout`). 0 means no limit.
DEFAULT_LLM_TIMEOUT_SECONDS = 300
# CERTO_CONTEXT_WARN_TOKENS: the window the 0.1.25 context benchmark ran
# well at with condensing (docs/benchmark/context-0.1.25.md).
DEFAULT_CONTEXT_WARN_TOKENS = 32768
# CERTO_TOOL_CALL_REMINDERS: 25 of 151 saved qwen3.8 runs ended on a tool
# call written as text, at most once per run (text_tool_calls.py).
DEFAULT_TOOL_CALL_REMINDERS = 3
DEFAULT_DOCKER_IMAGE = "certo/agent-server:local"
DEFAULT_DOCKER_PLATFORM = (
    "linux/arm64" if _platform.machine().lower() in ("arm64", "aarch64") else "linux/amd64"
)

# --- Server-mode task registry persistence (see task_store.py) -------------
DEFAULT_TASK_STORE = "memory"
# 0 means "keep forever" — matches the pre-existing (unbounded, in-memory)
# behavior exactly, so enabling a store backend alone never changes
# retention; a TTL is something a caller opts into separately.
DEFAULT_TASK_TTL_SECONDS = 0
DEFAULT_TASK_STORE_SQLITE_PATH = "./certo_tasks.db"
# Pre-rename default; task_store.py still opens it when only it exists.
LEGACY_TASK_STORE_SQLITE_PATH = "./harness_tasks.db"
DEFAULT_TASK_STORE_MYSQL_HOST = "localhost"
DEFAULT_TASK_STORE_MYSQL_PORT = 3306
DEFAULT_TASK_STORE_MYSQL_USER = "root"
DEFAULT_TASK_STORE_MYSQL_DATABASE = "certo"
DEFAULT_TASK_STORE_POSTGRES_HOST = "localhost"
DEFAULT_TASK_STORE_POSTGRES_PORT = 5432
DEFAULT_TASK_STORE_POSTGRES_USER = "postgres"
DEFAULT_TASK_STORE_POSTGRES_DATABASE = "certo"
DEFAULT_TASK_STORE_REDIS_HOST = "localhost"
DEFAULT_TASK_STORE_REDIS_PORT = 6379
DEFAULT_TASK_STORE_REDIS_DB = 0

# --- Deterministic auto model selection (see model_catalog.py) -------------
DEFAULT_MODEL_SELECTION = "manual"  # one of MODEL_SELECTION_MODES
# Blank: look for models.yaml / models_list.yaml in the current folder, then
# the user settings folder (see model_files.py).
DEFAULT_MODELS_FILE = ""


class ConfigError(ValueError):
    """Raised when the environment is missing or invalid. Message is user-facing."""


@dataclass(frozen=True)
class Config:
    """Resolved, validated harness configuration."""

    # LLM selection (consumed by llm.py). Provider is encoded in `model`'s prefix.
    model: str
    api_key: str | None
    base_url: str | None

    # Certo policy (not the LLM's concern).
    workspace: str
    max_iterations: int
    confirm_mode: str  # one of CONFIRM_MODES
    execution: str  # one of EXECUTION_MODES

    # Where generated projects live: workspace defaults to plain CERTO_WORKSPACE,
    # but `--project NAME` (cli.py) overrides it to `projects_dir/NAME`, created if
    # missing, so each project's generated software lands in its own subfolder.
    projects_dir: str = DEFAULT_PROJECTS_DIR

    # The global skills folder (skill_library.py). Blank: the user folder's
    # `skills/`. No setting reads it; `certo bench` points it at an empty
    # folder so a user's own skills never change benchmark results.
    global_skills_dir: str = ""
    # Official skills a run doesn't get, by name. No setting reads it; a
    # `certo bench` arm sets it (`skills_off`) to measure what a skill
    # changes (agent.py).
    skills_off: tuple[str, ...] = ()

    # Only consulted when execution == "docker" (see workspace.py).
    docker_image: str = DEFAULT_DOCKER_IMAGE
    docker_platform: str = DEFAULT_DOCKER_PLATFORM  # one of DOCKER_PLATFORMS

    # Post-hoc test verification (see runner.py's _verify_tests_and_retry):
    # after the agent finishes, the harness itself re-runs the project's
    # pytest suite (no LLM involved) and, if it fails, sends the real
    # failure output back and lets the agent try again, up to this many
    # times — a safety net for trusting the agent's own "it's done" self-
    # report, which live testing showed can be wrong (see DECISIONS.md).
    verify_tests: str = DEFAULT_VERIFY_TESTS  # one of VERIFY_TESTS_MODES
    max_verify_retries: int = DEFAULT_MAX_VERIFY_RETRIES

    # A shared, task-level wall-clock budget spanning every phase of one task
    # — the initial conversation.run(), and all of _enforce_task_tracker_
    # completion's and _verify_and_report's retries — not just the SDK's own
    # max_iteration_per_run, which resets on every single run() call and so
    # cannot on its own bound how long one task can run in total (see
    # runner.py's _run_with_confirmation and DECISIONS.md).
    max_task_seconds: int = DEFAULT_MAX_TASK_SECONDS

    # Provider-neutral reasoning effort, consumed by llm.py and passed
    # straight through to the SDK's own `LLM.reasoning_effort` (LiteLLM
    # translates it per-provider — see DECISIONS.md).
    # Deliberately not validated against a fixed choice list: the SDK's own
    # field accepts forward-compatible values beyond its documented ones
    # ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', ...), so
    # this harness shouldn't reject one it doesn't yet know about. None
    # means "not configured" — llm.py picks the default (see
    # `build_llm`). "off" is normalized to "none", which llm.py turns into
    # an explicit "send no reasoning parameter at all".
    reasoning_effort: str | None = None

    # CERTO_LLM_TIMEOUT_SECONDS: how long one model call may take before it
    # fails (passed to the SDK's `LLM.timeout`; 0 = no limit). Slow local
    # models can need more than the 300-second default.
    llm_timeout_seconds: int = DEFAULT_LLM_TIMEOUT_SECONDS
    # CERTO_LLM_CONTEXT_TOKENS: the model's context window; 0 = what the
    # provider reports (asked from the server for Ollama). For Ollama, a set
    # value is also requested from the server (context_window.py, llm.py).
    llm_context_tokens: int = 0

    # Server-mode task registry persistence (see task_store.py). Default
    # ("memory", no TTL) is byte-for-byte the pre-existing behavior — this
    # entire feature is additive, never a silent behavior change for an
    # existing server-mode deployment.
    task_store: str = DEFAULT_TASK_STORE  # one of TASK_STORE_BACKENDS
    task_ttl_seconds: int = DEFAULT_TASK_TTL_SECONDS  # 0 = keep forever

    task_store_sqlite_path: str = DEFAULT_TASK_STORE_SQLITE_PATH

    task_store_mysql_host: str = DEFAULT_TASK_STORE_MYSQL_HOST
    task_store_mysql_port: int = DEFAULT_TASK_STORE_MYSQL_PORT
    task_store_mysql_user: str = DEFAULT_TASK_STORE_MYSQL_USER
    task_store_mysql_password: str | None = None
    task_store_mysql_database: str = DEFAULT_TASK_STORE_MYSQL_DATABASE

    task_store_postgres_host: str = DEFAULT_TASK_STORE_POSTGRES_HOST
    task_store_postgres_port: int = DEFAULT_TASK_STORE_POSTGRES_PORT
    task_store_postgres_user: str = DEFAULT_TASK_STORE_POSTGRES_USER
    task_store_postgres_password: str | None = None
    task_store_postgres_database: str = DEFAULT_TASK_STORE_POSTGRES_DATABASE

    task_store_redis_host: str = DEFAULT_TASK_STORE_REDIS_HOST
    task_store_redis_port: int = DEFAULT_TASK_STORE_REDIS_PORT
    task_store_redis_db: int = DEFAULT_TASK_STORE_REDIS_DB
    task_store_redis_password: str | None = None
    task_store_redis_use_tls: bool = False

    # Opt-in interactive mode (see runner.py's stream_task interactive loop
    # and agent.py's build_agent): when true, drops _AUTONOMOUS_SUFFIX from
    # the system prompt so the agent may pause/ask instead of being told to
    # always push forward on its own. Only meaningful for a caller that also
    # supplies an on_awaiting_input callback (cli.py's --interactive does;
    # server.py never does, same as CERTO_CONFIRM_MODE=always having no
    # effect there) — default false, current fully-autonomous behavior
    # unchanged.
    interactive: bool = False

    # CERTO_INDEPENDENT_TESTS: before the build, a separate conversation
    # writes tests from the task and the project as it is then; after the
    # verdict Certo runs them and reports the result next to it, without
    # changing the verdict (independent_tests.py). Local runs only.
    independent_tests: bool = False
    # CERTO_INDEPENDENT_TESTS_SETS: how many writers each write a set; the
    # result is "failed" only when most sets fail (1 to 5).
    independent_tests_sets: int = 3
    # CERTO_INDEPENDENT_TESTS_STRICT: a `verified` run whose independent
    # tests failed (most sets) ends `independent_failed` instead. Turns the
    # tests on.
    independent_tests_strict: bool = False
    # CERTO_CHECKPOINTS: snapshots of the project in .certo/checkpoints/
    # during a run, for `certo rollback` (checkpoints.py).
    checkpoints: bool = True
    # CERTO_CONDENSE: let the SDK summarize older steps when the
    # conversation nears the model's context window (agent.py).
    condense: bool = True
    # CERTO_CONTEXT_WARN_TOKENS: warn at the start of a run when the
    # model's known context window is smaller; 0 = never (context_window.py).
    context_warn_tokens: int = DEFAULT_CONTEXT_WARN_TOKENS
    # CERTO_TOOL_CALL_REMINDERS: when the agent ends on a tool call written
    # as text, send it back this many times per run at most; 0 = never
    # (runner._remind_text_tool_call).
    tool_call_reminders: int = DEFAULT_TOOL_CALL_REMINDERS

    # The full SDK console output: the system prompt, the whole task with
    # its skills, the SDK's INFO logs. Off by default (console.py shows a
    # line for each instead).
    verbose: bool = False
    # CERTO_PROGRESS_SECONDS: how often a terminal run prints its progress
    # line while the agent works (run_progress.py); 0 turns the line off.
    progress_seconds: int = 120

    # Deterministic auto model selection (see model_catalog.py/
    # model_selection.py). Default ("manual") is byte-for-byte the
    # pre-existing behavior — cfg.model is used exactly as it always has
    # been. The model files (model_files.py) are read only for "auto" and
    # "escalate", and by `certo check`: CERTO_MODELS_FILE is the personal
    # models.yaml, CERTO_MODELS_LIST_FILE the catalog; blank looks them up.
    # CERTO_TASK_PROFILES_FILE and CERTO_ESCALATION_FILE name the two
    # optional files (since 0.1.20); blank looks them up too.
    model_selection: str = DEFAULT_MODEL_SELECTION  # one of MODEL_SELECTION_MODES
    models_file: str = DEFAULT_MODELS_FILE
    models_list_file: str = ""
    task_profiles_file: str = ""
    escalation_file: str = ""
    # CERTO_ESCALATION_LADDER: with model_selection "escalate", the ladder
    # from models_list.yaml to climb; blank: `default`, else a derived one
    # (see escalation.py).
    escalation_ladder: str = ""
    # CERTO_ESCALATION_HANDOFF: what the next rung starts from. "continue"
    # (default): the files as the previous rung left them. "restart": the
    # files as they were before the first rung, restored from a checkpoint
    # (the previous rung's work stays in one, see checkpoints.py).
    escalation_handoff: str = "continue"
    # CERTO_MAX_TASK_COST: a USD cap on a task, every rung and the
    # independent tests included. The agent is stopped once the cost
    # reaches it (cost_limit.py), and no escalation rung starts past it;
    # unknown prices count as 0. None (unset) means no cap.
    max_task_cost: float | None = None

    # Opt-in per-run artifacts directory (see artifacts.py): metadata, the
    # full message transcript, and token/cost metrics for each task run,
    # one subfolder per project per run. Blank (the default) means the
    # feature is off entirely — same "blank means off" convention as
    # CERTO_LLM_BASE_URL/CERTO_DOCKER_PLATFORM, no separate on/off flag needed.
    artifacts_dir: str = ""

    # CERTO_NO_WORKTREE_WARNING: skip the CLI's note before the agent edits
    # a folder that already has files (see worktree.py).
    no_worktree_warning: bool = False

    # CERTO_SAVE_STATE: the CLI keeps the last run's state in the project's
    # .certo/ folder, for `certo --resume` (see project_state.py).
    save_state: bool = True


# Certo's LLM settings. Up to 0.1.1 Certo read the bare LLM_* names, which other
# tools use too; those are never read now (another app's LLM_MODEL must not
# leak in), only named in the "required" errors so an old setup gets told why.
LLM_ENV_PREFIX = "CERTO_LLM_"
_OLD_LLM_ENV_PREFIX = "LLM_"


def _old_llm_names_hint(env: Mapping[str, str], *suffixes: str) -> str:
    """A sentence naming old LLM_* variables that are set, for an error
    message, or "" when there are none. Only says *that* they're set, never
    their values (one may be an API key)."""
    found = [
        _OLD_LLM_ENV_PREFIX + s
        for s in suffixes
        if _clean(env.get(_OLD_LLM_ENV_PREFIX + s)) is not None
    ]
    if not found:
        return ""
    renames = ", ".join(f"{name} -> CERTO_{name}" for name in found)
    return (
        f" Found {', '.join(found)}, which Certo no longer reads: its LLM "
        f"settings now use the CERTO_LLM_ prefix, so other tools' LLM_* "
        f"variables can't leak in. Rename {renames}."
    )


def _clean(value: str | None) -> str | None:
    """Trim whitespace; treat empty string as absent."""
    if value is None:
        return None
    value = value.strip()
    return value or None


# Spellings of "reasoning disabled", normalized to the SDK's own "none".
_REASONING_OFF = {"none", "off"}


def _clean_reasoning_effort(value: str | None) -> str | None:
    """Like `_clean`, but folds every "disabled" spelling into "none"."""
    value = _clean(value)
    if value is not None and value.lower() in _REASONING_OFF:
        return "none"
    return value


# Every policy env var is CERTO_<NAME>. The pre-rename HARNESS_<NAME> spelling
# is still read as a fallback for one release: a non-blank CERTO_ value wins,
# otherwise a non-blank HARNESS_ value is used and logged once per process as
# deprecated. Blank counts as unset on both sides, so a fresh .env copied from
# .env.example (blank CERTO_ lines) doesn't mask an old HARNESS_ setting.
ENV_PREFIX = "CERTO_"
LEGACY_ENV_PREFIX = "HARNESS_"

_warned_legacy_vars: set[str] = set()


def _read(env: Mapping[str, str], suffix: str) -> tuple[str | None, str]:
    """Return `(raw value, name of the variable it came from)` for one
    CERTO_/HARNESS_ setting. The name is what error messages quote, so a bad
    value is reported under the variable the user actually set."""
    name = ENV_PREFIX + suffix
    value = env.get(name)
    if _clean(value) is not None:
        return value, name
    legacy_name = LEGACY_ENV_PREFIX + suffix
    legacy_value = env.get(legacy_name)
    if _clean(legacy_value) is not None:
        if legacy_name not in _warned_legacy_vars:
            _warned_legacy_vars.add(legacy_name)
            logger.warning("%s is deprecated; rename it to %s.", legacy_name, name)
        return legacy_value, legacy_name
    return value, name


# The old skill folders' settings, no longer read since 0.1.23 (skill
# library: `certo skills`). One still set is named once per process, so its
# skills don't drop out of a run unnoticed.
_REMOVED_SKILL_SETTINGS = ("SKILLS_DIR", "THIRD_PARTY_SKILLS_DIR", "THIRD_PARTY_SKILLS_LOCK")
_warned_removed_vars: set[str] = set()


def _warn_removed_skill_settings(env: Mapping[str, str]) -> None:
    for suffix in _REMOVED_SKILL_SETTINGS:
        for name in (ENV_PREFIX + suffix, LEGACY_ENV_PREFIX + suffix):
            if _clean(env.get(name)) is None or name in _warned_removed_vars:
                continue
            _warned_removed_vars.add(name)
            logger.warning(
                "%s is no longer read: Certo no longer uses the old skill folders. Add each "
                "skill again with: certo skills add PATH --global (or --project NAME).",
                name,
            )


def _get(env: Mapping[str, str], suffix: str) -> str | None:
    return _clean(_read(env, suffix)[0])


def _parse_positive_int(env: Mapping[str, str], suffix: str, *, default: int) -> int:
    value, name = _read(env, suffix)
    if _clean(value) is None:
        return default
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ConfigError(f"{name} must be an integer, got {value!r}.") from None
    if parsed <= 0:
        raise ConfigError(f"{name} must be a positive integer, got {parsed}.")
    return parsed


def _parse_choice(
    env: Mapping[str, str], suffix: str, *, default: str, choices: tuple[str, ...]
) -> str:
    value, name = _read(env, suffix)
    resolved = (_clean(value) or default).lower()
    if resolved not in choices:
        allowed = " | ".join(choices)
        raise ConfigError(f"{name} must be one of: {allowed}. Got {resolved!r}.")
    return resolved


def _parse_nonnegative_int(env: Mapping[str, str], suffix: str, *, default: int) -> int:
    """Like `_parse_positive_int` but allows `0` — used only where `0` is a
    real, meaningful setting ("no limit"/"keep forever"), not "unset".
    """
    value, name = _read(env, suffix)
    if _clean(value) is None:
        return default
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ConfigError(f"{name} must be an integer, got {value!r}.") from None
    if parsed < 0:
        raise ConfigError(f"{name} must be zero or a positive integer, got {parsed}.")
    return parsed


def _parse_optional_cost(env: Mapping[str, str], suffix: str) -> float | None:
    value, name = _read(env, suffix)
    cleaned = _clean(value)
    if cleaned is None:
        return None
    try:
        parsed = float(cleaned)
    except ValueError:
        raise ConfigError(f"{name} must be an amount in US dollars, got {value!r}.") from None
    if parsed < 0 or math.isnan(parsed):
        raise ConfigError(f"{name} must be zero or more, got {value!r}.")
    return parsed


def _parse_bool(env: Mapping[str, str], suffix: str, *, default: bool) -> bool:
    value, name = _read(env, suffix)
    cleaned = _clean(value)
    if cleaned is None:
        return default
    lowered = cleaned.lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{name} must be a boolean (true/false), got {value!r}.")


def user_settings_path(environ: Mapping[str, str] | None = None) -> str:
    """The settings file for every project on this computer:
    `$XDG_CONFIG_HOME/certo/.env`, else `~/.config/certo/.env`, on every
    platform. A relative XDG_CONFIG_HOME is ignored, as the XDG spec says."""
    environ = os.environ if environ is None else environ
    xdg = (environ.get("XDG_CONFIG_HOME") or "").strip()
    base = xdg if os.path.isabs(xdg) else os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "certo", ".env")


@dataclass(frozen=True)
class SettingSource:
    """Where one setting's value came from."""

    kind: str  # "environment" | "folder" | "user"
    path: str | None = None

    def describe(self) -> str:
        if self.kind == "environment":
            return "environment variable"
        if self.kind == "folder":
            return f"./.env ({self.path})"
        return f"user settings ({self.path})"


def load_settings_files(
    dotenv_path: str = ".env",
    user_path: str | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> dict[str, SettingSource]:
    """Fill `environ` (os.environ by default) from the folder's `.env`, then
    the user settings file, and return where each set variable came from.

    Each variable is resolved on its own, in this order: the environment,
    then `dotenv_path`, then `user_path`. A source only fills a variable no
    earlier source set, so nothing overrides a higher-priority value. A
    blank value counts as unset (as in `_read`), so a `CERTO_LLM_API_KEY=`
    line left empty in a folder's `.env` doesn't hide the user file's key.
    The user file is read after the folder's values are in `environ`, so
    its `${VAR}` references can see them. Missing files are skipped.
    """
    # DotEnv with override=False is what load_dotenv() uses: a `${VAR}`
    # reference sees the environment before the file's own earlier lines.
    from dotenv.main import DotEnv

    environ = os.environ if environ is None else environ
    user_path = user_settings_path(environ) if user_path is None else user_path
    sources = {
        name: SettingSource("environment") for name, value in environ.items() if _clean(value)
    }
    for kind, path in (("folder", dotenv_path), ("user", user_path)):
        if not os.path.isfile(path):
            continue
        values = DotEnv(path, interpolate=True, override=False, encoding="utf-8").dict()
        for name, value in values.items():
            if name in sources or _clean(value) is None:
                continue
            environ[name] = value  # type: ignore[assignment]
            sources[name] = SettingSource(kind, os.path.abspath(path))
    return sources


def _missing_model_message(env: Mapping[str, str], dotenv_path: str, user_path: str) -> str:
    return (
        "CERTO_LLM_MODEL is required (e.g. 'anthropic/claude-sonnet-5-5' or "
        "'ollama/qwen3.8:27b'), and it isn't set in any of the three places "
        "Certo looks, in this order: 1. the environment (export CERTO_LLM_MODEL=...); "
        f"2. .env in the current folder ({os.path.abspath(dotenv_path)}); "
        f"3. the user settings file ({user_path}). Run certo init to write it, "
        "or set it in one of these. Switching provider = changing only this value."
        + _old_llm_names_hint(env, "MODEL")
    )


def _missing_api_key_message(env: Mapping[str, str]) -> str:
    return (
        "CERTO_LLM_API_KEY is required unless CERTO_LLM_BASE_URL is set (e.g. a "
        "local Ollama/vLLM/LM Studio endpoint that needs no key)."
        + _old_llm_names_hint(env, "API_KEY", "BASE_URL")
    )


# When False, load_config skips the model/key required checks so a caller can
# apply CLI or request overrides first, then validate the final values (see
# defer_llm_check and ensure_llm_configured). Default True keeps every other
# caller unchanged.
_llm_check: contextvars.ContextVar[bool] = contextvars.ContextVar("certo_llm_check", default=True)


@contextmanager
def defer_llm_check() -> Iterator[None]:
    """Skip model/key required checks inside load_config for this context.

    Use when CLI flags or request fields will supply the model (and key or
    base URL) via override_llm afterwards. Call ensure_llm_configured on the
    result so a cloud model with no key is still an error.
    """
    token = _llm_check.set(False)
    try:
        yield
    finally:
        _llm_check.reset(token)


def load_config(
    env: Mapping[str, str] | None = None,
    *,
    dotenv_path: str = ".env",
    user_dotenv_path: str | None = None,
) -> Config:
    """Load and validate configuration.

    Args:
        env: Optional mapping to read from (defaults to os.environ). Passing a dict
            makes this fully testable without touching the real environment or a
            .env file.
        dotenv_path: The folder's .env, loaded into os.environ when `env` is None.
        user_dotenv_path: The user settings file, loaded after `dotenv_path` when
            `env` is None (default: `user_settings_path()`). See
            `load_settings_files` for the order. Missing files are ignored.

    Raises:
        ConfigError: if required values are missing or any value is invalid.
    """
    user_path = user_settings_path() if user_dotenv_path is None else user_dotenv_path
    if env is None:
        load_settings_files(dotenv_path, user_path)
        env = os.environ

    check_llm = _llm_check.get()
    model = _clean(env.get(LLM_ENV_PREFIX + "MODEL"))
    if model is None:
        if check_llm:
            raise ConfigError(_missing_model_message(env, dotenv_path, user_path))
        # Placeholder until override_llm (or the caller) fills it in.
        model = ""

    api_key = _clean(env.get(LLM_ENV_PREFIX + "API_KEY"))
    base_url = _clean(env.get(LLM_ENV_PREFIX + "BASE_URL"))
    if api_key is None and base_url is None and check_llm:
        raise ConfigError(_missing_api_key_message(env))
    reasoning_effort = _clean_reasoning_effort(env.get(LLM_ENV_PREFIX + "REASONING_EFFORT"))
    llm_timeout_seconds = _parse_nonnegative_int(
        env, "LLM_TIMEOUT_SECONDS", default=DEFAULT_LLM_TIMEOUT_SECONDS
    )
    llm_context_tokens = _parse_nonnegative_int(env, "LLM_CONTEXT_TOKENS", default=0)

    workspace = _get(env, "WORKSPACE") or DEFAULT_WORKSPACE
    max_iterations = _parse_positive_int(
        env,
        "MAX_ITERATIONS",
        default=DEFAULT_MAX_ITERATIONS,
    )
    confirm_mode = _parse_choice(
        env,
        "CONFIRM_MODE",
        default=DEFAULT_CONFIRM_MODE,
        choices=CONFIRM_MODES,
    )
    execution = _parse_choice(
        env,
        "EXECUTION",
        default=DEFAULT_EXECUTION,
        choices=EXECUTION_MODES,
    )
    projects_dir = _get(env, "PROJECTS_DIR") or DEFAULT_PROJECTS_DIR
    _warn_removed_skill_settings(env)
    docker_image = _get(env, "DOCKER_IMAGE") or DEFAULT_DOCKER_IMAGE
    docker_platform = _parse_choice(
        env,
        "DOCKER_PLATFORM",
        default=DEFAULT_DOCKER_PLATFORM,
        choices=DOCKER_PLATFORMS,
    )
    verify_tests = _parse_choice(
        env,
        "VERIFY_TESTS",
        default=DEFAULT_VERIFY_TESTS,
        choices=VERIFY_TESTS_MODES,
    )
    max_verify_retries = _parse_positive_int(
        env,
        "MAX_VERIFY_RETRIES",
        default=DEFAULT_MAX_VERIFY_RETRIES,
    )
    max_task_seconds = _parse_positive_int(
        env,
        "MAX_TASK_SECONDS",
        default=DEFAULT_MAX_TASK_SECONDS,
    )

    task_store = _parse_choice(
        env,
        "TASK_STORE",
        default=DEFAULT_TASK_STORE,
        choices=TASK_STORE_BACKENDS,
    )
    task_ttl_seconds = _parse_nonnegative_int(
        env,
        "TASK_TTL_SECONDS",
        default=DEFAULT_TASK_TTL_SECONDS,
    )
    task_store_sqlite_path = _get(env, "TASK_STORE_SQLITE_PATH") or DEFAULT_TASK_STORE_SQLITE_PATH
    task_store_mysql_host = _get(env, "TASK_STORE_MYSQL_HOST") or DEFAULT_TASK_STORE_MYSQL_HOST
    task_store_mysql_port = _parse_positive_int(
        env,
        "TASK_STORE_MYSQL_PORT",
        default=DEFAULT_TASK_STORE_MYSQL_PORT,
    )
    task_store_mysql_user = _get(env, "TASK_STORE_MYSQL_USER") or DEFAULT_TASK_STORE_MYSQL_USER
    task_store_mysql_password = _get(env, "TASK_STORE_MYSQL_PASSWORD")
    task_store_mysql_database = (
        _get(env, "TASK_STORE_MYSQL_DATABASE") or DEFAULT_TASK_STORE_MYSQL_DATABASE
    )
    task_store_postgres_host = (
        _get(env, "TASK_STORE_POSTGRES_HOST") or DEFAULT_TASK_STORE_POSTGRES_HOST
    )
    task_store_postgres_port = _parse_positive_int(
        env,
        "TASK_STORE_POSTGRES_PORT",
        default=DEFAULT_TASK_STORE_POSTGRES_PORT,
    )
    task_store_postgres_user = (
        _get(env, "TASK_STORE_POSTGRES_USER") or DEFAULT_TASK_STORE_POSTGRES_USER
    )
    task_store_postgres_password = _get(env, "TASK_STORE_POSTGRES_PASSWORD")
    task_store_postgres_database = (
        _get(env, "TASK_STORE_POSTGRES_DATABASE") or DEFAULT_TASK_STORE_POSTGRES_DATABASE
    )
    task_store_redis_host = _get(env, "TASK_STORE_REDIS_HOST") or DEFAULT_TASK_STORE_REDIS_HOST
    task_store_redis_port = _parse_positive_int(
        env,
        "TASK_STORE_REDIS_PORT",
        default=DEFAULT_TASK_STORE_REDIS_PORT,
    )
    task_store_redis_db = _parse_nonnegative_int(
        env,
        "TASK_STORE_REDIS_DB",
        default=DEFAULT_TASK_STORE_REDIS_DB,
    )
    task_store_redis_password = _get(env, "TASK_STORE_REDIS_PASSWORD")
    task_store_redis_use_tls = _parse_bool(
        env,
        "TASK_STORE_REDIS_USE_TLS",
        default=False,
    )
    interactive = _parse_bool(
        env,
        "INTERACTIVE",
        default=False,
    )
    verbose = _parse_bool(env, "VERBOSE", default=False)
    progress_seconds = _parse_nonnegative_int(env, "PROGRESS_SECONDS", default=120)
    independent_tests_strict = _parse_bool(env, "INDEPENDENT_TESTS_STRICT", default=False)
    independent_tests = (
        _parse_bool(env, "INDEPENDENT_TESTS", default=False) or independent_tests_strict
    )
    independent_tests_sets = _parse_positive_int(env, "INDEPENDENT_TESTS_SETS", default=3)
    checkpoints = _parse_bool(env, "CHECKPOINTS", default=True)
    condense = _parse_bool(env, "CONDENSE", default=True)
    context_warn_tokens = _parse_nonnegative_int(
        env, "CONTEXT_WARN_TOKENS", default=DEFAULT_CONTEXT_WARN_TOKENS
    )
    tool_call_reminders = _parse_nonnegative_int(
        env, "TOOL_CALL_REMINDERS", default=DEFAULT_TOOL_CALL_REMINDERS
    )
    if independent_tests_sets > MAX_INDEPENDENT_TESTS_SETS:
        raise ConfigError(
            f"CERTO_INDEPENDENT_TESTS_SETS must be at most {MAX_INDEPENDENT_TESTS_SETS}, "
            f"got {independent_tests_sets}."
        )
    model_selection = _parse_choice(
        env,
        "MODEL_SELECTION",
        default=DEFAULT_MODEL_SELECTION,
        choices=MODEL_SELECTION_MODES,
    )
    models_file = _get(env, "MODELS_FILE") or DEFAULT_MODELS_FILE
    models_list_file = _get(env, "MODELS_LIST_FILE") or ""
    task_profiles_file = _get(env, "TASK_PROFILES_FILE") or ""
    escalation_file = _get(env, "ESCALATION_FILE") or ""
    escalation_ladder = _get(env, "ESCALATION_LADDER") or ""
    escalation_handoff = _parse_choice(
        env, "ESCALATION_HANDOFF", default="continue", choices=ESCALATION_HANDOFFS
    )
    max_task_cost = _parse_optional_cost(env, "MAX_TASK_COST")
    artifacts_dir = _get(env, "ARTIFACTS_DIR") or ""
    no_worktree_warning = _parse_bool(env, "NO_WORKTREE_WARNING", default=False)
    save_state = _parse_bool(env, "SAVE_STATE", default=True)

    return Config(
        model=model,
        api_key=api_key,
        base_url=base_url,
        workspace=workspace,
        max_iterations=max_iterations,
        confirm_mode=confirm_mode,
        execution=execution,
        projects_dir=projects_dir,
        docker_image=docker_image,
        docker_platform=docker_platform,
        verify_tests=verify_tests,
        max_verify_retries=max_verify_retries,
        max_task_seconds=max_task_seconds,
        reasoning_effort=reasoning_effort,
        llm_timeout_seconds=llm_timeout_seconds,
        llm_context_tokens=llm_context_tokens,
        task_store=task_store,
        task_ttl_seconds=task_ttl_seconds,
        task_store_sqlite_path=task_store_sqlite_path,
        task_store_mysql_host=task_store_mysql_host,
        task_store_mysql_port=task_store_mysql_port,
        task_store_mysql_user=task_store_mysql_user,
        task_store_mysql_password=task_store_mysql_password,
        task_store_mysql_database=task_store_mysql_database,
        task_store_postgres_host=task_store_postgres_host,
        task_store_postgres_port=task_store_postgres_port,
        task_store_postgres_user=task_store_postgres_user,
        task_store_postgres_password=task_store_postgres_password,
        task_store_postgres_database=task_store_postgres_database,
        task_store_redis_host=task_store_redis_host,
        task_store_redis_port=task_store_redis_port,
        task_store_redis_db=task_store_redis_db,
        task_store_redis_password=task_store_redis_password,
        task_store_redis_use_tls=task_store_redis_use_tls,
        interactive=interactive,
        independent_tests=independent_tests,
        independent_tests_sets=independent_tests_sets,
        independent_tests_strict=independent_tests_strict,
        checkpoints=checkpoints,
        condense=condense,
        context_warn_tokens=context_warn_tokens,
        tool_call_reminders=tool_call_reminders,
        verbose=verbose,
        progress_seconds=progress_seconds,
        model_selection=model_selection,
        models_file=models_file,
        models_list_file=models_list_file,
        task_profiles_file=task_profiles_file,
        escalation_file=escalation_file,
        escalation_ladder=escalation_ladder,
        escalation_handoff=escalation_handoff,
        max_task_cost=max_task_cost,
        artifacts_dir=artifacts_dir,
        no_worktree_warning=no_worktree_warning,
        save_state=save_state,
    )


def ensure_llm_configured(
    cfg: Config,
    *,
    env: Mapping[str, str] | None = None,
    dotenv_path: str = ".env",
    user_dotenv_path: str | None = None,
) -> Config:
    """Raise ConfigError unless cfg has a model and either an api_key or a base_url.

    Same messages as load_config. Call after override_llm when load_config ran
    under defer_llm_check, so CLI flags are checked on the final values.
    """
    env = os.environ if env is None else env
    user_path = user_settings_path() if user_dotenv_path is None else user_dotenv_path
    if not cfg.model:
        raise ConfigError(_missing_model_message(env, dotenv_path, user_path))
    if cfg.api_key is None and cfg.base_url is None:
        raise ConfigError(_missing_api_key_message(env))
    return cfg


def override_llm(
    cfg: Config,
    *,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    reasoning_effort: str | None = None,
    timeout_seconds: int | None = None,
    context_tokens: int | None = None,
) -> Config:
    """Return a copy of `cfg` with CERTO_LLM_MODEL/CERTO_LLM_API_KEY/
    CERTO_LLM_BASE_URL/CERTO_LLM_REASONING_EFFORT/CERTO_LLM_TIMEOUT_SECONDS/
    CERTO_LLM_CONTEXT_TOKENS overridden.

    Lets a single call (CLI flag or a server request field) swap provider/model
    (or just the reasoning effort, independent of provider) for one run without
    touching `.env` - e.g. to compare how two models, or two effort levels of
    the same model, handle the same task. Only arguments that are not None are
    applied; anything else keeps `cfg`'s existing value. Does not re-check the
    api_key-or-base_url rule from load_config; callers that used
    defer_llm_check should call ensure_llm_configured on the result.
    """
    updates: dict[str, str | int | None] = {}
    if model is not None:
        cleaned_model = _clean(model)
        if cleaned_model is None:
            raise ConfigError("Model override must not be blank.")
        updates["model"] = cleaned_model
    if api_key is not None:
        updates["api_key"] = _clean(api_key)
    if base_url is not None:
        updates["base_url"] = _clean(base_url)
    if reasoning_effort is not None:
        updates["reasoning_effort"] = _clean_reasoning_effort(reasoning_effort)
    if timeout_seconds is not None:
        if timeout_seconds < 0:
            raise ConfigError(f"LLM timeout must be zero or more seconds, got {timeout_seconds}.")
        updates["llm_timeout_seconds"] = timeout_seconds
    if context_tokens is not None:
        if context_tokens < 0:
            raise ConfigError(f"Context window must be zero or more tokens, got {context_tokens}.")
        updates["llm_context_tokens"] = context_tokens
    return replace(cfg, **updates) if updates else cfg


def resolve_project_dir(projects_dir: str, project: str) -> str:
    """Resolve a caller-supplied `project` name to a path guaranteed to stay
    inside `projects_dir` — the one shared resolver `cli.py`'s `--project`
    and `server.py`'s `project` request field both go through, instead of
    each doing its own unguarded `os.path.join(projects_dir, project)`.

    That unguarded join was a real bug, not just missing hardening:
    `os.path.join(a, b)` silently discards `a` when `b` is absolute, so an
    absolute `project` value (e.g. `--project /etc/cron.d`, or the same
    value in an unauthenticated `POST /tasks` request) redirected the
    agent's entire workspace — including its terminal and file-editor tools
    — to an arbitrary path on the host. `..` traversal had the same effect
    more subtly.

    Checked in order: `project` itself must be non-empty, relative, and
    contain no `..` segment (rejected before any path is ever built, so the
    error names the exact problem rather than a generic "path escaped").
    The resolved path is then checked against `projects_dir` with symlinks
    followed on both sides (`os.path.realpath`) — not just a lexical
    comparison — so a project name that looks safe but resolves through an
    existing symlink out of `projects_dir` is caught too.

    Raises `ConfigError` — the one error type both callers already catch
    and turn into a clean CLI/HTTP error — rather than a bespoke exception.
    """
    if not project or project in (".", ".."):
        raise ConfigError(f"Invalid project name: {project!r}")
    if os.path.isabs(project):
        raise ConfigError(f"Project name must be relative, not absolute: {project!r}")
    if any(part == ".." for part in Path(project).parts):
        raise ConfigError(f"Project name must not contain '..': {project!r}")

    projects_root = os.path.abspath(projects_dir)
    project_dir = os.path.join(projects_root, project)

    resolved_root = os.path.realpath(projects_root)
    resolved_project_dir = os.path.realpath(project_dir)
    if not Path(resolved_project_dir).is_relative_to(Path(resolved_root)):
        raise ConfigError(f"Project path escapes CERTO_PROJECTS_DIR: {project!r}")

    return project_dir
