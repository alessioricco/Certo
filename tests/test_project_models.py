"""A project's own model choice: certo-models.yaml (project_models.py,
models_choose.py, `certo models choose`, and the catalog's `use:` filter).
No model is called."""

from __future__ import annotations

import io

import pytest
import yaml
from model_file_helpers import write_model_files

from certo.api import RunOptions, resolve_config
from certo.config import Config, ConfigError
from certo.init_cmd import Prompter
from certo.model_catalog import PROJECT_FILE, load_model_catalog, rank_candidates
from certo.models_choose import cost_first, propose, recommend, render
from certo.models_cmd import models_main
from certo.project_models import apply_project_models

_MODELS = """
models:
  - name: local
    model: ollama/qwen3.8:27b
    base_url: http://box:11434
    ratings: {reasoning: 3, precision: 3, code: 2, cost: 5}
  - name: cheap
    model: anthropic/claude-haiku-5-5
    api_key: "${FAKE_KEY}"
    ratings: {reasoning: 3, precision: 3, code: 4, cost: 4}
  - name: mid
    model: openai/gpt-6.1-terra
    api_key: "${FAKE_KEY}"
    ratings: {reasoning: 4, precision: 4, code: 4, cost: 3}
  - name: strong
    model: anthropic/claude-opus-5-5
    api_key: "${FAKE_KEY}"
    ratings: {reasoning: 5, precision: 5, code: 5, cost: 2}
"""


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("FAKE_KEY", "sk-fake")
    monkeypatch.delenv("CERTO_MODEL_SELECTION", raising=False)


@pytest.fixture
def files(tmp_path):
    list_path, models_path = write_model_files(tmp_path, _MODELS)
    return list_path, models_path


def _catalog(files, **kw):
    return load_model_catalog(files[0], files[1], strict=False, **kw)


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


# --- the proposal ----------------------------------------------------------


def test_cost_first_puts_cost_above_the_other_axes_together():
    assert cost_first({"code": 3, "reasoning": 0.5, "precision": 0.5, "cost": 3}) == {
        "code": 3,
        "reasoning": 0.5,
        "precision": 0.5,
        "cost": 5.0,
    }
    assert cost_first({"code": 1, "cost": 6}) == {"code": 1, "cost": 6}


def test_the_proposed_orders_start_with_the_least_costly_model_that_fits(files):
    proposal = propose(_catalog(files), ["local", "cheap", "mid", "strong"])

    # build needs code 4: local (code 2) doesn't fit, so it comes last.
    assert proposal.orders["build"] == ["cheap", "mid", "strong", "local"]
    # architecture needs reasoning 5: only strong fits.
    assert proposal.orders["architecture"][0] == "strong"


def test_escalation_is_recommended_when_the_ladder_starts_much_cheaper(files):
    proposal = propose(_catalog(files), ["local", "strong"])

    assert proposal.recommended == "escalate"
    assert [r.name for r in proposal.ladder.rungs] == ["local", "strong"]


def test_auto_is_recommended_when_the_models_are_close_in_price(files):
    proposal = propose(_catalog(files), ["cheap", "mid"])

    assert proposal.recommended == "auto"


def test_recommend_without_a_ladder_says_auto():
    assert recommend(None)[0] == "auto"


def test_the_written_file_reads_back_as_profiles_ladder_and_use(files, tmp_path):
    proposal = propose(_catalog(files), ["cheap", "strong"])
    path = tmp_path / "proj" / PROJECT_FILE
    path.parent.mkdir()
    path.write_text(render(["cheap", "strong"], "auto", proposal))

    catalog = _catalog(files, profiles_path=str(path), escalation_path=str(path))

    assert {m.name for m in catalog.models if m.activated} == {"cheap", "strong"}
    assert [p.name for p in catalog.task_profiles][-1] == "default"
    assert [r.model for r in catalog.escalation.ladders["default"].rungs] == ["cheap", "strong"]
    weights = catalog.task_profiles[-1].weights
    assert [m.name for m in rank_candidates(catalog, weights)] == ["cheap", "strong"]
    assert "sk-fake" not in path.read_text()


def test_a_used_model_that_isnt_enabled_is_warned_about(files, tmp_path):
    path = tmp_path / PROJECT_FILE
    path.write_text("use: [cheap, nowhere]\nstrategy: auto\n")

    catalog = _catalog(files, profiles_path=str(path))

    assert any("'nowhere'" in w for w in catalog.load_warnings)
    assert {m.name for m in catalog.models if m.activated} == {"cheap"}


# --- applying it to a run ----------------------------------------------------


def test_the_project_file_sets_the_strategy_and_the_files(tmp_path):
    (tmp_path / PROJECT_FILE).write_text("use: [cheap]\nstrategy: escalate\n")

    cfg = apply_project_models(_cfg(), str(tmp_path), mode_chosen=False, environ={})

    assert cfg.model_selection == "escalate"
    assert cfg.task_profiles_file == cfg.escalation_file == str(tmp_path / PROJECT_FILE)


def test_a_flag_or_the_setting_wins_over_the_project_strategy(tmp_path):
    (tmp_path / PROJECT_FILE).write_text("strategy: escalate\n")

    flagged = apply_project_models(_cfg(), str(tmp_path), mode_chosen=True, environ={})
    set_ = apply_project_models(
        _cfg(), str(tmp_path), mode_chosen=False, environ={"CERTO_MODEL_SELECTION": "manual"}
    )

    assert flagged.model_selection == set_.model_selection == "manual"


def test_a_file_a_setting_names_is_kept(tmp_path):
    (tmp_path / PROJECT_FILE).write_text("strategy: auto\n")

    cfg = apply_project_models(
        _cfg(task_profiles_file="/mine.yaml"), str(tmp_path), mode_chosen=False, environ={}
    )

    assert cfg.task_profiles_file == "/mine.yaml"


def test_a_wrong_strategy_is_a_configuration_error(tmp_path):
    (tmp_path / PROJECT_FILE).write_text("strategy: fastest\n")

    with pytest.raises(ConfigError, match="'strategy' must be one of auto, escalate"):
        apply_project_models(_cfg(), str(tmp_path), mode_chosen=False, environ={})


def test_without_the_file_nothing_changes(tmp_path):
    assert apply_project_models(_cfg(), str(tmp_path), mode_chosen=False, environ={}) == _cfg()


def test_a_run_with_project_reads_the_file_in_that_project(tmp_path):
    project = tmp_path / "projects" / "game"
    project.mkdir(parents=True)
    (project / PROJECT_FILE).write_text("strategy: auto\n")

    cfg = resolve_config(
        RunOptions(project="game"), load=lambda: _cfg(projects_dir=str(tmp_path / "projects"))
    )

    assert cfg.model_selection == "auto"
    assert cfg.task_profiles_file == str(project / PROJECT_FILE)


# --- certo models choose ------------------------------------------------------


def _choose(argv, monkeypatch, files, folder, interactive=False):
    monkeypatch.setenv("CERTO_MODELS_LIST_FILE", files[0])
    monkeypatch.setenv("CERTO_MODELS_FILE", files[1])
    monkeypatch.setenv("CERTO_WORKSPACE", str(folder))
    out = io.StringIO()
    code = models_main(["choose", *argv], prompter=Prompter(out=out), interactive=interactive)
    return code, out.getvalue()


def test_choose_writes_the_project_file(monkeypatch, files, tmp_path):
    folder = tmp_path / "work"
    folder.mkdir()

    code, output = _choose(["--use", "cheap,strong", "--yes"], monkeypatch, files, folder)

    assert code == 0, output
    data = yaml.safe_load((folder / PROJECT_FILE).read_text())
    assert data["use"] == ["cheap", "strong"]
    assert data["strategy"] in ("auto", "escalate")
    assert "Recommended:" in output
    assert "sk-fake" not in output


def test_choose_without_yes_writes_nothing(monkeypatch, files, tmp_path):
    code, output = _choose(["--use", "cheap,strong"], monkeypatch, files, tmp_path)

    assert code == 1
    assert not (tmp_path / PROJECT_FILE).exists()


def test_choose_refuses_a_model_that_isnt_enabled(monkeypatch, files, tmp_path):
    code, output = _choose(["--use", "cheap,ghost", "--yes"], monkeypatch, files, tmp_path)

    assert code == 1
    assert "ghost" in output


def test_choose_needs_two_models(monkeypatch, files, tmp_path):
    code, output = _choose(["--use", "cheap", "--yes"], monkeypatch, files, tmp_path)

    assert code == 1
    assert "at least two" in output


def test_choose_by_numbers_on_a_terminal(monkeypatch, files, tmp_path):
    answers = iter(["2 4", "", ""])  # tick cheap and strong; Enter; default strategy
    monkeypatch.setattr(Prompter, "ask", lambda self, q, default=None: next(answers))
    monkeypatch.setattr(Prompter, "confirm", lambda self, q: True)
    monkeypatch.setattr(Prompter, "choose", lambda self, q, options, default=0: default)
    monkeypatch.setattr(Prompter, "menus", False, raising=False)

    code, output = _choose([], monkeypatch, files, tmp_path, interactive=True)

    assert code == 0, output
    assert yaml.safe_load((tmp_path / PROJECT_FILE).read_text())["use"] == ["cheap", "strong"]


def test_certo_check_shows_the_project_choice(monkeypatch, files, tmp_path):
    from certo.catalog_report import _load_catalog

    monkeypatch.setenv("CERTO_MODELS_LIST_FILE", files[0])
    monkeypatch.setenv("CERTO_MODELS_FILE", files[1])
    monkeypatch.setenv("CERTO_WORKSPACE", str(tmp_path))
    (tmp_path / PROJECT_FILE).write_text("use: [cheap, strong]\nstrategy: escalate\n")
    out = io.StringIO()

    catalog = _load_catalog(out)

    assert f"Project choice: {tmp_path / PROJECT_FILE} (strategy: escalate)" in out.getvalue()
    assert {m.name for m in catalog.models if m.activated} == {"cheap", "strong"}


# --- the fingerprint: choose rewrites its own sections, asks about yours ----


def _written(folder):
    return yaml.safe_load((folder / PROJECT_FILE).read_text())


def _edit_ladder(folder, rungs):
    data = _written(folder)
    data["escalation"]["ladders"]["default"] = [{"model": r} for r in rungs]
    (folder / PROJECT_FILE).write_text(yaml.safe_dump(data, sort_keys=False))


def test_an_untouched_ladder_is_rewritten_without_asking(monkeypatch, files, tmp_path):
    _choose(["--use", "cheap,strong", "--yes"], monkeypatch, files, tmp_path)
    first = _written(tmp_path)
    assert first["generated"]

    code, output = _choose(["--use", "cheap,mid,strong", "--yes"], monkeypatch, files, tmp_path)

    assert code == 0, output
    assert "edited by hand" not in output
    data = _written(tmp_path)
    assert [r["model"] for r in data["escalation"]["ladders"]["default"]][-1] == "strong"
    assert data["use"] == ["cheap", "mid", "strong"] and data["generated"] != first["generated"]


def test_an_edited_ladder_is_kept_with_yes_and_the_difference_shown(monkeypatch, files, tmp_path):
    _choose(["--use", "cheap,strong", "--yes"], monkeypatch, files, tmp_path)
    _edit_ladder(tmp_path, ["strong"])

    code, output = _choose(["--use", "cheap,mid,strong", "--yes"], monkeypatch, files, tmp_path)

    assert code == 0, output
    assert "edited by hand, or written by an earlier Certo" in output
    assert "--- yours" in output and "+    - {model: cheap}" in output
    assert "--replace-edits replaces them" in output
    data = _written(tmp_path)
    assert data["escalation"]["ladders"]["default"] == [{"model": "strong"}]
    assert data["use"] == ["cheap", "mid", "strong"]  # the choice itself still changes
    # Still edited next time: its old fingerprint was kept.
    _, again = _choose(["--use", "cheap,strong", "--yes"], monkeypatch, files, tmp_path)
    assert "edited by hand" in again


def test_replace_edits_writes_the_new_ladder(monkeypatch, files, tmp_path):
    _choose(["--use", "cheap,strong", "--yes"], monkeypatch, files, tmp_path)
    _edit_ladder(tmp_path, ["strong"])

    code, output = _choose(
        ["--use", "cheap,strong", "--yes", "--replace-edits"], monkeypatch, files, tmp_path
    )

    assert code == 0, output
    assert _written(tmp_path)["escalation"]["ladders"]["default"] != [{"model": "strong"}]
    _, again = _choose(["--use", "cheap,strong", "--yes"], monkeypatch, files, tmp_path)
    assert "edited by hand" not in again


def test_on_a_terminal_the_author_chooses_to_replace_or_cancel(monkeypatch, files, tmp_path):
    _choose(["--use", "cheap,strong", "--yes"], monkeypatch, files, tmp_path)
    _edit_ladder(tmp_path, ["strong"])
    monkeypatch.setattr(Prompter, "confirm", lambda self, q: True)
    monkeypatch.setattr(Prompter, "menus", False, raising=False)

    picks = iter([2])  # Cancel
    monkeypatch.setattr(Prompter, "choose", lambda self, q, options, default=0: next(picks))
    code, output = _choose(
        ["--use", "cheap,strong", "--strategy", "auto"], monkeypatch, files, tmp_path, True
    )
    assert code == 1 and "Nothing was written." in output
    assert _written(tmp_path)["escalation"]["ladders"]["default"] == [{"model": "strong"}]

    picks = iter([1])  # Replace them
    monkeypatch.setattr(Prompter, "choose", lambda self, q, options, default=0: next(picks))
    code, output = _choose(
        ["--use", "cheap,strong", "--strategy", "auto"], monkeypatch, files, tmp_path, True
    )
    assert code == 0, output
    assert _written(tmp_path)["escalation"]["ladders"]["default"] != [{"model": "strong"}]


def test_a_file_from_before_the_fingerprint_with_the_same_sections_gets_one(
    monkeypatch, files, tmp_path
):
    _choose(["--use", "cheap,strong", "--yes"], monkeypatch, files, tmp_path)
    data = _written(tmp_path)
    del data["generated"]
    (tmp_path / PROJECT_FILE).write_text(yaml.safe_dump(data, sort_keys=False))

    code, output = _choose(["--use", "cheap,strong", "--yes"], monkeypatch, files, tmp_path)

    assert code == 0 and "edited by hand" not in output
    assert _written(tmp_path)["generated"]
