"""certo.api: the shared core the CLI, the server and the MCP server call.
No LLM or network: `load` returns a constructed Config."""

from __future__ import annotations

import os

import pytest

from certo.api import RunOptions, UsageError, prepare_workspace, resolve_config
from certo.config import Config, ConfigError
from certo.worktree import was_created_by_certo


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


def _flag(name: str) -> str:
    return "--" + name.replace("_", "-")


def test_the_options_go_on_top_of_the_settings():
    cfg = resolve_config(
        RunOptions(model="anthropic/x", execution="docker", verbose=True),
        load=lambda: _cfg(),
    )
    assert cfg.model == "anthropic/x"
    assert cfg.execution == "docker"
    assert cfg.verbose is True


def test_max_steps_sets_the_step_limit_for_this_run():
    assert resolve_config(RunOptions(), load=lambda: _cfg()).max_iterations == 10
    cfg = resolve_config(RunOptions(max_steps=200), load=lambda: _cfg())
    assert cfg.max_iterations == 200


def test_max_steps_below_one_is_refused():
    with pytest.raises(UsageError, match="--max-steps must be 1 or more"):
        resolve_config(RunOptions(max_steps=0), load=lambda: _cfg(), spell=_flag)


def test_a_model_given_as_an_option_is_enough_without_one_in_the_settings():
    cfg = resolve_config(
        RunOptions(model="openai/gpt-4o", api_key="k"), load=lambda: _cfg(model="", api_key=None)
    )
    assert cfg.model == "openai/gpt-4o"


def test_a_run_with_no_model_anywhere_is_refused():
    with pytest.raises(ConfigError):
        resolve_config(RunOptions(), load=lambda: _cfg(model="", api_key=None))


def test_a_ladder_needs_no_model_in_the_settings():
    cfg = resolve_config(RunOptions(escalate=""), load=lambda: _cfg(model="", api_key=None))
    assert cfg.model_selection == "escalate"
    assert cfg.escalation_ladder == ""


@pytest.mark.parametrize(
    ("options", "spell", "message"),
    [
        (RunOptions(agents_md="x"), str, "agents_md requires project"),
        (RunOptions(agents_md="x"), _flag, "--agents-md requires --project"),
        (RunOptions(escalate="", model="openai/x"), str, "escalate can't be combined with model"),
        (
            RunOptions(escalate="", auto_model=True),
            _flag,
            "--escalate can't be combined with --auto-model or --model",
        ),
    ],
)
def test_options_that_dont_go_together_are_named_as_the_interface_spells_them(
    options, spell, message
):
    with pytest.raises(UsageError, match=message):
        resolve_config(options, load=lambda: _cfg(), spell=spell)


def test_a_model_while_the_settings_escalate_is_refused():
    with pytest.raises(UsageError, match="CERTO_MODEL_SELECTION=escalate"):
        resolve_config(RunOptions(model="openai/x"), load=lambda: _cfg(model_selection="escalate"))


def test_independent_tests_off_also_turns_strict_off():
    cfg = resolve_config(
        RunOptions(independent_tests=False),
        load=lambda: _cfg(independent_tests=True, independent_tests_strict=True),
    )
    assert (cfg.independent_tests, cfg.independent_tests_strict) == (False, False)


def test_a_project_is_resolved_inside_the_projects_folder_but_not_created(tmp_path):
    cfg = resolve_config(RunOptions(project="demo"), load=lambda: _cfg(projects_dir=str(tmp_path)))
    assert cfg.workspace == os.path.join(str(tmp_path), "demo")
    assert not os.path.exists(cfg.workspace)


def test_a_project_name_that_leaves_the_projects_folder_is_refused(tmp_path):
    with pytest.raises(ConfigError):
        resolve_config(RunOptions(project="../out"), load=lambda: _cfg(projects_dir=str(tmp_path)))


def test_prepare_workspace_creates_the_project_and_remembers_it(tmp_path):
    options = RunOptions(project="demo", agents_md="Use tabs.")
    cfg = resolve_config(options, load=lambda: _cfg(projects_dir=str(tmp_path)))
    assert prepare_workspace(cfg, options) is True
    assert os.path.isdir(cfg.workspace)
    assert was_created_by_certo(str(tmp_path), "demo")
    assert prepare_workspace(cfg, options) is False
