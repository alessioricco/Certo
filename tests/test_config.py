"""Tests for certo.config — pure, no SDK, no network.

Every test passes an explicit `env` dict so the real environment and .env file are
never touched.
"""

import os

import pytest

from certo.config import (
    DEFAULT_CONFIRM_MODE,
    DEFAULT_DOCKER_IMAGE,
    DEFAULT_DOCKER_PLATFORM,
    DEFAULT_EXECUTION,
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_MAX_TASK_SECONDS,
    DEFAULT_MAX_VERIFY_RETRIES,
    DEFAULT_PROJECTS_DIR,
    DEFAULT_TASK_STORE,
    DEFAULT_TASK_STORE_MYSQL_PORT,
    DEFAULT_TASK_STORE_POSTGRES_PORT,
    DEFAULT_TASK_STORE_REDIS_PORT,
    DEFAULT_TASK_STORE_SQLITE_PATH,
    DEFAULT_TASK_TTL_SECONDS,
    DEFAULT_VERIFY_TESTS,
    DEFAULT_WORKSPACE,
    Config,
    ConfigError,
    SettingSource,
    defer_llm_check,
    ensure_llm_configured,
    load_config,
    load_settings_files,
    override_llm,
    resolve_project_dir,
    user_settings_path,
)


def _base_env(**overrides: str) -> dict[str, str]:
    env = {
        "CERTO_LLM_MODEL": "anthropic/claude-sonnet-4-5-20250929",
        "CERTO_LLM_API_KEY": "sk-test",
    }
    env.update(overrides)
    return env


def test_minimal_valid_env_applies_defaults():
    cfg = load_config(_base_env())
    assert isinstance(cfg, Config)
    assert cfg.model == "anthropic/claude-sonnet-4-5-20250929"
    assert cfg.api_key == "sk-test"
    assert cfg.base_url is None
    assert cfg.workspace == DEFAULT_WORKSPACE
    assert cfg.max_iterations == DEFAULT_MAX_ITERATIONS
    assert cfg.confirm_mode == DEFAULT_CONFIRM_MODE
    assert cfg.execution == DEFAULT_EXECUTION
    assert cfg.projects_dir == DEFAULT_PROJECTS_DIR
    assert cfg.docker_image == DEFAULT_DOCKER_IMAGE
    assert cfg.docker_platform == DEFAULT_DOCKER_PLATFORM
    assert cfg.verify_tests == DEFAULT_VERIFY_TESTS
    assert cfg.max_verify_retries == DEFAULT_MAX_VERIFY_RETRIES
    assert cfg.reasoning_effort is None


def test_all_values_parsed():
    cfg = load_config(
        _base_env(
            CERTO_LLM_BASE_URL="http://localhost:11434",
            CERTO_LLM_REASONING_EFFORT="low",
            CERTO_WORKSPACE="/tmp/ws",
            CERTO_MAX_ITERATIONS="12",
            CERTO_CONFIRM_MODE="always",
            CERTO_EXECUTION="docker",
            CERTO_PROJECTS_DIR="/tmp/projects",
            CERTO_DOCKER_IMAGE="myorg/agent-server:custom",
            CERTO_DOCKER_PLATFORM="linux/amd64",
            CERTO_VERIFY_TESTS="never",
            CERTO_MAX_VERIFY_RETRIES="5",
        )
    )
    assert cfg.base_url == "http://localhost:11434"
    assert cfg.workspace == "/tmp/ws"
    assert cfg.max_iterations == 12
    assert cfg.confirm_mode == "always"
    assert cfg.execution == "docker"
    assert cfg.projects_dir == "/tmp/projects"
    assert cfg.docker_image == "myorg/agent-server:custom"
    assert cfg.docker_platform == "linux/amd64"
    assert cfg.verify_tests == "never"
    assert cfg.max_verify_retries == 5
    assert cfg.reasoning_effort == "low"


def test_reasoning_effort_blank_treated_as_absent():
    cfg = load_config(_base_env(CERTO_LLM_REASONING_EFFORT="   "))
    assert cfg.reasoning_effort is None


@pytest.mark.parametrize("value", ["none", "None", "off", " OFF "])
def test_reasoning_effort_off_spellings_normalize_to_none_string(value):
    cfg = load_config(_base_env(CERTO_LLM_REASONING_EFFORT=value))
    assert cfg.reasoning_effort == "none"


def test_override_llm_reasoning_effort_off_normalizes_to_none_string():
    cfg = override_llm(load_config(_base_env()), reasoning_effort="off")
    assert cfg.reasoning_effort == "none"


def test_reasoning_effort_accepts_forward_compatible_value():
    # Deliberately not validated against a fixed choice list — see config.py's
    # comment on the field. A value the SDK/provider might add later must not
    # be rejected here.
    cfg = load_config(_base_env(CERTO_LLM_REASONING_EFFORT="some-future-value"))
    assert cfg.reasoning_effort == "some-future-value"


def test_invalid_verify_tests_raises():
    with pytest.raises(ConfigError, match="CERTO_VERIFY_TESTS"):
        load_config(_base_env(CERTO_VERIFY_TESTS="sometimes"))


@pytest.mark.parametrize("bad", ["0", "-1", "abc"])
def test_invalid_max_verify_retries_raises(bad):
    with pytest.raises(ConfigError, match="CERTO_MAX_VERIFY_RETRIES"):
        load_config(_base_env(CERTO_MAX_VERIFY_RETRIES=bad))


def test_max_task_seconds_defaults_when_unset():
    cfg = load_config(_base_env())
    assert cfg.max_task_seconds == DEFAULT_MAX_TASK_SECONDS


def test_max_task_seconds_reads_a_custom_value():
    cfg = load_config(_base_env(CERTO_MAX_TASK_SECONDS="60"))
    assert cfg.max_task_seconds == 60


@pytest.mark.parametrize("bad", ["0", "-1", "abc", "3.5"])
def test_invalid_max_task_seconds_raises(bad):
    with pytest.raises(ConfigError, match="CERTO_MAX_TASK_SECONDS"):
        load_config(_base_env(CERTO_MAX_TASK_SECONDS=bad))


def test_invalid_docker_platform_raises():
    with pytest.raises(ConfigError, match="CERTO_DOCKER_PLATFORM"):
        load_config(_base_env(CERTO_DOCKER_PLATFORM="linux/mips"))


def test_missing_model_raises():
    with pytest.raises(ConfigError, match="CERTO_LLM_MODEL is required"):
        load_config({"CERTO_LLM_API_KEY": "sk-test"})


def test_missing_model_error_says_how_to_set_it_without_a_dotenv():
    # A pip-installed user may have no .env at all; exporting is enough.
    with pytest.raises(ConfigError) as excinfo:
        load_config({"CERTO_LLM_API_KEY": "sk-test"})
    message = str(excinfo.value)
    assert "export CERTO_LLM_MODEL=" in message
    assert ".env" in message


def test_exported_llm_vars_are_enough_with_no_dotenv_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no .env here
    for name in ("CERTO_LLM_MODEL", "CERTO_LLM_API_KEY", "CERTO_LLM_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CERTO_LLM_MODEL", "ollama/qwen2.5-coder")
    monkeypatch.setenv("CERTO_LLM_BASE_URL", "http://localhost:11434")

    cfg = load_config()

    assert cfg.model == "ollama/qwen2.5-coder"
    assert cfg.base_url == "http://localhost:11434"
    assert cfg.api_key is None


def test_missing_key_without_base_url_raises():
    with pytest.raises(ConfigError, match="CERTO_LLM_API_KEY is required"):
        load_config({"CERTO_LLM_MODEL": "anthropic/claude-sonnet-4-5-20250929"})


def test_base_url_allows_missing_key():
    # Local models can be keyless: base_url present, api_key absent -> OK.
    cfg = load_config(
        {"CERTO_LLM_MODEL": "ollama/llama3", "CERTO_LLM_BASE_URL": "http://localhost:11434"}
    )
    assert cfg.api_key is None
    assert cfg.base_url == "http://localhost:11434"


def test_blank_values_treated_as_absent():
    cfg = load_config(_base_env(CERTO_WORKSPACE="   ", CERTO_CONFIRM_MODE=""))
    assert cfg.workspace == DEFAULT_WORKSPACE
    assert cfg.confirm_mode == DEFAULT_CONFIRM_MODE


def test_whitespace_is_trimmed():
    cfg = load_config(_base_env(CERTO_LLM_MODEL="  openai/gpt-4o  "))
    assert cfg.model == "openai/gpt-4o"


@pytest.mark.parametrize("bad", ["0", "-3", "abc", "3.5"])
def test_invalid_max_iterations_raises(bad):
    with pytest.raises(ConfigError, match="CERTO_MAX_ITERATIONS"):
        load_config(_base_env(CERTO_MAX_ITERATIONS=bad))


def test_invalid_confirm_mode_raises():
    with pytest.raises(ConfigError, match="CERTO_CONFIRM_MODE"):
        load_config(_base_env(CERTO_CONFIRM_MODE="sometimes"))


def test_invalid_execution_raises():
    with pytest.raises(ConfigError, match="CERTO_EXECUTION"):
        load_config(_base_env(CERTO_EXECUTION="kubernetes"))


def test_choices_are_case_insensitive():
    cfg = load_config(_base_env(CERTO_CONFIRM_MODE="ALWAYS", CERTO_EXECUTION="Docker"))
    assert cfg.confirm_mode == "always"
    assert cfg.execution == "docker"


def test_config_is_frozen():
    cfg = load_config(_base_env())
    with pytest.raises(Exception):
        cfg.model = "openai/gpt-4o"  # type: ignore[misc]


def test_override_llm_applies_only_given_fields():
    cfg = load_config(_base_env())

    overridden = override_llm(cfg, model="openai/gpt-4o")

    assert overridden.model == "openai/gpt-4o"
    assert overridden.api_key == cfg.api_key
    assert overridden.base_url == cfg.base_url


def test_override_llm_applies_all_fields():
    cfg = load_config(_base_env())

    overridden = override_llm(
        cfg,
        model="ollama/llama3",
        api_key=None,
        base_url="http://localhost:11434",
        reasoning_effort="low",
    )

    assert overridden.model == "ollama/llama3"
    assert overridden.base_url == "http://localhost:11434"
    assert overridden.reasoning_effort == "low"
    # api_key=None means "not overridden", not "cleared" -> unchanged.
    assert overridden.api_key == cfg.api_key


def test_override_llm_reasoning_effort_only():
    cfg = load_config(_base_env())

    overridden = override_llm(cfg, reasoning_effort="xhigh")

    assert overridden.reasoning_effort == "xhigh"
    assert overridden.model == cfg.model
    assert overridden.api_key == cfg.api_key
    assert overridden.base_url == cfg.base_url


def test_override_llm_blank_reasoning_effort_clears_it():
    # Unlike model (which raises on blank), a blank reasoning_effort override
    # clears it back to "unset" -> the SDK's own default applies. Matches
    # api_key/base_url's leniency, not model's strictness.
    cfg = load_config(_base_env(CERTO_LLM_REASONING_EFFORT="low"))

    overridden = override_llm(cfg, reasoning_effort="   ")

    assert overridden.reasoning_effort is None


def test_override_llm_no_args_returns_same_config():
    cfg = load_config(_base_env())

    assert override_llm(cfg) == cfg


def test_override_llm_blank_model_raises():
    cfg = load_config(_base_env())

    with pytest.raises(ConfigError, match="Model override must not be blank"):
        override_llm(cfg, model="   ")


def test_defer_llm_check_allows_load_then_override_fills_model():
    with defer_llm_check():
        cfg = load_config({})
    assert cfg.model == ""
    assert cfg.api_key is None
    assert cfg.base_url is None

    filled = ensure_llm_configured(
        override_llm(cfg, model="ollama/qwen3.8:27b", base_url="http://localhost:11434")
    )
    assert filled.model == "ollama/qwen3.8:27b"
    assert filled.base_url == "http://localhost:11434"


def test_ensure_llm_configured_rejects_cloud_model_with_no_key():
    with defer_llm_check():
        cfg = load_config({})
    with pytest.raises(ConfigError, match="CERTO_LLM_API_KEY is required"):
        ensure_llm_configured(override_llm(cfg, model="openai/gpt-5.6-luna"))


def test_override_llm_does_not_mutate_original():
    cfg = load_config(_base_env())

    override_llm(cfg, model="openai/gpt-4o")

    assert cfg.model == "anthropic/claude-sonnet-4-5-20250929"


# --- resolve_project_dir: path containment and symlink protection ----------


def test_resolve_project_dir_returns_a_path_inside_projects_dir(tmp_path):
    projects_dir = str(tmp_path / "projects")

    resolved = resolve_project_dir(projects_dir, "myapp")

    assert resolved == os.path.join(os.path.abspath(projects_dir), "myapp")


def test_resolve_project_dir_allows_a_safe_nested_name(tmp_path):
    projects_dir = str(tmp_path / "projects")

    resolved = resolve_project_dir(projects_dir, "team/myapp")

    assert os.path.normpath(resolved) == os.path.join(
        os.path.abspath(projects_dir), "team", "myapp"
    )


def test_resolve_project_dir_rejects_empty_or_dot_names(tmp_path):
    projects_dir = str(tmp_path / "projects")

    for bad in ("", ".", ".."):
        with pytest.raises(ConfigError, match="Invalid project name"):
            resolve_project_dir(projects_dir, bad)


def test_resolve_project_dir_rejects_an_absolute_project_name(tmp_path):
    # The original bug: os.path.join(a, b) silently discards `a` when `b` is
    # absolute, so an unguarded join let this redirect the entire workspace.
    projects_dir = str(tmp_path / "projects")

    with pytest.raises(ConfigError, match="must be relative, not absolute"):
        resolve_project_dir(projects_dir, "/etc/cron.d")


def test_resolve_project_dir_rejects_dotdot_traversal(tmp_path):
    projects_dir = str(tmp_path / "projects")

    for traversal in ("..", "../escaped", "myapp/../../escaped", "a/b/../../../escaped"):
        with pytest.raises(ConfigError):
            resolve_project_dir(projects_dir, traversal)


def test_resolve_project_dir_rejects_a_symlinked_escape(tmp_path, directory_link):
    # Even a project name with no ".." at all must be rejected if the
    # resulting path resolves, via an existing symlink, outside projects_dir.
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    directory_link(projects_dir / "myapp", outside)

    with pytest.raises(ConfigError, match="escapes CERTO_PROJECTS_DIR"):
        resolve_project_dir(str(projects_dir), "myapp")


def test_resolve_project_dir_allows_a_symlink_that_stays_inside(tmp_path, directory_link):
    # A symlink is not inherently a violation — only one that resolves
    # outside projects_dir is. This one points at a sibling directory that
    # is still under projects_dir.
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    real_target = projects_dir / "real-team-dir"
    real_target.mkdir()
    directory_link(projects_dir / "myapp", real_target)

    resolved = resolve_project_dir(str(projects_dir), "myapp")

    assert os.path.realpath(resolved) == os.path.realpath(str(real_target))


# --- Server-mode task registry persistence (task_store.py config) ----------


def test_task_store_defaults_to_memory_with_no_ttl():
    cfg = load_config(_base_env())

    assert cfg.task_store == DEFAULT_TASK_STORE == "memory"
    assert cfg.task_ttl_seconds == DEFAULT_TASK_TTL_SECONDS == 0


def test_task_store_accepts_each_backend():
    for backend in ("memory", "redis", "sqlite", "mysql", "postgres"):
        cfg = load_config(_base_env(CERTO_TASK_STORE=backend))
        assert cfg.task_store == backend


def test_task_store_is_case_insensitive():
    cfg = load_config(_base_env(CERTO_TASK_STORE="SQLITE"))
    assert cfg.task_store == "sqlite"


def test_invalid_task_store_raises():
    with pytest.raises(ConfigError, match="CERTO_TASK_STORE"):
        load_config(_base_env(CERTO_TASK_STORE="oracle"))


def test_task_ttl_seconds_zero_means_keep_forever():
    cfg = load_config(_base_env(CERTO_TASK_TTL_SECONDS="0"))
    assert cfg.task_ttl_seconds == 0


def test_task_ttl_seconds_accepts_a_positive_value():
    cfg = load_config(_base_env(CERTO_TASK_TTL_SECONDS="3600"))
    assert cfg.task_ttl_seconds == 3600


@pytest.mark.parametrize("bad", ["-1", "abc", "3.5"])
def test_invalid_task_ttl_seconds_raises(bad):
    with pytest.raises(ConfigError, match="CERTO_TASK_TTL_SECONDS"):
        load_config(_base_env(CERTO_TASK_TTL_SECONDS=bad))


def test_task_store_sqlite_path_defaults_and_overrides():
    cfg = load_config(_base_env())
    assert cfg.task_store_sqlite_path == DEFAULT_TASK_STORE_SQLITE_PATH

    cfg = load_config(_base_env(CERTO_TASK_STORE_SQLITE_PATH="/tmp/custom.db"))
    assert cfg.task_store_sqlite_path == "/tmp/custom.db"


def test_task_store_mysql_fields_default_and_override():
    cfg = load_config(_base_env())
    assert cfg.task_store_mysql_host == "localhost"
    assert cfg.task_store_mysql_port == DEFAULT_TASK_STORE_MYSQL_PORT
    assert cfg.task_store_mysql_user == "root"
    assert cfg.task_store_mysql_password is None
    assert cfg.task_store_mysql_database == "certo"

    cfg = load_config(
        _base_env(
            CERTO_TASK_STORE_MYSQL_HOST="db.internal",
            CERTO_TASK_STORE_MYSQL_PORT="3307",
            CERTO_TASK_STORE_MYSQL_USER="certo_user",
            CERTO_TASK_STORE_MYSQL_PASSWORD="secret",
            CERTO_TASK_STORE_MYSQL_DATABASE="certo_prod",
        )
    )
    assert cfg.task_store_mysql_host == "db.internal"
    assert cfg.task_store_mysql_port == 3307
    assert cfg.task_store_mysql_user == "certo_user"
    assert cfg.task_store_mysql_password == "secret"
    assert cfg.task_store_mysql_database == "certo_prod"


def test_invalid_task_store_mysql_port_raises():
    with pytest.raises(ConfigError, match="CERTO_TASK_STORE_MYSQL_PORT"):
        load_config(_base_env(CERTO_TASK_STORE_MYSQL_PORT="not-a-port"))


def test_task_store_postgres_fields_default_and_override():
    cfg = load_config(_base_env())
    assert cfg.task_store_postgres_host == "localhost"
    assert cfg.task_store_postgres_port == DEFAULT_TASK_STORE_POSTGRES_PORT
    assert cfg.task_store_postgres_user == "postgres"
    assert cfg.task_store_postgres_password is None
    assert cfg.task_store_postgres_database == "certo"

    cfg = load_config(
        _base_env(
            CERTO_TASK_STORE_POSTGRES_HOST="pg.internal",
            CERTO_TASK_STORE_POSTGRES_PORT="5433",
            CERTO_TASK_STORE_POSTGRES_USER="certo_user",
            CERTO_TASK_STORE_POSTGRES_PASSWORD="secret",
            CERTO_TASK_STORE_POSTGRES_DATABASE="certo_prod",
        )
    )
    assert cfg.task_store_postgres_host == "pg.internal"
    assert cfg.task_store_postgres_port == 5433
    assert cfg.task_store_postgres_user == "certo_user"
    assert cfg.task_store_postgres_password == "secret"
    assert cfg.task_store_postgres_database == "certo_prod"


def test_task_store_redis_fields_default_and_override():
    cfg = load_config(_base_env())
    assert cfg.task_store_redis_host == "localhost"
    assert cfg.task_store_redis_port == DEFAULT_TASK_STORE_REDIS_PORT
    assert cfg.task_store_redis_db == 0
    assert cfg.task_store_redis_password is None
    assert cfg.task_store_redis_use_tls is False

    cfg = load_config(
        _base_env(
            CERTO_TASK_STORE_REDIS_HOST="redis.internal",
            CERTO_TASK_STORE_REDIS_PORT="6380",
            CERTO_TASK_STORE_REDIS_DB="2",
            CERTO_TASK_STORE_REDIS_PASSWORD="secret",
            CERTO_TASK_STORE_REDIS_USE_TLS="true",
        )
    )
    assert cfg.task_store_redis_host == "redis.internal"
    assert cfg.task_store_redis_port == 6380
    assert cfg.task_store_redis_db == 2
    assert cfg.task_store_redis_password == "secret"
    assert cfg.task_store_redis_use_tls is True


@pytest.mark.parametrize("bad", ["-1", "abc"])
def test_invalid_task_store_redis_db_raises(bad):
    with pytest.raises(ConfigError, match="CERTO_TASK_STORE_REDIS_DB"):
        load_config(_base_env(CERTO_TASK_STORE_REDIS_DB=bad))


@pytest.mark.parametrize(
    "value,expected", [("true", True), ("1", True), ("yes", True), ("on", True)]
)
def test_task_store_redis_use_tls_accepts_true_spellings(value, expected):
    cfg = load_config(_base_env(CERTO_TASK_STORE_REDIS_USE_TLS=value))
    assert cfg.task_store_redis_use_tls is expected


@pytest.mark.parametrize(
    "value,expected", [("false", False), ("0", False), ("no", False), ("off", False)]
)
def test_task_store_redis_use_tls_accepts_false_spellings(value, expected):
    cfg = load_config(_base_env(CERTO_TASK_STORE_REDIS_USE_TLS=value))
    assert cfg.task_store_redis_use_tls is expected


def test_invalid_task_store_redis_use_tls_raises():
    with pytest.raises(ConfigError, match="CERTO_TASK_STORE_REDIS_USE_TLS"):
        load_config(_base_env(CERTO_TASK_STORE_REDIS_USE_TLS="maybe"))


# --- Interactive mode (CERTO_INTERACTIVE) ---------------------------------


def test_interactive_defaults_to_false():
    cfg = load_config(_base_env())
    assert cfg.interactive is False


@pytest.mark.parametrize(
    "value,expected", [("true", True), ("1", True), ("yes", True), ("on", True)]
)
def test_interactive_accepts_true_spellings(value, expected):
    cfg = load_config(_base_env(CERTO_INTERACTIVE=value))
    assert cfg.interactive is expected


@pytest.mark.parametrize(
    "value,expected", [("false", False), ("0", False), ("no", False), ("off", False)]
)
def test_interactive_accepts_false_spellings(value, expected):
    cfg = load_config(_base_env(CERTO_INTERACTIVE=value))
    assert cfg.interactive is expected


def test_invalid_interactive_raises():
    with pytest.raises(ConfigError, match="CERTO_INTERACTIVE"):
        load_config(_base_env(CERTO_INTERACTIVE="maybe"))


# --- Verbose output (CERTO_VERBOSE) ----------------------------------------------


def test_verbose_defaults_to_false_and_reads_yes():
    assert load_config(_base_env()).verbose is False
    assert load_config(_base_env(CERTO_VERBOSE="yes")).verbose is True


# --- Independent test sets (CERTO_INDEPENDENT_TESTS_SETS) ----------------


def test_independent_tests_sets_default_to_three_and_stay_between_1_and_5():
    assert load_config(_base_env()).independent_tests_sets == 3
    assert load_config(_base_env(CERTO_INDEPENDENT_TESTS_SETS="1")).independent_tests_sets == 1
    with pytest.raises(ConfigError, match="at most 5"):
        load_config(_base_env(CERTO_INDEPENDENT_TESTS_SETS="6"))
    with pytest.raises(ConfigError, match="positive"):
        load_config(_base_env(CERTO_INDEPENDENT_TESTS_SETS="0"))


# --- Deterministic auto model selection (CERTO_MODEL_SELECTION) ----------


def test_model_selection_defaults_to_manual():
    cfg = load_config(_base_env())
    assert cfg.model_selection == "manual"
    assert (cfg.models_file, cfg.models_list_file) == ("", "")  # "": look them up


def test_model_selection_accepts_auto():
    cfg = load_config(_base_env(CERTO_MODEL_SELECTION="auto"))
    assert cfg.model_selection == "auto"


def test_model_selection_is_case_insensitive():
    cfg = load_config(_base_env(CERTO_MODEL_SELECTION="AUTO"))
    assert cfg.model_selection == "auto"


def test_invalid_model_selection_raises():
    with pytest.raises(ConfigError, match="CERTO_MODEL_SELECTION"):
        load_config(_base_env(CERTO_MODEL_SELECTION="sometimes"))


def test_models_file_defaults_and_override():
    cfg = load_config(_base_env(CERTO_MODELS_FILE="./custom-models.yaml"))
    assert cfg.models_file == "./custom-models.yaml"


def test_task_profiles_and_escalation_files_default_to_lookup_and_can_be_set():
    assert load_config(_base_env()).task_profiles_file == ""
    assert load_config(_base_env()).escalation_file == ""
    cfg = load_config(
        _base_env(CERTO_TASK_PROFILES_FILE="./p.yaml", CERTO_ESCALATION_FILE="./e.yaml")
    )
    assert (cfg.task_profiles_file, cfg.escalation_file) == ("./p.yaml", "./e.yaml")


# --- Per-run artifacts directory (CERTO_ARTIFACTS_DIR) --------------------


def test_artifacts_dir_defaults_to_blank():
    cfg = load_config(_base_env())
    assert cfg.artifacts_dir == ""


def test_artifacts_dir_override():
    cfg = load_config(_base_env(CERTO_ARTIFACTS_DIR="./artifacts"))
    assert cfg.artifacts_dir == "./artifacts"


def test_artifacts_dir_blank_value_stays_blank():
    cfg = load_config(_base_env(CERTO_ARTIFACTS_DIR="   "))
    assert cfg.artifacts_dir == ""


# --- HARNESS_* -> CERTO_* deprecation fallback -------------------------------


@pytest.fixture
def fresh_legacy_warnings(monkeypatch):
    """The once-per-process warning memory is module state; isolate it."""
    import certo.config as config_mod

    monkeypatch.setattr(config_mod, "_warned_legacy_vars", set())


def _legacy_warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if "deprecated" in r.getMessage()]


def test_new_env_name_only(fresh_legacy_warnings, caplog):
    cfg = load_config(_base_env(CERTO_MAX_ITERATIONS="7", CERTO_EXECUTION="docker"))
    assert cfg.max_iterations == 7
    assert cfg.execution == "docker"
    assert _legacy_warnings(caplog) == []


def test_legacy_env_name_only_is_used_and_warns_naming_the_new_var(fresh_legacy_warnings, caplog):
    cfg = load_config(_base_env(HARNESS_MAX_ITERATIONS="7", HARNESS_PROJECTS_DIR="./old-projects"))
    assert cfg.max_iterations == 7
    assert cfg.projects_dir == "./old-projects"
    assert sorted(_legacy_warnings(caplog)) == [
        "HARNESS_MAX_ITERATIONS is deprecated; rename it to CERTO_MAX_ITERATIONS.",
        "HARNESS_PROJECTS_DIR is deprecated; rename it to CERTO_PROJECTS_DIR.",
    ]


def test_an_old_skill_folder_setting_still_set_is_named_once(monkeypatch, caplog):
    import certo.config as config_mod

    monkeypatch.setattr(config_mod, "_warned_removed_vars", set())
    env = _base_env(CERTO_SKILLS_DIR="./skills", CERTO_THIRD_PARTY_SKILLS_LOCK="")

    load_config(env)
    load_config(env)

    warnings = [r.getMessage() for r in caplog.records if "no longer read" in r.getMessage()]
    assert warnings == [
        "CERTO_SKILLS_DIR is no longer read: Certo no longer uses the old skill folders. Add "
        "each skill again with: certo skills add PATH --global (or --project NAME)."
    ]


def test_legacy_env_warning_is_logged_once_per_variable(fresh_legacy_warnings, caplog):
    load_config(_base_env(HARNESS_MAX_ITERATIONS="7"))
    load_config(_base_env(HARNESS_MAX_ITERATIONS="7"))
    assert len(_legacy_warnings(caplog)) == 1


def test_both_env_names_set_new_wins_silently(fresh_legacy_warnings, caplog):
    cfg = load_config(_base_env(CERTO_MAX_ITERATIONS="7", HARNESS_MAX_ITERATIONS="99"))
    assert cfg.max_iterations == 7
    assert _legacy_warnings(caplog) == []


def test_blank_new_env_name_falls_back_to_legacy(fresh_legacy_warnings):
    cfg = load_config(_base_env(CERTO_EXECUTION="", HARNESS_EXECUTION="docker"))
    assert cfg.execution == "docker"


def test_invalid_legacy_value_error_names_the_legacy_var(fresh_legacy_warnings):
    with pytest.raises(ConfigError, match="HARNESS_MAX_ITERATIONS"):
        load_config(_base_env(HARNESS_MAX_ITERATIONS="abc"))


@pytest.mark.parametrize(
    "suffix, value, field, expected",
    [
        ("CONFIRM_MODE", "always", "confirm_mode", "always"),
        ("TASK_TTL_SECONDS", "0", "task_ttl_seconds", 0),
        ("TASK_STORE_REDIS_USE_TLS", "true", "task_store_redis_use_tls", True),
        ("ARTIFACTS_DIR", "./arts", "artifacts_dir", "./arts"),
    ],
)
def test_legacy_fallback_covers_every_parser_kind(
    fresh_legacy_warnings, suffix, value, field, expected
):
    assert getattr(load_config(_base_env(**{f"HARNESS_{suffix}": value})), field) == expected
    assert getattr(load_config(_base_env(**{f"CERTO_{suffix}": value})), field) == expected


# --- CERTO_LLM_* replaced the bare LLM_* names --------------------------------


def test_bare_llm_variables_are_never_read():
    # Another tool's LLM_* settings must not leak into Certo.
    cfg = load_config(
        _base_env(
            LLM_MODEL="openai/other-app-model",
            LLM_API_KEY="sk-other-app",
            LLM_BASE_URL="http://other-app:1234",
            LLM_REASONING_EFFORT="low",
        )
    )

    assert cfg.model == _base_env()["CERTO_LLM_MODEL"]
    assert cfg.api_key == _base_env()["CERTO_LLM_API_KEY"]
    assert cfg.base_url is None
    assert cfg.reasoning_effort is None


def test_only_old_llm_model_set_explains_the_rename():
    with pytest.raises(ConfigError) as exc:
        load_config({"LLM_MODEL": "ollama/qwen3-coder:30b", "LLM_BASE_URL": "http://h:11434"})

    message = str(exc.value)
    assert "CERTO_LLM_MODEL is required" in message
    assert "Rename LLM_MODEL -> CERTO_LLM_MODEL" in message


def test_only_old_llm_api_key_set_explains_the_rename_without_leaking_it():
    with pytest.raises(ConfigError) as exc:
        load_config({"CERTO_LLM_MODEL": "openai/gpt-4o", "LLM_API_KEY": "sk-secret-value"})

    message = str(exc.value)
    assert "Rename LLM_API_KEY -> CERTO_LLM_API_KEY" in message
    assert "sk-secret-value" not in message


def test_required_error_has_no_rename_hint_without_old_variables():
    with pytest.raises(ConfigError) as exc:
        load_config({})

    assert "no longer reads" not in str(exc.value)


# --- settings sources: environment, ./.env, the user settings file -----------

_LLM_VARS = ("CERTO_LLM_MODEL", "CERTO_LLM_API_KEY", "CERTO_LLM_BASE_URL")


@pytest.fixture
def sources(tmp_path, monkeypatch):
    """A clean environment, an empty working folder, and a temporary
    XDG_CONFIG_HOME. Returns (folder .env path, user file path)."""
    for name in _LLM_VARS:
        monkeypatch.delenv(name, raising=False)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    user = tmp_path / "xdg" / "certo" / ".env"
    user.parent.mkdir(parents=True)
    return work / ".env", user


def test_user_settings_path_follows_xdg_config_home(tmp_path):
    assert user_settings_path({"XDG_CONFIG_HOME": str(tmp_path)}) == str(
        tmp_path / "certo" / ".env"
    )


@pytest.mark.parametrize("xdg", [None, "", "relative/dir"])
def test_user_settings_path_falls_back_to_dot_config(xdg, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    env = {} if xdg is None else {"XDG_CONFIG_HOME": xdg}
    assert user_settings_path(env) == str(tmp_path / ".config" / "certo" / ".env")


def test_environment_only(sources, monkeypatch):
    monkeypatch.setenv("CERTO_LLM_MODEL", "openai/from-env")
    monkeypatch.setenv("CERTO_LLM_API_KEY", "k-env")

    cfg = load_config()

    assert (cfg.model, cfg.api_key) == ("openai/from-env", "k-env")


def test_folder_env_only(sources):
    folder, _user = sources
    folder.write_text("CERTO_LLM_MODEL=openai/from-folder\nCERTO_LLM_API_KEY=k-folder\n")

    cfg = load_config()

    assert (cfg.model, cfg.api_key) == ("openai/from-folder", "k-folder")


def test_user_file_only(sources):
    _folder, user = sources
    user.write_text("CERTO_LLM_MODEL=openai/from-user\nCERTO_LLM_API_KEY=k-user\n")

    cfg = load_config()

    assert (cfg.model, cfg.api_key) == ("openai/from-user", "k-user")


def test_folder_overrides_the_user_file_one_setting_at_a_time(sources):
    folder, user = sources
    user.write_text("CERTO_LLM_MODEL=openai/from-user\nCERTO_LLM_API_KEY=k-user\n")
    folder.write_text("CERTO_LLM_MODEL=anthropic/from-folder\n")

    cfg = load_config()

    assert cfg.model == "anthropic/from-folder"
    assert cfg.api_key == "k-user"


def test_environment_overrides_both_files(sources, monkeypatch):
    folder, user = sources
    user.write_text("CERTO_LLM_MODEL=openai/from-user\nCERTO_LLM_API_KEY=k-user\n")
    folder.write_text("CERTO_LLM_MODEL=openai/from-folder\nCERTO_LLM_API_KEY=k-folder\n")
    monkeypatch.setenv("CERTO_LLM_MODEL", "openai/from-env")

    cfg = load_config()

    assert cfg.model == "openai/from-env"
    assert cfg.api_key == "k-folder"


def test_a_blank_line_in_the_folder_env_does_not_hide_the_user_files_value(sources):
    # `certo init` writes `CERTO_LLM_API_KEY=` for a key still to fill in.
    folder, user = sources
    user.write_text("CERTO_LLM_MODEL=openai/from-user\nCERTO_LLM_API_KEY=k-user\n")
    folder.write_text("CERTO_LLM_MODEL=openai/from-folder\nCERTO_LLM_API_KEY=\n")

    cfg = load_config()

    assert (cfg.model, cfg.api_key) == ("openai/from-folder", "k-user")


def test_user_file_references_resolve_from_the_environment(sources, monkeypatch):
    _folder, user = sources
    user.write_text("CERTO_LLM_MODEL=anthropic/m\nCERTO_LLM_API_KEY=${ANTHROPIC_API_KEY}\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k-exported")

    assert load_config().api_key == "k-exported"


def test_load_settings_files_reports_each_source(sources, monkeypatch):
    folder, user = sources
    user.write_text(
        "CERTO_LLM_MODEL=openai/u\nCERTO_LLM_API_KEY=k-user\nCERTO_LLM_BASE_URL=http://u\n"
    )
    folder.write_text("CERTO_LLM_MODEL=openai/f\n")
    monkeypatch.setenv("CERTO_LLM_BASE_URL", "http://env")

    found = load_settings_files()

    assert found["CERTO_LLM_MODEL"] == SettingSource("folder", str(folder))
    assert found["CERTO_LLM_API_KEY"] == SettingSource("user", str(user))
    assert found["CERTO_LLM_BASE_URL"] == SettingSource("environment")
    assert os.environ["CERTO_LLM_BASE_URL"] == "http://env"


def test_missing_model_error_lists_the_three_places(sources):
    folder, user = sources

    with pytest.raises(ConfigError) as excinfo:
        load_config()

    message = str(excinfo.value)
    assert "export CERTO_LLM_MODEL=" in message
    assert str(folder) in message
    assert str(user) in message
    assert "certo init" in message


# --- CERTO_LLM_TIMEOUT_SECONDS ---------------------------------------------------


def test_llm_timeout_defaults_to_300_seconds():
    assert load_config(_base_env()).llm_timeout_seconds == 300


@pytest.mark.parametrize(("value", "expected"), [("900", 900), ("0", 0), (" ", 300)])
def test_llm_timeout_is_read_from_the_environment(value, expected):
    cfg = load_config(_base_env(CERTO_LLM_TIMEOUT_SECONDS=value))
    assert cfg.llm_timeout_seconds == expected


@pytest.mark.parametrize("value", ["-1", "ten", "1.5"])
def test_llm_timeout_rejects_bad_values(value):
    with pytest.raises(ConfigError, match="CERTO_LLM_TIMEOUT_SECONDS"):
        load_config(_base_env(CERTO_LLM_TIMEOUT_SECONDS=value))


def test_override_llm_timeout_only():
    cfg = override_llm(load_config(_base_env()), timeout_seconds=1200)
    assert cfg.llm_timeout_seconds == 1200
    with pytest.raises(ConfigError):
        override_llm(cfg, timeout_seconds=-5)


def test_env_example_puts_comments_above_settings_not_beside_them():
    """python-dotenv keeps a `# comment` after an empty value as the value
    itself, so every comment in .env.example goes on its own line."""
    import re
    from pathlib import Path

    from dotenv import dotenv_values

    path = Path(__file__).resolve().parent.parent / ".env.example"
    beside = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if re.match(r"^[A-Z][A-Z0-9_]*=.*#", line)
    ]
    assert beside == []
    assert not [k for k, v in dotenv_values(path).items() if v and "#" in v]


def test_escalate_is_a_model_selection_mode_with_an_optional_ladder():
    cfg = load_config(
        _base_env(CERTO_MODEL_SELECTION="escalate", CERTO_ESCALATION_LADDER="local-only")
    )
    assert (cfg.model_selection, cfg.escalation_ladder) == ("escalate", "local-only")
    assert load_config(_base_env()).escalation_ladder == ""


def test_escalation_handoff_is_continue_unless_set_to_restart():
    assert load_config(_base_env()).escalation_handoff == "continue"
    assert load_config(_base_env(CERTO_ESCALATION_HANDOFF="Restart")).escalation_handoff == (
        "restart"
    )
    with pytest.raises(ConfigError, match="CERTO_ESCALATION_HANDOFF must be one of"):
        load_config(_base_env(CERTO_ESCALATION_HANDOFF="rewind"))


@pytest.mark.parametrize(("value", "expected"), [("", None), ("2.5", 2.5), ("0", 0.0)])
def test_max_task_cost(value, expected):
    assert load_config(_base_env(CERTO_MAX_TASK_COST=value)).max_task_cost == expected


@pytest.mark.parametrize("value", ["-1", "lots", "nan"])
def test_max_task_cost_rejects_bad_values(value):
    with pytest.raises(ConfigError, match="CERTO_MAX_TASK_COST"):
        load_config(_base_env(CERTO_MAX_TASK_COST=value))


def test_strict_independent_tests_are_off_by_default_and_turn_the_tests_on():
    cfg = load_config(_base_env())
    assert cfg.independent_tests_strict is False and cfg.independent_tests is False
    cfg = load_config(_base_env(CERTO_INDEPENDENT_TESTS_STRICT="yes"))
    assert cfg.independent_tests_strict is True and cfg.independent_tests is True


def test_tool_call_reminders_default_to_3_and_0_turns_them_off():
    assert load_config(_base_env()).tool_call_reminders == 3
    assert load_config(_base_env(CERTO_TOOL_CALL_REMINDERS="0")).tool_call_reminders == 0
    with pytest.raises(ConfigError, match="TOOL_CALL_REMINDERS"):
        load_config(_base_env(CERTO_TOOL_CALL_REMINDERS="-1"))


def test_the_independent_tests_model_is_read():
    assert load_config(_base_env()).independent_tests_model == ""
    cfg = load_config(_base_env(CERTO_INDEPENDENT_TESTS_MODEL="claude-haiku-5-5"))
    assert cfg.independent_tests_model == "claude-haiku-5-5"


def test_the_planner_reasoning_effort_defaults_to_xhigh():
    assert load_config(_base_env()).planner_reasoning_effort == "xhigh"
    cfg = load_config(_base_env(CERTO_PLANNER_REASONING_EFFORT="xhigh"))
    assert cfg.planner_reasoning_effort == "xhigh"
    cfg = load_config(_base_env(CERTO_PLANNER_REASONING_EFFORT="default"))
    assert cfg.planner_reasoning_effort == "default"
