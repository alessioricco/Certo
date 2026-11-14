"""Model files in layers: user folder, current folder, project folder,
merged by name (model_files.find_layers, model_catalog.merge_layer)."""

from __future__ import annotations

import io

import pytest

from certo.catalog_check import load_checked_catalog
from certo.model_catalog import LayeredPath, merge_layer
from certo.model_files import find, find_layers

_LIST = """models:
  - name: cheap
    model: anthropic/claude-haiku-5-5
    ratings: {reasoning: 3, code: 4, cost: 4}
  - name: strong
    model: anthropic/claude-opus-5-5
    ratings: {reasoning: 5, code: 5, cost: 2}
"""
_MODELS = """models:
  - name: cheap
    api_key: "${FAKE_KEY}"
  - name: strong
    api_key: "${FAKE_KEY}"
"""
_PROFILES = """task_profiles:
  build:
    triggers: [build]
    weights: {code: 3, cost: 3}
  default:
    weights: {cost: 1}
"""


@pytest.fixture
def folders(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_KEY", "sk-fake")
    for name in (
        "CERTO_MODELS_FILE",
        "CERTO_MODELS_LIST_FILE",
        "CERTO_TASK_PROFILES_FILE",
        "CERTO_ESCALATION_FILE",
    ):
        monkeypatch.delenv(name, raising=False)
    config = tmp_path / "config"
    user = config / "certo"
    user.mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    (user / "models_list.yaml").write_text(_LIST)
    (user / "models.yaml").write_text(_MODELS)
    (user / "task_profiles.yaml").write_text(_PROFILES)
    workspace = tmp_path / "workspace"
    project = workspace / "projects" / "game"
    project.mkdir(parents=True)
    monkeypatch.chdir(workspace)
    return user, workspace, project


def _active(catalog):
    return {m.name: m for m in catalog.models if m.activated}


def test_with_one_file_nothing_is_layered(folders):
    user, _, _ = folders

    path = find_layers("models_list.yaml")

    assert path == str(user / "models_list.yaml")
    assert not isinstance(path, LayeredPath)


def test_a_project_file_changes_one_rating_and_keeps_the_rest(folders):
    user, _, project = folders
    (project / "models_list.yaml").write_text("models:\n  - name: cheap\n    ratings: {code: 5}\n")

    catalog = load_checked_catalog(project_dir=str(project))

    cheap = _active(catalog)["cheap"]
    assert cheap.ratings == {"reasoning": 3, "code": 5, "cost": 4}
    assert cheap.model == "anthropic/claude-haiku-5-5"
    assert set(_active(catalog)) == {"cheap", "strong"}


def test_the_layers_go_user_then_current_folder_then_project(folders):
    user, workspace, project = folders
    (workspace / "models_list.yaml").write_text(
        "models:\n  - name: cheap\n    ratings: {code: 1}\n"
    )
    (project / "models_list.yaml").write_text("models:\n  - name: cheap\n    ratings: {code: 2}\n")

    path = find_layers("models_list.yaml", project_dir=str(project))

    assert path.layers == (
        str(user / "models_list.yaml"),
        str(workspace / "models_list.yaml"),
        str(project / "models_list.yaml"),
    )
    assert str(path) == str(project / "models_list.yaml")
    catalog = load_checked_catalog(project_dir=str(project))
    assert _active(catalog)["cheap"].ratings["code"] == 2


def test_a_project_can_turn_a_model_off_or_add_one(folders):
    _, _, project = folders
    (project / "models_list.yaml").write_text(
        "models:\n  - name: local\n    model: ollama/qwen3.8:27b\n    ratings: {code: 2, cost: 5}\n"
    )
    (project / "models.yaml").write_text(
        "models:\n  - name: strong\n    activated: false\n"
        "  - name: local\n    base_url: http://box:11434\n"
    )

    catalog = load_checked_catalog(project_dir=str(project))

    assert set(_active(catalog)) == {"cheap", "local"}
    assert _active(catalog)["cheap"].api_key == "sk-fake"  # the key comes from the user file


def test_replace_true_hides_the_layers_below(folders):
    _, _, project = folders
    (project / "models.yaml").write_text(
        'replace: true\nmodels:\n  - name: cheap\n    api_key: "${FAKE_KEY}"\n'
    )

    catalog = load_checked_catalog(project_dir=str(project))

    assert set(_active(catalog)) == {"cheap"}


def test_profiles_merge_by_name(folders):
    _, _, project = folders
    (project / "task_profiles.yaml").write_text(
        "task_profiles:\n  build:\n    triggers: [build, game]\n    weights: {code: 1}\n"
        "  docs:\n    triggers: [readme]\n    weights: {cost: 5}\n"
    )

    catalog = load_checked_catalog(project_dir=str(project))

    profiles = {p.name: p for p in catalog.task_profiles}
    assert set(profiles) == {"build", "default", "docs"}
    assert profiles["build"].triggers == ("build", "game")
    assert profiles["build"].weights == {"code": 1.0}


def test_a_comments_only_project_file_changes_nothing(folders):
    _, _, project = folders
    (project / "task_profiles.yaml").write_text("# nothing here yet\n")

    catalog = load_checked_catalog(project_dir=str(project))

    assert {p.name for p in catalog.task_profiles} == {"build", "default"}


def test_a_file_a_setting_names_is_read_alone(folders, monkeypatch, tmp_path):
    _, _, project = folders
    (project / "models_list.yaml").write_text("models:\n  - name: cheap\n    ratings: {code: 5}\n")
    only = tmp_path / "only.yaml"
    only.write_text(_LIST)

    assert find_layers("models_list.yaml", str(only), str(project)) == str(only)


def test_find_still_gives_the_top_file_to_edit(folders):
    _, _, project = folders
    (project / "models.yaml").write_text("models:\n  - name: cheap\n    activated: false\n")

    assert find("models.yaml", project_dir=str(project)) == str(project / "models.yaml")


def test_merge_layer_merges_ladders_by_name():
    base = {"escalation": {"max_rungs": 3, "ladders": {"a": [1], "b": [2]}}}
    over = {"escalation": {"ladders": {"b": [3]}}}

    assert merge_layer(base, over) == {
        "escalation": {"max_rungs": 3, "ladders": {"a": [1], "b": [3]}}
    }


def test_certo_check_shows_what_each_layer_changes(folders):
    from certo.catalog_report import _load_catalog

    user, _, project = folders
    (project / "models_list.yaml").write_text(
        "models:\n  - name: cheap\n    ratings: {code: 5}\n"
        "  - name: local\n    model: ollama/qwen3.8:27b\n    ratings: {code: 2}\n"
    )
    out = io.StringIO()

    _load_catalog(out, str(project))

    text = out.getvalue()
    assert f"  List: {user / 'models_list.yaml'}" in text
    assert f"    + {project / 'models_list.yaml'}: changes cheap; adds local" in text
