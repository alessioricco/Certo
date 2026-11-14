"""`certo models update`: slim a full copy of the model list to the user's
own changes (models_slim.py), and the command. No model and no network."""

from __future__ import annotations

import pytest
import yaml
from test_init_cmd import Script

from certo import cli
from certo.models_cmd import models_main
from certo.models_slim import plan_slim, render

# Certo's list as it is now.
_CERTO = """models:
  - name: local
    model: ollama/qwen3-coder:30b
    ratings: {reasoning: 1, code: 2, cost: 5}
  - name: cloud
    model: openai/gpt-6-luna
    description: The cheap one.
    ratings: {reasoning: 4, code: 4, cost: 4}
  - name: strong
    model: anthropic/claude-opus-5-5
    ratings: {reasoning: 5, code: 5, cost: 1}
"""

# What the user's copy came from: an older Certo list.
_BASE = """models:
  - name: local
    model: ollama/qwen3-coder:30b
    ratings: {reasoning: 1, code: 1, cost: 5}
  - name: old-cloud
    model: openai/gpt-4.1
    ratings: {reasoning: 3, code: 3, cost: 3}
  - name: cloud
    model: openai/gpt-6-luna
    description: The cheap one.
    ratings: {reasoning: 4, code: 4, cost: 4}
"""

# The user's copy: the base, with cloud's code changed by the user, and a
# model of their own.
_USER = """# My list.
models:
  - name: local
    model: ollama/qwen3-coder:30b
    ratings: {reasoning: 1, code: 1, cost: 5}
  - name: old-cloud
    model: openai/gpt-4.1
    ratings: {reasoning: 3, code: 3, cost: 3}
  - name: cloud
    model: openai/gpt-6-luna
    description: The cheap one.
    ratings: {reasoning: 4, code: 5, cost: 4}
  - name: mine
    model: openrouter/z-ai/glm-5
    ratings: {code: 3, cost: 4}
"""


def _models(text):
    return yaml.safe_load(text)["models"]


def test_with_a_base_only_the_users_own_changes_stay():
    plans = plan_slim(_models(_USER), _models(_CERTO), _models(_BASE), used=set())

    result = _models(render(plans))

    assert result == [
        {"name": "cloud", "ratings": {"code": 5}},
        {"name": "mine", "model": "openrouter/z-ai/glm-5", "ratings": {"code": 3, "cost": 4}},
    ]


def test_an_old_value_the_user_never_changed_is_dropped():
    plans = {p.name: p for p in plan_slim(_models(_USER), _models(_CERTO), _models(_BASE), set())}

    assert "ratings.code" in plans["local"].dropped  # base 1, Certo now 2: just old
    assert plans["old-cloud"].remove  # Certo removed it, unchanged and unused


def test_a_model_certo_removed_stays_while_models_yaml_uses_it():
    plans = {
        p.name: p for p in plan_slim(_models(_USER), _models(_CERTO), _models(_BASE), {"old-cloud"})
    }

    assert not plans["old-cloud"].remove


def test_without_a_base_differences_are_undecided():
    plans = {p.name: p for p in plan_slim(_models(_USER), _models(_CERTO), None, set())}

    assert plans["local"].undecided == {"ratings.code": (1, 2)}
    assert plans["cloud"].undecided == {"ratings.code": (5, 4)}
    assert "description" in plans["cloud"].dropped  # the same as Certo's


def test_nothing_left_means_no_file():
    plans = plan_slim(_models(_CERTO), _models(_CERTO), None, set())

    assert render(plans) is None


# --- the command -----------------------------------------------------------------


@pytest.fixture
def files(tmp_path, monkeypatch):
    config = tmp_path / "config"
    folder = config / "certo"
    folder.mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    (folder / "models_list.yaml").write_text(_USER)
    certo = tmp_path / "certo.yaml"
    certo.write_text(_CERTO)
    return folder, str(certo)


def _update(example, answers=(), argv=("update",), interactive=True):
    script = Script(answers=answers)
    code = models_main(
        list(argv), prompter=script.prompter(), interactive=interactive, example=example
    )
    return code, script.text


def test_with_a_base_it_slims_after_one_confirmation(files):
    folder, certo = files
    (folder / ".models_list.base.yaml").write_text(_BASE)

    code, text = _update(certo, answers=[""])

    assert code == 0, text
    assert "cloud: your change kept (code 5)" in text
    assert "No model is gone: the other 1 (local) still come from Certo's own list" in text
    assert _models((folder / "models_list.yaml").read_text())[0] == {
        "name": "cloud",
        "ratings": {"code": 5},
    }
    assert (folder / "models_list.yaml.bak").read_text() == _USER
    assert not (folder / ".models_list.base.yaml").exists()


def test_without_a_base_it_asks_per_model(files):
    folder, certo = files

    # local: use Certo's (default); cloud: keep yours; then confirm.
    code, text = _update(certo, answers=["", "1", ""])

    assert code == 0, text
    assert "Certo can't tell your changes from old values" in text
    names = {m["name"]: m for m in _models((folder / "models_list.yaml").read_text())}
    assert "local" not in names
    assert names["cloud"] == {"name": "cloud", "ratings": {"code": 5}}


def test_use_certos_drops_every_undecided_value(files):
    folder, certo = files

    code, text = _update(certo, argv=("update", "--use-certos", "--yes"), interactive=False)

    assert code == 0, text
    assert [m["name"] for m in _models((folder / "models_list.yaml").read_text())] == [
        "old-cloud",
        "mine",
    ]


def test_without_a_terminal_nothing_is_written_unless_yes(files):
    folder, certo = files

    code, text = _update(certo, interactive=False)

    assert code == 1
    assert (folder / "models_list.yaml").read_text() == _USER


def test_without_a_list_there_is_nothing_to_do(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty"))
    monkeypatch.chdir(tmp_path)

    code, text = _update(str(tmp_path / "x.yaml"))

    assert code == 0
    assert "you don't need one" in text


def test_certo_models_is_a_subcommand(monkeypatch):
    seen = []
    monkeypatch.setattr("certo.models_cmd.models_main", lambda argv: seen.append(argv) or 0)

    assert cli.main(["models", "update", "--yes"]) == 0
    assert seen == [["update", "--yes"]]
