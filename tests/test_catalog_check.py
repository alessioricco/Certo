"""catalog_check.py: every error and warning, in plain words."""

from __future__ import annotations

import pytest
from model_file_helpers import write_split_model_files

from certo.catalog_check import check_catalog, load_checked_catalog, usable_rungs
from certo.model_catalog import ModelCatalogError, load_model_catalog

_MODELS = """
models:
  - name: local
    model: ollama/qwen3-coder:30b
    base_url: http://localhost:11434
    ratings: {reasoning: 2, code: 2, cost: 5}
  - name: mid
    model: openai/gpt-luna
    api_key: "${FAKE_KEY}"
    ratings: {reasoning: 3, code: 4, cost: 4}
  - name: strong
    model: anthropic/claude-sonnet
    api_key: "${FAKE_KEY}"
    ratings: {reasoning: 5, code: 5, cost: 2}
  - name: parked
    model: openai/gpt-old
    api_key: "${FAKE_KEY}"
    ratings: {reasoning: 1, code: 1, cost: 1}
    activated: false
task_profiles:
  default:
    weights: {reasoning: 1, code: 1, cost: 1}
"""


@pytest.fixture(autouse=True)
def _fake_key(monkeypatch):
    # Keys are named as ${NAME}; one written out gets its own warning.
    monkeypatch.setenv("FAKE_KEY", "sk-fake")


def _report(tmp_path, extra: str = "", models: str = _MODELS):
    # The layout since 0.1.20: profiles and ladders in their own files.
    return check_catalog(
        load_model_catalog(**write_split_model_files(tmp_path, models + extra), strict=False)
    )


def test_a_consistent_catalog_has_no_problems(tmp_path):
    report = _report(
        tmp_path,
        "escalation:\n  ladders:\n    default:\n      - model: local\n      - model: strong\n",
    )
    assert report.ok
    assert report.errors == []
    assert report.warnings == []


# --- errors ----------------------------------------------------------------------


def test_duplicate_model_names(tmp_path):
    report = _report(tmp_path, models=_MODELS.replace("name: mid", "name: local"))
    assert (
        "Two models in models_list.yaml are named 'local'. Model names must be unique."
        in report.errors
    )


def test_a_rung_naming_a_missing_model_lists_the_known_names(tmp_path):
    report = _report(tmp_path, "escalation:\n  ladders:\n    x:\n      - model: lokal\n")
    assert report.errors[0] == (
        "Ladder 'x', rung 1: there is no model named 'lokal'. Models: local, mid, strong, parked."
    )


def test_a_profile_naming_a_missing_model_is_an_error(tmp_path):
    report = _report(tmp_path, models=_MODELS.replace(
        "  default:\n", "  debugging:\n    triggers: [fix]\n    model: stronk\n  default:\n"
    ))  # fmt: skip
    assert (
        "Task profile 'debugging': there is no model named 'stronk'. "
        "Models: local, mid, strong, parked." in report.errors
    )


def test_a_profile_naming_a_disabled_model_is_a_warning(tmp_path):
    report = _report(tmp_path, models=_MODELS.replace(
        "  default:\n", "  debugging:\n    triggers: [fix]\n    model: parked\n  default:\n"
    ))  # fmt: skip
    assert report.ok
    assert (
        "Task profile 'debugging': parked isn't enabled in models.yaml, so tasks of this "
        "profile use the model its needs (or weights) rank first." in report.warnings
    )


def test_a_duplicate_rung(tmp_path):
    report = _report(
        tmp_path,
        "escalation:\n  ladders:\n    x:\n      - model: local\n      - model: local\n",
    )
    assert "Ladder 'x' lists local twice with the same settings." in report.errors


def test_the_same_model_with_a_different_reasoning_effort_is_not_a_duplicate(tmp_path):
    report = _report(
        tmp_path,
        "escalation:\n  ladders:\n    x:\n      - model: local\n"
        "      - model: local\n        reasoning_effort: max\n",
    )
    assert report.ok


def test_negative_retries(tmp_path):
    report = _report(
        tmp_path,
        "escalation:\n  ladders:\n    x:\n      - model: local\n        retries: -1\n"
        "      - model: strong\n",
    )
    assert "Ladder 'x', rung 1 (local): retries must be 0 or more, got -1." in report.errors


def test_a_cost_axis_no_model_is_rated_on(tmp_path):
    report = _report(tmp_path, "escalation:\n  cost_axis: price\n")
    assert report.errors[0].startswith(
        "escalation.cost_axis is 'price', but no model has a rating with that name."
    )


def test_the_default_cost_axis_is_not_required(tmp_path):
    models = _MODELS.replace(", cost: 5", "").replace(", cost: 4", "").replace(", cost: 2", "")
    assert _report(tmp_path, models=models.replace(", cost: 1", "")).ok


def test_a_ladder_with_only_inactive_models(tmp_path):
    report = _report(tmp_path, "escalation:\n  ladders:\n    x:\n      - model: parked\n")
    assert (
        "Ladder 'x' has no usable rung: none of its models is enabled in models.yaml."
        in report.errors
    )


def test_no_active_model_at_all(tmp_path):
    report = _report(
        tmp_path,
        models=_MODELS.replace(
            "    ratings: {reason", "    activated: false\n    ratings: {reason"
        ),
    )
    assert any(e.startswith("No model is enabled") for e in report.errors)


def test_load_checked_catalog_lists_every_error(tmp_path):
    files = write_split_model_files(
        tmp_path,
        _MODELS.replace("name: mid", "name: local")
        + "escalation:\n  ladders:\n    x:\n      - model: nope\n",
    )
    with pytest.raises(ModelCatalogError) as caught:
        load_checked_catalog(
            files["models_path"], files["list_path"], escalation_file=files["escalation_path"]
        )
    message = str(caught.value)
    assert "have 4 problem(s)" in message
    assert "models.yaml lists 'local' twice." in message
    assert "Two models in models_list.yaml are named 'local'" in message
    assert "no model named 'nope'" in message


# --- problems a mode doesn't use --------------------------------------------------

_BROKEN_LADDER = "escalation:\n  ladders:\n    x:\n      - model: parked\n"
_BROKEN_PROFILE = _MODELS.replace(
    "  default:\n", "  debugging:\n    triggers: [fix]\n    model: stronk\n  default:\n"
)


def _mode_report(tmp_path, mode, extra="", models=_MODELS):
    files = write_split_model_files(tmp_path, models + extra)
    return check_catalog(load_model_catalog(**files, strict=False), mode=mode)


def test_a_broken_ladder_does_not_stop_auto_model(tmp_path):
    # Seen live 2026-10-19: unusable ladders stopped an --auto-model run.
    report = _mode_report(tmp_path, "auto", _BROKEN_LADDER)
    assert report.ok
    assert (
        "Ladder 'x' has no usable rung: none of its models is enabled in models.yaml. "
        "Only --escalate uses ladders, so this run goes on." in report.warnings
    )


def test_a_broken_ladder_still_stops_escalate(tmp_path):
    report = _mode_report(tmp_path, "escalate", _BROKEN_LADDER)
    assert "Ladder 'x' has no usable rung: none of its models is enabled in models.yaml." in (
        report.errors
    )


def test_a_broken_profile_does_not_stop_escalate(tmp_path):
    report = _mode_report(tmp_path, "escalate", models=_BROKEN_PROFILE)
    assert report.ok
    assert (
        "Task profile 'debugging': there is no model named 'stronk'. "
        "Models: local, mid, strong, parked. "
        "Only --auto-model uses task profiles, so this run goes on." in report.warnings
    )


def test_a_broken_profile_still_stops_auto_model(tmp_path):
    report = _mode_report(tmp_path, "auto", models=_BROKEN_PROFILE)
    assert not report.ok


def test_a_problem_both_modes_share_stops_either(tmp_path):
    duplicated = _MODELS.replace("name: mid", "name: local")
    for mode in ("auto", "escalate", None):
        (tmp_path / str(mode)).mkdir()
        assert not _mode_report(tmp_path / str(mode), mode, models=duplicated).ok


def test_load_checked_catalog_passes_the_mode_on(tmp_path):
    files = write_split_model_files(tmp_path, _MODELS + _BROKEN_LADDER)
    args = (files["models_path"], files["list_path"])
    kwargs = {"escalation_file": files["escalation_path"]}
    seen = []
    load_checked_catalog(*args, **kwargs, on_warning=seen.append, mode="auto")
    assert any("Only --escalate uses ladders" in w for w in seen)
    with pytest.raises(ModelCatalogError):
        load_checked_catalog(*args, **kwargs)


# --- warnings --------------------------------------------------------------------


def test_a_rung_pointing_at_an_inactive_model_is_skipped(tmp_path):
    report = _report(
        tmp_path,
        "escalation:\n  ladders:\n    x:\n      - model: parked\n"
        "      - model: local\n      - model: strong\n",
    )
    assert report.ok
    assert report.warnings == [
        "Ladder 'x', rung 1: parked has 'activated: false', so this rung is skipped."
    ]


def test_a_ladder_with_a_single_usable_rung(tmp_path):
    report = _report(
        tmp_path, "escalation:\n  ladders:\n    x:\n      - model: local\n      - model: parked\n"
    )
    assert "Ladder 'x' has only one usable rung (local), so it can't escalate." in report.warnings


def test_a_missing_rating_on_a_weighed_axis(tmp_path):
    report = _report(
        tmp_path, models=_MODELS.replace("{reasoning: 3, code: 4, cost: 4}", "{code: 4, cost: 4}")
    )
    assert (
        "Model 'mid' has no rating for reasoning, which task profile(s) default weigh: "
        "it counts as 0."
    ) in report.warnings


def test_an_inactive_model_is_not_warned_about(tmp_path):
    models = _MODELS.replace("{reasoning: 1, code: 1, cost: 1}", "{}").replace(
        '    model: openai/gpt-old\n    api_key: "${FAKE_KEY}"\n', "    model: openai/gpt-old\n"
    )
    assert _report(tmp_path, models=models).warnings == []


def test_no_key_and_no_base_url(tmp_path):
    report = _report(
        tmp_path,
        models=_MODELS.replace(
            '    model: openai/gpt-luna\n    api_key: "${FAKE_KEY}"\n',
            "    model: openai/gpt-luna\n",
        ),
    )
    assert report.warnings == [
        (
            "Model 'mid' has no api_key and no base_url: it works only if the provider's own "
            "key variable (such as OPENAI_API_KEY) is set."
        )
    ]


def test_a_ladder_whose_capability_goes_down(tmp_path):
    report = _report(
        tmp_path, "escalation:\n  ladders:\n    x:\n      - model: strong\n      - model: local\n"
    )
    assert report.ok
    assert report.warnings == [
        (
            "Ladder 'x': local (capability 4) comes after strong (capability 10) but is rated "
            "less capable. Allowed, but check the order."
        )
    ]


def test_warnings_reach_the_callback(tmp_path):
    files = write_split_model_files(
        tmp_path,
        _MODELS + "escalation:\n  ladders:\n    x:\n      - model: strong\n      - model: local\n",
    )
    seen: list[str] = []
    catalog = load_checked_catalog(
        files["models_path"],
        files["list_path"],
        task_profiles_file=files["profiles_path"],
        escalation_file=files["escalation_path"],
        on_warning=seen.append,
    )
    assert len(seen) == 1
    assert [r.model for r in usable_rungs(catalog.escalation.ladders["x"], catalog)] == [
        "strong",
        "local",
    ]


def test_a_rung_on_a_model_not_in_models_yaml_is_skipped(tmp_path):
    from certo.model_catalog import load_model_catalog as load

    files = write_split_model_files(
        tmp_path,
        _MODELS + "escalation:\n  ladders:\n    x:\n      - model: local\n      - model: strong\n"
        "      - model: mid\n",
    )
    list_path, models_path = files["list_path"], files["models_path"]
    # Drop 'mid' from models.yaml: it stays in the list only.
    from pathlib import Path

    personal = Path(models_path)
    personal.write_text(personal.read_text().replace("- name: mid\n  api_key: ${FAKE_KEY}\n", ""))
    report = check_catalog(
        load(list_path, models_path, escalation_path=files["escalation_path"], strict=False)
    )
    assert "Ladder 'x', rung 3: mid isn't in models.yaml, so this rung is skipped." in (
        report.warnings
    )


def test_a_key_written_out_in_models_yaml_is_warned_about(tmp_path):
    models = _MODELS.replace('    api_key: "${FAKE_KEY}"\n', "    api_key: sk-written-out\n", 1)

    warnings = _report(tmp_path, models=models).warnings

    assert warnings == [
        "models.yaml: 'mid' has its API key written out in the file. Run \"certo models "
        'secure" to move it to your settings file and name it there as ${NAME}.'
    ]
    assert not any("sk-written-out" in w for w in warnings)
