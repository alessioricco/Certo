"""CLI tests. No LLM/network: load_config and run_task are monkeypatched so
these exercise only argument parsing and control flow.
"""

from __future__ import annotations

import importlib.metadata
import tomllib
import urllib.error
from dataclasses import replace
from pathlib import Path

import pytest

from certo import cli
from certo.config import Config, ConfigError
from certo.run_summary import ModelUsage, RunSummary
from certo.runner import CompletionContract, TaskOutcome, TaskResult


@pytest.fixture(autouse=True)
def recorded_runs(monkeypatch):
    """Most tests here use workspace ".", the checkout itself: catch the
    .certo/RUNS.md entries instead of writing them there."""
    entries = []
    monkeypatch.setattr(cli, "append_run", lambda workspace, entry: entries.append(entry))
    return entries


def _fake_result(messages=(), verification_state="verified", limitations=()):
    """Build the same `TaskResult` shape `run_task` now returns, for tests
    that monkeypatch `run_task` — `messages[-1]`/`if messages:` behave
    exactly like a plain list, plus `.outcome` for the new verification
    state the CLI now reports."""
    contract = CompletionContract(
        goal="", acceptance_criteria=[], verification_checks=[], limitations=list(limitations)
    )
    outcome = TaskOutcome(verification_state=verification_state, completion_contract=contract)
    return TaskResult(list(messages), outcome)


def _cfg(**overrides) -> Config:
    base = {
        "model": "openai/gpt-4o",
        "api_key": "key",
        "base_url": None,
        "workspace": ".",
        "max_iterations": 10,
        "confirm_mode": "never",
        "execution": "local",
    }
    base.update(overrides)
    return Config(**base)


class _FakeContent:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeMessage:
    def __init__(self, text: str) -> None:
        self.content = [_FakeContent(text)]


class _FakeUrlResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self) -> bytes:
        return self._body


def test_resolve_task_source_returns_literal_text_unchanged():
    assert cli.resolve_task_source("Refactor utils.py") == "Refactor utils.py"


def test_resolve_task_source_reads_existing_file(tmp_path):
    task_file = tmp_path / "task.md"
    task_file.write_text("Do the thing described here.\n")

    assert cli.resolve_task_source(str(task_file)) == "Do the thing described here."


def test_resolve_task_source_fetches_url(monkeypatch):
    monkeypatch.setattr(
        cli.urllib.request,
        "urlopen",
        lambda url, timeout: _FakeUrlResponse(b"Task fetched from the web."),
    )

    assert cli.resolve_task_source("https://example.com/task.md") == "Task fetched from the web."


def test_resolve_task_source_url_fetch_error_raises_value_error(monkeypatch):
    def _raise(url, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(cli.urllib.request, "urlopen", _raise)

    with pytest.raises(ValueError, match="Failed to fetch task from URL"):
        cli.resolve_task_source("https://example.com/task.md")


def test_resolve_task_source_empty_file_raises_value_error(tmp_path):
    task_file = tmp_path / "empty.md"
    task_file.write_text("   \n")

    with pytest.raises(ValueError, match="is empty"):
        cli.resolve_task_source(str(task_file))


def test_main_reads_task_from_file(monkeypatch, tmp_path, capsys):
    task_file = tmp_path / "task.md"
    task_file.write_text("Create HELLO.txt with the line: hi.")
    calls = {}

    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        calls["task"] = task
        return _fake_result([_FakeMessage("done")])

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    exit_code = cli.main([str(task_file)])

    assert exit_code == 0
    assert calls["task"] == "Create HELLO.txt with the line: hi."


def test_main_reports_task_resolution_error(monkeypatch, capsys):
    def _fail_if_called(*args, **kwargs):
        raise AssertionError("run_task should not be called")

    def _raise(url, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(cli.urllib.request, "urlopen", _raise)
    monkeypatch.setattr(cli, "run_task", _fail_if_called)

    exit_code = cli.main(["https://example.com/task.md"])

    assert exit_code == 1
    assert "Failed to fetch task from URL" in capsys.readouterr().err


def test_config_error_is_reported_and_exits_nonzero(monkeypatch, capsys):
    def _raise() -> Config:
        raise ConfigError("CERTO_LLM_MODEL is required")

    monkeypatch.setattr(cli, "load_config", _raise)

    exit_code = cli.main(["do something"])

    assert exit_code == 1
    assert "CERTO_LLM_MODEL is required" in capsys.readouterr().err


def test_docker_execution_is_passed_through_to_run_task(monkeypatch):
    calls = {}

    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        calls["cfg"] = cfg
        return _fake_result()

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    exit_code = cli.main(["do something", "--execution", "docker"])

    assert exit_code == 0
    assert calls["cfg"].execution == "docker"


def test_run_task_error_is_reported_and_exits_nonzero(monkeypatch, capsys):
    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        raise RuntimeError("CERTO_EXECUTION=docker requires the 'sandbox' extra")

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    exit_code = cli.main(["do something", "--execution", "docker"])

    assert exit_code == 1
    assert "sandbox" in capsys.readouterr().err.lower()


def test_project_flag_creates_subfolder_and_overrides_workspace(monkeypatch, tmp_path):
    calls = {}

    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        calls["cfg"] = cfg
        calls["project"] = project
        return _fake_result()

    monkeypatch.setattr(cli, "load_config", lambda: _cfg(projects_dir=str(tmp_path)))
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    exit_code = cli.main(["do something", "--project", "myapp"])

    expected = str(tmp_path / "myapp")
    assert exit_code == 0
    assert calls["cfg"].workspace == expected
    assert calls["project"] == "myapp"
    assert (tmp_path / "myapp").is_dir()
    assert (tmp_path / ".certo-created-projects").read_text() == "myapp\n"


@pytest.mark.parametrize(
    ("options", "error"),
    [
        (["--auto-model"], "No models_list.yaml found"),
        (["--escalate"], "No models_list.yaml found"),
        (["--acceptance-checks", "not json"], "--acceptance-checks must be valid JSON"),
    ],
)
@pytest.mark.parametrize("existing_registry", [False, True])
def test_project_configuration_error_creates_no_folder_or_registry_entry(
    monkeypatch, tmp_path, capsys, options, error, existing_registry
):
    projects_dir = tmp_path / "projects"
    registry = projects_dir / ".certo-created-projects"
    if existing_registry:
        projects_dir.mkdir()
        registry.write_text("earlier\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "load_config", lambda: _cfg(projects_dir=str(projects_dir)))
    monkeypatch.setattr(cli, "run_task", _fail_if_called)

    assert cli.main(["hi", "--project", "leap", *options]) == 1

    captured = capsys.readouterr()
    assert f"Configuration error: {error}" in captured.err
    assert captured.out == ""
    assert not (projects_dir / "leap").exists()
    if existing_registry:
        assert registry.read_text() == "earlier\n"
    else:
        assert not projects_dir.exists()


@pytest.mark.parametrize("mode", ["--auto-model", "--escalate"])
@pytest.mark.parametrize("with_file", [False, True])
def test_project_configuration_error_preserves_existing_folder(
    monkeypatch, tmp_path, capsys, mode, with_file
):
    project_dir = tmp_path / "leap"
    project_dir.mkdir()
    if with_file:
        (project_dir / "notes.txt").write_text("keep me\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "load_config", lambda: _cfg(projects_dir=str(tmp_path)))
    monkeypatch.setattr(cli, "run_task", _fail_if_called)

    assert cli.main(["hi", "--project", "leap", mode]) == 1

    assert "Configuration error: No models_list.yaml found" in capsys.readouterr().err
    assert project_dir.is_dir()
    assert not (tmp_path / ".certo-created-projects").exists()
    if with_file:
        assert (project_dir / "notes.txt").read_text() == "keep me\n"
    else:
        assert list(project_dir.iterdir()) == []


def test_a_run_starts_with_the_banner(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "load_config", lambda: _cfg(projects_dir=str(tmp_path)))
    monkeypatch.setattr(cli, "run_task", lambda *a, **k: _fake_result())

    assert cli.main(["do something", "--project", "myapp"]) == 0

    out = capsys.readouterr().out
    assert out.startswith(f"── Certo {cli.__version__} ")
    assert f"Folder   {tmp_path / 'myapp'} (project myapp)" in out


def test_a_refused_run_prints_no_banner(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "load_config", lambda: _cfg(projects_dir=str(tmp_path)))

    assert cli.main(["do something", "--project", "../escaped"]) == 1

    assert "Certo" not in capsys.readouterr().out


def test_project_flag_rejects_a_path_escape_attempt(monkeypatch, tmp_path, capsys):
    def _fail_if_called(*args, **kwargs):
        raise AssertionError("run_task should not be called")

    monkeypatch.setattr(cli, "load_config", lambda: _cfg(projects_dir=str(tmp_path)))
    monkeypatch.setattr(cli, "run_task", _fail_if_called)

    exit_code = cli.main(["do something", "--project", "../escaped"])

    assert exit_code == 1
    assert "Configuration error" in capsys.readouterr().err
    assert not (tmp_path.parent / "escaped").exists()


def test_local_execution_runs_task_and_prints_the_verdict_not_the_message_again(
    monkeypatch, capsys
):
    calls = {}

    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        calls["task"] = task
        calls["cfg"] = cfg
        return _fake_result([_FakeMessage("all done")])

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    exit_code = cli.main(["do something"])

    assert exit_code == 0
    assert calls["task"] == "do something"
    assert calls["cfg"].execution == "local"
    out = capsys.readouterr().out
    # The SDK's visualizer already printed the agent's last message.
    assert "all done" not in out
    assert "Verification: verified" in out


def test_agents_md_without_project_is_rejected(monkeypatch, capsys):
    def _fail_if_called(*args, **kwargs):
        raise AssertionError("run_task should not be called")

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fail_if_called)

    exit_code = cli.main(["do something", "--agents-md", "some content"])

    assert exit_code == 1
    assert "--agents-md requires --project" in capsys.readouterr().err


def test_agents_md_with_project_writes_file(monkeypatch, tmp_path):
    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        return _fake_result()

    monkeypatch.setattr(cli, "load_config", lambda: _cfg(projects_dir=str(tmp_path)))
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    exit_code = cli.main(
        ["do something", "--project", "myapp", "--agents-md", "This project uses FastAPI."]
    )

    assert exit_code == 0
    assert (tmp_path / "myapp" / "AGENTS.md").read_text() == "This project uses FastAPI."


def test_model_flag_overrides_llm_model_without_touching_env(monkeypatch):
    calls = {}

    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        calls["cfg"] = cfg
        return _fake_result()

    monkeypatch.setattr(
        cli, "load_config", lambda: _cfg(model="anthropic/claude-sonnet-4-5-20250929")
    )
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    exit_code = cli.main(["do something", "--model", "openai/gpt-4o"])

    assert exit_code == 0
    assert calls["cfg"].model == "openai/gpt-4o"


def test_api_key_and_base_url_flags_override_config(monkeypatch):
    calls = {}

    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        calls["cfg"] = cfg
        return _fake_result()

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    exit_code = cli.main(
        [
            "do something",
            "--api-key",
            "sk-other",
            "--base-url",
            "http://localhost:11434",
        ]
    )

    assert exit_code == 0
    assert calls["cfg"].api_key == "sk-other"
    assert calls["cfg"].base_url == "http://localhost:11434"


def test_no_llm_override_flags_leaves_config_untouched(monkeypatch):
    calls = {}

    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        calls["cfg"] = cfg
        return _fake_result()

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    exit_code = cli.main(["do something"])

    assert exit_code == 0
    assert calls["cfg"].model == "openai/gpt-4o"
    assert calls["cfg"].api_key == "key"


def test_reasoning_effort_flag_overrides_config(monkeypatch):
    calls = {}

    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        calls["cfg"] = cfg
        return _fake_result()

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    exit_code = cli.main(["do something", "--reasoning-effort", "low"])

    assert exit_code == 0
    assert calls["cfg"].reasoning_effort == "low"
    # Untouched fields keep their configured values.
    assert calls["cfg"].model == "openai/gpt-4o"


def test_blank_model_override_reports_config_error(monkeypatch, capsys):
    def _fail_if_called(*args, **kwargs):
        raise AssertionError("run_task should not be called")

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fail_if_called)

    exit_code = cli.main(["do something", "--model", "   "])

    assert exit_code == 1
    assert "Model override must not be blank" in capsys.readouterr().err


def _clear_llm_settings(monkeypatch, tmp_path):
    """No CERTO_LLM_* in the environment, no folder .env, no user settings."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    for name in (
        "CERTO_LLM_MODEL",
        "CERTO_LLM_API_KEY",
        "CERTO_LLM_BASE_URL",
        "CERTO_LLM_REASONING_EFFORT",
        "LLM_MODEL",
        "LLM_API_KEY",
        "LLM_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_model_and_api_key_flags_work_with_no_configured_model(monkeypatch, tmp_path):
    """Issue #11: --model alone must satisfy CERTO_LLM_MODEL before checks run."""
    _clear_llm_settings(monkeypatch, tmp_path)
    calls = {}

    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        calls["cfg"] = cfg
        return _fake_result()

    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    exit_code = cli.main(["hi", "--model", "openai/gpt-5.6-luna", "--api-key", "sk-test"])

    assert exit_code == 0
    assert calls["cfg"].model == "openai/gpt-5.6-luna"
    assert calls["cfg"].api_key == "sk-test"


def test_model_and_base_url_flags_work_with_no_api_key(monkeypatch, tmp_path):
    """Issue #11: a local model needs no key when --base-url is set."""
    _clear_llm_settings(monkeypatch, tmp_path)
    calls = {}

    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        calls["cfg"] = cfg
        return _fake_result()

    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    exit_code = cli.main(
        [
            "hi",
            "--model",
            "ollama/qwen3.8:27b",
            "--base-url",
            "http://localhost:11434",
        ]
    )

    assert exit_code == 0
    assert calls["cfg"].model == "ollama/qwen3.8:27b"
    assert calls["cfg"].base_url == "http://localhost:11434"
    assert calls["cfg"].api_key is None


def test_no_model_and_no_flag_keeps_required_error(monkeypatch, tmp_path, capsys):
    """Issue #11: with neither setting nor flag, the error stays the same."""
    _clear_llm_settings(monkeypatch, tmp_path)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("run_task should not be called")

    monkeypatch.setattr(cli, "run_task", _fail_if_called)

    exit_code = cli.main(["hi"])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "CERTO_LLM_MODEL is required" in err
    assert "three places" in err


def test_model_flag_without_key_or_base_url_still_errors(monkeypatch, tmp_path, capsys):
    """Issue #11: checks apply to final values; a cloud model needs a key."""
    _clear_llm_settings(monkeypatch, tmp_path)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("run_task should not be called")

    monkeypatch.setattr(cli, "run_task", _fail_if_called)

    exit_code = cli.main(["hi", "--model", "openai/gpt-5.6-luna"])

    assert exit_code == 1
    assert "CERTO_LLM_API_KEY is required" in capsys.readouterr().err


def test_prints_verification_state_and_exits_zero_when_verified(monkeypatch, capsys):
    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        return _fake_result([_FakeMessage("all done")], verification_state="verified")

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    exit_code = cli.main(["do something"])

    assert exit_code == 0
    assert "Verification: verified" in capsys.readouterr().out


def test_exits_nonzero_when_verification_retries_are_exhausted(monkeypatch, capsys):
    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        return _fake_result(
            [_FakeMessage("I gave up")],
            verification_state="retry_exhausted",
            limitations=["pytest: 2 failed"],
        )

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    exit_code = cli.main(["do something"])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Verification: retry_exhausted" in out
    assert "pytest: 2 failed" in out


def test_exits_nonzero_when_verification_keeps_timing_out(monkeypatch, capsys):
    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        return _fake_result(
            [_FakeMessage("still going")],
            verification_state="timed_out",
            limitations=["cargo test: exceeded its 300s timeout and was killed"],
        )

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    exit_code = cli.main(["do something"])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Verification: timed_out" in out


def test_exits_nonzero_when_a_fix_attempt_made_no_progress(monkeypatch, capsys):
    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        return _fake_result([_FakeMessage("tried a fix")], verification_state="no_progress")

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    exit_code = cli.main(["do something"])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Verification: no_progress" in out


def test_exits_nonzero_when_task_tracker_left_incomplete(monkeypatch, capsys):
    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        return _fake_result(
            [_FakeMessage("finished")],
            verification_state="incomplete",
            limitations=["The agent's own task_tracker list still shows unfinished item(s)"],
        )

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    exit_code = cli.main(["do something"])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Verification: incomplete" in out


def test_exits_nonzero_when_agent_got_stuck(monkeypatch, capsys):
    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        return _fake_result([], verification_state="stuck")

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    exit_code = cli.main(["do something"])

    assert exit_code == 1
    assert "Verification: stuck" in capsys.readouterr().out


def test_exits_nonzero_when_task_budget_is_exhausted(monkeypatch, capsys):
    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        return _fake_result(
            [_FakeMessage("ran out of time")],
            verification_state="budget_exhausted",
            limitations=[
                (
                    "The task's shared wall-clock budget (CERTO_MAX_TASK_SECONDS=1800) "
                    "ran out before the task reached a normal finish, so its own "
                    "completion claim, if any, was not verified."
                )
            ],
        )

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    exit_code = cli.main(["do something"])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Verification: budget_exhausted" in out
    assert "CERTO_MAX_TASK_SECONDS" in out


def test_inconclusive_verification_still_exits_zero_but_is_visible(monkeypatch, capsys):
    # Inconclusive isn't an error (nothing was proven broken), but it must
    # not look like a silent, confirmed success either.
    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        return _fake_result(
            [_FakeMessage("done, probably")],
            verification_state="inconclusive",
            limitations=["No automated check could be run for this project."],
        )

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    exit_code = cli.main(["do something"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Verification: inconclusive" in out
    assert "No automated check could be run" in out


# --- --require-verification: opt-in strict treatment of "inconclusive" -----


def test_require_verification_flag_defaults_to_off(monkeypatch):
    calls = {}

    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        calls["called"] = True
        return _fake_result(verification_state="inconclusive")

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    exit_code = cli.main(["do something"])

    assert calls["called"] is True
    assert exit_code == 0


def test_require_verification_flag_makes_unknown_project_type_a_failure(monkeypatch, capsys):
    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        return _fake_result(
            verification_state="inconclusive",
            limitations=["No automated check could be run for this project."],
        )

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    exit_code = cli.main(["do something", "--require-verification"])

    assert exit_code == 1
    assert "Verification: inconclusive" in capsys.readouterr().out


def test_require_verification_flag_makes_a_missing_tool_a_failure(monkeypatch):
    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        return _fake_result(
            verification_state="inconclusive",
            limitations=["npm is required to verify this project but was not found on PATH."],
        )

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    exit_code = cli.main(["do something", "--require-verification"])

    assert exit_code == 1


def test_require_verification_flag_makes_no_tests_collected_a_failure(monkeypatch):
    # Even the quiet, otherwise-non-blocking "pytest collected zero tests"
    # case is still just "inconclusive" — --require-verification doesn't
    # special-case it, since the whole point of opting in is "no evidence
    # is not good enough," regardless of which specific reason produced it.
    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        return _fake_result(verification_state="inconclusive", limitations=[])

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    exit_code = cli.main(["do something", "--require-verification"])

    assert exit_code == 1


def test_require_verification_flag_does_not_affect_a_real_verified_pass(monkeypatch):
    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        return _fake_result(verification_state="verified")

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    exit_code = cli.main(["do something", "--require-verification"])

    assert exit_code == 0


def test_require_verification_flag_does_not_change_other_failure_states(monkeypatch):
    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        return _fake_result(verification_state="retry_exhausted")

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    exit_code = cli.main(["do something", "--require-verification"])

    assert exit_code == 1


def test_execution_flag_overrides_configured_docker_default(monkeypatch):
    calls = {}

    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        calls["cfg"] = cfg
        return _fake_result()

    monkeypatch.setattr(cli, "load_config", lambda: _cfg(execution="docker"))
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    exit_code = cli.main(["do something", "--execution", "local"])

    assert exit_code == 0
    assert calls["cfg"].execution == "local"


# --- CERTO_CONFIRM_MODE=always wiring -------------------------------------


def test_exits_nonzero_when_confirmation_required_with_no_handler(monkeypatch, capsys):
    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        return _fake_result(
            [_FakeMessage("stopped")],
            verification_state="confirmation_required",
            limitations=["The agent proposed an action that required confirmation"],
        )

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    exit_code = cli.main(["do something"])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Verification: confirmation_required" in out


def test_confirm_mode_never_passes_no_confirm_handler_to_run_task(monkeypatch):
    calls = {}

    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        calls["on_confirm"] = on_confirm
        return _fake_result()

    monkeypatch.setattr(cli, "load_config", lambda: _cfg(confirm_mode="never"))
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    cli.main(["do something"])

    assert calls["on_confirm"] is None


def test_confirm_mode_always_passes_the_interactive_handler_to_run_task(monkeypatch):
    calls = {}

    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        calls["on_confirm"] = on_confirm
        return _fake_result()

    monkeypatch.setattr(cli, "load_config", lambda: _cfg(confirm_mode="always"))
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    cli.main(["do something"])

    assert calls["on_confirm"] is cli._confirm_pending_actions


def test_confirm_pending_actions_approves_only_on_explicit_yes(monkeypatch):
    from types import SimpleNamespace

    pending = [SimpleNamespace(tool_name="terminal", action="rm -rf /tmp/x")]

    monkeypatch.setattr("builtins.input", lambda _prompt: "y")
    assert cli._confirm_pending_actions(pending) is True

    monkeypatch.setattr("builtins.input", lambda _prompt: "yes")
    assert cli._confirm_pending_actions(pending) is True

    for reply in ("n", "no", "", "sure", "YOLO"):
        monkeypatch.setattr("builtins.input", lambda _prompt, reply=reply: reply)
        assert cli._confirm_pending_actions(pending) is False


# --- --interactive: opt-in interactive checkpoint ---------------------------


def test_interactive_flag_off_by_default_passes_no_callback(monkeypatch):
    calls = {}

    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        calls["cfg"] = cfg
        calls["on_awaiting_input"] = on_awaiting_input
        return _fake_result()

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    cli.main(["do something"])

    assert calls["cfg"].interactive is False
    assert calls["on_awaiting_input"] is None


def test_interactive_flag_sets_config_and_passes_the_terminal_handler(monkeypatch):
    calls = {}

    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        calls["cfg"] = cfg
        calls["on_awaiting_input"] = on_awaiting_input
        return _fake_result()

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    cli.main(["do something", "--interactive"])

    assert calls["cfg"].interactive is True
    assert calls["on_awaiting_input"] is cli._prompt_for_continuation


def test_prompt_for_continuation_prints_narrative_and_returns_the_reply(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _prompt: "please also add tests")

    reply = cli._prompt_for_continuation("Anything else you'd like?")

    assert reply == "please also add tests"
    assert "Anything else you'd like?" in capsys.readouterr().out


def test_prompt_for_continuation_returns_none_on_empty_reply(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt: "   ")

    assert cli._prompt_for_continuation("some narrative") is None


def test_prompt_for_continuation_handles_empty_narrative(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _prompt: "")

    reply = cli._prompt_for_continuation("")

    assert reply is None
    assert capsys.readouterr().out == ""  # nothing to show, no blank block printed


# --- --auto-model: opt-in deterministic model selection ---------------------

_AUTO_MODEL_CATALOG = """
models:
  - name: local
    model: ollama/qwen
    base_url: http://localhost:11434
    ratings: {code: 2, cost: 5}
  - name: cloud
    model: openai/luna
    api_key: k
    ratings: {code: 5, cost: 2}
"""


def _auto_model_cfg(tmp_path, **overrides):
    from model_file_helpers import write_model_files

    list_path, models_path = write_model_files(tmp_path, _AUTO_MODEL_CATALOG)
    return _cfg(
        workspace=str(tmp_path), models_file=models_path, models_list_file=list_path, **overrides
    )


@pytest.mark.parametrize("mode", ["--auto-model", "--escalate"])
def test_project_can_use_model_files_inside_existing_folder(monkeypatch, tmp_path, mode):
    project_dir = tmp_path / "leap"
    project_dir.mkdir()
    cfg = replace(_auto_model_cfg(project_dir, projects_dir=str(tmp_path)), workspace=str(tmp_path))
    calls = []

    def fake_run_task(task, cfg=None, **kwargs):
        assert project_dir.is_dir()
        calls.append(cfg)
        return _fake_result()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    monkeypatch.setattr(cli, "run_task", fake_run_task)

    assert cli.main(["hi", "--project", "leap", mode]) == 0

    assert calls[0].workspace == str(project_dir)
    assert not (tmp_path / ".certo-created-projects").exists()


def test_auto_model_flag_off_by_default(monkeypatch):
    calls = {}

    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        calls["cfg"] = cfg
        calls["on_model_choice"] = on_model_choice
        return _fake_result()

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    cli.main(["do something"])

    assert calls["cfg"].model_selection == "manual"
    assert calls["on_model_choice"] is None


def test_auto_model_flag_sets_config(monkeypatch, tmp_path):
    calls = {}

    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        calls["cfg"] = cfg
        return _fake_result()

    monkeypatch.setattr(cli, "load_config", lambda: _auto_model_cfg(tmp_path))
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    cli.main(["do something", "--auto-model"])

    assert calls["cfg"].model_selection == "auto"


def test_auto_model_only_passes_the_prompt_when_also_interactive(monkeypatch, tmp_path):
    calls = {}

    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        calls["on_model_choice"] = on_model_choice
        return _fake_result()

    monkeypatch.setattr(cli, "load_config", lambda: _auto_model_cfg(tmp_path))
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    cli.main(["do something", "--auto-model"])
    assert calls["on_model_choice"] is None  # auto-model without --interactive: no prompt

    cli.main(["do something", "--auto-model", "--interactive"])
    assert calls["on_model_choice"] is cli._prompt_for_model_choice


def test_auto_model_without_a_catalog_prints_only_the_error(monkeypatch, tmp_path, capsys):
    """Missing model files must stop before the banner or any run record (#12)."""
    from certo import run_history

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli, "load_config", lambda: _cfg(workspace=str(tmp_path), projects_dir=str(tmp_path))
    )
    monkeypatch.setattr(cli, "run_task", _fail_if_called)
    monkeypatch.setattr(cli, "append_run", run_history.append_run)

    assert cli.main(["hi", "--auto-model", "--project", "leap"]) == 1
    captured = capsys.readouterr()
    assert "Configuration error" in captured.err
    assert "No models_list.yaml found" in captured.err
    assert "models_list.yaml.example" in captured.err
    assert "Continue with" not in captured.err
    assert "Certo" not in captured.out
    assert not (tmp_path / "leap" / ".certo").exists()
    assert not (tmp_path / "leap").exists()
    assert not (tmp_path / ".certo-created-projects").exists()


def test_auto_model_with_broken_model_files_prints_only_the_error(monkeypatch, tmp_path, capsys):
    from certo import run_history

    (tmp_path / "models_list.yaml").write_text(
        "models:\n  - name: local\n    model: ollama/q\n  - name: local\n    model: ollama/r\n"
    )
    (tmp_path / "models.yaml").write_text(
        "models:\n  - name: local\n    base_url: http://localhost:11434\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda: _cfg(
            workspace=str(tmp_path),
            models_file=str(tmp_path / "models.yaml"),
            models_list_file=str(tmp_path / "models_list.yaml"),
        ),
    )
    monkeypatch.setattr(cli, "run_task", _fail_if_called)
    monkeypatch.setattr(cli, "append_run", run_history.append_run)

    assert cli.main(["hi", "--auto-model"]) == 1
    captured = capsys.readouterr()
    assert "Configuration error" in captured.err
    assert "named 'local'" in captured.err
    assert "Continue with" not in captured.err
    assert "Certo" not in captured.out
    assert not (tmp_path / ".certo").exists()


def test_prompt_for_model_choice_accepts_the_recommendation_on_enter(monkeypatch, capsys):
    from certo.model_catalog import ModelCatalogEntry

    candidates = [
        ModelCatalogEntry(name="cheap", model="a", ratings={"cost": 5}, description="Fast."),
        ModelCatalogEntry(name="strong", model="b", ratings={"reasoning": 5}),
    ]
    monkeypatch.setattr("builtins.input", lambda _prompt: "")

    choice = cli._prompt_for_model_choice(candidates, 0, "Task classified as 'default'.")

    assert choice == 0
    out = capsys.readouterr().out
    assert "cheap" in out
    assert "strong" in out
    assert "Fast." in out


def test_prompt_for_model_choice_accepts_a_typed_index(monkeypatch):
    from certo.model_catalog import ModelCatalogEntry

    candidates = [
        ModelCatalogEntry(name="cheap", model="a", ratings={}),
        ModelCatalogEntry(name="strong", model="b", ratings={}),
    ]
    monkeypatch.setattr("builtins.input", lambda _prompt: "1")

    choice = cli._prompt_for_model_choice(candidates, 0, "reason")

    assert choice == 1


def test_prompt_for_model_choice_falls_back_to_recommended_on_invalid_input(monkeypatch):
    from certo.model_catalog import ModelCatalogEntry

    candidates = [ModelCatalogEntry(name="only", model="a", ratings={})]
    monkeypatch.setattr("builtins.input", lambda _prompt: "not a number")

    assert cli._prompt_for_model_choice(candidates, 0, "reason") == 0


def test_prompt_for_model_choice_falls_back_to_recommended_on_out_of_range_index(monkeypatch):
    from certo.model_catalog import ModelCatalogEntry

    candidates = [ModelCatalogEntry(name="only", model="a", ratings={})]
    monkeypatch.setattr("builtins.input", lambda _prompt: "99")

    assert cli._prompt_for_model_choice(candidates, 0, "reason") == 0


# --- --acceptance-checks: opt-in machine-checkable acceptance criteria ------


def test_resolve_acceptance_checks_parses_inline_json():
    checks = cli.resolve_acceptance_checks('[{"kind": "file_exists", "path": "README.md"}]')

    assert len(checks) == 1
    assert checks[0].kind == "file_exists"
    assert checks[0].path == "README.md"


def test_resolve_acceptance_checks_reads_a_file(tmp_path):
    checks_file = tmp_path / "checks.json"
    checks_file.write_text('[{"kind": "file_exists", "path": "OUTPUT.txt"}]')

    checks = cli.resolve_acceptance_checks(str(checks_file))

    assert checks[0].path == "OUTPUT.txt"


def test_resolve_acceptance_checks_rejects_invalid_json():
    with pytest.raises(ValueError, match="must be valid JSON"):
        cli.resolve_acceptance_checks("not json")


def test_resolve_acceptance_checks_rejects_a_non_array():
    with pytest.raises(ValueError, match="must be a JSON array"):
        cli.resolve_acceptance_checks('{"kind": "file_exists", "path": "x"}')


def test_resolve_acceptance_checks_rejects_an_invalid_check():
    with pytest.raises(ValueError, match="Unknown acceptance check kind"):
        cli.resolve_acceptance_checks('[{"kind": "run_command", "path": "x"}]')


def test_main_rejects_bad_acceptance_checks_json(monkeypatch, capsys):
    def _fail_if_called(*args, **kwargs):
        raise AssertionError("run_task should not be called")

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fail_if_called)

    exit_code = cli.main(["do something", "--acceptance-checks", "not json"])

    assert exit_code == 1
    assert "Configuration error" in capsys.readouterr().err


def test_main_passes_parsed_acceptance_checks_to_run_task(monkeypatch):
    calls = {}

    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        calls["acceptance_checks"] = acceptance_checks
        return _fake_result()

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    exit_code = cli.main(
        [
            "do something",
            "--acceptance-checks",
            '[{"kind": "file_exists", "path": "OUTPUT.txt"}]',
        ]
    )

    assert exit_code == 0
    assert calls["acceptance_checks"][0].path == "OUTPUT.txt"


def test_main_without_acceptance_checks_flag_passes_none(monkeypatch):
    calls = {}

    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        calls["acceptance_checks"] = acceptance_checks
        return _fake_result()

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    cli.main(["do something"])

    assert calls["acceptance_checks"] is None


def test_exits_nonzero_when_acceptance_check_failed(monkeypatch, capsys):
    def _fake_run_task(
        task,
        cfg=None,
        on_confirm=None,
        acceptance_checks=None,
        on_awaiting_input=None,
        on_model_choice=None,
        run_id=None,
        project=None,
        **_state,
    ):
        return _fake_result(
            [_FakeMessage("done, I think")],
            verification_state="acceptance_failed",
            limitations=[
                "Required acceptance check failed (OUTPUT.txt): OUTPUT.txt does not exist"
            ],
        )

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fake_run_task)

    exit_code = cli.main(["do something"])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Verification: acceptance_failed" in out


def test_cli_prints_run_summary_at_the_end(monkeypatch, capsys):
    result = _fake_result([_FakeMessage("done")])
    result.outcome = TaskOutcome(
        verification_state="verified",
        completion_contract=result.outcome.completion_contract,
        run_summary=RunSummary(
            duration_seconds=242.6,
            models=(
                ModelUsage(
                    model="openai/gpt-4o", prompt_tokens=900, completion_tokens=100, cost=0.05
                ),
            ),
        ),
    )
    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", lambda *a, **kw: result)

    assert cli.main(["do something"]) == 0

    out = capsys.readouterr().out
    assert out.index("Verification: verified") < out.index("Run summary:")
    assert "Total running time: 4m 03s" in out
    assert "Models: openai/gpt-4o" in out
    assert "Total tokens: 1,000" in out
    assert "Total cost: $0.0500" in out


# --- Console scripts: exactly the certo-* commands --------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent

# The pre-rename `harness*` aliases were dropped before the first PyPI
# release: a bare `harness` on a user's PATH could shadow another tool.
_SCRIPTS = {
    "certo": "certo.cli:main",
    "certo-server": "certo.server:main",
    "certo-admin": "certo.admin_cli:main",
}


def _declared_scripts() -> dict[str, str]:
    with open(_REPO_ROOT / "pyproject.toml", "rb") as fh:
        return tomllib.load(fh)["project"]["scripts"]


def test_console_scripts_are_exactly_the_certo_commands():
    assert _declared_scripts() == _SCRIPTS


def test_installed_console_scripts_are_exactly_the_certo_commands():
    """Same check against the installed distribution's metadata, so a stale
    install (pyproject edited, package not reinstalled) is caught too."""
    try:
        eps = importlib.metadata.distribution("certo").entry_points
    except importlib.metadata.PackageNotFoundError:
        pytest.skip("certo distribution is not installed")
    by_name = {ep.name: ep.value for ep in eps if ep.group == "console_scripts"}
    assert by_name == _SCRIPTS


def test_parser_prog_is_certo():
    assert cli._build_parser().prog == "certo"


# --- OpenHands SDK startup banner -----------------------------------------


def _run_help(env_overrides: dict[str, str]) -> str:
    """Run `python -m certo --help` in a fresh process (the banner prints on
    the SDK's first import, which in this test process already happened)."""
    import os
    import subprocess
    import sys

    env = {k: v for k, v in os.environ.items() if k != "OPENHANDS_SUPPRESS_BANNER"}
    env["PYTHONPATH"] = str(_REPO_ROOT / "src")
    env.update(env_overrides)
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import certo.cli, sys; sys.argv=['certo','--help']; certo.cli.main()",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return proc.stdout + proc.stderr


def test_sdk_banner_is_suppressed_by_default():
    out = _run_help({})
    assert "usage: certo" in out
    assert "OpenHands SDK v" not in out


def _run_sdk_import(env_overrides: dict[str, str]) -> str:
    """Import certo, then the SDK, as a command that runs an agent does."""
    import os
    import subprocess
    import sys

    env = {k: v for k, v in os.environ.items() if k != "OPENHANDS_SUPPRESS_BANNER"}
    env["PYTHONPATH"] = str(_REPO_ROOT / "src")
    env.update(env_overrides)
    proc = subprocess.run(
        [sys.executable, "-c", "import certo, openhands.sdk"],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return proc.stdout + proc.stderr


def test_sdk_banner_is_suppressed_when_the_sdk_loads():
    assert "OpenHands SDK v" not in _run_sdk_import({})


def test_sdk_banner_shows_when_explicitly_enabled():
    # --help no longer loads the SDK at all, so load it directly.
    assert "OpenHands SDK v" in _run_sdk_import({"OPENHANDS_SUPPRESS_BANNER": "0"})


def test_help_and_version_do_not_load_the_sdk():
    """The SDK takes about 2 seconds to import; commands that run no agent
    must not pay for it."""
    import os
    import subprocess
    import sys

    env = dict(os.environ, PYTHONPATH=str(_REPO_ROOT / "src"))
    code = (
        "import sys, certo.cli\n"
        "for argv in (['--version'], ['--help'], ['verify', '--help']):\n"
        "    try:\n"
        "        certo.cli.main(argv)\n"
        "    except SystemExit:\n"
        "        pass\n"
        "print('SDK' if any(m.startswith('openhands') for m in sys.modules) else 'none')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True
    )
    assert proc.stdout.strip().splitlines()[-1] == "none"


# --- certo verify -------------------------------------------------------------


def _capture_task(monkeypatch):
    calls = {}

    def _fake_run_task(task, **_kwargs):
        calls["task"] = task
        return _fake_result([_FakeMessage("done")])

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _fake_run_task)
    monkeypatch.setattr(cli, "verify_main", lambda _argv: pytest.fail("verify must not run"))
    return calls


@pytest.mark.parametrize(
    "argv",
    [
        ["verify the login flow"],
        ["Verify"],
        ["verify:"],
        ["--", "verify"],
        ["--model", "x/y", "verify the app"],
    ],
)
def test_a_task_mentioning_verify_is_still_a_task(monkeypatch, argv):
    calls = _capture_task(monkeypatch)

    assert cli.main(argv) == 0
    assert calls["task"] == argv[-1]


def test_verify_subcommand_needs_no_llm_config(monkeypatch, tmp_path, project_venv, capsys):
    project_venv(tmp_path)
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    monkeypatch.setattr(cli, "load_config", lambda: pytest.fail("verify must not load LLM config"))
    monkeypatch.setattr(
        cli, "run_task", lambda *a, **kw: pytest.fail("verify must not run an agent")
    )

    exit_code = cli.main(["verify", str(tmp_path)])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert f"Project: {tmp_path} (python)" in out
    assert "Verification: verified" in out


def test_verify_defaults_to_the_current_directory(monkeypatch, tmp_path, project_venv, capsys):
    project_venv(tmp_path)
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    monkeypatch.chdir(tmp_path)

    assert cli.main(["verify"]) == 0
    assert "Verification: verified" in capsys.readouterr().out


def test_verify_failing_project_exits_nonzero_and_shows_the_output(tmp_path, project_venv, capsys):
    project_venv(tmp_path)
    (tmp_path / "test_bad.py").write_text("def test_bad():\n    assert 1 == 2, 'boom'\n")

    exit_code = cli.main(["verify", str(tmp_path)])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Verification: failed" in out
    assert "boom" in out


def test_verify_inconclusive_exits_zero_unless_verification_is_required(tmp_path, capsys):
    (tmp_path / "notes.md").write_text("nothing to run\n")

    assert cli.main(["verify", str(tmp_path)]) == 0
    assert "Verification: inconclusive" in capsys.readouterr().out
    assert cli.main(["verify", str(tmp_path), "--require-verification"]) == 1


def test_verify_rejects_a_missing_directory(tmp_path, capsys):
    assert cli.main(["verify", str(tmp_path / "nope")]) == 1
    assert "is not a directory" in capsys.readouterr().err


def test_task_help_mentions_the_verify_subcommand():
    assert "certo verify [PATH]" in cli._build_parser().format_help()


# --- certo --resume ------------------------------------------------------------


def _saved_run(workspace, **overrides):
    from certo.project_state import RunRecord, save_record

    values = {
        "task": "Build a Wordle game",
        "conversation_id": "b" * 32,
        "model": "openai/gpt-4o",
        "execution": "local",
        "started_at": "2026-10-16T10:00:00+00:00",
        "updated_at": "2026-10-16T10:00:00+00:00",
        "status": "finished",
        "verdict": "retry_exhausted",
    }
    values.update(overrides)
    save_record(str(workspace), RunRecord(**values))


def _fail_if_called(*_args, **_kwargs):
    raise AssertionError("run_task must not be called")


def _recording_run_task(calls, verification_state="verified"):
    def fake(task, **kwargs):
        calls.append({"task": task, **kwargs})
        return _fake_result([_FakeMessage("done")], verification_state=verification_state)

    return fake


def test_task_is_required_without_resume(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    with pytest.raises(SystemExit):
        cli.main([])
    assert "required: task" in capsys.readouterr().err


def test_a_normal_run_asks_the_runner_to_save_state(monkeypatch, tmp_path):
    calls: list = []
    monkeypatch.setattr(cli, "load_config", lambda: _cfg(workspace=str(tmp_path)))
    monkeypatch.setattr(cli, "run_task", _recording_run_task(calls))

    assert cli.main(["do it"]) == 0
    assert calls[0]["save_state"] is True
    assert calls[0]["resume_from"] is None


def test_certo_save_state_off_is_passed_on(monkeypatch, tmp_path):
    calls: list = []
    monkeypatch.setattr(cli, "load_config", lambda: _cfg(workspace=str(tmp_path), save_state=False))
    monkeypatch.setattr(cli, "run_task", _recording_run_task(calls))

    cli.main(["do it"])
    assert calls[0]["save_state"] is False


def test_resume_with_nothing_saved_is_an_error(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "load_config", lambda: _cfg(workspace=str(tmp_path)))
    monkeypatch.setattr(cli, "run_task", _fail_if_called)

    assert cli.main(["--resume"]) == 1
    assert "nothing to resume" in capsys.readouterr().err


def test_resume_continues_the_saved_task_with_the_optional_instruction(monkeypatch, tmp_path):
    _saved_run(tmp_path)
    calls: list = []
    monkeypatch.setattr(cli, "load_config", lambda: _cfg(workspace=str(tmp_path)))
    monkeypatch.setattr(cli, "run_task", _recording_run_task(calls))

    assert cli.main(["--resume", "use port 8080"]) == 0
    assert calls[0]["task"] == "Build a Wordle game"
    assert calls[0]["resume_from"].verdict == "retry_exhausted"
    assert calls[0]["resume_instruction"] == "use port 8080"
    assert calls[0]["save_state"] is True


def test_resume_saves_state_even_when_saving_is_off(monkeypatch, tmp_path):
    _saved_run(tmp_path)
    calls: list = []
    monkeypatch.setattr(cli, "load_config", lambda: _cfg(workspace=str(tmp_path), save_state=False))
    monkeypatch.setattr(cli, "run_task", _recording_run_task(calls))

    cli.main(["--resume"])
    assert calls[0]["save_state"] is True


def test_resume_of_a_verified_run_needs_an_instruction(monkeypatch, tmp_path, capsys):
    _saved_run(tmp_path, verdict="verified")
    monkeypatch.setattr(cli, "load_config", lambda: _cfg(workspace=str(tmp_path)))
    monkeypatch.setattr(cli, "run_task", _fail_if_called)

    assert cli.main(["--resume"]) == 0
    assert "already ended with 'verified'" in capsys.readouterr().out


def test_resume_of_a_missing_project_is_an_error(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "load_config", lambda: _cfg(projects_dir=str(tmp_path)))
    monkeypatch.setattr(cli, "run_task", _fail_if_called)

    assert cli.main(["--resume", "--project", "nope"]) == 1
    assert "nothing to resume" in capsys.readouterr().err
    assert not (tmp_path / "nope").exists()


def test_a_failing_verdict_points_at_status_md_and_resume(monkeypatch, tmp_path, capsys):
    calls: list = []
    monkeypatch.setattr(cli, "load_config", lambda: _cfg(projects_dir=str(tmp_path)))
    monkeypatch.setattr(cli, "run_task", _recording_run_task(calls, "retry_exhausted"))

    assert cli.main(["do it", "--project", "game"]) == 1
    out = capsys.readouterr().out
    assert "STATUS.md" in out
    assert "certo --resume --project game" in out


def test_resume_hint_includes_projects_dir_only_when_not_default(monkeypatch, tmp_path, capsys):
    """The printed resume command must carry CERTO_PROJECTS_DIR when the
    run used a non-default projects folder; with the default it stays plain.
    """
    import shlex

    from certo.config import DEFAULT_PROJECTS_DIR

    calls: list = []
    monkeypatch.setattr(cli, "run_task", _recording_run_task(calls, "retry_exhausted"))
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(cli, "load_config", lambda: _cfg(projects_dir=DEFAULT_PROJECTS_DIR))
    assert cli.main(["do it", "--project", "leap"]) == 1
    default_out = capsys.readouterr().out
    assert "Continue with: certo --resume --project leap" in default_out
    assert "CERTO_PROJECTS_DIR=" not in default_out

    custom = str(tmp_path / "my work")
    monkeypatch.setattr(cli, "load_config", lambda: _cfg(projects_dir=custom))
    assert cli.main(["do it", "--project", "leap"]) == 1
    custom_out = capsys.readouterr().out
    assert (
        f"Continue with: CERTO_PROJECTS_DIR={shlex.quote(custom)} certo --resume --project leap"
    ) in custom_out


def test_ctrl_c_prints_how_to_resume_and_exits_130(monkeypatch, tmp_path, capsys):
    def interrupted(task, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "load_config", lambda: _cfg(workspace=str(tmp_path)))
    monkeypatch.setattr(cli, "run_task", interrupted)

    assert cli.main(["do it"]) == 130
    assert "Continue with: certo --resume" in capsys.readouterr().err


# --- --escalate -------------------------------------------------------------------------

_ESCALATION_CATALOG = """
models:
  - name: local
    model: ollama/qwen
    base_url: http://localhost:11434
    ratings: {code: 2, cost: 5}
  - name: cloud
    model: openai/luna
    api_key: k
    ratings: {code: 5, cost: 2}
escalation:
  ladders:
    default: [{model: local}, {model: cloud}]
    cloud-only: [{model: cloud}]
"""


def _escalation_cfg(tmp_path, **overrides):
    from model_file_helpers import write_model_files

    list_path, models_path = write_model_files(tmp_path, _ESCALATION_CATALOG)
    return _cfg(
        workspace=str(tmp_path), models_file=models_path, models_list_file=list_path, **overrides
    )


@pytest.mark.parametrize(
    ("argv", "ladder_name"),
    [
        (["do it", "--escalate"], "default"),
        (["do it", "--escalate", "cloud-only"], "cloud-only"),
        # The flag first: a lone value is the task (seen failing 2026-10-20).
        (["--escalate", "do it"], "default"),
        (["--escalate", "cloud-only", "do it"], "cloud-only"),
    ],
)
def test_escalate_resolves_the_ladder_and_passes_it(monkeypatch, tmp_path, argv, ladder_name):
    calls: list = []
    monkeypatch.setattr(cli, "load_config", lambda: _escalation_cfg(tmp_path))
    monkeypatch.setattr(cli, "run_task", _recording_run_task(calls))

    assert cli.main(argv) == 0
    assert calls[0]["task"] == "do it"
    assert calls[0]["cfg"].model_selection == "escalate"
    assert calls[0]["ladder"].name == ladder_name


def test_the_escalate_setting_works_without_the_flag(monkeypatch, tmp_path):
    calls: list = []
    monkeypatch.setattr(
        cli, "load_config", lambda: _escalation_cfg(tmp_path, model_selection="escalate")
    )
    monkeypatch.setattr(cli, "run_task", _recording_run_task(calls))

    assert cli.main(["do it"]) == 0
    assert calls[0]["ladder"].name == "default"


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["do it", "--escalate", "--auto-model"], "can't be combined with --auto-model or --model"),
        (["do it", "--escalate", "--model", "openai/x"], "can't be combined"),
        (
            ["do it", "--escalate", "fast"],
            "no escalation ladder named 'fast' in escalation.yaml. Ladders: cloud-only, default.",
        ),
        (["--resume", "--escalate"], "--resume can't be combined with escalation"),
    ],
)
def test_escalate_errors(monkeypatch, tmp_path, capsys, argv, message):
    monkeypatch.setattr(cli, "load_config", lambda: _escalation_cfg(tmp_path))
    monkeypatch.setattr(cli, "run_task", _fail_if_called)

    assert cli.main(argv) == 1
    assert message in capsys.readouterr().err


def test_model_flag_with_the_escalate_setting_is_an_error(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        cli, "load_config", lambda: _escalation_cfg(tmp_path, model_selection="escalate")
    )
    monkeypatch.setattr(cli, "run_task", _fail_if_called)

    assert cli.main(["do it", "--model", "openai/x"]) == 1
    assert "--model can't be used while CERTO_MODEL_SELECTION=escalate" in capsys.readouterr().err


def test_escalate_without_a_catalog_says_what_to_do(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "load_config", lambda: _cfg(workspace=str(tmp_path)))
    monkeypatch.setattr(cli, "run_task", _fail_if_called)

    assert cli.main(["do it", "--escalate"]) == 1
    err = capsys.readouterr().err
    assert "No models_list.yaml found" in err
    assert "models_list.yaml.example" in err


def test_escalate_prints_progress_and_asks_only_when_interactive(monkeypatch, tmp_path):
    calls: list = []
    monkeypatch.setattr(cli, "load_config", lambda: _escalation_cfg(tmp_path))
    monkeypatch.setattr(cli, "run_task", _recording_run_task(calls))

    cli.main(["do it", "--escalate"])
    cli.main(["do it", "--escalate", "--interactive"])

    # Escalation lines are Certo's notices, printed once through on_notice
    # (live 2026-10-22: with on_progress too, each line printed twice).
    assert "on_progress" not in calls[0]
    assert calls[0]["on_notice"] is cli._print_progress
    assert calls[0]["on_escalate"] is None
    assert calls[1]["on_escalate"] is cli._confirm_escalation


@pytest.mark.parametrize(("answer", "climbs"), [("", True), ("y", True), ("n", False)])
def test_the_escalation_prompt(monkeypatch, answer, climbs):
    monkeypatch.setattr("builtins.input", lambda prompt: answer)
    assert cli._confirm_escalation("Try mid next?") is climbs


def test_an_escalation_run_prints_one_line_per_rung(monkeypatch, tmp_path, capsys):
    from certo.escalation import RungResult
    from certo.run_summary import RunSummary

    def fake(task, **kwargs):
        result = _fake_result([_FakeMessage("done")])
        result.outcome = replace(
            result.outcome,
            run_summary=RunSummary(duration_seconds=1.0),
            rungs=(
                RungResult(1, "local", "ollama/q", "no_progress", 1, 60.0, RunSummary(60.0)),
                RungResult(2, "mid", "openai/m", "verified", 0, 30.0, RunSummary(30.0)),
            ),
            final_rung=2,
        )
        return result

    monkeypatch.setattr(cli, "load_config", lambda: _escalation_cfg(tmp_path))
    monkeypatch.setattr(cli, "run_task", fake)

    assert cli.main(["do it", "--escalate"]) == 0
    out = capsys.readouterr().out
    assert "  Rungs:" in out
    assert (
        "    1. local (ollama/q, effort default): no_progress, 1 fix attempt, 1m 00s, 0 tokens, "
        "$0.0000" in out
    )
    assert "  Final result from rung 2 (mid)." in out


@pytest.mark.parametrize(("flag", "expected"), [([], 0), (["--require-verification"], 1)])
def test_unchanged_exits_like_inconclusive(monkeypatch, capsys, flag, expected):
    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(
        cli, "run_task", lambda task, **_kw: _fake_result(verification_state="unchanged")
    )

    assert cli.main(["do something", *flag]) == expected
    assert "Verification: unchanged" in capsys.readouterr().out


def test_a_finished_run_is_recorded_with_its_model_and_verdict(monkeypatch, recorded_runs):
    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(
        cli, "run_task", lambda *a, **k: _fake_result(verification_state="verified")
    )

    assert cli.main(["Build a CLI todo app\nwith tests"]) == 0

    (entry,) = recorded_runs
    assert entry.ended == "verified"
    assert entry.models == ["openai/gpt-4o (effort default)"]
    assert entry.task.startswith("Build a CLI todo app")


def test_an_interrupted_run_is_recorded_too(monkeypatch, recorded_runs):
    def _interrupt(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", _interrupt)

    assert cli.main(["do something"]) == 130
    assert [e.ended for e in recorded_runs] == ["interrupted"]


def test_no_run_is_recorded_when_saving_state_is_off(monkeypatch, recorded_runs):
    monkeypatch.setattr(cli, "load_config", lambda: _cfg(save_state=False))
    monkeypatch.setattr(cli, "run_task", lambda *a, **k: _fake_result())

    assert cli.main(["do something"]) == 0
    assert recorded_runs == []


def test_a_history_write_that_fails_never_fails_the_run(monkeypatch, capsys):
    def _fail(workspace, entry):
        raise OSError("read-only file system")

    monkeypatch.setattr(cli, "append_run", _fail)
    monkeypatch.setattr(cli, "load_config", lambda: _cfg())
    monkeypatch.setattr(cli, "run_task", lambda *a, **k: _fake_result())

    assert cli.main(["do something"]) == 0
    assert "couldn't add this run to .certo/RUNS.md" in capsys.readouterr().err


def _builds_a_readme(cfg_holder):
    def _fake_run_task(task, cfg=None, **_):
        Path(cfg.workspace, "README.md").write_text("# App\n")
        cfg_holder.append(cfg)
        summary = RunSummary(duration_seconds=1.0, models=(ModelUsage(model="openai/gpt-4o"),))
        return TaskResult([], replace(_fake_result().outcome, run_summary=summary))

    return _fake_run_task


def test_a_project_certo_created_gets_the_model_note_in_its_readme(monkeypatch, tmp_path):
    cfgs = []
    monkeypatch.setattr(cli, "load_config", lambda: _cfg(projects_dir=str(tmp_path)))
    monkeypatch.setattr(cli, "run_task", _builds_a_readme(cfgs))

    assert cli.main(["build an app", "--project", "app"]) == 0

    text = (tmp_path / "app" / "README.md").read_text()
    assert "<!-- certo:models -->" in text
    assert "using `openai/gpt-4o`." in text


def test_a_folder_certo_did_not_create_keeps_its_readme(monkeypatch, tmp_path):
    (tmp_path / "mine").mkdir()
    monkeypatch.setattr(cli, "load_config", lambda: _cfg(projects_dir=str(tmp_path)))
    monkeypatch.setattr(cli, "run_task", _builds_a_readme([]))

    assert cli.main(["build an app", "--project", "mine"]) == 0

    assert (tmp_path / "mine" / "README.md").read_text() == "# App\n"


def test_a_run_says_when_a_third_party_skill_replaces_an_official_one(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    skills = tmp_path / "xdg" / "certo" / "skills"
    skills.mkdir(parents=True)
    (skills / "pytest-conventions.md").write_text(
        "---\nname: pytest-conventions\ntriggers:\n  - pytest\n---\nMine.\n"
    )
    monkeypatch.setattr(
        cli, "load_config", lambda: _cfg(workspace=str(tmp_path), skills_dir=str(tmp_path / "none"))
    )
    monkeypatch.setattr(
        cli, "run_task", lambda *a, **k: _fake_result(verification_state="verified")
    )

    assert cli.main(["do it"]) == 0
    assert (
        "Certo: your global skill 'pytest-conventions' replaces the official one."
        in capsys.readouterr().out
    )
